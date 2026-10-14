#!/usr/bin/env python3
"""
Generate synthetic clinical notes with planted identifiers and an answer key.

    python3 scripts/data/generate_notes.py generate
    python3 scripts/data/generate_notes.py upload

Why: to MEASURE de-identification we need text where we know exactly where
every identifier is. Each note is built piece by piece from a patient's
synthetic record (patients/v1); every identifier inserted is recorded with
its exact character position - the answer key. A de-identification tool
later processes the notes without the key, and is scored against it.

Notes are written by code templates, NOT an LLM: sending text full of
identifiers to an LLM is exactly what this project forbids, and templates
with a seed are reproducible.

Deliberately hard: name variants (first name only, nicknames, typos, caps),
relatives with word-like names, several date/phone/ID formats - plus
non-identifier traps (lab values, doses, years, the state, eponymous
diseases) that a good detector must leave alone.

Fakes are safe: phones use the 555-01xx fiction range, emails use the
reserved example.com/.org/.net domains.

Standard library only; needs patients/v1 locally (data/patients/v1) and the
AWS CLI for upload. Output goes to the RAW bucket (it contains identifiers).
"""

import argparse
import csv
import datetime
import hashlib
import json
import random
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

DATASET = "notes"
DATASET_VERSION = "v1"
SEED = 42
NOTES = 500                       # one note per patient
REFERENCE_DATE = datetime.date(2026, 10, 1)  # same fixed "today" as patients/v1

RAW_BUCKET = "ctm-raw-359013545044"
REPO_ROOT = Path(__file__).resolve().parents[2]
PATIENTS_DIR = REPO_ROOT / "data" / "patients" / "v1"
DATASET_DIR = REPO_ROOT / "data" / DATASET / DATASET_VERSION

# Visit types a GP-style note would be written for
NOTE_CLASSES = {"ambulatory", "wellness", "outpatient"}

# Latest measurements to quote in the note (Synthea observation descriptions)
OBSERVATIONS = {
    "Systolic Blood Pressure": "sbp",
    "Diastolic Blood Pressure": "dbp",
    "Hemoglobin A1c/Hemoglobin.total in Blood": "hba1c",
    "Body mass index (BMI) [Ratio]": "bmi",
}

NICKNAMES = {
    "Robert": "Bob", "William": "Bill", "Elizabeth": "Liz", "Margaret": "Peggy",
    "James": "Jim", "Katherine": "Kate", "Joseph": "Joe", "Michael": "Mike",
    "Thomas": "Tom", "Jennifer": "Jen", "Patricia": "Pat", "Charles": "Charlie",
    "Daniel": "Dan", "Christopher": "Chris", "Anthony": "Tony", "Richard": "Rich",
    "Susan": "Sue", "Deborah": "Debbie", "Edward": "Ed", "Nicholas": "Nick",
}
# Relatives get names that are also ordinary words - hard for detectors
WORDLIKE_FIRST = ["Hope", "Faith", "Grace", "Rose", "May", "June", "Will", "Joy", "Summer", "Dawn"]
WORDLIKE_LAST = ["Brown", "White", "Young", "Hunter", "Price", "Little", "Banks", "Rivers", "Stone", "Wells"]
RELATIONS = ["daughter", "son", "wife", "husband", "sister", "brother", "partner"]
CLINICIAN_FIRST = ["Sarah", "David", "Priya", "Marcus", "Elena", "Tomasz", "Aisha", "Gareth", "Mei", "Olu"]
CLINICIAN_LAST = ["Okafor", "Lindqvist", "Ramirez", "Patel", "Novak", "Hughes", "Chen", "Adeyemi", "Byrne", "Kowalski"]
EMAIL_DOMAINS = ["example.com", "example.org", "example.net"]

# Precision traps: diseases named after people - NOT identifiers
EPONYM_SENTENCES = [
    "No family history of Parkinson disease or Hodgkin lymphoma.",
    "Previously screened for Crohn disease; negative.",
    "Father had Alzheimer disease in his eighties.",
    "No features suggestive of Cushing syndrome.",
]


class Note:
    """Builds text piece by piece and records where each identifier lands."""

    def __init__(self):
        self.parts: list = []
        self.length = 0
        self.spans: list = []

    def add(self, text: str) -> None:
        self.parts.append(text)
        self.length += len(text)

    def pii(self, text: str, label: str, variant: str = "standard") -> None:
        self.spans.append({"start": self.length, "end": self.length + len(text),
                           "label": label, "variant": variant, "text": text})
        self.add(text)

    def text(self) -> str:
        return "".join(self.parts)


# --- Formatting helpers (each returns text + variant name) -----------------

