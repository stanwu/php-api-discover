"""claude.py — Claude CLI adapter."""

from __future__ import annotations

from .base import AgentAdapter, AgentError

SUPPORTED_MODELS = ["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5"]
DEFAULT_MODEL    = "claude-opus-4-5"


class ClaudeAdapter(AgentAdapter):
    name = "claude"

    @property
    def default_model(self) -> str:
        return DEFAULT_MODEL

    def build_command(self, prompt: str, model: str | None) -> list[str]:
        return [
            "claude",
            "--print",
            "--model", model or DEFAULT_MODEL,
            "-p", prompt,
        ]

    def parse_response(self, stdout: str, stderr: str, returncode: int) -> str:
        if returncode != 0:
            excerpt = stderr[:500] if stderr else "(no stderr)"
            raise AgentError(
                f"Claude exited with code {returncode}. stderr: {excerpt}"
            )
        if not stdout.strip():
            raise AgentError("Claude returned empty output.")
        return stdout
