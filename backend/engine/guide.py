"""Help for somebody stuck in the interface, that knows who is asking.

The most common stuck-moment in this app is not "I cannot find the button".
It is "the button is not there" — and the answer is almost always that the
person's role does not have it. A nurse looking for *clear this flagged
result* will never find it, because accepting an out-of-protocol lab value is
a clinical decision and the backend gives it to doctors and admins only.

A help page cannot say that. It does not know who is reading. So every topic
here carries the roles its endpoint actually requires, taken from the
``require_role(...)`` on that route, and the answer changes depending on who
asked:

* **you can do this** — here are the steps;
* **you cannot** — here is who can, and why it sits with them.

The second answer is the one that saves a shift, and it is the reason this is
a feature rather than a FAQ.

The roles on each topic are the backend's, not the interface's. Where the two
ever disagree the backend wins — it is the thing that returns 403 — so
copying from it is the only way this stays true as the app changes.

Pure module: no I/O, no clock, no network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

ALL = ("admin", "nurse", "doctor", "coordinator")

ROLE_LABEL = {
    "admin": "an administrator",
    "nurse": "a nurse",
    "doctor": "a doctor",
    "coordinator": "a care coordinator",
}


@dataclass(frozen=True)
class Topic:
    id: str
    #: What the person is trying to do, in their words.
    title: str
    #: Which tab it lives on, as the sidebar labels it.
    where: str
    #: The roles the backend actually lets do this.
    roles: tuple[str, ...]
    steps: tuple[str, ...]
    #: Said only to somebody whose role cannot do it. Explains the rule rather
    #: than just refusing, because "ask a nurse" without a reason reads as a
    #: bug in the software.
    why_not: str = ""
    #: What to say to everybody — a caveat that applies whoever is asking.
    note: str = ""
    cues: tuple[str, ...] = ()


TOPICS: tuple[Topic, ...] = (
    Topic(
        id="checkin",
        title="Mark a patient as arrived",
        where="Front Desk",
        roles=ALL,
        steps=("Open Front Desk.",
               "Find them on the board — it is in arrival order, and people "
               "who have not arrived keep their slot order.",
               "Press Check in. They are given a token (A-01, A-02…) there "
               "and then."),
        note="Checking someone in is what stops the watchdog marking them "
             "absent when their slot passes.",
        cues=("check in", "checkin", "arrived", "mark arrival", "token",
              "check-in kaise", "aaya hua mark"),
    ),
    Topic(
        id="call_in",
        title="Call the next patient in",
        where="Front Desk",
        roles=ALL,
        steps=("Open Front Desk.",
               "The next-up panel names who should be called: ready, longest "
               "wait first.",
               "Press Call in. That timestamp is what the waiting figures are "
               "measured from, so it matters that it is pressed when they "
               "actually go in."),
        cues=("call in", "call next", "next patient", "send next",
              "bulana kaise", "andar bhejna"),
    ),
    Topic(
        id="book",
        title="Book an appointment",
        where="Schedule",
        roles=("admin", "nurse"),
        steps=("Open Schedule.",
               "Use the New booking panel at the top: visit type, patient, "
               "doctor, date, preferred start.",
               "It shows the length it will book and, where there is history, "
               "what these visits actually run at.",
               "Press Book."),
        why_not="Booking belongs to the desk. Doctors and coordinators can "
                "move and hand over patients who are already booked, but the "
                "list itself is the desk's to build.",
        cues=("book", "new booking", "add appointment", "booking kaise",
              "appointment kaise"),
    ),
    Topic(
        id="reschedule",
        title="Move an appointment",
        where="Schedule",
        roles=("admin", "nurse"),
        steps=("Open Schedule and click the appointment on the timeline.",
               "Pick a new time, or use the suggestions it offers.",
               "The patient is messaged automatically."),
        why_not="Moving a booking is the desk's. If you are a doctor and need "
                "to shift your own list, use Close my list at or Hand over "
                "instead — both are yours.",
        cues=("reschedule", "move appointment", "change time", "shift",
              "time badalna", "aage badhana"),
    ),
    Topic(
        id="walk_in",
        title="Fit in a walk-in",
        where="Schedule",
        roles=("admin", "nurse", "coordinator"),
        steps=("Open Schedule.",
               "In the walk-in panel choose the patient and how urgently they "
               "need to be seen.",
               "It shows every placement and what each one costs — who gets "
               "pushed and by how long — before anything is written.",
               "Pick one and confirm."),
        why_not="Placing a walk-in creates a booking, so it belongs to the "
                "desk and the coordinator. A doctor who needs somebody seen "
                "sooner can use Pull forward on their own list instead.",
        note="Nothing is booked until you choose. The options call writes "
             "nothing.",
        cues=("walk in", "walk-in", "fit in", "squeeze", "bina appointment",
              "walkin kaise"),
    ),
    Topic(
        id="gate",
        title="Hold a treatment because results are not back",
        where="Schedule",
        roles=ALL,
        steps=("Open Schedule and find the treatment.",
               "Press Hold for results.",
               "The chair goes back to the pool so somebody else can use it. "
               "The patient keeps their place and is never marked a no-show.",
               "When the result lands, press Proceed — find a slot."),
        note="This is the one that recovers chair time. Holding is not "
             "cancelling: the patient is still here.",
        cues=("hold", "held for results", "gate", "bloods not back",
              "report nahi aayi", "rok", "hold kaise"),
    ),
    Topic(
        id="clear_flag",
        title="Let a flagged result through",
        where="Schedule",
        roles=("admin", "doctor"),
        steps=("Open Schedule and find the held treatment.",
               "The flagged result is shown with the value as it was entered.",
               "Press Clear flag to accept it, then Proceed — find a slot."),
        why_not="Accepting an out-of-protocol result is a clinical decision, "
                "so it sits with the treating doctor. A nurse or coordinator "
                "can order the investigation and file the result, but not "
                "decide that treatment may go ahead on it.",
        note="The system never reads the value or decides anything from it. "
             "A human ticks the flag, and a doctor clears it.",
        cues=("clear flag", "flagged", "unflag", "accept result",
              "flag hatana", "result accept"),
    ),
    Topic(
        id="hand_off",
        title="Give a patient to a colleague",
        where="Schedule",
        roles=ALL,
        steps=("Open Schedule and click the patient.",
               "Choose the colleague under Hand over to.",
               "Write a note for them — what you would have said on the "
               "phone. It appears on their own list with your name on it.",
               "Press Hand over."),
        note="It refuses if the colleague is on leave, at their daily cap, or "
             "is not a listed cover for the specialty.",
        cues=("hand off", "handoff", "hand over", "give patient", "transfer",
              "doosre doctor ko dena"),
    ),
    Topic(
        id="close_list",
        title="Stop taking patients after a time",
        where="Schedule",
        roles=ALL,
        steps=("Open Schedule.",
               "Under Close my list at, set the time.",
               "Press Show who it affects. It shows the plan first: who stays "
               "with you, who moves to cover, who needs rebooking.",
               "Confirm only if the plan looks right."),
        note="A doctor may only close their own list.",
        cues=("close list", "close my list", "leaving early", "stop taking",
              "list band", "jaldi nikalna"),
    ),
    Topic(
        id="waitlist",
        title="Use a slot that has come free",
        where="Schedule",
        roles=("admin", "nurse", "coordinator"),
        steps=("Open Schedule.",
               "When something is cancelled the freed slot is shown with who "
               "could take it — people already in the building first, then "
               "those who can get here.",
               "Offer it to as many as you like. The first to accept gets it."),
        why_not="Offering a freed slot rebooks somebody, so it sits with the "
                "desk and the coordinator.",
        cues=("waitlist", "wait list", "free slot", "slot opened", "backfill",
              "khaali slot", "cancel hua slot"),
    ),
    Topic(
        id="follow_ups",
        title="See who has fallen off somebody's list",
        where="Follow-ups",
        roles=("admin", "nurse", "coordinator"),
        steps=("Open Follow-ups.",
               "Everyone nobody is currently looking after, worst first. Each "
               "row says why it is there and offers the one action that "
               "clears it."),
        why_not="This is the coordinator's console. Doctors see what concerns "
                "their own patients on My Day instead.",
        note="A missed visit that has already been rebooked never appears — "
             "otherwise the list becomes noise and stops being read.",
        cues=("follow up", "follow-ups", "chasing", "fell through",
              "peeche chhoot", "kisko phone"),
    ),
    Topic(
        id="consent",
        title="Record what a patient agreed we may send",
        where="Doctors & Patients",
        roles=("admin", "nurse"),
        steps=("Open Doctors & Patients and find the patient.",
               "Three separate consents: whether we may message at all, "
               "whether a message may name the treatment, and whether whoever "
               "answers the phone may be spoken to.",
               "Save."),
        why_not="Consent is captured at registration, so it sits with the "
                "desk. You can see what a patient agreed to on your own day "
                "list — it is only changing it that is the desk's.",
        note="Naming the treatment is off by default. A phone is often "
             "shared, and a cancer diagnosis is not something to disclose by "
             "leaving a box ticked.",
        cues=("consent", "permission", "sms consent", "messaging consent",
              "consent kaise"),
    ),
    Topic(
        id="working_week",
        title="Set when a doctor actually has clinics",
        where="Availability",
        roles=("admin", "doctor"),
        steps=("Open Availability.",
               "Add clinic sessions for the weekdays this doctor runs.",
               "Add any case-mix rules — for example, no more than four new "
               "cases in a morning."),
        why_not="A doctor may set their own working week; changing somebody "
                "else's is the administrator's.",
        note="Without a session template a doctor counts as available all "
             "day, which makes a full clinic look two-thirds empty.",
        cues=("working week", "sessions", "clinic hours", "availability",
              "case mix", "timing set"),
    ),
    Topic(
        id="undo",
        title="Undo something that moved",
        where="Schedule",
        roles=ALL,
        steps=("Open Schedule.",
               "What changed on your list shows every change with its reason "
               "and who made it.",
               "Press Undo on the one you want back."),
        note="It refuses if the patient has already been seen, or if a later "
             "change touched the same appointments — an undo that is not "
             "exact is worse than none.",
        cues=("undo", "revert", "take back", "wapas", "galti se"),
    ),
    Topic(
        id="patient_link",
        title="Give a patient the link to their own visit",
        where="Schedule",
        roles=("admin", "nurse", "coordinator"),
        steps=("Open Schedule and click the appointment.",
               "Copy the patient link and send it to them.",
               "It shows their token, where they are in the queue and roughly "
               "how long — and lets them confirm or decline."),
        why_not="Sending something to a patient is the desk's and the "
                "coordinator's work, so the link is theirs to hand out.",
        note="The link is the credential: no login. It shows one visit and "
             "nobody else's name, and names the treatment only where that "
             "consent was given.",
        cues=("patient link", "share link", "patient page", "link bhejna",
              "patient ko link"),
    ),
    Topic(
        id="import",
        title="Bring patients in from a spreadsheet",
        where="Doctors & Patients",
        roles=("admin",),
        steps=("Open Doctors & Patients.",
               "Paste or upload the CSV. A name column is required.",
               "Read the preview — it names every problem by line and writes "
               "nothing.",
               "Apply only if the preview is clean."),
        why_not="Importing writes to everybody's records at once, so it is "
                "the administrator's.",
        cues=("import", "csv", "spreadsheet", "upload patients", "excel se"),
    ),
    Topic(
        id="audit",
        title="See the security trail",
        where="Activity",
        roles=("admin",),
        steps=("Open Activity.",
               "The audit trail records sign-ins, failures and privileged "
               "actions with who, when and from where."),
        why_not="The security trail is the administrator's alone. The event "
                "stream and message log on the same tab are open to nurses "
                "and coordinators.",
        cues=("audit", "security log", "who logged in", "audit trail"),
    ),
    Topic(
        id="edge_cases",
        title="Simulate a disruption",
        where="Ops Console",
        roles=("admin", "nurse"),
        steps=("Open Ops Console.",
               "Pick the scenario: sick leave, a chemo overrun, a room "
               "breakdown, a no-show, or advancing the clock.",
               "The schedule recovers in front of you and every move is "
               "recorded with its reason."),
        why_not="These rewrite the day, so they are the desk's. Doctors and "
                "coordinators see the result, not the trigger.",
        note="The Ops Console only appears in a demo build.",
        cues=("ops console", "simulate", "sick leave", "breakdown", "overrun",
              "demo scenario", "disruption"),
    ),
)

TOPIC_BY_ID = {t.id: t for t in TOPICS}

#: Phrasings that mean "I am stuck", rather than "tell me a number".
HELP_CUES = (
    r"\bhow (do|can|should) i\b", r"\bhow to\b", r"\bwhere (is|do|can)\b",
    r"\bwhy can'?t i\b", r"\bi can'?t find\b", r"\bcannot find\b",
    r"\bnot (showing|there|visible|working)\b", r"\bbutton\b",
    r"\bhelp\b", r"\bstuck\b",
    r"\bkaise\b", r"\bkahan\b", r"\bkyun nahi\b", r"\bnahi dikh\b",
    r"\bmadad\b", r"\bkuthe\b", r"\bkasa\b",
)


def looks_like_help(question: str) -> bool:
    """Is this person asking how to do something, rather than asking a number?"""
    q = re.sub(r"\s+", " ", (question or "").strip().lower())
    return any(re.search(p, q) for p in HELP_CUES)


def _words(text: str) -> set[str]:
    return set(re.findall(r"[\w']+", (text or "").lower()))


def match_topic(question: str) -> Optional[Topic]:
    """The topic this question is about.

    Cues match on words rather than as a run of characters, because people do
    not put the words together: "where do I check someone in" is about
    checking in, but "check in" never appears in it. Every word of the cue
    has to be present, so "check in" matches and "check the room" does not.

    The most specific cue wins — more words first, then longer ones — and a
    single short word can never carry a match on its own.
    """
    qw = _words(question)
    if not qw:
        return None
    best, best_score = None, (0, 0)
    for topic in TOPICS:
        for cue in topic.cues:
            cw = _words(cue)
            if not cw or not cw <= qw:
                continue
            if len(cw) == 1 and len(next(iter(cw))) < 4:
                continue        # "in", "to", "csv" alone prove nothing
            score = (len(cw), len(cue))
            if score > best_score:
                best, best_score = topic, score
    return best


def who_can(topic: Topic) -> str:
    """"a nurse or an administrator", for telling somebody who to ask."""
    labels = [ROLE_LABEL[r] for r in ALL if r in topic.roles]
    if not labels:
        return "nobody"
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + " or " + labels[-1]


def answer(topic: Topic, role: str) -> dict[str, Any]:
    """The help, from the point of view of the person asking."""
    allowed = role in topic.roles
    return {
        "topic": topic.id,
        "title": topic.title,
        "where": topic.where,
        "allowed": allowed,
        "steps": list(topic.steps) if allowed else [],
        "who_can": who_can(topic),
        "why_not": "" if allowed else topic.why_not,
        "note": topic.note,
        "roles": list(topic.roles),
    }


def catalogue() -> list[dict[str, str]]:
    """Every topic, as a model would be shown them."""
    return [{"id": t.id, "about": f"{t.title} (on {t.where})"} for t in TOPICS]
