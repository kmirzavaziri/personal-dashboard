from typing import ClassVar

from pkg.model.base import Model

STATUSES = ('backlog', 'next', 'done')


class Task(Model):
    SUBDIR: ClassVar[str] = 'planner'

    key: str
    title: str = ''
    labels: list[str] = []
    status: str = 'backlog'
    order: int = 0
    notes: str = ''


class PlannerMeta(Model):
    SUBDIR: ClassVar[str] = 'planner_meta'

    key: str = 'board'
    label_order: list[str] = []
