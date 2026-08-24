from functools import cache

from pkg.model.base import Model


class EdibleCategory(Model):
    SUBDIR = 'edible_categories'

    key: str
    label: str
    order: int
    is_food: bool


class ClothingSection(Model):
    SUBDIR = 'clothing_sections'

    key: str
    label: str
    order: int
    aliases: tuple[str, ...]


@cache
def _edibles() -> tuple[EdibleCategory, ...]:
    return tuple(sorted(EdibleCategory.objects.all(), key=lambda c: c.order))


@cache
def _sections() -> tuple[ClothingSection, ...]:
    return tuple(sorted(ClothingSection.objects.all(), key=lambda s: s.order))


def edible_categories() -> tuple[EdibleCategory, ...]:
    return _edibles()


def edible_label(key: str) -> str:
    for c in _edibles():
        if c.key == key:
            return c.label
    return key.capitalize()


def food_categories() -> tuple[EdibleCategory, ...]:
    return tuple(c for c in _edibles() if c.is_food)


def clothing_sections() -> tuple[ClothingSection, ...]:
    return _sections()


def clothing_section_of(category: str) -> str:
    for s in _sections():
        if category == s.key or category in s.aliases:
            return s.key
    return 'other'
