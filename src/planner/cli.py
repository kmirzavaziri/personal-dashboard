import re

import typer

from planner.model import STATUSES, Task

planner_app = typer.Typer(no_args_is_help=True, add_completion=False, help='Manage planner tasks')


def register(root: typer.Typer) -> None:
    root.add_typer(planner_app, name='planner')


def _slug(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')[:60] or 'task'


def _unique_key(base: str) -> str:
    key, suffix = base, 2
    while Task.objects.get_or_none(key=key) is not None:
        key, suffix = f'{base}-{suffix}', suffix + 1
    return key


def _next_order() -> int:
    return max((t.order for t in Task.objects.all()), default=0) + 1


def _flatten(labels: list[str]) -> list[str]:
    return [part.strip() for value in labels for part in value.split(',') if part.strip()]


def _get(key: str) -> Task:
    task = Task.objects.get_or_none(key=key)
    if task is None:
        raise SystemExit(f'Task not found: {key}')
    return task


def _check_status(status: str) -> None:
    if status not in STATUSES:
        raise SystemExit(f"Unknown status '{status}'. Valid: {', '.join(STATUSES)}")


def _show(task: Task) -> str:
    labels = ' '.join(f'#{label}' for label in task.labels)
    return f'  [{task.status:8}] {task.key:24} {task.title}  {labels}'.rstrip()


@planner_app.command(help='Add a task.')
def add(
    title: str = typer.Argument(..., help='Task title'),
    label: list[str] = typer.Option([], '--label', '-l', help='Label/dimension (repeatable or comma-separated)'),
    status: str = typer.Option('backlog', '--status', '-s', help=f"One of: {', '.join(STATUSES)}"),
    notes: str = typer.Option('', '--notes', '-n', help='Optional notes'),
):
    _check_status(status)
    task = Task(
        key=_unique_key(_slug(title)),
        title=title,
        labels=_flatten(label),
        status=status,
        order=_next_order(),
        notes=notes,
    )
    task.save()
    print(_show(task))


@planner_app.command('ls', help='List tasks, optionally filtered by label or status.')
def ls(
    label: str = typer.Option(None, '--label', '-l', help='Only tasks carrying this label'),
    status: str = typer.Option(None, '--status', '-s', help='Only tasks in this status'),
):
    tasks = sorted(Task.objects.all(), key=lambda t: (t.status, t.order))
    if label:
        tasks = [t for t in tasks if label in t.labels]
    if status:
        tasks = [t for t in tasks if t.status == status]
    for task in tasks:
        print(_show(task))
    print(f'  ({len(tasks)} task{"s" if len(tasks) != 1 else ""})')


@planner_app.command(help='Edit a task. Only the fields you pass change; --label replaces all labels.')
def edit(
    key: str = typer.Argument(..., help='Task key'),
    title: str = typer.Option(None, '--title', '-t', help='New title'),
    label: list[str] = typer.Option(None, '--label', '-l', help='Replacement label(s); pass empty string to clear'),
    status: str = typer.Option(None, '--status', '-s', help=f"One of: {', '.join(STATUSES)}"),
    notes: str = typer.Option(None, '--notes', '-n', help='New notes'),
):
    task = _get(key)
    if title is not None:
        task.title = title
    if label is not None:
        task.labels = _flatten(label)
    if status is not None:
        _check_status(status)
        task.status = status
    if notes is not None:
        task.notes = notes
    task.save()
    print(_show(task))


@planner_app.command(help='Move a task to a status (backlog / next / done).')
def move(
    key: str = typer.Argument(..., help='Task key'),
    status: str = typer.Argument(..., help=f"One of: {', '.join(STATUSES)}"),
):
    _check_status(status)
    task = _get(key)
    task.status = status
    task.save()
    print(_show(task))


@planner_app.command(help='Mark a task done.')
def check(key: str = typer.Argument(..., help='Task key')):
    task = _get(key)
    task.status = 'done'
    task.save()
    print(_show(task))


@planner_app.command(help='Remove a task.')
def rm(key: str = typer.Argument(..., help='Task key')):
    task = _get(key)
    task.delete()
    print(f'  Removed {key}')
