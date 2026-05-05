from __future__ import annotations
from pathlib import Path

from mimicrec.inference.contract import ContractSpec


def list_inference_configs(configs_root: Path) -> list[dict]:
    d = configs_root / "inference"
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("*.yaml")):
        spec = ContractSpec.from_yaml_text(p.read_text())
        out.append({"name": spec.name, "description": spec.description})
    return out


def load_inference_config(configs_root: Path, name: str) -> ContractSpec:
    p = configs_root / "inference" / f"{name}.yaml"
    if not p.exists():
        raise FileNotFoundError(p)
    return ContractSpec.from_yaml_text(p.read_text())
