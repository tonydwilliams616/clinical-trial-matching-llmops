"""
The masking engine: find identifiers in text, replace each with a label.

    "Seen John Smith, MRN 1234567"  ->  "Seen <PERSON>, MRN <MRN>"

Presidio does the work in two steps:
  1. Analyzer - finds identifiers. A spaCy language model spots names, places
     and dates from the sentence around them; regular expressions catch fixed
     shapes (phone numbers, emails, SSNs, our MRNs).
  2. Anonymizer - replaces every finding with a placeholder like <PERSON>.

Labels match the notes/v1 answer key, so the benchmark (PR 11) can score the
gateway directly.
"""

import tldextract
import tldextract.tldextract
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

from .recognizers import custom_recognizers

# Presidio entity -> our label (as used in labels.jsonl)
LABELS = {
    "PERSON": "PERSON",
    "DATE_TIME": "DATE",
    "PHONE_NUMBER": "PHONE",
    "EMAIL_ADDRESS": "EMAIL",
    "US_SSN": "SSN",
    "US_DRIVER_LICENSE": "LICENSE",
    "LOCATION": "LOCATION",
    "MRN": "MRN",
    "US_ZIP_CODE": "ZIP",
    "STREET_ADDRESS": "ADDRESS",
}

# Presidio's email recognizer validates each address's ending (.com, .org)
# with tldextract, which by default DOWNLOADS the public suffix list on first
# use and holds a file lock while it does. On EKS the gateway can resolve DNS
# but its NetworkPolicy silently drops internet traffic, and tldextract sets no
# timeout - so the download hung forever, the lock was never released, every
# later email validation failed, and no email was masked (found in the phase 3
# EKS session: refusals with leftover EMAIL, and worker timeouts).
# Use only the suffix list bundled with tldextract: no network, ever.
tldextract.tldextract.TLD_EXTRACTOR = tldextract.TLDExtract(suffix_list_urls=())

# Large English model: best name/place detection. Baked into the image.
SPACY_MODEL = "en_core_web_lg"

# Findings scored below this are ignored. Lower = catch more, mask more
# by mistake. The benchmark in PR 11 is how this gets tuned, not guesswork.
SCORE_THRESHOLD = 0.35


# Entities found by the language model (a judgement from sentence context).
# Everything else comes from a pattern that matched an exact shape.
MODEL_ENTITIES = {"PERSON", "LOCATION", "DATE_TIME"}


def _rank(r) -> tuple:
    # On the exact same text, a purpose-built pattern beats the model's guess:
    # "record no. 482-1937" is an MRN, even if the model thinks it's a date.
    return (r.entity_type not in MODEL_ENTITIES, r.score, r.entity_type)


def drop_nested(results: list) -> list:
    """Keep one finding per piece of text.

    - A finding inside a bigger one is dropped: "(617) 555-0147" is one PHONE,
      not a PHONE plus a 7-digit number inside it.
    - Two findings on exactly the same text: the higher-ranked one is kept.

    The anonymizer already masks only one of them; this keeps the findings and
    counts honest too, so the benchmark doesn't see phantom extra identifiers.
    """
    def inside(r, o) -> bool:
        if r is o or not (o.start <= r.start and r.end <= o.end):
            return False
        same_span = (r.start, r.end) == (o.start, o.end)
        return not same_span or _rank(o) > _rank(r)

    return [r for r in results if not any(inside(r, o) for o in results)]


class Masker:
    def __init__(self) -> None:
        nlp_engine = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": SPACY_MODEL}],
            }
        ).create_engine()
        self.analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en"])
        for recognizer in custom_recognizers():
            self.analyzer.registry.add_recognizer(recognizer)
        self.anonymizer = AnonymizerEngine()
        self.operators = {
            entity: OperatorConfig("replace", {"new_value": f"<{label}>"})
            for entity, label in LABELS.items()
        }

    def mask(self, text: str) -> dict:
        results = self.analyzer.analyze(
            text=text,
            language="en",
            entities=list(LABELS),
            score_threshold=SCORE_THRESHOLD,
        )
        results = drop_nested(results)
        masked = self.anonymizer.anonymize(
            text=text, analyzer_results=results, operators=self.operators
        )
        # Positions and labels only - never the identifier values themselves
        findings = sorted(
            (
                {
                    "label": LABELS[r.entity_type],
                    "start": r.start,
                    "end": r.end,
                    "score": round(r.score, 2),
                }
                for r in results
            ),
            key=lambda f: (f["start"], f["end"]),
        )
        counts: dict[str, int] = {}
        for f in findings:
            counts[f["label"]] = counts.get(f["label"], 0) + 1
        return {"masked_text": masked.text, "findings": findings, "counts": counts}
