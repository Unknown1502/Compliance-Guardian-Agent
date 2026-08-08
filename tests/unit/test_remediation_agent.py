"""Unit tests: Remediation Agent (hermetic — no Gemini key, no emulators)."""

from __future__ import annotations

from pathlib import Path

import pytest

from gemini_client import GeminiResult
from schema_validators import (
    CheckDecision,
    ComplianceCheck,
    RemediationItem,
    RuleVerdict,
    RuleVerdictStatus,
    Tenant,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RULESETS_ROOT = str(REPO_ROOT / "rulesets")


class FakeGemini:
    """Returns queued results, or raises to exercise the fallback path."""

    def __init__(self, results=None, raises: Exception | None = None):
        self._results = list(results or [])
        self._raises = raises
        self.calls: list[dict] = []

    def generate_json(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises:
            raise self._raises
        if not self._results:
            raise AssertionError("FakeGemini ran out of queued results")
        return self._results.pop(0)


def gemini_result(data: dict) -> GeminiResult:
    return GeminiResult(
        data=data,
        prompt_version="remediation_v1",
        model_name="gemini-3.1-flash-lite",
        model_version="test",
        response_id="resp-1",
        raw_text="{}",
        attempts=1,
    )


class FakeRepo:
    def __init__(self, tenant: Tenant):
        self._tenant = tenant
        self.plans: dict = {}

    def get_tenant(self, tenant_id):
        return self._tenant

    def upsert_remediation_plan(self, plan):
        self.plans[plan.plan_id] = plan


class FakeAuditor:
    def __init__(self):
        self.events: list[dict] = []

    def log(self, **kwargs):
        self.events.append(kwargs)
        return kwargs


@pytest.fixture()
def tenant() -> Tenant:
    return Tenant(
        tenant_id="tenant-a",
        name="Sunrise Care",
        industry="healthcare_ndis",
        jurisdiction="AU",
    )


def _check(verdicts: list[RuleVerdict]) -> ComplianceCheck:
    return ComplianceCheck(
        check_id="check-1",
        document_id="doc-1",
        tenant_id="tenant-a",
        rule_set_version="1.1.0",
        risk_score=70,
        justification="Some rules failed.",
        citations=[v.rule_id for v in verdicts if v.status is RuleVerdictStatus.FAIL],
        decision=CheckDecision.ESCALATED,
        rule_verdicts=verdicts,
    )


def _real_rule_ids(n: int = 3) -> list[str]:
    """Rule ids that genuinely exist in the NDIS ruleset."""
    from schema_validators import load_ruleset

    rs = load_ruleset(RULESETS_ROOT, "healthcare_ndis", "AU")
    return [r.id for r in rs.rules[:n]]


def _run(check, tenant, gemini, repo=None, auditor=None):
    from remediation_agent.planner import build_remediation_plan

    repo = repo or FakeRepo(tenant)
    auditor = auditor or FakeAuditor()
    outcome = build_remediation_plan(
        check=check,
        repo=repo,
        gemini=gemini,
        auditor=auditor,
        rulesets_root=RULESETS_ROOT,
        document_extract="Service delivered 2026-02-02.",
    )
    return outcome, repo, auditor


class TestOrdering:
    def test_blocking_items_come_first(self):
        from remediation_agent.planner import order_items

        items = [
            RemediationItem(rule_id="a", title="a", action="a", blocking=False,
                            estimated_minutes=5, severity="low"),
            RemediationItem(rule_id="b", title="b", action="b", blocking=True,
                            estimated_minutes=90, severity="critical"),
        ]
        assert [i.rule_id for i in order_items(items)] == ["b", "a"]

    def test_within_blocking_more_severe_first(self):
        from remediation_agent.planner import order_items

        items = [
            RemediationItem(rule_id="med", title="m", action="m", blocking=True,
                            estimated_minutes=10, severity="medium"),
            RemediationItem(rule_id="crit", title="c", action="c", blocking=True,
                            estimated_minutes=10, severity="critical"),
        ]
        assert [i.rule_id for i in order_items(items)] == ["crit", "med"]

    def test_ties_broken_by_shortest_job(self):
        from remediation_agent.planner import order_items

        items = [
            RemediationItem(rule_id="slow", title="s", action="s", blocking=True,
                            estimated_minutes=120, severity="high"),
            RemediationItem(rule_id="quick", title="q", action="q", blocking=True,
                            estimated_minutes=5, severity="high"),
        ]
        assert [i.rule_id for i in order_items(items)] == ["quick", "slow"]

    def test_unknown_severity_sorts_last_rather_than_crashing(self):
        from remediation_agent.planner import order_items

        items = [
            RemediationItem(rule_id="weird", title="w", action="w", blocking=False,
                            estimated_minutes=5, severity="banana"),
            RemediationItem(rule_id="known", title="k", action="k", blocking=False,
                            estimated_minutes=5, severity="low"),
        ]
        assert [i.rule_id for i in order_items(items)] == ["known", "weird"]

    def test_ordering_is_deterministic(self):
        """Two identical checks must produce the same plan, not a model's whim."""
        from remediation_agent.planner import order_items

        items = [
            RemediationItem(rule_id=f"r{i}", title="t", action="a", blocking=i % 2 == 0,
                            estimated_minutes=i + 1, severity="high")
            for i in range(6)
        ]
        assert [i.rule_id for i in order_items(items)] == [
            i.rule_id for i in order_items(list(reversed(items)))
        ]


class TestPlanGeneration:
    def test_clean_document_produces_empty_plan_not_an_error(self, tenant):
        ids = _real_rule_ids(1)
        check = _check([
            RuleVerdict(rule_id=ids[0], status=RuleVerdictStatus.PASS,
                        confidence=1.0, explanation="fine")
        ])
        outcome, repo, auditor = _run(check, tenant, FakeGemini())
        assert outcome.plan.items == []
        assert outcome.plan.plan_id in repo.plans
        assert any(e["action"] == "remediation_plan_generated" for e in auditor.events)

    def test_one_item_per_failed_rule(self, tenant):
        ids = _real_rule_ids(2)
        check = _check([
            RuleVerdict(rule_id=ids[0], status=RuleVerdictStatus.FAIL,
                        confidence=0.9, explanation="missing consent"),
            RuleVerdict(rule_id=ids[1], status=RuleVerdictStatus.FAIL,
                        confidence=0.9, explanation="record too old"),
        ])
        g = FakeGemini([gemini_result({"items": [
            {"rule_id": ids[0], "title": "Get consent", "action": "Obtain a signed consent form.",
             "blocking": True, "estimated_minutes": 20},
            {"rule_id": ids[1], "title": "Refile record", "action": "Re-file with the correct date.",
             "blocking": False, "estimated_minutes": 10},
        ]})])
        outcome, _, _ = _run(check, tenant, g)
        assert {i.rule_id for i in outcome.plan.items} == set(ids)
        assert outcome.used_fixture is False

    def test_uncertain_verdicts_are_remediated_too(self, tenant):
        """'We could not tell' is exactly what a human should resolve."""
        ids = _real_rule_ids(1)
        check = _check([
            RuleVerdict(rule_id=ids[0], status=RuleVerdictStatus.UNCERTAIN,
                        confidence=0.4, explanation="could not determine")
        ])
        g = FakeGemini([gemini_result({"items": [
            {"rule_id": ids[0], "title": "Confirm", "action": "Confirm the record manually.",
             "blocking": False, "estimated_minutes": 10},
        ]})])
        outcome, _, _ = _run(check, tenant, g)
        assert len(outcome.plan.items) == 1

    def test_fabricated_rule_ids_are_dropped(self, tenant):
        """An item citing a rule that never failed is a made-up obligation."""
        ids = _real_rule_ids(1)
        check = _check([
            RuleVerdict(rule_id=ids[0], status=RuleVerdictStatus.FAIL,
                        confidence=0.9, explanation="missing")
        ])
        g = FakeGemini([gemini_result({"items": [
            {"rule_id": ids[0], "title": "Real", "action": "Do the real thing.",
             "blocking": True, "estimated_minutes": 15},
            {"rule_id": "totally_invented_rule", "title": "Fake",
             "action": "Do something no rule requires.", "blocking": True,
             "estimated_minutes": 60},
        ]})])
        outcome, _, _ = _run(check, tenant, g)
        assert [i.rule_id for i in outcome.plan.items] == [ids[0]]

    def test_item_without_an_action_is_dropped(self, tenant):
        ids = _real_rule_ids(2)
        check = _check([
            RuleVerdict(rule_id=i, status=RuleVerdictStatus.FAIL,
                        confidence=0.9, explanation="x") for i in ids
        ])
        g = FakeGemini([gemini_result({"items": [
            {"rule_id": ids[0], "title": "Has action", "action": "Do this.",
             "blocking": False, "estimated_minutes": 5},
            {"rule_id": ids[1], "title": "No action", "action": "   ",
             "blocking": False, "estimated_minutes": 5},
        ]})])
        outcome, _, _ = _run(check, tenant, g)
        assert [i.rule_id for i in outcome.plan.items] == [ids[0]]

    def test_duplicate_rule_ids_collapse(self, tenant):
        ids = _real_rule_ids(1)
        check = _check([
            RuleVerdict(rule_id=ids[0], status=RuleVerdictStatus.FAIL,
                        confidence=0.9, explanation="x")
        ])
        g = FakeGemini([gemini_result({"items": [
            {"rule_id": ids[0], "title": "One", "action": "A", "blocking": False,
             "estimated_minutes": 5},
            {"rule_id": ids[0], "title": "Two", "action": "B", "blocking": False,
             "estimated_minutes": 5},
        ]})])
        outcome, _, _ = _run(check, tenant, g)
        assert len(outcome.plan.items) == 1

    def test_absurd_minutes_are_clamped(self, tenant):
        ids = _real_rule_ids(1)
        check = _check([
            RuleVerdict(rule_id=ids[0], status=RuleVerdictStatus.FAIL,
                        confidence=0.9, explanation="x")
        ])
        g = FakeGemini([gemini_result({"items": [
            {"rule_id": ids[0], "title": "T", "action": "A", "blocking": False,
             "estimated_minutes": 9_999_999},
        ]})])
        outcome, _, _ = _run(check, tenant, g)
        assert outcome.plan.items[0].estimated_minutes <= 10080


class TestFailureHandling:
    def test_malformed_json_falls_back_instead_of_raising(self, tenant):
        """gemini_client's repair pass can still fail; that must not lose the plan."""
        ids = _real_rule_ids(2)
        check = _check([
            RuleVerdict(rule_id=i, status=RuleVerdictStatus.FAIL,
                        confidence=0.9, explanation="x") for i in ids
        ])
        g = FakeGemini([gemini_result({"garbage": "no items key"})])
        outcome, _, auditor = _run(check, tenant, g)
        assert outcome.used_fixture is True
        assert {i.rule_id for i in outcome.plan.items} == set(ids)
        assert any(e["action"] == "remediation_plan_generated" for e in auditor.events)

    def test_gemini_outage_still_produces_a_plan(self, tenant):
        ids = _real_rule_ids(1)
        check = _check([
            RuleVerdict(rule_id=ids[0], status=RuleVerdictStatus.FAIL,
                        confidence=0.9, explanation="missing consent")
        ])
        outcome, _, _ = _run(check, tenant, FakeGemini(raises=RuntimeError("503")))
        assert outcome.used_fixture is True
        assert len(outcome.plan.items) == 1

    def test_no_gemini_client_configured(self, tenant):
        ids = _real_rule_ids(1)
        check = _check([
            RuleVerdict(rule_id=ids[0], status=RuleVerdictStatus.FAIL,
                        confidence=0.9, explanation="x")
        ])
        outcome, _, _ = _run(check, tenant, None)
        assert outcome.used_fixture is True

    def test_verdict_for_a_rule_not_in_the_ruleset_is_ignored(self, tenant):
        check = _check([
            RuleVerdict(rule_id="not_a_real_rule", status=RuleVerdictStatus.FAIL,
                        confidence=0.9, explanation="x")
        ])
        outcome, _, _ = _run(check, tenant, FakeGemini())
        assert outcome.plan.items == []


class TestPersistenceAndAudit:
    def test_plan_id_is_deterministic_per_check(self):
        from remediation_agent.planner import deterministic_plan_id

        assert deterministic_plan_id("check-1") == deterministic_plan_id("check-1")
        assert deterministic_plan_id("check-1") != deterministic_plan_id("check-2")

    def test_replay_overwrites_rather_than_duplicating(self, tenant):
        ids = _real_rule_ids(1)
        check = _check([
            RuleVerdict(rule_id=ids[0], status=RuleVerdictStatus.FAIL,
                        confidence=0.9, explanation="x")
        ])
        repo = FakeRepo(tenant)
        _run(check, tenant, FakeGemini(raises=RuntimeError("x")), repo=repo)
        _run(check, tenant, FakeGemini(raises=RuntimeError("x")), repo=repo)
        assert len(repo.plans) == 1

    def test_audit_event_carries_the_evidence_fields(self, tenant):
        ids = _real_rule_ids(1)
        check = _check([
            RuleVerdict(rule_id=ids[0], status=RuleVerdictStatus.FAIL,
                        confidence=0.9, explanation="x")
        ])
        _, _, auditor = _run(check, tenant, FakeGemini(raises=RuntimeError("x")))
        event = next(e for e in auditor.events if e["action"] == "remediation_plan_generated")
        after = event["after_state"]
        for field in ("plan_id", "check_id", "document_id", "item_count",
                      "gemini_model", "estimated_minutes"):
            assert field in after, f"missing {field} in audit record"

    def test_total_estimated_minutes_sums_items(self, tenant):
        ids = _real_rule_ids(2)
        check = _check([
            RuleVerdict(rule_id=i, status=RuleVerdictStatus.FAIL,
                        confidence=0.9, explanation="x") for i in ids
        ])
        g = FakeGemini([gemini_result({"items": [
            {"rule_id": ids[0], "title": "A", "action": "a", "blocking": False,
             "estimated_minutes": 10},
            {"rule_id": ids[1], "title": "B", "action": "b", "blocking": False,
             "estimated_minutes": 25},
        ]})])
        outcome, _, _ = _run(check, tenant, g)
        assert outcome.plan.total_estimated_minutes == 35


class TestCostGuardrail:
    def test_document_extract_is_capped(self):
        from remediation_agent.prompts import MAX_EXTRACT_CHARS, build_remediation_user_prompt

        prompt = build_remediation_user_prompt(
            failures=[{"rule_id": "r", "description": "d", "explanation": "e"}],
            document_extract="x" * 50_000,
            industry="healthcare_ndis",
            jurisdiction="AU",
        )
        assert prompt.count("x") <= MAX_EXTRACT_CHARS

    def test_plan_length_is_bounded(self, tenant):
        """A 40-item checklist is homework, not remediation."""
        from remediation_agent.planner import MAX_ITEMS

        ids = _real_rule_ids(14)
        check = _check([
            RuleVerdict(rule_id=i, status=RuleVerdictStatus.FAIL,
                        confidence=0.9, explanation="x") for i in ids
        ])
        outcome, _, _ = _run(check, tenant, FakeGemini(raises=RuntimeError("x")))
        assert len(outcome.plan.items) <= MAX_ITEMS


class TestPipelineTrigger:
    """Remediation must actually fire from the compliance pipeline."""

    def _dispatcher(self, tenant, gemini, calls):
        from orchestrator.handlers import build_inline_dispatcher

        class Repo(FakeRepo):
            def get_document(self, document_id, tenant_id):
                class D:
                    extracted_fields = {"consent_date": None}

                return D()

        class TaskSvc:
            def mark_running(self, *a, **k):
                pass

            def mark_succeeded(self, *a, **k):
                pass

            def mark_failed(self, *a, **k):
                pass

        class Notifier:
            def notify_escalation(self, **k):
                pass

        repo = Repo(tenant)
        return build_inline_dispatcher(
            task_service=TaskSvc(),
            repo=repo,
            storage_client=None,
            gemini=gemini,
            auditor=FakeAuditor(),
            notifier=Notifier(),
            rulesets_root=RULESETS_ROOT,
            escalation_threshold=60,
        ), repo

    def test_remediation_runs_for_auto_approved_checks_too(self, tenant, monkeypatch):
        """A document can auto-approve and still have fixable violations."""
        import orchestrator.handlers as handlers

        ids = _real_rule_ids(1)
        low_risk_check = _check([
            RuleVerdict(rule_id=ids[0], status=RuleVerdictStatus.FAIL,
                        confidence=0.9, explanation="minor gap")
        ])
        low_risk_check = low_risk_check.model_copy(
            update={"risk_score": 10, "decision": CheckDecision.AUTO_APPROVED}
        )

        class Outcome:
            check = low_risk_check

        monkeypatch.setattr(handlers, "run_compliance_check", lambda **k: Outcome())
        seen = {}
        import remediation_agent.planner as planner

        real = planner.build_remediation_plan

        def spy(**kwargs):
            seen["called"] = True
            return real(**kwargs)

        monkeypatch.setattr(planner, "build_remediation_plan", spy)

        dispatcher, _ = self._dispatcher(tenant, FakeGemini(raises=RuntimeError("x")), seen)
        dispatcher.dispatch(
            target="check",
            payload={"task_id": "t1", "tenant_id": "tenant-a", "document_id": "doc-1"},
        )
        assert seen.get("called") is True, "remediation did not run for an auto-approved check"

    def test_remediation_failure_does_not_fail_the_check(self, tenant, monkeypatch):
        """The compliance verdict is the guarantee; the fix list is help on top."""
        import orchestrator.handlers as handlers
        import remediation_agent.planner as planner

        ids = _real_rule_ids(1)
        check = _check([
            RuleVerdict(rule_id=ids[0], status=RuleVerdictStatus.FAIL,
                        confidence=0.9, explanation="x")
        ])

        class Outcome:
            pass

        Outcome.check = check
        monkeypatch.setattr(handlers, "run_compliance_check", lambda **k: Outcome())

        def explode(**kwargs):
            raise RuntimeError("remediation subsystem down")

        monkeypatch.setattr(planner, "build_remediation_plan", explode)

        dispatcher, _ = self._dispatcher(tenant, FakeGemini(), {})
        # Must not raise.
        dispatcher.dispatch(
            target="check",
            payload={"task_id": "t1", "tenant_id": "tenant-a", "document_id": "doc-1"},
        )
