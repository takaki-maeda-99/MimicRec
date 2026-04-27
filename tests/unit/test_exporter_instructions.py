from mimicrec.datasets.exporters.instructions import (
    expand_instruction,
    InstructionWarning,
)


def test_expand_with_instruction_filled():
    out = expand_instruction(
        template="What action should the robot take to {TASK}? A:",
        task_name="tape_on_bottle",
        instruction="Pick up the tape and place it on top of the bottle",
    )
    assert out.text == (
        "What action should the robot take to "
        "Pick up the tape and place it on top of the bottle? A:"
    )
    assert out.warnings == []


def test_expand_falls_back_to_task_name_when_instruction_empty():
    out = expand_instruction(
        template="What action should the robot take to {TASK}? A:",
        task_name="tape_on_bottle",
        instruction="",
    )
    assert "tape_on_bottle" in out.text
    assert out.warnings == [
        InstructionWarning.MISSING_INSTRUCTION_FALLBACK_TO_TASK_NAME
    ]


def test_expand_falls_back_when_instruction_is_none():
    out = expand_instruction(
        template="do {TASK}",
        task_name="x",
        instruction=None,
    )
    assert out.text == "do x"
    assert out.warnings == [
        InstructionWarning.MISSING_INSTRUCTION_FALLBACK_TO_TASK_NAME
    ]


def test_template_without_task_placeholder_is_used_verbatim():
    out = expand_instruction(
        template="static prompt",
        task_name="anything",
        instruction="anything",
    )
    assert out.text == "static prompt"
    assert out.warnings == []


def test_template_with_multiple_placeholders_replaces_all():
    out = expand_instruction(
        template="{TASK} then {TASK}",
        task_name="x",
        instruction="grab the cube",
    )
    assert out.text == "grab the cube then grab the cube"
