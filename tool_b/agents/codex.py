"""codex.py — Codex CLI adapter."""

from __future__ import annotations

from .base import AgentAdapter, AgentError

SUPPORTED_MODELS = ["gpt-4o", "gpt-4o-mini", "o3", "o4-mini"]
DEFAULT_MODEL    = "gpt-4o"


class CodexAdapter(AgentAdapter):
    name = "codex"

    @property
    def default_model(self) -> str:
        return DEFAULT_MODEL

    def build_command(self, prompt: str, model: str | None) -> list[str]:
        return [
            "codex",
            "--model",           model or DEFAULT_MODEL,
            "--quiet",
            "--full-auto",
            "--approval-policy", "auto-edit",
            "-p",                prompt,
        ]

    def parse_response(self, stdout: str, stderr: str, returncode: int) -> str:
        if returncode != 0:
            excerpt = stderr[:500] if stderr else "(no stderr)"
            raise AgentError(
                f"Codex exited with code {returncode}. stderr: {excerpt}"
            )
        if not stdout.strip():
            raise AgentError("Codex returned empty output.")
        return stdout
