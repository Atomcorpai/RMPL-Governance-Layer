"""
z1_action_guard.py
Action-risk classifier for the z1/RMPL dam layer.

Role:
    Classify user/runtime requests before execution.
    This module does not execute actions. It only returns a decision.

Design goals:
    - boring, explicit, auditable
    - destructive/evidence-affecting actions require confirmation
    - ambiguous instructions stop for clarity
    - safe/reversible analysis proceeds
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Iterable, List


class ActionDecision(str, Enum):
    ALLOW = "ALLOW"
    STOP_FOR_CLARITY = "STOP_FOR_CLARITY"
    REQUIRE_CONFIRMATION = "REQUIRE_CONFIRMATION"
    BLOCK = "BLOCK"


@dataclass
class GuardResult:
    decision: ActionDecision
    reason: str
    matched_terms: List[str] = field(default_factory=list)
    risk_level: str = "low"
    reversible: bool = True
    evidence_affecting: bool = False
    destructive: bool = False


DESTRUCTIVE_TERMS = [
    "delete", "remove", "wipe", "erase", "destroy", "purge", "trash",
    "overwrite", "replace", "reset", "format", "drop table", "truncate",
]

EVIDENCE_AFFECTING_TERMS = [
    "edit evidence", "alter evidence", "modify evidence", "change evidence",
    "redact original", "rename original", "delete original", "overwrite original",
    "compress evidence", "re-save evidence", "metadata", "timestamp",
]

EXTERNAL_ACTION_TERMS = [
    "send", "submit", "file", "publish", "post", "email", "forward",
    "upload", "commit", "push", "merge", "deploy", "release",
]

AMBIGUOUS_TARGET_TERMS = [
    "clean up", "fix it", "fix this", "handle it", "do it",
    "make it work", "update everything", "delete the bad ones",
    "remove the wrong ones", "archive everything",
]

SAFE_DRAFT_TERMS = [
    "draft", "review", "summarize", "analyze", "inspect", "compare",
    "explain", "classify", "triage", "recommend", "make a checklist",
]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _matched_terms(text: str, terms: Iterable[str]) -> List[str]:
    lower = _normalize(text)
    return [term for term in terms if term in lower]


def _has_explicit_target(text: str) -> bool:
    lower = _normalize(text)
    target_markers = [
        "file", "folder", "path", "named", "called", "this file", "these files",
        ".py", ".json", ".md", ".docx", ".pdf", ".zip", "only", "specific",
    ]
    return any(marker in lower for marker in target_markers)


class ActionGuard:
    """
    Classifies requests before the dam allows execution.

    confirmation=True means the user explicitly confirmed the action in the
    current interaction, not merely implied it historically.
    inspected_artifact=True means the relevant artifact was inspected or the
    request is not artifact-dependent.
    """

    def classify(
        self,
        request_text: str,
        *,
        confirmation: bool = False,
        inspected_artifact: bool = True,
    ) -> GuardResult:
        text = _normalize(request_text)

        if not text:
            return GuardResult(
                ActionDecision.STOP_FOR_CLARITY,
                "Empty request cannot be safely classified.",
                risk_level="unknown",
            )

        ambiguous = _matched_terms(text, AMBIGUOUS_TARGET_TERMS)
        if ambiguous and not _has_explicit_target(text):
            return GuardResult(
                ActionDecision.STOP_FOR_CLARITY,
                "Instruction is ambiguous and lacks a specific target/scope.",
                matched_terms=ambiguous,
                risk_level="ambiguous",
            )

        destructive = _matched_terms(text, DESTRUCTIVE_TERMS)
        evidence = _matched_terms(text, EVIDENCE_AFFECTING_TERMS)
        external = _matched_terms(text, EXTERNAL_ACTION_TERMS)

        if evidence:
            if confirmation and inspected_artifact:
                return GuardResult(
                    ActionDecision.ALLOW,
                    "Evidence-affecting action allowed only because explicit confirmation and artifact inspection are present.",
                    matched_terms=evidence,
                    risk_level="high",
                    reversible=False,
                    evidence_affecting=True,
                )
            return GuardResult(
                ActionDecision.REQUIRE_CONFIRMATION,
                "Evidence-affecting action requires explicit confirmation and artifact inspection.",
                matched_terms=evidence,
                risk_level="high",
                reversible=False,
                evidence_affecting=True,
            )

        if destructive:
            if confirmation and inspected_artifact:
                return GuardResult(
                    ActionDecision.ALLOW,
                    "Destructive action allowed only because explicit confirmation and artifact inspection are present.",
                    matched_terms=destructive,
                    risk_level="high",
                    reversible=False,
                    destructive=True,
                )
            return GuardResult(
                ActionDecision.REQUIRE_CONFIRMATION,
                "Destructive or irreversible action requires explicit confirmation.",
                matched_terms=destructive,
                risk_level="high",
                reversible=False,
                destructive=True,
            )

        if external:
            if confirmation:
                return GuardResult(
                    ActionDecision.ALLOW,
                    "External/action-taking request allowed because explicit confirmation is present.",
                    matched_terms=external,
                    risk_level="medium",
                    reversible=False,
                )
            return GuardResult(
                ActionDecision.REQUIRE_CONFIRMATION,
                "External action requires explicit confirmation before execution.",
                matched_terms=external,
                risk_level="medium",
                reversible=False,
            )

        safe = _matched_terms(text, SAFE_DRAFT_TERMS)
        if safe:
            return GuardResult(
                ActionDecision.ALLOW,
                "Safe reversible analysis/drafting request.",
                matched_terms=safe,
                risk_level="low",
                reversible=True,
            )

        if not inspected_artifact and _has_explicit_target(text):
            return GuardResult(
                ActionDecision.STOP_FOR_CLARITY,
                "Referenced artifact has not been inspected.",
                risk_level="ambiguous",
            )

        return GuardResult(
            ActionDecision.ALLOW,
            "No destructive, evidence-affecting, external, or ambiguous trigger detected.",
            risk_level="low",
            reversible=True,
        )
