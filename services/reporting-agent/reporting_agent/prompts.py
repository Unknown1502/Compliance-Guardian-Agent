"""Versioned prompt for the Reporting Agent.

reporting_v1 matches the exact prompt from the spec verbatim.
To evolve: add reporting_v2, update CURRENT_REPORTING_PROMPT_VERSION, never
edit the v1 text (reproducibility of historical reports).
"""

from __future__ import annotations

import json
from datetime import datetime

REPORTING_PROMPT_VERSION = "reporting_v1"

REPORTING_SYSTEM_INSTRUCTION = (
    "You are a compliance reporting specialist helping small business owners "
    "understand their compliance posture. You write clearly and concisely, "
    "avoiding legal jargon. You base every statement on the data provided and "
    "never fabricate statistics. Return strict JSON only."
)


def build_reporting_user_prompt(
    *,
    period_start: datetime,
    period_end: datetime,
    stats: dict,
) -> str:
    """Render the reporting prompt for the spec's exact reporting_v1 prompt."""
    stats_json = json.dumps(stats, indent=2, default=str)
    return (
        f"Summarize the following compliance check results for the period "
        f"{period_start.date()} to {period_end.date()} into a professional "
        f"audit-ready report.\n\n"
        f"DATA:\n{stats_json}\n\n"
        f"Include ALL of these in your JSON response:\n"
        f'  "total_documents_processed": (integer from data),\n'
        f'  "pass_count": (integer),\n'
        f'  "fail_count": (integer — checks that were escalated or rejected),\n'
        f'  "escalated_count": (integer — still awaiting or was escalated),\n'
        f'  "top_3_risk_patterns": (array of up to 3 strings — the most commonly '
        f"cited failing rule ids across all checks, with a plain-English name),\n"
        f'  "executive_summary": (3-5 sentences in plain language suitable for a '
        f"small business owner with no compliance background. Start with an overall "
        f"assessment, mention the most critical finding if any, and give one "
        f"actionable next step. Do not cite rule ids directly — use their "
        f"descriptions from the data instead.)\n\n"
        f"Base every number exactly on the provided data. Do not round or estimate."
    )
