"""Seed a demo workspace with a realistic period of compliance activity.

The product demos badly on an empty workspace. Its central claim -- that the
model handles the routine cases and a named human decides the hard ones -- is
invisible unless there are both kinds on screen, in volume, over time.

This writes ~34 documents and checks across six weeks into ONE demo tenant,
using the real NDIS ruleset's rule ids so every verdict on screen corresponds
to an actual regulatory obligation. Findings are drawn from the obligations
that genuinely put an Australian provider at risk: reportable incidents lodged
outside the 24-hour window, restrictive practices used without authorisation,
a complaint describing neglect with no matching incident report.

Deliberately NOT a substitute for running real checks. It writes stored
records directly rather than calling Gemini, so it is fast, free and
deterministic -- the same demo every time you rehearse. Records carry
`demo_seeded: True` so they can be told apart from real activity and removed.

Idempotent: fixed ids, set() upserts. Re-running replaces rather than
duplicates.

    python scripts/seed_demo_activity.py            # seed
    python scripts/seed_demo_activity.py --wipe     # remove what it wrote
    python scripts/seed_demo_activity.py --tenant tenant-x --project my-proj
"""

from __future__ import annotations

import argparse
import hashlib
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

from google.cloud import firestore, storage  # noqa: E402

from schema_validators import (  # noqa: E402
    CheckDecision,
    ComplianceCheck,
    Document,
    DocumentStatus,
    GeminiCallMetadata,
    RuleVerdict,
    RuleVerdictStatus,
)

DEFAULT_PROJECT = "cg-guardian-9856"
DEFAULT_TENANT = "tenant-sunrise-care"
RAW_BUCKET_SUFFIX = "-cg-raw-docs"
RULE_SET_VERSION = "1.1.0"
MODEL_NAME = "gemini-3.1-flash-lite"
PROMPT_VERSION = "compliance_v1"
SEED_MARKER = "demo_seeded"

# A reviewer must be a real uid for the escalation queue to attribute a
# decision. Overridden by --reviewer-uid when the demo account differs.
DEFAULT_REVIEWER_UID = "demo-reviewer"
DEFAULT_REVIEWER_EMAIL = "quality.lead@sunrisecare.example"

PARTICIPANTS = [
    "A. Whitfield", "M. Okonkwo", "J. Brennan", "S. Nakamura", "L. Petrov",
    "R. Castellanos", "D. Ferreira", "H. Osei", "K. Lindqvist", "T. Rahman",
    "N. Delacroix", "P. Kowalski", "E. Mbeki", "C. Tanaka", "B. Andersen",
]

WORKERS = [
    "Support Worker 114", "Support Worker 231", "Support Worker 087",
    "Support Worker 342", "Support Worker 195", "Support Worker 268",
]


# --- scenario templates ----------------------------------------------------
# Each produces one document and the check that was recorded against it. The
# `weight` decides how often it recurs across the period. Clean cases dominate,
# as they do in a real provider's caseload -- a demo where everything is on
# fire is not credible, and the point being made is that the model absorbs the
# routine volume so a human only sees the exceptions.

