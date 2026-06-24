"""
Typing animator.

Builds a per-character timeline that decides when each character of the
source code appears on screen.

Humanisation features
--------------------
  * Per-character jitter — base delay × uniform(0.55, 1.45)
  * Character-class delays — newlines, spaces, punctuation, brackets,
    digits, and upper-case letters each have their own timing profile.
  * Burst typing — real typing comes in rolls of 2-6 fast keystrokes
    separated by short micro-pauses. We model this explicitly so the
    cadence sounds natural instead of metronomic.
  * Thinking pauses — occasional 0.4-1.6s pauses that simulate the
    typist glancing at the source / deciding what comes next. These
    are more likely at structural boundaries (after `:`, `(`, `=`,
    line ends, blank lines, and at the start of common keywords).
  * Context-aware typos — instead of random a-z noise, typos are now
    drawn from the keys physically adjacent on a QWERTY keyboard, with
    rare doubled-letter and adjacent-transposition typos for variety.
    Each typo is followed by a realistic "notice + backspace" delay.
  * Hand fatigue — a slight gradual slowdown over the course of long
    clips (configurable, off by default).
  * Handedness bias — typing the same key twice in a row is faster
    than alternating hands, and alternation is faster than same-hand
    different-key sequences (approximated via row/column distance).
  * Speed ramp — optional Ease In / Ease Out / Ease In-Out cosine
    curve for a cinematic slow-start / slow-end.

Statistics
----------
``stats_at(t)`` returns a snapshot of typing metrics at time ``t``:
chars typed, keystrokes (including typos + backspaces), effective WPM,
accuracy %, and elapsed time. These are consumed by the renderer's
optional statistics overlay and can also be written to a sidecar
``.srt`` subtitle file by the exporter.
"""

from __future__ import annotations

import bisect
import logging
import math
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


# A timeline event: (timestamp, display_index, character)
Event = Tuple[float, int, str]


# QWERTY keyboard layout, used for context-aware typo generation and
# handedness-distance approximation. Each row is a string; we look up
# a char's (row, col) to compute physical distance.
_QWERTY_ROWS = (
    "`1234567890-=",
    "qwertyuiop[]\\",
    "asdfghjkl;'",
    "zxcvbnm,./",
)
# Precomputed char → (row, col) lookup.
_QWERTY_POS: Dict[str, Tuple[int, int]] = {}
for _r, _row in enumerate(_QWERTY_ROWS):
    for _c, _ch in enumerate(_row):
        _QWERTY_POS[_ch] = (_r, _c)
