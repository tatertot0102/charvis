"""Phase 2D.2 truth guard — the post-filter that blocks fabricated schedules and false write claims.

These are the exact strings the user actually saw when the bug fired: placeholder scaffolding and a
confident "I've updated your schedule" when nothing was written.
"""
from app.conversation import truth_guard


def test_placeholder_scaffolding_is_replaced():
    bad = "Here's your week:\n- 9am [insert existing events]\n- 11am standup"
    assert truth_guard.sanitize(bad) == truth_guard.SAFE_REPLY


def test_false_write_claim_is_replaced():
    for bad in (
        "I've updated your schedule with the new times.",
        "I have added the meeting to your calendar.",
        "Done — I scheduled a recurring event for you.",
        "I moved your 3pm appointment to 4pm.",
        "I've deleted those events from your calendar.",
    ):
        assert truth_guard.sanitize(bad) == truth_guard.SAFE_REPLY, bad


def test_honest_replies_pass_through_unchanged():
    for ok in (
        "I can't see your calendar in this message — ask me to pull it up.",
        "Sure, which day did you mean?",
        "I haven't changed anything on your calendar; tell me the change and reply CONFIRM.",
        "Union's deadline is closer — want to start there?",
    ):
        assert truth_guard.sanitize(ok) == ok


def test_is_suspect_flags_bracket_your():
    assert truth_guard.is_suspect("Your day: [your events here]")
    assert not truth_guard.is_suspect("Your day looks open this afternoon.")
