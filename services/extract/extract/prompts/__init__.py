from __future__ import annotations

from dataclasses import dataclass

from extract.prompts import v1


@dataclass(frozen=True)
class Prompt:
    version: str
    system: str
    instructions: str


PROMPTS: dict[str, Prompt] = {
    "v1": Prompt("v1", v1.SYSTEM, v1.INSTRUCTIONS),
}


def get_prompt(version: str) -> Prompt:
    try:
        return PROMPTS[version]
    except KeyError as exc:
        raise ValueError(f"unknown prompt version {version}; known: {sorted(PROMPTS)}") from exc
