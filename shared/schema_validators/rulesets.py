"""Ruleset loading & validation.

Rulesets live in versioned YAML at /rulesets/{industry}/{jurisdiction}.yaml
and are validated through the RuleSet Pydantic model on load — a malformed
ruleset fails at startup/seed time, never mid-compliance-check.
"""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class RulesetOption:
    """One selectable (industry, jurisdiction) pair that really exists.

    Deliberately carries no display title. RuleSet is a StrictModel shared by
    every service, so adding a `title:` field to the YAML would make every
    existing ruleset fail validation in the agents until all five services
    were redeployed together. Labels are presentation and belong in the API
    layer, not in the on-disk contract.
    """

    industry: str
    jurisdiction: str
    rule_set_version: str
    rule_count: int


def available_rulesets(rulesets_root: Path | str) -> list[RulesetOption]:
    """Every ruleset on disk, each one actually parsed before being offered.

    Read from the filesystem rather than a hardcoded list on purpose. A
    signup form that offers a jurisdiction with no ruleset behind it creates
    a workspace whose documents can never be checked, and a hardcoded list
    drifts silently the moment a YAML file is added or renamed. Parsing each
    file also means a malformed ruleset disappears from the menu instead of
    becoming a customer-facing 500 later.
    """
    root = Path(rulesets_root)
    if not root.is_dir():
        return []

    options: list[RulesetOption] = []
    for industry_dir in sorted(root.iterdir()):
        if not industry_dir.is_dir():
            continue
        for path in sorted(industry_dir.glob("*.yaml")):
            try:
                ruleset = load_ruleset_file(path)
            except Exception:
                # A broken file must not take the whole catalogue down with
                # it — the other jurisdictions are still perfectly usable.
                continue
            options.append(
                RulesetOption(
                    industry=industry_dir.name,
                    jurisdiction=path.stem,
                    rule_set_version=ruleset.rule_set_version,
                    rule_count=len(ruleset.rules),
                )
            )
    return options


def _safe_token(value: str) -> str:
    token = value.strip().lower()
    if not token or any(ch in token for ch in ("/", "\\", "..", "\0")):
        raise ValueError(f"unsafe ruleset path token: {value!r}")
    return token