CLEAN = [
    {
        "key": "service_record",
        "title": "Service delivery record",
        "weight": 9,
        "risk": (4, 14),
        "verdicts": [
            ("consent_documentation", "pass", "Signed consent record dated before first service date."),
            ("data_retention_period", "pass", "Retention date is 7 years after the service date."),
            ("provider_registration_current", "pass", "Registration number 40551982 matches the NDIS format."),
            ("worker_screening_check", "pass", "Worker screening clearance recorded and current."),
            ("service_agreement_documented", "pass", "Service agreement on file and referenced by id."),
        ],
        "justification": "All applicable obligations satisfied. Consent, retention, registration and worker screening are documented, and the service agreement is referenced. No finding requires human review.",
    },
    {
        "key": "restrictive_monthly",
        "title": "Restrictive practice monthly report",
        "weight": 3,
        "risk": (9, 19),
        "verdicts": [
            ("behaviour_support_plan_lodged", "pass", "Behaviour support plan lodged and recorded as active."),
            ("restrictive_practice_authorisation", "pass", "State authorisation recorded and within its validity period."),
            ("restrictive_practice_monthly_report", "pass", "Report submitted 3 business days after month end, inside the 5-day window."),
        ],
        "justification": "Monthly restrictive practice reporting submitted within the required window against a lodged and active behaviour support plan. Authorisation is current.",
    },
    {
        "key": "incident_ontime",
        "title": "Reportable incident notification",
        "weight": 2,
        "risk": (12, 22),
        "verdicts": [
            ("incident_reporting_window", "pass", "Lodged with the NDIS Commission 6 hours after identification."),
            ("reportable_incident_detailed_report", "pass", "Detailed report submitted on business day 3 of 5."),
        ],
        "justification": "Incident notified within the 24-hour window and the detailed report followed inside 5 business days. Handling met the Commission's timeframes.",
    },
]

# The findings worth escalating. These are what a compliance officer is
# actually afraid of, and what makes the demo land.
ESCALATED = [
    {
        "key": "incident_late",
        "title": "Reportable incident notification",
        "risk": 88,
        "verdicts": [
            ("incident_reporting_window", "fail",
             "Incident identified 02:15 on the 14th; lodged 19:40 on the 15th. Elapsed 41.4 hours against a 24-hour maximum.",
             "incident_identified_date=2026-07-14T02:15Z; incident_report_date=2026-07-15T19:40Z"),
            ("reportable_incident_detailed_report", "uncertain",
             "No detailed report date present. Cannot confirm the 5-business-day obligation was met.", None),
        ],
        "justification": "The 24-hour notification window was exceeded by 17.4 hours. Late notification of a reportable incident is a compliance breach in its own right and is separately reportable. Escalated for a named reviewer to confirm the timeline and record the remediation.",
    },
    {
        "key": "restrictive_unauthorised",
        "title": "Restrictive practice use record",
        "risk": 94,
        "verdicts": [
            ("restrictive_practice_authorisation", "fail",
             "Record states a regulated restrictive practice was used. No authorisation reference from the state authorising body is present.",
             "restrictive_practice_used=true; restrictive_practice_authorisation_record=absent"),
            ("behaviour_support_plan_lodged", "fail",
             "No behaviour support plan status recorded. Monthly reporting cannot be completed against a plan that is not lodged.", None),
        ],
        "justification": "A regulated restrictive practice appears to have been used without recorded authorisation and without a lodged behaviour support plan. This is the highest-severity finding the ruleset produces. Escalated immediately -- this requires a human decision and, if confirmed, notification to the Commission.",
    },
    {
        "key": "complaint_no_incident",
        "title": "Participant complaint record",
        "risk": 79,
        "verdicts": [
            ("complaint_escalation_to_incident", "fail",
             "Complaint text describes an allegation of neglect. No corresponding incident report reference is present in the record.",
             "complaints_process_record=present; incident_report_date=absent"),
            ("complaints_process_documented", "pass", "Documented complaints process with stated timeframes exists."),
        ],
        "justification": "The complaint describes conduct falling within a reportable incident category, but no incident report is linked. Whether this meets the reportable threshold is a judgement about the underlying facts, not something the model should decide. Escalated to a reviewer.",
    },
    {
        "key": "registration_malformed",
        "title": "Service delivery record",
        "risk": 71,
        "verdicts": [
            ("provider_registration_current", "fail",
             "Registration number '4055-198' does not match the NDIS format (4-digit prefix, 8+ digits).",
             "provider_registration_number=4055-198"),
            ("consent_documentation", "pass", "Consent record present and dated."),
        ],
        "justification": "The provider registration number is malformed. Most likely a transcription error rather than an unregistered provider, but the distinction matters and cannot be settled from this document alone.",
    },
    {
        "key": "worker_screening_missing",
        "title": "Support worker roster record",
        "risk": 68,
        "verdicts": [
            ("worker_screening_check", "fail",
             "No screening clearance recorded for the worker named on two shifts in this record.",
             "worker_screening_clearance=absent"),
            ("service_agreement_documented", "pass", "Service agreement referenced."),
        ],
        "justification": "A worker delivering supports has no recorded NDIS Worker Screening Check. Either the clearance exists and was not recorded, or an unscreened worker delivered supports. Escalated.",
    },
    {
        "key": "detailed_report_late",
        "title": "Reportable incident detailed report",
        "risk": 76,
        "verdicts": [
            ("reportable_incident_detailed_report", "fail",
             "Submitted 8 business days after the provider became aware, against a 5-business-day maximum.",
             "incident_identified_date=2026-07-21; incident_detailed_report_date=2026-08-03"),
            ("incident_reporting_window", "pass", "Initial 24-hour notification was lodged on time."),
        ],
        "justification": "Initial notification met the 24-hour window but the detailed report was 3 business days late. Escalated so the delay is recorded with a reason.",
    },
    {
        "key": "agreement_terms_unclear",
        "title": "Participant service agreement",
        "risk": 44,
        "verdicts": [
            ("service_agreement_required_terms", "uncertain",
             "Agreement exists but the document does not show pricing, cancellation or the complaints process. Marked uncertain rather than failed -- the terms may be present in an annexe not submitted.",
             "service_agreement_terms=partial"),
            ("service_agreement_documented", "pass", "A signed agreement is on file."),
        ],
        "justification": "The agreement is documented but three required terms are not visible in what was submitted. This is a documentation gap rather than a confirmed breach, so it is escalated rather than rejected.",
    },
]

