"""Instruction-template expansion for VLA-compat export.

Pure: no I/O, deterministic, inputs not mutated.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class InstructionWarning(str, Enum):
    MISSING_INSTRUCTION_FALLBACK_TO_TASK_NAME = (
        "missing_instruction_fallback_to_task_name"
    )


@dataclass(frozen=True)
class ExpandedInstruction:
    text: str
    warnings: list[InstructionWarning] = field(default_factory=list)


def expand_instruction(
    *,
    template: str,
    task_name: str,
    instruction: str | None,
) -> ExpandedInstruction:
    """Expand ``{TASK}`` in ``template`` using ``instruction`` (preferred) or
    ``task_name`` (fallback). Returns the rendered string plus any warnings.
    """
    warnings: list[InstructionWarning] = []
    chosen = instruction if instruction else None
    if chosen is None:
        chosen = task_name
        warnings.append(
            InstructionWarning.MISSING_INSTRUCTION_FALLBACK_TO_TASK_NAME
        )
    text = template.replace("{TASK}", chosen)
    return ExpandedInstruction(text=text, warnings=warnings)
