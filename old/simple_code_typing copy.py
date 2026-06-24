"""
Simple Code Typing Video Generator

Scans a folder for code files, lets you pick them with checkboxes,
then renders typing-animation MP4 videos (with procedural audio)
via FFmpeg.

Requirements:  Python 3.9+, PySide6, numpy, FFmpeg (on PATH).
Usage:         python simple_code_typing.py
"""

from __future__ import annotations

import bisect
import logging
import math
import os
import random
import re
import subprocess
import sys
import tempfile
import threading
import wave
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
from PySide6.QtCore import (
    QEvent, QPoint, QRect, Qt, QThread, Signal, QTimer,
)
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QImage, QLinearGradient, QPainter, QPalette,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
    QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QSizePolicy, QSpinBox, QStatusBar, QStyleFactory, QTabWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QScrollArea,
)

# ── logging ──────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("SimpleCTVG")

# ── directories ─────────────────────────────────────────────────────

CWD = os.getcwd()
INPUT_DIR  = os.path.join(CWD, "input")
OUTPUT_DIR = os.path.join(CWD, "output")
TMP_DIR    = os.path.join(CWD, "tmp")

for _d in (INPUT_DIR, OUTPUT_DIR, TMP_DIR):
    os.makedirs(_d, exist_ok=True)

# ── supported extensions & language map ─────────────────────────────

SUPPORTED_EXTENSIONS = frozenset({
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h",
    ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt",
    ".sh", ".bash", ".zsh", ".sql", ".html", ".css", ".scss", ".json",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".txt", ".md",
    ".lua", ".dart", ".r", ".m",
})

EXT_TO_LANGUAGE: dict[str, str] = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".java": "CFamily", ".c": "CFamily", ".cpp": "CFamily",
    ".h": "CFamily", ".hpp": "CFamily", ".cs": "CFamily",
    ".go": "Go", ".rs": "Rust",
}

# ── resolution presets ──────────────────────────────────────────────

RESOLUTIONS: Dict[str, Tuple[int, int]] = {
    "1920x1080": (1920, 1080),
    "1280x720":  (1280, 720),
    "3840x2160": (3840, 2160),
    "1080x1920 (9:16)": (1080, 1920),
}

# ── colour themes ───────────────────────────────────────────────────

THEMES: Dict[str, Dict[str, str]] = {
    "Dracula": {
        "background": "#282a36", "foreground": "#f8f8f2",
        "comment": "#6272a4", "keyword": "#ff79c6", "string": "#f1fa8c",
        "number": "#bd93f9", "function": "#50fa7b", "builtin": "#8be9fd",
        "decorator": "#50fa7b", "operator": "#ff79c6", "class_name": "#8be9fd",
        "line_number": "#6272a4", "current_line": "#44475a", "cursor": "#f8f8f2",
        "title_bar": "#21222c", "title_text": "#8be9fd",
        "window_border": "#191a21",
    },
    "One Dark": {
        "background": "#282c34", "foreground": "#abb2bf",
        "comment": "#5c6370", "keyword": "#c678dd", "string": "#98c379",
        "number": "#d19a66", "function": "#61afef", "builtin": "#e5c07b",
        "decorator": "#56b6c2", "operator": "#c678dd", "class_name": "#e5c07b",
        "line_number": "#4b5263", "current_line": "#2c313c", "cursor": "#528bff",
        "title_bar": "#21252b", "title_text": "#61afef",
        "window_border": "#181a1f",
    },
    "GitHub Dark": {
        "background": "#0d1117", "foreground": "#c9d1d9",
        "comment": "#8b949e", "keyword": "#ff7b72", "string": "#a5d6ff",
        "number": "#79c0ff", "function": "#d2a8ff", "builtin": "#ffa657",
        "decorator": "#ffa657", "operator": "#ff7b72", "class_name": "#ffa657",
        "line_number": "#484f58", "current_line": "#161b22", "cursor": "#58a6ff",
        "title_bar": "#010409", "title_text": "#58a6ff",
        "window_border": "#010409",
    },
    "Monokai": {
        "background": "#272822", "foreground": "#f8f8f2",
        "comment": "#75715e", "keyword": "#f92672", "string": "#e6db74",
        "number": "#ae81ff", "function": "#a6e22e", "builtin": "#66d9ef",
        "decorator": "#a6e22e", "operator": "#f92672", "class_name": "#66d9ef",
        "line_number": "#75715e", "current_line": "#3e3d32", "cursor": "#f8f8f2",
        "title_bar": "#1e1f1c", "title_text": "#a6e22e",
        "window_border": "#1e1f1c",
    },
    "Solarized Dark": {
        "background": "#002b36", "foreground": "#839496",
        "comment": "#586e75", "keyword": "#859900", "string": "#2aa198",
        "number": "#d33682", "function": "#268bd2", "builtin": "#b58900",
        "decorator": "#b58900", "operator": "#859900", "class_name": "#b58900",
        "line_number": "#586e75", "current_line": "#073642", "cursor": "#93a1a1",
        "title_bar": "#073642", "title_text": "#268bd2",
        "window_border": "#001e26",
    },
    "VS Code Dark+": {
        "background": "#1e1e1e", "foreground": "#d4d4d4",
        "comment": "#6a9955", "keyword": "#569cd6", "string": "#ce9178",
        "number": "#b5cea8", "function": "#dcdcaa", "builtin": "#4ec9b0",
        "decorator": "#4ec9b0", "operator": "#d4d4d4", "class_name": "#4ec9b0",
        "line_number": "#858585", "current_line": "#2a2d2e", "cursor": "#aeafad",
        "title_bar": "#323233", "title_text": "#007acc",
        "window_border": "#323233",
    },
}

# ── language definitions (tokenizer data) ───────────────────────────

