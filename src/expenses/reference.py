from functools import cache

from pkg.model.base import Model


class ExpenseCategory(Model):
    SUBDIR = 'expense_categories'

    key: str
    account: str
    display: str


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


def category_account(category: str) -> str | None:
    c = _categories().get(category)
    return c.account if c else None


def category_display(category: str) -> str:
    c = _categories().get(category)
    return c.display if c else category.capitalize()


def expense_accounts() -> tuple[ExpenseAccount, ...]:
    return _accounts()
