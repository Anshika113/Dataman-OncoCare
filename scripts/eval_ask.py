"""Score the assistant on a frozen list of labelled sentences.

    python scripts/eval_ask.py docs/eval/commands_dev.csv --local-only
    CARE_SARVAM_KEY=... python scripts/eval_ask.py docs/eval/commands_test.csv

Compares the phrase matcher with Sarvam on the same sentences. Sarvam's output
can differ between runs, so one run is written out and that run is what gets
reported. The sentences are synthetic: this measures whether the mechanism
works on the phrasing we thought of, not accuracy in a real clinic.

The headline numbers are the ones that matter when it is wrong:

* wrong action  a card for an action nobody asked for
* clinical      clinical sentences declined, out of all clinical sentences
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import defaultdict
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from engine import ask, propose  # noqa: E402
from services import sarvam  # noqa: E402

#: The seeded demo roster. Sentences name these people, and none of them exist.
DOCTORS = [{"id": "DOC-0001", "name": "Dr. Amina Khan"},
           {"id": "DOC-0002", "name": "Dr. Ben Ortiz"},
           {"id": "DOC-0003", "name": "Dr. Chloe Wu"},
           {"id": "DOC-0004", "name": "Dr. Dan Meyer"},
           {"id": "DOC-0005", "name": "Dr. Elena Ross"}]
NAMES = {"P1": "Meera Nair", "P2": "Usman Tariq", "P3": "Rahim Ullah",
         "P4": "Sara Ahmed", "P5": "Bilal Hussain"}
ACTIONS = {a.id for a in propose.ACTIONS}
#: How the sheet labels names written in Devanagari.
SPOKEN = {"मीरा": "Meera Nair", "उस्मान": "Usman Tariq"}


def local_choice(sentence: str) -> dict:
    a = ask.resolve(sentence, NAMES)
    if a.kind == "refused":
        return {"choice": "clinical"}
    if a.kind == "view":
        return {"choice": a.view,
                "patient": NAMES.get(a.patient_query, "")}
    return {"choice": "none"}


def model_choice(sentence: str) -> dict:
    """Same order as the API: refuse locally first, then ask the model."""
    if ask.clinical_reason(sentence):
        return {"choice": "clinical", "refused_locally": True}
    masked, mask = propose.mask_names(sentence, NAMES)
    out = sarvam.choose(masked, DOCTORS, propose.catalogue(), propose.choices())
    ids = mask.get(str(out.get("patient") or ""))
    if ids:
        out["patient"] = NAMES.get(ids[0], "")
    return out


def _details_right(row: dict, got: dict) -> bool:
    # Scored the way the app reads it: a named patient must resolve to that one
    # person, and "this patient" must come back with no name, or the app asks.
    said = propose.said_patient(got)
    want = SPOKEN.get(row["patient"], row["patient"])
    if want:
        ids = ask.find_patient(said, NAMES)
        if len(ids) != 1 or NAMES[ids[0]] != want:
            return False
    elif said:
        return False
    if row["doctor"] and str(got.get("doctor") or "") != row["doctor"]:
        return False
    if row["to_doctor"] and propose.receiving_doctor(got) != row["to_doctor"]:
        return False
    if row["from_time"] and str(got.get("from_time") or "") != row["from_time"]:
        return False
    if row["minutes"] and str(got.get("minutes") or "") != row["minutes"]:
        return False
    return True


def score(rows: list[dict], answers: list[Optional[dict]]) -> dict:
    n = len(rows)
    right = wrong_action = clinical = clinical_all = 0
    actions = actions_right = false_refusals = failed = 0
    by_lang: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for row, got in zip(rows, answers):
        want = row["choice"]
        by_lang[row["language"]][1] += 1
        if got is None:
            failed += 1
            continue
        c = got.get("choice")
        if c == want:
            right += 1
            by_lang[row["language"]][0] += 1
        if c in ACTIONS and c != want:
            wrong_action += 1
        if want == "clinical":
            clinical_all += 1
            clinical += c == "clinical"
        elif c == "clinical":
            false_refusals += 1
        if want in ACTIONS:
            actions += 1
            actions_right += c == want and _details_right(row, got)
    return {
        "sentences": n,
        "right_choice": right,
        "right_choice_pct": round(100 * right / n, 1) if n else 0,
        "wrong_action_cards": wrong_action,
        "clinical_declined": f"{clinical}/{clinical_all}",
        "operational_wrongly_refused": false_refusals,
        "actions_fully_right": f"{actions_right}/{actions}",
        "call_failures": failed,
        "by_language": {k: f"{v[0]}/{v[1]}" for k, v in sorted(by_lang.items())},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--local-only", action="store_true")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    with open(args.csv_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    # A sentence the prompt quotes as an example proves nothing about reading.
    quoted = [r for r in rows if f'"{r["sentence"]}"' in sarvam.SYSTEM]
    rows = [r for r in rows if r not in quoted]
    print(f"{len(quoted)} sentence(s) skipped: quoted in the prompt", file=sys.stderr)

    report: dict = {"file": os.path.basename(args.csv_path),
                    "when": time.strftime("%Y-%m-%d %H:%M"),
                    "local": score(rows, [local_choice(r["sentence"]) for r in rows])}
    detail = []
    if not args.local_only:
        if not sarvam.enabled():
            sys.exit("CARE_SARVAM_KEY is not set. Use --local-only for the baseline.")
        answers: list[Optional[dict]] = []
        times = []
        for r in rows:
            began = time.time()
            try:
                answers.append(model_choice(r["sentence"]))
            except sarvam.SarvamError:
                answers.append(None)
            times.append(time.time() - began)
            time.sleep(1.1)     # Sarvam's pay-as-you-go limit is 60 a minute
        report["sarvam"] = score(rows, answers)
        report["sarvam"]["median_seconds"] = round(sorted(times)[len(times) // 2], 2)
        report["sarvam"]["model"] = os.environ.get("CARE_SARVAM_MODEL",
                                                  "sarvam-105b-conversations")
        detail = [{"id": r["id"], "sentence": r["sentence"], "want": r["choice"],
                   "got": a} for r, a in zip(rows, answers)]

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({**report, "detail": detail}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
