from __future__ import annotations

import sys

import app


def test_parse_args_has_no_hardcoded_topic_default(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["app.py", "Vad vill ni göra åt välfärden?"])

    args = app.parse_args()

    assert args.question == "Vad vill ni göra åt välfärden?"
    assert args.topic is None


def test_parse_args_accepts_explicit_topic(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["app.py", "Vad vill ni göra åt välfärden?", "--topic", "välfärd"],
    )

    args = app.parse_args()

    assert args.question == "Vad vill ni göra åt välfärden?"
    assert args.topic == "välfärd"
