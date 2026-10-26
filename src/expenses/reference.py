from functools import cache

from pkg.model.base import Model


class ExpenseCategory(Model):
    SUBDIR = 'expense_categories'

    key: str
    category: str


@cache
def _categories() -> dict[str, ExpenseCategory]:
    return {c.key: c for c in ExpenseCategory.objects.all()}


def expense_category(item_category: str) -> ExpenseCategory | None:
    return _categories().get(item_category)
