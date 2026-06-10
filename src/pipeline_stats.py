from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from typing import Any, TypeVar

T = TypeVar("T")


def count_by(items: Iterable[T], key_fn: Callable[[T], Any]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for item in items:
        key = key_fn(item)
        counts[str(key) if key not in (None, "") else "unknown"] += 1
    return dict(sorted(counts.items()))


def safe_median(numbers: Iterable[int]) -> int:
    values = sorted(numbers)
    if not values:
        return 0
    midpoint = len(values) // 2
    if len(values) % 2:
        return values[midpoint]
    return (values[midpoint - 1] + values[midpoint]) // 2


def text_stats(texts: Iterable[str]) -> dict[str, int]:
    text_list = [text or "" for text in texts]
    lengths = [len(text) for text in text_list]
    words = [len(text.split()) for text in text_list]
    return {
        "documents": len(lengths),
        "chars_total": sum(lengths),
        "chars_min": min(lengths, default=0),
        "chars_median": safe_median(lengths),
        "chars_max": max(lengths, default=0),
        "words_total": sum(words),
    }
