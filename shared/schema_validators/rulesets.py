"""Ruleset loading & validation.

Rulesets live in versioned YAML at /rulesets/{industry}/{jurisdiction}.yaml
and are validated through the RuleSet Pydantic model on load — a malformed
ruleset fails at startup/seed time, never mid-compliance-check.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from schema_validators.models import RuleSet


class RulesetNotFoundError(FileNotFoundError):
    """Raised when no ruleset file exists for the industry/jurisdiction pair."""


def load_ruleset_file(path: Path | str) -> RuleSet:
    """Load and validate a single ruleset YAML file."""
    p = Path(path)
    if not p.is_file():
        raise RulesetNotFoundError(f"ruleset file not found: {p}")
    with p.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ValueError(f"ruleset file {p} did not parse to a mapping")
    return RuleSet.model_validate(raw)


def load_ruleset(rulesets_root: Path | str, industry: str, jurisdiction: str) -> RuleSet:
    """Load /rulesets/{industry}/{jurisdiction}.yaml relative to the given root.

    industry/jurisdiction are sanitized to path-safe tokens to prevent
    directory traversal via tenant-controlled values.
    """
    safe_industry = _safe_token(industry)
    safe_jurisdiction = _safe_token(jurisdiction)
    path = Path(rulesets_root) / safe_industry / f"{safe_jurisdiction}.yaml"
    ruleset = load_ruleset_file(path)
    # Case-insensitive match: spec YAML uses jurisdiction "AU" while file
    # paths are lowercase (au.yaml); both must resolve to the same ruleset.
    if (
        ruleset.industry.lower() != safe_industry
        or ruleset.jurisdiction.lower() != safe_jurisdiction
    ):
        raise ValueError(
            f"ruleset at {path} declares industry={ruleset.industry!r} "
            f"jurisdiction={ruleset.jurisdiction!r}, expected {industry!r}/{jurisdiction!r}"
        )
    return ruleset


def _safe_token(value: str) -> str:
    token = value.strip().lower()
    if not token or any(ch in token for ch in ("/", "\\", "..", "\0")):
        raise ValueError(f"unsafe ruleset path token: {value!r}")
    return token
