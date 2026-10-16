"""
Custom Presidio recognizers for identifiers in our notes that Presidio's
built-ins miss: medical record numbers, ZIP codes and street addresses.

Scores: Presidio keeps a finding only if its score is >= the threshold in
masker.py (0.35). A context word found just before a match adds 0.35, so a
pattern scored 0.1 or 0.3 only counts when its context word is present.
"""

from presidio_analyzer import Pattern, PatternRecognizer

from . import patterns


def custom_recognizers() -> list[PatternRecognizer]:
    return [
        PatternRecognizer(
            supported_entity="MRN",
            patterns=[
                Pattern("mrn_labelled", patterns.MRN_LABELLED, 0.85),
                Pattern("mrn_joined", patterns.MRN_JOINED, 0.85),
            ],
        ),
        # Separate recognizer so only "record" boosts the weak hyphenated
        # shape - otherwise an "MRN" label just before a phone number made
        # the phone's last 7 digits count as an MRN too.
        PatternRecognizer(
            supported_entity="MRN",
            name="MrnHyphenatedRecognizer",
            patterns=[Pattern("mrn_hyphenated", patterns.MRN_HYPHENATED, 0.1)],
            context=["record"],
        ),
        PatternRecognizer(
            supported_entity="US_ZIP_CODE",
            patterns=[Pattern("zip", patterns.ZIP, 0.4)],
            context=["zip", "postcode", "postal"],
        ),
        PatternRecognizer(
            supported_entity="STREET_ADDRESS",
            patterns=[Pattern("street", patterns.STREET, 0.3)],
            context=["address", "lives", "resides"],
        ),
    ]
