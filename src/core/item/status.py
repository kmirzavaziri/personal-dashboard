from dataclasses import dataclass


@dataclass(frozen=True)
class Status:
    value: str
    label: str
    tone: str


STATUSES: dict[str, tuple[Status, ...]] = {
    'edible': (
        Status('OK', 'OK', 'var(--green)'),
        Status('Low', 'Low', 'var(--yellow)'),
        Status('Out', 'Out', 'var(--red)'),
        Status('Basket', 'Basket', 'var(--accent)'),
        Status('Ordered', 'Ordered', 'var(--c-mauve)'),
        Status('', 'None', 'var(--faint)'),
    ),
    'durable': (
        Status('pending', 'Pending', 'var(--red)'),
        Status('basket', 'Basket', 'var(--accent)'),
        Status('ordered', 'Ordered', 'var(--c-mauve)'),
        Status('owned', 'Owned', 'var(--green)'),
        Status('', 'None', 'var(--faint)'),
    ),
    'clothing': (
        Status('candidate', 'Candidate', 'var(--muted)'),
        Status('deferred', 'Deferred', 'var(--c-teal)'),
        Status('next_batch', 'Next batch', 'var(--c-clay)'),
        Status('unavailable', 'Out of my size', 'var(--yellow)'),
        Status('pending', 'Pending', 'var(--red)'),
        Status('basket', 'Basket', 'var(--accent)'),
        Status('ordered', 'Ordered', 'var(--c-mauve)'),
        Status('owned', 'Owned', 'var(--green)'),
    ),
}


def status_values(kind: str) -> tuple[str, ...]:
    return tuple(s.value for s in STATUSES[kind])


def statuses(kind: str) -> tuple[Status, ...]:
    return STATUSES[kind]