REJECTED = [
    {
        "key": "consent_absent",
        "title": "Service delivery record",
        "risk": 91,
        "verdicts": [
            ("consent_documentation", "fail",
             "No consent record of any kind in the document. Services were delivered on three dates.",
             "consent_record=absent"),
            ("data_retention_period", "fail", "No retention date recorded.", None),
        ],
        "justification": "Personal information was processed with no documented consent. Confirmed by the reviewer as a genuine gap rather than a missing attachment.",
        "review_note": "Confirmed with the service manager -- consent was never obtained for this participant. Services paused, consent process restarted, and the three delivered dates logged for remediation.",
    },
    {
        "key": "agreement_absent",
        "title": "Service delivery record",
        "risk": 83,
        "verdicts": [
            ("service_agreement_documented", "fail",
             "No service agreement reference. Supports delivered across the period without a documented agreement.",
             "service_agreement_record=absent"),
        ],
        "justification": "Supports were delivered without a documented service agreement, so the participant has no shared written record of what was agreed.",
        "review_note": "Checked against the client file -- no agreement exists. Agreement drafted and sent for signature; onboarding checklist updated so this cannot recur.",
    },
]


def _document_text(title: str, participant: str, day: datetime, scenario_key: str) -> str:
    """A plausible record. Short on purpose -- it appears in the viewer, and a
    demo audience reads maybe fifteen lines of it."""
    d = day.strftime("%d %B %Y")
    lines = [
        "SUNRISE COMMUNITY CARE PTY LTD",
        f"{title.upper()}",
        "",
        f"Participant:              {participant}",
        f"Service date:             {d}",
        "Provider registration:    " + ("4055-198" if scenario_key == "registration_malformed" else "40551982"),
        f"Prepared by:              {random.choice(WORKERS)}",
        "",
    ]
    if scenario_key == "consent_absent":
        lines += ["Consent record:           -- not on file --",
                  "Record retention date:    -- not recorded --"]
    elif scenario_key == "agreement_absent":
        lines += ["Consent record:           CN-2026-0871 (signed)",
                  "Service agreement:        -- not on file --"]
    elif scenario_key == "restrictive_unauthorised":
        lines += ["Restrictive practice used: YES -- environmental restraint (locked kitchen access)",
                  "Authorisation reference:   -- not recorded --",
                  "Behaviour support plan:    -- status not recorded --"]
    elif scenario_key == "incident_late":
        lines += ["Incident identified:      14 July 2026, 02:15",
                  "Lodged with Commission:   15 July 2026, 19:40",
                  "Incident category:        Serious injury requiring medical treatment"]
    elif scenario_key == "detailed_report_late":
        lines += ["Incident identified:      21 July 2026",
                  "Initial notification:     21 July 2026 (within 24h)",
                  "Detailed report lodged:   3 August 2026"]
    elif scenario_key == "complaint_no_incident":
        lines += ["Complaint received:       " + d,
                  "Complaint summary:        Family reports participant left without assistance",
                  "                          for an extended period during an overnight shift.",
                  "Incident report raised:   -- none linked --"]
    elif scenario_key == "worker_screening_missing":
        lines += ["Worker screening:         -- clearance not recorded --",
                  "Shifts covered:           2 (overnight)"]
    elif scenario_key == "agreement_terms_unclear":
        lines += ["Service agreement:        SA-2026-0342 (signed)",
                  "Terms visible:            participant goals, privacy consent",
                  "Terms not visible:        pricing, cancellation, complaints process"]
    else:
        lines += ["Consent record:           CN-2026-0" + str(random.randint(100, 999)) + " (signed)",
                  "Record retention date:    " + (day + timedelta(days=365 * 7 + 2)).strftime("%d %B %Y"),
                  "Worker screening:         WS-" + str(random.randint(10000, 99999)) + " (current)",
                  "Service agreement:        SA-2026-0" + str(random.randint(100, 999))]
    lines += ["", "Supports delivered in accordance with the participant's plan.",
              "This record forms part of the participant file and is retained",
              "under the provider's record management policy.", ""]
    return "\n".join(lines)


