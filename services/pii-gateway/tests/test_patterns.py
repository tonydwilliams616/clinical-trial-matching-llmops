"""Fast checks on the custom regular expressions (no Presidio needed)."""

import re

from app import patterns


def found(pattern: str, text: str) -> list[str]:
    return [m.group(0) for m in re.finditer(pattern, text)]


def test_mrn_labelled_takes_digits_only():
    assert found(patterns.MRN_LABELLED, "DOB: 03/04/1961    MRN 4821937") == ["4821937"]


def test_mrn_joined():
    assert found(patterns.MRN_JOINED, "Ref MRN4821937 today") == ["MRN4821937"]


def test_mrn_hyphenated_shape():
    assert found(patterns.MRN_HYPHENATED, "record no. 482-1937") == ["482-1937"]


def test_mrn_ignores_longer_numbers():
    assert found(patterns.MRN_JOINED, "MRN48219370") == []


def test_zip_five_and_plus_four():
    assert found(patterns.ZIP, "Boston, Massachusetts 02118") == ["02118"]
    assert found(patterns.ZIP, "Springfield 01103-1234") == ["01103-1234"]


def test_zip_ignores_doses_and_years():
    assert found(patterns.ZIP, "Metformin 500 mg since 2019, HbA1c 6.9") == []


def test_street_with_unit():
    assert found(patterns.STREET, "Address: 1015 Kuhn Promenade Suite 37, Boston") == [
        "1015 Kuhn Promenade Suite 37"
    ]


def test_street_ignores_lowercase_phrases():
    assert found(patterns.STREET, "Review in 3 months") == []
