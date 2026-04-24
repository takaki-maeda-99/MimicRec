# Plan A Execution Notes

Running log of decisions, workarounds, and follow-ups surfaced during Plan A
execution. The plan itself is the source of truth for *what* to build; this
file is the source of truth for *how we had to set things up*, plus known
issues deferred to later plans.

## Environment setup

Repo root: `/home/takakimaeda/MimicRec`. Plan A runs entirely against `main`.

### Editable installs needed

```bash
# In /home/takakimaeda/MimicRec
uv venv .venv
uv pip install -e './lerobot[dataset]'    # dataset extra is mandatory, see below
uv pip install -e './backend[dev]'
```

**Do not `uv pip install -e ./reBotArm_control_py`.** Its packaging is broken
(flat-layout with multiple top-level packages — `urdf/`, `config/`,
`reBotArm_control_py/`). Plan A only needs a stub adapter for this robot, not
a real import, so installation is unnecessary and the failure is fine to
leave untouched until Plan D. See "Deferred to Plan D" below.

**Do not forget the `[dataset]` extra on `lerobot`.** Without it,
`from lerobot.datasets.lerobot_dataset import LeRobotDataset` raises
`'datasets' is required but not installed` and the Task 0 / Task 1 / Task 5
compatibility checks silently skip instead of verifying the API surface.
We intentionally do not pin this in `backend/pyproject.toml` because `lerobot`
is a sibling editable clone, not a publishable dependency.

### Running pytest

Always invoke tests via the in-repo wrapper:

```bash
scripts/test.sh -v tests/...
```

`scripts/test.sh` drops `PYTHONPATH` (which the host's ROS 2 install
populates with `/opt/ros/humble/...`) and sets `PYTHONNOUSERSITE=1` so that
any `~/.local/lib/python3.10/site-packages/` leftovers cannot shadow the
editable installs in `.venv`. Do not run `uv run pytest` or bare `pytest`
inside this repo — both have been observed to pick up host packages that
break test collection.

## Decisions taken during execution

- **RAW parquet + MP4 path vs. wrapping `lerobot.datasets.DatasetWriter`.**
  Task 1 decided this via the spike. The decision and its rationale go in
  the Task 1 commit message; this note is a placeholder until the spike
  lands.

## Deferred to later plans

### Plan D (real-hardware bring-up) concerns

- **`reBotArm_control_py` is not `pip install -e` -able.** Flat-layout
  discovers three top-level packages and setuptools refuses. Before Plan D
  can wire the real reBotArm adapter, this needs a `src/` layout, explicit
  `[tool.setuptools.packages.find]`, or migration to hatchling. Plan A only
  needs the offline `ReBotArmAdapter` stub so this does not block anything
  here.
- **SO-101 gravity comp** remains explicitly not supported (see spec §15).
  Plan A enforces this via `supports_mode` and the HTTP-422 precheck path.

### Plan B (HTTP/WS surface) concerns

- Domain exceptions produced by Plan A (`HandTeachNotSupportedError`,
  `InvalidTransitionError`, `HardwareError`, `RecorderError`,
  `ReplaySafetyError`) are bare raises; Plan B must translate them to
  HTTP 422/409/500 in the FastAPI error-handler layer.

### Plan C (frontend) concerns

- None recorded yet.
