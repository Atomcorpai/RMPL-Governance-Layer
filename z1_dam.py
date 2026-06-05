"""
gumbo_dam.py
Coordinator / flow controller for the Gumbo dam layer.

Role:
    Orchestrates ledger, action guard, and reservoir gate.
    Decides whether a request may flow forward into runtime/tool execution/retrieval.

Outputs:
    ALLOW
    STOP_FOR_CLARITY
    BLOCK_DESTRUCTIVE
    LEDGER_CONFLICT
    LEDGER_FAILURE
    RESERVOIR_AUTH_REQUIRED

This file is the implementation-facing version of the RMPL dam spec.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any, Dict, List, Optional

from gumbo_action_guard import ActionDecision, ActionGuard, GuardResult
from rmpl_core import (
    LedgerFailureState,
    load_ledger,
    save_ledger,
    RuntimeMemoryPersistenceLedger,
)


# ---------------------------------------------------------------------------
# Thin adapter: maps gumbo_ledger-style class API onto rmpl_core functions
# so the rest of this file needs no changes.
# ---------------------------------------------------------------------------

class LedgerStatus:
    """Aliases onto LedgerFailureState values expected by GumboDam."""
    OK = LedgerFailureState.AVAILABLE
    UNAVAILABLE = LedgerFailureState.UNAVAILABLE
    CORRUPTED = LedgerFailureState.CORRUPTED
    STALE = LedgerFailureState.STALE
    CONFLICT = LedgerFailureState.CONFLICT


from dataclasses import dataclass as _dc

@_dc
class _LedgerCheckResult:
    status: object
    message: str
    ledger: object = None


class RuntimeLedger:
    """Adapter: wraps rmpl_core load_ledger/save_ledger behind the class API."""

    def load(self) -> _LedgerCheckResult:
        state, ledger, message = load_ledger()
        # Map LedgerFailureState -> LedgerStatus alias
        status_map = {
            LedgerFailureState.AVAILABLE: LedgerStatus.OK,
            LedgerFailureState.UNAVAILABLE: LedgerStatus.UNAVAILABLE,
            LedgerFailureState.CORRUPTED: LedgerStatus.CORRUPTED,
            LedgerFailureState.STALE: LedgerStatus.STALE,
            LedgerFailureState.CONFLICT: LedgerStatus.CONFLICT,
            LedgerFailureState.CAPABILITY_CONFLICT: LedgerStatus.CONFLICT,
        }
        return _LedgerCheckResult(
            status=status_map.get(state, LedgerStatus.UNAVAILABLE),
            message=message,
            ledger=ledger,
        )

    def log_rejected_path(self, action: str, reason: str, context: dict = None) -> None:
        state, ledger, _ = load_ledger()
        if ledger is None:
            return
        ledger.reject_path(path=action[:240], reason=reason)
        save_ledger(ledger, backup=False)
from gumbo_reservoir_gate import ReservoirDecision, ReservoirGate, ReservoirGateResult


class DamDecision(str, Enum):
    ALLOW = "ALLOW"
    STOP_FOR_CLARITY = "STOP_FOR_CLARITY"
    BLOCK_DESTRUCTIVE = "BLOCK_DESTRUCTIVE"
    LEDGER_FAILURE = "LEDGER_FAILURE"
    LEDGER_CONFLICT = "LEDGER_CONFLICT"
    RESERVOIR_AUTH_REQUIRED = "RESERVOIR_AUTH_REQUIRED"


@dataclass
class DamResult:
    decision: DamDecision
    reason: str
    action_guard: Optional[GuardResult] = None
    reservoir_gate: Optional[ReservoirGateResult] = None
    ledger_status: Optional[LedgerStatus] = None
    assumptions: List[str] = field(default_factory=list)
    required_next_step: Optional[str] = None


AMBIGUOUS_ACTION_TERMS = [
    "clean up", "fix", "remove", "archive", "update everything", "sync", "migrate", "restore", "replace", "delete", "handle",
]

RESERVOIR_TERMS = [
    "reservoir", "cold storage", "archive", "old files", "chat history", "dump.txt", ".gsd", "scaffolding files",
]


def _mentions_any(text: str, terms: List[str]) -> bool:
    text = (text or "").lower()
    return any(term in text for term in terms)


def _looks_ambiguous(text: str) -> bool:
    lower = (text or "").lower()
    if _mentions_any(lower, AMBIGUOUS_ACTION_TERMS):
        # If no explicit target/scope markers, stop.
        target_markers = ["file", "folder", "path", "named", "called", "this", "these", "only", "specific"]
        return not any(marker in lower for marker in target_markers)
    return False


class GumboDam:
    def __init__(
        self,
        ledger: Optional[RuntimeLedger] = None,
        action_guard: Optional[ActionGuard] = None,
        reservoir_gate: Optional[ReservoirGate] = None,
        *,
        allow_current_session_without_ledger: bool = True,
    ):
        self.ledger = ledger or RuntimeLedger()
        self.action_guard = action_guard or ActionGuard()
        self.reservoir_gate = reservoir_gate or ReservoirGate()
        self.allow_current_session_without_ledger = allow_current_session_without_ledger

    def inspect_request(
        self,
        request_text: str,
        *,
        confirmation: bool = False,
        inspected_artifact: bool = True,
        requested_reservoir_target: Optional[str] = None,
    ) -> DamResult:
        """
        Classify a request before runtime/tool/retrieval execution.
        This does not execute the request.
        """
        request_text = request_text or ""
        ledger_check = self.ledger.load()

        if ledger_check.status not in {LedgerStatus.OK, LedgerStatus.UNAVAILABLE}:
            return DamResult(
                DamDecision.LEDGER_FAILURE,
                f"Ledger failure: {ledger_check.message}",
                ledger_status=ledger_check.status,
                required_next_step="Stop before acting. Use current-session facts only or restore/update the ledger.",
            )

        if ledger_check.status == LedgerStatus.UNAVAILABLE and not self.allow_current_session_without_ledger:
            return DamResult(
                DamDecision.LEDGER_FAILURE,
                "Ledger unavailable and current-session-only fallback is disabled.",
                ledger_status=ledger_check.status,
                required_next_step="Restore ledger or explicitly authorize current-session-only operation.",
            )

        if _looks_ambiguous(request_text):
            return DamResult(
                DamDecision.STOP_FOR_CLARITY,
                "Instruction contains ambiguous action language without a clear target/scope.",
                ledger_status=ledger_check.status,
                required_next_step="Ask Adam to choose target, scope, and action before executing.",
            )

        guard_result = self.action_guard.classify(
            request_text,
            confirmation=confirmation,
            inspected_artifact=inspected_artifact,
        )
        if guard_result.decision in {ActionDecision.REQUIRE_CONFIRMATION, ActionDecision.BLOCK}:
            try:
                self.ledger.log_rejected_path(
                    action=request_text[:240],
                    reason=guard_result.reason,
                    context={"matched_terms": guard_result.matched_terms},
                )
            except Exception:
                # Never let logging failure become permission to execute.
                pass
            return DamResult(
                DamDecision.BLOCK_DESTRUCTIVE,
                guard_result.reason,
                action_guard=guard_result,
                ledger_status=ledger_check.status,
                required_next_step="Require explicit confirmation or provide a reversible draft/checklist only.",
            )
        if guard_result.decision == ActionDecision.STOP_FOR_CLARITY:
            return DamResult(
                DamDecision.STOP_FOR_CLARITY,
                guard_result.reason,
                action_guard=guard_result,
                ledger_status=ledger_check.status,
                required_next_step="Inspect artifact or ask for target/scope clarification.",
            )

        if _mentions_any(request_text, RESERVOIR_TERMS):
            reservoir_result = self.reservoir_gate.authorize(
                request_text,
                requested_target=requested_reservoir_target,
            )
            if reservoir_result.decision != ReservoirDecision.ALLOW:
                return DamResult(
                    DamDecision.RESERVOIR_AUTH_REQUIRED,
                    reservoir_result.reason,
                    action_guard=guard_result,
                    reservoir_gate=reservoir_result,
                    ledger_status=ledger_check.status,
                    required_next_step="Use OPEN_RESERVOIR: [specific file/folder/request] if cold storage should be accessed.",
                )
            return DamResult(
                DamDecision.ALLOW,
                "Request allowed with scoped reservoir authorization. Label retrieved content as retrieved, not current truth.",
                action_guard=guard_result,
                reservoir_gate=reservoir_result,
                ledger_status=ledger_check.status,
            )

        return DamResult(
            DamDecision.ALLOW,
            "Request allowed by dam inspection.",
            action_guard=guard_result,
            ledger_status=ledger_check.status,
            assumptions=[] if ledger_check.status == LedgerStatus.OK else ["Ledger unavailable; proceeding with current-session context only."],
        )

    def build_runtime_preamble(self) -> str:
        """Small boot preamble for prompt/runtime injection."""
        check = self.ledger.load()
        if check.status != LedgerStatus.OK:
            return (
                f"GUMBO DAM STATUS: {check.status}. {check.message}\n"
                "Use current-session facts only. Do not invent continuity. Stop before destructive or ambiguous actions."
            )
        ledger = check.ledger
        rules = [r.rule for r in getattr(ledger, "runtime_rules", [])]
        task = getattr(ledger, "current_task", "")
        open_loops = getattr(ledger, "open_loops", [])[-5:]
        rejected = getattr(ledger, "rejected_paths", [])[-5:]
        return (
            "GUMBO DAM STATUS: LEDGER_OK\n"
            f"Current task state: {task}\n"
            f"Safety rules: {rules}\n"
            f"Recent open loops: {open_loops}\n"
            f"Recent rejected paths: {rejected}\n"
            "Do not access reservoir without explicit OPEN_RESERVOIR scope. "
            "No confirmation means no destructive execution."
        )