# Add uppercase letters as neighbours of their lowercase equivalents.
for _ch in list("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    _QWERTY_POS[_ch] = _QWERTY_POS[_ch.lower()]
# Map shifted symbols to their unshifted key positions for
# realistic typo generation and distance calculations.
_SHIFTED_MAP = {
    "~": "`", "!": "1", "@": "2", "#": "3", "$": "4", "%": "5",
    "^": "6", "&": "7", "*": "8", "(": "9", ")": "0", "_": "-",
    "+": "=", "{": "[", "}": "]", "|": "\\", ":": ";", '"': "'",
    "<": ",", ">": ".", "?": "/",
}
for _shifted, _unshifted in _SHIFTED_MAP.items():
    _pos = _QWERTY_POS.get(_unshifted)
    if _pos is not None:
        _QWERTY_POS[_shifted] = _pos


def _key_distance(a: str, b: str) -> float:
    """Approximate physical distance between two keys on a QWERTY layout.

    Returns a large number for keys we don't know about so they're
    treated as "far apart" (slow).
    """
    pa = _QWERTY_POS.get(a.lower())
    pb = _QWERTY_POS.get(b.lower())
    if pa is None or pb is None:
        return 10.0
    return math.hypot(pa[0] - pb[0], pa[1] - pb[1])


@dataclass
class TypingStats:
    """Snapshot of typing metrics at a single point in time."""
    elapsed: float           # seconds since start (excluding start_pause)
    chars_typed: int         # characters currently visible (post-backspace)
    keystrokes: int          # total key presses (chars + typos + backspaces)
    correct_keystrokes: int  # keystrokes that contributed to final text
    wpm: float               # effective words-per-minute at this instant
    accuracy: float          # correct_keystrokes / keystrokes, in [0, 1]


class TypingAnimator:
    """Pre-compute a typing timeline and answer "how many chars are visible at time t"."""

    # Keywords whose first character gets a brief "thinking" delay.
    PAUSE_KEYWORDS = (
        "def ", "class ", "import ", "from ", "return ", "if ", "for ",
        "while ", "with ", "try:", "except ", "function ", "const ", "let ",
        "var ", "public ", "private ", "func ", "fn ", "package ",
    )

    # PERF (v1.6): pre-compute a set of first characters that appear at
    # the start of any PAUSE_KEYWORD.  Used as a fast-reject filter in
    # _char_delay so we skip the O(n) keyword scan entirely when the
    # current character can't possibly start a keyword.
    _KW_FIRST_CHARS: frozenset = frozenset(kw[0] for kw in PAUSE_KEYWORDS)

    # Characters that end a "structural unit" and thus invite a small
    # thinking pause. Mapped to (delay_min, delay_max, probability).
    STRUCTURAL_PAUSES: Dict[str, Tuple[float, float, float]] = {
        "\n": (0.18, 0.55, 0.55),   # line end
        ":":  (0.15, 0.45, 0.45),   # block opener
        "=":  (0.08, 0.25, 0.25),   # assignment
        "(":  (0.06, 0.18, 0.20),   # call opener
    }

    # Sentence-final punctuation gets a longer pause than mid-sentence.
    SENTENCE_FINAL = {".", "!", "?"}

    def __init__(
        self,
        code: str,
        base_wpm: int = 120,
        humanize: bool = True,
        typo_rate: float = 0.015,
        start_pause: float = 0.5,
        end_pause: float = 1.5,
        seed: Optional[int] = None,
        speed_ramp: str = "None",
        ramp_strength: float = 0.5,
        burst_typing: bool = True,
        thinking_pauses: bool = True,
        fatigue: float = 0.0,
    ) -> None:
        """
        Parameters
        ----------
        speed_ramp : {"None", "Ease In", "Ease Out", "Ease In-Out"}
            Optionally slow the typing rate at the start and/or end of
            the clip for a cinematic effect.
        ramp_strength : float in [0, 1]
            How strongly the ramp affects timing. 0 = no effect, 1 =
            typing is 3x slower at the ramped endpoints.
        burst_typing : bool
            If True (default), typing comes in rolls of 2-6 fast
            keystrokes separated by short micro-pauses, matching the
            rhythm of real typing.
        thinking_pauses : bool
            If True (default), occasionally insert a 0.4-1.6s "thinking"
            pause at structural boundaries.
        fatigue : float in [0, 1]
            0 = no fatigue; 1 = typing is ~40% slower by the end of a
            long clip. Useful for long-form (10+ minute) typing videos.
        """
        self.logger = logging.getLogger("TypingAnimator")
        self.code = code
        self.base_wpm = base_wpm
        self.humanize = humanize
        self.typo_rate = typo_rate
        self.start_pause = start_pause
        self.end_pause = end_pause
        self.speed_ramp = speed_ramp if speed_ramp in (
            "None", "Ease In", "Ease Out", "Ease In-Out"
        ) else "None"
        self.ramp_strength = max(0.0, min(1.0, ramp_strength))
        self.burst_typing = burst_typing and humanize
        self.thinking_pauses = thinking_pauses and humanize
        self.fatigue = max(0.0, min(1.0, fatigue))

        cps = (base_wpm * 5) / 60  # 1 word = 5 chars (industry standard)
        self.base_delay = 1.0 / cps

        # Per-event bookkeeping for stats: counts of (correct, total) up
        # to and including each timeline event. Precomputed once so
        # stats_at() is O(log n).
        self._keystrokes_prefix: List[int] = []
        self._correct_prefix: List[int] = []
        self._resolved_prefix: List[int] = []
        self._typo_indices: set[int] = set()

        self.display_chars: List[str] = []
        self.timeline: List[Event] = self._build_timeline(seed)
        self._timestamps: List[float] = [ts for ts, _, _ in self.timeline]

        self._build_stats_prefix()

    # ── timeline construction ─────────────────────────────────────────
    def _build_timeline(self, seed: Optional[int]) -> List[Event]:
        rng = random.Random(seed)
        t = 0.0
        events: List[Event] = []
        n_chars = len(self.code)

        # Burst-typing state: we maintain a "roll" counter that
        # decrements with each keystroke; when it hits zero we insert a
        # micro-pause and reset it to a fresh random roll length.
        roll_remaining = 0  # first character always starts a fresh roll

        for i, ch in enumerate(self.code):
            # ── Maybe insert a typo + backspace pair ──────────────────
            if (
                self.humanize
                and self.typo_rate > 0
                and ch not in ("\n", " ", "\t")
                and rng.random() < self.typo_rate
            ):
                typo_char = self._make_typo(ch, rng)
                self.display_chars.append(typo_char)
                events.append((t, len(self.display_chars) - 1, typo_char))
                self._typo_indices.add(len(events) - 1)
                # Typo keystroke itself is fast (typist doesn't know yet).
                t += self.base_delay * rng.uniform(0.4, 0.9) * self._ramp_factor(i, n_chars)

                # "Notice + backspace" delay — typist realises the typo,
                # pauses briefly, then backspaces.
                notice = rng.uniform(0.12, 0.35)
                t += notice * self._ramp_factor(i, n_chars)

                self.display_chars.append("\b")
                events.append((t, len(self.display_chars) - 1, "\b"))
                # Backspace is typically faster than a normal keystroke.
                t += self.base_delay * rng.uniform(0.3, 0.6) * self._ramp_factor(i, n_chars)

            # ── The real character ────────────────────────────────────
            self.display_chars.append(ch)
            events.append((t, len(self.display_chars) - 1, ch))

            d = self._char_delay(ch, i, rng)
            d *= self._ramp_factor(i, n_chars)
            d *= self._fatigue_factor(i, n_chars)

            # ── Burst-typing micro-pauses ─────────────────────────────
            if self.burst_typing:
                roll_remaining -= 1
                if roll_remaining <= 0:
                    # End of a roll: insert a short gap, then start a
                    # new roll. Don't add this on top of a structural
                    # pause (we'd double-count).
                    if not (self.thinking_pauses and self._is_structural(ch, i)):
                        d += rng.uniform(0.06, 0.18)
                    roll_remaining = self._new_roll(rng)
                else:
                    # Mid-roll: keystrokes are noticeably faster than
                    # the base delay, like a real typing burst.
                    d *= rng.uniform(0.55, 0.85)

            # ── Thinking pauses at structural boundaries ──────────────
            if self.thinking_pauses:
                d += self._structural_pause(ch, i, rng)

            # ── Random "lost my place" pause (rare) ───────────────────
            if self.humanize and rng.random() < 0.012:
                d += rng.uniform(0.4, 1.6)

            t += max(d, 0.012)

        # Shift everything past the start pause.
        # PERF (v1.7): add start_pause in-place instead of creating a
        # new list of tuples via list comprehension.  Avoids allocating
        # a second full-size list (saved ~100 KB for a typical 5000-
        # event timeline).
        sp = self.start_pause
        for i in range(len(events)):
            ts, idx, ch = events[i]
            events[i] = (ts + sp, idx, ch)
        return events

    @staticmethod
    def _new_roll(rng: random.Random) -> int:
        """Return a fresh burst-typing roll length (2-6 keystrokes)."""
        return rng.randint(2, 6)

    def _fatigue_factor(self, i: int, n: int) -> float:
        """Return a multiplier in [1, 1 + 0.4*fatigue] that grows over time."""
        if self.fatigue <= 0 or n == 0:
            return 1.0
        progress = i / max(1, n - 1)
        # Linear ramp from 1.0 at start to 1 + 0.4*fatigue at end.
        return 1.0 + 0.4 * self.fatigue * progress

    def _ramp_factor(self, i: int, n: int) -> float:
        """Return a multiplier in [1, 1 + 2*ramp_strength] for the ramp.

        At the endpoints (i near 0 or n) typing is slowest; in the
        middle of the clip typing is at full speed.
        """
        if self.speed_ramp == "None" or self.ramp_strength <= 0 or n == 0:
            return 1.0
        progress = i / max(1, n - 1)  # 0 at start, 1 at end
        if self.speed_ramp == "Ease In":
            # Slow at start, fast at end. Eased with a cosine.
            factor = 1.0 + math.cos(progress * math.pi / 2) * 2.0 * self.ramp_strength
        elif self.speed_ramp == "Ease Out":
            # Fast at start, slow at end.
            factor = 1.0 + math.sin(progress * math.pi / 2) * 2.0 * self.ramp_strength
        else:  # Ease In-Out
            # Slow at both ends, fast in the middle.
            factor = 1.0 + (math.cos(progress * 2.0 * math.pi) + 1.0) * self.ramp_strength
        return max(0.2, factor)

    def _char_delay(self, ch: str, i: int, rng: random.Random) -> float:
        """Base per-character delay, before burst / structural adjustments."""
        d = self.base_delay
        if self.humanize:
            d *= rng.uniform(0.55, 1.45)

            if ch == "\n":
                # Newline: longer than the old version, with high variance
                # to model "end of thought" vs "just wrapping a line".
                d *= rng.uniform(2.2, 5.5)
            elif ch == " ":
                d *= rng.uniform(0.7, 1.4)
            elif ch == "\t":
                # Tab is a deliberate formatting key — slightly slower.
                d *= rng.uniform(1.1, 1.8)
            elif ch in self.SENTENCE_FINAL:
                # Sentence-final punctuation (. ! ?) gets the longest
                # non-newline pause. Must be checked before the general
                # "., " branch so that '.' gets the heavier delay here.
                d *= rng.uniform(2.2, 4.0)
            elif ch in ",;":  # comma and semicolon (period handled above)
                d *= rng.uniform(1.6, 2.8)
            elif ch == ":":
                d *= rng.uniform(1.4, 2.4)
            elif ch in "([{":
                d *= rng.uniform(1.2, 2.0)
            elif ch in ")]}":
                d *= rng.uniform(0.9, 1.6)
            elif ch in "+-*/%=<>!&|^~?":
                # Operators are deliberate; small extra pause.
                d *= rng.uniform(1.05, 1.5)
            elif ch in "'\"`":
                # Quote characters get a small extra pause.
                d *= rng.uniform(1.1, 1.7)
            elif ch.isdigit():
                # Digits are slightly slower than letters on average
                # (they live on the top row, harder to reach).
                d *= rng.uniform(0.95, 1.3)
            elif ch.isupper():
                # Upper-case requires Shift — model the extra coordination.
                d *= rng.uniform(1.05, 1.45)

            # ── Handedness / distance modelling ──────────────────────
            # If the previous char exists, scale by physical distance:
            # same key = very fast, adjacent key = fast, far key = slow.
            if i >= 1:
                prev = self.code[i - 1]
                dist = _key_distance(ch, prev)
                if dist < 0.5:
                    # Same key repeated (e.g. "ll", "11")
                    d *= 0.65
                elif dist < 2.0:
                    # Adjacent key — fast roll.
                    d *= rng.uniform(0.7, 0.95)
                elif dist > 4.0:
                    # Big hand reposition — slight slowdown.
                    d *= rng.uniform(1.05, 1.3)

            # Triple-repeat speed-up (e.g. "   " or "===")
            if i >= 2 and ch == self.code[i - 1] == self.code[i - 2]:
                d *= 0.65

            # Slow down at the start of common keywords.
            # PERF (v1.6): fast-reject via first-char set before the
            # O(n) substring comparison loop.
            if ch in self._KW_FIRST_CHARS:
                # PERF (v1.7): use startswith() instead of substring
                # slicing + comparison.  str.startswith avoids creating
                # a temporary slice object on each comparison.
                for kw in self.PAUSE_KEYWORDS:
                    if self.code.startswith(kw, i):
                        d *= 1.6
                        break
        return d

    # ── context-aware typo generation ─────────────────────────────────
    @staticmethod
    def _make_typo(ch: str, rng: random.Random) -> str:
        """Generate a realistic typo for ``ch``.

        Distribution:
          70% — an adjacent key on the QWERTY layout
          15% — a doubled-letter typo (e.g. "l" → "ll", then backspace)
          10% — a transposition-style near-miss (a key from the same row)
           5% — a random a-z fallback (rare, catches edge cases)
        """
        lower = ch.lower()
        pos = _QWERTY_POS.get(lower)
        roll = rng.random()

        if pos is not None and roll < 0.70:
            # Adjacent-key typo: pick a neighbour within ±1 row/col.
            r, c = pos
            candidates: List[str] = []
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < len(_QWERTY_ROWS):
                        row = _QWERTY_ROWS[nr]
                        if 0 <= nc < len(row):
                            candidates.append(row[nc])
            if candidates:
                typo = rng.choice(candidates)
                return typo.upper() if ch.isupper() else typo

        if roll < 0.85:
            # Doubled-letter typo.
            return ch

        if pos is not None and roll < 0.95:
            # Same-row near-miss.
            r, c = pos
            row = _QWERTY_ROWS[r]
            if len(row) > 1:
                idx = c
                # Pick a different char from the same row.
                other = (idx + rng.choice((-1, 1))) % len(row)
                typo = row[other]
                return typo.upper() if ch.isupper() else typo

        # Random fallback.
        typo = rng.choice("abcdefghijklmnopqrstuvwxyz")
        return typo.upper() if ch.isupper() else typo

    # ── structural-boundary thinking pauses ───────────────────────────
    def _is_structural(self, ch: str, i: int) -> bool:
        """Return True if this position is a structural boundary.

        NOTE (v1.5.1): the previous implementation had a dead "blank line"
        branch — ``if ch == "\n" and ...`` — that was unreachable because
        ``"\\n"`` is already a key in :pyattr:`STRUCTURAL_PAUSES`, so the
        first check always returned True first. The dead branch has been
        removed; the blank-line bonus is still applied inside
        :meth:`_structural_pause`.
        """
        return ch in self.STRUCTURAL_PAUSES

    def _structural_pause(self, ch: str, i: int, rng: random.Random) -> float:
        """Return an extra delay for a structural boundary, or 0."""
        if ch in self.STRUCTURAL_PAUSES:
            lo, hi, prob = self.STRUCTURAL_PAUSES[ch]
            if rng.random() < prob:
                base = rng.uniform(lo, hi)
                # Blank-line bonus: extra long "paragraph break" pause.
                if ch == "\n" and i >= 1 and self.code[i - 1] == "\n":
                    base *= rng.uniform(1.8, 3.0)
                return base
        return 0.0

    # ── stats precomputation ──────────────────────────────────────────
    def _build_stats_prefix(self) -> None:
        """Precompute prefix sums of (keystrokes, correct_keystrokes).

        For each timeline event we record the running totals so that
        stats_at(t) can answer in O(log n) via bisect.
        """
        keystrokes = 0
        correct = 0
        self._keystrokes_prefix = []
        self._correct_prefix = []
        self._resolved_prefix = []
        # Track the resolved-text cursor so we know which keystrokes
        # contributed to the final visible text.
        resolved_len = 0
        for event_idx, (_, _, ch) in enumerate(self.timeline):
            keystrokes += 1
            if ch == "\b":
                if resolved_len > 0:
                    resolved_len -= 1
            elif event_idx not in self._typo_indices:
                correct += 1
                resolved_len += 1
            else:
                # Typo character — not a correct keystroke, but still
                # advances the visible cursor (will be backspaced later).
                resolved_len += 1
            self._keystrokes_prefix.append(keystrokes)
            self._correct_prefix.append(correct)
            self._resolved_prefix.append(resolved_len)

    # ── queries ───────────────────────────────────────────────────────
    def duration(self) -> float:
        if not self.timeline:
            return self.start_pause + self.end_pause
        return self.timeline[-1][0] + self.end_pause

    def visible_at(self, t: float) -> int:
        """Number of display chars visible at time ``t``."""
        if t < self.start_pause:
            return 0
        idx = bisect.bisect_right(self._timestamps, t)
        if idx == 0:
            return 0
        return self.timeline[idx - 1][1] + 1

    def char_timestamps(self) -> List[Tuple[float, str]]:
        """Return non-backspace events for audio alignment."""
        return [(ts, ch) for ts, _, ch in self.timeline if ch != "\b"]

    def stats_at(self, t: float) -> TypingStats:
        """Return typing statistics at time ``t``.

        - WPM is computed as (chars_typed / 5) / (elapsed_minutes),
          where elapsed is measured from the start of typing (excluding
          the start pause). Returns 0 before typing begins.
        - Accuracy is correct_keystrokes / keystrokes (1.0 if no
          keystrokes yet).
        """
        if t < self.start_pause or not self.timeline:
            return TypingStats(0.0, 0, 0, 0, 0.0, 1.0)
        idx = bisect.bisect_right(self._timestamps, t)
        if idx == 0:
            return TypingStats(0.0, 0, 0, 0, 0.0, 1.0)
        ts, _, _ = self.timeline[idx - 1]
        elapsed = max(1e-6, ts - self.start_pause)
        keystrokes = self._keystrokes_prefix[idx - 1]
        correct = self._correct_prefix[idx - 1]
        chars_typed = self._resolved_prefix[idx - 1]
        # Effective WPM: only count chars currently on screen.
        wpm = (chars_typed / 5.0) / (elapsed / 60.0) if elapsed > 0 else 0.0
        accuracy = correct / keystrokes if keystrokes > 0 else 1.0
        return TypingStats(elapsed, chars_typed, keystrokes, correct, wpm, accuracy)
