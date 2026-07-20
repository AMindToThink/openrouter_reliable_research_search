"""Integrity checks for the interactive explorer before it gets published.

The explorer is the project's most-shared deliverable and it is a single generated file, so
nothing but these checks stands between a bad edit and a broken published page.

Written after a real one: `users` was read one line above its own `const` declaration in the
stats IIFE — a temporal-dead-zone ReferenceError. Because every widget lives in one classic
<script> block, that single throw aborted the rest of it, so the stats, chart, repo list and
Routing Roulette all silently failed to render. It shipped into a branch and survived a merge
because nothing ever executed the page.

    uv run pytest tests/test_artifact_page.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "artifact" / "index_template.html"
PAGE = ROOT / "artifact" / "index.html"
DATA = ROOT / "artifact" / "_data.json"
PLACEHOLDER = "/*__DATA__*/[]"


@pytest.fixture(scope="module")
def template() -> str:
    return TEMPLATE.read_text()


@pytest.fixture(scope="module")
def page() -> str:
    return PAGE.read_text()


def script_body(html: str) -> str:
    m = re.search(r"<script>(.*)</script>", html, re.S)
    assert m, "no <script> block found"
    return m.group(1)


# --- the page is publishable as an Artifact ---------------------------------------

@pytest.mark.parametrize("tag", ["<!doctype", "<html", "<body", "</body>", "</html>"])
def test_page_has_no_document_wrapper(page: str, tag: str) -> None:
    """Artifacts are wrapped in their own skeleton; our own wrapper would nest documents."""
    assert tag not in page.lower()


def test_page_starts_with_a_title(page: str) -> None:
    assert page.lstrip().startswith("<title>"), "the <title> names the artifact in the gallery"


def test_page_has_exactly_one_script_block(page: str) -> None:
    assert page.count("<script>") == 1 and page.count("</script>") == 1


def test_no_external_resources(page: str) -> None:
    """A strict CSP blocks every external host — the page must be self-contained."""
    for pattern in (r'<script[^>]+src=', r'<link[^>]+href="https?://',
                    r'@import\s+url\(', r'https?://[^"\')\s]+\.(?:js|css|woff2?)'):
        assert not re.search(pattern, page, re.I), f"external resource matched {pattern!r}"


def test_embedded_data_cannot_break_out_of_the_script(page: str) -> None:
    body = script_body(page)
    for bad in ("</script", "<!--", "]]>"):
        assert bad not in body, f"{bad!r} inside the script block would terminate it early"


# --- the generated page matches the template and the data -------------------------

def test_page_is_in_sync_with_template_and_data(template: str, page: str) -> None:
    """index.html is generated — a hand-edit here would be silently overwritten."""
    expected = template.replace(PLACEHOLDER, DATA.read_text().strip())
    assert page == expected, (
        "artifact/index.html is stale or hand-edited — regenerate with "
        "`uv run scripts/set_safety_class.py`"
    )


def test_template_keeps_its_data_placeholder(template: str) -> None:
    assert template.count(PLACEHOLDER) == 1


def test_embedded_rows_match_the_survey(page: str) -> None:
    rows = json.loads(DATA.read_text())
    survey = json.loads((ROOT / "findings" / "survey.json").read_text())["rows"]
    assert len(rows) == len(survey)
    assert all(r.get("safety_class") for r in rows), "every card needs a verdict to render"


# --- no use-before-declaration (the bug that broke the page) ----------------------

DECL = re.compile(r"^\s*(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=", re.M)


def _blank(s: str) -> str:
    """Replace every character with a space, keeping newlines so offsets and lines survive."""
    return "".join("\n" if ch == "\n" else " " for ch in s)


def strip_strings_and_comments(src: str) -> str:
    """Blank out comment and string content so identifier scans can't match inside them.

    Template-literal interpolations (`${...}`) are kept verbatim — real code lives there,
    and the explorer builds all of its markup that way. Length is preserved exactly so
    reported line numbers still point at the source.
    """
    out: list[str] = []
    i, n = 0, len(src)
    while i < n:
        two = src[i:i + 2]
        if two == "//":
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(_blank(src[i:j])); i = j
        elif two == "/*":
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(_blank(src[i:j])); i = j
        elif src[i] in "'\"":
            quote, j = src[i], i + 1
            while j < n and src[j] != quote:
                j += 2 if src[j] == "\\" else 1
            j = min(j + 1, n)
            out.append(_blank(src[i:j])); i = j
        elif src[i] == "`":
            j = i + 1
            out.append(" ")
            while j < n and src[j] != "`":
                if src[j] == "\\":
                    out.append("  "); j += 2
                elif src[j:j + 2] == "${":
                    depth, k = 1, j + 2
                    while k < n and depth:
                        depth += (src[k] == "{") - (src[k] == "}")
                        k += 1
                    out.append("  " + src[j + 2:k - 1] + " ")  # drop ${ and }, keep the code
                    j = k
                else:
                    out.append("\n" if src[j] == "\n" else " "); j += 1
            out.append(" "); i = min(j + 1, n)
        else:
            out.append(src[i]); i += 1
    return "".join(out)


def test_stripper_preserves_offsets_and_removes_literals() -> None:
    """The scan below is only trustworthy if this helper is."""
    src = 'const a = "high";\n// users\nconst b = `x${ y }z`;'
    stripped = strip_strings_and_comments(src)
    assert len(stripped) == len(src), "offsets must survive so line numbers stay correct"
    assert "high" not in stripped and "users" not in stripped
    assert "y" in stripped, "interpolated code must be kept"
    assert stripped.count("\n") == src.count("\n")


def stats_iife(body: str) -> str:
    """The leading `(function(){ ... })();` that computes and renders the stat cards.

    Scoped deliberately. This block runs at the very top of the script, so a throw here
    aborts everything after it — chart, repo list, roulette. It is also flat enough for a
    text-level scan to be trustworthy, which the rest of the script (nested template
    literals building markup) is not.
    """
    start = body.index("(function(){")
    end = body.index("})();", start)
    return body[start:end]


def test_no_const_or_let_is_used_before_it_is_declared(template: str) -> None:
    """Catches the temporal-dead-zone bug that silently killed the whole script.

    Deliberately narrow: the stats IIFE only, `const`/`let` at the start of a line only,
    first textual occurrence only. `function` declarations are excluded because they hoist,
    and single-character names are skipped as nested loop variables. This is a lint, not a
    substitute for running the page — see the module docstring.
    """
    body = stats_iife(strip_strings_and_comments(script_body(template)))
    offenders: list[str] = []
    for m in DECL.finditer(body):
        name = m.group(1)
        if len(name) < 2:
            continue
        # `\b` does not work for names containing `$`, so bound on identifier characters.
        first = re.search(rf"(?<![\w$]){re.escape(name)}(?![\w$])", body)
        assert first is not None, f"declared name {name!r} not found in the script body"
        if first.start() < m.start(1):
            line = body[:first.start()].count("\n") + 1
            decl_line = body[:m.start(1)].count("\n") + 1
            offenders.append(f"{name!r} used on line {line} but declared on line {decl_line}")
    assert not offenders, (
        "use-before-declaration in the artifact script (throws ReferenceError at runtime, "
        "aborting the rest of the block):\n  " + "\n  ".join(offenders)
    )


def test_stats_iife_computes_the_tally_before_rendering(template: str) -> None:
    """Pin the specific ordering that broke: the tally must precede the DOM write.

    The lede number has since moved from `users` (any call site) to `onPath` (OpenRouter
    reaches a published result); the ordering requirement is what matters, not the name.
    """
    body = script_body(template)
    written = re.search(r"_u\.textContent\s*=\s*([A-Za-z_$][\w$]*)", body)
    assert written, "the lede count is no longer written from a variable — update this test"
    name = written.group(1)
    decl = body.find(f"const {name} =")
    assert decl != -1, f"lede is rendered from {name!r}, which is never declared with const"
    assert decl < written.start(), f"`{name}` must be computed before it is written into the lede"
