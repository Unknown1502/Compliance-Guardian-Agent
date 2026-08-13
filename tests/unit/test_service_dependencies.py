"""Every third-party package a service imports must be in its requirements.txt.

This exists because the scanner agent shipped without `google-cloud-tasks`.
Nothing caught it: the dev environment has the package via the gateway's
requirements, so imports resolved locally and all 601 tests passed. It failed
only inside the deployed container, as an ImportError at first request — the
same shape as the `shared/` packaging trap that has broken a deployment here
before.

A container gets exactly what its requirements.txt declares. Local success
proves nothing about that.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Top-level import name -> distribution named in requirements.txt.
DISTRIBUTION = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "pydantic": "pydantic",
    "yaml": "PyYAML",
    "google.cloud.firestore": "google-cloud-firestore",
    "google.cloud.bigquery": "google-cloud-bigquery",
    "google.cloud.storage": "google-cloud-storage",
    "google.cloud.tasks_v2": "google-cloud-tasks",
    "google.genai": "google-genai",
    "firebase_admin": "firebase-admin",
    "reportlab": "reportlab",
}

# Packages installed from shared/ by the Dockerfile, plus stdlib and the
# service's own modules — never declared in requirements.txt.
LOCAL = {
    "audit_logger", "gcp_clients", "schema_validators", "gemini_client",
    "auth_middleware", "task_dispatch", "notifications", "payments",
    "ingestion_agent", "compliance_agent", "escalation_service", "orchestrator",
    "reporting_agent", "remediation_agent", "scanner_agent", "api_gateway",
}

SERVICES = [
    ("scanner-agent", "services/scanner-agent"),
    ("ingestion-agent", "services/ingestion-agent"),
    ("compliance-agent", "services/compliance-agent"),
    ("reporting-agent", "services/reporting-agent"),
    ("orchestrator", "services/orchestrator"),
    ("escalation-service", "services/escalation-service"),
    ("api-gateway", "apps/api-gateway"),
]


def _imports(pkg_dir: Path) -> set[str]:
    found: set[str] = set()
    for path in pkg_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    found.add(a.name)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                # `from google.cloud import tasks_v2` — the distribution is
                # decided by the imported name, not just the module path.
                if node.module == "google.cloud":
                    for a in node.names:
                        found.add(f"google.cloud.{a.name}")
                else:
                    found.add(node.module)
    return found


def _required(name: str, root: Path) -> set[str]:
    """Third-party distributions this service's container actually needs.

    Follows imports into the shared/ packages. That transitivity is the whole
    point: the scanner's own code imports `task_dispatch`, and it is
    *task_dispatch* that imports tasks_v2. Scanning only the service's
    directory would have declared the scanner fine while its container
    ImportErrors — which is exactly what happened.
    """
    seen_local: set[str] = set()
    pending = [root]
    needed: set[str] = set()

    while pending:
        modules = _imports(pending.pop())
        for mod in modules:
            head = mod.split(".")[0]
            if head == "__future__":
                continue
            if head in LOCAL:
                shared_pkg = REPO_ROOT / "shared" / head
                if head not in seen_local and shared_pkg.is_dir():
                    seen_local.add(head)
                    pending.append(shared_pkg)
                continue
            for prefix, dist in DISTRIBUTION.items():
                if mod == prefix or mod.startswith(prefix + "."):
                    needed.add(dist)
    return needed


def _declared(root: Path) -> str:
    return (root / "requirements.txt").read_text(encoding="utf-8").lower()


@pytest.mark.parametrize("name,rel", SERVICES, ids=[s for s, _ in SERVICES])
def test_service_declares_every_package_it_imports(name, rel):
    root = REPO_ROOT / rel
    if not (root / "requirements.txt").exists():
        pytest.skip(f"{name} has no requirements.txt")
    declared = _declared(root)
    missing = sorted(d for d in _required(name, root) if d.lower() not in declared)
    assert not missing, (
        f"{name} imports {missing} but does not declare them in requirements.txt — "
        f"the container will ImportError at runtime even though local tests pass"
    )


def test_scanner_declares_cloud_tasks():
    """The specific regression: the scanner chains to ingestion via Cloud Tasks."""
    declared = _declared(REPO_ROOT / "services/scanner-agent")
    assert "google-cloud-tasks" in declared