_LANG_DATA: Dict[str, dict] = {
    "Python": {
        "keywords": {
            "False", "None", "True", "and", "as", "assert", "async", "await",
            "break", "class", "continue", "def", "del", "elif", "else",
            "except", "finally", "for", "from", "global", "if", "import",
            "in", "is", "lambda", "nonlocal", "not", "or", "pass", "raise",
            "return", "try", "while", "with", "yield",
        },
        "builtins": {
            "print", "len", "range", "int", "str", "float", "list", "dict",
            "set", "tuple", "bool", "type", "isinstance", "enumerate", "zip",
            "map", "filter", "sorted", "reversed", "open", "super", "property",
            "staticmethod", "classmethod", "abs", "max", "min", "sum", "any",
            "all", "hash", "id", "input", "format", "hex", "oct", "bin",
            "round", "pow", "divmod", "chr", "ord", "repr", "vars", "dir",
            "getattr", "setattr", "hasattr", "delattr", "callable", "iter",
            "next", "send", "throw", "close",
        },
        "extra_patterns": [
            ("decorator", r"@\w+(\.\w+)*"),
        ],
        "comment": r"#[^\n]*",
        "string":  r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'',
        "number":  r"\b\d+\.?\d*(?:e[+-]?\d+)?\b|0x[0-9a-fA-F]+\b",
    },
    "JavaScript": {
        "keywords": {
            "break", "case", "catch", "class", "const", "continue", "debugger",
            "default", "delete", "do", "else", "export", "extends", "finally",
            "for", "function", "if", "import", "in", "instanceof", "let",
            "new", "of", "return", "static", "super", "switch", "this",
            "throw", "try", "typeof", "var", "void", "while", "with", "yield",
            "async", "await", "from", "as", "true", "false", "null", "undefined",
        },
        "builtins": {
            "console", "Math", "JSON", "Array", "Object", "String", "Number",
            "Boolean", "Date", "RegExp", "Error", "Map", "Set", "Promise",
            "Symbol", "Proxy", "Reflect", "parseInt", "parseFloat", "isNaN",
            "isFinite", "encodeURI", "decodeURI", "setTimeout", "setInterval",
            "clearTimeout", "clearInterval", "fetch", "document", "window",
            "require", "module", "process", "Buffer", "global",
        },
        "extra_patterns": [],
        "comment": r"//[^\n]*|/\*[\s\S]*?\*/",
        "string":  r'`(?:[^`\\]|\\.)*`|"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'',
        "number":  r"\b\d+\.?\d*(?:e[+-]?\d+)?\b|0x[0-9a-fA-F]+\b",
    },
    "TypeScript": "JavaScript",
    "CFamily": {
        "keywords": {
            "auto", "break", "case", "char", "const", "continue", "default",
            "do", "double", "else", "enum", "extern", "float", "for", "goto",
            "if", "inline", "int", "long", "register", "return", "short",
            "signed", "sizeof", "static", "struct", "switch", "typedef",
            "union", "unsigned", "void", "volatile", "while", "class",
            "namespace", "template", "typename", "public", "private",
            "protected", "virtual", "override", "final", "new", "delete",
            "try", "catch", "throw", "using", "true", "false", "nullptr",
            "boolean", "byte", "extends", "implements", "import", "instanceof",
            "interface", "native", "package", "super", "synchronized",
            "this", "throws", "transient", "abstract", "assert",
        },
        "builtins": {
            "printf", "scanf", "malloc", "free", "sizeof", "strlen",
            "std", "cout", "cin", "endl", "string", "vector", "map", "set",
            "println", "System", "Math",
        },
        "extra_patterns": [],
        "comment": r"//[^\n]*|/\*[\s\S]*?\*/",
        "string":  r'"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\'',
        "number":  r"\b\d+\.?\d*(?:e[+-]?\d+)?\b|0x[0-9a-fA-F]+\b",
    },
    "Go": {
        "keywords": {
            "break", "case", "chan", "const", "continue", "default", "defer",
            "else", "fallthrough", "for", "func", "go", "goto", "if",
            "import", "interface", "map", "package", "range", "return",
            "select", "struct", "switch", "type", "var", "nil", "true",
            "false", "iota",
        },
        "builtins": {
            "fmt", "os", "io", "strings", "strconv", "math", "time",
            "len", "cap", "make", "new", "append", "copy", "delete",
            "panic", "recover", "print", "println",
        },
        "extra_patterns": [],
        "comment": r"//[^\n]*|/\*[\s\S]*?\*/",
        "string":  r'"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\'|`[^`]*`',
        "number":  r"\b\d+\.?\d*(?:e[+-]?\d+)?\b|0x[0-9a-fA-F]+\b",
    },
    "Rust": {
        "keywords": {
            "fn", "let", "mut", "const", "static", "if", "else", "for",
            "while", "loop", "match", "return", "break", "continue", "in",
            "as", "use", "mod", "pub", "struct", "enum", "trait", "impl",
            "where", "self", "Self", "super", "crate", "extern", "ref",
            "move", "async", "await", "dyn", "unsafe", "true", "false",
        },
        "builtins": {
            "println", "print", "format", "vec", "String", "Vec", "Option",
            "Result", "Box", "Rc", "Arc", "Some", "None", "Ok", "Err",
            "HashMap", "BTreeMap", "HashSet",
        },
        "extra_patterns": [],
        "comment": r"//[^\n]*|/\*[\s\S]*?\*/",
        "string":  r'"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\'',
        "number":  r"\b\d+\.?\d*(?:e[+-]?\d+)?\b|0x[0-9a-fA-F]+\b",
    },
}

# Resolve aliases
for _k, _v in list(_LANG_DATA.items()):
    if isinstance(_v, str) and _v in _LANG_DATA:
        _LANG_DATA[_k] = _LANG_DATA[_v]


# =====================================================================
# Tokenizer
# =====================================================================

