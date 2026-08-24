from dataclasses import dataclass

from core.item.item import Item
from core.item.sourcing import effective_servings, pick_cheapest_source, source_url
from core.store.source import Source


@dataclass
class ScheduledItem:
    item: Item
    servings_per_week: int
    occasions: list

    @property
    def key(self) -> str:
        return self.item.key

    @property
    def kind(self) -> str:
        return self.item.kind

    @property
    def short_name(self) -> str:
        return self.item.short_name

    @property
    def name(self) -> str:
        return self.item.name

    @property
    def notes(self) -> str:
        return self.item.notes

    @property
    def image(self) -> str:
        return self.item.image

    @property
    def status(self) -> str:
        return self.item.status

    @property
    def sources(self) -> list[Source]:
        return self.item.sources

    @property
    def metadata(self) -> Item.Metadata:
        return self.item.metadata

    @property
    def chosen_source(self) -> Source | None:
        return pick_cheapest_source(self.item.sources, self.servings_per_week or 7, self.item.metadata.edible.ml_per_serving)

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
    def servings_per_item(self) -> int:
        src = self.chosen_source
        if not src:
            return 1
        return effective_servings(src, self.item.metadata.edible.ml_per_serving) or 1

    @property
    def price_per_serving(self) -> float | None:
        p = self.price
        s = self.servings_per_item
        if p is None or s == 0:
            return None
        return p / s

    @property
    def price_per_week(self) -> float | None:
        pps = self.price_per_serving
        if pps is None:
            return None
        return pps * self.servings_per_week

    @property
    def price_per_month(self) -> float | None:
        ppw = self.price_per_week
        if ppw is None:
            return None
        return ppw * (30 / 7)

    @property
    def items_per_week(self) -> float | None:
        if self.servings_per_item == 0 or self.servings_per_week == 0:
            return None
        return self.servings_per_week / self.servings_per_item

    @property
    def items_per_month(self) -> float | None:
        if self.servings_per_item == 0 or self.servings_per_week == 0:
            return None
        return self.servings_per_week * (30 / 7) / self.servings_per_item

    @property
    def price_per_protein_g(self) -> float | None:
        pps = self.price_per_serving
        protein = (self.item.metadata.edible.nutrition or {}).get('protein_g')
        if pps is None or not protein:
            return None
        return pps / protein