def _verdicts(spec) -> list[RuleVerdict]:
    out = []
    for item in spec:
        rule_id, status, explanation = item[0], item[1], item[2]
        trigger = item[3] if len(item) > 3 else None
        out.append(RuleVerdict(
            rule_id=rule_id,
            status=RuleVerdictStatus(status),
            confidence=round(random.uniform(0.88, 0.99), 2) if status != "uncertain" else round(random.uniform(0.42, 0.63), 2),
            explanation=explanation,
            triggering_data_point=trigger,
        ))
    return out


def build_plan(tenant: str, weeks: int = 6) -> list[dict]:
    """Lay the period out so the trend line has shape rather than being flat."""
    rng = random.Random(20260811)
    random.seed(20260811)
    end = datetime(2026, 8, 11, tzinfo=timezone.utc)
    start = end - timedelta(weeks=weeks)

    pool = []
    for tpl in CLEAN:
        pool += [("clean", tpl)] * tpl["weight"]
    plan = []

    # Clean volume spread across the whole window.
    for i in range(24):
        kind, tpl = rng.choice(pool)
        day = start + timedelta(days=rng.uniform(0, weeks * 7 - 1), hours=rng.uniform(8, 17))
        plan.append({"tpl": tpl, "decision": "auto_approved", "when": day})

    # Escalations, one of each, placed later in the period so the queue a
    # viewer opens is not stale.
    for idx, tpl in enumerate(ESCALATED):
        day = end - timedelta(days=rng.uniform(0.4, 12), hours=rng.uniform(0, 9))
        plan.append({"tpl": tpl, "decision": "escalated", "when": day})

    # Rejections sit further back -- they have already been decided.
    for tpl in REJECTED:
        day = end - timedelta(days=rng.uniform(14, 30))
        plan.append({"tpl": tpl, "decision": "rejected", "when": day})

    plan.sort(key=lambda p: p["when"])
    return plan


