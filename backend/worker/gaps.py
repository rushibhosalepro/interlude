"""Find the silences worth describing. No AI, just arithmetic on word timings.

A gap is the space between the end of one word and the start of the next. If that
space is long enough, there is room to narrate something into it.
"""

import logging
import os

logger = logging.getLogger(__name__)

# below this there is no room to say anything useful
MIN_GAP_SECONDS = 1.5

# leave a little air either side so narration never collides with speech
EDGE_PADDING = 0.2

# Measured, not assumed. 268 words across 33 real renders of the ElevenLabs
# voice came out at 1.72 w/s, but those were full of quoted strings, which the
# voice reads slowly. The writer no longer emits quotation marks (they are
# silent anyway) and clean prose measures nearer 1.95, so 1.85 leaves a margin.
#
# The old 2.6 was 51% optimistic. Every first attempt overran, and each retry
# hacked the sentence shorter until it was a list of labels rather than
# something a listener could follow.
#
# Recalibrate if the voice changes. Acronyms and version numbers cost far more
# than their word count suggests: "GPT-5.6" is spoken as six syllables.
WORDS_PER_SECOND = float(os.getenv("WORDS_PER_SECOND", "1.85"))


def find_gaps(transcript: dict) -> dict:
    words = transcript.get("words") or []
    duration = transcript.get("duration") or 0.0
    gaps = []

    def add(start: float, end: float, kind: str):
        usable = end - start - (EDGE_PADDING * 2)
        if usable < MIN_GAP_SECONDS:
            return
        gaps.append(
            {
                "id": f"gap-{len(gaps) + 1:03d}",
                "start": round(start + EDGE_PADDING, 3),
                "end": round(end - EDGE_PADDING, 3),
                "duration": round(usable, 3),
                "midpoint": round((start + end) / 2, 3),
                "kind": kind,
                "wordBudget": int(usable * WORDS_PER_SECOND),
            }
        )

    if not words:
        # no speech at all, the whole thing is one long gap
        add(0.0, duration, "silent-video")
        return _summary(gaps, duration, transcript)

    # before the first word
    add(0.0, words[0]["start"], "opening")

    # between words
    for previous, following in zip(words, words[1:]):
        add(previous["end"], following["start"], "between")

    # after the last word
    if duration > words[-1]["end"]:
        add(words[-1]["end"], duration, "closing")

    return _summary(gaps, duration, transcript)


def _summary(gaps: list, duration: float, transcript: dict) -> dict:
    total = sum(g["duration"] for g in gaps)
    return {
        "gaps": gaps,
        "count": len(gaps),
        "totalGapSeconds": round(total, 3),
        "videoDuration": duration,
        # how much of the video is describable silence
        "gapRatio": round(total / duration, 4) if duration else 0.0,
        "settings": {
            "minGapSeconds": MIN_GAP_SECONDS,
            "edgePadding": EDGE_PADDING,
            "wordsPerSecond": WORDS_PER_SECOND,
        },
        "sourceWords": len(transcript.get("words") or []),
    }
