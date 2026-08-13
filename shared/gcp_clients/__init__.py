"""GCP client factories — the single place emulator/production wiring lives.

Every service imports clients from here. Behavior:
  - If FIRESTORE_EMULATOR_HOST / BIGQUERY_EMULATOR_HOST / STORAGE_EMULATOR_HOST
    are set, clients connect to local emulators with anonymous credentials.
  - Otherwise, clients use Application Default Credentials against live GCP.

This keeps emulator quirks (anonymous creds, custom endpoints) out of business
logic entirely.
"""

from __future__ import annotations

import os
from functools import lru_cache

from google.api_core.client_options import ClientOptions
from google.auth.credentials import AnonymousCredentials
from google.cloud import bigquery, firestore, storage


def project_id() -> str:
    return os.environ.get("GOOGLE_CLOUD_PROJECT", "cg-local")


@lru_cache(maxsize=1)
def firestore_client() -> firestore.Client:
    # google-cloud-firestore honors FIRESTORE_EMULATOR_HOST natively, but with
    # real ADC it still tries to load credentials; pass anonymous explicitly
    # when the emulator is in play so no ADC is required locally.
    if os.environ.get("FIRESTORE_EMULATOR_HOST"):
        return firestore.Client(project=project_id(), credentials=AnonymousCredentials())
    return firestore.Client(project=project_id())


@lru_cache(maxsize=1)
def bigquery_client() -> bigquery.Client:
    emulator = os.environ.get("BIGQUERY_EMULATOR_HOST")
    if emulator:
        return bigquery.Client(
            project=project_id(),
            credentials=AnonymousCredentials(),
            client_options=ClientOptions(api_endpoint=emulator),
        )
    return bigquery.Client(project=project_id())


@lru_cache(maxsize=1)
def storage_client() -> storage.Client:
    # google-cloud-storage honors STORAGE_EMULATOR_HOST natively; anonymous
    # credentials avoid an ADC lookup locally.
    if os.environ.get("STORAGE_EMULATOR_HOST"):
        return storage.Client(project=project_id(), credentials=AnonymousCredentials())
    return storage.Client(project=project_id())


def audit_dataset() -> str:
    return os.environ.get("BQ_DATASET_AUDIT", "compliance_audit")


def audit_table() -> str:
    return os.environ.get("BQ_TABLE_AUDIT_LOGS", "audit_logs")


def reports_table() -> str:
    return os.environ.get("BQ_TABLE_REPORTS", "reports")


def raw_docs_bucket() -> str:
    return os.environ.get("GCS_BUCKET_RAW_DOCS", f"{project_id()}-cg-raw-docs")


def reports_bucket() -> str:
    return os.environ.get("GCS_BUCKET_REPORTS", f"{project_id()}-cg-reports")


def quarantine_bucket() -> str:
    """Where uploaded bytes live before a scanner has cleared them.

    A separate bucket rather than a prefix inside raw-docs, so the boundary can
    be an IAM one: the ingestion and compliance service accounts are not granted
    read on this bucket at all. That way a bug in the application layer cannot
    hand a worker an unscanned file — the worker could not read it even if it
    tried.
    """
    return os.environ.get("GCS_BUCKET_QUARANTINE", f"{project_id()}-cg-quarantine")


def reset_client_caches() -> None:
    """Test hook: clear cached clients (e.g., after monkeypatching env vars)."""
    firestore_client.cache_clear()
    bigquery_client.cache_clear()
    storage_client.cache_clear()
