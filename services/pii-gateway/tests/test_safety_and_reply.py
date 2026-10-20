"""
Unit tests for the two pure pieces of /v1/assess - no model, no Presidio:
  - the leftover-identifier check that runs after masking
  - reading the model's reply (anything odd must become "unclear")
All values are fake: 555-01xx phones, example.com email, 999 SSN.
"""

import pytest

from app.assess import UNREADABLE, build_user_message, parse_reply
from app.safety import residual_identifiers


@pytest.mark.parametrize("text, label", [
    ("call (617) 555-0147", "PHONE"),
    ("call 617-555-0147", "PHONE"),
    ("call 617.555.0147", "PHONE"),
    ("SSN 999-52-8841", "SSN"),
    ("mail john.s42@example.com", "EMAIL"),
    ("MRN 4821937", "MRN"),
    ("MRN4821937", "MRN"),
])
def test_leftover_identifiers_are_caught(text, label):
    assert residual_identifiers(text) == [label]


@pytest.mark.parametrize("text", [
    "Seen <PERSON>, MRN <MRN>, phone <PHONE>, on <DATE>.",
    "BP 140/90, HbA1c 7.2%, age 54, dose 100-1000 mg, eGFR 58.",
    "Metformin 500 mg twice daily; follow up in 3-6 months.",
])
def test_masked_or_clinical_text_passes(text):
    assert residual_identifiers(text) == []


def test_valid_reply():
    assert parse_reply('{"verdict": "likely_fails", "reason": "BP 182/110 noted."}') == (
        "likely_fails", "BP 182/110 noted.")


def test_reply_wrapped_in_prose_or_fences_still_read():
    text = 'Here you go:\n```json\n{"verdict": "likely_meets", "reason": "No such history."}\n```'
    assert parse_reply(text) == ("likely_meets", "No such history.")


@pytest.mark.parametrize("text", [
    "",
    "I think the patient qualifies.",
    '{"verdict": "eligible", "reason": "Looks fine."}',   # not an allowed verdict
    '{"verdict": "likely_meets"}',                         # no reason
    '{"verdict": "likely_meets", "reason": "  "}',         # empty reason
    '{"verdict": "likely_meets", "reason": "x"',           # truncated JSON
    '["likely_meets"]',                                    # not an object
])
def test_anything_odd_becomes_unclear(text):
    assert parse_reply(text) == ("unclear", UNREADABLE)


def test_long_reason_is_capped():
    verdict, reason = parse_reply('{"verdict": "unclear", "reason": "' + "a" * 2000 + '"}')
    assert verdict == "unclear" and len(reason) == 500


def test_note_and_criterion_are_fenced_as_data():
    message = build_user_message("No uncontrolled hypertension", "Seen <PERSON>.")
    assert message.index("<criterion>") < message.index("<note>")
    assert "</note>" in message
