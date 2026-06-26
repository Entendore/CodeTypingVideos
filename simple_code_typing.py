"""
Code Typing Video Generator

Scans a folder for code files, lets you pick them with checkboxes,
then renders typing-animation MP4 videos (with procedural audio)
via FFmpeg.

Requirements:  Python 3.9+, PySide6, numpy, FFmpeg (on PATH).
Usage:         python code_typing.py
"""

from __future__ import annotations

import bisect
import json
import logging
import math
import os
import platform
import random
import re
import subprocess
import sys
import shutil
import tempfile
import threading
import time as _time
import wave
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
from PySide6.QtCore import (
    QEvent, QPointF, QPoint, QRect, Qt, QThread, Signal, QTimer, QUrl,
)
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QFontMetrics, QImage, QLinearGradient, QPainter, QPalette, QPen, QBrush, QPainterPath, QPixmap, QPolygonF,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
    QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QSizePolicy, QSpinBox, QStatusBar, QStyleFactory, QTabWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QScrollArea,
    QFormLayout, QFrame, QDialogButtonBox, QSlider, QGraphicsDropShadowEffect,
    QLineEdit,
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

SETTINGS_FILE = os.path.join(CWD, "settings.json")

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

# Directories to skip during recursive scanning
_SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", "__pycache__", "node_modules",
    ".venv", "venv", ".env", ".idea", ".vscode", "dist",
    "build", ".tox", ".mypy_cache", ".pytest_cache", ".next",
    ".nuxt", "target", "vendor", ".bundle",
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
# Sound Presets
# =====================================================================

SOUND_PRESETS = {
    "Mechanical": {
        "description": "Standard mechanical keyboard click",
    },
    "Typewriter": {
        "description": "Classic typewriter with carriage bell on Enter",
    },
    "Cash Register": {
        "description": "Chunky cash register keys with ka-ching on Enter",
    },
}


# ── Mechanical preset (original sounds) ────────────────────────────

def _make_mechanical_click(sr: int = 44100, duration: float = 0.06, seed: int = 0) -> np.ndarray:
    rng = np.random.RandomState(seed)
    n = int(sr * duration)
    t = np.linspace(0, duration, n, False)
    noise = rng.randn(n) * np.exp(-t * 500) * 0.4
    freq = 3500 + rng.randint(-300, 300)
    click = np.sin(2 * np.pi * freq * t) * np.exp(-t * 400) * 0.5
    thud = np.sin(2 * np.pi * 200 * t) * np.exp(-t * 150) * 0.3
    out = noise + click + thud
    peak = np.max(np.abs(out))
    if peak > 0:
        out = out / peak * 32767 * 0.7
    return out.astype(np.int16)


def _make_mechanical_space(sr: int = 44100, seed: int = 100) -> np.ndarray:
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


def _make_mechanical_enter(sr: int = 44100, seed: int = 200) -> np.ndarray:
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


# ── Typewriter preset ──────────────────────────────────────────────

def _make_typewriter_click(sr: int = 44100, duration: float = 0.045, seed: int = 0) -> np.ndarray:
    """Sharp, metallic typewriter key strike - short and punchy."""
    rng = np.random.RandomState(seed)
    n = int(sr * duration)
    t = np.linspace(0, duration, n, False)
    # Sharp metal impact noise
    noise = rng.randn(n) * np.exp(-t * 800) * 0.5
    # High metallic ring
    freq = 4500 + rng.randint(-400, 400)
    ring = np.sin(2 * np.pi * freq * t) * np.exp(-t * 600) * 0.45
    # Hammer arm thud
    thud = np.sin(2 * np.pi * 280 * t) * np.exp(-t * 200) * 0.25
    # Typebar slap
    slap = np.sin(2 * np.pi * 1200 * t) * np.exp(-t * 900) * 0.3
    out = noise + ring + thud + slap
    peak = np.max(np.abs(out))
    if peak > 0:
        out = out / peak * 32767 * 0.75
    return out.astype(np.int16)


def _make_typewriter_space(sr: int = 44100, seed: int = 100) -> np.ndarray:
    """Typewriter space bar - wider, more resonant."""
    rng = np.random.RandomState(seed)
    n = int(sr * 0.08)
    t = np.linspace(0, 0.08, n, False)
    noise = rng.randn(n) * np.exp(-t * 400) * 0.45
    thud = np.sin(2 * np.pi * 180 * t) * np.exp(-t * 160) * 0.45
    ring = np.sin(2 * np.pi * 2000 * t) * np.exp(-t * 500) * 0.2
    out = noise + thud + ring
    peak = np.max(np.abs(out))
    if peak > 0:
        out = out / peak * 32767 * 0.75
    return out.astype(np.int16)


def _make_typewriter_enter(sr: int = 44100, seed: int = 200) -> np.ndarray:
    """Carriage return slide + bell - the classic typewriter ding."""
    rng = np.random.RandomState(seed)
    # Carriage return slide (0.25s)
    slide_dur = 0.25
    n_slide = int(sr * slide_dur)
    t_s = np.linspace(0, slide_dur, n_slide, False)
    # Sliding carriage noise
    slide_noise = rng.randn(n_slide) * np.exp(-t_s * 20) * 0.15
    # Ratchet sound (rapid clicks)
    ratchet = np.sin(2 * np.pi * 60 * t_s * (1 + 8 * np.exp(-t_s * 15))) \
        * np.exp(-t_s * 12) * 0.25
    # Bell at the end (pure tone ding)
    bell_dur = 0.35
    n_bell = int(sr * bell_dur)
    t_b = np.linspace(0, bell_dur, n_bell, False)
    bell = np.sin(2 * np.pi * 2200 * t_b) * np.exp(-t_b * 8) * 0.5
    bell += np.sin(2 * np.pi * 4400 * t_b) * np.exp(-t_b * 12) * 0.15
    # Combine: slide first, then bell overlaps
    out_len = n_slide + n_bell
    out = np.zeros(out_len, dtype=np.float64)
    out[:n_slide] += slide_noise + ratchet
    overlap = int(sr * 0.05)
    out[n_slide - overlap:n_slide - overlap + n_bell] += bell
    peak = np.max(np.abs(out))
    if peak > 0:
        out = out / peak * 32767 * 0.75
    return out.astype(np.int16)


# ── Cash Register preset ───────────────────────────────────────────

def _make_cashreg_click(sr: int = 44100, duration: float = 0.07, seed: int = 0) -> np.ndarray:
    """Chunky, deep cash register key press."""
    rng = np.random.RandomState(seed)
    n = int(sr * duration)
    t = np.linspace(0, duration, n, False)
    # Heavy mechanical thud
    thud = np.sin(2 * np.pi * 120 * t) * np.exp(-t * 100) * 0.6
    # Key plunger noise
    noise = rng.randn(n) * np.exp(-t * 350) * 0.35
    # Plastic/metal clack
    clack = np.sin(2 * np.pi * 2800 * t) * np.exp(-t * 500) * 0.3
    # Spring return
    spring = np.sin(2 * np.pi * 600 * t * (1 + 2 * np.exp(-t * 300))) \
        * np.exp(-t * 250) * 0.15
    out = thud + noise + clack + spring
    peak = np.max(np.abs(out))
    if peak > 0:
        out = out / peak * 32767 * 0.7
    return out.astype(np.int16)


def _make_cashreg_space(sr: int = 44100, seed: int = 100) -> np.ndarray:
    """Wide cash register bar press - heavier thud."""
    rng = np.random.RandomState(seed)
    n = int(sr * 0.10)
    t = np.linspace(0, 0.10, n, False)
    thud = np.sin(2 * np.pi * 100 * t) * np.exp(-t * 80) * 0.65
    noise = rng.randn(n) * np.exp(-t * 200) * 0.3
    clack = np.sin(2 * np.pi * 2000 * t) * np.exp(-t * 350) * 0.25
    out = thud + noise + clack
    peak = np.max(np.abs(out))
    if peak > 0:
        out = out / peak * 32767 * 0.7
    return out.astype(np.int16)


def _make_cashreg_enter(sr: int = 44100, seed: int = 200) -> np.ndarray:
    """Cash register total key - chunky press + ka-ching!"""
    rng = np.random.RandomState(seed)
    # Key press (0.06s)
    press_dur = 0.06
    n_press = int(sr * press_dur)
    t_p = np.linspace(0, press_dur, n_press, False)
    thud = np.sin(2 * np.pi * 100 * t_p) * np.exp(-t_p * 150) * 0.5
    noise = rng.randn(n_press) * np.exp(-t_p * 500) * 0.3
    press = thud + noise
    # Ka-ching! (0.5s) - two metallic tones
    ka_dur = 0.18
    ching_dur = 0.40
    pause_dur = 0.04
    n_ka = int(sr * ka_dur)
    n_pause = int(sr * pause_dur)
    n_ching = int(sr * ching_dur)
    t_ka = np.linspace(0, ka_dur, n_ka, False)
    t_ch = np.linspace(0, ching_dur, n_ching, False)
    # "Ka" - low metallic
    ka = np.sin(2 * np.pi * 800 * t_ka) * np.exp(-t_ka * 20) * 0.55
    ka += np.sin(2 * np.pi * 1600 * t_ka) * np.exp(-t_ka * 25) * 0.25
    ka += rng.randn(n_ka) * np.exp(-t_ka * 40) * 0.1
    # "Ching" - high bell-like
    ching = np.sin(2 * np.pi * 3500 * t_ch) * np.exp(-t_ch * 6) * 0.45
    ching += np.sin(2 * np.pi * 5250 * t_ch) * np.exp(-t_ch * 8) * 0.2
    ching += np.sin(2 * np.pi * 7000 * t_ch) * np.exp(-t_ch * 12) * 0.1
    # Combine
    out_len = n_press + n_ka + n_pause + n_ching
    out = np.zeros(out_len, dtype=np.float64)
    out[:n_press] += press
    offset = n_press
    out[offset:offset + n_ka] += ka
    offset += n_ka + n_pause
    out[offset:offset + n_ching] += ching
    peak = np.max(np.abs(out))
    if peak > 0:
        out = out / peak * 32767 * 0.75
    return out.astype(np.int16)


# ── Preset dispatch tables ─────────────────────────────────────────

_PRESET_FACTORIES: Dict[str, Dict[str, callable]] = {
    "Mechanical": {
        "click": _make_mechanical_click,
        "space": _make_mechanical_space,
        "enter": _make_mechanical_enter,
    },
    "Typewriter": {
        "click": _make_typewriter_click,
        "space": _make_typewriter_space,
        "enter": _make_typewriter_enter,
    },
    "Cash Register": {
        "click": _make_cashreg_click,
        "space": _make_cashreg_space,
        "enter": _make_cashreg_enter,
    },
}


# ── Optional acceleration backend ───────────────────────────────────
# Numba > CPU  JIT-compiled loops (fast, no GPU needed)
# NumPy > pure-Python fallback (works everywhere)

try:
    import numba
    _HAS_NUMBA = True
except ImportError:
    _HAS_NUMBA = False


# ── Numba JIT kernels (compiled once, cached to __pycache__) ───────

if _HAS_NUMBA:
    @numba.njit(cache=True)
    def _nb_mix_sounds(mix, sounds_flat, offsets, lengths, starts):
        """Accumulate every sound into *mix* - overlap-safe, single thread."""
        for i in range(len(starts)):
            s  = starts[i]
            ln = lengths[i]
            o  = offsets[i]
            for j in range(ln):
                mix[s + j] += sounds_flat[o + j]

    @numba.njit(cache=True, parallel=True)
    def _nb_chunked_peak(mix, chunk_size):
        """Return one abs-peak per chunk (parallel across chunks)."""
        n = len(mix)
        n_chunks = (n + chunk_size - 1) // chunk_size
        peaks = np.empty(n_chunks, dtype=np.float32)
        for c in numba.prange(n_chunks):
            cs = c * chunk_size
            ce = cs + chunk_size
            if ce > n:
                ce = n
            p = np.float32(0.0)
            for i in range(cs, ce):
                v = mix[i]
                if v < 0.0:
                    v = -v
                if v > p:
                    p = v
            peaks[c] = p
        return peaks

    @numba.njit(cache=True)
    def _nb_normalize_clip(mix_chunk, norm):
        """Normalize → hard-clip → int16 in one pass, no temp arrays."""
        n = len(mix_chunk)
        out = np.empty(n, dtype=np.int16)
        for i in range(n):
            v = mix_chunk[i] * norm
            if v > 32767.0:
                out[i] = 32767
            elif v < -32768.0:
                out[i] = -32768
            else:
                out[i] = np.int16(v)
        return out


# =====================================================================
# Simple Sound Generator
# =====================================================================

class SimpleSoundGen:
    """Generate and mix typing sounds with selectable presets.

    Uses Numba (JIT CPU) when available, otherwise falls back to
    NumPy + memmap.  Install Numba for ~10x faster audio generation:
        pip install numba
    """

    def __init__(self, sr: int = 44100, preset: str = "Mechanical"):
        self.sr = sr
        self.preset = preset
        factories = _PRESET_FACTORIES.get(preset, _PRESET_FACTORIES["Mechanical"])
        # Pre-generate a small pool of variants
        click_dur = 0.045 if preset == "Typewriter" else 0.06
        self.clicks = [factories["click"](
            sr, duration=click_dur, seed=i
        ) for i in range(6)]
        self.spaces = [factories["space"](sr, seed=100 + i) for i in range(3)]
        self.enters = [factories["enter"](sr, seed=200 + i) for i in range(3)]

    def _pick(self, char: str) -> np.ndarray:
        if char == "\n":
            return random.choice(self.enters)
        if char == " ":
            return random.choice(self.spaces)
        return random.choice(self.clicks)

    # ─────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────

    def generate_track(
        self,
        timestamps: List[Tuple[float, str]],
        filepath: str,
        volume: float = 0.5,
    ) -> None:
        """Mix all keystrokes into a WAV file.

        Dispatches to the fastest available backend (CuPy > Numba > NumPy).
        All backends produce bit-identical output normalised to -1.5 dBFS.
        """
        if not timestamps:
            return
        sr = self.sr
        total = max(ts for ts, _ in timestamps) + 0.3
        n = int(sr * total)

        # ── Pre-resolve & flatten sounds ──────────────────────────────
        # Converting every sound to float32 and concatenating into one
        # contiguous buffer lets Numba and CuPy iterate with zero Python
        # overhead and optimal memory-access patterns.
        raw_sounds: List[np.ndarray] = []
        starts_i: List[int] = []
        for ts, ch in timestamps:
            snd = self._pick(ch)
            s = int(ts * sr)
            e = min(s + len(snd), n)
            if s < n:
                raw_sounds.append(snd[:e - s].astype(np.float32) * volume)
                starts_i.append(s)
        if not raw_sounds:
            return

        starts      = np.array(starts_i, dtype=np.int64)
        lengths     = np.array([len(s) for s in raw_sounds], dtype=np.int64)
        sounds_flat = np.concatenate(raw_sounds)
        offsets     = np.zeros(len(raw_sounds), dtype=np.int64)
        for i in range(1, len(raw_sounds)):
            offsets[i] = offsets[i - 1] + lengths[i - 1]
        del raw_sounds, starts_i  # free per-sound overhead

        # ── Dispatch ─────────────────────────────────────────────────
        if _HAS_NUMBA:
            self._mix_numba(n, starts, lengths, offsets, sounds_flat,
                            filepath, sr)
        else:
            self._mix_numpy(n, starts, lengths, offsets, sounds_flat,
                            filepath, sr)

    # ─────────────────────────────────────────────────────────────────
    # Numba backend  (JIT-compiled CPU)
    # ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _mix_numba(n, starts, lengths, offsets, sounds_flat, filepath, sr):
        """JIT-compiled mix + parallel peak scan + JIT normalize/clip."""
        log.info("Audio backend: Numba (JIT CPU)")

        _mmap_path = filepath + ".mixtmp"
        mix = np.memmap(_mmap_path, dtype=np.float32, mode="w+",
                        shape=(n,))
        try:
            # Single-threaded JIT mix (overlap-safe)
            _nb_mix_sounds(mix, sounds_flat, offsets, lengths, starts)
            del sounds_flat

            # Multi-core parallel peak scan (10 s chunks)
            CHUNK = 10 * sr
            chunk_peaks = _nb_chunked_peak(mix, CHUNK)
            peak = float(np.max(chunk_peaks))
            del chunk_peaks
            norm = (32767 * 10 ** (-1.5 / 20)) / peak if peak > 0 else 1.0

            # Stream to WAV - JIT handles normalize + clip + int16
            with wave.open(filepath, "w") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sr)
                for cs in range(0, n, CHUNK):
                    ce = min(cs + CHUNK, n)
                    pcm = _nb_normalize_clip(mix[cs:ce], np.float32(norm))
                    wf.writeframes(pcm.tobytes())
        finally:
            del mix
            try:
                os.remove(_mmap_path)
            except OSError:
                pass

    # ─────────────────────────────────────────────────────────────────
    # NumPy fallback  (pure Python, works everywhere)
    # ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _mix_numpy(n, starts, lengths, offsets, sounds_flat, filepath, sr):
        """Memmap-backed numpy path - no extra dependencies."""
        log.info("Audio backend: NumPy (memmap fallback)")

        _mmap_path = filepath + ".mixtmp"
        mix = np.memmap(_mmap_path, dtype=np.float32, mode="w+",
                        shape=(n,))
        try:
            peak = 0.0
            for i in range(len(starts)):
                s  = int(starts[i])
                ln = int(lengths[i])
                o  = int(offsets[i])
                mix[s:s + ln] += sounds_flat[o:o + ln]
                rp = float(np.max(np.abs(mix[s:s + ln])))
                if rp > peak:
                    peak = rp
            del sounds_flat

            norm = (32767 * 10 ** (-1.5 / 20)) / peak if peak > 0 else 1.0

            CHUNK = 10 * sr
            with wave.open(filepath, "w") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sr)
                for cs in range(0, n, CHUNK):
                    ce = min(cs + CHUNK, n)
                    pcm = np.clip(
                        mix[cs:ce] * norm, -32768, 32767,
                    ).astype(np.int16)
                    wf.writeframes(pcm.tobytes())
        finally:
            del mix
            try:
                os.remove(_mmap_path)
            except OSError:
                pass



# =====================================================================
# Keyboard Overlay
# =====================================================================

_US_SHIFT_MAP: Dict[str, str] = {
    "~": "`", "!": "1", "@": "2", "#": "3", "$": "4", "%": "5",
    "^": "6", "&": "7", "*": "8", "(": "9", ")": "0",
    "_": "-", "+": "=", "{": "[", "}": "]", "|": "\\",
    ":": ";", '"': "'", "<": ",", ">": ".", "?": "/",
}

