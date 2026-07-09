"""Unit tests for the Phase 2D natural-language parser (pure — no DB, no network)."""
from datetime import time

from app.calendar_actions import parse
from app.calendar_actions.schema import ActionType


def test_move_with_two_times_splits_target_and_destination():
    req = parse.detect("move my 3pm meeting to 4")
    assert req is not None
    assert req.action_type is ActionType.UPDATE
    assert req.target_time == time(15, 0)  # the "3pm" identifies the event
    assert req.new_time == time(16, 0)  # the "to 4" is where it goes (bare hour → PM)


def test_move_with_one_time_is_destination_only():
    req = parse.detect("reschedule standup to 11am")
    assert req.action_type is ActionType.UPDATE
    assert req.target_time is None
    assert req.new_time == time(11, 0)
    assert "standup" in (req.target_hint or "")


def test_cancel_maps_to_delete_with_hint():
    req = parse.detect("cancel my dentist appointment")
    assert req.action_type is ActionType.DELETE
    assert "dentist" in (req.target_hint or "")


def test_schedule_maps_to_create_with_title_and_time():
    req = parse.detect("schedule Dentist tomorrow at 2 for 45 minutes")
    assert req.action_type is ActionType.CREATE
    assert "dentist" in (req.title or "")
    assert req.new_time == time(14, 0)  # bare "at 2" → PM
    assert req.day_offset == 1
    assert req.duration_minutes == 45


def test_create_hour_duration_is_minutes():
    req = parse.detect("book a 2 hour focus block at 9am")
    assert req.action_type is ActionType.CREATE
    assert req.duration_minutes == 120


def test_explicit_meridiem_respected():
    assert parse.parse_time("meet at 9am") == time(9, 0)
    assert parse.parse_time("dinner at 8pm") == time(20, 0)
    assert parse.parse_time("call at noon") == time(12, 0)


def test_non_action_message_returns_none():
    assert parse.detect("what's my day look like?") is None
    assert parse.detect("anything important in my email?") is None
    assert parse.detect("") is None
