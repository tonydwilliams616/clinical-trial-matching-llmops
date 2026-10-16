#!/usr/bin/env python3
"""
Score the pii-gateway against the notes/v1 answer key - the release gate.

    python3 scripts/eval/score_gateway.py --data-dir data/notes/v1 \
        --url http://localhost:8080 --min-recall 0.90

Sends every note to a running gateway (POST /v1/mask), then compares what it
found with labels.jsonl, which records exactly where each planted identifier is.

  recall     share of real identifiers that were FULLY masked. A half-masked
             name still leaks, so partial cover counts as a miss. This is the
             safety number and the one the gate enforces.
  precision  share of masks that really were identifiers. Low precision only
             means harmless text got hidden - a usefulness cost, not a leak.

Exit code 1 if recall is below --min-recall, so CI fails and nothing is pushed.

Prints counts only - never note text or identifier values (CI logs are public).
Standard library only.
"""

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def verify_manifest(data_dir: Path) -> dict:
    """Refuse to score against files that don't match their manifest."""
    manifest = json.loads((data_dir / "manifest.json").read_text())
    for name, meta in manifest["files"].items():
        digest = hashlib.sha256((data_dir / name).read_bytes()).hexdigest()
        if digest != meta["sha256"]:
            sys.exit(f"{name}: SHA-256 does not match manifest.json - wrong or corrupted dataset")
    return manifest


def wait_until_ready(url: str, timeout_s: int) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/readyz", timeout=5) as r:
                if r.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
        time.sleep(2)
    sys.exit(f"gateway at {url} not ready after {timeout_s}s")


def mask(url: str, text: str) -> list[dict]:
    req = urllib.request.Request(
        f"{url}/v1/mask",
        data=json.dumps({"text": text}).encode(),
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())["findings"]


def coverage(span: dict, findings: list[dict], text: str) -> float:
    """Share of the identifier's non-space characters covered by any finding.

    Spaces are ignored: "John" + "Smith" found separately still fully
    covers "John Smith".
    """
    positions = [i for i in range(span["start"], span["end"]) if not text[i].isspace()]
    if not positions:
        return 1.0
    covered = sum(1 for i in positions if any(f["start"] <= i < f["end"] for f in findings))
    return covered / len(positions)


def overlaps(a: dict, b: dict) -> bool:
    return a["start"] < b["end"] and b["start"] < a["end"]


def score(notes: list[dict], labels: dict, results: dict) -> dict:
    total, full, partial = Counter(), Counter(), Counter()
    var_total, var_full = Counter(), Counter()
    true_pos, false_pos = 0, Counter()

    for note in notes:
        text, findings = note["text"], results[note["note_id"]]
        spans = labels[note["note_id"]]
        for s in spans:
            key = f"{s['label']}:{s['variant']}"
            total[s["label"]] += 1
            var_total[key] += 1
            c = coverage(s, findings, text)
            if c == 1.0:
                full[s["label"]] += 1
                var_full[key] += 1
            elif c > 0:
                partial[s["label"]] += 1
        for f in findings:
            if any(overlaps(f, s) for s in spans):
                true_pos += 1
            else:
                false_pos[f["label"]] += 1

    n_total, n_full = sum(total.values()), sum(full.values())
    n_found = true_pos + sum(false_pos.values())
    weakest = sorted(
        ((k, var_full[k] / n, n) for k, n in var_total.items() if n >= 10),
        key=lambda x: x[1],
    )[:8]
    return {
        "identifiers": n_total,
        "recall": round(n_full / n_total, 4) if n_total else 0.0,
        "partially_masked": sum(partial.values()),
        "findings": n_found,
        "precision": round(true_pos / n_found, 4) if n_found else 0.0,
        "by_label": {
            label: {
                "identifiers": n,
                "recall": round(full[label] / n, 4),
                "partial": partial[label],
            }
            for label, n in sorted(total.items())
        },
        "weakest_variants": [{"variant": k, "recall": round(r, 4), "n": n} for k, r, n in weakest],
        "false_positives_by_label": dict(false_pos.most_common()),
    }


def markdown(report: dict, min_recall: float, passed: bool) -> str:
    lines = [
        f"### De-identification benchmark: {'PASS' if passed else 'FAIL'}",
        "",
        f"Recall **{report['recall']:.1%}** (gate: {min_recall:.1%}) · "
        f"precision **{report['precision']:.1%}** · "
        f"{report['identifiers']} identifiers in {report['notes']} notes · "
        f"{report['partially_masked']} partially masked",
        "",
        "| Label | Identifiers | Recall | Partial |",
        "| --- | ---: | ---: | ---: |",
    ]
    for label, r in report["by_label"].items():
        lines.append(f"| {label} | {r['identifiers']} | {r['recall']:.1%} | {r['partial']} |")
    lines += ["", "Weakest variants:", ""]
    lines += [f"- `{v['variant']}`: {v['recall']:.1%} of {v['n']}" for v in report["weakest_variants"]]
    lines += ["", f"False positives by label: {report['false_positives_by_label']}", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, required=True, help="folder with notes.jsonl, labels.jsonl, manifest.json")
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument("--min-recall", type=float, required=True)
    parser.add_argument("--report", type=Path, default=Path("benchmark-report.json"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--ready-timeout", type=int, default=180)
    args = parser.parse_args()

    manifest = verify_manifest(args.data_dir)
    notes = load_jsonl(args.data_dir / "notes.jsonl")
    labels = {r["note_id"]: r["spans"] for r in load_jsonl(args.data_dir / "labels.jsonl")}

    wait_until_ready(args.url, args.ready_timeout)
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        found = list(pool.map(lambda n: mask(args.url, n["text"]), notes))
    results = {n["note_id"]: f for n, f in zip(notes, found)}
    elapsed = time.perf_counter() - started

    report = score(notes, labels, results)
    report.update({
        "dataset": f"{manifest['dataset']}/{manifest['version']}",
        "notes": len(notes),
        "min_recall": args.min_recall,
        "seconds": round(elapsed, 1),
    })
    passed = report["recall"] >= args.min_recall
    report["passed"] = passed

    args.report.write_text(json.dumps(report, indent=2) + "\n")
    summary = markdown(report, args.min_recall, passed)
    print(summary)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as fh:
            fh.write(summary)

    if not passed:
        sys.exit(f"Recall {report['recall']:.1%} is below the gate of {args.min_recall:.1%}")


if __name__ == "__main__":
    main()
