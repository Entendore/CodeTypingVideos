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
import json
import logging
import math
import os
import random
import re
import subprocess
import sys
import tempfile
import threading
import unicodedata
import wave
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

import numpy as np
from PySide6.QtCore import (
    QEvent, QPoint, QRect, Qt, QThread, Signal, QTimer,
)
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QImage, QLinearGradient, QPainter, QPalette,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
    QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QSizePolicy, QSpinBox, QSplitter, QStatusBar, QStyleFactory,
    QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
    QScrollArea,
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
SETTINGS_FILE = os.path.join(CWD, "sctvg_settings.json")

for _d in (INPUT_DIR, OUTPUT_DIR, TMP_DIR):
    os.makedirs(_d, exist_ok=True)

# ── supported extensions & language map ─────────────────────────────

SUPPORTED_EXTENSIONS = frozenset({
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h",
    ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt",
    ".sh", ".bash", ".zsh", ".sql", ".html", ".css", ".scss", ".json",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".txt", ".md",
    ".lua", ".dart", ".r", ".m",
    ".po", ".properties", ".rst", ".tex", ".log",
    ".pyi", ".pyw", ".pyx", ".pxd",
    ".vue", ".svelte",
    ".swift",
})

EXT_TO_LANGUAGE: dict[str, str] = {
    ".py": "Python", ".pyi": "Python", ".pyw": "Python", ".pyx": "Python",
    ".js": "JavaScript", ".jsx": "JavaScript", ".vue": "JavaScript",
    ".svelte": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
    ".java": "CFamily", ".c": "CFamily", ".cpp": "CFamily",
    ".h": "CFamily", ".hpp": "CFamily", ".cs": "CFamily",
    ".go": "Go", ".rs": "Rust",
    ".swift": "Swift", ".kt": "Kotlin",
    ".rb": "Ruby", ".php": "PHP",
    ".lua": "Lua", ".dart": "Dart", ".r": "R", ".m": "ObjectiveC",
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell",
    ".sql": "SQL", ".html": "HTML", ".css": "CSS", ".scss": "CSS",
    ".json": "JSON", ".yaml": "YAML", ".yml": "YAML",
    ".toml": "TOML", ".ini": "INI", ".cfg": "INI",
    ".md": "Markdown", ".rst": "Markdown", ".tex": "LaTeX",
    ".txt": "PlainText", ".log": "PlainText",
    ".po": "PlainText", ".properties": "INI",
}

# ── Folders to exclude during recursive scan ────────────────────────

EXCLUDED_DIRS = frozenset({
    "__pycache__", ".git", ".hg", ".svn", "node_modules", "venv",
    ".venv", "env", ".env", ".tox", ".mypy_cache", ".pytest_cache",
    "dist", "build", ".egg-info", ".idea", ".vscode", "target",
    ".next", ".nuxt", "coverage", ".turbo",
})


def _scan_dir_recursive(
    base_dir: str,
    max_depth: int = -1,
    excluded_dirs: frozenset = EXCLUDED_DIRS,
    extensions: frozenset = SUPPORTED_EXTENSIONS,
) -> List[str]:
    """Walk *base_dir* recursively and return absolute paths of matching files.

    Parameters
    ----------
    base_dir : str
        Root folder to scan.
    max_depth : int
        Maximum subfolder depth (-1 = unlimited, 0 = top-level only).
    excluded_dirs : frozenset
        Directory names to skip entirely.
    extensions : frozenset
        File extensions to include.
    """
    results: List[str] = []
    for dirpath, dirnames, filenames in os.walk(base_dir):
        # Compute depth relative to base_dir
        rel = os.path.relpath(dirpath, base_dir)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if max_depth >= 0 and depth > max_depth:
            dirnames.clear()  # prevent descending further
            continue
        # Prune excluded directories in-place
        dirnames[:] = [
            d for d in dirnames
            if d not in excluded_dirs
        ]
        for fname in sorted(filenames):
            ext = os.path.splitext(fname)[1].lower()
            if ext in extensions:
                results.append(os.path.join(dirpath, fname))
    return results

# ── resolution presets ──────────────────────────────────────────────

RESOLUTIONS: Dict[str, Tuple[int, int]] = {
    "1920x1080": (1920, 1080),
    "1280x720":  (1280, 720),
    "3840x2160": (3840, 2160),
    "1080x1920 (9:16)": (1080, 1920),
}

# ── supported font families (with CJK / multilingual support) ──────

