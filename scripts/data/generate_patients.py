#!/usr/bin/env python3
"""
Generate a reproducible synthetic patient dataset with Synthea, and upload it.

    python3 scripts/data/generate_patients.py generate
    python3 scripts/data/generate_patients.py upload

Same Synthea version + same seeds + same reference date + same settings
= the same patients, every time. The manifest records all of them, plus a
checksum per file, so anyone can rebuild and verify patients/<version>.

Synthetic data only: every person is invented. The data still contains
realistic-looking identifiers (names, addresses, SSN-style numbers), so it
goes to the RAW bucket and is handled as if it were real.

Standard library only; needs Java 17+ and (for upload) the AWS CLI.
"""

import argparse
import csv
import datetime
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

# --- Pinned generator -------------------------------------------------------
SYNTHEA_VERSION = "v4.0.0"
SYNTHEA_SHA256 = "ed43c20ad40ba5c3bc724503a5af032715fe3c491620b766148e7c2361e6ecc1"
SYNTHEA_URL = (
    "https://github.com/synthetichealth/synthea/releases/download/"
    f"{SYNTHEA_VERSION}/synthea-with-dependencies.jar"
)

# --- Dataset definition (change any of these => new dataset version) --------
DATASET = "patients"
DATASET_VERSION = "v1"
POPULATION = 1000            # living people; Synthea also keeps those who died
SEED = 42                    # people's lives
CLINICIAN_SEED = 42          # doctors and hospitals assigned to them
AGE_RANGE = "18-90"          # adults only - trials here recruit adults
STATE = "Massachusetts"      # only affects towns and addresses
REFERENCE_DATE = "20261001"  # ages are calculated as of this FIXED date
END_DATE = "20261001"        # ...and the simulation stops here, not "now".
                             # Without it, visits still open at the end get
                             # the wall-clock time as their STOP (found by a
                             # reproducibility test: 3 visits differed per run).

# Synthea settings overridden on the command line
CONFIG = {
    "exporter.csv.export": "true",
    "exporter.fhir.export": "false",               # large JSON we don't use
    "exporter.hospital.fhir.export": "false",
    "exporter.practitioner.fhir.export": "false",
    "generate.append_numbers_to_person_names": "false",  # "Jose", not "Jose871"
}

# Tables we keep (the rest - claims, payers, etc. - aren't needed)
TABLES = [
    "patients.csv",      # one row per person: demographics + identifiers
    "conditions.csv",    # diagnoses
    "medications.csv",   # prescriptions
    "observations.csv",  # measurements and lab results
    "encounters.csv",    # visits (notes in PR 8 hang off these)
    "allergies.csv",     # a common trial exclusion
]

RAW_BUCKET = "ctm-raw-359013545044"

REPO_ROOT = Path(__file__).resolve().parents[2]
WORK_DIR = REPO_ROOT / "data"                       # git-ignored
JAR_PATH = WORK_DIR / "tools" / f"synthea-{SYNTHEA_VERSION}.jar"
RUN_DIR = WORK_DIR / "synthea-run"                  # Synthea's raw output
DATASET_DIR = WORK_DIR / DATASET / DATASET_VERSION  # what we upload


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def get_synthea() -> None:
    """Download the pinned jar once, and refuse to run anything else."""
    if not JAR_PATH.exists():
        JAR_PATH.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading Synthea {SYNTHEA_VERSION} ...")
        urllib.request.urlretrieve(SYNTHEA_URL, JAR_PATH)
    actual = sha256_of(JAR_PATH)
    if actual != SYNTHEA_SHA256:
        JAR_PATH.unlink()
        sys.exit(f"Checksum mismatch for Synthea jar (got {actual}) - deleted it. Not running.")
    print(f"Synthea {SYNTHEA_VERSION} checksum OK")


