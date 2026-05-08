from __future__ import annotations
import logging
from pathlib import Path

from mimicrec.inference.contract import ContractSpec

logger = logging.getLogger(__name__)


def list_inference_configs(configs_root: Path) -> list[dict]:
    d = configs_root / "inference"
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("*.yaml")):
        # `name` is always the file stem because that is what
        # load_inference_config() looks up by — using spec.name here would
        # let the list return identifiers the loader can't resolve.
        try:
            spec = ContractSpec.from_yaml_text(p.read_text())
            out.append({
                "name": p.stem,
                "title": spec.name,
                "description": spec.description,
            })
        except Exception as e:
            # One broken contract YAML must not blank the whole inference page;
            # surface it instead so the operator can still see other contracts
            # and knows which one needs attention.
            logger.warning("inference contract %s failed to parse: %s", p.name, e)
            out.append({
                "name": p.stem,
                "title": p.stem,
                "description": f"⚠ failed to load: {e}",
                "error": str(e),
            })
    return out


def load_inference_config(configs_root: Path, name: str) -> ContractSpec:
    p = configs_root / "inference" / f"{name}.yaml"
    if not p.exists():
        raise FileNotFoundError(p)
    return ContractSpec.from_yaml_text(p.read_text())