SUPPORTED_FONTS: List[Dict[str, str]] = [
    {"name": "Consolas",           "label": "Consolas (Latin only)"},
    {"name": "Monaco",             "label": "Monaco (Latin only)"},
    {"name": "Courier New",        "label": "Courier New (Latin only)"},
    {"name": "DejaVu Sans Mono",   "label": "DejaVu Sans Mono (Latin + symbols)"},
    {"name": "Noto Sans Mono",     "label": "Noto Sans Mono (Latin + CJK)"},
    {"name": "Noto Sans Mono CJK SC", "label": "Noto Sans Mono CJK SC (Chinese)"},
    {"name": "Noto Sans Mono CJK JP", "label": "Noto Sans Mono CJK JP (Japanese)"},
    {"name": "Noto Sans Mono CJK KR", "label": "Noto Sans Mono CJK KR (Korean)"},
    {"name": "Source Han Mono",    "label": "Source Han Mono (CJK all)"},
    {"name": "Source Code Pro",    "label": "Source Code Pro (Latin + CJK fallback)"},
    {"name": "LXGW WenKai Mono",   "label": "LXGW WenKai Mono (Chinese, artistic)"},
    {"name": "MS Gothic",          "label": "MS Gothic (Japanese)"},
    {"name": "Malgun Gothic",      "label": "Malgun Gothic (Korean)"},
    {"name": "Arial Unicode MS",   "label": "Arial Unicode MS (Universal)"},
    {"name": "Sarasa Mono SC",     "label": "Sarasa Mono SC (Latin + Chinese)"},
    {"name": "Sarasa Mono JP",     "label": "Sarasa Mono JP (Latin + Japanese)"},
]

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
    # ── Shell / Bash ────────────────────────────────────────────────
    "Shell": {
        "keywords": {
            "if", "then", "else", "elif", "fi", "for", "while", "until",
            "do", "done", "case", "esac", "in", "function", "select",
            "time", "coproc", "|", "&&", "||", "!", "break", "continue",
            "return", "exit", "export", "local", "readonly", "declare",
            "typeset", "unset", "shift", "source", "alias", "true", "false",
            "echo", "cd", "ls", "grep", "sed", "awk", "cat", "mkdir",
            "rm", "cp", "mv", "chmod", "chown", "find", "sort", "wc",
            "head", "tail", "curl", "wget", "make", "apt", "yum", "npm",
            "pip", "git", "docker", "sudo",
        },
        "builtins": set(),
        "extra_patterns": [
            ("keyword", r"\$\{[^}]+\}"),   # variable expansion
            ("keyword", r"\$\([^)]+\)"),   # command substitution
            ("string", r"\"(?:[^\"\\]|\\.)*\""),
            ("string", r"'[^']*'"),
        ],
        "comment": r"#[^\n]*",
        "string":  r"\"(?:[^\"\\]|\\.)*\"|'[^']*'",
        "number":  r"\b\d+\b",
    },
    # ── SQL ─────────────────────────────────────────────────────────
    "SQL": {
        "keywords": {
            "select", "from", "where", "insert", "into", "values", "update",
            "set", "delete", "create", "table", "drop", "alter", "add",
            "column", "index", "view", "join", "inner", "left", "right",
            "outer", "on", "and", "or", "not", "in", "between", "like",
            "is", "null", "as", "order", "by", "group", "having", "limit",
            "offset", "union", "all", "distinct", "case", "when", "then",
            "else", "end", "exists", "primary", "key", "foreign", "references",
            "constraint", "default", "check", "unique", "asc", "desc",
            "count", "sum", "avg", "min", "max", "true", "false",
            "begin", "commit", "rollback", "transaction", "grant", "revoke",
            "truncate", "if", "replace", "with", "recursive",
        },
        "builtins": set(),
        "extra_patterns": [
            ("builtin", r"\b(?:int|integer|text|varchar|char|boolean|float|double|date|datetime|timestamp|blob|serial|bigserial|numeric|decimal|real|uuid|json|jsonb|array)\b"),
        ],
        "comment": r"--[^\n]*|/\*[\s\S]*?\*/",
        "string":  r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"",
        "number":  r"\b\d+\.?\d*(?:e[+-]?\d+)?\b",
    },
    # ── HTML ────────────────────────────────────────────────────────
    "HTML": {
        "keywords": set(),
        "builtins": set(),
        "extra_patterns": [
            ("keyword", r"</?[a-zA-Z][a-zA-Z0-9-]*(?:\s[^>]*)?>"),
            ("string",  r"(?:src|href|alt|class|id|style|type|name|value|placeholder|action|method|rel|lang|charset|content|http-equiv|data-[a-zA-Z-]+)\s*=\s*(?:\"[^\"]*\"|'[^']*')"),
        ],
        "comment": r"<!--[\s\S]*?-->",
        "string":  r"\"[^\"]*\"|'[^']*'",
        "number":  r"\b\d+\b",
    },
    # ── CSS / SCSS ──────────────────────────────────────────────────
    "CSS": {
        "keywords": {
            "important", "media", "keyframes", "import", "charset", "font-face",
            "supports", "layer", "container",
        },
        "builtins": {
            "inherit", "initial", "unset", "none", "auto", "block", "inline",
            "flex", "grid", "inline-block", "inline-flex", "table", "absolute",
            "relative", "fixed", "sticky", "static", "hidden", "visible",
            "solid", "dashed", "dotted", "transparent", "currentColor",
            "ease", "linear", "ease-in", "ease-out", "ease-in-out",
            "bold", "normal", "italic", "uppercase", "lowercase", "capitalize",
            "left", "right", "center", "justify", "top", "bottom", "middle",
            "wrap", "nowrap", "break-word", "ellipsis", "clip",
            "pointer", "default", "not-allowed", "grab",
            "border-box", "content-box", "padding-box",
            "cover", "contain", "scroll", "no-repeat", "repeat",
        },
        "extra_patterns": [
            ("function", r"@[a-zA-Z-]+\b"),  # @media, @keyframes, etc.
            ("function", r"var\(\s*--[\w-]+\s*\)"),
            ("function", r"(?:calc|rgba?|hsla?|linear-gradient|radial-gradient|clamp|min|max|minmax|repeat|url|env)\s*\([^)]*\)"),
            ("class_name", r"#[a-zA-Z_-][\w-]*"),  # ID selector
            ("class_name", r"\.[a-zA-Z_-][\w-]*"),  # class selector
        ],
        "comment": r"/\*[\s\S]*?\*/",
        "string":  r"\"(?:[^\"\\]|\\.)*\"|'[^']*'",
        "number":  r"\b\d+\.?\d*(?:px|em|rem|vh|vw|%|deg|s|ms|fr)?\b",
    },
    # ── Markdown ────────────────────────────────────────────────────
    "Markdown": {
        "keywords": set(),
        "builtins": set(),
        "extra_patterns": [
            ("keyword",  r"^#{1,6}\s+.*$"),
            ("keyword",  r"^\s*[-*+]\s"),
            ("keyword",  r"^\s*\d+\.\s"),
            ("keyword",  r"\*\*[^*]+\*\*"),
            ("keyword",  r"\*[^*]+\*"),
            ("keyword",  r"__[^_]+__"),
            ("keyword",  r"_[^_]+_"),
            ("keyword",  r"`[^`]+`"),
            ("keyword",  r"```[\s\S]*?```"),
            ("string",   r"\[([^\]]+)\]\(([^)]+)\)"),
            ("string",   r"!\[([^\]]*)\]\(([^)]+)\)"),
            ("comment",  r"^>\s.*$"),
        ],
        "comment": r"^>\s.*$",
        "string":  r"\[([^\]]+)\]\(([^)]+)\)",
        "number":  r"\b\d+\b",
    },
    # ── JSON ────────────────────────────────────────────────────────
    "JSON": {
        "keywords": {"true", "false", "null"},
        "builtins": set(),
        "extra_patterns": [],
        "comment": r"(?!x)x",  # JSON has no comments
        "string":  r'"(?:[^"\\]|\\.)*"',
        "number":  r"-?\b\d+\.?\d*(?:e[+-]?\d+)?\b",
    },
    # ── YAML / TOML / INI (minimal highlighting) ────────────────────
    "YAML": {
        "keywords": {"true", "false", "null", "yes", "no", "on", "off"},
        "builtins": set(),
        "extra_patterns": [
            ("keyword", r"^[a-zA-Z_][\w-]*\s*:"),
            ("string",  r"\"(?:[^\"\\]|\\.)*\"|'[^']*'"),
        ],
        "comment": r"#[^\n]*",
        "string":  r"\"(?:[^\"\\]|\\.)*\"|'[^']*'",
        "number":  r"\b\d+\.?\d*(?:e[+-]?\d+)?\b",
    },
    "TOML": {
        "keywords": {"true", "false"},
        "builtins": set(),
        "extra_patterns": [
            ("keyword", r"^\[[^\]]+\]"),
            ("keyword", r"^[a-zA-Z_][\w-]*\s*="),
            ("string",  r"\"(?:[^\"\\]|\\.)*\"|'[^']*'"),
        ],
        "comment": r"#[^\n]*",
        "string":  r"\"(?:[^\"\\]|\\.)*\"|'[^']*'",
        "number":  r"\b\d+\.?\d*(?:e[+-]?\d+)?\b",
    },
    "INI": {
        "keywords": set(),
        "builtins": set(),
        "extra_patterns": [
            ("keyword", r"^\[[^\]]+\]"),
            ("keyword", r"^[a-zA-Z_][\w.-]*\s*="),
        ],
        "comment": r"#[^\n]*|;[^\n]*",
        "string":  r"\"(?:[^\"\\]|\\.)*\"|'[^']*'",
        "number":  r"\b\d+\.?\d*(?:e[+-]?\d+)?\b",
    },
    # ── Plain text / CJK / multilingual (minimal highlighting) ──────
    "PlainText": {
        "keywords": set(),
        "builtins": set(),
        "extra_patterns": [],
        "comment": r"(?!x)x",
        "string":  r"(?!x)x",
        "number":  r"\b\d+\.?\d*(?:e[+-]?\d+)?\b",
    },
    # ── Additional programming languages ────────────────────────────
    "Swift": {
        "keywords": {
            "import", "let", "var", "func", "class", "struct", "enum",
            "protocol", "extension", "if", "else", "switch", "case",
            "for", "in", "while", "return", "break", "continue",
            "guard", "where", "typealias", "associatedtype", "init",
            "deinit", "self", "super", "nil", "true", "false",
            "as", "is", "try", "catch", "throw", "throws", "rethrows",
            "defer", "do", "public", "private", "internal", "fileprivate",
            "open", "static", "override", "final", "lazy", "weak", "unowned",
            "optional", "required", "convenience", "subscript", "operator",
            "precedencegroup", "indirect", "mutating", "nonmutating",
            "inout", "@available", "@escaping", "@autoclosure", "@discardableResult",
            "async", "await", "some", "any",
        },
        "builtins": {
            "print", "Array", "Dictionary", "Set", "String", "Int", "Double",
            "Float", "Bool", "Character", "Optional", "Result", "Range",
            "stride", "map", "filter", "reduce", "compactMap", "flatMap",
            "sorted", "reversed", "enumerate", "zip", "min", "max", "abs",
            "import", "type", "Value", "Key",
        },
        "extra_patterns": [
            ("decorator", r"@[a-zA-Z_]\w*"),
        ],
        "comment": r"//[^\n]*|/\*[\s\S]*?\*/",
        "string":  r'"""[\s\S]*?"""|"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'',
        "number":  r"\b\d+\.?\d*(?:e[+-]?\d+)?\b|0x[0-9a-fA-F]+\b",
    },
    "Kotlin": {
        "keywords": {
            "package", "import", "class", "object", "interface", "enum",
            "fun", "val", "var", "if", "else", "when", "for", "while",
            "do", "return", "break", "continue", "is", "as", "in", "!in",
            "typealias", "this", "super", "null", "true", "false",
            "try", "catch", "finally", "throw", "throws",
            "public", "private", "protected", "internal", "open", "abstract",
            "final", "override", "sealed", "data", "inner", "companion",
            "inline", "reified", "crossinline", "noinline", "tailrec",
            "suspend", "operator", "infix", "by", "lazy", "lateinit",
            "init", "constructor", "where", "out", "in", "vararg",
            "async", "await",
        },
        "builtins": {
            "println", "print", "readLine", "IntArray", "DoubleArray",
            "String", "Int", "Long", "Double", "Float", "Boolean", "Unit",
            "Any", "Nothing", "List", "MutableList", "Map", "MutableMap",
            "Set", "MutableSet", "Pair", "Triple", "lazy", "run", "let",
            "also", "apply", "with", "use", "sequence", "generateSequence",
            "require", "check", "error", "TODO",
        },
        "extra_patterns": [],
        "comment": r"//[^\n]*|/\*[\s\S]*?\*/",
        "string":  r'\"\"\"[\s\S]*?\"\"\"|"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'',
        "number":  r"\b\d+\.?\d*(?:e[+-]?\d+)?\b|0x[0-9a-fA-F]+\b",
    },
    "Ruby": {
        "keywords": {
            "alias", "and", "begin", "break", "case", "class", "def",
            "defined", "do", "else", "elsif", "end", "ensure", "for",
            "if", "in", "module", "next", "nil", "not", "or", "redo",
            "rescue", "retry", "return", "self", "super", "then", "undef",
            "unless", "until", "when", "while", "yield", "true", "false",
            "require", "include", "extend", "attr_reader", "attr_writer",
            "attr_accessor", "private", "protected", "public",
            "raise", "begin", "rescue", "ensure",
        },
        "builtins": {
            "puts", "print", "gets", "chomp", "to_s", "to_i", "to_f",
            "to_a", "to_h", "length", "size", "each", "map", "select",
            "reject", "reduce", "inject", "find", "all", "any", "none",
            "sort", "reverse", "uniq", "flatten", "compact", "first",
            "last", "min", "max", "sum", "join", "split", "strip",
            "upcase", "downcase", "capitalize", "gsub", "sub", "scan",
            "match", "format", "sprintf", "open", "file", "dir",
            "require", "require_relative", "load", "rand", "srand",
            "Integer", "Float", "String", "Array", "Hash", "Set", "Range",
            "Proc", "Lambda", "Method", "Symbol", "Regexp", "Thread",
            "class", "module", "block_given", "enum_for",
        },
        "extra_patterns": [
            ("decorator", r"@\w+"),
            ("string",   r':\w+'),
            ("string",   r'%[qQwWxsr]\{[^}]*\}'),
        ],
        "comment": r"#[^\n]*|=begin[\s\S]*?=end",
        "string":  r'\"\"\"[\s\S]*?\"\"\"|"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'',
        "number":  r"\b\d+\.?\d*(?:e[+-]?\d+)?\b|0x[0-9a-fA-F]+\b",
    },
    "PHP": {
        "keywords": {
            "if", "else", "elseif", "while", "do", "for", "foreach",
            "as", "switch", "case", "default", "break", "continue",
            "return", "function", "class", "new", "extends", "implements",
            "public", "private", "protected", "static", "abstract",
            "interface", "trait", "const", "var", "echo", "print",
            "use", "namespace", "require", "include", "require_once",
            "include_once", "true", "false", "null", "array", "try",
            "catch", "finally", "throw", "isset", "unset", "empty",
            "list", "yield", "fn", "match", "enum", "readonly",
        },
        "builtins": {
            "strlen", "substr", "strpos", "str_replace", "explode",
            "implode", "trim", "strtolower", "strtoupper", "ucfirst",
            "intval", "floatval", "strval", "is_array", "is_string",
            "is_int", "is_null", "count", "array_push", "array_pop",
            "array_map", "array_filter", "array_merge", "array_keys",
            "array_values", "in_array", "sort", "usort", "json_encode",
            "json_decode", "file_get_contents", "file_put_contents",
            "preg_match", "preg_replace", "date", "time", "mktime",
            "strlen", "var_dump", "print_r", "sprintf",
        },
        "extra_patterns": [
            ("keyword", r"\$\w+"),
            ("decorator", r"@\w+"),
        ],
        "comment": r"//[^\n]*|/\*[\s\S]*?\*/|#[^\n]*",
        "string":  r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'',
        "number":  r"\b\d+\.?\d*(?:e[+-]?\d+)?\b|0x[0-9a-fA-F]+\b",
    },
    "LaTeX": {
        "keywords": {
            "documentclass", "usepackage", "begin", "end", "section",
            "subsection", "subsubsection", "paragraph", "subparagraph",
            "chapter", "part", "title", "author", "date", "maketitle",
            "tableofcontents", "listoffigures", "listoftables",
            "figure", "table", "caption", "label", "ref", "cite",
            "bibliography", "bibliographystyle", "include", "input",
            "newcommand", "renewcommand", "newenvironment",
            "textbf", "textit", "emph", "underline", "texttt",
            "footnote", "marginpar", "item", "hline", "cline",
            "multicolumn", "multirow", "toprule", "midrule", "bottomrule",
        },
        "builtins": set(),
        "extra_patterns": [
            ("function", r"\\[a-zA-Z]+\*?"),  # LaTeX commands
            ("keyword",  r"\\[a-zA-Z]+\{[^}]*\}"),
            ("string",   r"\$[^\$]+\$"),       # inline math
            ("string",   r"\\text\{[^}]*\}"),
        ],
        "comment": r"%[^\n]*",
        "string":  r"\$[^\$]+\$",
        "number":  r"\b\d+\.?\d*\b",
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
# Multi-Preset Sound Generator
# =====================================================================

def _normalise(samples: np.ndarray, target_peak: float = 0.7) -> np.ndarray:
    """Normalise samples to int16 range with a target peak fraction."""
    peak = np.max(np.abs(samples))
    if peak > 0:
        samples = samples / peak * 32767 * target_peak
    return samples.astype(np.int16)


# ── Individual sound synthesis helpers ─────────────────────────────

def _synth_mechanical_click(sr: int, seed: int) -> np.ndarray:
    """Modern mechanical keyboard switch click."""
    rng = np.random.RandomState(seed)
    dur = 0.06
    n = int(sr * dur)
    t = np.linspace(0, dur, n, False)
    noise = rng.randn(n) * np.exp(-t * 500) * 0.4
    freq = 3500 + rng.randint(-300, 300)
    click = np.sin(2 * np.pi * freq * t) * np.exp(-t * 400) * 0.5
    thud = np.sin(2 * np.pi * 200 * t) * np.exp(-t * 150) * 0.3
    return _normalise(noise + click + thud)


def _synth_typewriter_click(sr: int, seed: int) -> np.ndarray:
    """Vintage typewriter: sharp metal strike + long mechanical ring."""
    rng = np.random.RandomState(seed)
    dur = 0.10
    n = int(sr * dur)
    t = np.linspace(0, dur, n, False)
    # Sharp metal impact
    impact = rng.randn(n) * np.exp(-t * 1200) * 0.6
    freq = 2200 + rng.randint(-200, 200)
    strike = np.sin(2 * np.pi * freq * t) * np.exp(-t * 800) * 0.5
    # Long ring / resonance
    ring_freq = 800 + rng.randint(-100, 100)
    ring = np.sin(2 * np.pi * ring_freq * t) * np.exp(-t * 40) * 0.25
    # Mechanical carriage rattle
    rattle = rng.randn(n) * np.exp(-t * 60) * 0.08
    return _normalise(impact + strike + ring + rattle)


def _synth_circus_click(sr: int, seed: int) -> np.ndarray:
    """Circus / carnival: bright, bouncy, musical pings."""
    rng = np.random.RandomState(seed)
    dur = 0.12
    n = int(sr * dur)
    t = np.linspace(0, dur, n, False)
    # Two-tone ping (like a calliope key)
    f1 = 1200 + rng.randint(0, 400)
    f2 = f1 * 1.5  # perfect fifth
    tone = (
        np.sin(2 * np.pi * f1 * t) * 0.35
        + np.sin(2 * np.pi * f2 * t) * 0.25
    ) * np.exp(-t * 80)
    # Bright pluck
    pluck = np.sin(2 * np.pi * (f1 * 2) * t) * np.exp(-t * 300) * 0.15
    # Soft thump
    thump = np.sin(2 * np.pi * 150 * t) * np.exp(-t * 100) * 0.3
    # Tiny bell
    bell_f = 3000 + rng.randint(0, 500)
    bell = np.sin(2 * np.pi * bell_f * t) * np.exp(-t * 150) * 0.1
    return _normalise(tone + pluck + thump + bell)


def _synth_cash_register_click(sr: int, seed: int) -> np.ndarray:
    """Cash register: heavy mechanical clunk + bell ding."""
    rng = np.random.RandomState(seed)
    dur = 0.18
    n = int(sr * dur)
    t = np.linspace(0, dur, n, False)
    # Heavy drawer clunk
    clunk = rng.randn(n) * np.exp(-t * 200) * 0.5
    thud = np.sin(2 * np.pi * 80 * t) * np.exp(-t * 80) * 0.6
    # Metal gear grind
    grind = (
        np.sin(2 * np.pi * 300 * t)
        + np.sin(2 * np.pi * 450 * t) * 0.5
    ) * np.exp(-t * 150) * 0.2
    # Bell ding (delayed slightly by 0.02s)
    delay_samples = int(0.02 * sr)
    bell_t = np.linspace(0, dur - 0.02, max(1, n - delay_samples), False)
    bell_f = 2800 + rng.randint(-100, 100)
    bell = np.sin(2 * np.pi * bell_f * bell_t) * np.exp(-bell_t * 30) * 0.5
    # Place bell after delay
    padded = np.zeros(n, dtype=np.float64)
    padded[delay_samples:delay_samples + len(bell)] = bell
    return _normalise(clunk + thud + grind + padded)


def _synth_laptop_click(sr: int, seed: int) -> np.ndarray:
    """Laptop / chiclet keyboard: soft, quiet, low-profile."""
    rng = np.random.RandomState(seed)
    dur = 0.04
    n = int(sr * dur)
    t = np.linspace(0, dur, n, False)
    # Soft pad tap
    noise = rng.randn(n) * np.exp(-t * 800) * 0.3
    freq = 4000 + rng.randint(-500, 500)
    tap = np.sin(2 * np.pi * freq * t) * np.exp(-t * 600) * 0.3
    # Tiny plastic thud
    thud = np.sin(2 * np.pi * 300 * t) * np.exp(-t * 400) * 0.2
    return _normalise(noise + tap + thud, target_peak=0.45)


def _synth_retro_game_click(sr: int, seed: int) -> np.ndarray:
    """Retro 8-bit game: short chip-tune blip."""
    rng = np.random.RandomState(seed)
    dur = 0.07
    n = int(sr * dur)
    t = np.linspace(0, dur, n, False)
    # Square-wave-ish blip (sum of odd harmonics for square approx)
    f = 600 + rng.randint(0, 300)
    blip = np.zeros(n, dtype=np.float64)
    for k in range(1, 8, 2):  # odd harmonics 1,3,5,7
        blip += np.sin(2 * np.pi * f * k * t) / k
    blip = blip * 0.3 * np.exp(-t * 200)
    # Noise burst
    noise = rng.randn(n) * np.exp(-t * 500) * 0.2
    return _normalise(blip + noise, target_peak=0.6)


def _synth_telegraph_click(sr: int, seed: int) -> np.ndarray:
    """Telegraph / morse: sharp electromagnetic tap."""
    rng = np.random.RandomState(seed)
    dur = 0.05
    n = int(sr * dur)
    t = np.linspace(0, dur, n, False)
    # Sharp electromagnetic click
    click = np.sin(2 * np.pi * 5000 * t) * np.exp(-t * 1000) * 0.5
    # Metal contact snap
    snap = rng.randn(n) * np.exp(-t * 1500) * 0.5
    # Resonant body
    body = np.sin(2 * np.pi * 350 * t) * np.exp(-t * 100) * 0.2
    return _normalise(click + snap + body)


# ── Special key variants (space, enter) per preset ─────────────────

def _synth_space_generic(sr: int, seed: int, decay: float = 250,
                         freq: float = 140, decay2: float = 120) -> np.ndarray:
    rng = np.random.RandomState(seed)
    dur = 0.09
    n = int(sr * dur)
    t = np.linspace(0, dur, n, False)
    noise = rng.randn(n) * np.exp(-t * decay) * 0.35
    thud = np.sin(2 * np.pi * freq * t) * np.exp(-t * decay2) * 0.5
    return _normalise(noise + thud)


def _synth_enter_generic(sr: int, seed: int, decay: float = 300,
                         freq: float = 120, decay2: float = 130) -> np.ndarray:
    rng = np.random.RandomState(seed)
    dur = 0.08
    n = int(sr * dur)
    t = np.linspace(0, dur, n, False)
    noise = rng.randn(n) * np.exp(-t * decay) * 0.4
    thud = np.sin(2 * np.pi * freq * t) * np.exp(-t * decay2) * 0.55
    return _normalise(noise + thud)


def _synth_space_typewriter(sr: int, seed: int) -> np.ndarray:
    """Typewriter space: long carriage slide."""
    rng = np.random.RandomState(seed)
    dur = 0.15
    n = int(sr * dur)
    t = np.linspace(0, dur, n, False)
    # Carriage sliding
    slide = rng.randn(n) * np.exp(-t * 30) * 0.2
    # Metal bar
    bar = np.sin(2 * np.pi * 100 * t) * np.exp(-t * 40) * 0.4
    # Impact at start
    impact = rng.randn(n) * np.exp(-t * 600) * 0.3
    return _normalise(slide + bar + impact)


def _synth_enter_typewriter(sr: int, seed: int) -> np.ndarray:
    """Typewriter enter: carriage return + bell."""
    rng = np.random.RandomState(seed)
    dur = 0.22
    n = int(sr * dur)
    t = np.linspace(0, dur, n, False)
    # Carriage return slide
    slide = rng.randn(n) * np.exp(-t * 25) * 0.3
    # Heavy ding
    bell_f = 2000 + rng.randint(-100, 100)
    delay = int(0.03 * sr)
    bell_t = np.linspace(0, dur - 0.03, max(1, n - delay), False)
    bell = np.sin(2 * np.pi * bell_f * bell_t) * np.exp(-bell_t * 20) * 0.6
    padded_bell = np.zeros(n, dtype=np.float64)
    padded_bell[delay:delay + len(bell)] = bell
    # Thud
    thud = np.sin(2 * np.pi * 80 * t) * np.exp(-t * 60) * 0.4
    return _normalise(slide + padded_bell + thud)


def _synth_space_circus(sr: int, seed: int) -> np.ndarray:
    """Circus space: slide whistle effect."""
    rng = np.random.RandomState(seed)
    dur = 0.15
    n = int(sr * dur)
    t = np.linspace(0, dur, n, False)
    # Descending frequency chirp
    phase = 2 * np.pi * (800 * t - 2000 * t * t)
    chirp = np.sin(phase) * np.exp(-t * 60) * 0.4
    # Thump
    thump = np.sin(2 * np.pi * 200 * t) * np.exp(-t * 80) * 0.3
    # Sparkle
    sparkle = rng.randn(n) * np.exp(-t * 200) * 0.15
    return _normalise(chirp + thump + sparkle)


def _synth_enter_circus(sr: int, seed: int) -> np.ndarray:
    """Circus enter: drum roll hit + cymbal."""
    rng = np.random.RandomState(seed)
    dur = 0.20
    n = int(sr * dur)
    t = np.linspace(0, dur, n, False)
    # Snare hit
    snare = rng.randn(n) * np.exp(-t * 150) * 0.4
    drum = np.sin(2 * np.pi * 150 * t) * np.exp(-t * 80) * 0.4
    # Cymbal (high-freq noise)
    cymbal = rng.randn(n) * np.exp(-t * 15) * 0.2
    # Bright ping
    ping_f = 1500 + rng.randint(0, 300)
    ping = np.sin(2 * np.pi * ping_f * t) * np.exp(-t * 40) * 0.2
    return _normalise(snare + drum + cymbal + ping)


def _synth_space_cash(sr: int, seed: int) -> np.ndarray:
    """Cash register space: drawer slide."""
    rng = np.random.RandomState(seed)
    dur = 0.20
    n = int(sr * dur)
    t = np.linspace(0, dur, n, False)
    # Metal drawer sliding on rails
    slide = rng.randn(n) * np.exp(-t * 20) * 0.25
    rail = np.sin(2 * np.pi * 200 * t) * np.exp(-t * 25) * 0.3
    # Impact
    impact = rng.randn(n) * np.exp(-t * 400) * 0.3
    return _normalise(slide + rail + impact)


def _synth_enter_cash(sr: int, seed: int) -> np.ndarray:
    """Cash register enter: drawer open + bell + coins."""
    rng = np.random.RandomState(seed)
    dur = 0.30
    n = int(sr * dur)
    t = np.linspace(0, dur, n, False)
    # Drawer thud
    thud = np.sin(2 * np.pi * 70 * t) * np.exp(-t * 50) * 0.5
    clunk = rng.randn(n) * np.exp(-t * 200) * 0.4
    # Bell
    bell_f = 2600 + rng.randint(-100, 100)
    delay = int(0.04 * sr)
    bell_t = np.linspace(0, dur - 0.04, max(1, n - delay), False)
    bell = np.sin(2 * np.pi * bell_f * bell_t) * np.exp(-bell_t * 15) * 0.5
    padded_bell = np.zeros(n, dtype=np.float64)
    padded_bell[delay:delay + len(bell)] = bell
    # Coin clinks (multiple tiny high pings at random times)
    coins = np.zeros(n, dtype=np.float64)
    for _ in range(rng.randint(2, 5)):
        offset = int(rng.uniform(0.05, 0.20) * sr)
        cf = 4000 + rng.randint(0, 2000)
        cdur = int(0.02 * sr)
        ct = np.linspace(0, 0.02, cdur, False)
        clink = np.sin(2 * np.pi * cf * ct) * np.exp(-ct * 200) * 0.2
        end = min(offset + cdur, n)
        if offset < n:
            coins[offset:end] += clink[:end - offset]
    return _normalise(thud + clunk + padded_bell + coins)


def _synth_space_retro(sr: int, seed: int) -> np.ndarray:
    """Retro game space: low blip."""
    rng = np.random.RandomState(seed)
    dur = 0.08
    n = int(sr * dur)
    t = np.linspace(0, dur, n, False)
    f = 300 + rng.randint(0, 100)
    blip = np.sin(2 * np.pi * f * t) * np.exp(-t * 150) * 0.4
    noise = rng.randn(n) * np.exp(-t * 400) * 0.2
    return _normalise(blip + noise, target_peak=0.55)


def _synth_enter_retro(sr: int, seed: int) -> np.ndarray:
    """Retro game enter: confirmation sound."""
    rng = np.random.RandomState(seed)
    dur = 0.12
    n = int(sr * dur)
    t = np.linspace(0, dur, n, False)
    # Two-tone ascending
    f1 = 500
    f2 = 800
    tone1 = np.sin(2 * np.pi * f1 * t) * np.exp(-t * 200) * 0.35
    mid = n // 3
    t2 = np.linspace(0, dur * 2 / 3, n - mid, False)
    tone2 = np.sin(2 * np.pi * f2 * t2) * np.exp(-t2 * 200) * 0.35
    padded2 = np.zeros(n, dtype=np.float64)
    padded2[mid:] = tone2
    return _normalise(tone1 + padded2, target_peak=0.6)


def _synth_space_telegraph(sr: int, seed: int) -> np.ndarray:
    """Telegraph space: long dash buzz."""
    rng = np.random.RandomState(seed)
    dur = 0.12
    n = int(sr * dur)
    t = np.linspace(0, dur, n, False)
    buzz = np.sin(2 * np.pi * 600 * t) * np.exp(-t * 50) * 0.4
    click = rng.randn(n) * np.exp(-t * 800) * 0.3
    return _normalise(buzz + click)


def _synth_enter_telegraph(sr: int, seed: int) -> np.ndarray:
    """Telegraph enter: double tap."""
    rng = np.random.RandomState(seed)
    dur = 0.10
    n = int(sr * dur)
    t = np.linspace(0, dur, n, False)
    tap1 = np.sin(2 * np.pi * 5000 * t) * np.exp(-t * 1000) * 0.5
    tap1 += rng.randn(n) * np.exp(-t * 1200) * 0.3
    # Second tap delayed by 0.03s
    delay = int(0.03 * sr)
    t2 = np.linspace(0, dur - 0.03, max(1, n - delay), False)
    tap2 = np.sin(2 * np.pi * 5000 * t2) * np.exp(-t2 * 1000) * 0.5
    tap2 += np.random.RandomState(seed + 99).randn(len(t2)) * np.exp(-t2 * 1200) * 0.3
    padded2 = np.zeros(n, dtype=np.float64)
    padded2[delay:delay + len(tap2)] = tap2
    return _normalise(tap1 + padded2)


# ── Preset registry ────────────────────────────────────────────────

SOUND_PRESETS: Dict[str, dict] = {
    "Mechanical Keyboard": {
        "click_fn": _synth_mechanical_click,
        "space_fn": lambda sr, seed: _synth_space_generic(sr, seed),
        "enter_fn": lambda sr, seed: _synth_enter_generic(sr, seed),
        "click_variants": 6,
        "space_variants": 3,
        "enter_variants": 3,
    },
    "Typewriter": {
        "click_fn": _synth_typewriter_click,
        "space_fn": _synth_space_typewriter,
        "enter_fn": _synth_enter_typewriter,
        "click_variants": 6,
        "space_variants": 3,
        "enter_variants": 3,
    },
    "Circus": {
        "click_fn": _synth_circus_click,
        "space_fn": _synth_space_circus,
        "enter_fn": _synth_enter_circus,
        "click_variants": 6,
        "space_variants": 3,
        "enter_variants": 3,
    },
    "Cash Register": {
        "click_fn": _synth_cash_register_click,
        "space_fn": _synth_space_cash,
        "enter_fn": _synth_enter_cash,
        "click_variants": 6,
        "space_variants": 3,
        "enter_variants": 3,
    },
    "Laptop Keyboard": {
        "click_fn": _synth_laptop_click,
        "space_fn": lambda sr, seed: _synth_space_generic(sr, seed, decay=350, freq=180, decay2=200),
        "enter_fn": lambda sr, seed: _synth_enter_generic(sr, seed, decay=400, freq=160, decay2=200),
        "click_variants": 6,
        "space_variants": 3,
        "enter_variants": 3,
    },
    "Retro Game": {
        "click_fn": _synth_retro_game_click,
        "space_fn": _synth_space_retro,
        "enter_fn": _synth_enter_retro,
        "click_variants": 6,
        "space_variants": 3,
        "enter_variants": 3,
    },
    "Telegraph": {
        "click_fn": _synth_telegraph_click,
        "space_fn": _synth_space_telegraph,
        "enter_fn": _synth_enter_telegraph,
        "click_variants": 6,
        "space_variants": 3,
        "enter_variants": 3,
    },
}


class SoundGen:
    """Generate and mix typing sounds using a selected preset."""

    def __init__(self, preset_name: str = "Mechanical Keyboard", sr: int = 44100):
        self.sr = sr
        preset = SOUND_PRESETS.get(preset_name, SOUND_PRESETS["Mechanical Keyboard"])
        self.clicks = [
            preset["click_fn"](sr, seed=i)
            for i in range(preset["click_variants"])
        ]
        self.spaces = [
            preset["space_fn"](sr, seed=100 + i)
            for i in range(preset["space_variants"])
        ]
        self.enters = [
            preset["enter_fn"](sr, seed=200 + i)
            for i in range(preset["enter_variants"])
        ]

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


# Backwards compatibility alias
SimpleSoundGen = SoundGen


# =====================================================================
# Keyboard Layout Data & Overlay Renderer
# =====================================================================

@dataclass
class KeyDef:
    """A single physical key on the keyboard."""
    label: str          # Primary label shown on keycap
    shift_label: str    # Shift label (above primary), "" if none
    width: float        # Key width in units (1.0 = standard key)
    chars: str          # Characters this key produces: "<base><shift>"
    special: str = ""   # "space", "enter", "tab", "shift", "backspace", "caps" or ""


def _build_char_map(keys: List[List[KeyDef]]) -> Dict[str, Tuple[int, int]]:
    """Build a char → (row, col) lookup from a layout."""
    m: Dict[str, Tuple[int, int]] = {}
    for r, row in enumerate(keys):
        for c, k in enumerate(row):
            if len(k.chars) >= 1:
                m[k.chars[0]] = (r, c)
            if len(k.chars) >= 2:
                m[k.chars[1]] = (r, c)
    return m


def _make_qwerty() -> Tuple[List[List[KeyDef]], Dict[str, Tuple[int, int]]]:
    rows = [
        [
            KeyDef("`", "~", 1.0, "`~"),
            KeyDef("1", "!", 1.0, "1!"), KeyDef("2", "@", 1.0, "2@"),
            KeyDef("3", "#", 1.0, "3#"), KeyDef("4", "$", 1.0, "4$"),
            KeyDef("5", "%", 1.0, "5%"), KeyDef("6", "^", 1.0, "6^"),
            KeyDef("7", "&", 1.0, "7&"), KeyDef("8", "*", 1.0, "8*"),
            KeyDef("9", "(", 1.0, "9("), KeyDef("0", ")", 1.0, "0)"),
            KeyDef("-", "_", 1.0, "-_"), KeyDef("=", "+", 1.0, "=+"),
            KeyDef("Bksp", "", 2.0, "", special="backspace"),
        ],
        [
            KeyDef("Tab", "", 1.5, "\t", special="tab"),
            KeyDef("q", "Q", 1.0, "qQ"), KeyDef("w", "W", 1.0, "wW"),
            KeyDef("e", "E", 1.0, "eE"), KeyDef("r", "R", 1.0, "rR"),
            KeyDef("t", "T", 1.0, "tT"), KeyDef("y", "Y", 1.0, "yY"),
            KeyDef("u", "U", 1.0, "uU"), KeyDef("i", "I", 1.0, "iI"),
            KeyDef("o", "O", 1.0, "oO"), KeyDef("p", "P", 1.0, "pP"),
            KeyDef("[", "{", 1.0, "[{"), KeyDef("]", "}", 1.0, "]}"),
            KeyDef("\\", "|", 1.5, "\\|"),
        ],
        [
            KeyDef("Caps", "", 1.75, "", special="caps"),
            KeyDef("a", "A", 1.0, "aA"), KeyDef("s", "S", 1.0, "sS"),
            KeyDef("d", "D", 1.0, "dD"), KeyDef("f", "F", 1.0, "fF"),
            KeyDef("g", "G", 1.0, "gG"), KeyDef("h", "H", 1.0, "hH"),
            KeyDef("j", "J", 1.0, "jJ"), KeyDef("k", "K", 1.0, "kK"),
            KeyDef("l", "L", 1.0, "lL"), KeyDef(";", ":", 1.0, ";:"),
            KeyDef("'", '"', 1.0, "'\""),
            KeyDef("Enter", "", 2.25, "\n", special="enter"),
        ],
        [
            KeyDef("Shift", "", 2.25, "", special="shift"),
            KeyDef("z", "Z", 1.0, "zZ"), KeyDef("x", "X", 1.0, "xX"),
            KeyDef("c", "C", 1.0, "cC"), KeyDef("v", "V", 1.0, "vV"),
            KeyDef("b", "B", 1.0, "bB"), KeyDef("n", "N", 1.0, "nN"),
            KeyDef("m", "M", 1.0, "mM"), KeyDef(",", "<", 1.0, ",<"),
            KeyDef(".", ">", 1.0, ".>"), KeyDef("/", "?", 1.0, "/?"),
            KeyDef("Shift", "", 2.75, "", special="shift"),
        ],
        [
            KeyDef("Ctrl", "", 1.5, "", special=""),
            KeyDef("Alt", "", 1.25, "", special=""),
            KeyDef("", "", 6.25, " ", special="space"),
            KeyDef("Alt", "", 1.25, "", special=""),
            KeyDef("Ctrl", "", 1.5, "", special=""),
        ],
    ]
    return rows, _build_char_map(rows)


def _make_azerty() -> Tuple[List[List[KeyDef]], Dict[str, Tuple[int, int]]]:
    rows = [
        [
            KeyDef("²", "", 1.0, "²&"),
            KeyDef("&", "1", 1.0, "&1"), KeyDef("é", "2", 1.0, "é2"),
            KeyDef('"', "3", 1.0, '"3'), KeyDef("'", "4", 1.0, "'4"),
            KeyDef("(", "5", 1.0, "(5"), KeyDef("-", "6", 1.0, "-6"),
            KeyDef("è", "7", 1.0, "è7"), KeyDef("_", "8", 1.0, "_8"),
            KeyDef("ç", "9", 1.0, "ç9"), KeyDef("à", "0", 1.0, "à0"),
            KeyDef(")", "°", 1.0, ")°"), KeyDef("=", "+", 1.0, "=+"),
            KeyDef("Bksp", "", 2.0, "", special="backspace"),
        ],
        [
            KeyDef("Tab", "", 1.5, "\t", special="tab"),
            KeyDef("a", "A", 1.0, "aA"), KeyDef("z", "Z", 1.0, "zZ"),
            KeyDef("e", "E", 1.0, "eE"), KeyDef("r", "R", 1.0, "rR"),
            KeyDef("t", "T", 1.0, "tT"), KeyDef("y", "Y", 1.0, "yY"),
            KeyDef("u", "U", 1.0, "uU"), KeyDef("i", "I", 1.0, "iI"),
            KeyDef("o", "O", 1.0, "oO"), KeyDef("p", "P", 1.0, "pP"),
            KeyDef("^", "¨", 1.0, "^¨"), KeyDef("$", "£", 1.0, "$£"),
            KeyDef("*", "µ", 1.5, "*µ"),
        ],
        [
            KeyDef("Caps", "", 1.75, "", special="caps"),
            KeyDef("q", "Q", 1.0, "qQ"), KeyDef("s", "S", 1.0, "sS"),
            KeyDef("d", "D", 1.0, "dD"), KeyDef("f", "F", 1.0, "fF"),
            KeyDef("g", "G", 1.0, "gG"), KeyDef("h", "H", 1.0, "hH"),
            KeyDef("j", "J", 1.0, "jJ"), KeyDef("k", "K", 1.0, "kK"),
            KeyDef("l", "L", 1.0, "lL"), KeyDef("m", "M", 1.0, "mM"),
            KeyDef("ù", "%", 1.0, "ù%"),
            KeyDef("Enter", "", 2.25, "\n", special="enter"),
        ],
        [
            KeyDef("Shift", "", 2.25, "", special="shift"),
            KeyDef("w", "W", 1.0, "wW"), KeyDef("x", "X", 1.0, "xX"),
            KeyDef("c", "C", 1.0, "cC"), KeyDef("v", "V", 1.0, "vV"),
            KeyDef("b", "B", 1.0, "bB"), KeyDef("n", "N", 1.0, "nN"),
            KeyDef(",", "?", 1.0, ",?"), KeyDef(";", ".", 1.0, ";."),
            KeyDef(":", "/", 1.0, ":/"), KeyDef("!", "§", 1.0, "!§"),
            KeyDef("Shift", "", 2.75, "", special="shift"),
        ],
        [
            KeyDef("Ctrl", "", 1.5, "", special=""),
            KeyDef("Alt", "", 1.25, "", special=""),
            KeyDef("", "", 6.25, " ", special="space"),
            KeyDef("Alt", "", 1.25, "", special=""),
            KeyDef("Ctrl", "", 1.5, "", special=""),
        ],
    ]
    return rows, _build_char_map(rows)


def _make_dvorak() -> Tuple[List[List[KeyDef]], Dict[str, Tuple[int, int]]]:
    rows = [
        [
            KeyDef("`", "~", 1.0, "`~"),
            KeyDef("1", "!", 1.0, "1!"), KeyDef("2", "@", 1.0, "2@"),
            KeyDef("3", "#", 1.0, "3#"), KeyDef("4", "$", 1.0, "4$"),
            KeyDef("5", "%", 1.0, "5%"), KeyDef("6", "^", 1.0, "6^"),
            KeyDef("7", "&", 1.0, "7&"), KeyDef("8", "*", 1.0, "8*"),
            KeyDef("9", "(", 1.0, "9("), KeyDef("0", ")", 1.0, "0)"),
            KeyDef("[", "{", 1.0, "[{"), KeyDef("]", "}", 1.0, "]}"),
            KeyDef("Bksp", "", 2.0, "", special="backspace"),
        ],
        [
            KeyDef("Tab", "", 1.5, "\t", special="tab"),
            KeyDef("'", '"', 1.0, "'\""), KeyDef(",", "<", 1.0, ",<"),
            KeyDef(".", ">", 1.0, ".>"), KeyDef("p", "P", 1.0, "pP"),
            KeyDef("y", "Y", 1.0, "yY"), KeyDef("f", "F", 1.0, "fF"),
            KeyDef("g", "G", 1.0, "gG"), KeyDef("c", "C", 1.0, "cC"),
            KeyDef("r", "R", 1.0, "rR"), KeyDef("l", "L", 1.0, "lL"),
            KeyDef("/", "?", 1.0, "/?"), KeyDef("=", "+", 1.0, "=+"),
            KeyDef("\\", "|", 1.5, "\\|"),
        ],
        [
            KeyDef("Caps", "", 1.75, "", special="caps"),
            KeyDef("a", "A", 1.0, "aA"), KeyDef("o", "O", 1.0, "oO"),
            KeyDef("e", "E", 1.0, "eE"), KeyDef("u", "U", 1.0, "uU"),
            KeyDef("i", "I", 1.0, "iI"), KeyDef("d", "D", 1.0, "dD"),
            KeyDef("h", "H", 1.0, "hH"), KeyDef("t", "T", 1.0, "tT"),
            KeyDef("n", "N", 1.0, "nN"), KeyDef("s", "S", 1.0, "sS"),
            KeyDef("-", "_", 1.0, "-_"),
            KeyDef("Enter", "", 2.25, "\n", special="enter"),
        ],
        [
            KeyDef("Shift", "", 2.25, "", special="shift"),
            KeyDef(";", ":", 1.0, ";:"), KeyDef("q", "Q", 1.0, "qQ"),
            KeyDef("j", "J", 1.0, "jJ"), KeyDef("k", "K", 1.0, "kK"),
            KeyDef("x", "X", 1.0, "xX"), KeyDef("b", "B", 1.0, "bB"),
            KeyDef("m", "M", 1.0, "mM"), KeyDef("w", "W", 1.0, "wW"),
            KeyDef("v", "V", 1.0, "vV"), KeyDef("z", "Z", 1.0, "zZ"),
            KeyDef("Shift", "", 2.75, "", special="shift"),
        ],
        [
            KeyDef("Ctrl", "", 1.5, "", special=""),
            KeyDef("Alt", "", 1.25, "", special=""),
            KeyDef("", "", 6.25, " ", special="space"),
            KeyDef("Alt", "", 1.25, "", special=""),
            KeyDef("Ctrl", "", 1.5, "", special=""),
        ],
    ]
    return rows, _build_char_map(rows)


def _make_colemak() -> Tuple[List[List[KeyDef]], Dict[str, Tuple[int, int]]]:
    rows = [
        [
            KeyDef("`", "~", 1.0, "`~"),
            KeyDef("1", "!", 1.0, "1!"), KeyDef("2", "@", 1.0, "2@"),
            KeyDef("3", "#", 1.0, "3#"), KeyDef("4", "$", 1.0, "4$"),
            KeyDef("5", "%", 1.0, "5%"), KeyDef("6", "^", 1.0, "6^"),
            KeyDef("7", "&", 1.0, "7&"), KeyDef("8", "*", 1.0, "8*"),
            KeyDef("9", "(", 1.0, "9("), KeyDef("0", ")", 1.0, "0)"),
            KeyDef("-", "_", 1.0, "-_"), KeyDef("=", "+", 1.0, "=+"),
            KeyDef("Bksp", "", 2.0, "", special="backspace"),
        ],
        [
            KeyDef("Tab", "", 1.5, "\t", special="tab"),
            KeyDef("q", "Q", 1.0, "qQ"), KeyDef("w", "W", 1.0, "wW"),
            KeyDef("f", "F", 1.0, "fF"), KeyDef("p", "P", 1.0, "pP"),
            KeyDef("g", "G", 1.0, "gG"), KeyDef("j", "J", 1.0, "jJ"),
            KeyDef("l", "L", 1.0, "lL"), KeyDef("u", "U", 1.0, "uU"),
            KeyDef("y", "Y", 1.0, "yY"), KeyDef(";", ":", 1.0, ";:"),
            KeyDef("[", "{", 1.0, "[{"), KeyDef("]", "}", 1.0, "]}"),
            KeyDef("\\", "|", 1.5, "\\|"),
        ],
        [
            KeyDef("Caps", "", 1.75, "", special="caps"),
            KeyDef("a", "A", 1.0, "aA"), KeyDef("r", "R", 1.0, "rR"),
            KeyDef("s", "S", 1.0, "sS"), KeyDef("t", "T", 1.0, "tT"),
            KeyDef("d", "D", 1.0, "dD"), KeyDef("h", "H", 1.0, "hH"),
            KeyDef("n", "N", 1.0, "nN"), KeyDef("e", "E", 1.0, "eE"),
            KeyDef("i", "I", 1.0, "iI"), KeyDef("o", "O", 1.0, "oO"),
            KeyDef("'", '"', 1.0, "'\""),
            KeyDef("Enter", "", 2.25, "\n", special="enter"),
        ],
        [
            KeyDef("Shift", "", 2.25, "", special="shift"),
            KeyDef("z", "Z", 1.0, "zZ"), KeyDef("x", "X", 1.0, "xX"),
            KeyDef("c", "C", 1.0, "cC"), KeyDef("v", "V", 1.0, "vV"),
            KeyDef("b", "B", 1.0, "bB"), KeyDef("k", "K", 1.0, "kK"),
            KeyDef("m", "M", 1.0, "mM"), KeyDef(",", "<", 1.0, ",<"),
            KeyDef(".", ">", 1.0, ".>"), KeyDef("/", "?", 1.0, "/?"),
            KeyDef("Shift", "", 2.75, "", special="shift"),
        ],
        [
            KeyDef("Ctrl", "", 1.5, "", special=""),
            KeyDef("Alt", "", 1.25, "", special=""),
            KeyDef("", "", 6.25, " ", special="space"),
            KeyDef("Alt", "", 1.25, "", special=""),
            KeyDef("Ctrl", "", 1.5, "", special=""),
        ],
    ]
    return rows, _build_char_map(rows)


def _make_workman() -> Tuple[List[List[KeyDef]], Dict[str, Tuple[int, int]]]:
    rows = [
        [
            KeyDef("`", "~", 1.0, "`~"),
            KeyDef("1", "!", 1.0, "1!"), KeyDef("2", "@", 1.0, "2@"),
            KeyDef("3", "#", 1.0, "3#"), KeyDef("4", "$", 1.0, "4$"),
            KeyDef("5", "%", 1.0, "5%"), KeyDef("6", "^", 1.0, "6^"),
            KeyDef("7", "&", 1.0, "7&"), KeyDef("8", "*", 1.0, "8*"),
            KeyDef("9", "(", 1.0, "9("), KeyDef("0", ")", 1.0, "0)"),
            KeyDef("-", "_", 1.0, "-_"), KeyDef("=", "+", 1.0, "=+"),
            KeyDef("Bksp", "", 2.0, "", special="backspace"),
        ],
        [
            KeyDef("Tab", "", 1.5, "\t", special="tab"),
            KeyDef("q", "Q", 1.0, "qQ"), KeyDef("d", "D", 1.0, "dD"),
            KeyDef("r", "R", 1.0, "rR"), KeyDef("w", "W", 1.0, "wW"),
            KeyDef("b", "B", 1.0, "bB"), KeyDef("j", "J", 1.0, "jJ"),
            KeyDef("f", "F", 1.0, "fF"), KeyDef("u", "U", 1.0, "uU"),
            KeyDef("p", "P", 1.0, "pP"), KeyDef(";", ":", 1.0, ";:"),
            KeyDef("[", "{", 1.0, "[{"), KeyDef("]", "}", 1.0, "]}"),
            KeyDef("\\", "|", 1.5, "\\|"),
        ],
        [
            KeyDef("Caps", "", 1.75, "", special="caps"),
            KeyDef("a", "A", 1.0, "aA"), KeyDef("s", "S", 1.0, "sS"),
            KeyDef("h", "H", 1.0, "hH"), KeyDef("t", "T", 1.0, "tT"),
            KeyDef("g", "G", 1.0, "gG"), KeyDef("y", "Y", 1.0, "yY"),
            KeyDef("n", "N", 1.0, "nN"), KeyDef("e", "E", 1.0, "eE"),
            KeyDef("o", "O", 1.0, "oO"), KeyDef("i", "I", 1.0, "iI"),
            KeyDef("'", '"', 1.0, "'\""),
            KeyDef("Enter", "", 2.25, "\n", special="enter"),
        ],
        [
            KeyDef("Shift", "", 2.25, "", special="shift"),
            KeyDef("z", "Z", 1.0, "zZ"), KeyDef("x", "X", 1.0, "xX"),
            KeyDef("m", "M", 1.0, "mM"), KeyDef("c", "C", 1.0, "cC"),
            KeyDef("v", "V", 1.0, "vV"), KeyDef("k", "K", 1.0, "kK"),
            KeyDef("l", "L", 1.0, "lL"), KeyDef(",", "<", 1.0, ",<"),
            KeyDef(".", ">", 1.0, ".>"), KeyDef("/", "?", 1.0, "/?"),
            KeyDef("Shift", "", 2.75, "", special="shift"),
        ],
        [
            KeyDef("Ctrl", "", 1.5, "", special=""),
            KeyDef("Alt", "", 1.25, "", special=""),
            KeyDef("", "", 6.25, " ", special="space"),
            KeyDef("Alt", "", 1.25, "", special=""),
            KeyDef("Ctrl", "", 1.5, "", special=""),
        ],
    ]
    return rows, _build_char_map(rows)


# Layout registry: name → (rows, char_map)
KEYBOARD_LAYOUTS: Dict[str, Tuple[List[List[KeyDef]], Dict[str, Tuple[int, int]]]] = {}
for _fn in (_make_qwerty, _make_azerty, _make_dvorak, _make_colemak, _make_workman):
    _rows, _cmap = _fn()
    # Use the function name to derive layout name
    _name = _fn.__name__.replace("_make_", "").replace("_", " ").title()
    KEYBOARD_LAYOUTS[_name] = (_rows, _cmap)


# =====================================================================
# CJK / IME / Script Detection Support
# =====================================================================

def _is_cjk_char(ch: str) -> bool:
    """Check if a character is CJK (Chinese, Japanese Kanji, or Korean Hanja)."""
    if len(ch) != 1:
        return False
    cp = ord(ch)
    # CJK Unified Ideographs + Extension A/B
    if 0x4E00 <= cp <= 0x9FFF:
        return True
    if 0x3400 <= cp <= 0x4DBF:
        return True
    if 0x20000 <= cp <= 0x2A6DF:
        return True
    # CJK Compatibility Ideographs
    if 0xF900 <= cp <= 0xFAFF:
        return True
    return False


def _is_hiragana(ch: str) -> bool:
    return 0x3040 <= ord(ch) <= 0x309F


def _is_katakana(ch: str) -> bool:
    return 0x30A0 <= ord(ch) <= 0x30FF


def _is_hangul(ch: str) -> bool:
    cp = ord(ch)
    return (0xAC00 <= cp <= 0xD7AF) or (0x1100 <= cp <= 0x11FF) or (0x3130 <= cp <= 0x318F)


def _is_cjk_or_fullwidth(ch: str) -> bool:
    """Check if a character should be rendered as double-width."""
    if _is_cjk_char(ch) or _is_hangul(ch):
        return True
    # Fullwidth forms
    cp = ord(ch)
    if 0xFF01 <= cp <= 0xFF60:
        return True
    # CJK punctuation and symbols
    if 0x3000 <= cp <= 0x303F:
        return True
    # Hiragana/Katakana are typically fullwidth
    if _is_hiragana(ch) or _is_katakana(ch):
        return True
    # CJK Radicals Supplement, Kangxi Radicals
    if 0x2E80 <= cp <= 0x2FDF:
        return True
    return False


def _detect_script(text: str) -> str:
    """Detect the dominant script in text. Returns 'latin', 'cjk', 'japanese', 'korean', or 'mixed'."""
    cjk = 0
    hiragana = 0
    katakana = 0
    hangul = 0
    latin = 0
    for ch in text:
        if _is_cjk_char(ch):
            cjk += 1
        elif _is_hiragana(ch):
            hiragana += 1
        elif _is_katakana(ch):
            katakana += 1
        elif _is_hangul(ch):
            hangul += 1
        elif ch.isascii():
            latin += 1
    total = cjk + hiragana + katakana + hangul + latin
    if total == 0:
        return "latin"
    if hangul / total > 0.3:
        return "korean"
    if (hiragana + katakana) / total > 0.15:
        return "japanese"
    if cjk / total > 0.2:
        return "cjk"
    return "latin"


def _suggest_font(script: str) -> str:
    """Suggest an appropriate font family for the detected script."""
    suggestions = {
        "cjk": "Noto Sans Mono CJK SC",
        "japanese": "Noto Sans Mono CJK JP",
        "korean": "Noto Sans Mono CJK KR",
        "latin": "Consolas",
        "mixed": "Noto Sans Mono CJK SC",
    }
    return suggestions.get(script, "Consolas")


# ── Pinyin dictionary for common Chinese characters ────────────────
# Maps CJK characters → their pinyin romanization for IME simulation

_CJK_PINYIN: Dict[str, str] = {
    "的": "de", "一": "yi", "是": "shi", "不": "bu", "了": "le",
    "我": "wo", "在": "zai", "人": "ren", "们": "men", "有": "you",
    "这": "zhe", "中": "zhong", "大": "da", "为": "wei", "上": "shang",
    "个": "ge", "国": "guo", "他": "ta", "来": "lai", "到": "dao",
    "说": "shuo", "会": "hui", "着": "zhe", "年": "nian", "出": "chu",
    "那": "na", "要": "yao", "就": "jiu", "对": "dui", "也": "ye",
    "能": "neng", "去": "qu", "都": "dou", "可": "ke", "以": "yi",
    "还": "hai", "下": "xia", "多": "duo", "没": "mei", "于": "yu",
    "又": "you", "学": "xue", "里": "li", "后": "hou", "之": "zhi",
    "过": "guo", "家": "jia", "十": "shi", "小": "xiao", "时": "shi",
    "如": "ru", "心": "xin", "前": "qian", "所": "suo", "道": "dao",
    "其": "qi", "想": "xiang", "样": "yang", "同": "tong", "现": "xian",
    "当": "dang", "起": "qi", "看": "kan", "好": "hao", "自": "zi",
    "将": "jiang", "已": "yi", "她": "ta", "从": "cong", "得": "de",
    "把": "ba", "你": "ni", "用": "yong", "生": "sheng", "而": "er",
    "新": "xin", "方": "fang", "实": "shi", "做": "zuo", "只": "zhi",
    "回": "hui", "最": "zui", "但": "dan", "比": "bi", "向": "xiang",
    "别": "bie", "信": "xin", "因": "yin", "二": "er", "三": "san",
    "些": "xie", "然": "ran", "相": "xiang", "力": "li", "理": "li",
    "话": "hua", "工": "gong", "正": "zheng", "儿": "er", "关": "guan",
    "点": "dian", "面": "mian", "文": "wen", "进": "jin", "行": "xing",
    "果": "guo", "月": "yue", "问": "wen", "与": "yu", "意": "yi",
    "明": "ming", "和": "he", "此": "ci", "部": "bu", "手": "shou",
    "很": "hen", "几": "ji", "什": "shen", "公": "gong", "各": "ge",
    "被": "bei", "始": "shi", "直": "zhi", "题": "ti", "教": "jiao",
    "次": "ci", "体": "ti", "合": "he", "完": "wan", "才": "cai",
    "化": "hua", "世": "shi", "间": "jian", "日": "ri", "期": "qi",
    "平": "ping", "件": "jian", "名": "ming", "定": "ding", "真": "zhen",
    "特": "te", "许": "xu", "通": "tong", "传": "chuan", "重": "zhong",
    "感": "gan", "等": "deng", "老": "lao", "百": "bai", "第": "di",
    "经": "jing", "门": "men", "内": "nei", "接": "jie", "代": "dai",
    "位": "wei", "任": "ren", "常": "chang", "先": "xian", "写": "xie",
    "字": "zi", "便": "bian", "气": "qi", "更": "geng", "数": "shu",
    "据": "ju", "程": "cheng", "序": "xu", "设": "she", "计": "ji",
    "请": "qing", "击": "ji", "网": "wang", "页": "ye", "链": "lian",
    "打": "da", "开": "kai", "按": "an", "钮": "niu", "选": "xuan",
    "择": "ze", "输": "shu", "入": "ru", "创": "chuang", "建": "jian",
    "删": "shan", "除": "chu", "改": "gai", "查": "cha", "找": "zhao",
    "搜": "sou", "索": "suo", "替": "ti", "换": "huan", "复": "fu",
    "制": "zhi", "粘": "zhan", "贴": "tie", "剪": "jian", "切": "qie",
    "撤": "che", "销": "xiao", "恢": "hui", "清": "qing", "空": "kong",
    "全": "quan", "反": "fan", "转": "zhuan", "格": "ge", "式": "shi",
    "颜": "yan", "色": "se", "加": "jia", "粗": "cu", "斜": "xie",
    "划": "hua", "线": "xian", "表": "biao", "列": "lie", "图": "tu",
    "片": "pian", "视": "shi", "频": "pin", "音": "yin", "乐": "le",
    "播": "bo", "放": "fang", "暂": "zan", "停": "ting", "快": "kuai",
    "慢": "man", "退": "tui", "静": "jing", "屏": "ping", "幕": "mu",
    "高": "gao", "亮": "liang", "度": "du", "饱": "bao", "暗": "an",
    "语": "yu", "言": "yan", "翻": "fan", "译": "yi", "注": "zhu",
    "释": "shi", "编": "bian", "码": "ma", "功": "gong", "测": "ce",
    "试": "shi", "调": "tiao", "错": "cuo", "误": "wu", "警": "jing",
    "告": "gao", "提": "ti", "示": "shi", "确": "que", "认": "ren",
    "取": "qu", "消": "xiao", "帮": "bang", "助": "zhu", "版": "ban",
    "权": "quan", "保": "bao", "密": "mi", "私": "si", "安": "an",
    "风": "feng", "险": "xian", "隐": "yin", "条": "tiao", "款": "kuan",
    "服": "fu", "务": "wu", "器": "qi", "应": "ying", "整": "zheng",
    "形": "xing", "浮": "fu", "类": "lei", "象": "xiang", "引": "yin",
    "包": "bao", "含": "han", "导": "dao", "模": "mo", "块": "kuai",
    "方": "fang", "法": "fa", "属": "shu", "性": "xing", "事": "shi",
    "监": "jian", "听": "ting", "触": "chu", "发": "fa", "求": "qiu",
    "响": "xiang", "答": "da", "状": "zhuang", "态": "tai", "头": "tou",
    "息": "xi", "载": "zai", "荷": "he", "定": "ding", "向": "xiang",
    "则": "ze", "若": "ruo", "虽": "sui", "即": "ji", "且": "qie",
    "或": "huo", "非": "fei", "否": "fou", "每": "mei", "它": "ta",
    "总": "zong", "结": "jie", "构": "gou", "种": "zhong", "情": "qing",
    "景": "jing", "像": "xiang", "变": "bian", "使": "shi", "命": "ming",
    "令": "ling", "务": "wu", "即": "ji", "调": "tiao", "增": "zeng",
    "删": "shan", "存": "cun", "取": "qu", "存": "cun", "储": "chu",
    "读": "du", "写": "xie", "返": "fan", "回": "hui", "调": "diao",
    "函": "han", "参": "can", "数": "shu", "返": "fan", "类": "lei",
    "型": "xing", "接": "jie", "口": "kou", "实": "shi", "现": "xian",
    "继": "ji", "承": "cheng", "封": "feng", "装": "zhuang", "多": "duo",
    "态": "tai", "抽": "chou", "象": "xiang", "覆": "fu", "盖": "gai",
    "异": "yi", "常": "chang", "处": "chu", "理": "li", "抛": "pao",
}

# ── Romaji for Japanese Hiragana / Katakana ────────────────────────

_JP_ROMAJI: Dict[str, str] = {
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
    "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so",
    "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to",
    "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho",
    "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
    "や": "ya", "ゆ": "yu", "よ": "yo",
    "ら": "ra", "り": "ri", "る": "ru", "れ": "re", "ろ": "ro",
    "わ": "wa", "を": "wo", "ん": "n",
    "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go",
    "ざ": "za", "じ": "ji", "ず": "zu", "ぜ": "ze", "ぞ": "zo",
    "だ": "da", "ぢ": "di", "づ": "du", "で": "de", "ど": "do",
    "ば": "ba", "び": "bi", "ぶ": "bu", "べ": "be", "ぼ": "bo",
    "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po",
    "きゃ": "kya", "きゅ": "kyu", "きょ": "kyo",
    "しゃ": "sha", "しゅ": "shu", "しょ": "sho",
    "ちゃ": "cha", "ちゅ": "chu", "ちょ": "cho",
    "にゃ": "nya", "にゅ": "nyu", "にょ": "nyo",
    "ひゃ": "hya", "ひゅ": "hyu", "ひょ": "hyo",
    "みゃ": "mya", "みゅ": "myu", "みょ": "myo",
    "りゃ": "rya", "りゅ": "ryu", "りょ": "ryo",
    # Katakana
    "ア": "a", "イ": "i", "ウ": "u", "エ": "e", "オ": "o",
    "カ": "ka", "キ": "ki", "ク": "ku", "ケ": "ke", "コ": "ko",
    "サ": "sa", "シ": "shi", "ス": "su", "セ": "se", "ソ": "so",
    "タ": "ta", "チ": "chi", "ツ": "tsu", "テ": "te", "ト": "to",
    "ナ": "na", "ニ": "ni", "ヌ": "nu", "ネ": "ne", "ノ": "no",
    "ハ": "ha", "ヒ": "hi", "フ": "fu", "ヘ": "he", "ホ": "ho",
    "マ": "ma", "ミ": "mi", "ム": "mu", "メ": "me", "モ": "mo",
    "ヤ": "ya", "ユ": "yu", "ヨ": "yo",
    "ラ": "ra", "リ": "ri", "ル": "ru", "レ": "re", "ロ": "ro",
    "ワ": "wa", "ヲ": "wo", "ン": "n",
    "ガ": "ga", "ギ": "gi", "グ": "gu", "ゲ": "ge", "ゴ": "go",
    "ザ": "za", "ジ": "ji", "ズ": "zu", "ゼ": "ze", "ゾ": "zo",
    "ダ": "da", "ヂ": "di", "ヅ": "du", "デ": "de", "ド": "do",
    "バ": "ba", "ビ": "bi", "ブ": "bu", "ベ": "be", "ボ": "bo",
    "パ": "pa", "ピ": "pi", "プ": "pu", "ペ": "pe", "ポ": "po",
    "ァ": "a", "ィ": "i", "ゥ": "u", "ェ": "e", "ォ": "o",
    "ッ": "xtsu", "ャ": "ya", "ュ": "yu", "ョ": "yo",
}

# ── Simple Korean romanization for common Hangul ───────────────────

_KR_ROMANIZATION: Dict[str, str] = {
    "안": "an", "녕": "nyeong", "하": "ha", "세": "se", "요": "yo",
    "감": "gam", "사": "sa", "합": "hap", "니": "ni", "다": "da",
    "이": "i", "가": "ga", "서": "seo", "도": "do", "고": "go",
    "수": "su", "있": "iss", "없": "eops", "그": "geu", "래": "rae",
    "네": "ne", "게": "ge", "겠": "get", "지": "ji", "은": "eun",
    "는": "neun", "을": "eul", "를": "reul", "와": "wa", "과": "gwa",
    "한": "han", "글": "geul", "자": "ja", "판": "pan", "원": "won",
    "정": "jeong", "보": "bo", "주": "ju", "면": "myeon", "못": "mot",
    "에서": "eseo", "까지": "kkaji", "부터": "buteo",
}


class KeyboardOverlay:
    """Renders a semi-transparent keyboard overlay with active-key highlighting."""

    # Visual tuning
    KEY_HEIGHT_RATIO = 0.38       # key height relative to unit width
    GAP = 0.10                    # gap between keys as fraction of unit
    CORNER_RADIUS = 4             # key corner radius in px (at 1x)
    BOTTOM_MARGIN_RATIO = 0.04    # margin from frame bottom
    SIDE_MARGIN_RATIO = 0.06      # margin from frame sides

    def __init__(
        self,
        width: int,
        height: int,
        layout_name: str = "Qwerty",
        opacity: float = 0.85,
        theme: Optional[Dict[str, str]] = None,
    ):
        self.width = width
        self.height = height
        self.opacity = opacity
        self.theme = theme or THEMES.get("Dracula", THEMES["Dracula"])

        # Resolve layout
        if layout_name not in KEYBOARD_LAYOUTS:
            layout_name = "Qwerty"
        self.layout_name = layout_name
        self.rows, self.char_map = KEYBOARD_LAYOUTS[layout_name]

        # Compute geometry
        self._compute_geometry()

        # Pre-render base keyboard
        self._base_img = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        self._base_img.fill(Qt.GlobalColor.transparent)
        self._render_base(self._base_img)

    def _compute_geometry(self):
        """Calculate key positions and sizes in pixel space."""
        total_units = sum(k.width for k in self.rows[0])  # reference row
        margin_x = self.width * self.SIDE_MARGIN_RATIO
        margin_bottom = self.height * self.BOTTOM_MARGIN_RATIO
        available_w = self.width - 2 * margin_x
        self.unit_w = available_w / (total_units + (len(self.rows[0]) - 1) * self.GAP)
        self.key_h = self.unit_w * self.KEY_HEIGHT_RATIO
        self.gap = self.unit_w * self.GAP

        # Total keyboard height
        self.total_h = len(self.rows) * self.key_h + (len(self.rows) - 1) * self.gap
        self.kb_x = margin_x
        self.kb_y = self.height - margin_bottom - self.total_h

        # Pre-calculate key rects
        self.key_rects: List[List[QRect]] = []
        for r, row in enumerate(self.rows):
            rects = []
            x = self.kb_x
            y = self.kb_y + r * (self.key_h + self.gap)
            for k in row:
                w = k.width * self.unit_w + (k.width - 1) * self.gap
                rects.append(QRect(int(x), int(y), int(w), int(self.key_h)))
                x += w + self.gap
            self.key_rects.append(rects)

    def _render_base(self, img: QImage):
        """Render all keys in their resting state onto *img*."""
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(self.opacity)

        bg_color = QColor(self.theme.get("background", "#282a36"))
        # Make keyboard background slightly different
        kb_bg = QColor(bg_color)
        kb_bg.setAlpha(220)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(kb_bg)
        p.drawRoundedRect(
            int(self.kb_x - self.gap),
            int(self.kb_y - self.gap),
            int(self.width - 2 * self.kb_x + 2 * self.gap),
            int(self.total_h + 2 * self.gap),
            8, 8,
        )

        key_bg = QColor("#3a3d4d")
        key_border = QColor("#505468")
        label_color = QColor(self.theme.get("foreground", "#f8f8f2"))
        sub_label_color = QColor(self.theme.get("comment", "#6272a4"))
        special_label_color = QColor(self.theme.get("comment", "#6272a4"))

        for r, row in enumerate(self.rows):
            for c, k in enumerate(row):
                rect = self.key_rects[r][c]
                # Key background
                p.setPen(QPen(key_border, 1))
                p.setBrush(key_bg)
                p.drawRoundedRect(rect, self.CORNER_RADIUS, self.CORNER_RADIUS)

                # Label
                p.setPen(Qt.PenStyle.NoPen)
                is_special = k.special != "" and len(k.chars) <= 1
                if is_special:
                    p.setPen(special_label_color)
                    font = QFont("Sans", max(6, int(self.unit_w * 0.22)))
                    p.setFont(font)
                    p.drawText(rect, Qt.AlignmentFlag.AlignCenter, k.label)
                else:
                    # Primary label (lower-left area)
                    p.setPen(label_color)
                    font_size = max(6, int(self.unit_w * 0.30))
                    font = QFont("Sans", font_size)
                    font.setBold(True)
                    p.setFont(font)
                    main_label = k.label if k.label else k.chars[0] if k.chars else ""
                    p.drawText(rect.adjusted(2, 0, 0, -rect.height() * 0.28),
                               Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
                               main_label)
                    # Shift label (upper-right area)
                    if k.shift_label:
                        p.setPen(sub_label_color)
                        font.setBold(False)
                        font.setPointSize(max(5, int(self.unit_w * 0.20)))
                        p.setFont(font)
                        p.drawText(rect.adjusted(0, 2, -2, 0),
                                   Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
                                   k.shift_label)
        p.end()

    def draw(self, painter: QPainter, active_char: str = ""):
        """Draw the keyboard overlay with *active_char* highlighted."""
        # Draw base
        painter.drawImage(0, 0, self._base_img)

        if not active_char:
            return

        # Find which key to highlight
        pos = self.char_map.get(active_char)
        if pos is None:
            # Try lowercase
            pos = self.char_map.get(active_char.lower(), self.char_map.get(active_char.upper()))
        if pos is None:
            return

        r, c = pos
        rect = self.key_rects[r][c]
        k = self.rows[r][c]

        painter.setOpacity(self.opacity)

        # Determine highlight color from theme accent
        accent = QColor(self.theme.get("keyword", "#ff79c6"))
        glow = QColor(accent)
        glow.setAlpha(60)

        # Glow behind key
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawRoundedRect(rect.adjusted(-4, -4, 4, 4),
                                self.CORNER_RADIUS + 2, self.CORNER_RADIUS + 2)

        # Highlighted key background
        highlight = QColor(accent)
        highlight.setAlpha(180)
        painter.setBrush(highlight)
        painter.setPen(QPen(accent, 2))
        painter.drawRoundedRect(rect, self.CORNER_RADIUS, self.CORNER_RADIUS)

        # Re-draw label in white for contrast
        painter.setPen(QColor("#ffffff"))
        is_special = k.special != "" and len(k.chars) <= 1
        if is_special:
            font = QFont("Sans", max(6, int(self.unit_w * 0.22)))
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, k.label)
        else:
            font_size = max(6, int(self.unit_w * 0.30))
            font = QFont("Sans", font_size)
            font.setBold(True)
            painter.setFont(font)
            main_label = k.label if k.label else k.chars[0] if k.chars else ""
            painter.drawText(rect.adjusted(2, 0, 0, -rect.height() * 0.28),
                             Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
                             main_label)
            if k.shift_label:
                painter.setPen(QColor("#ffffffd0"))
                font.setBold(False)
                font.setPointSize(max(5, int(self.unit_w * 0.20)))
                painter.setFont(font)
                painter.drawText(rect.adjusted(0, 2, -2, 0),
                                 Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
                                 k.shift_label)

        painter.setOpacity(1.0)


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
    """Build a per-character typing timeline with basic humanisation and IME simulation."""

    def __init__(
        self,
        code: str,
        wpm: int = 100,
        start_pause: float = 0.5,
        end_pause: float = 1.5,
        seed: Optional[int] = None,
        ime_mode: str = "auto",
    ):
        self.code = code
        self.start_pause = start_pause
        self.end_pause = end_pause
        self.ime_mode = ime_mode  # "auto", "on", "off"
        cps = (wpm * 5) / 60
        self.base_delay = 1.0 / cps
        self.display_chars: List[str] = []
        # IME composition timeline: list of (timestamp, composition_text, is_start)
        self._comp_events: List[Tuple[float, str, bool]] = []
        self.timeline: List[Event] = self._build(seed)
        self._timestamps = [ts for ts, _, _ in self.timeline]
        self._comp_timestamps = [ts for ts, _, _ in self._comp_events]

    @staticmethod
    def _get_romanization(ch: str) -> str:
        """Look up romanization for a CJK / Japanese / Korean character."""
        if ch in _CJK_PINYIN:
            return _CJK_PINYIN[ch]
        if ch in _JP_ROMAJI:
            return _JP_ROMAJI[ch]
        if ch in _KR_ROMANIZATION:
            return _KR_ROMANIZATION[ch]
        # Fallback: use Unicode code-point hex for unknown CJK chars
        if _is_cjk_char(ch) or _is_hangul(ch):
            return f"u{ord(ch):04x}"
        return ""

    def _is_ime_char(self, ch: str) -> bool:
        """Check if a character should use IME simulation."""
        if self.ime_mode == "off":
            return False
        if self.ime_mode == "on":
            return bool(self._get_romanization(ch))
        # "auto" mode — only if romanization is available
        return bool(self._get_romanization(ch))

    def _build(self, seed) -> List[Event]:
        rng = random.Random(seed)
        t = 0.0
        events: List[Event] = []

        for i, ch in enumerate(self.code):
            # ── Check if this character uses IME ──────────────────
            romanization = ""
            use_ime = self._is_ime_char(ch)
            if use_ime:
                romanization = self._get_romanization(ch)

            if use_ime and romanization:
                # ── IME composition mode ─────────────────────────
                comp_start_t = t

                # Fast typing of romanization letters
                for rc_idx, rc in enumerate(romanization):
                    rc_delay = self.base_delay * rng.uniform(0.25, 0.50)
                    t += rc_delay
                    # Record composition building (show progressive text)
                    partial = romanization[:rc_idx + 1]
                    self._comp_events.append((t, partial, True))

                # IME conversion pause (brief hesitation while selecting candidate)
                convert_pause = self.base_delay * rng.uniform(0.2, 0.6)
                t += convert_pause

                # End composition, add CJK character to display
                self._comp_events.append((t, romanization, False))

                # The CJK character itself takes a slightly longer "landing" delay
                d = self.base_delay * rng.uniform(0.6, 1.2)
                self.display_chars.append(ch)
                events.append((t, len(self.display_chars) - 1, ch))
                t += max(d, 0.012)
            else:
                # ── Normal typing (original logic) ───────────────
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
        self._comp_events = [(ts + sp, txt, is_s) for ts, txt, is_s in self._comp_events]
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

    def last_char_at(self, t: float) -> str:
        """Return the character most recently typed at or before time *t*."""
        if t < self.start_pause or not self.timeline:
            return ""
        idx = bisect.bisect_right(self._timestamps, t)
        if idx == 0:
            return ""
        return self.timeline[idx - 1][2]

    def composition_at(self, t: float) -> str:
        """Return the current IME composition text at time *t*, or ''."""
        if t < self.start_pause or not self._comp_events:
            return ""
        # Walk backwards through composition events to find active one
        active_text = ""
        for ts, txt, is_start in self._comp_events:
            if ts > t:
                break
            if is_start:
                active_text = txt
            else:
                active_text = ""
        return active_text


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
    def _char_col_width(ch: str, char_w: float, fm: QFontMetrics,
                         tab_size: int = 4) -> float:
        """Return the visual column width of a single character."""
        if ch == "\t":
            return tab_size * char_w
        if _is_cjk_or_fullwidth(ch):
            return 2.0 * char_w
        return fm.horizontalAdvance(ch)

    @staticmethod
    def _line_col_width(line: str, char_w: float, fm: QFontMetrics,
                         tab_size: int = 4) -> float:
        """Return the total visual column width of a line."""
        w = 0.0
        for ch in line:
            w += CodeRenderer._char_col_width(ch, char_w, fm, tab_size)
        return w

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
            # Account for CJK double-width characters
            max_col_width = 0.0
            for line in code.split("\n"):
                expanded = line.replace("\t", " " * tab_size)
                col_w = 0.0
                for ch in expanded:
                    if _is_cjk_or_fullwidth(ch):
                        col_w += 2.0
                    else:
                        col_w += 1.0
                max_col_width = max(max_col_width, col_w)
            max_chars = max(int(max_col_width) + 5, 40)
        max_font_by_w = avail_w / (max_chars * cw) * 20

        return int(min(max_font_by_h, max_font_by_w, 40))

    def render_frame(
        self,
        display_chars: List[str],
        num_visible: int,
        cursor_visible: bool = True,
        target: Optional[QImage] = None,
        keyboard_overlay: Optional[KeyboardOverlay] = None,
        active_char: str = "",
        composition_text: str = "",
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
                x_acc = 0.0
                colored: List[Tuple[str, str, float]] = []
                for ttype, ttext in tokens:
                    colored.append((ttype, ttext, x_acc))
                    # CJK-aware column accumulation
                    for tc in ttext:
                        x_acc += self._char_col_width(tc, self.char_w, self.fm, self.tab_size)
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

        # Cursor (CJK-aware position calculation)
        if cursor_visible and num_visible > 0:
            cur_line_idx = visible_text.rfind("\n")
            cur_line = visible_text[cur_line_idx + 1:] if cur_line_idx >= 0 else visible_text
            # Calculate cursor column position using CJK-aware widths
            cur_col_px = 0.0
            for ch in cur_line:
                cur_col_px += self._char_col_width(ch, self.char_w, self.fm, self.tab_size)
            cur_line_screen = visible_text.count("\n") - scroll

            if 0 <= cur_line_screen < max_visible_lines:
                cx = x0 + cur_col_px
                cy = y_base + cur_line_screen * self.line_h
                p.setPen(QColor(self.theme["cursor"]))
                p.drawRect(int(cx), cy + 2, 2, self.line_h - 4)

                # IME composition text (underlined at cursor position)
                if composition_text:
                    comp_font = QFont(self.font_family, self.font_size)
                    comp_font.setUnderline(True)
                    p.setFont(comp_font)
                    p.setPen(QColor(self.theme.get("string", "#f1fa8c")))
                    comp_px_w = 0.0
                    for ch in composition_text:
                        comp_px_w += self.fm.horizontalAdvance(ch)
                    # Draw composition text
                    p.drawText(int(cx + 2), int(cy + self.fm.ascent()), composition_text)
                    # Move cursor after composition text
                    p.setPen(QColor(self.theme["cursor"]))
                    p.drawRect(int(cx + comp_px_w + 2), cy + 2, 2, self.line_h - 4)
                    # Restore normal font
                    p.setFont(self.font)

        # Keyboard overlay
        if keyboard_overlay is not None:
            keyboard_overlay.draw(p, active_char)

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
        keyboard_overlay: Optional[KeyboardOverlay] = None,
    ):
        super().__init__()
        self.code = code
        self.output = output
        self.renderer = renderer
        self.animator = animator
        self.fps = fps
        self.sound_gen = sound_gen
        self.volume = volume
        self.keyboard_overlay = keyboard_overlay
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
                    self.animator.display_chars, nv, cur_vis, target=scratch,
                    keyboard_overlay=self.keyboard_overlay,
                    active_char=self.animator.last_char_at(t),
                    composition_text=self.animator.composition_at(t),
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
        self.setMinimumSize(1050, 650)
        self.resize(1200, 750)

        self._items: List[FileItem] = []
        self._exporter: Optional[VideoExporter] = None
        self._export_queue: List[FileItem] = []

        self._build_ui()
        self._load_settings()
        self._scan_input_dir()

    # ── UI construction ─────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # --- Top splitter: file list (left) + preview (right) ---
        top_splitter = QSplitter(Qt.Orientation.Horizontal)

        # -- Left: file list group --
        left_widget = QWidget()
        left_lay = QVBoxLayout(left_widget)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(12)

        file_group = QGroupBox("Programs (check to export)")
        fg_lay = QVBoxLayout(file_group)

        # Buttons row
        btn_row = QHBoxLayout()
        self.scan_btn = QPushButton("Scan input/ folder")
        self.scan_btn.clicked.connect(self._scan_input_dir)
        btn_row.addWidget(self.scan_btn)

        btn_row.addWidget(QLabel("Depth:"))
        self.depth_cb = QComboBox()
        self.depth_cb.addItem("Unlimited", -1)
        self.depth_cb.addItem("Top only", 0)
        self.depth_cb.addItem("1 level", 1)
        self.depth_cb.addItem("2 levels", 2)
        self.depth_cb.addItem("3 levels", 3)
        self.depth_cb.addItem("5 levels", 5)
        self.depth_cb.setCurrentIndex(0)
        self.depth_cb.setMinimumWidth(100)
        btn_row.addWidget(self.depth_cb)

        self.add_btn = QPushButton("Add files...")
        self.add_btn.clicked.connect(self._add_files)
        btn_row.addWidget(self.add_btn)

        self.add_folder_btn = QPushButton("Add folder...")
        self.add_folder_btn.clicked.connect(self._add_folder)
        btn_row.addWidget(self.add_folder_btn)

        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self._select_all)
        btn_row.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("Deselect All")
        self.deselect_all_btn.clicked.connect(self._deselect_all)
        btn_row.addWidget(self.deselect_all_btn)

        btn_row.addStretch()
        fg_lay.addLayout(btn_row)

        # Table
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Export", "File", "Folder", "Language", "Status"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Fixed)
        hdr.resizeSection(0, 60)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.Interactive)
        hdr.resizeSection(2, 120)
        hdr.setSectionResizeMode(3, QHeaderView.Fixed)
        hdr.resizeSection(3, 90)
        hdr.setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.currentRowChanged.connect(self._on_table_row_changed)
        fg_lay.addWidget(self.table)
        left_lay.addWidget(file_group)

        # -- Right: preview panel --
        right_widget = QWidget()
        right_lay = QVBoxLayout(right_widget)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(8)

        preview_group = QGroupBox("Output Preview")
        pg_lay = QVBoxLayout(preview_group)
        pg_lay.setSpacing(6)

        self.preview_label = QLabel("Select a file to see preview")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(360, 200)
        self.preview_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.preview_label.setStyleSheet(
            "background: #11111b; border: 1px solid #45475a; border-radius: 6px;"
        )
        pg_lay.addWidget(self.preview_label)

        self.preview_info = QLabel("")
        self.preview_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_info.setStyleSheet("color: #a6adc8; font-size: 11px;")
        pg_lay.addWidget(self.preview_info)

        right_lay.addWidget(preview_group)

        top_splitter.addWidget(left_widget)
        top_splitter.addWidget(right_widget)
        top_splitter.setStretchFactor(0, 3)
        top_splitter.setStretchFactor(1, 2)
        top_splitter.setSizes([550, 400])

        root.addWidget(top_splitter, stretch=1)

        # --- Settings group ---
        settings_group = QGroupBox("Settings")
        sg = QGridLayout(settings_group)
        sg.setSpacing(8)
        row = 0

        sg.addWidget(QLabel("Theme:"), row, 0)
        self.theme_cb = QComboBox()
        self.theme_cb.addItems(list(THEMES.keys()))
        self.theme_cb.setCurrentText("Dracula")
        self.theme_cb.currentTextChanged.connect(self._on_settings_changed)
        sg.addWidget(self.theme_cb, row, 1)

        sg.addWidget(QLabel("Resolution:"), row, 2)
        self.res_cb = QComboBox()
        self.res_cb.addItems(list(RESOLUTIONS.keys()))
        self.res_cb.setCurrentText("1920x1080")
        self.res_cb.currentTextChanged.connect(self._on_settings_changed)
        sg.addWidget(self.res_cb, row, 3)

        row += 1
        sg.addWidget(QLabel("Font:"), row, 0, 1, 2)
        self.font_cb = QComboBox()
        for f in SUPPORTED_FONTS:
            self.font_cb.addItem(f["label"], f["name"])
        self.font_cb.setCurrentIndex(0)
        self.font_cb.currentIndexChanged.connect(self._on_settings_changed)
        sg.addWidget(self.font_cb, row, 2, 1, 2)

        row += 1
        sg.addWidget(QLabel("IME Mode:"), row, 0, 1, 2)
        self.ime_cb = QComboBox()
        self.ime_cb.addItem("Auto (detect CJK)", "auto")
        self.ime_cb.addItem("Always On", "on")
        self.ime_cb.addItem("Off (direct type)", "off")
        self.ime_cb.setCurrentIndex(0)
        self.ime_cb.currentIndexChanged.connect(self._on_settings_changed)
        sg.addWidget(self.ime_cb, row, 2, 1, 2)

        row += 1
        sg.addWidget(QLabel("WPM:"), row, 0)
        self.wpm_sp = QSpinBox()
        self.wpm_sp.setRange(30, 300)
        self.wpm_sp.setValue(100)
        self.wpm_sp.valueChanged.connect(self._on_settings_changed)
        sg.addWidget(self.wpm_sp, row, 1)

        sg.addWidget(QLabel("FPS:"), row, 2)
        self.fps_sp = QSpinBox()
        self.fps_sp.setRange(10, 60)
        self.fps_sp.setValue(30)
        self.fps_sp.valueChanged.connect(self._on_settings_changed)
        sg.addWidget(self.fps_sp, row, 3)

        row += 1
        sg.addWidget(QLabel("Start Pause (s):"), row, 0)
        self.start_pause_sp = QDoubleSpinBox()
        self.start_pause_sp.setRange(0, 10)
        self.start_pause_sp.setSingleStep(0.5)
        self.start_pause_sp.setValue(0.5)
        self.start_pause_sp.valueChanged.connect(self._on_settings_changed)
        sg.addWidget(self.start_pause_sp, row, 1)

        sg.addWidget(QLabel("End Pause (s):"), row, 2)
        self.end_pause_sp = QDoubleSpinBox()
        self.end_pause_sp.setRange(0, 10)
        self.end_pause_sp.setSingleStep(0.5)
        self.end_pause_sp.setValue(1.5)
        self.end_pause_sp.valueChanged.connect(self._on_settings_changed)
        sg.addWidget(self.end_pause_sp, row, 3)

        row += 1
        self.sound_chk = QCheckBox("Typing Sounds")
        self.sound_chk.setChecked(True)
        self.sound_chk.stateChanged.connect(self._on_settings_changed)
        sg.addWidget(self.sound_chk, row, 0, 1, 2)

        sg.addWidget(QLabel("Volume:"), row, 2)
        self.vol_sl = QSpinBox()
        self.vol_sl.setRange(0, 100)
        self.vol_sl.setValue(50)
        self.vol_sl.setSuffix("%")
        self.vol_sl.valueChanged.connect(self._on_settings_changed)
        sg.addWidget(self.vol_sl, row, 3)

        row += 1
        sg.addWidget(QLabel("Sound Preset:"), row, 0, 1, 2)
        self.sound_preset_cb = QComboBox()
        self.sound_preset_cb.addItems(list(SOUND_PRESETS.keys()))
        self.sound_preset_cb.setCurrentText("Mechanical Keyboard")
        self.sound_preset_cb.currentTextChanged.connect(self._on_settings_changed)
        sg.addWidget(self.sound_preset_cb, row, 2, 1, 2)

        row += 1
        self.kb_chk = QCheckBox("Show Keyboard Overlay")
        self.kb_chk.setChecked(False)
        self.kb_chk.stateChanged.connect(self._on_settings_changed)
        sg.addWidget(self.kb_chk, row, 0, 1, 2)

        sg.addWidget(QLabel("Layout:"), row, 2)
        self.kb_layout_cb = QComboBox()
        self.kb_layout_cb.addItems(list(KEYBOARD_LAYOUTS.keys()))
        self.kb_layout_cb.setCurrentText("Qwerty")
        self.kb_layout_cb.currentTextChanged.connect(self._on_settings_changed)
        sg.addWidget(self.kb_layout_cb, row, 3)

        row += 1
        sg.addWidget(QLabel("KB Opacity:"), row, 0, 1, 2)
        self.kb_opacity_sp = QSpinBox()
        self.kb_opacity_sp.setRange(10, 100)
        self.kb_opacity_sp.setValue(85)
        self.kb_opacity_sp.setSuffix("%")
        self.kb_opacity_sp.valueChanged.connect(self._on_settings_changed)
        sg.addWidget(self.kb_opacity_sp, row, 2, 1, 2)

        # Save / Load settings buttons
        row += 1
        save_load_row = QHBoxLayout()
        save_load_row.addStretch()

        self.save_settings_btn = QPushButton("Save Settings")
        self.save_settings_btn.setObjectName("settingsBtn")
        self.save_settings_btn.clicked.connect(self._save_settings)
        save_load_row.addWidget(self.save_settings_btn)

        self.load_settings_btn = QPushButton("Load Settings")
        self.load_settings_btn.setObjectName("settingsBtn")
        self.load_settings_btn.clicked.connect(self._load_settings_dialog)
        save_load_row.addWidget(self.load_settings_btn)

        sg.addLayout(save_load_row, row, 0, 1, 4)

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

        # --- Preview update timer ---
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(200)
        self._preview_timer.timeout.connect(self._update_preview)

    # ── File scanning ───────────────────────────────────────────────

    def _scan_input_dir(self):
        self._items.clear()
        if not os.path.isdir(INPUT_DIR):
            self.statusBar().showMessage(f"input/ folder not found at {INPUT_DIR}")
            self._refresh_table()
            return
        max_depth = self.depth_cb.currentData()
        paths = _scan_dir_recursive(INPUT_DIR, max_depth=max_depth)
        for fpath in paths:
            self._items.append(FileItem(path=fpath))
        self._refresh_table()
        depth_label = self.depth_cb.currentText().lower()
        self.statusBar().showMessage(
            f"Found {len(self._items)} code file(s) in {INPUT_DIR}/ ({depth_label})"
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

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Folder to Scan", ""
        )
        if not folder:
            return
        max_depth = self.depth_cb.currentData()
        paths = _scan_dir_recursive(folder, max_depth=max_depth)
        added = 0
        for p in paths:
            if not any(it.path == p for it in self._items):
                self._items.append(FileItem(path=p))
                added += 1
        self._refresh_table()
        self.statusBar().showMessage(
            f"Added {added} file(s) from {folder}/"
        )

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

            # Folder (relative to INPUT_DIR, or parent dir for external files)
            try:
                rel_dir = os.path.relpath(os.path.dirname(item.path), INPUT_DIR)
                if rel_dir == ".":
                    folder_text = "(root)"
                else:
                    folder_text = rel_dir
            except ValueError:
                folder_text = os.path.dirname(item.path)
            folder_item = QTableWidgetItem(folder_text)
            folder_item.setForeground(QColor("#a6adc8"))
            self.table.setItem(i, 2, folder_item)

            # Language
            ext = os.path.splitext(item.path)[1].lower()
            lang = EXT_TO_LANGUAGE.get(ext, "Python")
            self.table.setItem(i, 3, QTableWidgetItem(lang))

            # Status
            status_item = QTableWidgetItem(item.status)
            if item.status == "Done":
                status_item.setForeground(QColor("#50fa7b"))
            elif item.status == "Failed":
                status_item.setForeground(QColor("#ff5555"))
            elif item.status == "Rendering":
                status_item.setForeground(QColor("#8be9fd"))
            self.table.setItem(i, 4, status_item)

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

        # Resolve font family (auto-detect if needed)
        font_family = self.font_cb.currentData() or "Consolas"
        if font_family == "Consolas":
            # Auto-detect script and suggest CJK font if needed
            script = _detect_script(code)
            if script in ("cjk", "japanese", "korean", "mixed"):
                font_family = _suggest_font(script)

        font_size = CodeRenderer.auto_font_size(
            code_lines=code.count("\n") + 1,
            width=w, height=h,
            code=code,
            font_family=font_family,
        )

        title = f"{os.path.basename(item.path)} - Code Editor"

        renderer = CodeRenderer(
            width=w, height=h,
            theme_name=self.theme_cb.currentText(),
            font_family=font_family,
            font_size=font_size,
            title_text=title,
            language=language,
        )

        ime_mode = self.ime_cb.currentData() or "auto"
        animator = TypingAnimator(
            code,
            wpm=self.wpm_sp.value(),
            start_pause=self.start_pause_sp.value(),
            end_pause=self.end_pause_sp.value(),
            ime_mode=ime_mode,
        )

        # Output path — preserve subfolder structure under output/
        try:
            rel_path = os.path.relpath(item.path, INPUT_DIR)
        except ValueError:
            # File is on a different drive / mount — just use basename
            rel_path = os.path.basename(item.path)
        base = os.path.splitext(rel_path)[0]
        out_dir = os.path.join(OUTPUT_DIR, os.path.dirname(base))
        os.makedirs(out_dir, exist_ok=True)
        output = os.path.join(out_dir, f"{os.path.basename(base)}.mp4")

        sound_gen = None
        if self.sound_chk.isChecked():
            sound_gen = SoundGen(
                preset_name=self.sound_preset_cb.currentText()
            )

        # Keyboard overlay
        kb_overlay = None
        if self.kb_chk.isChecked():
            kb_overlay = KeyboardOverlay(
                width=w, height=h,
                layout_name=self.kb_layout_cb.currentText(),
                opacity=self.kb_opacity_sp.value() / 100.0,
                theme=THEMES.get(self.theme_cb.currentText(), THEMES["Dracula"]),
            )

        self._exporter = VideoExporter(
            code=code,
            output=output,
            renderer=renderer,
            animator=animator,
            fps=self.fps_sp.value(),
            sound_gen=sound_gen,
            volume=self.vol_sl.value() / 100.0,
            keyboard_overlay=kb_overlay,
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

    def _on_table_row_changed(self, row: int):
        """Trigger a debounced preview update when the selected row changes."""
        self._preview_timer.start()

    def _on_settings_changed(self):
        """Re-render preview when any setting widget changes."""
        self._preview_timer.start()

    def _schedule_preview(self):
        self._preview_timer.start()

    # ── Settings save / load ──────────────────────────────────────

    def _gather_settings(self) -> dict:
        return {
            "theme": self.theme_cb.currentText(),
            "resolution": self.res_cb.currentText(),
            "font_family": self.font_cb.currentData(),
            "ime_mode": self.ime_cb.currentData(),
            "wpm": self.wpm_sp.value(),
            "fps": self.fps_sp.value(),
            "start_pause": self.start_pause_sp.value(),
            "end_pause": self.end_pause_sp.value(),
            "sound_enabled": self.sound_chk.isChecked(),
            "volume": self.vol_sl.value(),
            "sound_preset": self.sound_preset_cb.currentText(),
            "kb_show": self.kb_chk.isChecked(),
            "kb_layout": self.kb_layout_cb.currentText(),
            "kb_opacity": self.kb_opacity_sp.value(),
        }

    def _apply_settings(self, s: dict) -> None:
        """Apply a settings dict to the UI widgets (no preview refresh)."""
        # Block signals to avoid cascading preview updates
        for w in (self.theme_cb, self.res_cb, self.font_cb, self.ime_cb,
                  self.wpm_sp, self.fps_sp,
                  self.start_pause_sp, self.end_pause_sp, self.vol_sl,
                  self.sound_preset_cb, self.kb_layout_cb, self.kb_opacity_sp):
            w.blockSignals(True)
        self.sound_chk.blockSignals(True)
        self.kb_chk.blockSignals(True)

        if "theme" in s and s["theme"] in THEMES:
            self.theme_cb.setCurrentText(s["theme"])
        if "resolution" in s and s["resolution"] in RESOLUTIONS:
            self.res_cb.setCurrentText(s["resolution"])
        if "wpm" in s:
            self.wpm_sp.setValue(int(s["wpm"]))
        if "fps" in s:
            self.fps_sp.setValue(int(s["fps"]))
        if "start_pause" in s:
            self.start_pause_sp.setValue(float(s["start_pause"]))
        if "end_pause" in s:
            self.end_pause_sp.setValue(float(s["end_pause"]))
        if "sound_enabled" in s:
            self.sound_chk.setChecked(bool(s["sound_enabled"]))
        if "volume" in s:
            self.vol_sl.setValue(int(s["volume"]))
        if "sound_preset" in s and s["sound_preset"] in SOUND_PRESETS:
            self.sound_preset_cb.setCurrentText(s["sound_preset"])
        if "kb_show" in s:
            self.kb_chk.setChecked(bool(s["kb_show"]))
        if "kb_layout" in s and s["kb_layout"] in KEYBOARD_LAYOUTS:
            self.kb_layout_cb.setCurrentText(s["kb_layout"])
        if "kb_opacity" in s:
            self.kb_opacity_sp.setValue(int(s["kb_opacity"]))
        if "font_family" in s:
            # Find matching font in the combo
            for i in range(self.font_cb.count()):
                if self.font_cb.itemData(i) == s["font_family"]:
                    self.font_cb.setCurrentIndex(i)
                    break
        if "ime_mode" in s:
            for i in range(self.ime_cb.count()):
                if self.ime_cb.itemData(i) == s["ime_mode"]:
                    self.ime_cb.setCurrentIndex(i)
                    break

        for w in (self.theme_cb, self.res_cb, self.font_cb, self.ime_cb,
                  self.wpm_sp, self.fps_sp,
                  self.start_pause_sp, self.end_pause_sp, self.vol_sl,
                  self.sound_preset_cb, self.kb_layout_cb, self.kb_opacity_sp):
            w.blockSignals(False)
        self.sound_chk.blockSignals(False)
        self.kb_chk.blockSignals(False)

    def _save_settings(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Settings", SETTINGS_FILE, "JSON Files (*.json);;All Files (*)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._gather_settings(), f, indent=2)
            self.statusBar().showMessage(f"Settings saved to {path}")
        except Exception as e:
            QMessageBox.warning(self, "Save Error", f"Could not save settings:\n{e}")

    def _load_settings(self, path: Optional[str] = None) -> None:
        if path is None:
            path = SETTINGS_FILE
            if not os.path.isfile(path):
                return  # Silent skip if no default file yet
        try:
            with open(path, "r", encoding="utf-8") as f:
                s = json.load(f)
            self._apply_settings(s)
            self.statusBar().showMessage(f"Settings loaded from {path}")
        except Exception:
            pass  # Silent on auto-load; explicit load will use file dialog

    def _load_settings_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Settings", SETTINGS_FILE, "JSON Files (*.json);;All Files (*)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                s = json.load(f)
            self._apply_settings(s)
            self.statusBar().showMessage(f"Settings loaded from {path}")
        except Exception as e:
            QMessageBox.warning(self, "Load Error", f"Could not load settings:\n{e}")

    # ── Preview ────────────────────────────────────────────────────

    def _update_preview(self) -> None:
        """Render a preview frame for the currently selected file."""
        row = self.table.currentRow()
        if row < 0 or row >= len(self._items):
            self.preview_label.clear()
            self.preview_label.setText("Select a file to see preview")
            self.preview_info.setText("")
            return

        item = self._items[row]
        try:
            with open(item.path, "r", encoding="utf-8", errors="replace") as f:
                code = f.read()
        except Exception as e:
            self.preview_label.setText(f"Cannot read file:\n{e}")
            self.preview_info.setText("")
            return

        if not code.strip():
            self.preview_label.setText("Empty file")
            self.preview_info.setText("")
            return

        # Build renderer with current settings
        ext = os.path.splitext(item.path)[1].lower()
        language = EXT_TO_LANGUAGE.get(ext, "Python")
        res_name = self.res_cb.currentText()
        w, h = RESOLUTIONS.get(res_name, (1920, 1080))

        # Resolve font family (auto-detect if needed)
        font_family = self.font_cb.currentData() or "Consolas"
        if font_family == "Consolas":
            script = _detect_script(code)
            if script in ("cjk", "japanese", "korean", "mixed"):
                font_family = _suggest_font(script)

        font_size = CodeRenderer.auto_font_size(
            code_lines=code.count("\n") + 1,
            width=w, height=h,
            code=code,
            font_family=font_family,
        )
        title = f"{os.path.basename(item.path)} - Code Editor"

        renderer = CodeRenderer(
            width=w, height=h,
            theme_name=self.theme_cb.currentText(),
            font_family=font_family,
            font_size=font_size,
            title_text=title,
            language=language,
        )

        # Show a partial frame (first ~40% of characters typed) with cursor
        total_chars = len(code)
        preview_chars = max(1, int(total_chars * 0.4))
        display_chars = list(code[:preview_chars])
        active_ch = code[preview_chars - 1] if preview_chars > 0 else ""

        # Check if we can show IME composition in preview
        comp_text = ""
        ime_mode = self.ime_cb.currentData() or "auto"
        if active_ch and ime_mode != "off":
            romanization = TypingAnimator._get_romanization(active_ch)
            if romanization:
                comp_text = romanization

        # Keyboard overlay for preview
        kb_overlay = None
        if self.kb_chk.isChecked():
            kb_overlay = KeyboardOverlay(
                width=w, height=h,
                layout_name=self.kb_layout_cb.currentText(),
                opacity=self.kb_opacity_sp.value() / 100.0,
                theme=THEMES.get(self.theme_cb.currentText(), THEMES["Dracula"]),
            )

        qimg = renderer.render_frame(
            display_chars, len(display_chars), cursor_visible=True,
            keyboard_overlay=kb_overlay, active_char=active_ch,
            composition_text=comp_text,
        )

        # Scale to fit the preview label while keeping aspect ratio
        pixmap = QPixmap.fromImage(qimg)
        label_w = self.preview_label.width() or 400
        label_h = self.preview_label.height() or 250
        scaled = pixmap.scaled(
            label_w, label_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled)

        # Info text
        duration_est = total_chars / ((self.wpm_sp.value() * 5) / 60)
        script = _detect_script(code)
        script_label = {"cjk": "中文", "japanese": "日本語", "korean": "한국어",
                         "latin": "Latin", "mixed": "Mixed"}.get(script, script)
        self.preview_info.setText(
            f"{os.path.basename(item.path)}  |  {language}  |  "
            f"{total_chars} chars  |  ~{duration_est:.1f}s at {self.wpm_sp.value()} WPM  |  "
            f"{w}x{h}  |  {self.theme_cb.currentText()}  |  "
            f"Script: {script_label}  |  Font: {font_family}"
        )

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
QPushButton#settingsBtn {
    background: #45475a; color: #cdd6f4; border: 1px solid #585b70;
    border-radius: 6px; padding: 6px 16px; font-size: 13px;
}
QPushButton#settingsBtn:hover { background: #585b70; }
QSplitter::handle { background: #45475a; width: 3px; }
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