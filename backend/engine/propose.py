"""Turning a sentence a doctor said into a card they can confirm.

"Give me ten more minutes" and "Meera ko Dr. Ben ko de do" are already things a
consultant says out loud. A language model is the right tool for reading them,
because nobody can list every way a busy clinic says them in three languages.
It is the wrong tool for everything after that, so this module keeps it to one
job: choosing from a fixed list.

* **It proposes; a person confirms.** Nothing here writes. A confirmed card
  calls the same endpoint the button calls, with its role checks and its undo.
* **Its answer is checked, not trusted.** An unknown choice, doctor or time is
  thrown away, and a patient who cannot be pinned down is a question to the
  person asking rather than a guess.
* **It sees a sentence.** No record, no result, no count — and a patient's name
  typed in Latin script reaches it only as ``PATIENT_1``.

Pure module: no I/O, no clock, no network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from .ask import SUGGESTIONS, VIEW_BY_ID, VIEWS, Ask, find_patient
from .clinic_control import LIVE, _name
from .state import Appointment, SystemState
from .timeutils import to_min


@dataclass(frozen=True)
class ActionDef:
    id: str
    purpose: str


#: Every change the assistant may propose. Each one is an endpoint that already
#: exists, and adding to this list is the only way to widen what it can suggest.
ACTIONS: tuple[ActionDef, ...] = (
    ActionDef("extend", "give the current or a named patient more minutes"),
    ActionDef("pull_forward", "send the doctor's next patient in now"),
    ActionDef("hand_off", "give a patient to another named doctor, with an "
                          "optional note for that doctor"),
    ActionDef("close_list", "stop taking patients after a given time today"),
)
ACTION_BY_ID = {a.id: a for a in ACTIONS}

#: What "this patient" sounds like. Giving away the wrong patient is the worst
#: mistake on the list, so a hand-off names someone or says one of these.
_THIS = re.compile(
    r"\b(this|current|ye|yeh|yah|is|iss|isko|inko|abhi|ya|hya)\b|इस|इन्हें|इनको|ये|या\s|ह्या",
    re.I)

#: A model asked for a name sometimes answers "is patient". Every word has to
#: be on this list, so "Vitram patient" still counts as a name it could not match.
_NOT_A_NAME = {
    "this", "the", "current", "is", "iss", "ye", "yeh", "yah", "ya", "hya",
    "isko", "inko", "abhi", "wale", "wala", "patient", "patientla", "mareez",
    "marij", "mariz", "rugna", "rugnala", "इस", "ये", "यह", "या", "ह्या", "इनको",
    "पेशेंट", "पेशंट", "पेशंटला", "मरीज़", "मरीज", "रुग्ण", "रुग्णाला",
}

#: The model's way of saying it should not be the one answering.
CLINICAL, NONE = "clinical", "none"


def catalogue() -> list[dict[str, str]]:
    """The whole surface offered to a model."""
    return ([{"id": v.id, "kind": "lookup", "purpose": v.purpose} for v in VIEWS]
            + [{"id": a.id, "kind": "action", "purpose": a.purpose}
               for a in ACTIONS])


def choices() -> list[str]:
    return [v.id for v in VIEWS] + [a.id for a in ACTIONS] + [CLINICAL, NONE]


#: Marathi joins these to a name: "Vikramla" is "to Vikram".
_MARATHI_ENDING = r"(?:la|na|ne|cha|chi|che)?"


def mask_names(question: str, names: dict[str, str]) -> tuple[str, dict[str, list[str]]]:
    """Swap patient names for placeholders, and say which ids each one meant.

    Two people called Fatima share one placeholder, so the ambiguity survives
    the round trip and comes back as a question.
    """
    spoken: dict[str, list[str]] = {}
    for pid, name in names.items():
        low = (name or "").strip().lower()
        for part in {low, low.split(" ")[0]}:
            if len(part) >= 3 and re.search(
                    r"\b" + re.escape(part) + _MARATHI_ENDING + r"\b",
                    question, re.I):
                spoken.setdefault(part, []).append(pid)

    masked = question
    mask: dict[str, list[str]] = {}
    for part in sorted(spoken, key=len, reverse=True):
        token = f"PATIENT_{len(mask) + 1}"
        masked, hits = re.subn(r"\b" + re.escape(part) + _MARATHI_ENDING + r"\b",
                               token, masked, flags=re.I)
        if hits:
            mask[token] = spoken[part]
    return masked, mask


def _unclear(reason: str) -> Ask:
    return Ask(kind="unclear", reason=reason, via="model",
               suggestions=SUGGESTIONS)


def said_patient(choice: dict) -> str:
    """The name the model reported, or "" if it only meant this patient."""
    said = str(choice.get("patient") or "").strip()
    return "" if all(w in _NOT_A_NAME for w in said.lower().split()) else said


def _patient_ids(raw: Any, mask: dict[str, list[str]],
                 names: dict[str, str]) -> list[str]:
    value = str(raw or "").strip()
    if not value:
        return []
    if value in mask:
        return mask[value]
    return find_patient(value, names)


def _today(state: SystemState, patient_id: str, day: str) -> list[Appointment]:
    return [a for a in state.appointments.values()
            if a.patient_id == patient_id and a.eff_date == day
            and a.status in LIVE]


def _in_the_room(state: SystemState, doctor_id: str, now: str,
                 day: str) -> Optional[Appointment]:
    """Who "this patient" means: the visit under way on this doctor's list."""
    rows = [a for a in state.appointments.values()
            if a.doctor_id == doctor_id and a.eff_date == day
            and a.status in LIVE and a.started_at
            and to_min(a.slot_start) <= to_min(now) < to_min(a.slot_end)]
    return rows[0] if len(rows) == 1 else None