class Tokenizer:
    """Lightweight regex tokenizer for syntax highlighting."""

    _COMPILED: Dict[str, re.Pattern] = {}
    _LOCK = threading.Lock()

    @classmethod
    def _compile(cls, lang: str) -> re.Pattern:
        if lang not in cls._COMPILED:
            with cls._LOCK:
                if lang not in cls._COMPILED:
                    data = _LANG_DATA.get(lang, _LANG_DATA["Python"])
                    patterns = list(data.get("extra_patterns", []))
                    patterns.extend([
                        ("comment",    data["comment"]),
                        ("string",     data["string"]),
                        ("number",     data["number"]),
                        ("keyword",    r"\b(?:" + "|".join(data["keywords"]) + r")\b"),
                        ("builtin",    r"\b(?:" + "|".join(data["builtins"]) + r")\b"),
                        ("function",   r"\b([a-zA-Z_]\w*)\s*(?=\()"),
                        ("identifier", r"\b[a-zA-Z_]\w*\b"),
                        ("operator",   r"[+\-*/%=<>!&|^~]+"),
                        ("bracket",    r"[(){}[\]]"),
                        ("punctuation",r"[;:,.]"),
                        ("whitespace", r"\s+"),
                        ("other",      r"."),
                    ])
                    pat_str = "|".join(f"(?P<{n}>{p})" for n, p in patterns)
                    cls._COMPILED[lang] = re.compile(pat_str, re.MULTILINE | re.DOTALL)
        return cls._COMPILED[lang]

    @classmethod
    def tokenize(cls, text: str, lang: str) -> List[Tuple[str, str]]:
        compiled = cls._COMPILED.get(lang) or cls._compile(lang)
        return [(m.lastgroup, m.group()) for m in compiled.finditer(text)]


# =====================================================================
# Simple Sound Generator
# =====================================================================

def _make_click(sr: int = 44100, duration: float = 0.06, seed: int = 0) -> np.ndarray:
    """Generate a simple mechanical key click sound."""
    rng = np.random.RandomState(seed)
    n = int(sr * duration)
    t = np.linspace(0, duration, n, False)

    # Impact noise burst
    noise = rng.randn(n) * np.exp(-t * 500) * 0.4
    # Click tone
    freq = 3500 + rng.randint(-300, 300)
    click = np.sin(2 * np.pi * freq * t) * np.exp(-t * 400) * 0.5
    # Low thud
    thud = np.sin(2 * np.pi * 200 * t) * np.exp(-t * 150) * 0.3
    # Combine
    out = noise + click + thud
    peak = np.max(np.abs(out))
    if peak > 0:
        out = out / peak * 32767 * 0.7
    return out.astype(np.int16)


def _make_space_click(sr: int = 44100, seed: int = 100) -> np.ndarray:
    """Lower, longer space bar sound."""
    rng = np.random.RandomState(seed)
    n = int(sr * 0.09)
    t = np.linspace(0, 0.09, n, False)
    noise = rng.randn(n) * np.exp(-t * 250) * 0.35
    thud = np.sin(2 * np.pi * 140 * t) * np.exp(-t * 120) * 0.5
    out = noise + thud
    peak = np.max(np.abs(out))
    if peak > 0:
        out = out / peak * 32767 * 0.7
    return out.astype(np.int16)


def _make_enter_click(sr: int = 44100, seed: int = 200) -> np.ndarray:
    """Return key sound."""
    rng = np.random.RandomState(seed)
    n = int(sr * 0.08)
    t = np.linspace(0, 0.08, n, False)
    noise = rng.randn(n) * np.exp(-t * 300) * 0.4
    thud = np.sin(2 * np.pi * 120 * t) * np.exp(-t * 130) * 0.55
    out = noise + thud
    peak = np.max(np.abs(out))
    if peak > 0:
        out = out / peak * 32767 * 0.7
    return out.astype(np.int16)


