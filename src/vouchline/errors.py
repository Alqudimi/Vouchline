"""Stable errors shared by the library and CLI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ErrorInfo:
    code: str
    message: str
    details: dict[str, Any]
    exit_code: int


class VouchlineError(Exception):
    """Base class for expected, user-actionable failures."""

    code = "VOUCHLINE_ERROR"
    exit_code = 5

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def info(self) -> ErrorInfo:
        return ErrorInfo(self.code, self.message, self.details, self.exit_code)


class InputError(VouchlineError):
    code = "INVALID_INPUT"
    exit_code = 2


class IntegrityError(VouchlineError):
    code = "INTEGRITY_FAILURE"
    exit_code = 3


class ReplayError(VouchlineError):
    code = "REPLAY_FAILURE"
    exit_code = 4


class PolicyError(VouchlineError):
    code = "POLICY_FAILURE"
    exit_code = 4


class LimitError(InputError):
    code = "INPUT_LIMIT_EXCEEDED"