def fmt_date(d: datetime.date, rng: random.Random):
    style = rng.choice(["numeric", "iso", "short", "long"])
    if style == "numeric":
        return d.strftime("%m/%d/%Y"), "numeric"
    if style == "iso":
        return d.isoformat(), "iso"
    if style == "short":
        return f"{d.day} {d.strftime('%b %Y')}", "short_month"
    suffix = "th" if 11 <= d.day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(d.day % 10, "th")
    return f"{d.strftime('%B')} {d.day}{suffix}, {d.year}", "long_month"


def fake_phone(rng: random.Random):
    area = rng.choice(["617", "508", "781", "413", "978"])
    line = f"01{rng.randint(0, 99):02d}"           # 555-0100..0199 = fiction range
    style = rng.choice(["paren", "dots", "intl", "dashes"])
    if style == "paren":
        return f"({area}) 555-{line}", "paren"
    if style == "dots":
        return f"{area}.555.{line}", "dots"
    if style == "intl":
        return f"+1 {area} 555 {line}", "international"
    return f"{area}-555-{line}", "dashes"


def fake_mrn(rng: random.Random):
    n = f"{rng.randint(1000000, 9999999)}"
    style = rng.choice(["labelled", "joined", "hyphenated"])
    if style == "labelled":
        return "MRN ", n, "labelled"
    if style == "joined":
        return "", f"MRN{n}", "joined"
    return "record no. ", f"{n[:3]}-{n[3:]}", "hyphenated"


def name_variant(first: str, last: str, prefix: str, rng: random.Random):
    """A later mention of the patient - often NOT the full name.

    Returns (title, name, variant). Titles (Mr, Mrs, Dr) are written as plain
    text OUTSIDE the identifier span - detectors mark the name, not the title.
    """
    options = ["first_only", "title_surname", "full", "caps_surname"]
    if first in NICKNAMES:
        options.append("nickname")
    if len(last) > 4:
        options.append("typo")
    v = rng.choice(options)
    if v == "first_only":
        return "", first, v
    if v == "title_surname":
        return f"{(prefix or 'Mx.').rstrip('.')} ", last, v
    if v == "full":
        return "", f"{first} {last}", v
    if v == "caps_surname":
        return "", f"{last.upper()}, {first}", v
    if v == "nickname":
        return "", NICKNAMES[first], v
    i = rng.randint(1, len(last) - 3)                 # swap two letters
    return "", last[:i] + last[i + 1] + last[i] + last[i + 2:], v


def years_since(d: datetime.date) -> int:
    return (REFERENCE_DATE - d).days // 365


# --- Loading patients/v1 ----------------------------------------------------

def load_inputs(rng: random.Random):
    if not (PATIENTS_DIR / "manifest.json").exists():
        sys.exit(f"{PATIENTS_DIR} not found - run generate_patients.py, or "
                 f"aws s3 sync s3://{RAW_BUCKET}/patients/v1/ {PATIENTS_DIR}")

    def rows(name):
        with (PATIENTS_DIR / name).open(newline="") as f:
            yield from csv.DictReader(f)

    patients = {r["Id"]: r for r in rows("patients.csv") if not r["DEATHDATE"]}
    chosen = sorted(rng.sample(sorted(patients), NOTES))
    chosen_set = set(chosen)

    visit = {}
    for e in rows("encounters.csv"):
        if e["PATIENT"] in chosen_set and e["ENCOUNTERCLASS"] in NOTE_CLASSES:
            if e["PATIENT"] not in visit or e["START"] > visit[e["PATIENT"]]["START"]:
                visit[e["PATIENT"]] = e

    conditions = defaultdict(dict)   # active disorders, earliest start per description
    for c in rows("conditions.csv"):
        if c["PATIENT"] in chosen_set and not c["STOP"] and "(disorder)" in c["DESCRIPTION"]:
            d = c["DESCRIPTION"].replace(" (disorder)", "")
            if d not in conditions[c["PATIENT"]] or c["START"] < conditions[c["PATIENT"]][d]:
                conditions[c["PATIENT"]][d] = c["START"]

    meds = defaultdict(set)
    for m in rows("medications.csv"):
        if m["PATIENT"] in chosen_set and not m["STOP"]:
            meds[m["PATIENT"]].add(m["DESCRIPTION"])

    obs = defaultdict(dict)          # latest value per measurement
    for o in rows("observations.csv"):
        key = OBSERVATIONS.get(o["DESCRIPTION"])
        if key and o["PATIENT"] in chosen_set:
            prev = obs[o["PATIENT"]].get(key)
            if prev is None or o["DATE"] > prev[0]:
                obs[o["PATIENT"]][key] = (o["DATE"], o["VALUE"])

    return [(pid, patients[pid], visit.get(pid), conditions[pid], sorted(meds[pid]), obs[pid])
            for pid in chosen]