class SimpleSoundGen:
    """Generate and mix simple typing sounds."""

    def __init__(self, sr: int = 44100):
        self.sr = sr
        # Pre-generate a small pool of variants
        self.clicks = [_make_click(sr, seed=i) for i in range(6)]
        self.spaces = [_make_space_click(sr, seed=100 + i) for i in range(3)]
        self.enters = [_make_enter_click(sr, seed=200 + i) for i in range(3)]

    def _pick(self, char: str) -> np.ndarray:
        if char == "\n":
            return random.choice(self.enters)
        if char == " ":
            return random.choice(self.spaces)
        return random.choice(self.clicks)

    def generate_track(
        self,
        timestamps: List[Tuple[float, str]],
        filepath: str,
        volume: float = 0.5,
    ) -> None:
        """Mix all keystrokes into a WAV file."""
        if not timestamps:
            return
        sr = self.sr
        total = max(ts for ts, _ in timestamps) + 0.3
        n = int(sr * total)
        mix = np.zeros(n, dtype=np.float64)

        for ts, ch in timestamps:
            snd = self._pick(ch).astype(np.float64)
            s = int(ts * sr)
            e = min(s + len(snd), n)
            if s < n:
                mix[s:e] += snd[:e - s] * volume

        # Simple soft-clip
        peak = np.max(np.abs(mix))
        if peak > 0:
            target = 32767 * 10 ** (-1.5 / 20)
            mix = mix * (target / peak)

        pcm = np.clip(mix, -32768, 32767).astype(np.int16)
        with wave.open(filepath, "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm.tobytes())


# =====================================================================
# Typing Animator (simplified)
# =====================================================================

Event = Tuple[float, int, str]  # (timestamp, display_index, char)

_QWERTY_ROWS = (
    "`1234567890-=",
    "qwertyuiop[]\\",
    "asdfghjkl;'",
    "zxcvbnm,./",
)
_QWERTY_POS: Dict[str, Tuple[int, int]] = {}
for _r, _row in enumerate(_QWERTY_ROWS):
    for _c, _ch in enumerate(_row):
        _QWERTY_POS[_ch] = (_r, _c)
for _ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    _QWERTY_POS[_ch] = _QWERTY_POS.get(_ch.lower(), (2, 0))


class TypingAnimator:
    """Build a per-character typing timeline with basic humanisation."""

    def __init__(
        self,
        code: str,
        wpm: int = 100,
        start_pause: float = 0.5,
        end_pause: float = 1.5,
        seed: Optional[int] = None,
    ):
        self.code = code
        self.start_pause = start_pause
        self.end_pause = end_pause
        cps = (wpm * 5) / 60
        self.base_delay = 1.0 / cps
        self.display_chars: List[str] = []
        self.timeline: List[Event] = self._build(seed)
        self._timestamps = [ts for ts, _, _ in self.timeline]

    def _build(self, seed) -> List[Event]:
        rng = random.Random(seed)
        t = 0.0
        events: List[Event] = []

        for i, ch in enumerate(self.code):
            # Basic per-char delay with jitter
            d = self.base_delay * rng.uniform(0.6, 1.4)

            # Char-class multipliers
            if ch == "\n":
                d *= rng.uniform(2.0, 4.0)
            elif ch == " ":
                d *= rng.uniform(0.7, 1.3)
            elif ch == "\t":
                d *= rng.uniform(1.2, 1.8)
            elif ch in "([{" :
                d *= rng.uniform(1.1, 1.8)
            elif ch in ")]}":
                d *= rng.uniform(0.9, 1.5)
            elif ch in ",;:":
                d *= rng.uniform(1.3, 2.2)

            # Key distance factor
            if i >= 1:
                prev = self.code[i - 1]
                pa = _QWERTY_POS.get(prev.lower())
                pb = _QWERTY_POS.get(ch.lower())
                if pa and pb:
                    dist = math.hypot(pa[0] - pb[0], pa[1] - pb[1])
                    if dist < 0.5:
                        d *= 0.7
                    elif dist > 4:
                        d *= 1.15

            # Occasional thinking pause
            if rng.random() < 0.012:
                d += rng.uniform(0.4, 1.4)

            self.display_chars.append(ch)
            events.append((t, len(self.display_chars) - 1, ch))
            t += max(d, 0.012)

        # Add start/end pauses
        sp = self.start_pause
        events = [(ts + sp, idx, ch) for ts, idx, ch in events]
        return events

    def duration(self) -> float:
        if not self.timeline:
            return self.start_pause + self.end_pause
        return self.timeline[-1][0] + self.end_pause

    def visible_at(self, t: float) -> int:
        if t < self.start_pause:
            return 0
        idx = bisect.bisect_right(self._timestamps, t)
        if idx == 0:
            return 0
        return self.timeline[idx - 1][1] + 1

    def char_timestamps(self) -> List[Tuple[float, str]]:
        return [(ts, ch) for ts, _, ch in self.timeline]


# =====================================================================
# Code Renderer (PySide6 QPainter)
# =====================================================================

class CodeRenderer:
    """Render a single frame of the typing animation into a QImage."""

    TOKEN_COLOR_MAP = {
        "keyword": "keyword", "builtin": "builtin", "string": "string",
        "number": "number", "comment": "comment", "decorator": "decorator",
        "function": "function", "class_name": "class_name",
        "operator": "operator",
    }

    CURSOR_BLINK = 0.53

    def __init__(
        self,
        width: int,
        height: int,
        theme_name: str = "Dracula",
        font_family: str = "Consolas",
        font_size: int = 22,
        show_line_numbers: bool = True,
        show_window_chrome: bool = True,
        padding: int = 50,
        tab_size: int = 4,
        title_text: str = "main.py",
        language: str = "Python",
    ):
        self.width = width
        self.height = height
        self.theme = THEMES.get(theme_name, THEMES["Dracula"])
        self.font_family = font_family
        self.font_size = font_size
        self.show_line_numbers = show_line_numbers
        self.show_window_chrome = show_window_chrome
        self.padding = padding
        self.tab_size = tab_size
        self.title_text = title_text
        self.language = language

        self.font = QFont(font_family, font_size)
        self.font.setFixedPitch(True)
        self.fm = QFontMetrics(self.font)
        self.char_w = self.fm.horizontalAdvance("M")
        self.line_h = self.fm.height()

        self._build_bg_cache()

        # Token color cache per line text
        self._token_cache: Dict[str, List[Tuple[str, str, int]]] = {}

    def _build_bg_cache(self):
        """Pre-render the static background + window chrome."""
        self._bg = QImage(self.width, self.height, QImage.Format_RGB32)
        self._bg.fill(QColor(self.theme["background"]))
        p = QPainter(self._bg)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width, self.height
        pad = self.padding
        chrome_h = 42 if self.show_window_chrome else 0

        # Window area
        wx = pad
        wy = pad
        ww = w - 2 * pad
        wh = h - 2 * pad

        # Window border
        p.setPen(QColor(self.theme["window_border"]))
        p.setBrush(QColor(self.theme["background"]))
        r = 10
        p.drawRoundedRect(wx, wy, ww, wh, r, r)

        if self.show_window_chrome:
            # Title bar
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(self.theme["title_bar"]))
            p.drawRoundedRect(wx, wy, ww, chrome_h, r, r)
            # Cover bottom corners of title bar
            p.drawRect(wx, wy + chrome_h - r, ww, r)

            # Traffic lights
            btn_r = 6
            btn_y = wy + chrome_h // 2
            for i, color in enumerate(["#ff5f56", "#ffbd2e", "#27c93f"]):
                cx = wx + 20 + i * 20
                p.setBrush(QColor(color))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QPoint(cx, btn_y), btn_r, btn_r)

            # Title text
            p.setPen(QColor(self.theme["title_text"]))
            p.setFont(QFont(self.font_family, 12))
            p.drawText(
                QRect(wx, wy, ww, chrome_h),
                Qt.AlignCenter,
                self.title_text,
            )

            code_top = wy + chrome_h
        else:
            code_top = wy

        self._code_rect = QRect(
            wx + 12, code_top + 4, ww - 24, wh - (code_top - wy) - 8
        )
        p.end()

    @staticmethod
    def auto_font_size(
        code_lines: int, width: int, height: int,
        padding: int = 50, show_window_chrome: bool = True,
        show_line_numbers: bool = True, tab_size: int = 4,
        code: Optional[str] = None, font_family: str = "Consolas",
    ) -> int:
        chrome_h = 42 if show_window_chrome else 0
        avail_h = height - 2 * padding - chrome_h - 8
        avail_w = width - 2 * padding - 24
        if show_line_numbers:
            avail_w -= 50

        fm = QFontMetrics(QFont(font_family, 20))
        cw = fm.horizontalAdvance("M")
        lh = fm.height()

        max_font_by_h = avail_h / (code_lines * lh) * 20
        max_chars = 120
        if code:
            longest = max(
                len(line.replace("\t", " " * tab_size)) for line in code.split("\n")
            )
            max_chars = max(longest + 5, 40)
        max_font_by_w = avail_w / (max_chars * cw) * 20

        return int(min(max_font_by_h, max_font_by_w, 40))

    def render_frame(
        self,
        display_chars: List[str],
        num_visible: int,
        cursor_visible: bool = True,
        target: Optional[QImage] = None,
    ) -> QImage:
        img = target if target is not None else QImage(
            self.width, self.height, QImage.Format_RGB32
        )
        if target is None:
            img.fill(QColor(self.theme["background"]))

        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)

        # Blit cached background
        p.drawImage(0, 0, self._bg)

        # Build visible text lines
        visible_text = "".join(display_chars[:num_visible])
        lines = visible_text.split("\n")
        cr = self._code_rect

        # Determine scroll offset
        max_visible_lines = cr.height() // self.line_h
        total_lines = len(lines)
        scroll = max(0, total_lines - max_visible_lines)

        # Line number width
        ln_width = 0
        if self.show_line_numbers:
            ln_width = len(str(total_lines + scroll)) * self.char_w + 16

        # Current line number (1-based in final text)
        current_final_line = visible_text.count("\n") + 1
        # Map to scrolled coordinates
        current_scroll_line = current_final_line - 1 - scroll

        # Highlight current line
        if 0 <= current_scroll_line < max_visible_lines:
            hl_y = cr.top() + current_scroll_line * self.line_h
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(self.theme["current_line"]))
            p.drawRect(cr.left(), hl_y, cr.width(), self.line_h)

        # Draw line numbers + code
        p.setFont(self.font)
        x0 = cr.left() + ln_width
        y_base = cr.top()

        for li, line_text in enumerate(lines):
            si = li - scroll  # screen index
            if si < 0 or si >= max_visible_lines:
                continue

            y = y_base + si * self.line_h + self.fm.ascent()

            # Line number
            if self.show_line_numbers:
                ln_num = li + 1
                p.setPen(QColor(self.theme["line_number"]))
                p.drawText(cr.left() + 4, y, str(ln_num))

            # Tokenize this line
            key = line_text
            if key not in self._token_cache:
                tokens = Tokenizer.tokenize(line_text, self.language)
                x_acc = 0
                colored: List[Tuple[str, str, int]] = []
                for ttype, ttext in tokens:
                    colored.append((ttype, ttext, x_acc))
                    x_acc += len(ttext.replace("\t", " " * self.tab_size))
                self._token_cache[key] = colored

            # Draw tokens
            cx = x0
            for ttype, ttext, _ in self._token_cache[key]:
                color_key = self.TOKEN_COLOR_MAP.get(ttype, "foreground")
                p.setPen(QColor(self.theme.get(color_key, self.theme["foreground"])))
                if ttext == "\t":
                    cx += self.tab_size * self.char_w
                else:
                    for ch in ttext:
                        p.drawText(cx, y, ch)
                        cx += self.fm.horizontalAdvance(ch)

        # Cursor
        if cursor_visible and num_visible > 0:
            cur_line_idx = visible_text.rfind("\n")
            cur_line = visible_text[cur_line_idx + 1:] if cur_line_idx >= 0 else visible_text
            cur_col = len(cur_line.replace("\t", " " * self.tab_size))
            cur_line_screen = visible_text.count("\n") - scroll

            if 0 <= cur_line_screen < max_visible_lines:
                cx = x0 + cur_col * self.char_w
                cy = y_base + cur_line_screen * self.line_h
                p.setPen(QColor(self.theme["cursor"]))
                p.drawRect(cx, cy + 2, 2, self.line_h - 4)

        p.end()
        return img


