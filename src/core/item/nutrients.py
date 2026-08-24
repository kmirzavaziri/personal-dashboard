from functools import cache

from pkg.model.base import Model


class Nutrient(Model):
    SUBDIR = 'nutrients'

    key: str
    label: str
    unit: str


@cache
def _registry() -> dict[str, Nutrient]:
    return {n.key: n for n in Nutrient.objects.all()}


def nutrient(key: str) -> Nutrient:
    return _registry().get(key) or Nutrient(key=key, label=key.replace('_', ' '), unit='')