# --- Writing one note --------------------------------------------------------

def write_note(p, visit, conds, meds, obs, rng: random.Random) -> Note:
    n = Note()
    first, last, prefix = p["FIRST"], p["LAST"], p["PREFIX"]
    dob = datetime.date.fromisoformat(p["BIRTHDATE"])
    visit_date = datetime.date.fromisoformat((visit or {}).get("START", "2026-09-01")[:10])
    age = years_since(dob)
    sex_word = "woman" if p["GENDER"] == "F" else "man"
    style = rng.choice(["clinic_review", "referral_letter", "telephone"])
    clinician = f"{rng.choice(CLINICIAN_FIRST)} {rng.choice(CLINICIAN_LAST)}"

    # Header: full identifiers
    title = {"clinic_review": "CLINIC REVIEW", "referral_letter": "REFERRAL LETTER",
             "telephone": "TELEPHONE FOLLOW-UP"}[style]
    n.add(f"{title}\nPatient: ")
    n.pii(f"{first} {last}", "PERSON", "full")
    n.add("    DOB: ")
    d_text, d_var = fmt_date(dob, rng)
    n.pii(d_text, "DATE", f"dob_{d_var}")
    n.add("    ")
    lead, mrn, mrn_var = fake_mrn(rng)
    n.add(lead)
    n.pii(mrn, "MRN", mrn_var)
    n.add("\nAddress: ")
    n.pii(p["ADDRESS"], "ADDRESS")
    n.add(", ")
    n.pii(p["CITY"], "CITY")
    n.add(f", {p['STATE']} ")                 # state is allowed - a precision trap
    n.pii(p["ZIP"], "ZIP")
    n.add("\nDate of visit: ")
    v_text, v_var = fmt_date(visit_date, rng)
    n.pii(v_text, "DATE", f"visit_{v_var}")
    n.add("\n\n")

    # Opening line: a later mention, often not the full name
    title_word, mention, m_var = name_variant(first, last, prefix, rng)
    if style == "referral_letter":
        n.add("Dear colleague,\n\nThank you for seeing " + title_word)
        n.pii(mention, "PERSON", m_var)
        n.add(f", a {age}-year-old {sex_word} known to our practice")
    elif style == "telephone":
        n.add("Spoke with " + title_word)
        n.pii(mention, "PERSON", m_var)
        n.add(f" by phone today. {age}-year-old {sex_word}")
    else:
        n.add(title_word)
        n.pii(mention, "PERSON", m_var)
        n.add(f" is a {age}-year-old {sex_word} seen for review")
    n.add(".\n\n")

    # History: diagnoses with YEARS only (allowed - a precision trap)
    n.add("Problems:\n")
    if conds:
        for desc, start in sorted(conds.items(), key=lambda kv: kv[1])[:6]:
            n.add(f"- {desc} (since {start[:4]})\n")
    else:
        n.add("- No active long-term conditions recorded\n")
    if rng.random() < 0.35:
        n.add(rng.choice(EPONYM_SENTENCES) + "\n")

    n.add("\nCurrent medication:\n")
    for m in meds[:5] or ["None"]:
        n.add(f"- {m}\n")

    # Measurements: numbers that are NOT identifiers
    n.add("\nExamination: ")
    bits = []
    if "sbp" in obs and "dbp" in obs:
        bits.append(f"BP {float(obs['sbp'][1]):.0f}/{float(obs['dbp'][1]):.0f} mmHg")
    if "bmi" in obs:
        bits.append(f"BMI {float(obs['bmi'][1]):.1f}")
    if "hba1c" in obs:
        bits.append(f"HbA1c {float(obs['hba1c'][1]):.1f}%")
    n.add(", ".join(bits) if bits else "unremarkable")
    n.add(".\n\n")

    # Social / contacts: relatives with word-like names, phones, emails
    n.add("Social: Lives in ")
    n.pii(p["CITY"], "CITY", "repeat")
    n.add(". ")
    if rng.random() < 0.7:
        relation = rng.choice(RELATIONS)
        rel_first, rel_last = rng.choice(WORDLIKE_FIRST), rng.choice(WORDLIKE_LAST)
        n.add(f"{relation.capitalize()} ")
        if rng.random() < 0.5:
            n.pii(f"{rel_first} {rel_last}", "PERSON", "relative_wordlike")
        else:
            n.pii(rel_first, "PERSON", "relative_wordlike_first_only")
        n.add(" is the main contact on ")
        ph, ph_var = fake_phone(rng)
        n.pii(ph, "PHONE", ph_var)
        n.add(".")
    n.add("\nPatient contact: ")
    ph, ph_var = fake_phone(rng)
    n.pii(ph, "PHONE", ph_var)
    if rng.random() < 0.6:
        n.add(", email ")
        local = f"{first}.{last[0]}".lower() if rng.random() < 0.5 else f"{first[0]}{last}".lower()
        n.pii(f"{local}{rng.randint(1, 99)}@{rng.choice(EMAIL_DOMAINS)}", "EMAIL")
    n.add(".\n")

    # Occasionally: national identifiers in admin lines
    if rng.random() < 0.3:
        n.add("Insurance verification: SSN ")
        ssn = p["SSN"] if rng.random() < 0.5 else p["SSN"].replace("-", "")
        n.pii(ssn, "SSN", "dashed" if "-" in ssn else "undashed")
        n.add(".\n")
    if p["DRIVERS"] and rng.random() < 0.2:
        n.add("ID checked: driving licence ")
        n.pii(p["DRIVERS"], "LICENSE")
        n.add(".\n")

    # Plan, mentioning the patient once more
    n.add("\nPlan: Continue current treatment. Review in 3 months. ")
    title_word, mention, m_var = name_variant(first, last, prefix, rng)
    n.add(title_word)
    n.pii(mention, "PERSON", m_var)
    n.add(" is aware of the plan.\n\nDr ")
    n.pii(clinician, "PERSON", "clinician")
    n.add("\n")
    return n