# =====================================================================
# FFmpeg Video Exporter
# =====================================================================

class VideoExporter(QThread):
    """Render frames and pipe them to FFmpeg."""

    progress = Signal(int)
    status = Signal(str)
    finished_ok = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        code: str,
        output: str,
        renderer: CodeRenderer,
        animator: TypingAnimator,
        fps: int = 30,
        sound_gen: Optional[SimpleSoundGen] = None,
        volume: float = 0.5,
    ):
        super().__init__()
        self.code = code
        self.output = output
        self.renderer = renderer
        self.animator = animator
        self.fps = fps
        self.sound_gen = sound_gen
        self.volume = volume
        self._cancel = threading.Event()
        self._raw_buf = np.empty(
            (renderer.height, renderer.width, 3), dtype=np.uint8
        )

    def cancel(self):
        self._cancel.set()

    def run(self):
        try:
            os.makedirs(TMP_DIR, exist_ok=True)
            tmp = tempfile.mkdtemp(dir=TMP_DIR, prefix="sctvg_")
            aud_path = os.path.join(tmp, "audio.wav")

            total = self.animator.duration()
            n_frames = max(1, int(total * self.fps))
            w, h = self.renderer.width, self.renderer.height

            self.status.emit(f"Generating audio...")
            has_audio = False
            if self.sound_gen:
                self.sound_gen.generate_track(
                    self.animator.char_timestamps(), aud_path, self.volume
                )
                has_audio = os.path.exists(aud_path) and os.path.getsize(aud_path) > 44

            # Build FFmpeg command
            cmd = [
                "ffmpeg", "-y",
                "-f", "rawvideo", "-pix_fmt", "rgb24",
                "-s", f"{w}x{h}", "-r", str(self.fps),
                "-i", "pipe:0",
            ]
            if has_audio:
                cmd += ["-i", aud_path]
            cmd += [
                "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            ]
            if has_audio:
                cmd += ["-c:a", "aac", "-b:a", "192k"]
            cmd.append(self.output)

            self.status.emit(f"Encoding {n_frames} frames...")
            proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )

            stderr_chunks: list[bytes] = []
            def _drain():
                while True:
                    chunk = proc.stderr.read(8192)
                    if not chunk:
                        break
                    stderr_chunks.append(chunk)
            drain_t = threading.Thread(target=_drain, daemon=True)
            drain_t.start()

            scratch = QImage(w, h, QImage.Format_RGB32)
            frame_size = w * h * 3

            for fi in range(n_frames):
                if self._cancel.is_set():
                    proc.stdin.close()
                    proc.terminate()
                    proc.wait(timeout=5)
                    self.error.emit("Cancelled")
                    return

                t = fi / self.fps
                nv = self.animator.visible_at(t)

                # Cursor blink
                cur_vis = True
                if nv > 0:
                    idx = bisect.bisect_right(self.animator._timestamps, t)
                    if idx > 0:
                        last_ts = self.animator.timeline[idx - 1][0]
                        if t - last_ts > 0.25:
                            cur_vis = (int((t - last_ts) / self.renderer.CURSOR_BLINK) % 2) == 0

                qimg = self.renderer.render_frame(
                    self.animator.display_chars, nv, cur_vis, target=scratch
                )
                raw = self._qimg_to_rgb(qimg)
                proc.stdin.write(raw)

                if fi % max(1, n_frames // 20) == 0 and fi > 0:
                    pct = int(fi / n_frames * 100)
                    self.progress.emit(pct)
                    self.status.emit(f"Encoding... {pct}%")

            proc.stdin.close()
            proc.wait(timeout=600)
            drain_t.join(timeout=5)

            if proc.returncode != 0:
                err = b"".join(stderr_chunks).decode(errors="ignore")[-600:]
                raise RuntimeError(f"FFmpeg failed (code {proc.returncode}): {err}")

            self.progress.emit(100)
            self.status.emit(f"Done -> {self.output}")
            self.finished_ok.emit(self.output)

        except Exception as e:
            log.error("Export failed: %s", e, exc_info=True)
            self.error.emit(str(e))

    def _qimg_to_rgb(self, qimg: QImage) -> bytes:
        w, h = qimg.width(), qimg.height()
        # Convert to RGB888 for reliable access
        qimg = qimg.convertToFormat(QImage.Format_RGB888)
        bpl = qimg.bytesPerLine()
        ptr = qimg.constBits()
        # Handle both sip.voidptr and memoryview
        raw = bytes(ptr) if isinstance(ptr, memoryview) else bytes(ptr)
        arr = np.frombuffer(raw[:h * bpl], dtype=np.uint8).reshape((h, bpl))
        if bpl != w * 3:
            arr = arr[:, :w * 3]
        return np.ascontiguousarray(arr).tobytes()


# =====================================================================
# Main Window — checkbox-based program selector
# =====================================================================

@dataclass
class FileItem:
    path: str
    checked: bool = False
    status: str = "Pending"  # Pending / Rendering / Done / Failed
    output_path: Optional[str] = None
    error: Optional[str] = None


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Simple Code Typing Video Generator")
        self.setMinimumSize(750, 600)
        self.resize(850, 700)

        self._items: List[FileItem] = []
        self._exporter: Optional[VideoExporter] = None
        self._export_queue: List[FileItem] = []

        self._build_ui()
        self._scan_input_dir()

    # ── UI construction ─────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # --- File list group ---
        file_group = QGroupBox("Programs (check to export)")
        fg_lay = QVBoxLayout(file_group)

        # Buttons row
        btn_row = QHBoxLayout()
        self.scan_btn = QPushButton("Scan input/ folder")
        self.scan_btn.clicked.connect(self._scan_input_dir)
        btn_row.addWidget(self.scan_btn)

        self.add_btn = QPushButton("Add files...")
        self.add_btn.clicked.connect(self._add_files)
        btn_row.addWidget(self.add_btn)

        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self._select_all)
        btn_row.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("Deselect All")
        self.deselect_all_btn.clicked.connect(self._deselect_all)
        btn_row.addWidget(self.deselect_all_btn)

        btn_row.addStretch()
        fg_lay.addLayout(btn_row)

        # Table
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Export", "File", "Language", "Status"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Fixed)
        hdr.resizeSection(0, 60)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.Fixed)
        hdr.resizeSection(2, 90)
        hdr.setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.itemChanged.connect(self._on_item_changed)
        fg_lay.addWidget(self.table)
        root.addWidget(file_group, stretch=1)

        # --- Settings group ---
        settings_group = QGroupBox("Settings")
        sg = QGridLayout(settings_group)
        sg.setSpacing(8)
        row = 0

        sg.addWidget(QLabel("Theme:"), row, 0)
        self.theme_cb = QComboBox()
        self.theme_cb.addItems(list(THEMES.keys()))
        self.theme_cb.setCurrentText("Dracula")
        sg.addWidget(self.theme_cb, row, 1)

        sg.addWidget(QLabel("Resolution:"), row, 2)
        self.res_cb = QComboBox()
        self.res_cb.addItems(list(RESOLUTIONS.keys()))
        self.res_cb.setCurrentText("1920x1080")
        sg.addWidget(self.res_cb, row, 3)

        row += 1
        sg.addWidget(QLabel("WPM:"), row, 0)
        self.wpm_sp = QSpinBox()
        self.wpm_sp.setRange(30, 300)
        self.wpm_sp.setValue(100)
        sg.addWidget(self.wpm_sp, row, 1)

        sg.addWidget(QLabel("FPS:"), row, 2)
        self.fps_sp = QSpinBox()
        self.fps_sp.setRange(10, 60)
        self.fps_sp.setValue(30)
        sg.addWidget(self.fps_sp, row, 3)

        row += 1
        sg.addWidget(QLabel("Start Pause (s):"), row, 0)
        self.start_pause_sp = QDoubleSpinBox()
        self.start_pause_sp.setRange(0, 10)
        self.start_pause_sp.setSingleStep(0.5)
        self.start_pause_sp.setValue(0.5)
        sg.addWidget(self.start_pause_sp, row, 1)

        sg.addWidget(QLabel("End Pause (s):"), row, 2)
        self.end_pause_sp = QDoubleSpinBox()
        self.end_pause_sp.setRange(0, 10)
        self.end_pause_sp.setSingleStep(0.5)
        self.end_pause_sp.setValue(1.5)
        sg.addWidget(self.end_pause_sp, row, 3)

        row += 1
        self.sound_chk = QCheckBox("Typing Sounds")
        self.sound_chk.setChecked(True)
        sg.addWidget(self.sound_chk, row, 0, 1, 2)

        sg.addWidget(QLabel("Volume:"), row, 2)
        self.vol_sl = QSpinBox()
        self.vol_sl.setRange(0, 100)
        self.vol_sl.setValue(50)
        self.vol_sl.setSuffix("%")
        sg.addWidget(self.vol_sl, row, 3)

        root.addWidget(settings_group)

        # --- Progress ---
        prog_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        prog_row.addWidget(self.progress_bar)
        root.addLayout(prog_row)

        # --- Buttons ---
        btn_row2 = QHBoxLayout()
        btn_row2.addStretch()

        self.export_btn = QPushButton("Export Checked")
        self.export_btn.setObjectName("primaryBtn")
        self.export_btn.setMinimumHeight(36)
        self.export_btn.clicked.connect(self._start_export)
        btn_row2.addWidget(self.export_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_export)
        btn_row2.addWidget(self.cancel_btn)

        root.addLayout(btn_row2)

        # --- Status bar ---
        self.statusBar().showMessage("Ready. Place code files in input/ folder and click Scan.")

    # ── File scanning ───────────────────────────────────────────────

    def _scan_input_dir(self):
        self._items.clear()
        if not os.path.isdir(INPUT_DIR):
            self.statusBar().showMessage(f"input/ folder not found at {INPUT_DIR}")
            self._refresh_table()
            return
        for fname in sorted(os.listdir(INPUT_DIR)):
            fpath = os.path.join(INPUT_DIR, fname)
            if os.path.isfile(fpath):
                ext = os.path.splitext(fname)[1].lower()
                if ext in SUPPORTED_EXTENSIONS:
                    self._items.append(FileItem(path=fpath))
        self._refresh_table()
        self.statusBar().showMessage(
            f"Found {len(self._items)} code file(s) in {INPUT_DIR}/"
        )

    def _add_files(self):
        ext_str = " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTENSIONS))
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Code Files", "",
            f"Code Files ({ext_str});;All Files (*)",
        )
        for p in paths:
            if not any(it.path == p for it in self._items):
                self._items.append(FileItem(path=p))
        self._refresh_table()

    def _select_all(self):
        for it in self._items:
            it.checked = True
        self._refresh_table()

    def _deselect_all(self):
        for it in self._items:
            it.checked = False
        self._refresh_table()

    def _on_item_changed(self, item):
        row = item.row()
        col = item.column()
        if col == 0 and 0 <= row < len(self._items):
            self._items[row].checked = (item.checkState() == Qt.CheckState.Checked)

    def _refresh_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._items))
        for i, item in enumerate(self._items):
            # Checkbox
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk.setCheckState(
                Qt.CheckState.Checked if item.checked else Qt.CheckState.Unchecked
            )
            self.table.setItem(i, 0, chk)

            # Filename
            self.table.setItem(i, 1, QTableWidgetItem(os.path.basename(item.path)))

            # Language
            ext = os.path.splitext(item.path)[1].lower()
            lang = EXT_TO_LANGUAGE.get(ext, "Python")
            self.table.setItem(i, 2, QTableWidgetItem(lang))

            # Status
            status_item = QTableWidgetItem(item.status)
            if item.status == "Done":
                status_item.setForeground(QColor("#50fa7b"))
            elif item.status == "Failed":
                status_item.setForeground(QColor("#ff5555"))
            elif item.status == "Rendering":
                status_item.setForeground(QColor("#8be9fd"))
            self.table.setItem(i, 3, status_item)

        self.table.blockSignals(False)

    # ── Export ──────────────────────────────────────────────────────

    def _start_export(self):
        checked = [it for it in self._items if it.checked]
        if not checked:
            QMessageBox.information(self, "Nothing selected", "Check at least one program to export.")
            return

        # Reset statuses
        for it in checked:
            it.status = "Pending"
            it.output_path = None
            it.error = None
        self._refresh_table()

        self._export_queue = list(checked)
        self.export_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self._export_next()

    def _export_next(self):
        if not self._export_queue:
            self.export_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            done = sum(1 for it in self._items if it.status == "Done")
            failed = sum(1 for it in self._items if it.status == "Failed")
            msg = f"Batch complete: {done} done"
            if failed:
                msg += f", {failed} failed"
            self.statusBar().showMessage(msg)
            self.progress_bar.setValue(100)
            return

        item = self._export_queue.pop(0)
        item.status = "Rendering"
        self._refresh_table()

        # Read code
        try:
            with open(item.path, "r", encoding="utf-8", errors="replace") as f:
                code = f.read()
        except Exception as e:
            item.status = "Failed"
            item.error = str(e)
            self._refresh_table()
            self._export_next()
            return

        if not code.strip():
            item.status = "Failed"
            item.error = "Empty file"
            self._refresh_table()
            self._export_next()
            return

        # Resolve settings
        ext = os.path.splitext(item.path)[1].lower()
        language = EXT_TO_LANGUAGE.get(ext, "Python")
        res_name = self.res_cb.currentText()
        w, h = RESOLUTIONS.get(res_name, (1920, 1080))

        font_size = CodeRenderer.auto_font_size(
            code_lines=code.count("\n") + 1,
            width=w, height=h,
            code=code,
            font_family="Consolas",
        )

        title = f"{os.path.basename(item.path)} - Code Editor"

        renderer = CodeRenderer(
            width=w, height=h,
            theme_name=self.theme_cb.currentText(),
            font_size=font_size,
            title_text=title,
            language=language,
        )

        animator = TypingAnimator(
            code,
            wpm=self.wpm_sp.value(),
            start_pause=self.start_pause_sp.value(),
            end_pause=self.end_pause_sp.value(),
        )

        # Output path
        base = os.path.splitext(os.path.basename(item.path))[0]
        output = os.path.join(OUTPUT_DIR, f"{base}.mp4")

        sound_gen = SimpleSoundGen() if self.sound_chk.isChecked() else None

        self._exporter = VideoExporter(
            code=code,
            output=output,
            renderer=renderer,
            animator=animator,
            fps=self.fps_sp.value(),
            sound_gen=sound_gen,
            volume=self.vol_sl.value() / 100.0,
        )
        self._exporter.progress.connect(self.progress_bar.setValue)
        self._exporter.status.connect(self.statusBar().showMessage)
        self._exporter.finished_ok.connect(lambda p: self._on_item_done(item, p))
        self._exporter.error.connect(lambda e: self._on_item_failed(item, e))
        self._exporter.start()

    def _on_item_done(self, item: FileItem, path: str):
        item.status = "Done"
        item.output_path = path
        self._refresh_table()
        self._exporter = None
        self._export_next()

    def _on_item_failed(self, item: FileItem, err: str):
        item.status = "Failed"
        item.error = err
        self._refresh_table()
        self._exporter = None
        self._export_next()

    def _cancel_export(self):
        if self._exporter:
            self._exporter.cancel()
        self._export_queue.clear()


