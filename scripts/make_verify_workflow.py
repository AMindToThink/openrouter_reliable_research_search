#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Emit a verify-ONLY workflow for the rows still flagged `impact_verified: false`.

Why this exists: the original impacted-findings pass ran identify+verify (70 agents).
The identify results for every repo are already stored in findings/survey.json, so
re-verifying the stragglers only needs the *verify* stage — one agent per pending row.
Workflow `resumeFromRunId` is same-session only, so once a session ends the cheap way
to finish is this targeted script, not a resume.

Usage:
    uv run scripts/make_verify_workflow.py            # writes scripts/verify_pending.workflow.js
then, from Claude Code:
    Workflow({scriptPath: "<repo>/scripts/verify_pending.workflow.js"})
and merge the result with scripts/merge_verified.py.
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
rows = json.loads((ROOT / "findings/survey.json").read_text())["rows"]
pending = [r for r in rows if not r.get("impact_verified")]

payload = [{
    "title": r["title"],
    "repo_url": r.get("repo_url", ""),
    "paper_url": r.get("paper_url", ""),
    "code_url": r.get("code_url", ""),
    "venue": r.get("venue", ""),
    "uses_safely": bool(r.get("uses_safely")),
    "mistake_ids": r.get("mistake_ids") or [],
    "impacted_findings": r.get("impacted_findings") or [],
    "headline_impact": r.get("headline_impact", ""),
    "no_impact_reason": r.get("no_impact_reason", ""),
} for r in pending]

SCHEMA_AND_BODY = """
const IMPACT_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    impacted_findings: { type: 'array', items: { type: 'object', additionalProperties: false,
      properties: {
        finding: { type: 'string' }, locator: { type: 'string' }, mechanism: { type: 'string' },
        severity: { type: 'string', enum: ['high','medium','low'] },
        depends_on_or: { type: 'string', enum: ['high','medium','low'] },
      }, required: ['finding','locator','mechanism','severity','depends_on_or'] } },
    headline_impact: { type: 'string' },
    no_impact_reason: { type: 'string' },
  },
  required: ['impacted_findings','headline_impact'],
}

const VERIFY = (r) => `
Adversarially verify this "possibly-impacted findings" list for ${r.title}. Your job: strip
OVERCLAIMS and tighten. These findings came from a FIRST-PASS agent that has been observed to
invent plausible-looking numbers, so re-check every cited figure against the real source.

repo: ${r.repo_url}
paper/report: ${r.paper_url || '(none - use the README / linked report)'}
primary OpenRouter call site: ${r.code_url || r.repo_url}
our safety verdict: ${r.uses_safely ? 'SAFE' : 'AT RISK'} | mistakes: ${(r.mistake_ids||[]).join(', ')}

CANDIDATE LIST (JSON):
${JSON.stringify({impacted_findings: r.impacted_findings, headline_impact: r.headline_impact, no_impact_reason: r.no_impact_reason}, null, 2)}

CHECK each finding:
- Does the cited number/figure ACTUALLY EXIST in the paper/repo? Quote what you find. If it does
  not exist, DROP it (or replace it with the real number and say so).
- Does the result actually depend on OpenRouter-routed calls? (direct first-party API, local model,
  or proprietary single-served model with no quantization spread => downgrade depends_on_or or drop.)
- Is the mechanism the right M-id? Is severity honest?
Keep only findings that survive; you may ADD a clearly-missed one. Rewrite headline_impact to the
single most defensible impacted claim (or "none").

Use Bash ('gh api', 'git clone --depth 1'), WebFetch (paper/raw.githubusercontent) and WebSearch.
Do NOT spawn sub-agents. Return ONLY the schema object.
`

phase('Verify')
const out = await parallel(PENDING.map(r => () =>
  agent(VERIFY(r), { label: `verify:${(r.title||'').slice(0,36)}`, phase: 'Verify',
    model: 'sonnet', agentType: 'general-purpose', schema: IMPACT_SCHEMA })
    .then(v => v ? ({
      title: r.title, repo_url: r.repo_url,
      impacted_findings: v.impacted_findings || [],
      headline_impact: v.headline_impact || '',
      no_impact_reason: v.no_impact_reason || '',
      verified: true,
    }) : null)
))
const ok = out.filter(Boolean)
log(`verified ${ok.length}/${PENDING.length} pending rows`)
return { rows: ok }
"""

js = (
    "export const meta = {\n"
    "  name: 'openrouter-verify-pending',\n"
    "  description: 'Adversarially verify the impacted-findings rows still flagged impact_verified:false',\n"
    "  phases: [{ title: 'Verify', detail: 'one agent per pending repo; re-check every cited figure against source' }],\n"
    "}\n\n"
    f"const PENDING = {json.dumps(payload, ensure_ascii=False)};\n"
    + SCHEMA_AND_BODY
)

out = ROOT / "scripts/verify_pending.workflow.js"
out.write_text(js)
print(f"pending rows needing verification: {len(pending)}")
for r in pending:
    print(f"  - {r['title'][:64]}")
print(f"\nwrote {out.relative_to(ROOT)} ({len(js):,} bytes)")
print(f"run it with:  Workflow({{scriptPath: \"{out}\"}})")
