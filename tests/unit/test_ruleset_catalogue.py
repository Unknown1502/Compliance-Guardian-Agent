"""Unit tests: the ruleset catalogue and jurisdiction selection at signup.

These exist because of a real defect: the dashboard hardcoded
healthcare_ndis/AU at signup, so every workspace ever created was assigned
Australian NDIS rules regardless of where the business operated. Fourteen of
the fifteen rulesets were unreachable, and a non-Australian customer would
have received confident, cited verdicts against rules that did not govern
them — worse than no answer at all.

What is asserted here is that the menu can only ever offer pairs that really
exist on disk, and that the server still refuses a pair it cannot load.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from schema_validators import available_rulesets, load_ruleset

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RULESETS = REPO_ROOT / "rulesets"


class TestAvailableRulesets:
    def test_finds_every_ruleset_on_disk(self):
        found = {(o.industry, o.jurisdiction) for o in available_rulesets(RULESETS)}
        on_disk = {
            (p.parent.name, p.stem) for p in RULESETS.glob("*/*.yaml")
        }
        assert found == on_disk
        assert len(found) >= 15

    def test_every_offered_pair_actually_loads(self):
        """The menu must never offer a workspace that cannot be checked."""
        for option in available_rulesets(RULESETS):
            ruleset = load_ruleset(RULESETS, option.industry, option.jurisdiction)
            assert ruleset.rules, f"{option.industry}/{option.jurisdiction} has no rules"
            assert option.rule_count == len(ruleset.rules)
            assert option.rule_set_version == ruleset.rule_set_version

    def test_coverage_is_not_australia_only(self):
        """The regression this whole feature exists to prevent."""
        jurisdictions = {o.jurisdiction for o in available_rulesets(RULESETS)}
        assert "au" in jurisdictions
        assert "in" in jurisdictions
        assert "eu" in jurisdictions
        # More than a token second country.
        assert len(jurisdictions - {"au", "generic"}) >= 8

    def test_malformed_ruleset_is_skipped_not_fatal(self, tmp_path):
        """One broken file must not empty the whole menu."""
        good = tmp_path / "data_privacy"
        good.mkdir()
        (good / "in.yaml").write_text(
            (RULESETS / "data_privacy" / "in.yaml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        broken = tmp_path / "broken"
        broken.mkdir()
        (broken / "xx.yaml").write_text("this: is: not: a: ruleset", encoding="utf-8")

        options = available_rulesets(tmp_path)
        assert [(o.industry, o.jurisdiction) for o in options] == [("data_privacy", "in")]

    def test_missing_root_returns_empty_not_error(self, tmp_path):
        assert available_rulesets(tmp_path / "nope") == []


def _client(monkeypatch):
    monkeypatch.setenv("CG_AUTH_DEV_MODE", "1")
    import api_gateway.main as main
    import auth_middleware

    monkeypatch.setattr(auth_middleware, "_ensure_firebase_app", lambda: None)
    return TestClient(main.app, raise_server_exceptions=False)


class TestCatalogueEndpoint:
    def test_is_public_because_signup_needs_it_before_an_account_exists(self, monkeypatch):
        c = _client(monkeypatch)
        r = c.get("/api/rulesets/available")
        assert r.status_code == 200
        assert len(r.json()) >= 15

    def test_returns_india_so_a_non_australian_can_sign_up(self, monkeypatch):
        c = _client(monkeypatch)
        rows = c.get("/api/rulesets/available").json()
        assert any(
            row["industry"] == "data_privacy" and row["jurisdiction"] == "in" for row in rows
        )

    def test_every_row_carries_a_real_rule_count(self, monkeypatch):
        c = _client(monkeypatch)
        for row in c.get("/api/rulesets/available").json():
            assert row["rule_count"] > 0
            assert row["rule_set_version"]

    def test_exposes_no_filesystem_paths(self, monkeypatch):
        """Codes only — the response must not describe the container layout."""
        c = _client(monkeypatch)
        body = c.get("/api/rulesets/available").text
        assert "/app" not in body
        assert ".yaml" not in body


class TestSignupStillValidatesServerSide:
    """The picker is a convenience; the server remains the authority."""

    def test_unknown_pair_is_rejected(self, monkeypatch):
        c = _client(monkeypatch)
        r = c.post(
            "/api/signup",
            json={
                "email": "new@example.com",
                "password": "correct horse battery",
                "business_name": "Test Co",
                "industry": "data_privacy",
                "jurisdiction": "atlantis",
            },
        )
        assert r.status_code == 400
        assert "no ruleset" in r.json()["detail"]

    def test_path_traversal_in_jurisdiction_is_rejected(self, monkeypatch):
        c = _client(monkeypatch)
        r = c.post(
            "/api/signup",
            json={
                "email": "new@example.com",
                "password": "correct horse battery",
                "business_name": "Test Co",
                "industry": "data_privacy",
                "jurisdiction": "../../etc/passwd",
            },
        )
        # Rejected by the field pattern before load_ruleset is even reached.
        assert r.status_code == 422
