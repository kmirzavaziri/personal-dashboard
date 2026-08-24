from core.store.registry import STORES
from core.store.source import Source

PREF_THRESHOLD_AED_MONTH = 1.0


def store_pref_rank(slug: str) -> int:
    return STORES.resolve(slug).pref


def source_url(src: Source | None) -> str:
    if not src:
        return ''
    if src.url:
        return src.url
    return src.store.url(src.sku or src.id)


def effective_servings(src: Source, ml_per_serving: float | None) -> int | None:
    if src.servings_per_item is not None:
        return src.servings_per_item
    if src.size_ml and ml_per_serving:
        return round(src.size_ml / ml_per_serving)
    return None


def pick_cheapest_source(sources: list[Source], weekly_servings_hint: int, ml_per_serving: float | None) -> Source | None:
    if not sources:
        return None
    w = max(weekly_servings_hint, 1)

    def ppm(src: Source) -> float:
        servings = effective_servings(src, ml_per_serving)
        if not src.price or not servings:
            return float('inf')
        return src.price / servings * w * (30 / 7)

    priced = [s for s in sources if ppm(s) < float('inf') and not s.out_of_stock]
    if not priced:
        return sources[0]

    min_ppm = min(ppm(s) for s in priced)
    candidates = [s for s in priced if ppm(s) - min_ppm <= PREF_THRESHOLD_AED_MONTH]
    candidates.sort(key=lambda s: store_pref_rank(s.store.slug))
    return candidates[0]
