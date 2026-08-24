import re
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from core.item.sourcing import pick_cheapest_source, source_url
from core.store.source import Source
from pkg.model.base import Model


class Item(Model):
    class Search(BaseModel):
        model_config = ConfigDict(extra='forbid')

        query: str = ''
        sources: list[str] = []

    class Edible(BaseModel):
        model_config = ConfigDict(extra='forbid')

        serving_size: str = ''
        nutrition: dict = {}
        category: str = ''
        locations: list[str] = []
        subcategory: str = ''
        has: list[str] = []
        track_only: bool = False
        default_weekly_uses: int = 0
        ml_per_serving: float | None = None

    class Durable(BaseModel):
        model_config = ConfigDict(extra='forbid')

    class Clothing(BaseModel):
        model_config = ConfigDict(extra='forbid')

        brand: str = ''
        category: str = ''
        size_ok: bool | None = None
        goal: str = ''
        flags: list[str] = []

    class Metadata(BaseModel):
        model_config = ConfigDict(extra='forbid')

        edible: 'Item.Edible | None' = None
        durable: 'Item.Durable | None' = None
        clothing: 'Item.Clothing | None' = None

    SUBDIR: ClassVar[str] = 'items'

    key: str
    kind: str
    short_name: str = ''
    name: str = ''
    notes: str = ''
    image: str = ''
    status: str = ''
    search: Search = Search()
    sources: list[Source] = []
    metadata: Metadata = Field(default_factory=Metadata)

    @property
    def chosen_source(self) -> Source | None:
        if self.kind == 'edible':
            return pick_cheapest_source(self.sources, 7, self.metadata.edible.ml_per_serving)
        if self.kind == 'durable':
            priced = [s for s in self.sources if s.price is not None]
            return min(priced, key=lambda s: s.price) if priced else None
        return self.sources[0] if self.sources else None

    @property
    def price(self) -> float | None:
        src = self.chosen_source
        return src.price if src else None

    @property
    def url(self) -> str:
        return source_url(self.chosen_source)

    @property
    def source_title(self) -> str:
        src = self.chosen_source
        return (src.title or src.store.display) if src else ''

    @property
    def store_display(self) -> str:
        src = self.chosen_source
        return src.store.display if src else ''

    @property
    def garment_count(self) -> int:
        match = (
            re.search(r'(\d+)\s*[- ]?(?:[Pp]ack|[Pp]airs?)\b', self.name)
            or re.search(r'pack of (\d+)', self.name, re.IGNORECASE)
        )
        return int(match.group(1)) if match else 1


Item.Metadata.model_rebuild()
Item.model_rebuild()
