"""Phase 2D.2 — deterministic parsing of commitment corrections and recurrence specs (pure)."""
from datetime import time

from app.commitments import parse


# --- naming corrections ------------------------------------------------------


def test_it_is_captures_proper_noun_name():
    c = parse.detect_name_correction("it is ECE Machine Learning Lab")
    assert c is not None and c.title == "ECE Machine Learning Lab"


def test_its_actually_variant():
    c = parse.detect_name_correction("it's actually Physics 101")
    assert c is not None and c.title == "Physics 101"


def test_the_class_is_variant():
    c = parse.detect_name_correction("the class is Organic Chemistry")
    assert c is not None and c.title == "Organic Chemistry"


def test_chitchat_is_not_a_correction():
    assert parse.detect_name_correction("it's fine") is None
    assert parse.detect_name_correction("that is great, thanks") is None  # lowercase common words
    assert parse.detect_name_correction("what is my week") is None


def test_recurrence_statement_is_not_taken_as_a_name():
    # "it's every weekday 10-2" must go to the recurrence parser, not naming.
    assert parse.detect_name_correction("it's every weekday 10-2") is None


# --- recurrence specs --------------------------------------------------------


def test_every_weekday_with_time_range():
    spec = parse.detect_recurrence("it's every weekday 10-2")
    assert spec is not None
    assert spec.rrule == "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"
    assert spec.start_time == time(10, 0)
    assert spec.end_time == time(14, 0)
    assert "weekday" in spec.summary.lower()


def test_every_monday_at_three():
    spec = parse.detect_recurrence("every Monday at 3")
    assert spec is not None
    assert spec.rrule == "RRULE:FREQ=WEEKLY;BYDAY=MO"
    assert spec.start_time == time(15, 0)


def test_daily_recurrence():
    spec = parse.detect_recurrence("every day at 9am")
    assert spec is not None and spec.rrule == "RRULE:FREQ=DAILY"


def test_no_marker_is_not_recurrence():
    assert parse.detect_recurrence("move my 3pm to 4") is None
    assert parse.detect_recurrence("lunch at noon") is None
