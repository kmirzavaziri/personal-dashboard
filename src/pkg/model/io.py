from collections.abc import Iterator
from pathlib import Path

import yaml

_LOADER = getattr(yaml, 'CSafeLoader', yaml.SafeLoader)


def read_yaml(path: Path):
    return yaml.load(path.read_text(), Loader=_LOADER) if path.exists() else None


def walk_paths(roots) -> Iterator[Path]:
    for root in roots:
        if root.exists():
            yield from sorted(root.rglob('*.yaml'))
