from __future__ import annotations

from pipeline_stats import count_by, safe_median, text_stats


def test_safe_median_handles_zero_one_and_multiple_values() -> None:
    assert safe_median([]) == 0
    assert safe_median([7]) == 7
    assert safe_median([1, 9, 3]) == 3
    assert safe_median([1, 9, 3, 5]) == 4


def test_text_stats_handles_zero_one_and_multiple_documents() -> None:
    assert text_stats([]) == {
        "documents": 0,
        "chars_total": 0,
        "chars_min": 0,
        "chars_median": 0,
        "chars_max": 0,
        "words_total": 0,
    }
    assert text_stats(["abc def"]) == {
        "documents": 1,
        "chars_total": 7,
        "chars_min": 7,
        "chars_median": 7,
        "chars_max": 7,
        "words_total": 2,
    }
    assert text_stats(["a", "abcd", "abcdef"])["chars_median"] == 4


def test_text_stats_handles_generators() -> None:
    stats = text_stats(text for text in ["ett två", "tre fyra fem"])

    assert stats["documents"] == 2
    assert stats["words_total"] == 5


def test_count_by_handles_missing_and_mixed_values() -> None:
    rows = [{"source_kind": "policy_index"}, {"source_kind": "riksdag_speech"}, {}, {"source_kind": None}]

    assert count_by(rows, lambda row: row.get("source_kind")) == {
        "policy_index": 1,
        "riksdag_speech": 1,
        "unknown": 2,
    }
