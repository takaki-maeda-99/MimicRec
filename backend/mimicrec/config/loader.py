from __future__ import annotations
from pathlib import Path

from omegaconf import DictConfig, OmegaConf


def load_session_config(session_yaml: Path, configs_root: Path) -> DictConfig:
    cfg = OmegaConf.load(session_yaml)
    defaults = cfg.pop("defaults", {}) if "defaults" in cfg else {}
    for group, ref in defaults.items():
        folder = configs_root / group
        if isinstance(ref, list) or OmegaConf.is_list(ref):
            resolved = {}
            for name in ref:
                path = folder / f"{name}.yaml"
                if not path.exists():
                    raise FileNotFoundError(f"config {group}/{name}.yaml not found at {path}")
                resolved[name] = OmegaConf.load(path)
            cfg[group] = OmegaConf.create(resolved)
        else:
            path = folder / f"{ref}.yaml"
            if not path.exists():
                raise FileNotFoundError(f"config {group}/{ref}.yaml not found at {path}")
            cfg[group] = OmegaConf.load(path)
    OmegaConf.resolve(cfg)
    return cfg
