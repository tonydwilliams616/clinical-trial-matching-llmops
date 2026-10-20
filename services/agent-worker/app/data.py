"""
The synthetic datasets, loaded once per worker process and kept in memory
(a few MB):

    trials/v1/criteria.jsonl     de-identified bucket   trial criteria
    patients/v1/patients.csv     raw bucket             birth date, sex
    patients/v1/conditions.csv   raw bucket             active diagnoses
    notes/v1/notes.jsonl         raw bucket             one note per patient

The raw bucket holds synthetic identifiers and is read only inside the
cluster; notes leave the worker only towards the PII gateway.
"""

import csv
import io
import json
from collections import defaultdict


class Dataset:
    def __init__(self, trials: dict, patients: dict, conditions: dict, notes: dict):
        self._trials, self._patients, self._conditions, self._notes = trials, patients, conditions, notes

    @classmethod
    def from_text(cls, criteria_jsonl: str, patients_csv: str, conditions_csv: str, notes_jsonl: str):
        trials = {r["nct_id"]: r for r in map(json.loads, filter(None, criteria_jsonl.splitlines()))}
        patients = {r["Id"]: {"BIRTHDATE": r["BIRTHDATE"], "GENDER": r["GENDER"]}
                    for r in csv.DictReader(io.StringIO(patients_csv)) if not r.get("DEATHDATE")}
        conditions = defaultdict(list)
        for r in csv.DictReader(io.StringIO(conditions_csv)):
            if not r.get("STOP"):
                conditions[r["PATIENT"]].append(r["DESCRIPTION"])
        notes = {r["patient_id"]: r["text"] for r in map(json.loads, filter(None, notes_jsonl.splitlines()))}
        return cls(trials, patients, dict(conditions), notes)

    @classmethod
    def from_s3(cls, s3, raw_bucket: str, data_bucket: str):
        def read(bucket, key):
            return s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode()
        return cls.from_text(
            read(data_bucket, "trials/v1/criteria.jsonl"),
            read(raw_bucket, "patients/v1/patients.csv"),
            read(raw_bucket, "patients/v1/conditions.csv"),
            read(raw_bucket, "notes/v1/notes.jsonl"),
        )

    def trial(self, nct_id: str) -> dict:
        return self._trials[nct_id]

    def patient_ids_with_notes(self) -> list[str]:
        return [pid for pid in self._notes if pid in self._patients]

    def patient(self, pid: str) -> dict:
        return self._patients[pid]

    def active_conditions(self, pid: str) -> list[str]:
        return self._conditions.get(pid, [])

    def note(self, pid: str) -> str:
        return self._notes[pid]
