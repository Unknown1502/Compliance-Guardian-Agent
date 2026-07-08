"""Versioned prompts for the Compliance Agent.

Same versioning discipline as ingestion: never edit a released version's text;
add a new version and switch CURRENT. The version is persisted with every
compliance_check for reproducibility.
"""

from __future__ import annotations

import json

from schema_validators import RuleSet

COMPLIANCE_PROMPT_VERSION = "compliance_v1"

COMPLIANCE_SYSTEM_INSTRUCTION = (
    "You are a compliance risk analyst for small businesses. You evaluate "
    "extracted document data against an explicit, provided ruleset. You are "
    "rigorous and conservative: when the data is ambiguous or missing for a "
    "rule, you mark that rule 'uncertain' rather than guessing. You NEVER cite "
    "a rule that was not explicitly provided to you, and you NEVER fabricate a "
    "data point. You return strict JSON only."
)


def _serialize_rules(ruleset: RuleSet) -> str:
    return json.dumps(
        [
            {
                "id": r.id,
                "description": r.description,
                "check_type": r.check_type.value,
                "severity": r.severity.value,
                "params": r.params,
            }
            for r in ruleset.rules
        ],
        indent=2,
    )


def build_compliance_user_prompt(*, ruleset: RuleSet, extracted_fields: dict) -> str:
    """Render the compliance evaluation instruction for one document."""
    rules_json = _serialize_rules(ruleset)
    data_json = json.dumps(extracted_fields, indent=2, default=str)
    valid_ids = ", ".join(sorted(ruleset.rule_ids()))
    return (
        f"Ruleset: {ruleset.industry}/{ruleset.jurisdiction} "
        f"version {ruleset.rule_set_version}\n\n"
        f"RULES (evaluate every one of these; cite ONLY these rule ids):\n"
        f"{rules_json}\n\n"
        f"EXTRACTED DATA from the document:\n{data_json}\n\n"
        f"For EACH rule, decide pass / fail / uncertain based ONLY on the "
        f"extracted data above:\n"
        f"  - pass: the data satisfies the rule.\n"
        f"  - fail: the data violates the rule.\n"
        f"  - uncertain: the data needed to decide is missing or ambiguous.\n\n"
        f"Return a strict JSON object with these keys:\n"
        f'  "rule_verdicts": array of objects, one per rule, each with:\n'
        f'      "rule_id" (must be one of: {valid_ids}),\n'
        f'      "status" ("pass" | "fail" | "uncertain"),\n'
        f'      "confidence" (number 0.0-1.0),\n'
        f'      "explanation" (one plain-language sentence a non-expert business '
        f"owner can understand),\n"
        f'      "triggering_data_point" (the exact field=value that drove the '
        f"decision, or null if the field was absent).\n"
        f'  "risk_score": integer 0-100, where 0 means fully compliant and 100 '
        f"means a severe violation. Weight critical/high severity failures much "
        f"more heavily than medium/low.\n"
        f'  "justification": a 2-4 sentence plain-language overall summary for '
        f"the business owner explaining the score.\n\n"
        f"Cite only rule ids from the provided list. Do not invent rules, "
        f"fields, or values."
    )
