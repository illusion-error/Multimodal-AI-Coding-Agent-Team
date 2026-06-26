"""Prompt version helpers used by the workflow package."""

from __future__ import annotations

from typing import Dict


DEFAULT_PROMPT_VERSIONS = {
    "recognition": "v1-default",
    "planning": "v1-default",
    "test_generation": "v1-default",
    "code_generation": "v1-default",
    "debugging": "v1-default",
    "reflection": "v1-default",
}


def format_prompt_versions(prompt_versions: Dict[str, str]) -> str:
    if not prompt_versions:
        return ""
    lines = ["", "## Active Prompt Versions"]
    for agent, version in sorted(prompt_versions.items()):
        lines.append(f"- {agent}: {version}")
    return "\n".join(lines)