# =====================================================================
# Entry point
# =====================================================================

STYLE = """
QMainWindow, QDialog { background: #1e1e2e; }
QGroupBox {
    color: #cdd6f4; font-weight: bold; font-size: 13px;
    border: 1px solid #45475a; border-radius: 8px;
    margin-top: 12px; padding-top: 16px;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; }
QLabel { color: #cdd6f4; }
QTableWidget {
    background: #181825; color: #cdd6f4; gridline-color: #313244;
    border: 1px solid #45475a; border-radius: 6px;
    selection-background-color: #45475a;
}
QHeaderView::section {
    background: #313244; color: #cdd6f4; padding: 6px;
    border: none; font-weight: bold;
}
QComboBox, QSpinBox, QDoubleSpinBox {
    background: #313244; color: #cdd6f4; border: 1px solid #45475a;
    border-radius: 4px; padding: 4px 8px; min-height: 24px;
}
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background: #313244; color: #cdd6f4;
    selection-background-color: #45475a;
}
QCheckBox { color: #cdd6f4; spacing: 6px; }
QCheckBox::indicator {
    width: 18px; height: 18px; border-radius: 4px;
    border: 2px solid #45475a; background: #313244;
}
QCheckBox::indicator:checked { background: #89b4fa; border-color: #89b4fa; }
QPushButton {
    background: #313244; color: #cdd6f4; border: 1px solid #45475a;
    border-radius: 6px; padding: 6px 16px; font-size: 13px;
}
QPushButton:hover { background: #45475a; }
QPushButton:disabled { color: #585b70; }
QPushButton#primaryBtn {
    background: #89b4fa; color: #1e1e2e; font-weight: bold;
    border: none; padding: 8px 24px; font-size: 14px;
}
QPushButton#primaryBtn:hover { background: #74c7ec; }
QPushButton#primaryBtn:disabled { background: #45475a; color: #585b70; }
QProgressBar {
    background: #313244; border: none; border-radius: 4px;
    text-align: center; color: #cdd6f4; min-height: 20px;
}
QProgressBar::chunk { background: #89b4fa; border-radius: 4px; }
QStatusBar { color: #a6adc8; font-size: 12px; }
"""


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)

    pal = QPalette()
    pal.setColor(QPalette.Window, QColor("#1e1e2e"))
    pal.setColor(QPalette.WindowText, QColor("#cdd6f4"))
    pal.setColor(QPalette.Base, QColor("#313244"))
    pal.setColor(QPalette.Text, QColor("#cdd6f4"))
    pal.setColor(QPalette.Button, QColor("#313244"))
    pal.setColor(QPalette.ButtonText, QColor("#cdd6f4"))
    pal.setColor(QPalette.Highlight, QColor("#89b4fa"))
    pal.setColor(QPalette.HighlightedText, QColor("#1e1e2e"))
    app.setPalette(pal)

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())