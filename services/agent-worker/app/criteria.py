"""
Turning a trial's free-text eligibility section into individual criteria.

ClinicalTrials.gov text usually looks like:

    Inclusion Criteria:
    * Adults with type 2 diabetes ...
    Exclusion Criteria:
    * History of ...

Each bullet becomes one question for the model. Exclusion bullets are
rephrased as "Must NOT have: ..." so that "likely_meets" always means "this
patient is still OK on this point".

Bullets about age and sex are skipped - those are hard criteria, already
checked exactly in code (hard.py).
"""

import re

MIN_CHARS, MAX_CHARS = 15, 300
HARD_CRITERIA_WORDS = re.compile(r"\b(aged?|years? of age|years old|male|female|sex|gender)\b", re.I)
BULLET = re.compile(r"^\s*(?:[*\-•]|\d+[.)])\s+")


def split_criteria(text: str) -> list[dict]:
    """[{"kind": "inclusion"|"exclusion", "text": ...}] in document order."""
    kind, items = None, []
    for raw in (text or "").splitlines():
        line = raw.strip()
        lowered = line.lower().rstrip(":")
        if lowered.startswith("inclusion criteria"):
            kind = "inclusion"
            continue
        if lowered.startswith("exclusion criteria"):
            kind = "exclusion"
            continue
        if kind and BULLET.match(raw):
            items.append({"kind": kind, "text": BULLET.sub("", raw).strip()})
    return items


def select_free_text(items: list[dict], limit: int) -> list[dict]:
    """Up to `limit` criteria for the model, exclusions first (they decide most cases)."""
    usable = [i for i in items
              if MIN_CHARS <= len(i["text"]) <= MAX_CHARS and not HARD_CRITERIA_WORDS.search(i["text"])]
    ordered = [i for i in usable if i["kind"] == "exclusion"] + [i for i in usable if i["kind"] == "inclusion"]
    return ordered[:limit]


def as_question(item: dict) -> str:
    return item["text"] if item["kind"] == "inclusion" else f"Must NOT have: {item['text']}"
