"""Reading a patient's reply without talking ourselves into a yes.

A yes books a waitlist slot, so it has to be earned. Reading only the first
word turned "ji nahi" and "ok but papa ko bukhar hai, aa nahi payenge" into a
confirmed patient. Now any refusal anywhere in the reply wins, and a yes only
counts when nothing else was said. Anything else stays ``unclear`` and goes to
a person, which is the safe direction to be wrong in.

Pure module: no I/O, no clock.
"""

from __future__ import annotations

import re

YES = {"y", "yes", "ok", "okay", "confirm", "coming", "1",
       # Hindi / Marathi, romanised
       "haan", "han", "ha", "ji", "hoy", "ho", "aa", "aaunga", "yenar",
       # Devanagari
       "हाँ", "हां", "हा", "जी", "ठीक", "आऊंगा", "आऊँगा", "येत",
       "हो", "होय"}

NO = {"n", "no", "cant", "can't", "cannot", "unable", "0",
      # Hindi / Marathi, romanised
      "nahi", "nahin", "nai", "naahi", "nako",
      # Devanagari
      "नहीं", "नही", "ना", "नाही", "नको", "रद्द"}

#: Words that add nothing to a yes. Anything outside this set might be the
#: thing the clinic needed to hear, so it makes the reply unclear.
FILLER = {"please", "sir", "madam", "maam", "doctor", "dr", "thanks", "thank",
          "you", "i", "i'll", "i'm", "am", "will", "be", "there", "sure",
          "today", "tomorrow", "main", "mai", "hoon", "hun", "raha", "rahi",
          "rahe", "hai", "hain", "kal", "aaj", "theek", "thik", "zaroor",
          "aaungi", "aayenge", "yeto", "yete", "yeil", "मैं", "है", "हूँ",
          "हूं", "आ", "रहा", "रही", "कल", "आज", "है।", "येतो", "येते"}

#: "No" that does not mean no.
NOT_A_REFUSAL = ("no problem", "no issue", "koi baat nahi", "koi dikkat nahi")


def read_reply(text: str) -> str:
    """``yes``, ``no`` or ``unclear``."""
    low = (text or "").strip().lower()
    if not low or "?" in low:
        return "unclear"
    for phrase in NOT_A_REFUSAL:
        low = low.replace(phrase, " ")
    # Not \W: Devanagari vowel signs are not word characters, and splitting on
    # them would turn "नहीं" into pieces nobody recognises.
    words = [w for w in re.split(r"[\s,.!;:()\-।/]+", low) if w]
    if any(w in NO for w in words):
        return "no"
    if any(w in YES for w in words) and all(w in YES or w in FILLER
                                            for w in words):
        return "yes"
    return "unclear"
