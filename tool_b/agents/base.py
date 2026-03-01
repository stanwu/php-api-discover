"""base.py — Abstract AgentAdapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class AgentError(Exception):
    """Raised when the agent subprocess fails or returns unusable output."""


class AgentAdapter(ABC):
    """Abstract base for all AI agent CLI adapters."""

    name: str = ""  # identifier used in --agent flag and _tool_b_meta

    @abstractmethod
    def build_command(self, prompt: str, model: str | None) -> list[str]:
        """Return subprocess argv list for calling the agent CLI."""

    @abstractmethod
    def parse_response(self, stdout: str, stderr: str, returncode: int) -> str:
        """
        Extract the raw text content from agent output.

        Returns the agent's text reply as a string.
        Raises AgentError on failure (non-zero return code, empty output, etc.).
        """

    @property
    @abstractmethod
    def default_model(self) -> str:
        """Return the default model name for this adapter."""
