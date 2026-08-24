from dataclasses import dataclass


@dataclass(frozen=True)
class Status:
    value: str
    label: str
    css: str


STATUSES: dict[str, tuple[Status, ...]] = {
    'edible': (
        Status('OK', 'OK', 'status-ok'),
        Status('Low', 'Low', 'status-low'),
        Status('Out', 'Out', 'status-out'),
        Status('Basket', 'Basket', 'status-basket'),
        Status('Ordered', 'Ordered', 'status-ordered'),
        Status('', '—', 'muted'),
    ),
    'durable': (
        Status('pending', 'Pending', 'status-pending'),
        Status('basket', 'Basket', 'status-basket'),
        Status('ordered', 'Ordered', 'status-ordered'),
        Status('owned', 'Owned', 'status-owned'),
        Status('', '—', 'muted'),
    ),
    'clothing': (
        Status('candidate', 'Candidate', 'card-tag-candidate'),
        Status('deferred', 'Deferred', 'card-tag-deferred'),
        Status('next_batch', 'Next Batch', 'card-tag-next_batch'),
        Status('unavailable', 'Out of My Size', 'card-tag-unavailable'),
        Status('pending', 'Pending', 'card-tag-pending'),
        Status('basket', 'Basket', 'card-tag-basket'),
        Status('ordered', 'Ordered', 'card-tag-ordered'),
        Status('owned', 'Owned', 'card-tag-owned'),
    ),
}


def status_values(kind: str) -> tuple[str, ...]:
    return tuple(s.value for s in STATUSES[kind])


def status_config(kind: str) -> dict[str, dict[str, str]]:
    return {s.value: {'label': s.label, 'css': s.css} for s in STATUSES[kind]}
