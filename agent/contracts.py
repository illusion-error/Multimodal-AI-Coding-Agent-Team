"""Shared semantic contract helpers.

This module keeps the hard line between system-authoritative checks and
model-generated advisory tests. LLM output may suggest examples, but it must
not silently become an oracle.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List


SYSTEM_AUTHORITY = "system_contract"
MODEL_AUTHORITY = "model_generated"
HUMAN_AUTHORITY = "human_confirmed"


def is_authoritative_case(case: Dict[str, Any]) -> bool:
    """Return True only when a case is safe to use as an oracle."""

    authority = str(case.get("authority") or case.get("source") or "").strip()
    return authority in {SYSTEM_AUTHORITY, HUMAN_AUTHORITY} or bool(case.get("trusted"))


def split_test_cases(cases: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Split cases into trusted oracle cases and advisory cases."""

    trusted: List[Dict[str, Any]] = []
    advisory: List[Dict[str, Any]] = []
    for case in cases or []:
        if is_authoritative_case(case):
            trusted.append(case)
        else:
            advisory.append(case)
    return {"trusted": trusted, "advisory": advisory}


def semantic_status_from_cases(cases: Iterable[Dict[str, Any]]) -> str:
    """Compute semantic verification status without trusting model-only tests."""

    split = split_test_cases(cases)
    trusted = split["trusted"]
    if not trusted:
        return "manual_review"
    if all(bool(case.get("passed")) for case in trusted):
        return "verified"
    return "failed"


def ensure_model_case_is_advisory(case: Dict[str, Any]) -> Dict[str, Any]:
    """Mark an LLM-generated case as advisory unless it is already authoritative."""

    normalized = dict(case)
    if not is_authoritative_case(normalized):
        normalized["authority"] = MODEL_AUTHORITY
        normalized["trusted"] = False
    return normalized