def run_synthea() -> None:
    if RUN_DIR.exists():
        shutil.rmtree(RUN_DIR)  # a clean run every time
    cmd = [
        "java", "-jar", str(JAR_PATH),
        "-p", str(POPULATION),
        "-s", str(SEED),
        "-cs", str(CLINICIAN_SEED),
        "-a", AGE_RANGE,
        "-r", REFERENCE_DATE,
        "-e", END_DATE,
        "--exporter.baseDirectory", f"{RUN_DIR}/",
    ]
    for key, value in CONFIG.items():
        cmd += [f"--{key}", value]
    cmd.append(STATE)
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)


def count_rows(path: Path) -> int:
    with path.open(newline="") as f:
        return sum(1 for _ in csv.reader(f)) - 1  # minus header


def summarise_patients(path: Path) -> dict:
    ref = datetime.date(int(REFERENCE_DATE[:4]), int(REFERENCE_DATE[4:6]), int(REFERENCE_DATE[6:]))
    alive = deceased = 0
    sexes: dict = {}
    ages = []
    names_with_digits = 0
    with path.open(newline="") as f:
        for r in csv.DictReader(f):
            sexes[r["GENDER"]] = sexes.get(r["GENDER"], 0) + 1
            if r["DEATHDATE"]:
                deceased += 1
                continue
            alive += 1
            born = datetime.date.fromisoformat(r["BIRTHDATE"])
            ages.append((ref - born).days // 365)
            if any(ch.isdigit() for ch in r["FIRST"] + r["LAST"]):
                names_with_digits += 1
    return {
        "alive": alive,
        "deceased": deceased,
        "sex": sexes,
        "age_min_alive": min(ages),
        "age_max_alive": max(ages),
        "names_with_digits": names_with_digits,
    }


def write_sorted(src: Path, dst: Path) -> None:
    """Copy a CSV with its rows in a fixed (sorted) order.

    Synthea simulates people in parallel and writes each one as soon as it
    finishes, so row order changes between runs even when the data doesn't.
    Sorting gives a canonical order, so identical data => identical bytes
    => identical checksums.
    """
    with src.open(newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = sorted(reader)
    with dst.open("w", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def build_dataset() -> None:
    src = RUN_DIR / "csv"
    if DATASET_DIR.exists():
        shutil.rmtree(DATASET_DIR)
    DATASET_DIR.mkdir(parents=True)

    files = {}
    for table in TABLES:
        p = DATASET_DIR / table
        write_sorted(src / table, p)
        files[table] = {"rows": count_rows(p), "bytes": p.stat().st_size, "sha256": sha256_of(p)}

    summary = summarise_patients(DATASET_DIR / "patients.csv")
    manifest = {
        "dataset": DATASET,
        "version": DATASET_VERSION,
        "description": "Synthetic adult patients for clinical-trial matching. Every person is invented.",
        "contains_identifiers": True,
        "identifier_note": "Realistic but fake names, addresses and ID numbers - stored in the raw bucket and handled as if real.",
        "generator": {
            "name": "Synthea",
            "version": SYNTHEA_VERSION,
            "jar_sha256": SYNTHEA_SHA256,
            "source": SYNTHEA_URL,
            "licence": "Apache-2.0",
        },
        "parameters": {
            "population_alive": POPULATION,
            "seed": SEED,
            "clinician_seed": CLINICIAN_SEED,
            "age_range": AGE_RANGE,
            "state": STATE,
            "reference_date": REFERENCE_DATE,
            "end_date": END_DATE,
            "config": CONFIG,
        },
        "summary": summary,
        "files": files,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    }
    (DATASET_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"summary": summary, "rows": {t: f["rows"] for t, f in files.items()}}, indent=2))

    if summary["names_with_digits"]:
        print(f"WARNING: {summary['names_with_digits']} names contain digits - name setting not applied")


def upload() -> None:
    """Copy the dataset to S3 - but never over an existing version."""
    prefix = f"{DATASET}/{DATASET_VERSION}/"
    if not (DATASET_DIR / "manifest.json").exists():
        sys.exit("No dataset found - run 'generate' first.")
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
    if args.command == "generate":
        get_synthea()
        run_synthea()
        build_dataset()
    else:
        upload()


if __name__ == "__main__":
    main()
