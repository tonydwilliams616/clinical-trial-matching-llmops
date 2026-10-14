#!/usr/bin/env python3
"""
Fetch a snapshot of recruiting clinical trials from ClinicalTrials.gov, and upload it.

    python3 scripts/data/fetch_trials.py fetch
    python3 scripts/data/fetch_trials.py upload

The registry is LIVE - trials open, close and change daily - so this saves a
dated snapshot (trials/<version>) and the manifest records the exact query
and retrieval time. The snapshot, not the query, is what gets versioned.

Data minimisation: trial records include investigators' names, phone numbers
and emails. We never need them, so only the modules listed in KEEP_MODULES
are saved. With no personal data left, the snapshot goes to the
DE-IDENTIFIED bucket, which later phases (and the LLM) may read.

Source: ClinicalTrials.gov, U.S. National Library of Medicine (API v2).
Standard library only; needs the AWS CLI for upload.
"""

import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://clinicaltrials.gov/api/v2/studies"

DATASET = "trials"
DATASET_VERSION = "v1"

# Conditions chosen from what Synthea generates often in patients/v1, so the
# matcher has real candidates. Search term -> how many trials to keep.
CONDITIONS = {
    "type 2 diabetes": 8,
    "hypertension": 8,
    "chronic kidney disease": 8,
    "hyperlipidemia": 6,
}
PAGE_SIZE = 100  # results requested per condition, before our own filters

# One word can mean several diseases: "hypertension" also appears in lung
# (pulmonary), eye (ocular) and pregnancy conditions. A trial is skipped if
# its listed conditions or title contain any of these words for that search.
# (Found by reviewing the first snapshot: only 3 of 8 hypertension trials
# were about everyday high blood pressure.)
EXCLUDE_TERMS = {
    "type 2 diabetes": ["type 1", "gestational", "prediabet"],
    "hypertension": [
        "pulmonary", "ocular", "intraocular", "glaucoma", "preeclampsia",
        "pre-eclampsia", "pregnan", "gestational", "portal", "intracranial",
        "fetal", "foetal", "neonat", "diaphragmatic hernia",
    ],
    "chronic kidney disease": ["transplant"],
    "hyperlipidemia": [],
}

# Only these parts of each record are kept (no contacts/locations module).
KEEP_MODULES = [
    "identificationModule",  # NCT ID and title
    "statusModule",          # recruiting status and dates
    "conditionsModule",      # conditions and keywords
    "designModule",          # study type and phase
    "descriptionModule",     # brief summary (useful for retrieval later)
    "eligibilityModule",     # ages, sex, and the free-text criteria
]

DEIDENTIFIED_BUCKET = "ctm-deidentified-359013545044"

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "data" / DATASET / DATASET_VERSION  # git-ignored


def get_json(params: dict) -> dict:
    url = f"{API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "ctm-portfolio-project/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def age_in_years(text):
    """'18 Years' -> 18.0, '6 Months' -> 0.5; None if missing."""
    if not text:
        return None
    m = re.match(r"(\d+)\s*(Year|Month|Week|Day)", text)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    return {"Year": n, "Month": n / 12, "Week": n / 52, "Day": n / 365}[unit]


def suitable(study: dict, condition: str) -> bool:
    """Interventional, for adults WITH the condition, with real free-text criteria."""
    ps = study.get("protocolSection", {})
    design = ps.get("designModule", {})
    elig = ps.get("eligibilityModule", {})
    if design.get("studyType") != "INTERVENTIONAL":
        return False
    if "ADULT" not in elig.get("stdAges", []):
        return False
    if len(elig.get("eligibilityCriteria", "")) < 300:
        return False
    # Healthy-volunteer and Phase 1-only trials test safety in people WITHOUT
    # the disease - none of our patients could ever match them.
    if elig.get("healthyVolunteers"):
        return False
    phases = set(design.get("phases", []))
    if phases and phases <= {"PHASE1", "EARLY_PHASE1"}:
        return False
    text = " ".join(ps.get("conditionsModule", {}).get("conditions", [])
                    + [ps.get("identificationModule", {}).get("briefTitle", "")]).lower()
    if any(term in text for term in EXCLUDE_TERMS.get(condition, [])):
        return False
    return True


def minimise(study: dict) -> dict:
    ps = study["protocolSection"]
    return {"protocolSection": {k: ps[k] for k in KEEP_MODULES if k in ps}}


