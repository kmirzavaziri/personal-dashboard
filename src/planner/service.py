import re

from planner.model import STATUSES, Task


def slug(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')[:60] or 'task'


def unique_key(base: str) -> str:
    key, suffix = base, 2
    while Task.objects.get_or_none(key=key) is not None:
        key, suffix = f'{base}-{suffix}', suffix + 1
    return key


def next_order() -> int:
    return max((t.order for t in Task.objects.all()), default=0) + 1


def flatten(labels) -> list[str]:
    values = labels if isinstance(labels, list) else ([labels] if labels else [])
    return [part.strip() for value in values for part in str(value).split(',') if part.strip()]


def _check_status(status: str) -> None:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")


def get(key: str) -> Task:
    task = Task.objects.get_or_none(key=key)
    if task is None:
        raise ValueError(f'Task not found: {key}')
    return task


def add(title: str, labels=None, status: str = 'backlog', notes: str = '') -> Task:
    _check_status(status)
    task = Task(key=unique_key(slug(title)), title=title, labels=flatten(labels),
                status=status, order=next_order(), notes=notes)
    task.save()
    return task


def move(key: str, status: str) -> Task:
    _check_status(status)
    task = get(key)
    task.status = status
    task.save()
    return task


def edit(key: str, title=None, labels=None, status=None, notes=None) -> Task:
    task = get(key)
    if title is not None:
        task.title = title
    if labels is not None:
        task.labels = flatten(labels)
    if status is not None:
        _check_status(status)
        task.status = status
    if notes is not None:
        task.notes = notes
    task.save()
    return task


def check(key: str) -> Task:
    return move(key, 'done')


def remove(key: str) -> None:
    get(key).delete()


def listing(label=None, status=None) -> list[Task]:
    tasks = sorted(Task.objects.all(), key=lambda t: (t.status, t.order))
    if label:
        tasks = [t for t in tasks if label in t.labels]
    if status:
        tasks = [t for t in tasks if t.status == status]
    return tasks
