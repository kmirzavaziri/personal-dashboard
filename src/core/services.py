from dataclasses import dataclass

from core.config import Config
from core.gitdata import GitData
from pkg.model.base import Model


@dataclass(frozen=True)
class Services:
    config: Config
    git: GitData | None = None

    @classmethod
    def build(cls, config: Config) -> 'Services':
        Model.bind(config.db)
        return cls(config=config)
