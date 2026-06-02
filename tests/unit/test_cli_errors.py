"""Unit tests for the structured CLI error contract (Issue #31).

Covers:
- errors.classify_exception: exception -> stable error code mapping
- errors.ErrorInfo.exit_code: 0/2/1 exit-code policy
- cli.emit_error: structured error JSONL line
- cli.main: top-level boundary maps failures to an error line + exit code
"""

from __future__ import annotations

import json
import sys

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import SQLAlchemyError

import genai_tag_db_tools.cli as cli
from genai_tag_db_tools import errors


def _make_validation_error() -> ValidationError:
    class _Model(BaseModel):
        value: int

    try:
        _Model(value="not-an-int")  # type: ignore[arg-type]
    except ValidationError as exc:
        return exc
    raise AssertionError("ValidationError was not raised")


class TestClassifyException:
    """Test errors.classify_exception mapping."""

    def test_value_error_is_invalid_input(self) -> None:
        info = errors.classify_exception(ValueError("bad"))
        assert info.code == errors.INVALID_INPUT
        assert info.exit_code == 2

    def test_pydantic_validation_error_is_validation_failed(self) -> None:
        info = errors.classify_exception(_make_validation_error())
        assert info.code == errors.VALIDATION_FAILED
        assert info.exit_code == 2

    def test_runtime_error_is_precondition_failed(self) -> None:
        info = errors.classify_exception(RuntimeError("DB not initialized"))
        assert info.code == errors.PRECONDITION_FAILED
        assert info.exit_code == 1
        assert info.user_action_required is True

    def test_file_not_found_is_io_error(self) -> None:
        info = errors.classify_exception(FileNotFoundError("missing.sqlite"))
        assert info.code == errors.IO_ERROR
        assert info.exit_code == 1

    def test_sqlalchemy_error_is_db_error(self) -> None:
        info = errors.classify_exception(SQLAlchemyError("db blew up"))
        assert info.code == errors.DB_ERROR
        assert info.exit_code == 1

    def test_network_error_matched_by_module(self) -> None:
        class _FakeHfError(Exception):
            pass

        _FakeHfError.__module__ = "huggingface_hub.errors"
        info = errors.classify_exception(_FakeHfError("offline"))
        assert info.code == errors.NETWORK_ERROR
        assert info.retryable is True

    def test_unknown_exception_is_internal_error(self) -> None:
        info = errors.classify_exception(KeyError("type"))
        assert info.code == errors.INTERNAL_ERROR
        assert info.exit_code == 1


class TestEmitError:
    """Test cli.emit_error output."""

    def test_emit_error_structured_line(self, capsys: pytest.CaptureFixture[str]) -> None:
        cli.emit_error(
            errors.PRECONDITION_FAILED,
            "DB not initialized",
            retryable=False,
            user_action_required=True,
            hint="run ensure-dbs",
        )
        output = json.loads(capsys.readouterr().out)
        assert output["kind"] == "error"
        assert output["ok"] is False
        assert output["code"] == "PRECONDITION_FAILED"
        assert output["message"] == "DB not initialized"
        assert output["retryable"] is False
        assert output["user_action_required"] is True
        assert output["hint"] == "run ensure-dbs"

    def test_emit_error_omits_optional_fields(self, capsys: pytest.CaptureFixture[str]) -> None:
        cli.emit_error(
            errors.INTERNAL_ERROR,
            "boom",
            retryable=False,
            user_action_required=False,
        )
        output = json.loads(capsys.readouterr().out)
        assert "hint" not in output
        assert "details" not in output


class TestMainErrorBoundary:
    """Test cli.main maps handler failures to a structured error final line."""

    def _run_main_expecting_exit(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        exc: Exception,
    ) -> tuple[int, dict]:
        def boom(_args: object) -> None:
            raise exc

        monkeypatch.setattr(cli, "cmd_stats", boom)
        monkeypatch.setattr(sys, "argv", ["tag-db", "stats"])

        with pytest.raises(SystemExit) as exit_info:
            cli.main()

        lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
        return int(exit_info.value.code or 0), json.loads(lines[-1])

    def test_value_error_maps_to_invalid_input_exit_2(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code, error = self._run_main_expecting_exit(monkeypatch, capsys, ValueError("bad input"))
        assert exit_code == 2
        assert error["kind"] == "error"
        assert error["code"] == "INVALID_INPUT"
        assert error["message"] == "bad input"

    def test_runtime_error_maps_to_precondition_failed_exit_1(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code, error = self._run_main_expecting_exit(
            monkeypatch, capsys, RuntimeError("user DB not initialized")
        )
        assert exit_code == 1
        assert error["code"] == "PRECONDITION_FAILED"
        assert error["hint"]  # remediation hint present

    def test_unexpected_error_maps_to_internal_error_exit_1(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code, error = self._run_main_expecting_exit(monkeypatch, capsys, KeyError("type"))
        assert exit_code == 1
        assert error["code"] == "INTERNAL_ERROR"