# --- Main steps ---------------------------------------------------------------

def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate() -> None:
    rng = random.Random(SEED)
    inputs = load_inputs(rng)

    notes, labels = [], []
    label_counts, variant_counts = Counter(), Counter()
    for i, (pid, p, visit, conds, meds, obs) in enumerate(inputs, start=1):
        note = write_note(p, visit, conds, meds, obs, rng)
        text = note.text()
        for s in note.spans:                        # the key must match the text exactly
            assert text[s["start"]:s["end"]] == s["text"], (i, s)
            label_counts[s["label"]] += 1
            variant_counts[f"{s['label']}:{s['variant']}"] += 1
        note_id = f"note-{i:04d}"
        notes.append({"note_id": note_id, "patient_id": pid,
                      "encounter_id": (visit or {}).get("Id"), "text": text})
        labels.append({"note_id": note_id, "spans": note.spans})

    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    notes_path, labels_path = DATASET_DIR / "notes.jsonl", DATASET_DIR / "labels.jsonl"
    notes_path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in notes))
    labels_path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in labels))

    manifest = {
        "dataset": DATASET,
        "version": DATASET_VERSION,
        "description": "Synthetic clinical notes with planted identifiers (notes.jsonl) and their exact positions (labels.jsonl).",
        "contains_identifiers": True,
        "identifier_note": "All identifiers are synthetic; phones use the 555-01xx fiction range and emails reserved example domains.",
        "source": {
            "dataset": "patients/v1",
            "manifest_sha256": sha256_of(PATIENTS_DIR / "manifest.json"),
        },
        "parameters": {"seed": SEED, "notes": NOTES, "reference_date": REFERENCE_DATE.isoformat()},
        "labels": dict(sorted(label_counts.items())),
        "variants": dict(sorted(variant_counts.items())),
        "not_identifiers_by_design": [
            "ages under 90", "years on their own", "state name",
            "lab values, doses, blood pressure", "eponymous diseases (e.g. Parkinson disease)",
        ],
        "files": {p.name: {"bytes": p.stat().st_size, "sha256": sha256_of(p)}
                  for p in (notes_path, labels_path)},
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    }
    (DATASET_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"notes": len(notes), "identifiers": sum(label_counts.values()),
                      "labels": manifest["labels"]}, indent=2))


def upload() -> None:
    """Copy the notes to S3 - but never over an existing version."""
    prefix = f"{DATASET}/{DATASET_VERSION}/"
    if not (DATASET_DIR / "manifest.json").exists():
        sys.exit("No notes found - run 'generate' first.")
    existing = subprocess.run(
        ["aws", "s3api", "list-objects-v2", "--bucket", RAW_BUCKET, "--prefix", prefix,
         "--max-keys", "1", "--query", "KeyCount", "--output", "text"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    if existing not in ("0", "None", ""):
        sys.exit(f"s3://{RAW_BUCKET}/{prefix} already has data. Versions are never overwritten - bump DATASET_VERSION.")
    subprocess.run(["aws", "s3", "sync", str(DATASET_DIR), f"s3://{RAW_BUCKET}/{prefix}"], check=True)
    print(f"Uploaded to s3://{RAW_BUCKET}/{prefix}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["generate", "upload"])
    args = parser.parse_args()
    generate() if args.command == "generate" else upload()


if __name__ == "__main__":
    main()
