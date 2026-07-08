"""Versioned prompts for the Ingestion Agent.

Every prompt carries a version string. That version is stored on the Gemini
call result (and therefore in Firestore/BigQuery) so any extraction can be
reproduced against the exact prompt text that produced it.

To evolve a prompt: add a new version constant (ingestion_v2, ...) and switch
CURRENT_INGESTION_PROMPT. Never edit an existing version's text in place —
that would silently break reproducibility of historical records.
"""

from __future__ import annotations

INGESTION_PROMPT_VERSION = "ingestion_v1"

INGESTION_SYSTEM_INSTRUCTION = (
    "You are a meticulous document data-extraction engine for a compliance "
    "platform. You read a single business document and extract only the fields "
    "requested. You never invent values: if a field is not present in the "
    "document, you return null for it. You return strict JSON only — no prose, "
    "no markdown fences."
)


def build_ingestion_user_prompt(
    *, document_type: str, field_list: list[str], required_fields: list[str]
) -> str:
    """Render the ingestion instruction for a specific document type.

    The field list is dynamic (derived from the active ruleset) so the model is
    only ever asked for fields that downstream rules actually consume.
    """
    fields_block = "\n".join(f"  - {f}" for f in field_list)
    required_block = ", ".join(required_fields) if required_fields else "(none)"
    return (
        f"Document type: {document_type}\n\n"
        f"Extract the following structured fields from this document:\n"
        f"{fields_block}\n\n"
        f"Rules:\n"
        f"1. Return a strict JSON object with exactly two keys: "
        f'"fields" and "missing_required_fields".\n'
        f'2. "fields" is an object mapping every field name above to the value '
        f"found in the document, or null if the field is absent.\n"
        f"3. Copy values verbatim from the document. Do not normalize, infer, or "
        f"fabricate. Dates should be returned exactly as written.\n"
        f'4. "missing_required_fields" is an array listing every field from this '
        f"required list that is null or absent: {required_block}.\n"
        f"5. Do not include any field name that is not in the list above.\n"
    )
