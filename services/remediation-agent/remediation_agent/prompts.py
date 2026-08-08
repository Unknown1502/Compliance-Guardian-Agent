"""Gemini prompt for the Remediation Agent.

Separate from the Compliance Agent's prompt on purpose. Compliance answers
"is this wrong, and against which rule?"; remediation answers "what do I do
about it?". Merging them tempts the model to soften a verdict to make the fix
sound easier, which is exactly the failure a compliance product cannot have.
"""

from __future__ import annotations

REMEDIATION_PROMPT_VERSION = "remediation_v1"

REMEDIATION_SYSTEM_INSTRUCTION = """You are a compliance remediation advisor for small businesses.

You are given rules that a document FAILED, with the reason each failed. For
each one, write the concrete action the business should take to fix it.

Rules you must follow:
- Address ONLY the rule ids provided. Never invent a rule, a citation, or a
  requirement that was not given to you.
- Write for a busy operations person with no compliance training. Plain
  language, imperative voice: "Attach the signed consent form", not "Consent
  documentation should be considered".
- Be specific to the failure reason you were given. A generic "review your
  records" is useless.
- estimated_minutes is a realistic estimate of hands-on time for one person.
- blocking = true only when the document genuinely cannot be relied upon until
  it is fixed. Do not mark everything blocking; an inflated list gets ignored.
- Never state or imply legal advice, certification, or a guarantee of
  compliance. You describe steps against cited rules, nothing more.

Return STRICT JSON only:
{
  "items": [
    {
      "rule_id": "<one of the provided rule ids>",
      "title": "<short imperative summary, under 80 characters>",
      "action": "<what to do, 1-3 sentences>",
      "blocking": true|false,
      "estimated_minutes": <integer>
    }
  ]
}"""

# Documents can be long and this call is per-check, so the extract handed to
# the model is capped. The failure reasons carry the substance; the extract is
# only there for context.
MAX_EXTRACT_CHARS = 2000


def build_remediation_user_prompt(
    *, failures: list[dict], document_extract: str, industry: str, jurisdiction: str
) -> str:
    """Compose the user prompt from failed rules plus a trimmed document extract."""
    lines = [
        f"Industry: {industry}",
        f"Jurisdiction: {jurisdiction}",
        "",
        "Rules this document FAILED:",
    ]
    for f in failures:
        lines.append(
            f"- rule_id: {f['rule_id']}\n"
            f"  severity: {f.get('severity', 'unknown')}\n"
            f"  requirement: {f.get('description', '(no description)')}\n"
            f"  why it failed: {f.get('explanation', '(no explanation)')}"
        )
        if f.get("triggering_data_point"):
            lines.append(f"  data point that triggered it: {f['triggering_data_point']}")

    extract = (document_extract or "").strip()
    if extract:
        lines += ["", "Relevant document content (may be truncated):", extract[:MAX_EXTRACT_CHARS]]

    lines += ["", "Produce one remediation item per failed rule id above."]
    return "\n".join(lines)
