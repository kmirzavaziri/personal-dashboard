from collections.abc import Iterator
from pathlib import Path

import yaml


def read_yaml(path: Path):
    return yaml.safe_load(path.read_text()) if path.exists() else None


def walk_paths(roots) -> Iterator[Path]:
    for root in roots:
        if root.exists():
            yield from sorted(root.rglob('*.yaml'))
