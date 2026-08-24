from pydantic import BaseModel, ConfigDict, field_serializer, field_validator

from core.store.registry import STORES, Store


class Source(BaseModel):
    model_config = ConfigDict(extra='forbid', arbitrary_types_allowed=True, coerce_numbers_to_str=True)

    store: Store
    id: str = ''
    price: float | None = None
    servings_per_item: int | None = None
    size_ml: int | None = None
    url: str = ''
    sku: str = ''
    title: str = ''
    out_of_stock: bool = False

    @field_validator('store', mode='before')
    @classmethod
    def _resolve_store(cls, value) -> Store:
        return value if isinstance(value, Store) else STORES.resolve(value or '')

    @field_serializer('store')
    def _dump_store(self, store: Store) -> str:
        return store.slug
