from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from core.item.categories import EdibleCategory
from core.item.schedule import build_pool
from expenses.reference import expense_category
from pkg.model.io import read_yaml

DAYS_PER_MONTH = 365.25 / 12
MISC = ''


class Frequency(StrEnum):
    DAILY = 'daily'
    WORKDAY = 'workday'
    WEEKLY = 'weekly'
    BIWEEKLY = 'biweekly'
    MONTHLY = 'monthly'
    BIMONTHLY = 'bimonthly'
    SEMIANNUAL = 'semiannual'
    YEARLY = 'yearly'

    @property
    def per_month(self) -> float:
        return {
            Frequency.DAILY: DAYS_PER_MONTH,
            Frequency.WORKDAY: DAYS_PER_MONTH * 5 / 7,
            Frequency.WEEKLY: DAYS_PER_MONTH / 7,
            Frequency.BIWEEKLY: DAYS_PER_MONTH / 14,
            Frequency.MONTHLY: 1.0,
            Frequency.BIMONTHLY: 1 / 2,
            Frequency.SEMIANNUAL: 1 / 6,
            Frequency.YEARLY: 1 / 12,
        }[self]

    @property
    def cycle_months(self) -> int:
        return {Frequency.BIMONTHLY: 2, Frequency.SEMIANNUAL: 6, Frequency.YEARLY: 12}.get(self, 1)

    @property
    def is_sub_monthly(self) -> bool:
        return self in (Frequency.DAILY, Frequency.WORKDAY, Frequency.WEEKLY, Frequency.BIWEEKLY)

    @property
    def unit(self) -> str:
        return {
            Frequency.DAILY: 'day',
            Frequency.WORKDAY: 'workday',
            Frequency.WEEKLY: 'week',
            Frequency.BIWEEKLY: '2 weeks',
            Frequency.MONTHLY: 'month',
            Frequency.BIMONTHLY: '2 months',
            Frequency.SEMIANNUAL: '6 months',
            Frequency.YEARLY: 'year',
        }[self]


class BudgetLine(BaseModel):
    class Item(BaseModel):
        model_config = ConfigDict(extra='forbid')

        name: str
        monthly: float
        url: str = ''
        image: str = ''

    model_config = ConfigDict(extra='forbid')

    key: str
    name: str
    category: str = MISC
    cost_aed: float
    frequency: Frequency = Frequency.MONTHLY
    times: int = 1
    match: list[str] = []
    hours: list[int] = []
    bill: bool = False
    notes: str = ''
    items: list[Item] = []

    @property
    def monthly(self) -> float:
        return self.cost_aed * self.times * self.frequency.per_month

    @property
    def paced(self) -> bool:
        return self.frequency.is_sub_monthly or self.times > 1

    @property
    def rate(self) -> str:
        times = f' × {self.times}' if self.times > 1 else ''
        return f'{self.cost_aed:,.0f}{times} / {self.frequency.unit}'

    def claims(self, text: str) -> bool:
        folded = text.casefold()
        return any(term.casefold() in folded for term in self.match)

    def fits(self, hour: int, workday: bool) -> bool:
        if not self.hours or (self.frequency is Frequency.WORKDAY and not workday):
            return False
        start, end = self.hours
        return start <= hour < end if start < end else hour >= start or hour < end


def budget_lines(config) -> list[BudgetLine]:
    lines = _shopping_list_lines(config) + [BudgetLine.model_validate(line)
                                            for line in read_yaml(config.expenses_db / 'recurring.yaml') or []]
    keys = [line.key for line in lines]
    duplicates = {key for key in keys if keys.count(key) > 1}
    if duplicates:
        raise ValueError(f'budget line keys must be unique: {sorted(duplicates)}')
    return lines


def sub_categories(config) -> dict[str, BudgetLine]:
    return {line.key: line for line in budget_lines(config)}


def _shopping_list_lines(config) -> list[BudgetLine]:
    groups = {category.key: category for category in EdibleCategory.objects.all()}
    items: dict[str, list[BudgetLine.Item]] = {}
    categories: dict[str, str] = {}
    for item in sorted(build_pool(config).values(), key=lambda item: item.short_name):
        if item.metadata.edible.track_only or item.price_per_month is None or item.servings_per_week == 0:
            continue
        expense = expense_category(item.metadata.edible.category)
        if expense is None:
            continue
        group = item.metadata.edible.category
        categories[group] = expense.category
        items.setdefault(group, []).append(BudgetLine.Item(name=item.short_name, monthly=item.price_per_month,
                                                           url=item.url or '', image=item.image or ''))
    return [BudgetLine(key=group, name=groups[group].label, category=categories[group],
                       cost_aed=sum(item.monthly for item in members), items=members)
            for group, members in sorted(items.items(), key=lambda kv: groups[kv[0]].order)]
