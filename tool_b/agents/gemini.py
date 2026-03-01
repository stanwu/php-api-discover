"""gemini.py — Gemini CLI adapter."""

from __future__ import annotations

from .base import AgentAdapter, AgentError

SUPPORTED_MODELS = ["gemini-2.0-flash", "gemini-2.5-pro"]
DEFAULT_MODEL    = "gemini-2.0-flash"


class GeminiAdapter(AgentAdapter):
    name = "gemini"

    @property
    def default_model(self) -> str:
        return DEFAULT_MODEL

    def build_command(self, prompt: str, model: str | None) -> list[str]:
        return [
            "gemini",
            "--model", model or DEFAULT_MODEL,
            "-p",      prompt,
        ]

    def parse_response(self, stdout: str, stderr: str, returncode: int) -> str:
        if returncode != 0:
            excerpt = stderr[:500] if stderr else "(no stderr)"
            raise AgentError(
                f"Gemini exited with code {returncode}. stderr: {excerpt}"
            )
        if not stdout.strip():
            raise AgentError("Gemini returned empty output.")
        return stdout
