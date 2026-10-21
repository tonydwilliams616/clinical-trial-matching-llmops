"""
Last check before any text leaves for the model.

Masking is done by Presidio (masker.py). This is a second, independent check
on its output: a few strict regular expressions for identifiers that must
never reach a model. If any still match, nothing is sent.

Deliberately narrow - only shapes with almost no innocent look-alikes - so it
doesn't block notes for things like "dose 100-1000 mg" or "BP 140/90".
Kept free of Presidio imports so it can be unit-tested on its own.
"""

import re

from .patterns import MRN_JOINED, MRN_LABELLED

RESIDUAL_PATTERNS = {
    # (617) 555-0147, 617-555-0147, 617.555.0147
    "PHONE": re.compile(r"(?:\(\d{3}\)\s?|\b\d{3}[-.\s])\d{3}[-.]\d{4}\b"),
    "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "EMAIL": re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"),
    "MRN": re.compile(f"(?:{MRN_LABELLED})|(?:{MRN_JOINED})"),
}


def residual_identifiers(text: str) -> list[str]:
    """Labels of identifier types still present in text (empty list = safe)."""
    return sorted(label for label, pattern in RESIDUAL_PATTERNS.items() if pattern.search(text))


PLACEHOLDER = re.compile(r"<[A-Z_]+>")


def shape(text: str) -> str:
    """Text with letters and digits generalised, placeholders kept: safe to log.

    "Seen <PERSON>, j.s42@example.com" -> "Aaaa <PERSON>, a.a99@aaaaaaa.aaa"
    Shows WHAT kind of thing slipped through without revealing its value.
    """
    out, last = [], 0
    for m in PLACEHOLDER.finditer(text):
        out.append(_generalise(text[last:m.start()]))
        out.append(m.group())
        last = m.end()
    out.append(_generalise(text[last:]))
    return "".join(out)


def _generalise(part: str) -> str:
    return re.sub(r"[a-z]", "a", re.sub(r"[A-Z]", "A", re.sub(r"\d", "9", part)))


def residual_shapes(text: str, context: int = 15) -> list[str]:
    """For each leftover identifier: its label and the shape of it plus a little
    text before it - enough to diagnose a refusal from the logs alone."""
    shapes = []
    for label, pattern in RESIDUAL_PATTERNS.items():
        for m in pattern.finditer(text):
            start = max(0, m.start() - context)
            shapes.append(f"{label}: {shape(text[start:m.start()])}[[{shape(m.group())}]]")
    return shapes[:5]
