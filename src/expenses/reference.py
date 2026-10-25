from functools import cache

from pkg.model.base import Model


class ExpenseCategory(Model):
    SUBDIR = 'expense_categories'

    key: str
    account: str
    category: str


class ExpenseAccount(Model):
    SUBDIR = 'expense_accounts'

    key: str
    order: int
    tracking: str


@cache
def _categories() -> dict[str, ExpenseCategory]:
    return {c.key: c for c in ExpenseCategory.objects.all()}


@cache
def _accounts() -> tuple[ExpenseAccount, ...]:
    return tuple(sorted(ExpenseAccount.objects.all(), key=lambda a: a.order))


def expense_category(item_category: str) -> ExpenseCategory | None:
    return _categories().get(item_category)


def expense_accounts() -> tuple[ExpenseAccount, ...]:
    return _accounts()
