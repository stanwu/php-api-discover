"""mock.py — Mock agent adapter for deterministic testing.

Reads response from --mock-response-file instead of calling a real CLI.
Only available when --agent mock is specified.
"""

from __future__ import annotations

from pathlib import Path

from .base import AgentAdapter, AgentError

DEFAULT_MODEL = "mock-1.0"


class MockAdapter(AgentAdapter):
    name = "mock"

    def __init__(self, response_file: str | None = None) -> None:
        self._response_file = response_file

    @property
    def default_model(self) -> str:
        return DEFAULT_MODEL

    def build_command(self, prompt: str, model: str | None) -> list[str]:
        # Mock adapter does not use subprocess; this list is never actually executed.
        return ["mock-agent", "--response-file", self._response_file or ""]

    def parse_response(self, stdout: str, stderr: str, returncode: int) -> str:
        # For mock, stdout IS the file contents (set by agent_runner).
        if returncode != 0:
            raise AgentError(f"Mock agent returned non-zero exit code {returncode}")
        return stdout

    def read_response_file(self) -> str:
        """Read the mock response file and return its contents."""
        if not self._response_file:
            raise AgentError("--mock-response-file is required when --agent mock is used")
        p = Path(self._response_file)
        if not p.exists():
            raise AgentError(f"Mock response file not found: {self._response_file}")
        return p.read_text(encoding="utf-8")
