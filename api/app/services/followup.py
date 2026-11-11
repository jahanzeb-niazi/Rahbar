"""Follow-up detection (section 3.2 step 2: skip the cache for follow-up questions).

The API is single-turn: the request carries only the question. A follow-up is a question
whose meaning depends on an earlier turn ("what about the MS programme?", "is it the same
for summer?"). Its answer cannot be reused for someone else asking the same words, so it
is never served from, or written to, the cache.
"""

from __future__ import annotations

import re

_FOLLOWUP = re.compile(
    r"^\s*(and|but|also|so|then|what about|how about|what if|same for|is that|is it|"
    r"does that|does it|do they|are they|was it|were they|it|that|this|those|they|them)\b"
    r"|\b(the same|as above|you said|your (last|previous) answer|mentioned (above|before)|"
    r"that one|this one)\b",
    re.I,
)


def is_followup(question: str) -> bool:
    return bool(_FOLLOWUP.search(question))
