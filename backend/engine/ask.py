"""Turning a question into one of the views this app already has.

The console answers every one of these questions today; it just makes you
assemble the answer yourself — open Front Desk, read eighteen rows, sort them
by eye, then open Follow-ups to learn the longest wait is a patient held for
results rather than one who was forgotten. At a desk with somebody standing in
front of you, that is the expensive part.

So this module does one small thing: it decides **which existing view** a
question is asking for. It does not fetch the rows, does not count anything,
and does not phrase an answer. The API layer calls the same engine function
the screen calls, and the UI renders the rows exactly as any other panel does.

That split is the whole safety argument. The model — where one is configured —
chooses from a fixed catalogue of read-only views and may return nothing else.
It never sees a patient record, so it cannot summarise one; it never sees a
number, so it cannot invent one. The worst it can do is pick the wrong view,
which the reader notices immediately because the answer says which view it is.

Two more rules live here:

* **Clinical questions are refused before matching.** "Who is most urgent" is
  answered from the emergency queue, in the order of the severity staff
  recorded. "Who is sickest" is refused, because nobody recorded that and this
  app does not work it out: the assistant never judges a patient itself.
* **No view writes.** There is no booking, no cancelling, no clearing a flag.
  A question changes nothing, so there is nothing to confirm and nothing to
  undo.

Pure module: no I/O, no clock, no network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import guide
from typing import Any, Optional

#: Every view the assistant may choose. Adding one here is the only way to
#: widen what it can answer, which is deliberate: the catalogue is the
#: permission list.
@dataclass(frozen=True)
class View:
    id: str
    title: str
    #: What this view is for, in the words a model is given to choose by.
    purpose: str
    #: Phrases that pick it without a model. English first, then the Hindi and
    #: Marathi a desk actually types — the same three languages the reply
    #: parser already reads.
    cues: tuple[str, ...] = ()
    #: True when the answer is about the caller's own list and must be scoped.
    mine: bool = False


VIEWS: tuple[View, ...] = (
    View(
        id="waiting",
        title="Longest waits on the board",
        purpose="who has been waiting the longest, sorted by waiting time",
        cues=("waiting longest", "longest wait", "who is waiting",
              "waiting the most", "sabse zyada wait", "kitni der se",
              "kaun wait", "intezaar", "सबसे ज्यादा", "वेट",
              "ककति वेळ", "वाट पाहत"),
    ),
    View(
        id="not_called",
        title="Arrived, not yet called",
        purpose="patients who have checked in but have not been called in yet",
        cues=("not been called", "not called", "hasn't been called",
              "havent been called", "who is ready", "waiting room",
              "bulaya nahi", "abhi tak nahi bulaya", "बुलाया नहीं"),
    ),
    View(
        id="held",
        title="Held for results",
        purpose="treatments waiting on an investigation, and the chair each one freed",
        cues=("held for results", "waiting for results", "results",
              "bloods", "investigations", "lab", "labs",
              "report ka intezaar", "रिपोर्ट", "अहवाल"),
    ),
    View(
        id="free_rooms",
        title="Chairs and rooms free now",
        purpose="which infusion chairs or rooms are idle",
        cues=("chair free", "chairs free", "free chair", "room free",
              "rooms free", "idle", "khaali", "chair khaali", "खाली",
              "रिकामी"),
    ),
    View(
        id="running_late",
        title="Running late",
        purpose="which clinics are behind, by how much, and who is affected",
        cues=("running late", "am i late", "behind", "delay", "late chal",
              "der ho", "लेट", "उशीर"),
    ),
    View(
        id="my_day",
        title="Still to see today",
        purpose="the caller's own remaining list for today",
        cues=("my list", "my day", "still to see", "how many left",
              "kitne bache", "meri list", "मेरी लिस्ट", "माझी यादी"),
        mine=True,
    ),
    View(
        id="follow_ups",
        title="Nobody is looking after these",
        purpose="patients who fell through the cracks and need chasing",
        cues=("follow up", "follow-ups", "chase", "fell through",
              "nobody looking", "chhoot gaya", "पीछे छूट"),
    ),
    View(
        id="attention",
        title="Worth a look",
        purpose="the current bottlenecks and anything needing attention",
        cues=("anything i should", "worth a look", "what should i look",
              "anything wrong", "problems", "bottleneck", "kya dekhna",
              "कुछ देखना", "काही बघायचं"),
    ),
    View(
        id="emergency_queue",
        title="Emergency queue, by the severity staff recorded",
        purpose="the emergency queue, in the order of the severity staff "
                "recorded, for who is most urgent or who goes first",
        cues=("most urgent", "urgent", "emergency", "emergencies", "priority",
              "prioritise", "prioritize", "pehle kaun", "इमरजेंसी", "आपातकाल",
              "सबसे पहले"),
    ),
    View(
        id="patient",
        title="One patient",
        purpose="the status of a single named patient today",
        cues=(),            # chosen by name match, not by phrase
    ),
)

VIEW_BY_ID = {v.id: v for v in VIEWS}


# --------------------------------------------------------------------------- #
# The line this app does not cross
# --------------------------------------------------------------------------- #
#: Questions that ask the system to judge a patient rather than look one up.
#: Matched before anything else, so "who is the sickest person waiting" is
#: refused even though it names a view.
#:
#: A word like "counts" only counts alongside a judgement: "counts 11 baje aaye
#: the" is a doctor's hand-off note, and refusing it would refuse the doctor.
_LABS = r"(counts?|anc|neutrophil|platelet|h[ae]emoglobin|creatinine|bilirubin)"
CLINICAL = (
    (r"\b(most|more|least) (serious|critical|severe|unwell|sick)\b",
     "how ill a patient is"),
    (r"\b(sickest|worst|most ill)\w*\b", "how ill a patient is"),
    (r"\bworr(y|ied)\b", "how ill a patient is"),
    (r"\b(sabse|sarvat|zyada|jyada|kitna|kitni|kaun) (\w+ )?(bimar|beemar|serious|gambhir|aajari)\b",
     "how ill a patient is"),
    (r"बीमार|गंभीर|आजारी|तबीयत|तब्येत", "how ill a patient is"),
    (r"\b(well enough|fit for|safe for)\b",
     "whether it is safe to treat someone"),
    (r"\b(chemo|treatment|dawai|dawa|ilaj|ilaaj) (\w+ )?(de|dena|de sakte|rok|roko|band|skip)\w*\b",
     "a treatment decision"),
    (r"(कीमो|केमो|दवा|इलाज|उपचार).{0,12}(दे|रोक|बंद|द्या|थांब)",
     "a treatment decision"),
    (r"रिपोर्ट.{0,12}(मतलब|ठीक|कैसी|नॉर्मल|अर्थ)|अहवाल.{0,12}(अर्थ|ठीक|कसा)",
     "the meaning of a test result"),
    (r"\b(report|result)s? (ka matlab|kaisi|kaisa|theek|thik|normal)\b",
     "the meaning of a test result"),
    (r"\b(safe|ok|okay|fit) to (treat|proceed|give|go ahead|continue)\b",
     "whether it is safe to treat someone"),
    (r"\b(should|shall|can) (we|i) (skip|stop|delay|reduce|give|start|treat)\b",
     "a treatment decision"),
    (r"\b" + _LABS + r"\b.{0,25}\b(ok|okay|fine|good|low|high|normal|safe|bad|"
     r"theek|thik|kam|kaise|kaisa|kaisi)\b", "the meaning of a test result"),
    (r"\b(what|how|kya|kitn\w*)\b.{0,20}\b" + _LABS + r"\b",
     "the meaning of a test result"),
    (r"\b(diagnos|prognos|stage her|stage him|how (ill|sick|bad))\w*\b",
     "a clinical assessment"),
    (r"\b(interpret|what do(es)? (the|her|his) (result|report|scan))\b",
     "the meaning of a test result"),
)

#: Things it cannot do yet because this version only looks.
WRITES = (
    # "schedule" is a noun far more often than a verb here — "schedule slip ho
    # gaya kya" asks about the day, it does not ask to book — so it is not a
    # write cue. "book" and "rebook" are unambiguous.
    (r"\b(book|rebook|re-book)\b", "book"),
    (r"\b(cancel|cancell)\w*\b", "cancel"),
    (r"\b(reschedul|move|shift|postpone|push)\w*\b", "move"),
    (r"\b(hand ?off|hand over|handover|transfer)\b", "hand over"),
    (r"\b(clear|unflag|release) (the )?flag\b", "clear a flag"),
    (r"\b(close|band kar) (my )?list\b", "close a list"),
)


@dataclass
class Ask:
    """What a question resolved to."""

    kind: str                       # view | help | refused | cannot_write | unclear | proposal
    view: str = ""
    topic: str = ""                 # when kind == "help"
    title: str = ""
    patient_query: str = ""
    reason: str = ""
    #: How the choice was made, so the UI can be honest about it.
    via: str = "local"              # local | model
    suggestions: list[str] = field(default_factory=list)
    #: A change for a person to confirm. See :mod:`engine.propose`.
    proposal: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "view": self.view,
            "topic": self.topic,
            "title": self.title,
            "patient_query": self.patient_query,
            "reason": self.reason,
            "via": self.via,
            "suggestions": list(self.suggestions),
            "proposal": self.proposal,
        }


SUGGESTIONS = [
    "who is waiting longest",
    "who hasn't been called yet",
    "any chairs free",
    "am I running late",
    "anything I should look at",
]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def clinical_reason(question: str) -> Optional[str]:
    """What this question asks the system to judge, if anything."""
    q = _norm(question)
    for pattern, what in CLINICAL:
        if re.search(pattern, q):
            return what
    return None


def write_verb(question: str) -> Optional[str]:
    """The change this question is asking for, if any."""
    q = _norm(question)
    for pattern, verb in WRITES:
        if re.search(pattern, q):
            return verb
    return None


def match_view(question: str) -> Optional[View]:
    """Pick a view from the phrase alone, with no model and no network.

    This is not a fallback bolted on for offline use — it is how the feature
    behaves when nobody has configured a language model, and it has to be good
    enough that the app is still useful then. The longest cue wins, so
    "who is waiting longest" beats a stray "wait".
    """
    q = _norm(question)
    best: Optional[View] = None
    best_len = 0
    for view in VIEWS:
        for cue in view.cues:
            if cue in q and len(cue) > best_len:
                best, best_len = view, len(cue)
    return best


def find_patient(question: str, names: dict[str, str]) -> list[str]:
    """Patient ids whose name appears in the question.

    ``names`` is ``{id: name}``. Matching is on whole words so that a patient
    called "Ara" cannot be found inside "are", and both a first name and a
    full name work because the desk uses whichever is shorter.
    """
    q = _norm(question)
    hits: list[str] = []
    for pid, name in names.items():
        for part in {_norm(name), _norm(name).split(" ")[0]}:
            if len(part) < 3:
                continue
            if re.search(r"\b" + re.escape(part) + r"\b", q):
                if pid not in hits:
                    hits.append(pid)
                break
    return hits


def resolve(question: str, names: Optional[dict[str, str]] = None) -> Ask:
    """Decide what this question is asking for, locally.

    Order matters. A clinical question is refused even when it also names a
    view ("who is the most urgent person waiting"), because the refusal is the
    point and the view would answer the wrong half of it.
    """
    if not _norm(question):
        return Ask(kind="unclear", reason="ask me something about today",
                   suggestions=SUGGESTIONS)

    what = clinical_reason(question)
    if what:
        return Ask(
            kind="refused",
            reason=f"I do not answer questions about {what}. "
                   "That is the doctor's call.",
            suggestions=SUGGESTIONS)

    verb = write_verb(question)
    if verb:
        # It cannot do it, but it knows where the person can, which is more
        # use than a refusal on its own.
        topic = guide.match_topic(question)
        return Ask(
            kind="cannot_write",
            topic=topic.id if topic else "",
            reason=f"I can only look things up — I cannot {verb} anything."
                   + (f" Here is how to do it yourself." if topic else ""),
            suggestions=SUGGESTIONS)

    # "How do I hold a treatment" is a question about the interface, and
    # "whose results are we waiting for" is a question about today. They share
    # words, so the shape of the sentence decides: someone asking *how* is
    # stuck, and a list of patients is not what they want.
    topic = guide.match_topic(question)
    if topic is not None and guide.looks_like_help(question):
        return Ask(kind="help", topic=topic.id, title=topic.title)

    view = match_view(question)
    if view is not None:
        return Ask(kind="view", view=view.id, title=view.title)

    # No view matched, but they are clearly stuck and named something we
    # know about — answer the help rather than shrug.
    if topic is not None:
        return Ask(kind="help", topic=topic.id, title=topic.title)

    hits = find_patient(question, names or {})
    if len(hits) == 1:
        return Ask(kind="view", view="patient", title=VIEW_BY_ID["patient"].title,
                   patient_query=hits[0])
    if len(hits) > 1:
        return Ask(kind="unclear",
                   reason="More than one patient matches that name.",
                   suggestions=SUGGESTIONS)

    return Ask(kind="unclear",
               reason="I did not understand that one.",
               suggestions=SUGGESTIONS)


def catalogue() -> list[dict[str, str]]:
    """The views, as a model would be shown them.

    This is the entire surface a model is offered. It cannot name an endpoint
    that is not here, so a clinical question matches nothing and comes back
    unresolved — the same path as a typo.
    """
    return [{"id": v.id, "purpose": v.purpose} for v in VIEWS]


def from_model(choice: Any, names: Optional[dict[str, str]] = None) -> Ask:
    """Take a model's answer and keep it inside the catalogue.

    Anything that is not a known view id is discarded rather than trusted —
    a model that invents ``"cancel_appointment"`` gets the same treatment as
    one that returns nonsense.
    """
    if not isinstance(choice, dict):
        return Ask(kind="unclear", reason="I did not understand that one.",
                   suggestions=SUGGESTIONS)
    vid = str(choice.get("view") or "").strip()
    view = VIEW_BY_ID.get(vid)
    if view is None:
        return Ask(kind="unclear", reason="I did not understand that one.",
                   suggestions=SUGGESTIONS)
    pid = ""
    if view.id == "patient":
        raw = str(choice.get("patient") or "")
        hits = find_patient(raw, names or {})
        if len(hits) != 1:
            return Ask(kind="unclear",
                       reason="I could not tell which patient you meant.",
                       suggestions=SUGGESTIONS)
        pid = hits[0]
    return Ask(kind="view", view=view.id, title=view.title,
               patient_query=pid, via="model")