def seed(project: str, tenant: str, reviewer_uid: str, reviewer_email: str) -> None:
    db = firestore.Client(project=project)
    gcs = storage.Client(project=project)
    bucket = gcs.bucket(f"{project}{RAW_BUCKET_SUFFIX}")

    plan = build_plan(tenant)
    counts = {"auto_approved": 0, "escalated": 0, "rejected": 0}

    for i, item in enumerate(plan):
        tpl, decision, when = item["tpl"], item["decision"], item["when"]
        doc_id = f"demo-doc-{i:03d}"
        check_id = f"demo-chk-{i:03d}"
        participant = PARTICIPANTS[i % len(PARTICIPANTS)]
        filename = f"{tpl['key']}_{when.strftime('%Y%m%d')}.txt"

        text = _document_text(tpl["title"], participant, when, tpl["key"])
        data = text.encode("utf-8")
        blob_path = f"{tenant}/{doc_id}/{filename}"
        bucket.blob(blob_path).upload_from_string(data, content_type="text/plain")

        document = Document(
            document_id=doc_id,
            tenant_id=tenant,
            source="upload",
            storage_ref=f"gs://{bucket.name}/{blob_path}",
            status=DocumentStatus.PROCESSED,
            created_at=when,
            content_hash=hashlib.sha256(data).hexdigest(),
            content_type="text/plain",
            size_bytes=len(data),
            filename=filename,
            extracted_fields={"participant": participant, "title": tpl["title"]},
        )
        payload = document.model_dump(mode="json")
        payload[SEED_MARKER] = True
        db.collection("documents").document(doc_id).set(payload)

        risk = tpl["risk"]
        risk_score = random.randint(*risk) if isinstance(risk, tuple) else risk

        check = ComplianceCheck(
            check_id=check_id,
            document_id=doc_id,
            tenant_id=tenant,
            rule_set_version=RULE_SET_VERSION,
            risk_score=risk_score,
            justification=tpl["justification"],
            citations=[f"NDIS Practice Standards -- {v[0].replace('_', ' ')}" for v in tpl["verdicts"][:2]],
            decision=CheckDecision(decision),
            reviewer_id=reviewer_uid if decision == "rejected" else None,
            rule_verdicts=_verdicts(tpl["verdicts"]),
            gemini_metadata=GeminiCallMetadata(
                prompt_version=PROMPT_VERSION,
                model_name=MODEL_NAME,
                model_version="001",
            ),
            created_at=when,
        )
        cpayload = check.model_dump(mode="json")
        cpayload[SEED_MARKER] = True
        db.collection("compliance_checks").document(check_id).set(cpayload)
        counts[decision] += 1

    print(f"seeded into {tenant} ({project})")
    for k, v in counts.items():
        print(f"  {k:14} {v}")
    print(f"  {'total':14} {sum(counts.values())}")
    print(f"\nperiod: {plan[0]['when'].date()} to {plan[-1]['when'].date()}")
    print(f"{counts['escalated']} checks are waiting in the review queue.")


def wipe(project: str, tenant: str) -> None:
    db = firestore.Client(project=project)
    gcs = storage.Client(project=project)
    removed = 0
    for coll in ("documents", "compliance_checks"):
        for snap in db.collection(coll).where(SEED_MARKER, "==", True).stream():
            if snap.to_dict().get("tenant_id") == tenant:
                snap.reference.delete()
                removed += 1
    bucket = gcs.bucket(f"{project}{RAW_BUCKET_SUFFIX}")
    blobs = 0
    for blob in bucket.list_blobs(prefix=f"{tenant}/demo-doc-"):
        blob.delete()
        blobs += 1
    print(f"removed {removed} records and {blobs} stored files from {tenant}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", default=DEFAULT_PROJECT)
    ap.add_argument("--tenant", default=DEFAULT_TENANT)
    ap.add_argument("--reviewer-uid", default=DEFAULT_REVIEWER_UID)
    ap.add_argument("--reviewer-email", default=DEFAULT_REVIEWER_EMAIL)
    ap.add_argument("--wipe", action="store_true", help="remove previously seeded demo records")
    args = ap.parse_args()

    if args.wipe:
        wipe(args.project, args.tenant)
    else:
        seed(args.project, args.tenant, args.reviewer_uid, args.reviewer_email)


if __name__ == "__main__":
    main()
