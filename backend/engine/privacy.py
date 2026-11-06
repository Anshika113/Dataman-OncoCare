"""What a message is allowed to say.

The app sends real SMS. A phone in an Indian OPD is often shared — an
attendant, a neighbour, a son who came along — so a message reading *"Your
chemotherapy with Dr. Amina Khan has been rescheduled"* can disclose a cancer
diagnosis to whoever happens to pick it up. Nobody ever agreed to that.

This module answers two questions at dispatch time:

1. **May we message this patient at all?** If not, the message is marked
   ``blocked`` rather than quietly dropped, so the desk can see it and phone
   instead.
2. **May this message name the treatment?** If not, the identifying terms are
   replaced with neutral ones. The terms are derived from the datastore — the
   actual drug names and this patient's own diagnosis — never guessed.

The point is *minimum necessary*: enough for the patient to act on, nothing
more. Pure module: no I/O, no clock.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

#: Words that identify the treatment regardless of which drug is named.
GENERIC_TERMS = (
    "chemotherapy", "chemo", "infusion", "oncology", "hematology",
    "haematology", "radiation", "cancer", "tumour", "tumor",
)

#: What each kind of disclosure becomes when consent is absent. Deliberately
#: article-free ("treatment", not "your treatment") so it reads correctly
#: after whatever word preceded the term: "Your treatment session has moved".
REPLACEMENT = "treatment"
PLACE_REPLACEMENT = "the day-care unit"

#: Room types whose name gives the treatment away by where it happens.
REVEALING_ROOM_TYPES = ("infusion_chair", "isolation")

#: Nothing shorter than this is ever treated as a disclosing term. A one- or
#: two-character term cannot identify a treatment on its own, and matching one
#: wrecks the message: the cancer stage "I" used to turn "Please arrive on
#: time" into "Please arrtreatmentve on ttreatmentme". Six of the thirty
#: seeded patients are stage I.
MIN_TERM_LEN = 3


def _place_terms(state) -> list[str]:
    """Rooms whose name would disclose the treatment. Read from the datastore
    so a renamed room is still covered."""
    out = []
    for room in state.rooms.values():
        if room.type.value in REVEALING_ROOM_TYPES and room.name:
            out.append(room.name)
    return sorted(set(out), key=len, reverse=True)


def _terms_for(state, patient) -> list[str]:
    """Everything in this message that would name the treatment."""
    terms: list[str] = [t for t in GENERIC_TERMS]
    for drug in state.drugs.values():
        if drug.name:
            terms.append(drug.name)
    if patient is not None and patient.diagnosis:
        terms.append(patient.diagnosis)
    if patient is not None and patient.stage:
        # "Stage IV" discloses; a bare "IV" or "I" does not, and as a term it
        # matches inside ordinary words. Only the phrase is a disclosure.
        terms.append(f"stage {patient.stage}")
    # longest first, so "infusion chair" is replaced before "infusion"
    return sorted({t.strip() for t in terms
                   if t and len(t.strip()) >= MIN_TERM_LEN},
                  key=len, reverse=True)


def _starts_sentence(text: str, at: int) -> bool:
    """Is position ``at`` the first word of a sentence?"""
    before = text[:at].rstrip()
    return not before or before[-1] in ".!?"


def _replace_all(body: str, terms: Iterable[str], with_: str) -> str:
    """Substitute each term, capitalising only where a sentence begins.

    The terms being replaced are drug names and proper nouns, so they are
    capitalised wherever they appear — copying that case would produce
    "Your Treatment session" mid-sentence.
    """
    def _swap(m):
        if _starts_sentence(m.string, m.start()):
            return with_[:1].upper() + with_[1:]
        return with_

    out = body
    for t in terms:
        if len(t) < MIN_TERM_LEN:
            continue
        # Whole words only. Without this every term is a substring match, so
        # "IV" rewrites "arrive" and a drug called "Ara-C" rewrites nothing
        # recognisable. \b does not fire next to punctuation in a term like
        # "Ara-C", so the edges are only guarded where the term's own edge is
        # a word character.
        left = r"\b" if t[:1].isalnum() else ""
        right = r"\b" if t[-1:].isalnum() else ""
        out = re.sub(left + re.escape(t) + right, _swap, out,
                     flags=re.IGNORECASE)
    return out


def _tidy(body: str) -> str:
    """Clean up what substitution leaves behind.

    Terms sit next to each other ("chemotherapy infusion") and sometimes
    after an article the source already supplied ("the Infusion 2"), so
    collapse the duplicates rather than sending a sentence that reads like a
    bug.
    """
    out = re.sub(r"\s{2,}", " ", body)
    out = re.sub(r"\b(treatment)(\s+treatment)+\b", r"\1", out,
                 flags=re.IGNORECASE)
    out = re.sub(r"\bthe\s+the\b", "the", out, flags=re.IGNORECASE)
    out = re.sub(r"\(\s*\)", "", out)
    return out.strip()


def may_send(patient) -> bool:
    """Has this patient agreed to be messaged at all?"""
    return patient is None or patient.consent_sms


def scrub(state, patient, body: str) -> tuple[str, bool]:
    """Return ``(body, changed)`` for what this patient agreed to receive.

    With consent to name the treatment, the message goes as written.
    """
    if patient is None or patient.consent_name_treatment:
        return body, False
    # places first: "Infusion 2" must become the unit, not "your treatment 2"
    cleaned = _replace_all(body, _place_terms(state), PLACE_REPLACEMENT)
    cleaned = _replace_all(cleaned, _terms_for(state, patient), REPLACEMENT)
    cleaned = _tidy(cleaned)
    return cleaned, cleaned != body


def describe(patient) -> dict:
    """The consent record, for the registration form and the message log."""
    if patient is None:
        return {"sms": True, "name_treatment": False, "attendant": True}
    return {
        "sms": bool(patient.consent_sms),
        "name_treatment": bool(patient.consent_name_treatment),
        "attendant": bool(patient.consent_attendant),
    }


def blocked_reason(patient) -> Optional[str]:
    """Why a message was held back, in words a nurse can act on."""
    if patient is None:
        return None
    if not patient.consent_sms:
        return (f"{patient.name} has not agreed to messages — "
                f"phone them instead")
    return None
