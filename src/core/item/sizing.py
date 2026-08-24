import re
from dataclasses import dataclass

_TOP_CATEGORIES = {'polo', 'tee', 'shirt', 'topwear'}
_BOTTOM_CATEGORIES = {'trouser'}
_WORD_SIZES = (
    ('XXSMALL', 'XXS'), ('XSMALL', 'XS'), ('SMALL', 'S'), ('MEDIUM', 'M'),
    ('XXXLARGE', 'XXXL'), ('XXLARGE', 'XXL'), ('XLARGE', 'XL'), ('LARGE', 'L'),
)


@dataclass(frozen=True)
class Fit:
    top: str
    waist: int
    inseam: int
    shoe_eu: tuple[float, ...]

    @classmethod
    def from_profile(cls, profile: dict) -> 'Fit':
        fit = profile.get('fit') or {}
        return cls(
            top=fit['top'],
            waist=int(fit['waist']),
            inseam=int(fit['inseam']),
            shoe_eu=tuple(float(s) for s in fit.get('shoe_eu', [])),
        )


def size_available(category: str, sizes: list[str], fit: Fit) -> bool | None:
    if not sizes:
        return None
    category = category.lower()
    if category in _TOP_CATEGORIES:
        target = _canonical_top(fit.top)
        return any(_canonical_top(size) == target for size in sizes)
    if category in _BOTTOM_CATEGORIES:
        if any(re.search(r'\d{2}', size) for size in sizes):
            return any(_bottom_fits(size, fit) for size in sizes)
        target = _canonical_top(fit.top)
        return any(_canonical_top(size) == target for size in sizes)
    if category == 'shoes':
        return _shoe_available(sizes, fit)
    return None


def _shoe_available(sizes: list[str], fit: Fit) -> bool | None:
    if not fit.shoe_eu:
        return None
    parsed = []
    for size in sizes:
        match = re.search(r'(?:EU\s*)?(\d{2}(?:\.5)?)', size)
        if match:
            parsed.append(float(match.group(1)))
    if not parsed:
        return None
    return any(value in fit.shoe_eu for value in parsed)


def _canonical_top(size: str) -> str:
    token = re.sub(r'\(.*?\)', '', size.upper())
    token = re.sub(r'\bREG(ULAR)?\b', '', token)
    token = re.sub(r'[^A-Z0-9]', '', token)
    token = re.sub(r'^(\d)X', lambda m: 'X' * int(m.group(1)), token)
    for word, code in _WORD_SIZES:
        token = token.replace(word, code)
    return token


def _bottom_fits(size: str, fit: Fit) -> bool:
    waist = re.search(r'(\d{2})\s*W', size.upper()) or re.search(r'\b(\d{2})\b', size)
    if not waist or int(waist.group(1)) != fit.waist:
        return False
    inseam = re.search(r'(\d{2})\s*L', size.upper())
    return inseam is None or int(inseam.group(1)) >= fit.inseam - 3
