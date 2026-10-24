PALETTE = (
    'var(--c-clay)', 'var(--c-mauve)', 'var(--c-slate)', 'var(--c-sand)', 'var(--c-sage)', 'var(--blue)',
)

UNLABELED = 'General'

_RESERVED = {
    UNLABELED: 'var(--faint)',
    'Routine': 'var(--c-teal)',
}


def colors_for(labels) -> dict[str, str]:
    ordered = sorted(label for label in labels if label not in _RESERVED)
    colors = {label: PALETTE[index % len(PALETTE)] for index, label in enumerate(ordered)}
    colors.update(_RESERVED)
    return colors


def label_colors(items) -> dict[str, str]:
    return colors_for({label for item in items for label in item.labels})
