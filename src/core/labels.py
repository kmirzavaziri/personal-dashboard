PALETTE = (
    'var(--c-clay)', 'var(--c-indigo)', 'var(--c-sage)', 'var(--c-rose)', 'var(--c-cyan)', 'var(--c-amber)', 'var(--c-plum)',
    'var(--c-slate)', 'var(--c-coral)', 'var(--c-olive)', 'var(--c-mauve)', 'var(--c-pine)', 'var(--c-sand)', 'var(--blue)',
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
