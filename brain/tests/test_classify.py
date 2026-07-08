"""Unit tests for deterministic email classification (no network, no DB)."""
from app.integrations.google.classify import classify
from tests.gmail_helpers import MY_EMAIL, msg


def test_direction_inbound_vs_outbound():
    assert classify(msg(from_email="alice@example.com"), MY_EMAIL).direction == "inbound"
    assert classify(msg(from_email=MY_EMAIL), MY_EMAIL).direction == "outbound"


def test_promotional_label_marks_low_importance():
    c = classify(msg(labels=("INBOX", "CATEGORY_PROMOTIONS")), MY_EMAIL)
    assert c.is_promotional
    assert c.importance == "low"
    assert not c.requires_response


def test_requires_response_when_question_addressed_to_me():
    c = classify(msg(subject="Quick question", snippet="Can you review this?"), MY_EMAIL)
    assert c.requires_response
    assert c.importance == "high"


def test_no_response_from_noreply_sender():
    c = classify(msg(from_email="no-reply@service.com", snippet="Can you confirm?"), MY_EMAIL)
    assert not c.requires_response


def test_deadline_related_is_urgent():
    c = classify(msg(subject="Invoice due Friday", snippet="payment deadline asap"), MY_EMAIL)
    assert c.is_deadline_related
    assert c.urgency == "high"


def test_calendar_related_detected():
    c = classify(msg(subject="Meeting invite", snippet="are you free tomorrow for a zoom"), MY_EMAIL)
    assert c.is_calendar_related


def test_plain_inbound_is_fyi():
    c = classify(msg(subject="Notes", snippet="just sharing the deck for your records"), MY_EMAIL)
    assert c.is_fyi
    assert not c.requires_response
