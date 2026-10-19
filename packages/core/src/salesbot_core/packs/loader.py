"""Load and validate industry packs from YAML."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from salesbot_core.packs.schema import Pack

# PACKS_DIR overrides (used in Docker images). Otherwise packs/ at the repo root, which is
# 5 levels above packages/core/src/salesbot_core/packs/loader.py.
DEFAULT_PACKS_DIR = Path(
    os.environ.get("PACKS_DIR") or Path(__file__).resolve().parents[5] / "packs"
)


def load_pack(path: str | Path) -> Pack:
    with Path(path).open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return Pack.model_validate(data)


def load_pack_by_id(pack_id: str, packs_dir: Path = DEFAULT_PACKS_DIR) -> Pack:
    pack = load_pack(packs_dir / f"{pack_id}.yaml")
    if pack.id != pack_id:
        raise ValueError(f"pack file {pack_id}.yaml declares id '{pack.id}'")
    return pack


def load_all_packs(packs_dir: Path = DEFAULT_PACKS_DIR) -> dict[str, Pack]:
    return {p.id: p for p in (load_pack(f) for f in sorted(packs_dir.glob("*.yaml")))}
