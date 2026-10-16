"""
Regular expressions for identifiers Presidio has no built-in recognizer for.

Kept free of imports so they can be unit-tested without Presidio installed.
Each pattern gets a confidence score in recognizers.py; weak patterns only
count when a context word (e.g. "address", "record") appears nearby.
"""

# Medical record number written after its label: "MRN 1234567" -> the digits
MRN_LABELLED = r"(?<=\bMRN )\d{7}\b"

# Label and number run together: "MRN1234567"
MRN_JOINED = r"\bMRN\d{7}\b"

# Hyphenated record number: "record no. 123-4567". On its own this shape also
# appears inside phone numbers, so it only counts with a context word nearby.
MRN_HYPHENATED = r"\b\d{3}-\d{4}\b"

# US ZIP code, 5 digits with optional +4
ZIP = r"\b\d{5}(?:-\d{4})?\b"

# Street address: house number, 1-4 capitalised words, optional unit.
# "1015 Kuhn Promenade Suite 37". Weak on its own - needs a context word.
STREET = (
    r"\b\d{1,6}(?: (?!(?:Unit|Suite|Apt|Apartment)\b)[A-Z][a-zA-Z']*){1,4}"
    r"(?: (?:Unit|Suite|Apt\.?|Apartment) \d+[A-Z]?)?\b"
)
