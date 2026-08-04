"""Agent-drafted outreach — AI-native operations, not just AI-native product.

Takes a prospect list and has Gemini draft a personalized outreach message for
each one (tone adapted to the channel: personal network / cold / community).
A human still reviews and sends every message — this script never sends
anything itself — but every draft is logged to the SAME append-only BigQuery
audit trail the compliance pipeline uses, under a reserved internal tenant_id
(tenant-complianceguardian-ops). That's what turns "we used AI to help with
outreach" from a claim into an exportable, timestamped execution log: exactly
the "agent execution logs" evidence the submission asks for, and a genuine
answer to "how is AI running your business, not just your product."

Usage:
    python scripts/agent_outreach.py scripts/prospects.example.json
    python scripts/agent_outreach.py scripts/prospects.example.json --out drafts.md

Requires GEMINI_API_KEY (from .env or the environment). To write real audit
rows you also need GOOGLE_CLOUD_PROJECT pointed at a real project (or the
BigQuery emulator running) — without either, pass --dry-run to see drafts
without touching BigQuery.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

import os  # noqa: E402


def _load_local_env() -> None:
    """Load compliance-agent/.env (gitignored) into os.environ if present.

    Same minimal parser as demo_phase2.py — kept local rather than shared so
    each standalone script has zero import-order surprises.
    """
    env_path = REPO_ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_local_env()

from audit_logger import AuditLogger  # noqa: E402
from gcp_clients import audit_dataset, audit_table, bigquery_client  # noqa: E402
from gemini_client import GeminiClient  # noqa: E402

OUTREACH_PROMPT_VERSION = "outreach_v1"
OPS_TENANT_ID = "tenant-complianceguardian-ops"

_CHANNEL_GUIDANCE = {
    "personal": (
        "This is someone the founder knows personally or through a warm "
        "introduction. Write like a real message to an acquaintance: casual, "
        "specific, no sales-pitch structure, one clear ask at the end."
    ),
    "cold": (
        "This is a cold outreach email to someone the founder has never met. "
        "Keep it short (under 120 words), lead with the concrete pain point, "
        "make the free-first-audit offer explicit, and end with a low-friction "
        "single question."
    ),
    "community": (
        "This is a post for an NDIS provider community (Facebook/LinkedIn "
        "group), not a direct message. Write in first person as the founder, "
        "genuine and non-salesy, inviting comments/DMs rather than demanding "
        "action."
    ),
}

SYSTEM_INSTRUCTION = (
    "You are the founder of ComplianceGuardian, an AI tool that runs NDIS "
    "compliance audits automatically: it checks service records against NDIS "
    "compliance rules and returns a citation-backed risk score with plain-"
    "language findings, instead of a manual review or a paid consultant "
    "engagement. You are drafting real outreach messages the founder will "
    "review and send personally. Never invent facts about the prospect beyond "
    "what is given. Never promise a specific price beyond 'the first audit is "
    "free'. Return strict JSON only."
)


def build_user_prompt(prospect: dict) -> str:
    channel = prospect.get("channel", "cold")
    guidance = _CHANNEL_GUIDANCE.get(channel, _CHANNEL_GUIDANCE["cold"])
    return (
        f"Prospect:\n{json.dumps(prospect, indent=2)}\n\n"
        f"Channel: {channel}\n{guidance}\n\n"
        'Return a strict JSON object with keys: "subject" (empty string if the '
        'channel is not email), "message" (the full drafted text).'
    )


def draft_for_prospect(gemini: GeminiClient, prospect: dict) -> dict:
    result = gemini.generate_json(
        prompt_version=OUTREACH_PROMPT_VERSION,
        system_instruction=SYSTEM_INSTRUCTION,
        user_content=build_user_prompt(prospect),
        temperature=0.6,
    )
    return result.data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prospects_file", help="JSON file: a list of {name, business_name, channel, notes}")
    parser.add_argument("--out", help="Write all drafts to this markdown file in addition to stdout")
    parser.add_argument(
        "--dry-run", action="store_true", help="Draft and print only — skip the BigQuery audit write"
    )
    args = parser.parse_args()

    prospects = json.loads(Path(args.prospects_file).read_text(encoding="utf-8"))
    gemini = GeminiClient()

    auditor = None
    if not args.dry_run:
        auditor = AuditLogger(bigquery_client(), audit_dataset(), audit_table())

    out_lines: list[str] = []
    for i, prospect in enumerate(prospects, 1):
        name = prospect.get("name", f"prospect-{i}")
        print(f"\n--- Drafting for {name} ({prospect.get('channel', 'cold')}) ---")
        draft = draft_for_prospect(gemini, prospect)
        subject = draft.get("subject", "")
        message = draft.get("message", "")
        if subject:
            print(f"Subject: {subject}")
        print(message)

        out_lines.append(f"## {name} ({prospect.get('channel', 'cold')})")
        if subject:
            out_lines.append(f"**Subject:** {subject}\n")
        out_lines.append(message + "\n")

        if auditor is not None:
            auditor.log(
                tenant_id=OPS_TENANT_ID,
                actor="outreach_agent",
                action="outreach.drafted",
                dedup_key=f"{name}:{prospect.get('channel', 'cold')}:{i}",
                after_state={
                    "prospect_name": name,
                    "business_name": prospect.get("business_name"),
                    "channel": prospect.get("channel", "cold"),
                    "subject": subject,
                    "message_preview": message[:280],
                },
            )
            print("  [logged to audit trail]")

    if args.out:
        Path(args.out).write_text("\n".join(out_lines), encoding="utf-8")
        print(f"\nAll drafts written to {args.out}")


if __name__ == "__main__":
    main()
