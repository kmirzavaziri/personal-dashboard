from pathlib import Path
from typing import Callable, ClassVar, Self

import yaml
from pydantic import BaseModel, ConfigDict, PrivateAttr

from pkg.model.io import read_yaml, walk_paths


class DoesNotExist(Exception):
    pass


class Manager:
    def __init__(self, model: type['Model']):
        self._model = model

    def all(self) -> list:
        return [model for path in walk_paths((self._model.directory(),)) for model in self._model.from_file(path)]

    def filter(self, **query) -> list:
        return [model for model in self.all() if all(getattr(model, field) == value for field, value in query.items())]

    def get(self, **query):
        matches = self.filter(**query)
        if not matches:
            raise DoesNotExist(f'{self._model.__name__} {query}')
        return matches[0]

    def get_or_none(self, **query):
        matches = self.filter(**query)
        return matches[0] if matches else None


class ManagerProperty:
    def __get__(self, instance, owner) -> Manager:
        return Manager(owner)


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid')

    SUBDIR: ClassVar[str]
    objects: ClassVar[Manager] = ManagerProperty()
    _db_root: ClassVar[Path | None] = None
    _on_change: ClassVar[Callable[[], None] | None] = None
    _path: Path | None = PrivateAttr(default=None)

    @classmethod
    def bind(cls, db_root: Path) -> None:
        Model._db_root = db_root

    @classmethod
    def on_change(cls, callback: Callable[[], None] | None) -> None:
        Model._on_change = callback

    @staticmethod
    def _changed() -> None:
        if Model._on_change is not None:
            Model._on_change()

    @classmethod
    def directory(cls) -> Path:
        return cls._db_root / cls.SUBDIR

    @classmethod
    def from_file(cls, path: Path) -> list[Self]:
        raw = read_yaml(path)
        rows = raw if isinstance(raw, list) else [raw or {}]
        models = []
        for row in rows:
            model = cls.model_validate(row)
            model._path = path
            models.append(model)
        return models

    def to_dict(self) -> dict:
        return self.model_dump(exclude_defaults=True)

    def save(self) -> None:
        path = self._path or self.directory() / f'{self.key}.yaml'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'# {self.key}\n' + yaml.dump(self.to_dict(), allow_unicode=True, sort_keys=False))
        self._path = path
        Model._changed()

    def delete(self) -> None:
        if self._path and self._path.exists():
            self._path.unlink()
        self._path = None
        Model._changed()