_QWERTY_ROWS = [
    [("`",1),("1",1),("2",1),("3",1),("4",1),("5",1),("6",1),("7",1),("8",1),("9",1),("0",1),("-",1),("=",1),("Bksp",2)],
    [("Tab",1.5),("Q",1),("W",1),("E",1),("R",1),("T",1),("Y",1),("U",1),("I",1),("O",1),("P",1),("[",1),("]",1),("\\",1.5)],
    [("Caps",1.75),("A",1),("S",1),("D",1),("F",1),("G",1),("H",1),("J",1),("K",1),("L",1),(";",1),("'",1),("Enter",2.25)],
    [("Shift",2.25),("Z",1),("X",1),("C",1),("V",1),("B",1),("N",1),("M",1),(",",1),(".",1),("/",1),("Shift",2.75)],
    [("Ctrl",1.25),("Win",1.25),("Alt",1.25),("",6.25),("Alt",1.25),("Fn",1.25),("Menu",1.25),("Ctrl",1.25)],
]

_AZERTY_ROWS = [
    [("²",1),("&",1),("é",1),('"',1),("'",1),("(",1),("-",1),("è",1),("_",1),("ç",1),("à",1),(")",1),("=",1),("Bksp",2)],
    [("Tab",1.5),("A",1),("Z",1),("E",1),("R",1),("T",1),("Y",1),("U",1),("I",1),("O",1),("P",1),("^",1),("$",1),("*",1.5)],
    [("Caps",1.75),("Q",1),("S",1),("D",1),("F",1),("G",1),("H",1),("J",1),("K",1),("L",1),("M",1),("ù",1),("Enter",2.25)],
    [("Shift",2.25),("<",1),("W",1),("X",1),("C",1),("V",1),("B",1),("N",1),(",",1),(";",1),(":",1),("!",1),("Shift",2.75)],
    [("Ctrl",1.25),("Win",1.25),("Alt",1.25),("",6.25),("Alt",1.25),("Fn",1.25),("Menu",1.25),("Ctrl",1.25)],
]

_QWERTZ_ROWS = [
    [("^",1),("1",1),("2",1),("3",1),("4",1),("5",1),("6",1),("7",1),("8",1),("9",1),("0",1),("ß",1),("´",1),("Bksp",2)],
    [("Tab",1.5),("Q",1),("W",1),("E",1),("R",1),("T",1),("Z",1),("U",1),("I",1),("O",1),("P",1),("Ü",1),("Ö",1),("Ä",1),("#",1.5)],
    [("Caps",1.75),("A",1),("S",1),("D",1),("F",1),("G",1),("H",1),("J",1),("K",1),("L",1),("Ö",1),("Ä",1),("€",1),("Enter",2.25)],
    [("Shift",2.25),("<",1),("Y",1),("X",1),("C",1),("V",1),("B",1),("N",1),("M",1),(",",1),(".",1),("-",1),("Shift",2.75)],
    [("Ctrl",1.25),("Win",1.25),("Alt",1.25),("",6.25),("AltGr",1.25),("Fn",1.25),("Menu",1.25),("Ctrl",1.25)],
]

_DVORAK_ROWS = [
    [("`",1),("1",1),("2",1),("3",1),("4",1),("5",1),("6",1),("7",1),("8",1),("9",1),("0",1),("[",1),("]",1),("Bksp",2)],
    [("Tab",1.5),("'",1),(",",1),(".",1),("P",1),("Y",1),("F",1),("G",1),("C",1),("R",1),("L",1),("/",1),("=",1),("\\",1.5)],
    [("Caps",1.75),("A",1),("O",1),("E",1),("U",1),("I",1),("D",1),("H",1),("T",1),("N",1),("S",1),("-",1),("Enter",2.25)],
    [("Shift",2.25),(";",1),("Q",1),("J",1),("K",1),("X",1),("B",1),("M",1),("W",1),("V",1),("Z",1),("Shift",2.75)],
    [("Ctrl",1.25),("Win",1.25),("Alt",1.25),("",6.25),("Alt",1.25),("Fn",1.25),("Menu",1.25),("Ctrl",1.25)],
]

_COLEMAK_ROWS = [
    [("`",1),("1",1),("2",1),("3",1),("4",1),("5",1),("6",1),("7",1),("8",1),("9",1),("0",1),("-",1),("=",1),("Bksp",2)],
    [("Tab",1.5),("Q",1),("W",1),("F",1),("P",1),("G",1),("J",1),("L",1),("U",1),("Y",1),(";",1),("[",1),("]",1),("\\",1.5)],
    [("Bksp",1.75),("A",1),("R",1),("S",1),("T",1),("D",1),("H",1),("N",1),("E",1),("I",1),("O",1),("'",1),("Enter",2.25)],
    [("Shift",2.25),("Z",1),("X",1),("C",1),("V",1),("B",1),("K",1),("M",1),(",",1),(".",1),("/",1),("Shift",2.75)],
    [("Ctrl",1.25),("Win",1.25),("Alt",1.25),("",6.25),("Alt",1.25),("Fn",1.25),("Menu",1.25),("Ctrl",1.25)],
]

# JIS (Japanese) - 109-key layout with extra keys and smaller space bar
_JIS_ROWS = [
    # Half-width mode labels (JIS keyboard physically used for both)
    [("半",1),("1",1),("2",1),("3",1),("4",1),("5",1),("6",1),("7",1),("8",1),("9",1),("0",1),("-",1),("^",1),("¥",1),("Bksp",2)],
    [("Tab",1.5),("Q",1),("W",1),("E",1),("R",1),("T",1),("Y",1),("U",1),("I",1),("O",1),("P",1),("@",1),("[",1),("]",1),("\\",1.5)],
    [("Caps",1.75),("A",1),("S",1),("D",1),("F",1),("G",1),("H",1),("J",1),("K",1),("L",1),(";",1),(":",1),("Enter",2.25)],
    [("Shift",2.25),("Z",1),("X",1),("C",1),("V",1),("B",1),("N",1),("M",1),(",",1),(".",1),("/",1),("_",1),("Shift",2.75)],
    [("Ctrl",1.25),("Win",1.25),("Alt",1.25),("無",1),("",4.25),("変",1.25),("Alt",1.25),("Fn",1.25),("Ctrl",1.25)],
]

_JIS_SHIFT_MAP: Dict[str, str] = {
    "~": "`", "!": "1", '"': "2", "#": "3", "$": "4", "%": "5",
    "&": "6", "'": "7", "(": "8", ")": "9", "=": "0",
    "|": "-", "+": "^", "`": "@", "{": "[", "}": "]",
    ":": ";", "*": ":", "<": ",", ">": ".", "?": "/",
}

# Chinese (Pinyin input) - Uses standard US QWERTY physical layout
# The labels show pinyin input method mode markings
_PINYIN_ROWS = [
    [("`",1),("1",1),("2",1),("3",1),("4",1),("5",1),("6",1),("7",1),("8",1),("9",1),("0",1),("-",1),("=",1),("Bksp",2)],
    [("Tab",1.5),("Q",1),("W",1),("E",1),("R",1),("T",1),("Y",1),("U",1),("I",1),("O",1),("P",1),("[",1),("]",1),("\\",1.5)],
    [("中",1.75),("A",1),("S",1),("D",1),("F",1),("G",1),("H",1),("J",1),("K",1),("L",1),(";",1),("'",1),("Enter",2.25)],
    [("Shift",2.25),("Z",1),("X",1),("C",1),("V",1),("B",1),("N",1),("M",1),(",",1),(".",1),("/",1),("Shift",2.75)],
    [("Ctrl",1.25),("Win",1.25),("Alt",1.25),("",6.25),("Alt",1.25),("Fn",1.25),("Menu",1.25),("Ctrl",1.25)],
]

# Turkish Q - Based on QWERTY with Turkish-specific characters
_TURKISH_Q_ROWS = [
    [('"',1),("1",1),("2",1),("3",1),("4",1),("5",1),("6",1),("7",1),("8",1),("9",1),("0",1),("*",1),("-",1),("Bksp",2)],
    [("Tab",1.5),("Q",1),("W",1),("E",1),("R",1),("T",1),("Y",1),("U",1),("I",1),("O",1),("P",1),("Ğ",1),("Ü",1),(";",1.5)],
    [("Caps",1.75),("A",1),("S",1),("D",1),("F",1),("G",1),("H",1),("J",1),("K",1),("L",1),("Ş",1),("İ",1),("Enter",2.25)],
    [("Shift",2.25),("<",1),("Z",1),("X",1),("C",1),("V",1),("B",1),("N",1),("M",1),("Ö",1),("Ç",1),(".",1),("Shift",2.75)],
    [("Ctrl",1.25),("Win",1.25),("Alt",1.25),("",6.25),("Alt",1.25),("Fn",1.25),("Menu",1.25),("Ctrl",1.25)],
]

_TURKISH_SHIFT_MAP: Dict[str, str] = {
    "é": '"', "!": "1", "'": "2", "^": "3", "+": "4", "%": "5",
    "&": "6", "/": "7", "(": "8", ")": "9", "=": "0", "?": "*",
    "_": "-", "\\": "-", ",": ";", "{": "Ğ", "}": "Ü",
    ":": "Ş", "[": "İ", "]": "Enter",
    "|": "<", ">": ".", "#": ".",
}

KEYBOARD_LAYOUTS: Dict[str, Dict] = {
    "QWERTY":   {"description": "Standard US QWERTY layout",   "rows": _QWERTY_ROWS,   "shift_map": _US_SHIFT_MAP},
    "AZERTY":   {"description": "French AZERTY layout",        "rows": _AZERTY_ROWS,   "shift_map": {}},
    "QWERTZ":   {"description": "German QWERTZ layout",       "rows": _QWERTZ_ROWS,   "shift_map": {}},
    "Dvorak":   {"description": "Dvorak ergonomic layout",     "rows": _DVORAK_ROWS,   "shift_map": _US_SHIFT_MAP},
    "Colemak":  {"description": "Colemak ergonomic layout",    "rows": _COLEMAK_ROWS,  "shift_map": _US_SHIFT_MAP},
    "JIS (Japanese)":  {"description": "Japanese JIS 109-key layout",      "rows": _JIS_ROWS,         "shift_map": _JIS_SHIFT_MAP},
    "Pinyin (Chinese)":{"description": "Chinese Pinyin input layout",       "rows": _PINYIN_ROWS,      "shift_map": _US_SHIFT_MAP},
    "Turkish Q":       {"description": "Turkish Q keyboard layout",         "rows": _TURKISH_Q_ROWS,   "shift_map": _TURKISH_SHIFT_MAP},
}


def _build_char_map(layout_name: str) -> Dict[str, Tuple[int, int]]:
    """Build a char -> (row, col) mapping from a keyboard layout (single pass)."""
    ld = KEYBOARD_LAYOUTS[layout_name]
    cm: Dict[str, Tuple[int, int]] = {}
    rows = ld["rows"]
    for ri, row in enumerate(rows):
        for ci, (label, _w) in enumerate(row):
            ll = label.lower()
            if len(label) == 1:
                cm[label] = (ri, ci)
                cm[label.lower()] = (ri, ci)
                cm[label.upper()] = (ri, ci)
            # Special keys
            if ll == "space" or (label == "" and _w >= 4):
                cm[" "] = (ri, ci)
            elif "enter" in ll:
                cm["\n"] = (ri, ci)
            elif "tab" in ll:
                cm["\t"] = (ri, ci)
            elif "bksp" in ll:
                cm["\x08"] = (ri, ci)
    # Shift-map: shifted symbol -> same physical key as base char
    for shifted, base in ld.get("shift_map", {}).items():
        if base in cm:
            cm[shifted] = cm[base]
    return cm


