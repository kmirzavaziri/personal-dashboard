_PALETTE = (
    '#e78a4e', '#c56ea8', '#9d7cd8', '#d3869b', '#cf7a3e', '#3f9e93',
    '#c99a6a', '#8f7bd0', '#d99ac0', '#a0785a', '#b57edc', '#7d6ba8',
)

UNLABELED = 'General'

_RESERVED = {
    UNLABELED: '#9aa09c',
    'Routine': '#4fb0a5',
}


def colors_for(labels) -> dict[str, str]:
    ordered = sorted(label for label in labels if label not in _RESERVED)
    colors = {label: _PALETTE[index % len(_PALETTE)] for index, label in enumerate(ordered)}
    colors.update(_RESERVED)
    return colors


def label_colors(items) -> dict[str, str]:
    return colors_for({label for item in items for label in item.labels})
