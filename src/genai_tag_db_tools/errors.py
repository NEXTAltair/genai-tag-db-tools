"""Structured CLI error contract for tag-db (Issue #31).

The CLI maps any failure to a stable error-code set and a fixed exit-code
policy so agents can decide programmatically (without parsing stderr text) and
humans can still read the reason. The final stdout line on failure is a single
``{"kind": "error", ...}`` JSON object (see ``cli.emit_error``).

Exit-code policy:
    0 = success
    2 = input / validation error (``INVALID_INPUT`` / ``VALIDATION_FAILED``)
    1 = runtime error (everything else)
"""

from __future__ import annotations

from dataclasses import dataclass

# Standard error codes (machine-readable, stable identifiers).
INVALID_INPUT = "INVALID_INPUT"
VALIDATION_FAILED = "VALIDATION_FAILED"
PRECONDITION_FAILED = "PRECONDITION_FAILED"
NOT_FOUND = "NOT_FOUND"
ALREADY_EXISTS = "ALREADY_EXISTS"
CONFLICT = "CONFLICT"
IO_ERROR = "IO_ERROR"
NETWORK_ERROR = "NETWORK_ERROR"
DB_ERROR = "DB_ERROR"
TIMEOUT = "TIMEOUT"
INTERNAL_ERROR = "INTERNAL_ERROR"

EXIT_SUCCESS = 0
EXIT_RUNTIME_ERROR = 1
EXIT_INPUT_ERROR = 2

# Codes that represent a bad request from the caller (exit code 2).
_INPUT_CODES = frozenset({INVALID_INPUT, VALIDATION_FAILED})

# Short, machine/human friendly hints per code (optional).
_HINTS: dict[str, str] = {
    PRECONDITION_FAILED: "Initialize the database first (run 'tag-db ensure-dbs' or pass --base-db / --user-db-dir).",
    NETWORK_ERROR: "Check network connectivity and the Hugging Face token.",
}


@dataclass(frozen=True)
class ErrorInfo:
    """Classification result for a raised exception.

    Args:
        code: One of the standard error-code constants in this module.
        retryable: Whether retrying the same command may succeed (transient).
        user_action_required: Whether the caller must change input or fix a
            precondition before retrying.
    """

    code: str
    retryable: bool
    user_action_required: bool

    @property
    def exit_code(self) -> int:
        """Return the process exit code per the fixed policy."""
        return EXIT_INPUT_ERROR if self.code in _INPUT_CODES else EXIT_RUNTIME_ERROR


def hint_for(code: str) -> str | None:
    """Return a short remediation hint for a code, if one is defined."""
    return _HINTS.get(code)


def _module_chain_matches(exc: BaseException, prefixes: tuple[str, ...]) -> bool:
    """True if any class in the exception MRO comes from one of ``prefixes``."""
    return any(cls.__module__.startswith(prefixes) for cls in type(exc).__mro__)


def _is_network_error(exc: BaseException) -> bool:
    # Match by module so we do not import huggingface_hub / requests eagerly.
    if _module_chain_matches(exc, ("requests", "urllib3", "huggingface_hub", "http.client")):
        return True
    network_names = {"HfHubHTTPError", "LocalEntryNotFoundError", "OfflineModeIsEnabled"}
    return any(cls.__name__ in network_names for cls in type(exc).__mro__)


def _is_db_error(exc: BaseException) -> bool:
    return _module_chain_matches(exc, ("sqlalchemy",))


def classify_exception(exc: BaseException) -> ErrorInfo:
    """Map a raised exception to a stable :class:`ErrorInfo`.

    Order matters: pydantic ``ValidationError`` and ``FileNotFoundError`` are
    subclasses of ``ValueError`` / ``OSError`` respectively, so they are checked
    before their base classes.
    """
    # Pydantic ValidationError is a subclass of ValueError; check it first.
    if type(exc).__name__ == "ValidationError" and _module_chain_matches(exc, ("pydantic",)):
        return ErrorInfo(VALIDATION_FAILED, retryable=False, user_action_required=True)
    if _is_network_error(exc):
        return ErrorInfo(NETWORK_ERROR, retryable=True, user_action_required=False)
    if _is_db_error(exc):
        return ErrorInfo(DB_ERROR, retryable=False, user_action_required=False)
    if isinstance(exc, ValueError):
        return ErrorInfo(INVALID_INPUT, retryable=False, user_action_required=True)
    if isinstance(exc, TimeoutError):
        return ErrorInfo(TIMEOUT, retryable=True, user_action_required=False)
    if isinstance(exc, FileNotFoundError):
        return ErrorInfo(IO_ERROR, retryable=False, user_action_required=True)
    if isinstance(exc, RuntimeError):
        # runtime.py raises RuntimeError when DB engine / user DB is not initialized.
        return ErrorInfo(PRECONDITION_FAILED, retryable=False, user_action_required=True)
    if isinstance(exc, OSError):
        return ErrorInfo(IO_ERROR, retryable=False, user_action_required=True)
    return ErrorInfo(INTERNAL_ERROR, retryable=False, user_action_required=False)