def flatten(study: dict, matched_condition: str) -> dict:
    """One easy-to-read row per trial - what the matcher will use."""
    ps = study["protocolSection"]
    ident, elig = ps["identificationModule"], ps["eligibilityModule"]
    return {
        "nct_id": ident["nctId"],
        "title": ident.get("briefTitle"),
        "matched_condition": matched_condition,
        "conditions": ps.get("conditionsModule", {}).get("conditions", []),
        "phases": ps.get("designModule", {}).get("phases", []),
        "sex": elig.get("sex"),
        "minimum_age": elig.get("minimumAge"),
        "maximum_age": elig.get("maximumAge"),
        "minimum_age_years": age_in_years(elig.get("minimumAge")),
        "maximum_age_years": age_in_years(elig.get("maximumAge")),
        "healthy_volunteers": elig.get("healthyVolunteers"),
        "eligibility_criteria": elig.get("eligibilityCriteria"),
        "brief_summary": ps.get("descriptionModule", {}).get("briefSummary"),
    }


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch() -> None:
    retrieved_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    kept: dict = {}         # nct_id -> minimised study
    rows: dict = {}         # nct_id -> flat row
    per_condition: dict = {}

    for condition, want in CONDITIONS.items():
        data = get_json({
            "query.cond": condition,
            "filter.overallStatus": "RECRUITING",
            "pageSize": PAGE_SIZE,
            "format": "json",
        })
        studies = data.get("studies", [])
        if not studies:
            sys.exit(f"No studies returned for '{condition}' - check the API response format.")
        taken = 0
        for s in studies:
            if taken >= want:
                break
            if not suitable(s, condition):
                continue
            nct = s["protocolSection"]["identificationModule"]["nctId"]
            if nct in kept:  # e.g. a diabetes + CKD trial found twice
                continue
            kept[nct] = minimise(s)
            rows[nct] = flatten(s, condition)
            taken += 1
        per_condition[condition] = {"returned": len(studies), "kept": taken}
        print(f"{condition}: {len(studies)} returned, {taken} kept")

    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    order = sorted(kept)  # canonical order
    studies_path = DATASET_DIR / "studies.json"
    criteria_path = DATASET_DIR / "criteria.jsonl"
    studies_path.write_text(json.dumps([kept[n] for n in order], indent=2, sort_keys=True) + "\n")
    criteria_path.write_text("".join(json.dumps(rows[n], sort_keys=True) + "\n" for n in order))

    lengths = [len(r["eligibility_criteria"]) for r in rows.values()]
    manifest = {
        "dataset": DATASET,
        "version": DATASET_VERSION,
        "description": "Snapshot of recruiting interventional trials open to adults, for the conditions below.",
        "contains_identifiers": False,
        "minimisation_note": "Only these modules are kept; contacts and locations (investigator names, phones, emails) are dropped at fetch time.",
        "kept_modules": KEEP_MODULES,
        "source": {
            "name": "ClinicalTrials.gov",
            "publisher": "U.S. National Library of Medicine",
            "api": API,
            "retrieved_at": retrieved_at,
        },
        "query": {
            "conditions": CONDITIONS,
            "filter.overallStatus": "RECRUITING",
            "pageSize": PAGE_SIZE,
            "client_side_filters": "studyType INTERVENTIONAL; stdAges includes ADULT; criteria text >= 300 chars; no healthy volunteers; not Phase 1-only; no excluded terms in conditions/title; de-duplicated by NCT ID",
            "exclude_terms": EXCLUDE_TERMS,
        },
        "per_condition": per_condition,
        "summary": {
            "trials": len(rows),
            "criteria_chars_min": min(lengths),
            "criteria_chars_max": max(lengths),
            "criteria_chars_avg": round(sum(lengths) / len(lengths)),
        },
        "files": {
            p.name: {"bytes": p.stat().st_size, "sha256": sha256_of(p)}
            for p in (studies_path, criteria_path)
        },
    }
    (DATASET_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest["summary"], indent=2))


def upload() -> None:
    """Copy the snapshot to S3 - but never over an existing version."""
    prefix = f"{DATASET}/{DATASET_VERSION}/"
    if not (DATASET_DIR / "manifest.json").exists():
        sys.exit("No snapshot found - run 'fetch' first.")
    existing = subprocess.run(
        ["aws", "s3api", "list-objects-v2", "--bucket", DEIDENTIFIED_BUCKET, "--prefix", prefix,
         "--max-keys", "1", "--query", "KeyCount", "--output", "text"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    if existing not in ("0", "None", ""):
        sys.exit(f"s3://{DEIDENTIFIED_BUCKET}/{prefix} already has data. Versions are never overwritten - bump DATASET_VERSION.")
    subprocess.run(["aws", "s3", "sync", str(DATASET_DIR), f"s3://{DEIDENTIFIED_BUCKET}/{prefix}"], check=True)
    print(f"Uploaded to s3://{DEIDENTIFIED_BUCKET}/{prefix}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["fetch", "upload"])
    args = parser.parse_args()
    fetch() if args.command == "fetch" else upload()


if __name__ == "__main__":
    main()