def receiving_doctor(choice: dict) -> str:
    """Models often put a hand-off's one named doctor under ``doctor``."""
    return str(choice.get("to_doctor") or choice.get("doctor") or "").strip()


def _clock(raw: Any) -> str:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(raw or "").strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return ""
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def read_choice(choice: Any, state: SystemState, now: str, day: str,
                mask: dict[str, list[str]], names: dict[str, str],
                my_doctor_id: str = "", sentence: str = "") -> Optional[Ask]:
    """Check what the model chose. ``None`` hands the question back to the
    local matcher, which is what happens with no model at all."""
    if not isinstance(choice, dict):
        return None
    cid = str(choice.get("choice") or "").strip()

    if cid == CLINICAL:
        return Ask(kind="refused", via="model", suggestions=SUGGESTIONS,
                   reason="That sounds like a clinical question. That is the "
                          "doctor's call, and I only help run the clinic.")

    said = said_patient(choice)
    pids = _patient_ids(said, mask, names)

    view = VIEW_BY_ID.get(cid)
    if view is not None:
        if view.id != "patient":
            return Ask(kind="view", view=view.id, title=view.title, via="model")
        if len(pids) != 1:
            return _unclear("I could not tell which patient you meant.")
        return Ask(kind="view", view=view.id, title=view.title, via="model",
                   patient_query=pids[0])

    if cid not in ACTION_BY_ID:
        return None

    # On a hand-off the named doctor is the one receiving, not whose list it is.
    named = "" if cid == "hand_off" else str(choice.get("doctor") or "").strip()
    doctor_id = my_doctor_id or named
    if doctor_id and state.doctor(doctor_id) is None:
        doctor_id = ""

    if cid in ("pull_forward", "close_list"):
        if not doctor_id:
            return _unclear("Whose list do you mean? Name the doctor.")
        doc = state.doctor(doctor_id)
        if cid == "pull_forward":
            return _proposal(cid, f"Send {doc.name}'s next patient in",
                             doctor_id=doctor_id, doctor_name=doc.name)
        at = _clock(choice.get("from_time"))
        if not at:
            return _unclear("From what time should the list close?")
        return _proposal(cid, f"Close {doc.name}'s list from {at}",
                         doctor_id=doctor_id, doctor_name=doc.name, from_time=at)

    # extend and hand_off both act on one visit.
    if said and not pids:
        # A misheard name must never quietly become whoever is in the room.
        return _unclear(f"I could not match \"{said}\" to a patient. "
                        "Please say or type the name again.")
    if len(pids) > 1:
        return _unclear("More than one patient matches that name.")
    if cid == "hand_off" and not pids and not _THIS.search(sentence):
        return _unclear("Which patient do you mean?")
    if pids:
        visits = _today(state, pids[0], day)
        if my_doctor_id and visits and not any(
                a.doctor_id == my_doctor_id for a in visits):
            return _unclear("That patient is not on your list.")
        if my_doctor_id:
            visits = [a for a in visits if a.doctor_id == my_doctor_id]
        if not visits:
            return _unclear(f"{names.get(pids[0], 'That patient')} has no open "
                            "visit today.")
        if len(visits) > 1:
            return _unclear(f"{names.get(pids[0], 'That patient')} has more "
                            "than one visit today. Use the Schedule tab.")
        appt = visits[0]
    else:
        appt = _in_the_room(state, doctor_id, now, day) if doctor_id else None
        if appt is None:
            return _unclear("Which patient do you mean?")

    patient = _name(state, appt)
    source = state.doctor(appt.doctor_id)

    if cid == "extend":
        minutes = choice.get("minutes")
        if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) \
                or not 1 <= int(minutes) <= 120:
            return _unclear("How many more minutes?")
        minutes = int(minutes)
        return _proposal(cid, f"Give {patient} {minutes} more minutes",
                         appointment_id=appt.id, patient_name=patient,
                         doctor_id=appt.doctor_id,
                         doctor_name=source.name if source else "",
                         minutes=minutes)

    target = state.doctor(receiving_doctor(choice))
    if target is None:
        return _unclear("Which doctor should take this patient?")
    if target.id == appt.doctor_id:
        return _unclear(f"{patient} is already with {target.name}.")
    note = str(choice.get("note") or "").strip()
    for token, ids in mask.items():
        note = note.replace(token, names.get(ids[0], "") if len(ids) == 1 else "")
    return _proposal(cid, f"Hand {patient} to {target.name}",
                     appointment_id=appt.id, patient_name=patient,
                     doctor_id=appt.doctor_id,
                     doctor_name=source.name if source else "",
                     to_doctor_id=target.id, to_doctor_name=target.name,
                     note=note[:500])


def _proposal(action: str, summary: str, **fields: Any) -> Ask:
    return Ask(kind="proposal", via="model", title=summary,
               proposal={"action": action, "summary": summary, **fields})