class KeyboardOverlay:
    """Draws a semi-transparent keyboard overlay at the bottom of a frame."""

    def __init__(
        self,
        video_w: int,
        video_h: int,
        layout_name: str = "QWERTY",
        theme: Optional[Dict[str, str]] = None,
        opacity: float = 0.82,
        max_height: Optional[int] = None,
        position: str = "bottom_center",
    ):
        self.video_w = video_w
        self.video_h = video_h
        self.layout_name = layout_name
        self.theme = theme
        self.opacity = opacity
        self.rows = KEYBOARD_LAYOUTS[layout_name]["rows"]
        self.char_map = _build_char_map(layout_name)
        self.num_rows = len(self.rows)
        self.position = position

        # Key dimensions  (scale to video size)
        self.key_unit = max(20, int(video_w * 0.028))
        self.key_gap  = max(2, self.key_unit // 14)
        self.key_h    = int(self.key_unit * 0.82)

        # If a max_height budget is given, shrink key_unit so the keyboard
        # (including internal gaps) fits within it.
        if max_height is not None and max_height > 0:
            natural_h = self.num_rows * self.key_h + (self.num_rows - 1) * self.key_gap
            if natural_h > max_height:
                # Solve for key_unit that makes natural_h == max_height
                # natural_h = num_rows * (unit * 0.82) + (num_rows-1) * max(2, unit//14)
                # Iteratively find the right unit
                lo, hi = 10, self.key_unit
                for _ in range(30):
                    mid = (lo + hi) / 2
                    test_gap = max(2, int(mid) // 14)
                    test_h = self.num_rows * int(mid * 0.82) + (self.num_rows - 1) * test_gap
                    if test_h > max_height:
                        hi = mid
                    else:
                        lo = mid
                self.key_unit = max(10, int(lo))
                self.key_gap  = max(2, self.key_unit // 14)
                self.key_h    = int(self.key_unit * 0.82)

        # Widest row in units
        self._max_units = max(sum(w for _, w in row) for row in self.rows)
        self._max_keys  = max(len(row) for row in self.rows)

        # Compute total keyboard pixel width from widest row
        self._kb_width = int(
            self._max_units * self.key_unit
            + (self._max_keys - 1) * self.key_gap
        )
        self._kb_height = int(
            len(self.rows) * self.key_h
            + (len(self.rows) - 1) * self.key_gap
        )

        # Initial position (may be overridden by reposition)
        self._kb_x = (video_w - self._kb_width) // 2
        self._kb_y = video_h - self._kb_height - max(8, video_h // 60)
        self._apply_position()

        # Pre-compute key rects
        self.key_rects: Dict[Tuple[int, int], QRect] = {}
        self._rebuild_key_rects()

    # ---- public helpers ------------------------------------------------

    def height_needed(self) -> int:
        """Pixel height consumed by the overlay (for shrinking code area)."""
        return self._kb_height + max(8, self.video_h // 60) + max(6, self.video_h // 90)

    def _apply_position(self):
        """Set _kb_x and _kb_y based on self.position."""
        margin = max(8, self.video_h // 60)
        vw, vh, kw, kh = self.video_w, self.video_h, self._kb_width, self._kb_height

        if self.position == "bottom_center":
            self._kb_x = (vw - kw) // 2
            self._kb_y = vh - kh - margin
        elif self.position == "bottom_right":
            self._kb_x = vw - kw - margin
            self._kb_y = vh - kh - margin
        elif self.position == "bottom_left":
            self._kb_x = margin
            self._kb_y = vh - kh - margin
        elif self.position == "top_center":
            self._kb_x = (vw - kw) // 2
            self._kb_y = margin
        elif self.position == "top_right":
            self._kb_x = vw - kw - margin
            self._kb_y = margin
        elif self.position == "top_left":
            self._kb_x = margin
            self._kb_y = margin
        elif self.position == "center_left":
            self._kb_x = margin
            self._kb_y = (vh - kh) // 2
        elif self.position == "center_right":
            self._kb_x = vw - kw - margin
            self._kb_y = (vh - kh) // 2

    def _rebuild_key_rects(self):
        """Rebuild key rects from current _kb_x, _kb_y."""
        self.key_rects: Dict[Tuple[int, int], QRect] = {}
        for ri, row in enumerate(self.rows):
            x = self._kb_x
            for ci, (_label, w) in enumerate(row):
                kw = int(w * self.key_unit) - self.key_gap
                y = self._kb_y + ri * (self.key_h + self.key_gap)
                self.key_rects[(ri, ci)] = QRect(x, y, kw, self.key_h)
                x += int(w * self.key_unit)

    def set_position(self, position: str):
        """Change position and rebuild layout."""
        self.position = position
        self._apply_position()
        self._rebuild_key_rects()

    def reposition(self, y_below: int):
        """Move the keyboard so its top sits at *y_below*, respecting position anchor."""
        margin = max(8, self.video_h // 60)
        if "bottom" in self.position:
            self._kb_y = y_below
        elif "top" in self.position:
            self._kb_y = margin
        else:  # center_left / center_right - keep vertically centered
            self._kb_y = (self.video_h - self._kb_height) // 2
        self._rebuild_key_rects()

    def resolve_key(self, ch: str) -> Optional[Tuple[int, int]]:
        return self.char_map.get(ch)

    # ---- drawing -------------------------------------------------------

    def draw(self, painter: QPainter, active_key: Optional[Tuple[int, int]] = None,
             flash: float = 0.0):
        """Draw the full keyboard overlay. *flash* is 0-1 intensity for the highlight."""
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        th = self.theme or THEMES["Dracula"]
        radius = max(3, self.key_unit // 8)

        # Opaque solid background behind the keyboard
        bg = QColor(th["background"])
        painter.setPen(QPen(QColor(th["window_border"]), max(1, self.key_unit // 20)))
        painter.setBrush(bg)
        pad = max(6, self.key_unit // 4)
        painter.drawRoundedRect(
            self._kb_x - pad, self._kb_y - pad,
            self._kb_width + 2 * pad, self._kb_height + 2 * pad,
            radius * 2, radius * 2,
        )

        # Opaque key colours
        key_bg    = QColor(th["title_bar"])
        key_border = QColor(th["window_border"])
        label_color = QColor(th["foreground"])
        mod_color   = QColor(th["line_number"])

        # Highlight colour (use cursor colour from theme)
        try:
            hl_base = QColor(th["cursor"])
        except Exception:
            hl_base = QColor("#89b4fa")

        # Pre-compute highlighted key fill (avoid per-key allocation)
        if flash > 0 and active_key is not None:
            hl_key_fill = QColor(
                int(key_bg.red()   + (hl_base.red()   - key_bg.red())   * flash),
                int(key_bg.green() + (hl_base.green() - key_bg.green()) * flash),
                int(key_bg.blue()  + (hl_base.blue()  - key_bg.blue())  * flash),
            )
            hl_glow = QColor(hl_base)
            hl_glow.setAlpha(int(60 * flash))
            hl_expand = max(3, int(self.key_unit * 0.12 * flash))
        else:
            hl_key_fill = None

        for (ri, ci), rect in self.key_rects.items():
            label = self.rows[ri][ci][0]
            is_active = (active_key is not None and active_key == (ri, ci))

            # --- key background ---
            if is_active and hl_key_fill is not None:
                # Glow behind the active key
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(hl_glow)
                painter.drawRoundedRect(
                    rect.adjusted(-hl_expand, -hl_expand, hl_expand, hl_expand),
                    radius, radius,
                )
                painter.setBrush(hl_key_fill)
            else:
                painter.setBrush(key_bg)

            painter.setPen(key_border)
            painter.drawRoundedRect(rect, radius, radius)

            # --- label ---
            if label:
                is_mod = len(label) > 1 or label in {
                    "²", "^", "¨", "´", "ß", "Ü", "Ö", "Ä", "€", "ù",
                    "é", "è", "ç", "à", "æ", "Ğ", "Ş", "İ", "Ö", "Ç",
                    "¥", "@", "_", ":", "*", ";", "<", ">",
                    "半", "無", "変", "中",
                }
                painter.setPen(mod_color if is_mod else label_color)
                fsize = max(7, int(self.key_unit * 0.30))
                painter.setFont(QFont("Segoe UI", fsize))
                if label == "":
                    pass
                else:
                    painter.drawText(rect, Qt.AlignCenter, label)

        painter.restore()


# =====================================================================
# Typing Animator (simplified)
# =====================================================================

Event = Tuple[float, int, str]  # (timestamp, display_index, char)

_QWERTY_KEY_ROWS = (
    "`1234567890-=",
    "qwertyuiop[]\\",
    "asdfghjkl;'",
    "zxcvbnm,./",
)
_QWERTY_KEY_POS: Dict[str, Tuple[int, int]] = {}
for _r, _row in enumerate(_QWERTY_KEY_ROWS):
    for _c, _ch in enumerate(_row):
        _QWERTY_KEY_POS[_ch] = (_r, _c)
for _ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    _QWERTY_KEY_POS[_ch] = _QWERTY_KEY_POS.get(_ch.lower(), (2, 0))


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
                pa = _QWERTY_KEY_POS.get(prev.lower())
                pb = _QWERTY_KEY_POS.get(ch.lower())
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

    def active_key_at(
        self, t: float, flash_duration: float = 0.18,
    ) -> Tuple[Optional[str], float]:
        """Return (active_char, key_flash) for keyboard overlay at time *t*.

        Reusable by VideoExporter, LayoutPreviewDialog, and MainWindow
        instead of duplicating the bisect+dt logic in three places.
        """
        if not self._timestamps:
            return (None, 0.0)
        idx = bisect.bisect_right(self._timestamps, t)
        if idx == 0:
            return (None, 0.0)
        char = self.timeline[idx - 1][2]
        dt = t - self.timeline[idx - 1][0]
        if dt < flash_duration:
            return (char, max(0.0, 1.0 - dt / flash_duration))
        return (None, 0.0)


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
        padding: int = 24,
        tab_size: int = 4,
        title_text: str = "main.py",
        language: str = "Python",
        keyboard_overlay: Optional["KeyboardOverlay"] = None,
        bg_image_path: Optional[str] = None,
        total_code_lines: int = 0,
    ):
        """
        """
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
        self.keyboard_overlay = keyboard_overlay
        self.total_code_lines = total_code_lines

        # Font fallback chain: try requested family, then common monospace fonts
        # Also include emoji-capable fonts so characters like ✅ render correctly.
        self.font_family = font_family
        _MONO_FALLBACKS = ["Consolas", "JetBrains Mono", "DejaVu Sans Mono",
                            "Liberation Mono", "Courier New", "monospace"]
        _families_to_try = [font_family] + [f for f in _MONO_FALLBACKS if f != font_family]
        _available = QFontDatabase.families()
        chosen = "monospace"
        for family in _families_to_try:
            if family in _available:
                chosen = family
                break

        # Build a font family list that includes emoji-capable fallbacks.
        # QFont.setFamilies() tells Qt to try each family in order when
        # a glyph is missing from the primary font.
        _emoji_fallbacks = [
            "Noto Color Emoji", "Apple Color Emoji", "Segoe UI Emoji",
            "Twemoji Mozilla", "Android Emoji",
        ]
        _font_families = [chosen]
        for ef in _emoji_fallbacks:
            if ef in _available and ef != chosen:
                _font_families.append(ef)
        # Always keep a generic sans-serif as the last resort
        if "sans-serif" not in _font_families:
            _font_families.append("sans-serif")

        self.font = QFont(chosen, font_size)
        self.font.setFamilies(_font_families)
        self.font.setFixedPitch(True)
        self.fm = QFontMetrics(self.font)
        self.char_w = self.fm.horizontalAdvance("M")
        self.line_h = self.fm.height()

        # Pre-convert theme colours to QColor once
        self._qcolors: Dict[str, QColor] = {}
        for key, val in self.theme.items():
            if isinstance(val, str) and val.startswith("#"):
                self._qcolors[key] = QColor(val)
        self._qc_fg = self._qcolors.get("foreground", QColor("#f8f8f2"))
        self._qc_ln = self._qcolors.get("line_number", QColor("#6272a4"))
        self._qc_ln_active = QColor(self._qc_fg).darker(120)
        self._qc_cursor = self._qcolors.get("cursor", QColor("#f8f8f2"))
        self._qc_current_line = self._qcolors.get(
            "current_line", QColor("#44475a")
        )

        # Background image
        self.bg_image: Optional[QPixmap] = None
        if bg_image_path and os.path.exists(bg_image_path):
            self.bg_image = QPixmap(bg_image_path)

        self._build_bg_cache()

        # Backspace / typo resolution cache
        self._cached_display_chars_id: int = 0
        self._cached_display_chars_len: int = 0
        self._cached_resolved: str = ""
        self._cached_resolved_colors: List[str] = []
        self._cached_is_clean: List[bool] = []
        self._cached_stack_len: List[int] = []
        self._cached_resolved_color_qc: List[QColor] = []

        # Dirty-state (typo/backspace) tokenization cache
        self._dirty_num_visible: int = -1
        self._dirty_vis_color_qc: List[QColor] = []
        self._dirty_visible_text: str = ""

        # Frame-level layout cache: split lines, line offsets, cursor_line.
        # Invalidated when num_visible changes (which changes visible_text).
        self._layout_nv: int = -1
        self._layout_lines: List[str] = []
        self._layout_offsets: List[int] = []
        self._layout_cursor_line: int = 0

        # Per-line x-position layout cache (FIFO eviction)
        self._LINE_CACHE_MAX = 512
        self._line_layout_cache: "OrderedDict[str, Tuple[List[int], int]]" = OrderedDict()
        self._tab_advance = self.char_w * self.tab_size

    def set_background_image(self, path: Optional[str]):
        """Set (or clear) the background image and rebuild the cache."""
        if path and os.path.exists(path):
            self.bg_image = QPixmap(path)
        else:
            self.bg_image = None
        self._build_bg_cache()

    def _draw_bg(self, p: QPainter):
        """Fill the frame background - image or gradient."""
        if self.bg_image:
            scaled = self.bg_image.scaled(
                self.width, self.height,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (self.width - scaled.width()) // 2
            y = (self.height - scaled.height()) // 2
            p.drawPixmap(x, y, scaled)
        else:
            bg = self._qcolors.get("background", QColor("#282a36"))
            g = QLinearGradient(0, 0, 0, self.height)
            g.setColorAt(0, bg.lighter(105))
            g.setColorAt(1, bg)
            p.fillRect(0, 0, self.width, self.height, g)

    def _build_bg_cache(self):
        """Pre-render the static background + window chrome."""
        self._bg = QImage(self.width, self.height, QImage.Format_RGB32)
        self._bg.fill(QColor(self.theme["background"]))
        p = QPainter(self._bg)
        p.setRenderHint(QPainter.Antialiasing)

        # Layer the background (image or gradient) behind the window chrome
        p.save()
        self._draw_bg(p)
        p.restore()

        w, h = self.width, self.height
        pad = self.padding
        chrome_h = 42 if self.show_window_chrome else 0

        # Keyboard overlay reservation - keyboard gets up to 1/3, code gets ALL the rest
        kb_reserve = 0
        if self.keyboard_overlay:
            available_v = h - 2 * pad
            kb_budget = available_v // 3
            kb_reserve = min(self.keyboard_overlay.height_needed(), kb_budget)

        # Window area (fills everything the keyboard doesn't use)
        wx = pad
        wy = pad
        ww = w - 2 * pad
        wh = h - 2 * pad - kb_reserve

        # Window border - with drop shadow
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 60))
        p.drawRoundedRect(wx + 4, wy + 4, ww, wh, 12, 12)
        p.setPen(QColor(self.theme["window_border"]))
        p.setBrush(QColor(self.theme["background"]))
        r = 12
        p.drawRoundedRect(wx, wy, ww, wh, r, r)

        if self.show_window_chrome:
            # Title bar
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(self.theme["title_bar"]))
            p.drawRoundedRect(wx, wy, ww, chrome_h, r, r)
            # Cover bottom corners of title bar
            p.drawRect(wx, wy + chrome_h - r, ww, r)

            # Traffic lights with glyph icons
            btn_r = 7
            btn_y = wy + 19
            glyphs = {"button_close": "×", "button_min": "−", "button_max": "+"}
            glyph_colors = ["#ff5f56", "#ffbd2e", "#27c93f"]
            glyph_shadow = QColor(0, 0, 0, 100)
            glyph_font = QFont("Arial", 7, QFont.Weight.Bold)
            for i, color in enumerate(glyph_colors):
                cx = wx + 20 + i * 24
                p.setBrush(QColor(color))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QPoint(cx, btn_y), btn_r, btn_r)
                p.setPen(glyph_shadow)
                p.setFont(glyph_font)
                p.drawText(
                    QRect(cx - btn_r, btn_y - btn_r, btn_r * 2, btn_r * 2),
                    Qt.AlignmentFlag.AlignCenter,
                    glyphs[["button_close", "button_min", "button_max"][i]],
                )

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
            wx + 4, code_top, ww - 8, wh - (code_top - wy)
        )

        # Reposition keyboard to sit directly below the code window
        if self.keyboard_overlay:
            kb_bottom_margin = max(8, h // 60)
            kb_top = wy + wh + kb_bottom_margin
            self.keyboard_overlay.reposition(kb_top)

        p.end()

    @staticmethod
    def auto_font_size(
        code_lines: int, width: int, height: int,
        padding: int = 24, show_window_chrome: bool = True,
        show_line_numbers: bool = True, tab_size: int = 4,
        code: Optional[str] = None, font_family: str = "Consolas",
        keyboard_h: int = 0,
    ) -> int:
        """Compute the optimal font size using binary search for pixel-exact fit.

        The code rect dimensions must match _build_bg_cache exactly:
            rect_h = height - 2*padding - kb_used - chrome_h
            rect_w = width  - 2*padding - 8

        No bottom_margin is subtracted because render_frame now uses
        ceiling division + per-line pixel distribution to fill the
        code rect exactly.
        """
        chrome_h = 42 if show_window_chrome else 0

        # ── kb_used: same formula as _build_bg_cache ──
        if keyboard_h > 0:
            kb_budget = (height - 2 * padding) // 3
            kb_used = min(keyboard_h, kb_budget)
        else:
            kb_used = 0

        # ── exact code-rect dimensions ──
        rect_h = height - 2 * padding - kb_used - chrome_h
        rect_w = width  - 2 * padding - 8

        if rect_h < 20 or rect_w < 40 or code_lines < 1:
            log.info("[auto_font] rect too small or no lines → fallback 12px "
                     "(rect_h=%d rect_w=%d code_lines=%d)", rect_h, rect_w, code_lines)
            return 12

        # ── longest line (for width constraint) ──
        max_chars = 80
        if code:
            longest = max(
                len(line.replace("\t", " " * tab_size)) for line in code.split("\n")
            )
            max_chars = max(longest, 1)

        # ── helper: line-number width at a given font size ──
        def _ln_width(cw: int) -> int:
            return (len(str(code_lines)) * cw + 16) if show_line_numbers else 0

        # ── binary search: largest size where code_lines fit in rect_h ──
        #    condition: code_lines * fm.height() <= rect_h
        #    (no bottom_margin — render_frame distributes remainder pixels)
        v_lo, v_hi, v_best = 6, 80, 6
        while v_lo <= v_hi:
            mid = (v_lo + v_hi) // 2
            fm = QFontMetrics(QFont(font_family, mid))
            if code_lines * fm.height() <= rect_h:
                v_best = mid
                v_lo = mid + 1
            else:
                v_hi = mid - 1

        best = max(6, min(int(v_best), 72))
        fm_best = QFontMetrics(QFont(font_family, best))
        lh = fm_best.height()
        max_vis = -(-rect_h // lh)  # ceiling div
        total_px = max_vis * lh
        gap = rect_h - total_px    # negative → last line clips by |gap| px
        log.info(
            "[auto_font] font=%s best=%dpx  line_h=%d  rect_h=%d  "
            "max_vis=%dL  total_px=%d  gap=%dpx  code_lines=%d  "
            "rect_w=%d  max_chars=%d",
            font_family, best, lh, rect_h,
            max_vis, total_px, gap, code_lines,
            rect_w, max_chars,
        )
        return best

    @staticmethod
    def _resolve_backspaces(chars: List[str]) -> str:
        """Process ``\\b`` characters to produce the final visible string."""
        out: List[str] = []
        for ch in chars:
            if ch == "\b":
                if out:
                    out.pop()
            else:
                out.append(ch)
        return "".join(out)

    @staticmethod
    def _precompute_clean(
        display_chars: List[str], resolved: str,
    ) -> Tuple[List[bool], List[int]]:
        """Precompute ``is_clean[]`` and ``stack_len[]`` tables.

        ``is_clean[i]`` is True iff processing ``display_chars[:i]``
        yields a string that is a prefix of ``resolved`` (i.e. no
        unresolved typo is currently on screen).

        ``stack_len[i]`` is the length of the visible string after
        processing ``display_chars[:i]``.
        """
        n = len(display_chars)
        is_clean: List[bool] = [True] * (n + 1)
        stack_len: List[int] = [0] * (n + 1)
        stack: List[Tuple[str, bool]] = []
        incorrect = 0
        rlen = len(resolved)

        for i in range(n):
            ch = display_chars[i]
            if ch == "\b":
                if stack:
                    _, was_correct = stack.pop()
                    if not was_correct:
                        incorrect -= 1
            else:
                pos = len(stack)
                was_correct = pos < rlen and ch == resolved[pos]
                stack.append((ch, was_correct))
                if not was_correct:
                    incorrect += 1
            is_clean[i + 1] = (incorrect == 0)
            stack_len[i + 1] = len(stack)

        return is_clean, stack_len

    def _get_cache(
        self, full_text: List[str],
    ) -> Tuple[str, List[str], List[QColor], List[bool], List[int]]:
        """Return (resolved, resolved_colors, color_qc, is_clean, stack_len).

        Recomputes only when *full_text* is a different list object
        (compared by ``id()`` and length) than the one currently cached.
        This avoids redundant work on every frame when the char list
        hasn't changed between ticks.
        """
        cid = id(full_text)
        clen = len(full_text)
        if cid != self._cached_display_chars_id or clen != self._cached_display_chars_len:
            resolved = self._resolve_backspaces(full_text)
            self._cached_resolved = resolved
            self._cached_resolved_colors = self._tokenize_to_colors(resolved)
            # Pre-convert to QColor once
            fg = self._qc_fg
            qc = self._qcolors
            self._cached_resolved_color_qc = [
                qc.get(ck, fg) for ck in self._cached_resolved_colors
            ]
            self._cached_is_clean, self._cached_stack_len = (
                self._precompute_clean(full_text, resolved)
            )
            self._cached_display_chars_id = cid
            self._cached_display_chars_len = clen
            self._dirty_num_visible = -1  # invalidate dirty cache

        return (
            self._cached_resolved,
            self._cached_resolved_colors,
            self._cached_resolved_color_qc,
            self._cached_is_clean,
            self._cached_stack_len,
        )

    def _get_line_layout(self, line: str, x0: int) -> Tuple[List[int], int]:
        """Return (char_x_positions[], total_width) for *line*.

        *x0* is the pixel x-coordinate where the first character starts.
        Results are cached in an OrderedDict with FIFO eviction (max 512
        unique lines).  Uses actual ``horizontalAdvance`` per character
        instead of a fixed ``char_w`` assumption, so CJK / ligature /
        non-monospace glyphs are positioned accurately.
        """
        # Cache key includes x0 so different layouts don't collide
        cache_key = (line, x0)
        cached = self._line_layout_cache.get(cache_key)
        if cached is not None:
            return cached
        char_x: List[int] = []
        x = x0
        tab = self._tab_advance
        ham = self.fm.horizontalAdvance
        for ch in line:
            char_x.append(x)
            x += tab if ch == "\t" else ham(ch)
        result = (char_x, x)
        if len(self._line_layout_cache) >= self._LINE_CACHE_MAX:
            self._line_layout_cache.popitem(last=False)  # FIFO evict
        self._line_layout_cache[cache_key] = result
        return result

    def _tokenize_to_colors(self, text: str) -> List[str]:
        """Tokenise *text* once and return a per-char colour-key list."""
        tokens = Tokenizer.tokenize(text, self.language)
        colors: List[str] = ["foreground"] * len(text)
        pos = 0
        get = self.TOKEN_COLOR_MAP.get
        n = len(colors)
        for ttype, ttxt in tokens:
            ckey = get(ttype, "foreground")
            end = min(pos + len(ttxt), n)
            colors[pos:end] = [ckey] * (end - pos)
            pos = end
        return colors

    def render_frame(
        self,
        display_chars: List[str],
        num_visible: int,
        cursor_visible: bool = True,
        target: Optional[QImage] = None,
        active_char: Optional[str] = None,
        key_flash: float = 0.0,
    ) -> QImage:
        img = target if target is not None else QImage(
            self.width, self.height, QImage.Format_RGB32
        )
        if target is None:
            img.fill(QColor(self.theme["background"]))

        p = QPainter(img)
        # Antialiasing off: only rects are drawn (caret, line highlight) which
        # don't benefit from AA.  TextAntialiasing is kept for crisp text.
        p.setRenderHint(QPainter.TextAntialiasing)

        # Blit cached background
        p.drawImage(0, 0, self._bg)

        cr = self._code_rect

        # --- Resolve backspaces & pick visible text via cache ---
        resolved, resolved_colors, resolved_color_qc, is_clean, stack_len = (
            self._get_cache(display_chars)
        )

        # Determine how many characters of the *resolved* (final) text
        # are visible.  If the current num_visible is a "clean" point
        # (no typo on screen), we can slice the already-tokenized
        # resolved text directly - no re-tokenization needed.
        if 0 <= num_visible < len(is_clean) and is_clean[num_visible]:
            vl = stack_len[num_visible]
            visible_text = resolved[:vl]
            vis_color_qc = resolved_color_qc[:vl]
        else:
            # Dirty state: a typo or backspace is in progress.
            # Cache the re-tokenization result keyed on num_visible.
            if num_visible != self._dirty_num_visible:
                dirty_chars = display_chars[:num_visible]
                self._dirty_visible_text = self._resolve_backspaces(dirty_chars)
                dirty_colors = self._tokenize_to_colors(self._dirty_visible_text)
                fg = self._qc_fg
                qc = self._qcolors
                self._dirty_vis_color_qc = [qc.get(ck, fg) for ck in dirty_colors]
                self._dirty_num_visible = num_visible
            visible_text = self._dirty_visible_text
            vis_color_qc = self._dirty_vis_color_qc

        # --- Resolve visible lines via cache ---
        if num_visible != self._layout_nv:
            self._layout_lines = visible_text.split("\n")
            # Pre-compute line start offsets in visible_text
            offsets: List[int] = []
            off = 0
            for ln in self._layout_lines:
                offsets.append(off)
                off += len(ln) + 1
            self._layout_offsets = offsets
            self._layout_cursor_line = visible_text.count("\n")
            self._layout_nv = num_visible

        lines = self._layout_lines
        line_offsets = self._layout_offsets
        cursor_line = self._layout_cursor_line

        # --- Compute effective line height ---
        total_lines = len(lines)
        cr_h = cr.height()
        cr_top = cr.top()

        # STEP 1 - max_vis: number of lines that fit in cr_h.
        # We use ceiling division so the viewport is always filled to the
        # bottom edge.  Any sub-pixel remainder is distributed evenly
        # across all lines so nothing overflows the code rect.
        max_vis = max(1, -(-cr_h // self.line_h))

        # STEP 2 - distribute remaining pixels evenly across lines
        # so that max_vis lines exactly fill cr_h (no gap, no overflow).
        lh_base = self.line_h
        total_used = max_vis * lh_base
        remainder = cr_h - total_used          # always >= 0
        lh_extra = 0
        if remainder > 0 and max_vis > 0:
            # Distribute: first `remainder` lines get +1px each.
            # This keeps text baseline-stable for the majority of lines.
            lh_extra = 1

        log.debug(
            "[render_frame] cr_h=%d  line_h=%d  max_vis=%d  "
            "total_used=%d  remainder=%d  lh_extra=%d  "
            "total_lines=%d  cursor_line=%d  "
            "font=%s %dpx",
            cr_h, lh_base, max_vis,
            total_used, remainder, lh_extra,
            total_lines, cursor_line,
            self.font_family, self.font_size,
        )

        # STEP 3 - smart cursor-following scroll (works for both modes).
        # Scrolling only begins when the cursor line exceeds the last
        # fully visible slot minus the bottom margin.
        scroll_margin_top = 3
        scroll_margin_bottom = min(5, max_vis - 1)
        scroll = 0
        if cursor_line >= scroll + max_vis - scroll_margin_bottom:
            scroll = max(0, cursor_line - max_vis + scroll_margin_bottom + 1)
        if cursor_line < scroll + scroll_margin_top:
            scroll = max(0, cursor_line - scroll_margin_top)

        # Clamp scroll so the last page always fills the viewport.
        # Without this, when the file ends the remaining lines sit at the
        # top and a gap appears at the bottom.
        max_scroll = max(0, total_lines - max_vis)
        if scroll > max_scroll:
            scroll = max_scroll

        # Line number width
        ln_width = 0
        if self.show_line_numbers:
            ln_width = len(str(total_lines + scroll)) * self.char_w + 16

        # Map cursor to screen coordinates
        current_scroll_line = cursor_line - scroll

        # STEP 4 - build per-slot Y positions and heights.
        # The first `remainder` slots each get lh_base+1 so that the
        # total height of all max_vis slots equals cr_h exactly.
        line_y_arr: List[int] = []
        line_h_arr: List[int] = []
        y_acc = cr_top
        for si in range(max_vis):
            li = scroll + si
            if li >= total_lines:
                break
            lh = lh_base + (lh_extra if si < remainder else 0)
            line_y_arr.append(y_acc)
            line_h_arr.append(lh)
            y_acc += lh
        n_drawn = len(line_y_arr)

        # Highlight current line
        if 0 <= current_scroll_line < n_drawn:
            idx = current_scroll_line
            p.fillRect(cr.left(), line_y_arr[idx], cr.width(), line_h_arr[idx], self._qc_current_line)

        # Draw gutter separator line between line numbers and code
        if self.show_line_numbers and ln_width > 0:
            sep_x = cr.left() + ln_width
            sep_color = QColor(self._qc_ln)
            sep_color.setAlpha(60)
            p.setPen(QPen(sep_color, 1))
            p.drawLine(sep_x, cr.top(), sep_x, cr.top() + max_vis * lh_base)

        # Clip to code area
        p.setClipRect(cr)

        # --- Draw line numbers + code ---
        p.setFont(self.font)
        x0 = cr.left() + ln_width
        n_vis_chars = len(visible_text)
        fg = self._qc_fg

        for si in range(n_drawn):
            li = scroll + si
            lh = line_h_arr[si]
            y = line_y_arr[si]
            global_off = line_offsets[li]

            # Line number
            if self.show_line_numbers:
                p.setPen(
                    self._qc_ln_active if li == cursor_line else self._qc_ln
                )
                p.drawText(
                    QRect(cr.left(), y, ln_width, lh),
                    Qt.AlignRight | Qt.AlignVCenter,
                    str(li + 1),
                )

            line = lines[li]

            if not line:
                if cursor_visible and li == cursor_line:
                    caret_h = max(4, lh - 10)
                    self._draw_caret(p, int(x0), int(y + lh * 0.18), caret_h)
                continue

            # --- Cached x-position layout + RLE colour draw ---
            char_x, _ = self._get_line_layout(line, x0)

            cur_qc = vis_color_qc[global_off] if global_off < n_vis_chars else fg
            run_start = 0
            for j in range(1, len(line) + 1):
                next_qc = fg
                if j < len(line):
                    gp = global_off + j
                    next_qc = vis_color_qc[gp] if gp < n_vis_chars else fg
                if j == len(line) or next_qc is not cur_qc:
                    run_text = line[run_start:j].replace(
                        "\t", " " * self.tab_size
                    )
                    p.setPen(cur_qc)
                    p.drawText(
                        QPoint(int(char_x[run_start]),
                               int(y + lh * 0.78)),
                        run_text,
                    )
                    cur_qc = next_qc
                    run_start = j

            # Cursor
            if cursor_visible and li == cursor_line:
                n_ch = len(line)
                if n_ch < len(char_x):
                    cx = char_x[n_ch]
                else:
                    last_x = char_x[-1] if char_x else x0
                    if line and line[-1] == "\t":
                        cx = last_x + self._tab_advance
                    elif line:
                        cx = last_x + self.fm.horizontalAdvance(line[-1])
                    else:
                        cx = last_x
                caret_h = max(4, lh - 10)
                self._draw_caret(p, int(cx), int(y + lh * 0.18), caret_h)

        p.setClipping(False)

        # Keyboard overlay
        if self.keyboard_overlay:
            ak = None
            kf = 0.0
            if active_char is not None and key_flash > 0:
                ak = self.keyboard_overlay.resolve_key(active_char)
                kf = key_flash
            self.keyboard_overlay.draw(p, active_key=ak, flash=kf)

        p.end()
        return img

    def _draw_caret(self, p: QPainter, x: int, y: int, h: Optional[int] = None):
        """Draw the text cursor (caret) as a thin filled rect."""
        w = max(2, self.font_size // 10)
        caret_h = h if h is not None else self.line_h - 10
        p.fillRect(x, y, w, caret_h, self._qc_cursor)


# =====================================================================
# FFmpeg Video Exporter
# =====================================================================

def _format_eta(seconds: float) -> str:
    """Format a number of seconds into a human-readable ETA string.

    Returns e.g. ``"1m 23s"``, ``"45s"``, or ``"< 1s"``.
    """
    if seconds < 1:
        return "< 1s"
    if seconds < 60:
        return f"{int(seconds)}s"
    minutes = int(seconds) // 60
    secs = int(seconds) % 60
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m {secs}s"


class VideoExporter(QThread):
    """Render frames and pipe them to FFmpeg."""

    progress = Signal(int)
    status = Signal(str)
    finished_ok = Signal(str)
    error = Signal(str)

    # Number of frames to buffer in the writer queue before the render thread blocks.
    # This allows pipeline parallelism: while FFmpeg encodes frame N, we render frame N+K.
    # Larger queue = better pipelining (no GPU VRAM concern anymore).
    _WRITE_QUEUE_SIZE = 24

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
        # Double-buffer: two pre-allocated numpy arrays so we can keep the
        # previous frame's bytes alive without copying.
        self._raw_bufs = [
            np.empty((renderer.height, renderer.width, 3), dtype=np.uint8),
            np.empty((renderer.height, renderer.width, 3), dtype=np.uint8),
        ]
        self._buf_idx = 0

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

            log.info(
                "Exporting %d frames (%.1fs @ %d fps) -> %s",
                n_frames, total, self.fps, os.path.basename(self.output),
            )

            self.status.emit("Generating audio...")
            has_audio = False
            if self.sound_gen:
                t_audio = _time.perf_counter()
                self.sound_gen.generate_track(
                    self.animator.char_timestamps(), aud_path, self.volume
                )
                aud_elapsed = _time.perf_counter() - t_audio
                aud_size = os.path.getsize(aud_path) if os.path.exists(aud_path) else 0
                log.info(
                    "Audio generated in %.2fs (%.2f MB)",
                    aud_elapsed, aud_size / (1024 * 1024),
                )
                has_audio = aud_size > 44

            # Build FFmpeg command -- software only (libx264)
            cmd = [
                "ffmpeg", "-y",
                "-f", "rawvideo", "-pix_fmt", "rgb24",
                "-s", f"{w}x{h}", "-r", str(self.fps),
                "-i", "pipe:0",
            ]
            if has_audio:
                cmd += ["-i", aud_path]

            cmd += [
                "-c:v", "libx264",
                "-preset", "medium", "-crf", "18",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            ]

            if has_audio:
                cmd += ["-c:a", "aac", "-b:a", "192k"]
            cmd.append(self.output)

            log.info("FFmpeg cmd: %s", " ".join(cmd[:12]) + "...")

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

            export_start = _time.time()
            frame_render_total = 0.0
            dup_count = 0

            log.info(
                "Starting frame render + encode pipeline (%d frames @ %dx%d, "
                "write buffer=%d)...",
                n_frames, w, h, self._WRITE_QUEUE_SIZE,
            )

            # ---- Buffered writer thread for pipeline parallelism ----
            write_queue: deque = deque()
            write_lock = threading.Lock()
            write_cv = threading.Condition(write_lock)
            write_error: list = []
            writer_done = False

            def _writer_thread():
                """Drain write_queue and pipe each frame to FFmpeg stdin."""
                nonlocal writer_done
                try:
                    while True:
                        with write_lock:
                            while not write_queue and not writer_done:
                                write_cv.wait(timeout=0.5)
                            if not write_queue and writer_done:
                                break
                            frame_data = write_queue.popleft()
                        if frame_data is None:
                            break
                        proc.stdin.write(frame_data)
                except Exception as exc:
                    write_error.append(str(exc))
                finally:
                    try:
                        proc.stdin.close()
                    except (BrokenPipeError, OSError):
                        pass
                    writer_done = True
                    with write_lock:
                        write_cv.notify_all()

            writer_t = threading.Thread(target=_writer_thread, daemon=True)
            writer_t.start()

            # --- Duplicate frame detection ---
            # Track the render state that determines pixel output.
            # If state is identical to the previous frame, skip QPainter entirely.
            prev_state = None  # (num_visible, cursor_visible, active_char, key_flash)
            prev_frame_bytes = None  # numpy array (buffer protocol)

            for fi in range(n_frames):
                if self._cancel.is_set() or write_error:
                    log.info("Export cancelled at frame %d/%d.", fi, n_frames)
                    break

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

                # Determine active key for keyboard overlay
                active_char, key_flash = self.animator.active_key_at(t)

                # --- Duplicate frame detection ---
                # Quantise key_flash to avoid near-identical frames triggering re-renders.
                kf_rounded = round(key_flash, 2)
                frame_state = (nv, cur_vis, active_char, kf_rounded)

                if frame_state == prev_state and prev_frame_bytes is not None:
                    # Pixel-identical frame -- skip render, reuse bytes
                    dup_count += 1
                else:
                    rt0 = _time.perf_counter()
                    qimg = self.renderer.render_frame(
                        self.animator.display_chars, nv, cur_vis, target=scratch,
                        active_char=active_char, key_flash=key_flash,
                    )
                    frame_render_total += _time.perf_counter() - rt0
                    # Rotate double-buffer so the previous frame's data stays
                    # alive without a 6 MB bytes() copy.
                    self._buf_idx = 1 - self._buf_idx
                    raw = self._qimg_to_rgb(qimg, self._raw_bufs[self._buf_idx])
                    prev_frame_bytes = raw  # numpy array, supports buffer protocol
                    prev_state = frame_state

                # Enqueue frame bytes for the writer thread.
                with write_lock:
                    while len(write_queue) >= self._WRITE_QUEUE_SIZE:
                        write_cv.wait(timeout=0.1)
                    if self._cancel.is_set() or write_error:
                        break
                    write_queue.append(prev_frame_bytes)
                    write_cv.notify_all()

                if fi % max(1, n_frames // 20) == 0 and fi > 0:
                    pct = int((fi + 1) / n_frames * 100)
                    elapsed = _time.time() - export_start
                    eta = elapsed / (fi + 1) * (n_frames - fi - 1)
                    unique = fi + 1 - dup_count
                    log.info(
                        "Progress: %d%% (%d/%d frames, %d unique, %d dup, %.1fs elapsed, "
                        "ETA %s)",
                        pct, fi + 1, n_frames, unique, dup_count, elapsed,
                        _format_eta(eta),
                    )
                    self.progress.emit(pct)
                    self.status.emit(
                        f"Encoding... {pct}% (ETA: {_format_eta(eta)})"
                    )

            # Signal the writer thread that no more frames are coming
            if not self._cancel.is_set() and not write_error:
                with write_lock:
                    write_queue.append(None)  # sentinel
                    write_cv.notify_all()
            writer_t.join(timeout=600)

            # Check for writer thread errors
            if write_error:
                raise RuntimeError(f"FFmpeg write failed: {write_error[0]}")
            if self._cancel.is_set():
                proc.terminate()
                proc.wait(timeout=5)
                self.error.emit("Cancelled")
                return

            proc.wait(timeout=600)
            drain_t.join(timeout=5)

            if proc.returncode != 0:
                err = b"".join(stderr_chunks).decode(errors="ignore")[-600:]
                raise RuntimeError(f"FFmpeg failed (code {proc.returncode}): {err}")

            total_export_time = _time.time() - export_start
            unique_frames = n_frames - dup_count
            if n_frames > 0 and frame_render_total > 0:
                avg_ms = frame_render_total / unique_frames * 1000 if unique_frames > 0 else 0
                render_fps = unique_frames / frame_render_total if frame_render_total > 0 else 0
                log.info(
                    "Render stats: %d unique frames (skipped %d dups) in %.2fs render "
                    "(%.1f ms/frame, %.1f fps render throughput, %.1fs wall clock)",
                    unique_frames, dup_count, frame_render_total,
                    avg_ms, render_fps, total_export_time,
                )
                self.status.emit(
                    f"Rendered {unique_frames} unique frames ({dup_count} dups skipped) "
                    f"at {render_fps:.1f} fps ({avg_ms:.1f} ms/frame)"
                )

            self.progress.emit(100)
            self.status.emit(f"Done -> {self.output}")
            self.finished_ok.emit(self.output)

        except Exception as e:
            log.error("Export failed: %s", e, exc_info=True)
            self.error.emit(str(e))
        finally:
            # Clean up temp directory to avoid disk leaks
            try:
                shutil.rmtree(tmp, ignore_errors=True)
            except (OSError, NameError):
                pass


    def _qimg_to_rgb(self, qimg: QImage, out: np.ndarray):
        """Convert a QImage to raw RGB24 for FFmpeg.

        Writes into the caller-supplied *out* buffer (C-contiguous, HxWx3 uint8).
        Returns *out* directly so the caller can hold a reference without copying.
        """
        w, h = qimg.width(), qimg.height()
        bpl = qimg.bytesPerLine()

        # --- fast path: RGB32, no padding ---
        if qimg.format() == QImage.Format_RGB32 and bpl == w * 4:
            ptr = qimg.constBits()
            if hasattr(ptr, "setsize"):
                ptr.setsize(h * bpl)
                arr = np.asarray(ptr, dtype=np.uint8).reshape((h, w, 4))
            else:
                arr = np.frombuffer(bytes(ptr), dtype=np.uint8).reshape((h, w, 4))
            out[:, :, 0] = arr[:, :, 2]  # R <- B
            out[:, :, 1] = arr[:, :, 1]  # G <- G
            out[:, :, 2] = arr[:, :, 0]  # B <- R
            return out

        # --- fallback: convert to RGB888 ---
        qimg = qimg.convertToFormat(QImage.Format_RGB888)
        bpl = qimg.bytesPerLine()
        ptr = qimg.constBits()
        if isinstance(ptr, memoryview):
            arr = np.frombuffer(ptr, dtype=np.uint8).reshape((h, bpl))
        elif hasattr(ptr, "setsize"):
            ptr.setsize(h * bpl)
            arr = np.asarray(ptr, dtype=np.uint8).reshape((h, bpl))
        else:
            raw = bytes(ptr) if hasattr(ptr, "tobytes") else bytes(ptr)
            arr = np.frombuffer(raw[:h * bpl], dtype=np.uint8).reshape((h, bpl))
        if bpl != w * 3:
            arr = arr[:, :w * 3]
        return np.ascontiguousarray(arr)


# =====================================================================
# Layout Preview Dialog
# =====================================================================

_SAMPLE_CODE = '''import numpy as np
from dataclasses import dataclass

@dataclass
class NeuralLayer:
    """A single fully-connected layer."""
    weights: np.ndarray
    bias: np.ndarray
    activation: str = "relu"

    def forward(self, x: np.ndarray) -> np.ndarray:
        z = x @ self.weights + self.bias
        if self.activation == "relu":
            return np.maximum(0, z)
        return 1.0 / (1.0 + np.exp(-z))

def build_network(sizes: list[int]) -> list[NeuralLayer]:
    layers = []
    for i in range(len(sizes) - 1):
        w = np.random.randn(sizes[i], sizes[i + 1]) * 0.01
        b = np.zeros(sizes[i + 1])
        layers.append(NeuralLayer(weights=w, bias=b))
    return layers
'''


class _PreviewImageLabel(QLabel):
    """Label that displays a QImage with smooth scaling."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(480, 270)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("background: #11111b; border-radius: 8px;")

    def set_preview_image(self, qimg: QImage):
        self._pixmap = QPixmap.fromImage(qimg)
        self._update_painted()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_painted()

    def _update_painted(self):
        if self._pixmap is None:
            return
        scaled = self._pixmap.scaled(
            self.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(scaled)


class LayoutPreviewDialog(QDialog):
    """Full-featured layout preview showing a rendered frame."""

    def __init__(self, parent, renderer: "CodeRenderer", animator: "TypingAnimator",
                 theme_name: str, resolution_name: str):
        super().__init__(parent)
        self.setWindowTitle("Layout Preview")
        self.setMinimumSize(720, 540)
        self.resize(900, 640)
        self.renderer = renderer
        self.animator = animator
        self.theme_name = theme_name
        self.resolution_name = resolution_name

        # Pre-allocate scratch QImage (avoids ~8 MB allocation per frame)
        self._scratch = QImage(renderer.width, renderer.height, QImage.Format_RGB32)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # Header
        header = QLabel(f"Preview  -  {theme_name}  |  {resolution_name}")
        header.setStyleSheet("color: #cdd6f4; font-size: 15px; font-weight: bold;")
        layout.addWidget(header)

        # Preview image
        self.preview_label = _PreviewImageLabel()
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 120))
        self.preview_label.setGraphicsEffect(shadow)
        layout.addWidget(self.preview_label, stretch=1)

        # Info bar
        info_layout = QHBoxLayout()
        self._render_time_lbl = QLabel()
        self._render_time_lbl.setStyleSheet("color: #a6adc8; font-size: 11px;")
        info_layout.addWidget(self._render_time_lbl)

        info_layout.addStretch()

        # Navigation controls
        self.prev_btn = QPushButton("◀ Prev")
        self.prev_btn.setFixedWidth(80)
        self.prev_btn.clicked.connect(self._prev_frame)
        info_layout.addWidget(self.prev_btn)

        self.frame_slider = QSlider(Qt.Orientation.Horizontal)
        self.frame_slider.setRange(0, 100)
        self.frame_slider.setValue(30)
        self.frame_slider.setFixedWidth(200)
        self.frame_slider.valueChanged.connect(self._on_slider)
        info_layout.addWidget(self.frame_slider)

        self.next_btn = QPushButton("Next ▶")
        self.next_btn.setFixedWidth(80)
        self.next_btn.clicked.connect(self._next_frame)
        info_layout.addWidget(self.next_btn)

        self.frame_lbl = QLabel("")
        self.frame_lbl.setStyleSheet("color: #cdd6f4; font-size: 12px; min-width: 120px;")
        self.frame_lbl.setAlignment(Qt.AlignCenter)
        info_layout.addWidget(self.frame_lbl)

        info_layout.addStretch()

        # Play/pause animation
        self.play_btn = QPushButton("▶ Animate")
        self.play_btn.setObjectName("previewBtn")
        self.play_btn.setFixedWidth(100)
        self.play_btn.clicked.connect(self._toggle_animation)
        info_layout.addWidget(self.play_btn)

        layout.addLayout(info_layout)

        # Buttons
        btn_box = QHBoxLayout()
        btn_box.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_box.addWidget(close_btn)
        layout.addLayout(btn_box)

        # Animation state
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._advance_animation)
        self._animating = False
        self._anim_t = 0.0

        # Initial render
        self._current_progress = 0.30
        QTimer.singleShot(50, self._render_current)

    def _render_current(self):
        t0 = _time.perf_counter()
        total_chars = len(self.animator.display_chars)
        num_vis = int(total_chars * self._current_progress)
        nv = self.animator.visible_at(self.animator.duration() * self._current_progress)

        # Determine active key for keyboard overlay animation
        anim_t = self.animator.duration() * self._current_progress
        active_char, key_flash = self.animator.active_key_at(anim_t)
        if not self.renderer.keyboard_overlay:
            active_char = None
            key_flash = 0.0

        qimg = self.renderer.render_frame(
            self.animator.display_chars, nv, cursor_visible=True, target=self._scratch,
            active_char=active_char, key_flash=key_flash,
        )
        elapsed = time.perf_counter() - t0
        self.preview_label.set_preview_image(qimg)
        self._render_time_lbl.setText(
            f"Frame rendered in {elapsed*1000:.1f} ms  |  "
            f"{self.renderer.width}x{self.renderer.height}  |  "
            f"Font: {self.renderer.font_family} {self.renderer.font_size}px"
        )
        self.frame_lbl.setText(f"Progress: {self._current_progress*100:.0f}%  ({nv}/{total_chars} chars)")
        self.frame_slider.blockSignals(True)
        self.frame_slider.setValue(int(self._current_progress * 100))
        self.frame_slider.blockSignals(False)

    def _on_slider(self, value):
        self._stop_animation()
        self._current_progress = value / 100.0
        self._render_current()

    def _prev_frame(self):
        self._stop_animation()
        self._current_progress = max(0, self._current_progress - 0.05)
        self._render_current()

    def _next_frame(self):
        self._stop_animation()
        self._current_progress = min(1.0, self._current_progress + 0.05)
        self._render_current()

    def _toggle_animation(self):
        if self._animating:
            self._stop_animation()
        else:
            self._animating = True
            self.play_btn.setText("⏸ Pause")
            self._anim_t = self.animator.duration() * self._current_progress
            self._timer.start()

    def _advance_animation(self):
        dt = 0.05
        self._anim_t += dt
        total = self.animator.duration()
        if self._anim_t >= total:
            self._anim_t = total
            self._stop_animation()
        self._current_progress = min(1.0, self._anim_t / total)
        self._render_current()

    def _stop_animation(self):
        self._animating = False
        self._timer.stop()
        self.play_btn.setText("▶ Animate")


# =====================================================================
# Audio Preview Dialog
# =====================================================================

class _WaveformWidget(QWidget):
    """Custom widget that draws an audio waveform from PCM int16 data."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pcm: Optional[np.ndarray] = None
        self._sr = 44100
        self._playhead = -1.0  # -1 = no playhead
        self.setMinimumHeight(100)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("background: #181825; border-radius: 6px;")

    def set_waveform(self, pcm: np.ndarray, sr: int = 44100):
        self._pcm = pcm
        self._sr = sr
        self._playhead = -1.0
        self.update()

    def set_playhead(self, fraction: float):
        self._playhead = max(0.0, min(1.0, fraction))
        self.update()

    def clear_playhead(self):
        self._playhead = -1.0
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#181825"))

        if self._pcm is None or len(self._pcm) == 0:
            p.setPen(QColor("#585b70"))
            p.setFont(QFont("Segoe UI", 12))
            p.drawText(self.rect(), Qt.AlignCenter, "No waveform")
            p.end()
            return

        # Downsample waveform for display
        n = len(self._pcm)
        samples_per_pixel = max(1, n // w)
        mid = h / 2
        margin_y = 10
        amplitude = (h / 2) - margin_y

        # Draw center line
        p.setPen(QPen(QColor("#313244"), 1))
        p.drawLine(0, int(mid), w, int(mid))

        # Fully vectorized RMS downsampling using reshape - O(n) with no Python loop.
        # Reshape PCM into a 2D array where each row is one pixel's worth of samples,
        # then compute RMS per row.  This is ~20-50x faster than a Python for-loop.
        pcm_f = self._pcm.astype(np.float32) / 32768.0
        pcm_sq = pcm_f * pcm_f

        # Number of full chunks that fit evenly
        n_full_chunks = n // samples_per_pixel
        remainder = n % samples_per_pixel

        if n_full_chunks > 0:
            # Resquare into (n_full_chunks, samples_per_pixel) and take mean per row
            chunk_means = pcm_sq[:n_full_chunks * samples_per_pixel].reshape(
                n_full_chunks, samples_per_pixel
            ).mean(axis=1)
        else:
            chunk_means = np.empty(0, dtype=np.float64)

        # Handle the trailing partial chunk
        if remainder > 0:
            tail_mean = pcm_sq[n_full_chunks * samples_per_pixel:].mean()
            chunk_means = np.append(chunk_means, tail_mean)

        # Pad with zeros if we have fewer chunks than pixels
        if len(chunk_means) < w:
            chunk_means = np.pad(chunk_means, (0, w - len(chunk_means)))

        peaks = np.sqrt(np.maximum(chunk_means[:w], 0.0))
        peaks_top = mid - peaks * amplitude
        peaks_bot = mid + peaks * amplitude

        # Draw filled waveform as a single QPolygonF (one draw call vs w drawLines)
        poly = QPolygonF()
        poly.append(QPointF(0, mid))
        for x in range(w):
            poly.append(QPointF(float(x), float(peaks_top[x])))
        for x in range(w - 1, -1, -1):
            poly.append(QPointF(float(x), float(peaks_bot[x])))
        poly.close()

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(137, 180, 250, 50))
        p.drawPolygon(poly)

        # Draw outline as two polylines (2 draw calls vs w drawLines)
        p.setPen(QPen(QColor("#89b4fa"), 1.5))
        top_poly = QPolygonF([QPointF(float(x), float(peaks_top[x])) for x in range(w)])
        bot_poly = QPolygonF([QPointF(float(x), float(peaks_bot[x])) for x in range(w)])
        if top_poly.size() > 1:
            p.drawPolyline(top_poly)
            p.drawPolyline(bot_poly)

        # Playhead
        if 0 <= self._playhead <= 1:
            px = int(self._playhead * (w - 1))
            p.setPen(QPen(QColor("#f38ba8"), 2))
            p.drawLine(px, 0, px, h)
            # Small triangle at top
            p.setBrush(QColor("#f38ba8"))
            p.setPen(Qt.PenStyle.NoPen)
            tri = QPainterPath()
            tri.moveTo(px, 0)
            tri.lineTo(px - 5, 8)
            tri.lineTo(px + 5, 8)
            tri.closeSubpath()
            p.drawPath(tri)

        # Time labels
        p.setPen(QColor("#a6adc8"))
        p.setFont(QFont("Segoe UI", 9))
        duration_s = n / self._sr
        p.drawText(6, h - 6, "0:00.0")
        p.drawText(w - 70, h - 6, f"{duration_s:.1f}s")

        p.end()


class AudioPreviewDialog(QDialog):
    """Professional audio preview with waveform visualization and individual key sounds."""

    def __init__(self, parent, preset_name: str, volume: float = 0.5):
        super().__init__(parent)
        self.setWindowTitle(f"Audio Preview  -  {preset_name}")
        self.setMinimumSize(580, 420)
        self.resize(660, 480)
        self.preset_name = preset_name
        self.volume = volume

        self._gen = SimpleSoundGen(preset=preset_name)
        self._sr = self._gen.sr
        self._player = QMediaPlayer()
        self._audio_out = QAudioOutput()
        self._player.setAudioOutput(self._audio_out)
        self._audio_out.setVolume(volume)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Header
        desc = SOUND_PRESETS.get(preset_name, {}).get("description", "")
        header = QLabel(f"🔊  {preset_name}")
        header.setStyleSheet("color: #cdd6f4; font-size: 16px; font-weight: bold;")
        layout.addWidget(header)
        desc_lbl = QLabel(desc)
        desc_lbl.setStyleSheet("color: #a6adc8; font-size: 12px; font-style: italic;")
        layout.addWidget(desc_lbl)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #313244;")
        layout.addWidget(sep)

        # Waveform display
        wave_label = QLabel("Waveform")
        wave_label.setStyleSheet("color: #cdd6f4; font-size: 12px; font-weight: bold;")
        layout.addWidget(wave_label)
        self.waveform = _WaveformWidget()
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(12)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 80))
        self.waveform.setGraphicsEffect(shadow)
        layout.addWidget(self.waveform, stretch=1)

        # Individual sound buttons
        indiv_label = QLabel("Individual Key Sounds")
        indiv_label.setStyleSheet("color: #cdd6f4; font-size: 12px; font-weight: bold;")
        layout.addWidget(indiv_label)

        indiv_layout = QHBoxLayout()
        indiv_layout.setSpacing(10)
        for label, char in [("⌨  Click", "a"), ("⎵  Space", " "), ("↵  Enter", "\n")]:
            btn = QPushButton(label)
            btn.setFixedHeight(34)
            btn.setStyleSheet("""
                QPushButton {
                    background: #313244; color: #cdd6f4; border: 1px solid #45475a;
                    border-radius: 6px; padding: 6px 18px; font-size: 13px;
                }
                QPushButton:hover { background: #45475a; }
            """)
            btn.clicked.connect(lambda checked, c=char: self._play_individual(c))
            indiv_layout.addWidget(btn)
        indiv_layout.addStretch()
        layout.addLayout(indiv_layout)

        # Demo sequence + volume
        demo_row = QHBoxLayout()
        self.demo_btn = QPushButton("▶  Play Demo Sequence")
        self.demo_btn.setObjectName("previewBtn")
        self.demo_btn.setFixedHeight(38)
        self.demo_btn.clicked.connect(self._play_demo)
        demo_row.addWidget(self.demo_btn)

        demo_row.addStretch()

        vol_label = QLabel("Volume:")
        vol_label.setStyleSheet("color: #a6adc8; font-size: 12px;")
        demo_row.addWidget(vol_label)
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(int(volume * 100))
        self.vol_slider.setFixedWidth(120)
        self.vol_slider.setStyleSheet("""
            QSlider::groove:horizontal { background: #313244; height: 6px; border-radius: 3px; }
            QSlider::handle:horizontal { background: #89b4fa; width: 16px; height: 16px;
                margin: -5px 0; border-radius: 8px; }
        """)
        self.vol_slider.valueChanged.connect(self._on_vol_change)
        demo_row.addWidget(self.vol_slider)
        self.vol_pct = QLabel(f"{int(volume * 100)}%")
        self.vol_pct.setStyleSheet("color: #a6adc8; font-size: 12px; min-width: 36px;")
        demo_row.addWidget(self.vol_pct)
        layout.addLayout(demo_row)

        # Close button
        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(80)
        close_btn.clicked.connect(self.close)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

        # Generate and show demo waveform on open
        self._demo_pcm = None
        QTimer.singleShot(50, self._generate_demo_waveform)

    def _generate_demo_waveform(self):
        """Generate a realistic demo sequence waveform for display."""
        # Realistic code-typing sequence
        samples = [
            ("d", 0.00), ("e", 0.09), ("f", 0.17), (" ", 0.24),
            ("c", 0.34), ("l", 0.42), ("a", 0.49), ("s", 0.56), ("s", 0.63),
            (" ", 0.70), ("M", 0.80), ("y", 0.88), ("C", 0.96), ("l", 1.04),
            ("a", 1.10), ("s", 1.17), ("s", 1.24), (":", 1.34), ("\n", 1.50),
            (" ", 2.00), (" ", 2.06), (" ", 2.12), ("d", 2.22), ("e", 2.30),
            ("f", 2.37), (" ", 2.44), ("_", 2.54), ("_", 2.61), ("i", 2.68),
            ("n", 2.75), ("i", 2.82), ("t", 2.89), ("_", 3.00), ("_", 3.07),
            ("s", 3.14), ("e", 3.21), ("l", 3.28), ("f", 3.35), (":", 3.46),
            ("\n", 3.60), (" ", 4.10), (" ", 4.16), (" ", 4.22), (" ", 4.28),
            ("r", 4.38), ("e", 4.45), ("t", 4.52), ("u", 4.59), ("r", 4.66),
            ("n", 4.73), (" ", 4.80), ("s", 4.90), ("e", 4.97), ("l", 5.04),
            ("f", 5.11), ("\n", 5.35),
        ]
        max_end = 0
        for ch_char, ts in samples:
            snd = self._gen._pick(ch_char)
            end = ts + len(snd) / self._sr
            if end > max_end:
                max_end = end
        n_total = int(self._sr * (max_end + 0.5))
        mix = np.zeros(n_total, dtype=np.float64)
        for ch, ts in samples:
            snd = self._gen._pick(ch).astype(np.float64) * self.volume
            s = int(ts * self._sr)
            e = min(s + len(snd), n_total)
            if s < n_total:
                mix[s:e] += snd[:e - s]
        peak = np.max(np.abs(mix))
        if peak > 0:
            mix = mix * (32767 * 10 ** (-1.5 / 20) / peak)  # -1.5 dBFS, matches export
        self._demo_pcm = np.clip(mix, -32768, 32767).astype(np.int16)
        self._demo_samples = samples
        self.waveform.set_waveform(self._demo_pcm, self._sr)

    def _play_individual(self, char: str):
        """Play a single key sound and flash the waveform."""
        snd = self._gen._pick(char).astype(np.float64) * self.volume
        peak = np.max(np.abs(snd))
        if peak > 0:
            snd = snd * (32767 * 10 ** (-1.5 / 20) / peak)  # -1.5 dBFS, matches export
        pcm = np.clip(snd, -32768, 32767).astype(np.int16)
        # Show waveform
        self.waveform.set_waveform(pcm, self._sr)
        # Play
        tmp_path = os.path.join(TMP_DIR, "_preview_indiv.wav")
        os.makedirs(TMP_DIR, exist_ok=True)
        with wave.open(tmp_path, "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self._sr)
            w.writeframes(pcm.tobytes())
        self._audio_out.setVolume(self.volume)
        self._player.setSource(QUrl.fromLocalFile(os.path.abspath(tmp_path)))
        self._player.play()
        # Restore full waveform after sound plays
        QTimer.singleShot(800, self._restore_demo_waveform)

    def _restore_demo_waveform(self):
        if self._demo_pcm is not None:
            self.waveform.set_waveform(self._demo_pcm, self._sr)

    def _play_demo(self):
        """Play the full demo sequence with animated playhead."""
        if self._demo_pcm is None:
            return
        self.waveform.set_waveform(self._demo_pcm, self._sr)
        # Write to temp WAV
        tmp_path = os.path.join(TMP_DIR, "_preview_demo.wav")
        os.makedirs(TMP_DIR, exist_ok=True)
        with wave.open(tmp_path, "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self._sr)
            w.writeframes(self._demo_pcm.tobytes())
        # Disconnect any prior connections to prevent signal leaks
        try:
            self._player.positionChanged.disconnect()
        except RuntimeError:
            pass
        self._audio_out.setVolume(self.volume)
        self._player.setSource(QUrl.fromLocalFile(os.path.abspath(tmp_path)))
        self._player.play()
        # Animate playhead
        if hasattr(self, "_playback_timer") and self._playback_timer is not None:
            self._playback_timer.stop()
        self._playback_timer = QTimer(self)
        self._playback_timer.setInterval(30)
        self._playback_timer.timeout.connect(
            lambda: self.waveform.set_playhead(
                self._player.position() / max(1, self._player.duration())
            )
        )
        self._playback_timer.start()
        self.demo_btn.setEnabled(False)
        self.demo_btn.setText("♪  Playing...")
        self._player.positionChanged.connect(self._on_demo_finished)

    def _on_demo_finished(self, pos: int):
        """Single handler for demo playback completion - no signal leaks."""
        if pos >= self._player.duration() - 60:
            if hasattr(self, "_playback_timer") and self._playback_timer is not None:
                self._playback_timer.stop()
            self.waveform.clear_playhead()
            self.demo_btn.setEnabled(True)
            self.demo_btn.setText("▶  Play Demo Sequence")
            try:
                self._player.positionChanged.disconnect(self._on_demo_finished)
            except RuntimeError:
                pass

    def _on_vol_change(self, val):
        vol = val / 100.0
        self._audio_out.setVolume(vol)
        self.vol_pct.setText(f"{val}%")

    def closeEvent(self, event):
        self._player.stop()
        super().closeEvent(event)


# =====================================================================
# Main Window - checkbox-based program selector
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
        self._item_paths: set[str] = set()
        self._exporter: Optional[VideoExporter] = None
        self._export_queue: List[FileItem] = []
        self._loading_settings = False  # guard to prevent save-during-load

        # Inline preview state
        self._preview_progress = 0.30
        self._preview_animating = False
        self._preview_anim_t = 0.0
        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(50)
        self._preview_timer.timeout.connect(self._advance_preview_animation)

        # Preview caching \u2014 avoid re-reading files & re-creating objects every tick
        self._cached_preview_key: Optional[tuple] = None
        self._cached_preview_code: Optional[str] = None
        self._cached_preview_renderer: Optional["CodeRenderer"] = None
        self._cached_preview_animator: Optional["TypingAnimator"] = None
        # Pre-allocated scratch QImage for preview rendering (avoids ~8 MB alloc/frame)
        self._preview_scratch: Optional[QImage] = None

        self._build_ui()
        self._connect_settings_signals()
        self._load_settings()
        self._scan_input_dir()
        # Initial preview render (delayed so UI is visible first)
        QTimer.singleShot(500, self._update_preview)

    # ── UI construction ─────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # ── Horizontal split: LEFT (programs) | RIGHT (settings) ──
        hsplit = QHBoxLayout()
        hsplit.setSpacing(16)

        # ======== LEFT PANEL: Programs ========
        left_panel = QVBoxLayout()
        left_panel.setContentsMargins(0, 0, 0, 0)

        file_group = QGroupBox("Programs")
        fg_lay = QVBoxLayout(file_group)

        # Buttons row 1: scan controls
        btn_row = QHBoxLayout()
        self.scan_btn = QPushButton("Scan input/")
        self.scan_btn.clicked.connect(self._scan_input_dir)
        btn_row.addWidget(self.scan_btn)

        self.scan_folder_btn = QPushButton("Choose Folder...")
        self.scan_folder_btn.clicked.connect(self._scan_folder)
        btn_row.addWidget(self.scan_folder_btn)

        self.add_btn = QPushButton("Add files...")
        self.add_btn.clicked.connect(self._add_files)
        btn_row.addWidget(self.add_btn)

        btn_row.addStretch()

        # Recursive depth control
        self.recurse_chk = QCheckBox("Recursive")
        self.recurse_chk.setChecked(True)
        self.recurse_chk.setToolTip("Scan subfolders recursively")
        btn_row.addWidget(self.recurse_chk)

        btn_row.addWidget(QLabel("Depth:"))
        self.depth_sp = QSpinBox()
        self.depth_sp.setRange(1, 99)
        self.depth_sp.setValue(10)
        self.depth_sp.setToolTip("Max recursion depth (1 = only root folder)")
        self.depth_sp.setFixedWidth(60)
        btn_row.addWidget(self.depth_sp)
        fg_lay.addLayout(btn_row)

        # Buttons row 2: selection + file count
        btn_row2 = QHBoxLayout()
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self._select_all)
        btn_row2.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("Deselect All")
        self.deselect_all_btn.clicked.connect(self._deselect_all)
        btn_row2.addWidget(self.deselect_all_btn)

        self.file_count_lbl = QLabel("")
        self.file_count_lbl.setStyleSheet("color: #a6adc8; font-size: 11px;")
        btn_row2.addWidget(self.file_count_lbl)

        btn_row2.addStretch()
        fg_lay.addLayout(btn_row2)

        # Table
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Export", "Path", "Language", "Status"])
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
        left_panel.addWidget(file_group, stretch=1)

        # --- Progress (under left panel) ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        left_panel.addWidget(self.progress_bar)

        # --- Export / Cancel buttons ---
        btn_row3 = QHBoxLayout()
        btn_row3.addStretch()
        self.export_btn = QPushButton("Export Checked")
        self.export_btn.setObjectName("primaryBtn")
        self.export_btn.setMinimumHeight(36)
        self.export_btn.clicked.connect(self._start_export)
        btn_row3.addWidget(self.export_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_export)
        btn_row3.addWidget(self.cancel_btn)
        left_panel.addLayout(btn_row3)

        hsplit.addLayout(left_panel, stretch=3)

        # ======== RIGHT PANEL: Settings (tabbed) ========
        right_panel = QVBoxLayout()
        right_panel.setContentsMargins(0, 0, 0, 0)

        settings_tabs = QTabWidget()
        settings_tabs.setObjectName("settingsTabs")

        # ── Tab 1: Preview (inline, auto-updating) ──
        preview_tab = QWidget()
        pl = QVBoxLayout(preview_tab)
        pl.setContentsMargins(8, 8, 8, 8)
        pl.setSpacing(6)

        # Preview image
        self._preview_label = _PreviewImageLabel()
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 120))
        self._preview_label.setGraphicsEffect(shadow)
        pl.addWidget(self._preview_label, stretch=1)

        # Per-line height display
        self._preview_line_h_lbl = QLabel("")
        self._preview_line_h_lbl.setStyleSheet(
            "color: #89b4fa; font-size: 10px; font-family: 'DejaVu Sans Mono', monospace;"
        )
        self._preview_line_h_lbl.setWordWrap(True)
        pl.addWidget(self._preview_line_h_lbl)

        # Info bar
        info_layout = QHBoxLayout()
        self._preview_render_time_lbl = QLabel()
        self._preview_render_time_lbl.setStyleSheet("color: #a6adc8; font-size: 11px;")
        info_layout.addWidget(self._preview_render_time_lbl)

        info_layout.addStretch()

        # Estimated video duration
        self._preview_duration_lbl = QLabel("")
        self._preview_duration_lbl.setStyleSheet(
            "color: #a6e3a1; font-size: 11px; font-weight: bold;"
        )
        info_layout.addWidget(self._preview_duration_lbl)
        info_layout.addStretch()

        # Navigation controls
        self._prev_btn = QPushButton("◀ Prev")
        self._prev_btn.setFixedWidth(70)
        self._prev_btn.clicked.connect(self._preview_prev)
        info_layout.addWidget(self._prev_btn)

        self._frame_slider = QSlider(Qt.Orientation.Horizontal)
        self._frame_slider.setRange(0, 100)
        self._frame_slider.setValue(30)
        self._frame_slider.setFixedWidth(140)
        self._frame_slider.valueChanged.connect(self._on_preview_slider)
        info_layout.addWidget(self._frame_slider)

        self._next_btn = QPushButton("Next ▶")
        self._next_btn.setFixedWidth(70)
        self._next_btn.clicked.connect(self._preview_next)
        info_layout.addWidget(self._next_btn)

        self._frame_lbl = QLabel("")
        self._frame_lbl.setStyleSheet("color: #cdd6f4; font-size: 11px; min-width: 100px;")
        self._frame_lbl.setAlignment(Qt.AlignCenter)
        info_layout.addWidget(self._frame_lbl)
        info_layout.addStretch()

        # Visual guide toggles
        self._guide_padding_chk = QCheckBox("Pad")
        self._guide_padding_chk.setToolTip("Show padding boundary guide (red)")
        self._guide_padding_chk.setChecked(True)
        info_layout.addWidget(self._guide_padding_chk)

        self._guide_chrome_chk = QCheckBox("Chrome")
        self._guide_chrome_chk.setToolTip("Show window chrome boundary guide (blue)")
        self._guide_chrome_chk.setChecked(True)
        info_layout.addWidget(self._guide_chrome_chk)

        self._guide_code_chk = QCheckBox("Code")
        self._guide_code_chk.setToolTip("Show code rect boundary guide (green)")
        self._guide_code_chk.setChecked(True)
        info_layout.addWidget(self._guide_code_chk)

        self._guide_kb_chk = QCheckBox("KB")
        self._guide_kb_chk.setToolTip("Show keyboard overlay boundary guide (yellow)")
        self._guide_kb_chk.setChecked(True)
        info_layout.addWidget(self._guide_kb_chk)

        self._guide_gap_chk = QCheckBox("Gap")
        self._guide_gap_chk.setToolTip("Show bottom gap between last line and code rect edge (magenta)")
        self._guide_gap_chk.setChecked(True)
        info_layout.addWidget(self._guide_gap_chk)

        # Play/pause animation
        self._play_btn = QPushButton("▶ Animate")
        self._play_btn.setObjectName("previewBtn")
        self._play_btn.setFixedWidth(90)
        self._play_btn.clicked.connect(self._toggle_preview_animation)
        info_layout.addWidget(self._play_btn)

        pl.addLayout(info_layout)

        settings_tabs.addTab(preview_tab, "Preview")

        # ── Tab 2: Settings (all settings in one scrollable tab) ──
        settings_container = QWidget()
        settings_scroll = QScrollArea()
        settings_scroll.setWidget(settings_container)
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setFrameShape(QFrame.NoFrame)
        sl = QVBoxLayout(settings_container)
        sl.setSpacing(16)
        sl.setContentsMargins(12, 12, 12, 12)

        # -- Visual Group --
        visual_grp = QGroupBox("Visual")
        vl = QFormLayout(visual_grp)
        vl.setSpacing(10)
        vl.setContentsMargins(12, 16, 12, 12)

        self.theme_cb = QComboBox()
        self.theme_cb.addItems(list(THEMES.keys()))
        self.theme_cb.setCurrentText("Dracula")
        vl.addRow("Theme:", self.theme_cb)

        self.res_cb = QComboBox()
        self.res_cb.addItems(list(RESOLUTIONS.keys()))
        self.res_cb.setCurrentText("1920x1080")
        vl.addRow("Resolution:", self.res_cb)

        # Font family selector
        self.font_family_cb = QComboBox()
        self.font_family_cb.setToolTip("Choose the monospace font used to render code in the video")
        _known_mono = [
            "Consolas", "JetBrains Mono", "Fira Code", "Cascadia Code",
            "Source Code Pro", "Inconsolata", "Ubuntu Mono", "DejaVu Sans Mono",
            "Liberation Mono", "Courier New", "Courier 10 Pitch", "FreeMono",
            "Nimbus Mono PS", "monospace",
        ]
        _available_families = QFontDatabase.families()
        _mono_choices = [f for f in _known_mono if f in _available_families]
        # Also add any system monospace fonts not in the known list
        for fam in sorted(_available_families):
            if fam not in _mono_choices:
                test_font = QFont(fam)
                test_font.setFixedPitch(True)
                if test_font.fixedPitch():
                    _mono_choices.append(fam)
        self.font_family_cb.addItems(_mono_choices)
        self.font_family_cb.setCurrentText("Consolas" if "Consolas" in _mono_choices else (_mono_choices[0] if _mono_choices else "monospace"))
        vl.addRow("Code Font:", self.font_family_cb)

        # Font size override
        font_size_row = QHBoxLayout()
        self.font_size_auto_chk = QCheckBox("Auto")
        self.font_size_auto_chk.setChecked(True)
        self.font_size_auto_chk.setToolTip("Automatically calculate font size to fit code")
        font_size_row.addWidget(self.font_size_auto_chk)
        self.font_size_sp = QSpinBox()
        self.font_size_sp.setRange(8, 72)
        self.font_size_sp.setValue(22)
        self.font_size_sp.setSuffix(" px")
        self.font_size_sp.setEnabled(False)
        self.font_size_sp.setToolTip("Manual font size override")
        font_size_row.addWidget(self.font_size_sp)
        self.font_size_auto_chk.toggled.connect(self._on_font_size_auto_toggled)
        vl.addRow("Code Font Size:", font_size_row)

        # Title override
        title_row = QHBoxLayout()
        self.title_auto_chk = QCheckBox("Auto")
        self.title_auto_chk.setChecked(True)
        self.title_auto_chk.setToolTip(
            'Auto-generate title as "filename - Code Editor".\n'
            "Leave unchecked to enter a custom title."
        )
        title_row.addWidget(self.title_auto_chk)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("filename - Code Editor")
        self.title_edit.setEnabled(False)
        self.title_edit.setToolTip("Custom window title shown in the video")
        title_row.addWidget(self.title_edit)
        self.title_auto_chk.toggled.connect(self._on_title_auto_toggled)
        vl.addRow("Window Title:", title_row)

        sl.addWidget(visual_grp)

        # -- Layout Group --
        layout_grp = QGroupBox("Layout")
        ll = QFormLayout(layout_grp)
        ll.setSpacing(10)
        ll.setContentsMargins(12, 16, 12, 12)

        self.padding_sp = QSpinBox()
        self.padding_sp.setRange(0, 120)
        self.padding_sp.setValue(24)
        self.padding_sp.setSuffix(" px")
        self.padding_sp.setToolTip(
            "Space around the editor window inside the video frame.\n"
            "Lower values let the code area fill more of the resolution."
        )
        ll.addRow("Padding:", self.padding_sp)

        self.chrome_chk = QCheckBox("Show Window Chrome")
        self.chrome_chk.setChecked(True)
        self.chrome_chk.setToolTip("Show the title bar with traffic-light buttons (saves 42 px when off)")
        ll.addRow(self.chrome_chk)

        self.line_numbers_chk = QCheckBox("Show Line Numbers")
        self.line_numbers_chk.setChecked(True)
        self.line_numbers_chk.setToolTip("Toggle line-number gutter on/off to gain horizontal space")
        ll.addRow(self.line_numbers_chk)

        sl.addWidget(layout_grp)

        # -- Typing Group --
        typing_grp = QGroupBox("Typing")
        tl = QFormLayout(typing_grp)
        tl.setSpacing(10)
        tl.setContentsMargins(12, 16, 12, 12)

        self.wpm_sp = QSpinBox()
        self.wpm_sp.setRange(30, 300)
        self.wpm_sp.setValue(100)
        tl.addRow("WPM:", self.wpm_sp)

        self.fps_sp = QSpinBox()
        self.fps_sp.setRange(10, 60)
        self.fps_sp.setValue(30)
        tl.addRow("FPS:", self.fps_sp)

        self.start_pause_sp = QDoubleSpinBox()
        self.start_pause_sp.setRange(0, 10)
        self.start_pause_sp.setSingleStep(0.5)
        self.start_pause_sp.setValue(0.5)
        tl.addRow("Start Pause (s):", self.start_pause_sp)

        self.end_pause_sp = QDoubleSpinBox()
        self.end_pause_sp.setRange(0, 10)
        self.end_pause_sp.setSingleStep(0.5)
        self.end_pause_sp.setValue(1.5)
        tl.addRow("End Pause (s):", self.end_pause_sp)

        sl.addWidget(typing_grp)

        # -- Audio Group --
        audio_grp = QGroupBox("Audio")
        al = QFormLayout(audio_grp)
        al.setSpacing(10)
        al.setContentsMargins(12, 16, 12, 12)

        self.sound_chk = QCheckBox("Typing Sounds")
        self.sound_chk.setChecked(True)
        self.sound_chk.toggled.connect(self._on_sound_toggled)
        al.addRow(self.sound_chk)

        self.vol_sl = QSpinBox()
        self.vol_sl.setRange(0, 100)
        self.vol_sl.setValue(50)
        self.vol_sl.setSuffix("%")
        al.addRow("Volume:", self.vol_sl)

        self.sound_preset_cb = QComboBox()
        self.sound_preset_cb.addItems(list(SOUND_PRESETS.keys()))
        self.sound_preset_cb.setCurrentText("Mechanical")
        self.sound_preset_cb.currentTextChanged.connect(self._on_preset_changed)
        al.addRow("Sound Preset:", self.sound_preset_cb)

        self.preset_desc_lbl = QLabel(SOUND_PRESETS["Mechanical"]["description"])
        self.preset_desc_lbl.setStyleSheet("color: #a6adc8; font-size: 11px; font-style: italic;")
        al.addRow(self.preset_desc_lbl)

        self.preview_btn = QPushButton("\u25b6 Preview Sound")
        self.preview_btn.setObjectName("previewBtn")
        self.preview_btn.clicked.connect(self._preview_sound)
        al.addRow(self.preview_btn)

        sl.addWidget(audio_grp)

        # -- Keyboard Group --
        kb_grp = QGroupBox("Keyboard")
        kl = QFormLayout(kb_grp)
        kl.setSpacing(10)
        kl.setContentsMargins(12, 16, 12, 12)

        self.kb_overlay_chk = QCheckBox("Show Keyboard Overlay")
        self.kb_overlay_chk.setChecked(False)
        self.kb_overlay_chk.toggled.connect(self._on_kb_overlay_toggled)
        kl.addRow(self.kb_overlay_chk)

        self.kb_layout_cb = QComboBox()
        self.kb_layout_cb.addItems(list(KEYBOARD_LAYOUTS.keys()))
        self.kb_layout_cb.setCurrentText("QWERTY")
        self.kb_layout_cb.setEnabled(False)
        self.kb_layout_cb.currentTextChanged.connect(self._on_kb_layout_changed)
        kl.addRow("Layout:", self.kb_layout_cb)

        self.kb_position_cb = QComboBox()
        self.kb_position_cb.addItems([
            "Bottom Center", "Bottom Right", "Bottom Left",
            "Center Left", "Center Right",
            "Top Center", "Top Right", "Top Left",
        ])
        self.kb_position_cb.setCurrentText("Bottom Center")
        self.kb_position_cb.setEnabled(False)
        self.kb_position_cb.setToolTip("Choose where the keyboard overlay appears in the video frame")
        kl.addRow("Position:", self.kb_position_cb)

        self.kb_desc_lbl = QLabel(KEYBOARD_LAYOUTS["QWERTY"]["description"])
        self.kb_desc_lbl.setStyleSheet("color: #a6adc8; font-size: 11px; font-style: italic;")
        self.kb_desc_lbl.setEnabled(False)
        kl.addRow(self.kb_desc_lbl)

        sl.addWidget(kb_grp)

        sl.addStretch()

        settings_tabs.addTab(settings_scroll, "Settings")

        right_panel.addWidget(settings_tabs)
        hsplit.addLayout(right_panel, stretch=2)

        root.addLayout(hsplit, stretch=1)

        # --- Status bar ---
        self.statusBar().showMessage("Ready. Place code files in input/ folder and click Scan.")

        # --- Audio preview player ---
        self._audio_player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._audio_player.setAudioOutput(self._audio_output)
        self._audio_output.setVolume(self.vol_sl.value() / 100.0)

    def _on_sound_toggled(self, checked: bool):
        """Enable/disable sound-related controls."""
        self.sound_preset_cb.setEnabled(checked)
        self.preview_btn.setEnabled(checked)
        self.preset_desc_lbl.setEnabled(checked)

    def _on_preset_changed(self, preset_name: str):
        """Update the preset description label."""
        desc = SOUND_PRESETS.get(preset_name, {}).get("description", "")
        self.preset_desc_lbl.setText(desc)

    def _on_kb_overlay_toggled(self, checked: bool):
        """Enable/disable keyboard overlay controls."""
        self.kb_layout_cb.setEnabled(checked)
        self.kb_position_cb.setEnabled(checked)
        self.kb_desc_lbl.setEnabled(checked)

    def _on_kb_layout_changed(self, layout_name: str):
        """Update the keyboard layout description label."""
        desc = KEYBOARD_LAYOUTS.get(layout_name, {}).get("description", "")
        self.kb_desc_lbl.setText(desc)

    def _on_font_size_auto_toggled(self, checked: bool):
        """Toggle between auto and manual font size."""
        self.font_size_sp.setEnabled(not checked)

    def _on_title_auto_toggled(self, checked: bool):
        """Toggle between auto-generated and custom title."""
        self.title_edit.setEnabled(not checked)
        self._invalidate_preview_cache()
        self._schedule_preview_update()

    def _preview_sound(self):
        """Open the professional audio preview dialog."""
        if not self.sound_chk.isChecked():
            return
        preset = self.sound_preset_cb.currentText()
        vol = self.vol_sl.value() / 100.0
        dlg = AudioPreviewDialog(self, preset_name=preset, volume=vol)
        dlg.exec()

    # ── Inline Preview ────────────────────────────────────────────

    _KB_POS_MAP = {
        "Bottom Center": "bottom_center", "Bottom Right": "bottom_right",
        "Bottom Left": "bottom_left", "Center Left": "center_left",
        "Center Right": "center_right", "Top Center": "top_center",
        "Top Right": "top_right", "Top Left": "top_left",
    }

    def _kb_position_key(self) -> str:
        return self._KB_POS_MAP.get(self.kb_position_cb.currentText(), "bottom_center")

    def _invalidate_preview_cache(self, *_args):
        """Clear cached preview objects so the next _update_preview rebuilds them."""
        self._cached_preview_key = None
        self._cached_preview_code = None
        self._cached_preview_renderer = None
        self._cached_preview_animator = None
        self._preview_scratch = None  # scratch size may change with resolution

    def _draw_guides(self, img: QImage, renderer, show: dict):
        """Draw pixel-boundary guide lines on the preview image.

        *show* is a dict with keys: 'padding', 'chrome', 'code', 'kb'.
        Each value is a bool controlling whether that guide is drawn.
        """
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        pad = renderer.padding
        chrome_h = 42 if renderer.show_window_chrome else 0
        cr = renderer._code_rect

        # Colours (semi-transparent so they don't obscure content)
        pad_color   = QColor(255, 100, 100, 120)   # red - padding
        win_color   = QColor(100, 200, 255, 140)    # blue - window border
        code_color  = QColor(100, 255, 100, 120)    # green - code rect
        kb_color    = QColor(255, 200, 50, 120)     # yellow - keyboard

        pen_w = max(1, renderer.width // 960)

        # Padding boundaries
        if show.get('padding', False):
            p.setPen(QPen(pad_color, pen_w, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(pad, pad, renderer.width - 2 * pad, renderer.height - 2 * pad)

        # Window chrome bottom edge
        if show.get('chrome', False) and renderer.show_window_chrome:
            p.setPen(QPen(win_color, pen_w, Qt.PenStyle.DotLine))
            y_chrome = pad + chrome_h
            p.drawLine(pad, y_chrome, renderer.width - pad, y_chrome)

        # Code rect
        if show.get('code', False):
            p.setPen(QPen(code_color, pen_w))
            p.drawRect(cr)

        # Keyboard overlay bounds
        if show.get('kb', False) and renderer.keyboard_overlay:
            ko = renderer.keyboard_overlay
            p.setPen(QPen(kb_color, pen_w, Qt.PenStyle.DashLine))
            m = max(6, ko.key_unit // 4)
            p.drawRect(ko._kb_x - m, ko._kb_y - m,
                       ko._kb_width + 2 * m, ko._kb_height + 2 * m)

        # Dimension labels (always show for active guides)
        label_font = QFont("DejaVu Sans Mono", max(8, renderer.width // 160))
        label_font.setBold(True)
        p.setFont(label_font)

        def _draw_label(text: str, color: QColor, x: int, y: int):
            # Background pill
            fm = QFontMetrics(label_font)
            tw = fm.horizontalAdvance(text) + 8
            th = fm.height() + 4
            p.setPen(Qt.PenStyle.NoPen)
            bg = QColor(0, 0, 0, 180)
            p.drawRoundedRect(x, y - th + 2, tw, th, 3, 3)
            p.setPen(color)
            p.drawText(x + 4, y, text)

        if show.get('code', False):
            _draw_label(f"{cr.width()}×{cr.height()}", code_color, cr.x() + 4, cr.y() + 14)

        if show.get('padding', False):
            _draw_label(f"pad={pad}", pad_color, pad + 4, pad + 14)

        if show.get('kb', False) and renderer.keyboard_overlay:
            ko = renderer.keyboard_overlay
            m = max(6, ko.key_unit // 4)
            _draw_label(f"kb {ko._kb_width}×{ko._kb_height}", kb_color,
                       ko._kb_x - m + 4, ko._kb_y - m + 14)

        if show.get('chrome', False):
            ww = renderer.width - 2 * pad
            wh_full = renderer.height - 2 * pad - (0 if not renderer.keyboard_overlay
                   else min(renderer.keyboard_overlay.height_needed(),
                            (renderer.height - 2 * pad) // 3))
            _draw_label(f"window {ww}×{wh_full}", win_color,
                       pad + ww // 2 - 40, pad + wh_full + 6)

        # Bottom gap visualisation
        if show.get('gap', False):
            cr_h = cr.height()
            line_h = renderer.line_h
            # Floor division: how many FULL lines fit (old behaviour)
            max_floor = max(1, cr_h // line_h)
            gap_floor = cr_h - max_floor * line_h  # unused pixels at bottom
            # Ceiling division: lines that fill the rect (new behaviour)
            max_ceil = max(1, -(-cr_h // line_h))
            overflow_ceil = max_ceil * line_h - cr_h  # pixels clipped at bottom

            gap_color = QColor(255, 100, 255, 90)  # magenta semi-transparent
            gap_border = QColor(255, 100, 255, 200)
            pen_w2 = max(1, renderer.width // 960)

            if gap_floor > 0:
                # Draw the unfilled strip at the bottom of the code rect
                gap_y = cr.bottom() - gap_floor
                p.setPen(QPen(gap_border, pen_w2, Qt.PenStyle.DashLine))
                p.setBrush(gap_color)
                p.drawRect(cr.x(), gap_y, cr.width(), gap_floor)

            cr_w = cr.width()
            fill_pct = max_floor * line_h / cr_h * 100
            log.info(
                "[gap] cr_h=%d  line_h=%d  floor:%dL  gap:%dpx  ceil:%dL  overflow:%dpx  "
                "cr_w=%d  char_w=%d  cols~%d  fill=%.1f%%  font=%dpx",
                cr_h, line_h, max_floor, gap_floor, max_ceil, overflow_ceil,
                cr_w, renderer.char_w, cr_w // max(1, renderer.char_w),
                fill_pct, renderer.font_size,
            )

        p.end()

    def _update_preview(self):
        """Render a preview frame inline in the Preview tab (cached)."""
        try:
            res_name = self.res_cb.currentText()
            w, h = RESOLUTIONS.get(res_name, (1920, 1080))
            theme_name = self.theme_cb.currentText()
            kb_checked = self.kb_overlay_chk.isChecked()
            kb_layout = self.kb_layout_cb.currentText()
            wpm = self.wpm_sp.value()
            start_pause = self.start_pause_sp.value()
            end_pause = self.end_pause_sp.value()

            # Keyboard overlay setup
            kb_overlay = None
            kb_h = 0
            if kb_checked:
                kb_overlay = KeyboardOverlay(
                    video_w=w, video_h=h,
                    layout_name=kb_layout,
                    theme=THEMES.get(theme_name, THEMES["Dracula"]),
                    max_height=(h - 2 * self.padding_sp.value()) // 3,
                    position=self._kb_position_key(),
                )
                kb_h = kb_overlay.height_needed()

            # Determine code source (first checked file, or sample)
            # Resolve title
            if self.title_auto_chk.isChecked():
                title_text = "preview.py - Code Editor"
            else:
                custom = self.title_edit.text().strip()
                title_text = custom if custom else "preview.py - Code Editor"

            code_path = None
            language = "Python"
            for it in self._items:
                if it.checked:
                    code_path = it.path
                    if self.title_auto_chk.isChecked():
                        title_text = f"{os.path.basename(it.path)} - Code Editor"
                    ext = os.path.splitext(it.path)[1].lower()
                    language = EXT_TO_LANGUAGE.get(ext, "Python")
                    break

            _chosen_font = self.font_family_cb.currentText()

            if self.font_size_auto_chk.isChecked():
                font_size = CodeRenderer.auto_font_size(
                    code_lines=(self._cached_preview_code or _SAMPLE_CODE).count("\n") + 1,
                    width=w, height=h,
                    code=self._cached_preview_code or _SAMPLE_CODE,
                    font_family=_chosen_font, keyboard_h=kb_h,
                    padding=self.padding_sp.value(),
                    show_window_chrome=self.chrome_chk.isChecked(),
                    show_line_numbers=self.line_numbers_chk.isChecked(),
                )
            else:
                font_size = self.font_size_sp.value()

            cache_key = (code_path, w, h, theme_name, _chosen_font, font_size, kb_layout,
                         kb_checked, self._kb_position_key(),
                         wpm, start_pause, end_pause, title_text,
                         self.padding_sp.value(), self.chrome_chk.isChecked(),
                         self.line_numbers_chk.isChecked())

            # Rebuild cached objects only when the key changes
            if cache_key != self._cached_preview_key:
                if code_path is None:
                    code = _SAMPLE_CODE
                    if self.title_auto_chk.isChecked():
                        title_text = "neural_layer.py - Code Editor"
                    language = "Python"
                else:
                    try:
                        with open(code_path, "r", encoding="utf-8", errors="replace") as f:
                            code = f.read()
                    except Exception:
                        code = _SAMPLE_CODE
                        title_text = "neural_layer.py - Code Editor"
                        language = "Python"

                if self.font_size_auto_chk.isChecked():
                    font_size = CodeRenderer.auto_font_size(
                        code_lines=code.count("\n") + 1,
                        width=w, height=h, code=code,
                        font_family=_chosen_font, keyboard_h=kb_h,
                        padding=self.padding_sp.value(),
                        show_window_chrome=self.chrome_chk.isChecked(),
                        show_line_numbers=self.line_numbers_chk.isChecked(),
                    )

                self._cached_preview_code = code
                self._cached_preview_renderer = CodeRenderer(
                    width=w, height=h,
                    theme_name=theme_name,
                    font_family=_chosen_font,
                    font_size=font_size,
                    title_text=title_text,
                    language=language,
                    keyboard_overlay=kb_overlay,
                    padding=self.padding_sp.value(),
                    show_window_chrome=self.chrome_chk.isChecked(),
                    show_line_numbers=self.line_numbers_chk.isChecked(),
                    total_code_lines=code.count("\n") + 1,
                )
                self._cached_preview_animator = TypingAnimator(
                    code, wpm=wpm,
                    start_pause=start_pause,
                    end_pause=end_pause,
                )
                self._cached_preview_key = cache_key

            renderer = self._cached_preview_renderer
            animator = self._cached_preview_animator

            t0 = _time.perf_counter()
            total_chars = len(animator.display_chars)
            nv = animator.visible_at(animator.duration() * self._preview_progress)

            # Determine active key for keyboard overlay animation
            anim_t = animator.duration() * self._preview_progress
            active_char, key_flash = animator.active_key_at(anim_t)
            if not renderer.keyboard_overlay:
                active_char = None
                key_flash = 0.0

            # Reuse pre-allocated scratch QImage (avoids ~8 MB heap alloc per frame)
            if (self._preview_scratch is None
                    or self._preview_scratch.width() != renderer.width
                    or self._preview_scratch.height() != renderer.height):
                self._preview_scratch = QImage(
                    renderer.width, renderer.height, QImage.Format_RGB32
                )

            qimg = renderer.render_frame(
                animator.display_chars, nv, cursor_visible=True,
                target=self._preview_scratch,
                active_char=active_char, key_flash=key_flash,
            )
            # Draw visual guides if any are enabled
            any_guide = (self._guide_padding_chk.isChecked()
                         or self._guide_chrome_chk.isChecked()
                         or self._guide_code_chk.isChecked()
                         or self._guide_kb_chk.isChecked()
                         or self._guide_gap_chk.isChecked())
            if any_guide:
                self._draw_guides(qimg, renderer, show={
                    'padding': self._guide_padding_chk.isChecked(),
                    'chrome': self._guide_chrome_chk.isChecked(),
                    'code': self._guide_code_chk.isChecked(),
                    'kb': self._guide_kb_chk.isChecked(),
                    'gap': self._guide_gap_chk.isChecked(),
                })
            elapsed = _time.perf_counter() - t0
            self._preview_label.set_preview_image(qimg)
            auto_enabled = self.font_size_auto_chk.isChecked()
            # Build per-line line_h info string for preview
            line_h = renderer.line_h
            cr_h = renderer._code_rect.height()
            max_vis_preview = max(1, -(-cr_h // line_h))
            total_used_preview = max_vis_preview * line_h
            remainder_preview = cr_h - total_used_preview
            code = self._cached_preview_code or _SAMPLE_CODE
            # Reconstruct the visible text at current progress
            display_chars = animator.display_chars
            if 0 <= nv < len(display_chars):
                vis_chars = display_chars[:nv]
            else:
                vis_chars = display_chars
            visible_text = renderer._resolve_backspaces(vis_chars)
            visible_lines = visible_text.split("\n") if visible_text else []
            line_h_info_parts = []
            for i in range(min(len(visible_lines), max_vis_preview)):
                lh = line_h + (1 if i < remainder_preview else 0)
                line_h_info_parts.append(f"L{i+1}:{lh}")
            line_h_display = "  ".join(line_h_info_parts[:16])
            if len(line_h_info_parts) > 16:
                line_h_display += f"  ... ({len(visible_lines)} lines, {max_vis_preview} slots, gap={remainder_preview}px)"

            self._preview_render_time_lbl.setText(
                f"{elapsed*1000:.1f} ms  |  {renderer.width}x{renderer.height}  |  "
                f"Font: {renderer.font_family} {renderer.font_size}px "
                f"{'(auto)' if auto_enabled else '(manual)'}  |  "
                f"line_h={line_h}px  |  slots={max_vis_preview}  distribute={remainder_preview}px"
            )
            self._preview_line_h_lbl.setText(
                f"Per-line heights: {line_h_display}"
            )
            # Show code rect vs actual code content dimensions
            cr = renderer._code_rect
            n_lines = code.count("\n") + 1
            code_h = n_lines * renderer.line_h
            code_w = 0
            for line in code.split("\n"):
                lw = sum(renderer.fm.horizontalAdvance(ch) if ch != "\t" else renderer._tab_advance
                         for ch in line)
                code_w = max(code_w, lw)
            cr_h = cr.height()
            cr_w = cr.width()
            chars_per_line = cr_w // max(1, renderer.char_w)
            max_line_len = max(len(l) for l in code.split("\n")) if code else 0
            # When auto is ON: code_lines <= max_vis by design (font sized to fit).
            # When auto is OFF: code_lines may exceed max_vis → scrolling needed.
            max_scroll_preview = max(0, n_lines - max_vis_preview)
            log.info(
                "[preview] auto=%s  cr_h=%d  line_h=%d  "
                "ceil:%dL  distribute:%dpx  "
                "cr_w=%d  char_w=%d  cols~%d  max_line=%dch  n_lines=%d  "
                "total_code_h=%d  scroll_needed=%s  max_scroll=%d  "
                "font=%s %dpx  fill=%.1f%%",
                "ON" if auto_enabled else "OFF",
                cr_h, line_h,
                max_vis_preview, remainder_preview,
                cr_w, renderer.char_w, chars_per_line, max_line_len, n_lines,
                code_h,
                "yes" if n_lines > max_vis_preview else "no",
                max_scroll_preview,
                renderer.font_family, renderer.font_size,
                max_vis_preview * line_h / cr_h * 100 if cr_h else 0,
            )
            # Show estimated video duration
            dur = animator.duration()
            if dur < 60:
                dur_text = f"{dur:.1f}s"
            else:
                m = int(dur) // 60
                s = dur - m * 60
                dur_text = f"{m}m {s:.1f}s"
            self._preview_duration_lbl.setText(f"Duration: {dur_text}")
            self._frame_lbl.setText(
                f"{self._preview_progress*100:.0f}%  ({nv}/{total_chars})"
            )
            self._frame_slider.blockSignals(True)
            self._frame_slider.setValue(int(self._preview_progress * 100))
            self._frame_slider.blockSignals(False)
        except Exception as e:
            log.warning("Inline preview failed: %s", e, exc_info=True)

    def _schedule_preview_update(self):
        """Debounced preview update triggered by settings changes."""
        if self._loading_settings:
            return
        if not hasattr(self, "_preview_update_timer"):
            self._preview_update_timer = QTimer(self)
            self._preview_update_timer.setSingleShot(True)
            self._preview_update_timer.setInterval(400)
            self._preview_update_timer.timeout.connect(self._update_preview)
        self._preview_update_timer.start()

    def _on_preview_slider(self, value):
        self._stop_preview_animation()
        self._preview_progress = value / 100.0
        self._update_preview()

    def _preview_prev(self):
        self._stop_preview_animation()
        self._preview_progress = max(0, self._preview_progress - 0.05)
        self._update_preview()

    def _preview_next(self):
        self._stop_preview_animation()
        self._preview_progress = min(1.0, self._preview_progress + 0.05)
        self._update_preview()

    def _toggle_preview_animation(self):
        if self._preview_animating:
            self._stop_preview_animation()
        else:
            self._preview_animating = True
            self._play_btn.setText("⏸ Pause")
            # Ensure preview cache is populated, then use cached animator
            # instead of re-reading files and re-creating objects every click.
            self._update_preview()
            if self._cached_preview_animator is not None:
                self._preview_anim_t = (
                    self._cached_preview_animator.duration() * self._preview_progress
                )
            self._preview_timer.start()

    def _advance_preview_animation(self):
        dt = 0.05
        self._preview_anim_t += dt
        # Use cached animator (no file re-read / re-creation per tick)
        if self._cached_preview_animator is None:
            self._stop_preview_animation()
            return
        total = self._cached_preview_animator.duration()
        if self._preview_anim_t >= total:
            self._preview_anim_t = total
            self._stop_preview_animation()
        self._preview_progress = min(1.0, self._preview_anim_t / total)
        self._update_preview()

    def _stop_preview_animation(self):
        self._preview_animating = False
        self._preview_timer.stop()
        self._play_btn.setText("▶ Animate")

    # ── Settings persistence ─────────────────────────────────────────

    def _connect_settings_signals(self):
        """Connect all settings widgets so any change auto-saves and updates preview."""
        self.theme_cb.currentTextChanged.connect(self._auto_save_settings)
        self.theme_cb.currentTextChanged.connect(self._invalidate_preview_cache)
        self.theme_cb.currentTextChanged.connect(self._schedule_preview_update)
        self.res_cb.currentTextChanged.connect(self._auto_save_settings)
        self.res_cb.currentTextChanged.connect(self._invalidate_preview_cache)
        self.res_cb.currentTextChanged.connect(self._schedule_preview_update)
        self.wpm_sp.valueChanged.connect(self._auto_save_settings)
        self.wpm_sp.valueChanged.connect(self._invalidate_preview_cache)
        self.fps_sp.valueChanged.connect(self._auto_save_settings)
        self.start_pause_sp.valueChanged.connect(self._auto_save_settings)
        self.start_pause_sp.valueChanged.connect(self._invalidate_preview_cache)
        self.start_pause_sp.valueChanged.connect(self._schedule_preview_update)
        self.end_pause_sp.valueChanged.connect(self._auto_save_settings)
        self.end_pause_sp.valueChanged.connect(self._invalidate_preview_cache)
        self.end_pause_sp.valueChanged.connect(self._schedule_preview_update)
        self.font_family_cb.currentTextChanged.connect(self._auto_save_settings)
        self.font_family_cb.currentTextChanged.connect(self._invalidate_preview_cache)
        self.font_family_cb.currentTextChanged.connect(self._schedule_preview_update)
        self.font_size_auto_chk.toggled.connect(self._auto_save_settings)
        self.font_size_auto_chk.toggled.connect(self._invalidate_preview_cache)
        self.font_size_auto_chk.toggled.connect(self._schedule_preview_update)
        self.font_size_sp.valueChanged.connect(self._auto_save_settings)
        self.font_size_sp.valueChanged.connect(self._invalidate_preview_cache)
        self.font_size_sp.valueChanged.connect(self._schedule_preview_update)
        self.sound_chk.toggled.connect(self._auto_save_settings)
        self.vol_sl.valueChanged.connect(self._auto_save_settings)
        self.sound_preset_cb.currentTextChanged.connect(self._auto_save_settings)
        self.kb_overlay_chk.toggled.connect(self._auto_save_settings)
        self.kb_overlay_chk.toggled.connect(self._invalidate_preview_cache)
        self.kb_overlay_chk.toggled.connect(self._schedule_preview_update)
        self.kb_layout_cb.currentTextChanged.connect(self._auto_save_settings)
        self.kb_layout_cb.currentTextChanged.connect(self._invalidate_preview_cache)
        self.kb_layout_cb.currentTextChanged.connect(self._schedule_preview_update)
        self.kb_position_cb.currentTextChanged.connect(self._auto_save_settings)
        self.kb_position_cb.currentTextChanged.connect(self._invalidate_preview_cache)
        self.kb_position_cb.currentTextChanged.connect(self._schedule_preview_update)
        self.recurse_chk.toggled.connect(self._auto_save_settings)
        self.depth_sp.valueChanged.connect(self._auto_save_settings)
        self.title_auto_chk.toggled.connect(self._auto_save_settings)
        self.title_edit.textChanged.connect(self._auto_save_settings)
        self.title_edit.textChanged.connect(self._invalidate_preview_cache)
        self.title_edit.textChanged.connect(self._schedule_preview_update)
        self.padding_sp.valueChanged.connect(self._auto_save_settings)
        self.padding_sp.valueChanged.connect(self._invalidate_preview_cache)
        self.padding_sp.valueChanged.connect(self._schedule_preview_update)
        self.chrome_chk.toggled.connect(self._auto_save_settings)
        self.chrome_chk.toggled.connect(self._invalidate_preview_cache)
        self.chrome_chk.toggled.connect(self._schedule_preview_update)
        self.line_numbers_chk.toggled.connect(self._auto_save_settings)
        self.line_numbers_chk.toggled.connect(self._invalidate_preview_cache)
        self.line_numbers_chk.toggled.connect(self._schedule_preview_update)
        self._guide_padding_chk.toggled.connect(self._schedule_preview_update)
        self._guide_chrome_chk.toggled.connect(self._schedule_preview_update)
        self._guide_code_chk.toggled.connect(self._schedule_preview_update)
        self._guide_kb_chk.toggled.connect(self._schedule_preview_update)
        self._guide_gap_chk.toggled.connect(self._schedule_preview_update)

    def _auto_save_settings(self, *_args):
        """Slot that saves settings whenever any widget changes (debounced)."""
        if self._loading_settings:
            return
        # Debounce: restart a single-shot timer on every change
        if not hasattr(self, "_save_timer"):
            self._save_timer = QTimer(self)
            self._save_timer.setSingleShot(True)
            self._save_timer.setInterval(300)
            self._save_timer.timeout.connect(self._save_settings)
        self._save_timer.start()

    def _save_settings(self):
        """Persist current widget values to SETTINGS_FILE as JSON."""
        try:
            data = {
                "theme": self.theme_cb.currentText(),
                "resolution": self.res_cb.currentText(),
                "wpm": self.wpm_sp.value(),
                "fps": self.fps_sp.value(),
                "start_pause": self.start_pause_sp.value(),
                "end_pause": self.end_pause_sp.value(),
                "font_family": self.font_family_cb.currentText(),
                "font_size_auto": self.font_size_auto_chk.isChecked(),
                "font_size": self.font_size_sp.value(),
                "sound_enabled": self.sound_chk.isChecked(),
                "volume": self.vol_sl.value(),
                "sound_preset": self.sound_preset_cb.currentText(),
                "kb_overlay": self.kb_overlay_chk.isChecked(),
                "kb_layout": self.kb_layout_cb.currentText(),
                "kb_position": self.kb_position_cb.currentText(),
                "recursive": self.recurse_chk.isChecked(),
                "depth": self.depth_sp.value(),
                "title_auto": self.title_auto_chk.isChecked(),
                "title_custom": self.title_edit.text(),
                "padding": self.padding_sp.value(),
                "show_chrome": self.chrome_chk.isChecked(),
                "show_line_numbers": self.line_numbers_chk.isChecked(),
            }
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            log.debug("Settings saved to %s", SETTINGS_FILE)
        except Exception as e:
            log.warning("Failed to save settings: %s", e)

    def _load_settings(self):
        """Load previously saved settings from SETTINGS_FILE and apply to widgets."""
        if not os.path.isfile(SETTINGS_FILE):
            return
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Failed to load settings: %s", e)
            return

        self._loading_settings = True
        try:
            if "theme" in data and data["theme"] in THEMES:
                self.theme_cb.setCurrentText(data["theme"])
            if "resolution" in data and data["resolution"] in RESOLUTIONS:
                self.res_cb.setCurrentText(data["resolution"])
            if "wpm" in data:
                self.wpm_sp.setValue(int(data["wpm"]))
            if "fps" in data:
                self.fps_sp.setValue(int(data["fps"]))
            if "start_pause" in data:
                self.start_pause_sp.setValue(float(data["start_pause"]))
            if "end_pause" in data:
                self.end_pause_sp.setValue(float(data["end_pause"]))
            if "sound_enabled" in data:
                self.sound_chk.setChecked(bool(data["sound_enabled"]))
            if "volume" in data:
                self.vol_sl.setValue(int(data["volume"]))
            if "sound_preset" in data and data["sound_preset"] in SOUND_PRESETS:
                self.sound_preset_cb.setCurrentText(data["sound_preset"])
            if "kb_overlay" in data:
                self.kb_overlay_chk.setChecked(bool(data["kb_overlay"]))
            if "kb_layout" in data and data["kb_layout"] in KEYBOARD_LAYOUTS:
                self.kb_layout_cb.setCurrentText(data["kb_layout"])
            if "kb_position" in data and data["kb_position"] in self._KB_POS_MAP:
                self.kb_position_cb.setCurrentText(data["kb_position"])
            if "font_family" in data:
                idx = self.font_family_cb.findText(data["font_family"])
                if idx >= 0:
                    self.font_family_cb.setCurrentIndex(idx)
            if "font_size_auto" in data:
                self.font_size_auto_chk.setChecked(bool(data["font_size_auto"]))
            if "font_size" in data:
                self.font_size_sp.setValue(int(data["font_size"]))
            if "recursive" in data:
                self.recurse_chk.setChecked(bool(data["recursive"]))
            if "depth" in data:
                self.depth_sp.setValue(int(data["depth"]))
            if "title_auto" in data:
                self.title_auto_chk.setChecked(bool(data["title_auto"]))
            if "title_custom" in data:
                self.title_edit.setText(str(data["title_custom"]))
            if "padding" in data:
                self.padding_sp.setValue(int(data["padding"]))
            if "show_chrome" in data:
                self.chrome_chk.setChecked(bool(data["show_chrome"]))
            if "show_line_numbers" in data:
                self.line_numbers_chk.setChecked(bool(data["show_line_numbers"]))
            log.debug("Settings loaded from %s", SETTINGS_FILE)
        finally:
            self._loading_settings = False

    def closeEvent(self, event):
        """Save settings before the window closes."""
        self._save_settings()
        super().closeEvent(event)

    # ── File scanning ───────────────────────────────────────────────

    def _scan_input_dir(self):
        """Scan the default input/ folder, optionally recursing into subfolders."""
        self._scan_directory(INPUT_DIR)

    def _scan_folder(self):
        """Let the user pick a custom root folder to scan."""
        folder = QFileDialog.getExistingDirectory(
            self, "Select Root Folder to Scan", INPUT_DIR,
        )
        if folder:
            self._scan_directory(folder)

    def _scan_directory(self, root_dir: str):
        """Recursively scan a directory for code files."""
        self._items.clear()
        if not os.path.isdir(root_dir):
            self.statusBar().showMessage(f"Folder not found: {root_dir}")
            self._refresh_table()
            return

        max_depth = self.depth_sp.value() if self.recurse_chk.isChecked() else 1
        found: List[FileItem] = []

        for dirpath, dirnames, filenames in os.walk(root_dir):
            # Compute depth relative to root
            rel = os.path.relpath(dirpath, root_dir)
            if rel == ".":
                depth = 1
            else:
                depth = rel.count(os.sep) + 2

            if depth > max_depth:
                # Prune deeper subdirectories
                dirnames.clear()
                continue

            # Filter out skipped directories in-place (affects os.walk recursion)
            dirnames[:] = [
                d for d in dirnames
                if d not in _SKIP_DIRS and not d.startswith(".")
            ]

            for fname in sorted(filenames):
                ext = os.path.splitext(fname)[1].lower()
                if ext in SUPPORTED_EXTENSIONS:
                    fpath = os.path.join(dirpath, fname)
                    found.append(FileItem(path=fpath))

        self._items = found
        self._item_paths = {it.path for it in found}
        self._refresh_table()

        recurse_note = f" (depth ≤ {max_depth})" if self.recurse_chk.isChecked() else " (top-level only)"
        self.file_count_lbl.setText(f"{len(self._items)} file(s) found{recurse_note}")
        self.statusBar().showMessage(
            f"Found {len(self._items)} code file(s) in {root_dir}{recurse_note}"
        )

    def _add_files(self):
        ext_str = " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTENSIONS))
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Code Files", "",
            f"Code Files ({ext_str});;All Files (*)",
        )
        for p in paths:
            if p not in self._item_paths:
                item = FileItem(path=p)
                self._items.append(item)
                self._item_paths.add(p)
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
            self._invalidate_preview_cache()
            self._schedule_preview_update()

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

            # Relative path (show relative to CWD or absolute for external files)
            try:
                rel = os.path.relpath(item.path, CWD)
                display_path = rel if not rel.startswith("..") else item.path
            except ValueError:
                display_path = item.path
            path_item = QTableWidgetItem(display_path)
            path_item.setToolTip(item.path)  # full path in tooltip
            self.table.setItem(i, 1, path_item)

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

        _pad = self.padding_sp.value()
        _chrome = self.chrome_chk.isChecked()
        _ln = self.line_numbers_chk.isChecked()
        _chosen_font = self.font_family_cb.currentText()

        if self.font_size_auto_chk.isChecked():
            font_size = CodeRenderer.auto_font_size(
                code_lines=code.count("\n") + 1,
                width=w, height=h,
                code=code,
                font_family=_chosen_font,
                padding=_pad, show_window_chrome=_chrome,
                show_line_numbers=_ln,
            )
        else:
            font_size = self.font_size_sp.value()

        if self.title_auto_chk.isChecked():
            title = f"{os.path.basename(item.path)} - Code Editor"
        else:
            custom = self.title_edit.text().strip()
            title = custom if custom else f"{os.path.basename(item.path)} - Code Editor"

        # Keyboard overlay
        kb_overlay = None
        kb_h = 0
        if self.kb_overlay_chk.isChecked():
            layout_name = self.kb_layout_cb.currentText()
            kb_overlay = KeyboardOverlay(
                video_w=w, video_h=h,
                layout_name=layout_name,
                theme=THEMES.get(self.theme_cb.currentText(), THEMES["Dracula"]),
                max_height=(h - 2 * _pad) // 3,
                position=self._kb_position_key(),
            )
            kb_h = kb_overlay.height_needed()
            # Recalculate font size with keyboard space reserved
            if self.font_size_auto_chk.isChecked():
                font_size = CodeRenderer.auto_font_size(
                    code_lines=code.count("\n") + 1,
                    width=w, height=h,
                    code=code,
                    font_family=_chosen_font,
                    keyboard_h=kb_h,
                    padding=_pad, show_window_chrome=_chrome,
                    show_line_numbers=_ln,
                )

        renderer = CodeRenderer(
            width=w, height=h,
            theme_name=self.theme_cb.currentText(),
            font_family=_chosen_font,
            font_size=font_size,
            title_text=title,
            language=language,
            keyboard_overlay=kb_overlay,
            padding=_pad,
            show_window_chrome=_chrome,
            show_line_numbers=_ln,
            total_code_lines=code.count("\n") + 1,
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

        sound_gen = SimpleSoundGen(preset=self.sound_preset_cb.currentText()) if self.sound_chk.isChecked() else None

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
        self._exporter.finished.connect(self._on_exporter_thread_done)
        self._exporter.start()

    def _on_item_done(self, item: FileItem, path: str):
        item.status = "Done"
        item.output_path = path
        self._refresh_table()
        # Do NOT set self._exporter = None here - the thread may still be
        # tearing down.  Cleanup happens in _on_exporter_thread_done which
        # is connected to the built-in QThread.finished signal.
        self._export_next()

    def _on_item_failed(self, item: FileItem, err: str):
        item.status = "Failed"
        item.error = err
        self._refresh_table()
        # Do NOT set self._exporter = None here - see _on_item_done.
        self._export_next()

    def _on_exporter_thread_done(self):
        """Built-in QThread.finished handler - safe to drop the reference now.

        This fires *after* run() has returned and the thread has fully stopped,
        unlike our custom finished_ok / error signals which are emitted inside
        run() before the finally-block runs.
        """
        exp = self.sender()
        if exp is not None and self._exporter is exp:
            self._exporter = None

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
QPushButton#previewBtn {
    background: #a6e3a1; color: #1e1e2e; font-weight: bold;
    border: none; padding: 6px 14px; font-size: 12px;
}
QPushButton#previewBtn:hover { background: #94e2d5; }
QPushButton#previewBtn:disabled { background: #45475a; color: #585b70; }
QProgressBar {
    background: #313244; border: none; border-radius: 4px;
    text-align: center; color: #cdd6f4; min-height: 20px;
}
QProgressBar::chunk { background: #89b4fa; border-radius: 4px; }
QTabWidget::pane {
    border: 1px solid #45475a; border-radius: 6px;
    background: #1e1e2e; top: -1px;
}
QTabBar::tab {
    background: #313244; color: #a6adc8; padding: 8px 18px;
    border: 1px solid #45475a; border-bottom: none;
    border-top-left-radius: 6px; border-top-right-radius: 6px;
    font-size: 12px; font-weight: bold; margin-right: 2px;
}
QTabBar::tab:selected {
    background: #1e1e2e; color: #cdd6f4; border-bottom: 2px solid #89b4fa;
}
QTabBar::tab:hover:!selected {
    background: #45475a; color: #cdd6f4;
}
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