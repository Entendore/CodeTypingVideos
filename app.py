#!/usr/bin/env python3
"""
Code Typing Video Generator
Creates MP4/WebM/GIF videos of code being typed with realistic animation and sound effects.

Folder structure (auto-created in CWD):
  input/   ← Drop .py .js .ts .txt etc. files here
  output/  ← Exported videos land here automatically
  tmp/     ← Temp files (sounds, intermediate video), cleaned on exit
"""

import sys
import os
import random
import wave
import tempfile
import subprocess
import re
import shutil
import time as _time
import threading
import logging
from pathlib import Path

import numpy as np

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QLabel, QComboBox, QGroupBox,
    QFileDialog, QProgressBar, QSplitter, QSpinBox, QFontComboBox,
    QCheckBox, QMessageBox, QFormLayout, QSizePolicy, QSlider,
    QLineEdit, QInputDialog
)
from PySide6.QtCore import (
    Qt, QTimer, QThread, Signal, QRect, QPoint, QUrl, QSettings
)
from PySide6.QtGui import (
    QPainter, QFont, QColor, QPixmap, QFontMetrics, QImage,
    QLinearGradient, QAction, QPalette, QKeySequence, QShortcut,
    QDragEnterEvent, QDropEvent
)
from PySide6.QtMultimedia import QSoundEffect

import cv2

# ── Logging ────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)-25s | %(message)s',
    datefmt='%H:%M:%S'
)

# ── CWD-based directories ──────────────────────────────────────────
CWD = os.getcwd()
INPUT_DIR = os.path.join(CWD, "input")
OUTPUT_DIR = os.path.join(CWD, "output")
TMP_DIR = os.path.join(CWD, "tmp")

SUPPORTED_EXTENSIONS = {
    '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.c', '.cpp', '.h',
    '.hpp', '.cs', '.go', '.rs', '.rb', '.php', '.swift', '.kt',
    '.scala', '.r', '.m', '.sh', '.bash', '.zsh', '.fish', '.ps1',
    '.sql', '.html', '.css', '.scss', '.less', '.json', '.yaml',
    '.yml', '.toml', '.ini', '.cfg', '.conf', '.txt', '.md', '.rst',
    '.lua', '.vim', '.el', '.clj', '.ex', '.exs', '.erl', '.hs',
    '.ml', '.fs', '.dart', '.groovy', '.v', '.sv', '.vhd', '.tcl',
}

RESOLUTION_PRESETS = {
    "YouTube 1080p": (1920, 1080),
    "YouTube 4K": (3840, 2160),
    "TikTok / Reels": (1080, 1920),
    "Instagram Square": (1080, 1080),
    "Twitter / X": (1280, 720),
}

KEYBOARD_ROWS = [
    list("`1234567890-="),
    list("qwertyuiop[]\\"),
    list("asdfghjkl;'"),
    list("zxcvbnm,./"),
    [" "]
]
KEY_WIDTH = 40
KEY_HEIGHT = 40
KEY_MARGIN = 4

def ensure_cwd_dirs():
    for d in (INPUT_DIR, OUTPUT_DIR, TMP_DIR):
        os.makedirs(d, exist_ok=True)

# ═══════════════════════════ THEMES ═══════════════════════════════

THEMES = {
    "Dracula": {
        "background": "#282a36", "foreground": "#f8f8f2", "comment": "#6272a4",
        "keyword": "#ff79c6", "string": "#f1fa8c", "number": "#bd93f9",
        "function": "#50fa7b", "builtin": "#8be9fd", "decorator": "#50fa7b",
        "operator": "#ff79c6", "class_name": "#8be9fd",
        "line_number": "#6272a4", "current_line": "#44475a",
        "cursor": "#f8f8f2", "title_bar": "#21222c", "title_text": "#8be9fd",
        "window_border": "#191a21", "button_close": "#ff5555",
        "button_min": "#f1fa8c", "button_max": "#50fa7b",
    },
    "One Dark": {
        "background": "#282c34", "foreground": "#abb2bf", "comment": "#5c6370",
        "keyword": "#c678dd", "string": "#98c379", "number": "#d19a66",
        "function": "#61afef", "builtin": "#e5c07b", "decorator": "#56b6c2",
        "operator": "#c678dd", "class_name": "#e5c07b",
        "line_number": "#4b5263", "current_line": "#2c313c",
        "cursor": "#528bff", "title_bar": "#21252b", "title_text": "#61afef",
        "window_border": "#181a1f", "button_close": "#e06c75",
        "button_min": "#e5c07b", "button_max": "#98c379",
    },
    "Monokai": {
        "background": "#272822", "foreground": "#f8f8f2", "comment": "#75715e",
        "keyword": "#f92672", "string": "#e6db74", "number": "#ae81ff",
        "function": "#a6e22e", "builtin": "#66d9ef", "decorator": "#a6e22e",
        "operator": "#f92672", "class_name": "#66d9ef",
        "line_number": "#75715e", "current_line": "#3e3d32",
        "cursor": "#f8f8f2", "title_bar": "#1e1f1c", "title_text": "#a6e22e",
        "window_border": "#1e1f1c", "button_close": "#f92672",
        "button_min": "#e6db74", "button_max": "#a6e22e",
    },
    "Nord": {
        "background": "#2e3440", "foreground": "#d8dee9", "comment": "#616e88",
        "keyword": "#81a1c1", "string": "#a3be8c", "number": "#b48ead",
        "function": "#88c0d0", "builtin": "#5e81ac", "decorator": "#8fbcbb",
        "operator": "#81a1c1", "class_name": "#8fbcbb",
        "line_number": "#4c566a", "current_line": "#3b4252",
        "cursor": "#d8dee9", "title_bar": "#242933", "title_text": "#88c0d0",
        "window_border": "#242933", "button_close": "#bf616a",
        "button_min": "#ebcb8b", "button_max": "#a3be8c",
    },
    "GitHub Dark": {
        "background": "#0d1117", "foreground": "#c9d1d9", "comment": "#8b949e",
        "keyword": "#ff7b72", "string": "#a5d6ff", "number": "#79c0ff",
        "function": "#d2a8ff", "builtin": "#ffa657", "decorator": "#d2a8ff",
        "operator": "#ff7b72", "class_name": "#ffa657",
        "line_number": "#484f58", "current_line": "#161b22",
        "cursor": "#c9d1d9", "title_bar": "#010409", "title_text": "#58a6ff",
        "window_border": "#010409", "button_close": "#f85149",
        "button_min": "#d29922", "button_max": "#3fb950",
    },
    "Solarized Dark": {
        "background": "#002b36", "foreground": "#839496", "comment": "#586e75",
        "keyword": "#859900", "string": "#2aa198", "number": "#d33682",
        "function": "#268bd2", "builtin": "#b58900", "decorator": "#cb4b16",
        "operator": "#859900", "class_name": "#b58900",
        "line_number": "#586e75", "current_line": "#073642",
        "cursor": "#839496", "title_bar": "#002b36", "title_text": "#268bd2",
        "window_border": "#001e26", "button_close": "#dc322f",
        "button_min": "#b58900", "button_max": "#859900",
    },
    "Catppuccin Mocha": {
        "background": "#1e1e2e", "foreground": "#cdd6f4", "comment": "#6c7086",
        "keyword": "#cba6f7", "string": "#a6e3a1", "number": "#fab387",
        "function": "#89b4fa", "builtin": "#f9e2af", "decorator": "#f5c2e7",
        "operator": "#89dceb", "class_name": "#f9e2af",
        "line_number": "#6c7086", "current_line": "#313244",
        "cursor": "#f5e0dc", "title_bar": "#181825", "title_text": "#89b4fa",
        "window_border": "#11111b", "button_close": "#f38ba8",
        "button_min": "#f9e2af", "button_max": "#a6e3a1",
    },
}

# ═══════════════════════════ SYNTAX HIGHLIGHTER ═══════════════════════════

class BaseTokenizer:
    _PATTERNS = []
    _COMPILED = None
    _LOCK = threading.Lock()

    @classmethod
    def _compile(cls):
        if cls._COMPILED is None:
            with cls._LOCK:
                if cls._COMPILED is None:
                    pat = '|'.join(f'(?P<{n}>{p})' for n, p in cls._PATTERNS)
                    cls._COMPILED = re.compile(pat, re.MULTILINE | re.DOTALL)
        return cls._COMPILED

    @classmethod
    def tokenize(cls, text):
        return [(m.lastgroup, m.group()) for m in cls._compile().finditer(text)]


class PythonTokenizer(BaseTokenizer):
    KEYWORDS = {
        'def', 'class', 'if', 'elif', 'else', 'for', 'while', 'return',
        'import', 'from', 'as', 'try', 'except', 'finally', 'with',
        'raise', 'pass', 'break', 'continue', 'and', 'or', 'not',
        'in', 'is', 'lambda', 'yield', 'global', 'nonlocal', 'assert',
        'del', 'async', 'await', 'True', 'False', 'None'
    }
    BUILTINS = {
        'print', 'len', 'range', 'int', 'str', 'float', 'list', 'dict',
        'set', 'tuple', 'type', 'isinstance', 'enumerate', 'zip', 'map',
        'filter', 'sorted', 'reversed', 'any', 'all', 'min', 'max', 'sum',
        'abs', 'round', 'input', 'open', 'super', 'property', 'staticmethod',
        'classmethod', 'hasattr', 'getattr', 'setattr', 'delattr',
        'object', 'Exception', 'ValueError', 'TypeError', 'KeyError',
        'IndexError', 'AttributeError', 'RuntimeError', 'self', 'cls',
    }
    _PATTERNS = [
        ('comment',      r'#[^\n]*'),
        ('triple_string', r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\''),
        ('string',       r'"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\''),
        ('decorator',    r'@\w+'),
        ('number',       r'\b\d+\.?\d*(?:e[+-]?\d+)?\b|0x[0-9a-fA-F]+\b'),
        ('keyword',      r'\b(?:' + '|'.join(KEYWORDS) + r')\b'),
        ('builtin',      r'\b(?:' + '|'.join(BUILTINS) + r')\b'),
        ('function',     r'\b([a-zA-Z_]\w*)\s*(?=\()'),
        ('identifier',   r'\b[a-zA-Z_]\w*\b'),
        ('operator',     r'[+\-*/%=<>!&|^~]+'),
        ('bracket',      r'[(){}[\]]'),
        ('punctuation',  r'[;:,.]'),
        ('whitespace',   r'\s+'),
        ('other',        r'.'),
    ]

class JSTokenizer(BaseTokenizer):
    KEYWORDS = {'var', 'let', 'const', 'if', 'else', 'for', 'while', 'do', 'switch', 'case', 'break', 'continue', 'function', 'return', 'class', 'new', 'this', 'super', 'extends', 'import', 'export', 'from', 'default', 'try', 'catch', 'finally', 'throw', 'typeof', 'instanceof', 'in', 'of', 'async', 'await', 'yield', 'true', 'false', 'null', 'undefined', 'void', 'delete'}
    BUILTINS = {'console', 'document', 'window', 'Math', 'Array', 'Object', 'String', 'Number', 'Boolean', 'Promise', 'Symbol', 'Map', 'Set', 'Date', 'RegExp', 'Error', 'JSON', 'parseInt', 'parseFloat', 'isNaN', 'isFinite', 'require', 'module', 'process'}
    _PATTERNS = [
        ('comment',      r'//[^\n]*|/\*[\s\S]*?\*/'),
        ('string',       r'"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\'|`[^`\\]*(?:\\.[^`\\]*)*`'),
        ('number',       r'\b\d+\.?\d*(?:e[+-]?\d+)?\b'),
        ('keyword',      r'\b(?:' + '|'.join(KEYWORDS) + r')\b'),
        ('builtin',      r'\b(?:' + '|'.join(BUILTINS) + r')\b'),
        ('function',     r'\b([a-zA-Z_]\w*)\s*(?=\()'),
        ('identifier',   r'\b[a-zA-Z_]\w*\b'),
        ('operator',     r'[+\-*/%=<>!&|^~?]+'),
        ('bracket',      r'[(){}[\]]'),
        ('punctuation',  r'[;:,.]'),
        ('whitespace',   r'\s+'),
        ('other',        r'.'),
    ]

class GenericCTokenizer(BaseTokenizer):
    KEYWORDS = {'int', 'float', 'double', 'char', 'void', 'if', 'else', 'for', 'while', 'do', 'switch', 'case', 'break', 'continue', 'return', 'struct', 'typedef', 'enum', 'union', 'const', 'static', 'extern', 'unsigned', 'signed', 'long', 'short', 'class', 'public', 'private', 'protected', 'virtual', 'override', 'namespace', 'using', 'new', 'delete', 'try', 'catch', 'throw', 'true', 'false', 'null'}
    BUILTINS = {'printf', 'scanf', 'malloc', 'free', 'sizeof', 'strlen', 'std', 'cout', 'cin', 'endl', 'string', 'vector', 'map', 'set'}
    _PATTERNS = [
        ('comment',      r'//[^\n]*|/\*[\s\S]*?\*/'),
        ('string',       r'"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\''),
        ('number',       r'\b\d+\.?\d*(?:e[+-]?\d+)?\b'),
        ('keyword',      r'\b(?:' + '|'.join(KEYWORDS) + r')\b'),
        ('builtin',      r'\b(?:' + '|'.join(BUILTINS) + r')\b'),
        ('function',     r'\b([a-zA-Z_]\w*)\s*(?=\()'),
        ('identifier',   r'\b[a-zA-Z_]\w*\b'),
        ('operator',     r'[+\-*/%=<>!&|^~]+'),
        ('bracket',      r'[(){}[\]]'),
        ('punctuation',  r'[;:,.]'),
        ('whitespace',   r'\s+'),
        ('other',        r'.'),
    ]


# ═══════════════════════════ SOUND GENERATOR ═══════════════════════════

class TypingSoundGenerator:
    def __init__(self, sample_rate=44100, profile="Mechanical"):
        self.logger = logging.getLogger("TypingSoundGenerator")
        self.sample_rate = sample_rate
        self.profile = profile
        self.sounds = {}
        self._generate_all()

    def _generate_all(self):
        if self.profile == "Mechanical":
            self.sounds['key']   = [self._mech_click(i) for i in range(8)]
            self.sounds['space'] = [self._mech_space(i) for i in range(4)]
            self.sounds['enter'] = [self._mech_enter(i) for i in range(4)]
        elif self.profile == "Typewriter":
            self.sounds['key']   = [self._typewriter_click(i) for i in range(8)]
            self.sounds['space'] = [self._typewriter_space(i) for i in range(4)]
            self.sounds['enter'] = [self._typewriter_enter(i) for i in range(4)]
        elif self.profile == "Soft Membrane":
            self.sounds['key']   = [self._membrane_click(i) for i in range(8)]
            self.sounds['space'] = [self._membrane_space(i) for i in range(4)]
            self.sounds['enter'] = [self._membrane_enter(i) for i in range(4)]

    def _low_pass_noise(self, noise, kernel_size=4):
        kernel = np.ones(kernel_size) / kernel_size
        return np.convolve(noise, kernel, mode='same')

    def _mech_click(self, v=0, dur=0.06):
        n = int(self.sample_rate * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v)
        pitch = 1.0 + (v - 3.5) * 0.06
        f_click = 3200 * pitch + rng.randint(-200, 200); click = np.sin(2 * np.pi * f_click * t) * np.exp(-t * 380) * 0.35
        f_thock = 380 * pitch + rng.randint(-30, 30); thock = np.sin(2 * np.pi * f_thock * t) * np.exp(-t * 90) * 0.45
        f_thud = 140 * pitch + rng.randint(-20, 20); thud_env = np.maximum(0, t - 0.012) * 160; thud_env = thud_env * np.exp(-(t - 0.012) * 140); thud = np.sin(2 * np.pi * f_thud * t) * thud_env * 0.35
        noise = self._low_pass_noise(rng.randn(n), 4) * np.exp(-t * 180) * 0.12
        return (np.clip(click + thock + thud + noise, -1, 1) * 32767).astype(np.int16)

    def _mech_space(self, v=0, dur=0.09):
        n = int(self.sample_rate * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 100)
        rattle = sum(np.sin(2 * np.pi * (2200 + i*450 + rng.randint(-100, 100)) * t) * np.exp(-t * 220) for i in range(3)) * 0.15
        f_res = 220 + rng.randint(-20, 20); res = np.sin(2 * np.pi * f_res * t) * np.exp(-t * 55) * 0.65
        f_thud = 90 + rng.randint(-15, 15); thud_env = np.maximum(0, t - 0.018) * 120; thud_env = thud_env * np.exp(-(t - 0.018) * 90); thud = np.sin(2 * np.pi * f_thud * t) * thud_env * 0.5
        noise = self._low_pass_noise(rng.randn(n), 6) * np.exp(-t * 110) * 0.18
        return (np.clip(rattle + res + thud + noise, -1, 1) * 32767).astype(np.int16)

    def _mech_enter(self, v=0, dur=0.08):
        n = int(self.sample_rate * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 200)
        f_click = 2000 + rng.randint(-150, 150); click = np.sin(2 * np.pi * f_click * t) * np.exp(-t * 280) * 0.45
        f_res = 180 + rng.randint(-20, 20); res = np.sin(2 * np.pi * f_res * t) * np.exp(-t * 65) * 0.6
        f_thud = 75 + rng.randint(-10, 10); thud_env = np.maximum(0, t - 0.014) * 130; thud_env = thud_env * np.exp(-(t - 0.014) * 100); thud = np.sin(2 * np.pi * f_thud * t) * thud_env * 0.55
        noise = self._low_pass_noise(rng.randn(n), 3) * np.exp(-t * 140) * 0.18
        return (np.clip(click + res + thud + noise, -1, 1) * 32767).astype(np.int16)

    def _typewriter_click(self, v=0, dur=0.08):
        n = int(self.sample_rate * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v); pitch = 1.0 + (v - 3.5) * 0.04
        f_strike = 4500 * pitch + rng.randint(-300, 300); strike = np.sin(2 * np.pi * f_strike * t) * np.exp(-t * 500) * 0.5
        f_ring = 1200 * pitch + rng.randint(-50, 50); ring = np.sin(2 * np.pi * f_ring * t) * np.exp(-t * 60) * 0.4
        noise = rng.randn(n) * np.exp(-t * 250) * 0.15
        return (np.clip(strike + ring + noise, -1, 1) * 32767).astype(np.int16)

    def _typewriter_space(self, v=0, dur=0.1):
        n = int(self.sample_rate * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 100)
        f_strike = 3000 + rng.randint(-200, 200); strike = np.sin(2 * np.pi * f_strike * t) * np.exp(-t * 350) * 0.4
        f_ring = 800 + rng.randint(-40, 40); ring = np.sin(2 * np.pi * f_ring * t) * np.exp(-t * 40) * 0.6
        noise = self._low_pass_noise(rng.randn(n), 5) * np.exp(-t * 150) * 0.2
        return (np.clip(strike + ring + noise, -1, 1) * 32767).astype(np.int16)

    def _typewriter_enter(self, v=0, dur=0.15):
        n = int(self.sample_rate * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 200)
        slide = sum(np.sin(2 * np.pi * (600 + i*150 + rng.randint(-50, 50)) * t) * np.exp(-t * 30) for i in range(3)) * 0.3
        f_ding = 2500 + rng.randint(-100, 100); ding = np.sin(2 * np.pi * f_ding * t) * np.exp(-t * 25) * 0.4
        noise = self._low_pass_noise(rng.randn(n), 6) * np.exp(-t * 50) * 0.15
        return (np.clip(slide + ding + noise, -1, 1) * 32767).astype(np.int16)

    def _membrane_click(self, v=0, dur=0.05):
        n = int(self.sample_rate * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v); pitch = 1.0 + (v - 3.5) * 0.03
        f_thud = 200 * pitch + rng.randint(-20, 20); thud = np.sin(2 * np.pi * f_thud * t) * np.exp(-t * 120) * 0.6
        noise = self._low_pass_noise(rng.randn(n), 8) * np.exp(-t * 200) * 0.2
        return (np.clip(thud + noise, -1, 1) * 32767).astype(np.int16)

    def _membrane_space(self, v=0, dur=0.06):
        n = int(self.sample_rate * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 100)
        f_thud = 120 + rng.randint(-15, 15); thud = np.sin(2 * np.pi * f_thud * t) * np.exp(-t * 80) * 0.7
        noise = self._low_pass_noise(rng.randn(n), 10) * np.exp(-t * 100) * 0.25
        return (np.clip(thud + noise, -1, 1) * 32767).astype(np.int16)

    def _membrane_enter(self, v=0, dur=0.07):
        n = int(self.sample_rate * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 200)
        f_thud = 100 + rng.randint(-10, 10); thud = np.sin(2 * np.pi * f_thud * t) * np.exp(-t * 70) * 0.8
        noise = self._low_pass_noise(rng.randn(n), 10) * np.exp(-t * 90) * 0.25
        return (np.clip(thud + noise, -1, 1) * 32767).astype(np.int16)

    def get_sound(self, char):
        if char == '\n': return random.choice(self.sounds['enter'])
        if char == ' ': return random.choice(self.sounds['space'])
        return random.choice(self.sounds['key'])

    @staticmethod
    def save_wav(path, signal, sr=44100, volume=0.5):
        scaled = (signal * volume).astype(np.int16)
        with wave.open(path, 'w') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
            w.writeframes(scaled.tobytes())

    def generate_audio_track(self, char_timestamps, filepath, volume=0.5):
        if not char_timestamps: return
        total = max(ts for ts, _ in char_timestamps) + 0.5
        n = int(self.sample_rate * total)
        audio = np.zeros(n, dtype=np.int32)
        for ts, ch in char_timestamps:
            snd = self.get_sound(ch); s = int(ts * self.sample_rate); e = min(s + len(snd), n)
            if s < n:
                mixed = audio[s:e] + (snd[:e - s] * volume).astype(np.int32)
                audio[s:e] = np.clip(mixed, -32767, 32767)
        self.save_wav(filepath, audio.astype(np.int16), self.sample_rate, 1.0)


# ═══════════════════════════ CODE RENDERER ═══════════════════════════

class CodeRenderer:
    TOKEN_COLOR_MAP = {
        'keyword': 'keyword', 'builtin': 'builtin', 'string': 'string',
        'triple_string': 'string', 'number': 'number', 'comment': 'comment',
        'decorator': 'decorator', 'function': 'function',
        'class_name': 'class_name', 'operator': 'operator',
    }

    def __init__(self, width=1920, height=1080, theme_name="Dracula",
                 font_family="Consolas", font_size=24,
                 show_line_numbers=True, show_window_chrome=True,
                 padding=50, tab_size=4, title_text="main.py — Code Editor",
                 language="Python", show_keyboard=False):
        self.logger = logging.getLogger("CodeRenderer")
        self.width = width; self.height = height; self.theme_name = theme_name
        self.theme = THEMES[theme_name]; self.font_family = font_family; self.font_size = font_size
        self.show_line_numbers = show_line_numbers; self.show_window_chrome = show_window_chrome
        self.padding = padding; self.tab_size = tab_size; self.title_text = title_text
        self.language = language; self.show_keyboard = show_keyboard
        self.pressed_key = None; self.bg_image = None
        self.title_bar_h = 42 if show_window_chrome else 0
        self.ln_width = 65 if show_line_numbers else 0; self.code_margin = 20
        self.font = QFont(font_family, font_size); self.font.setStyleHint(QFont.Monospace)
        self.line_h = int(font_size * 1.55)
        self._cached_text = None; self._cached_colors = None
        self.tokenizer_map = {
            "Python": PythonTokenizer, "JavaScript": JSTokenizer, "C/C++/Java": GenericCTokenizer
        }

    def set_background_image(self, path):
        if path and os.path.exists(path):
            self.bg_image = QPixmap(path)
        else:
            self.bg_image = None

    def render_frame(self, full_text, num_visible, cursor_visible=True):
        img = QImage(self.width, self.height, QImage.Format_RGB32)
        img.fill(QColor(self.theme["background"]))
        p = QPainter(img); p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.TextAntialiasing)
        self._draw_bg(p)
        if self.show_window_chrome: self._draw_chrome(p)

        visible_raw = full_text[:num_visible]
        visible_list = []
        for ch in visible_raw:
            if ch == '\b':
                if visible_list: visible_list.pop()
            else:
                visible_list.append(ch)
        visible_text = ''.join(visible_list)

        vis_lines = visible_text.split('\n')
        cursor_line = visible_text.count('\n')
        last_nl = visible_text.rfind('\n')
        cursor_col = len(visible_text) - last_nl - 1 if last_nl >= 0 else len(visible_text)
        char_colors = self._build_color_map(visible_text)

        chrome = self.title_bar_h if self.show_window_chrome else 0
        area_top = self.padding + chrome
        area_h = self.height - 2 * self.padding - chrome
        if self.show_keyboard:
            area_h -= 220  # Make room for keyboard overlay
            
        max_vis = max(1, area_h // self.line_h)
        scroll_margin_top = 3; scroll_margin_bottom = 5; first = 0
        if cursor_line < first + scroll_margin_top: first = max(0, cursor_line - scroll_margin_top)
        if cursor_line >= first + max_vis - scroll_margin_bottom: first = max(0, cursor_line - max_vis + scroll_margin_bottom + 1)

        line_offsets = []; off = 0
        for line in vis_lines: line_offsets.append(off); off += len(line) + 1

        fm = QFontMetrics(self.font); tab_advance = fm.horizontalAdvance(' ') * self.tab_size

        for i in range(max_vis):
            li = first + i
            if li >= len(vis_lines): break
            y = area_top + i * self.line_h
            if li == cursor_line: p.fillRect(QRect(self.padding - 12, y, self.width - 2 * self.padding + 24, self.line_h), QColor(self.theme["current_line"]))
            if self.show_line_numbers:
                ln_font = QFont(self.font_family, self.font_size - 2); ln_font.setStyleHint(QFont.Monospace); p.setFont(ln_font)
                color = QColor(self.theme["foreground"]).darker(120) if li == cursor_line else QColor(self.theme["line_number"])
                p.setPen(color); p.drawText(QRect(self.padding, y, self.ln_width, self.line_h), Qt.AlignRight | Qt.AlignVCenter, str(li + 1))

            p.setFont(self.font); start_x = self.padding + self.ln_width + self.code_margin; line = vis_lines[li]; global_off = line_offsets[li]
            if not line:
                if cursor_visible and li == cursor_line: p.fillRect(int(start_x), int(y + 5), max(2, self.font_size // 10), self.line_h - 10, QColor(self.theme["cursor"]))
                continue

            char_x = []; x = start_x
            for ch in line: char_x.append(x); x += tab_advance if ch == '\t' else fm.horizontalAdvance(ch)

            cur_color = char_colors[global_off] if global_off < len(char_colors) else 'foreground'; run_start = 0
            for j in range(1, len(line) + 1):
                next_color = 'foreground'
                if j < len(line): gp = global_off + j; next_color = char_colors[gp] if gp < len(char_colors) else 'foreground'
                if j == len(line) or next_color != cur_color:
                    run_text = line[run_start:j].replace('\t', ' ' * self.tab_size)
                    p.setPen(QColor(self.theme.get(cur_color, self.theme['foreground'])))
                    p.drawText(QPoint(int(char_x[run_start]), int(y + self.line_h * 0.78)), run_text)
                    cur_color = next_color; run_start = j

            if cursor_visible and li == cursor_line:
                cx = start_x
                for j in range(min(cursor_col, len(line))): cx += tab_advance if line[j] == '\t' else fm.horizontalAdvance(line[j])
                p.fillRect(int(cx), int(y + 5), max(2, self.font_size // 10), self.line_h - 10, QColor(self.theme["cursor"]))

        if self.show_keyboard:
            self._draw_keyboard(p, self.pressed_key)

        p.end()
        return img

    def _build_color_map(self, text):
        if text == self._cached_text and self._cached_colors is not None:
            return self._cached_colors
        tokenizer = self.tokenizer_map.get(self.language, PythonTokenizer)
        tokens = tokenizer.tokenize(text); colors = ['foreground'] * len(text); pos = 0
        for ttype, ttxt in tokens:
            ckey = self.TOKEN_COLOR_MAP.get(ttype, 'foreground')
            for i in range(len(ttxt)):
                if pos + i < len(colors): colors[pos + i] = ckey
            pos += len(ttxt)
        self._cached_text = text; self._cached_colors = colors
        return colors

    def _draw_bg(self, p):
        if self.bg_image:
            scaled = self.bg_image.scaled(self.width, self.height, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            x = (self.width - scaled.width()) // 2
            y = (self.height - scaled.height()) // 2
            p.drawPixmap(x, y, scaled)
        else:
            g = QLinearGradient(0, 0, 0, self.height); bg = QColor(self.theme["background"])
            g.setColorAt(0, bg.lighter(105)); g.setColorAt(1, bg); p.fillRect(0, 0, self.width, self.height, g)

    def _draw_chrome(self, p):
        x, y = self.padding - 14, self.padding - 14; w = self.width - 2 * self.padding + 28; h = self.height - 2 * self.padding + 28
        p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 60)); p.drawRoundedRect(x + 4, y + 4, w, h, 12, 12)
        p.setBrush(QColor(self.theme["window_border"])); p.drawRoundedRect(x, y, w, h, 12, 12)
        tb = QColor(self.theme["title_bar"]); p.setBrush(tb); p.drawRoundedRect(x, y, w, self.title_bar_h + 10, 12, 12)
        p.fillRect(x, y + 18, w, self.title_bar_h - 8, tb)
        by = y + 19
        for dx, color_key in [(20, "button_close"), (44, "button_min"), (68, "button_max")]:
            p.setBrush(QColor(self.theme[color_key])); p.drawEllipse(x + dx, by, 14, 14)
            p.setPen(QColor(0, 0, 0, 100)); p.setFont(QFont("Arial", 7, QFont.Bold))
            p.drawText(QRect(x + dx, by, 14, 14), Qt.AlignCenter, {"button_close": "×", "button_min": "−", "button_max": "+"}[color_key])
            p.setPen(Qt.NoPen)
        p.setPen(QColor(self.theme["title_text"])); p.setFont(QFont(self.font_family, 12))
        p.drawText(QRect(x, y + 10, w, self.title_bar_h), Qt.AlignCenter, self.title_text)

    def _draw_keyboard(self, p, pressed_key):
        total_width = (KEY_WIDTH + KEY_MARGIN) * 15
        total_height = (KEY_HEIGHT + KEY_MARGIN) * 5
        start_x = (self.width - total_width) // 2
        start_y = self.height - total_height - 30
        
        font = QFont("Arial", 9); p.setFont(font)
        
        for r, row in enumerate(KEYBOARD_ROWS):
            offset_x = r * (KEY_WIDTH // 2)
            for c, key in enumerate(row):
                w = KEY_WIDTH; label = key.upper(); current_pressed = pressed_key
                if key == " ":
                    w = KEY_WIDTH * 6; offset_x = (total_width - w) // 2
                    if current_pressed == "space": current_pressed = " "
                
                x = start_x + offset_x + c * (KEY_WIDTH + KEY_MARGIN)
                y = start_y + r * (KEY_HEIGHT + KEY_MARGIN)
                
                is_pressed = (current_pressed == key)
                
                p.setPen(Qt.NoPen)
                if is_pressed:
                    p.setBrush(QColor(self.theme["keyword"]).lighter(130))
                else:
                    p.setBrush(QColor(self.theme["current_line"]))
                    
                p.drawRoundedRect(x, y, w, KEY_HEIGHT, 6, 6)
                
                p.setPen(QColor(self.theme["foreground"]) if not is_pressed else QColor(self.theme["background"]))
                p.drawText(QRect(x, y, w, KEY_HEIGHT), Qt.AlignCenter, label)


# ═══════════════════════════ TYPING ANIMATOR ═══════════════════════════

class TypingAnimator:
    def __init__(self, code, base_wpm=120, humanize=True, typo_rate=0.015, start_pause=0.5, end_pause=1.5):
        self.logger = logging.getLogger("TypingAnimator")
        self.code = code; self.base_wpm = base_wpm; self.humanize = humanize
        self.typo_rate = typo_rate; self.start_pause = start_pause; self.end_pause = end_pause
        cps = (base_wpm * 5) / 60; self.base_delay = 1.0 / cps
        self.display_chars = []
        self.timeline = self._build_timeline()
        self._timestamps = [ts for ts, _, _ in self.timeline]

    def _build_timeline(self):
        rng = random.Random(); t = 0.0; events = []
        for i, ch in enumerate(self.code):
            if self.humanize and self.typo_rate > 0 and ch not in ('\n', ' ', '\t') and rng.random() < self.typo_rate:
                typo_char = rng.choice('abcdefghijklmnopqrstuvwxyz')
                self.display_chars.append(typo_char)
                events.append((t, len(self.display_chars) - 1, typo_char))
                d = self.base_delay * rng.uniform(0.5, 1.5); t += d
                
                self.display_chars.append('\b')
                events.append((t, len(self.display_chars) - 1, '\b'))
                d = self.base_delay * rng.uniform(0.5, 1.0); t += d
                
            self.display_chars.append(ch)
            events.append((t, len(self.display_chars) - 1, ch))
            
            d = self.base_delay
            if self.humanize:
                d *= rng.uniform(0.55, 1.45)
                if ch == '\n': d *= rng.uniform(2.0, 4.5)
                elif ch == ' ': d *= rng.uniform(0.7, 1.4)
                elif ch in '.,:;': d *= rng.uniform(1.6, 3.0)
                elif ch in '([{': d *= rng.uniform(1.2, 2.2)
                elif ch in ')]}': d *= rng.uniform(1.0, 1.8)
                if i >= 2 and ch == self.code[i - 1] == self.code[i - 2]: d *= 0.65
                if rng.random() < 0.018: d += rng.uniform(0.3, 1.2)
                for kw in ('def ', 'class ', 'import ', 'return ', 'if ', 'for '):
                    if self.code[i:i + len(kw)] == kw: d *= 1.6; break
            d = max(d, 0.015); t += d
            
        events = [(ts + self.start_pause, idx, ch) for ts, idx, ch in events]
        return events

    def duration(self):
        if not self.timeline: return self.start_pause + self.end_pause
        return self.timeline[-1][0] + self.end_pause

    def visible_at(self, t):
        import bisect
        if t < self.start_pause: return 0
        idx = bisect.bisect_right(self._timestamps, t)
        if idx == 0: return 0
        return self.timeline[idx - 1][1] + 1

    def char_timestamps(self):
        return [(ts, ch) for ts, _, ch in self.timeline if ch != '\b']


# ═══════════════════════════ VIDEO EXPORTER ═══════════════════════════

class VideoExporter(QThread):
    progress = Signal(int)
    status = Signal(str)
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, code, output, renderer, animator, fps=30,
                 sound_gen=None, volume=0.5, codec_profile="MP4 (H.264)",
                 crf=18, preset="medium"):
        super().__init__()
        self.code = code; self.output = output; self.renderer = renderer
        self.animator = animator; self.fps = fps; self.sound_gen = sound_gen
        self.volume = volume; self.codec_profile = codec_profile
        self.crf = crf; self.preset = preset; self._cancel = False

    def cancel(self): self._cancel = True

    def _check_ffmpeg(self):
        try:
            r = subprocess.run(['ffmpeg', '-version'], capture_output=True, timeout=5)
            return r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _qimg_to_raw_rgb(self, qimg):
        qimg = qimg.convertToFormat(QImage.Format_RGB888)
        w, h = qimg.width(), qimg.height(); bpl = qimg.bytesPerLine(); ptr = qimg.constBits()
        if isinstance(ptr, memoryview):
            raw = ptr.tobytes()
            if len(raw) < h * bpl: return self._qimg_to_raw_rgb_scanline(qimg, w, h, bpl)
        elif hasattr(ptr, 'setsize'):
            ptr.setsize(h * bpl); arr = np.array(ptr, dtype=np.uint8).reshape((h, bpl))
            if bpl != w * 3: arr = arr[:, :w * 3]
            return np.ascontiguousarray(arr).tobytes()
        else:
            raw = ptr.tobytes() if hasattr(ptr, 'tobytes') else bytes(ptr)
        raw = raw[:h * bpl]
        if bpl == w * 3: return raw
        arr = np.frombuffer(raw, dtype=np.uint8).reshape((h, bpl))
        return np.ascontiguousarray(arr[:, :w * 3]).tobytes()

    def _qimg_to_raw_rgb_scanline(self, qimg, w, h, bpl):
        rows = []
        for y in range(h):
            scan = qimg.scanLine(y)
            if isinstance(scan, memoryview): rows.append(scan.tobytes()[:w * 3])
            elif hasattr(scan, 'setsize'): scan.setsize(bpl); rows.append(bytes(scan)[:w * 3])
            else: rows.append(bytes(scan)[:w * 3])
        return b''.join(rows)

    def _qimg_to_frame(self, qimg):
        raw = self._qimg_to_raw_rgb(qimg); w, h = qimg.width(), qimg.height()
        arr = np.frombuffer(raw, dtype=np.uint8).reshape((h, w, 3)).copy()
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

    def _render_frame_at(self, t, blink_period=0.53):
        nv = self.animator.visible_at(t); cur_vis = True; last_ts = 0
        for ts, idx, _ in self.animator.timeline:
            if idx == nv - 1: last_ts = ts; break
        since = t - last_ts
        if since > 0.25: cur_vis = (int(since / blink_period) % 2) == 0
        
        pressed_key = None
        if nv > 0:
            last_ch = self.animator.display_chars[nv - 1]
            if since < 0.1:
                if last_ch == '\n': pressed_key = 'enter'
                elif last_ch == ' ': pressed_key = 'space'
                elif last_ch == '\b': pressed_key = 'backspace'
                elif last_ch != '\t': pressed_key = last_ch.lower()
        
        self.renderer.pressed_key = pressed_key
        return self.renderer.render_frame(self.animator.display_chars, nv, cur_vis)

    def run(self):
        tmp = None
        try:
            os.makedirs(TMP_DIR, exist_ok=True)
            tmp = tempfile.mkdtemp(dir=TMP_DIR, prefix='export_')
            aud_path = os.path.join(tmp, "audio.wav")
            total = self.animator.duration(); n_frames = int(total * self.fps)
            blink_period = 0.53; w, h = self.renderer.width, self.renderer.height

            is_gif = "GIF" in self.codec_profile
            has_audio = (self.sound_gen is not None and not is_gif)
            
            if has_audio:
                self.sound_gen.generate_audio_track(self.animator.char_timestamps(), aud_path, self.volume)
                has_audio = os.path.exists(aud_path) and os.path.getsize(aud_path) > 0

            has_ffmpeg = self._check_ffmpeg()
            if has_ffmpeg:
                self._export_ffmpeg_pipe(tmp, aud_path, n_frames, w, h, has_audio, blink_period)
            else:
                self.error.emit("FFmpeg is required for exports but was not found on PATH.")
                shutil.rmtree(tmp, ignore_errors=True); tmp = None; return

            self.finished.emit(self.output)
            try: shutil.rmtree(tmp, ignore_errors=True); tmp = None
            except Exception: pass
        except Exception as e:
            self.error.emit(str(e))
            if tmp:
                try: shutil.rmtree(tmp, ignore_errors=True)
                except: pass

    def _export_ffmpeg_pipe(self, tmp, aud_path, n_frames, w, h, has_audio, blink_period):
        cmd = [
            'ffmpeg', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
            '-s', f'{w}x{h}', '-r', str(self.fps), '-i', 'pipe:0',
        ]
        
        if "GIF" in self.codec_profile:
            cmd += ['-vf', f'fps={min(self.fps, 15)},scale={w}:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse']
        elif "WebM" in self.codec_profile:
            cmd += ['-c:v', 'libvpx-vp9', '-crf', '30', '-b:v', '0', '-pix_fmt', 'yuv420p']
        else:
            if has_audio: cmd += ['-i', aud_path]
            cmd += ['-c:v', 'libx264', '-profile:v', 'high', '-level', '4.2',
                    '-preset', self.preset, '-crf', str(self.crf),
                    '-pix_fmt', 'yuv420p', '-bf', '2', '-refs', '4', '-movflags', '+faststart']
            if has_audio: cmd += ['-c:a', 'aac', '-b:a', '192k', '-shortest']
            
        cmd.append(self.output)

        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        stderr_chunks = []
        def _drain():
            while True:
                chunk = proc.stderr.read(8192)
                if not chunk: break
                stderr_chunks.append(chunk)
        drain_t = threading.Thread(target=_drain, daemon=True); drain_t.start()

        export_start = _time.time(); frame_size = w * h * 3
        try:
            for fi in range(n_frames):
                if self._cancel:
                    try: proc.stdin.close()
                    except: pass
                    proc.terminate(); self.error.emit("Cancelled"); return
                t = fi / self.fps
                qimg = self._render_frame_at(t, blink_period); raw = self._qimg_to_raw_rgb(qimg)
                if len(raw) != frame_size: raise RuntimeError(f"Frame {fi}: size {len(raw)} != expected {frame_size}")
                try: proc.stdin.write(raw)
                except BrokenPipeError: break
                pct = int((fi + 1) / n_frames * 100); self.progress.emit(pct)
                if fi % max(1, n_frames // 20) == 0 and fi > 0:
                    elapsed = _time.time() - export_start; eta = elapsed / (fi + 1) * (n_frames - fi - 1)
                    self.status.emit(f"Encoding... {pct}% (ETA: {int(eta)}s)")
            try: proc.stdin.close()
            except: pass
            proc.wait(timeout=600); drain_t.join(timeout=5)
            if proc.returncode != 0:
                err = b''.join(stderr_chunks).decode('utf-8', errors='ignore')[-800:]
                raise RuntimeError(f"FFmpeg encoding failed: {err}")
        except Exception:
            try: proc.stdin.close()
            except: pass
            proc.terminate(); raise


# ═══════════════════════════ DRAG & DROP EDITOR ═══════════════════════════

class DropTextEdit(QTextEdit):
    files_dropped = Signal(str)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
        else: super().dragEnterEvent(event)
            
    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
        else: super().dragMoveEvent(event)
            
    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    self.files_dropped.emit(url.toLocalFile())
                    break
        else: super().dropEvent(event)


# ═══════════════════════════ MAIN WINDOW ═══════════════════════════

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("MainWindow")
        self.setWindowTitle("Code Typing Video Generator")
        self.setMinimumSize(1350, 850)

        ensure_cwd_dirs()

        self.is_playing = False; self.animator = None; self.renderer = None
        self.sound_gen = TypingSoundGenerator(profile="Mechanical")
        self.exporter = None; self._last_vis = 0; self._play_t0 = 0.0
        self._play_offset = 0.0; self._current_input_file = None
        self._sfx_dir = None; self._sfx = {}; self._scrubbing = False
        self._bg_image_path = None

        self._preview_timer = QTimer(self); self._preview_timer.setInterval(16)
        self._preview_timer.timeout.connect(self._tick)
        self._code_debounce = QTimer(self); self._code_debounce.setSingleShot(True)
        self._code_debounce.setInterval(400); self._code_debounce.timeout.connect(self._static_preview)

        self._build_ui()
        self._build_menu()
        self._build_shortcuts()
        self._init_sounds()
        self._restore_settings()
        self._refresh_input_files()
        self._static_preview()

    def _init_sounds(self, profile="Mechanical"):
        if self._sfx_dir and os.path.isdir(self._sfx_dir):
            try: shutil.rmtree(self._sfx_dir, ignore_errors=True)
            except: pass
        os.makedirs(TMP_DIR, exist_ok=True)
        self._sfx_dir = tempfile.mkdtemp(dir=TMP_DIR, prefix='sfx_')
        self._sfx = {}; self.sound_gen = TypingSoundGenerator(profile=profile)
        volume = self.snd_vol_sl.value() / 100.0 if hasattr(self, 'snd_vol_sl') else 0.5
        for kind in ('key', 'space', 'enter'):
            for i, snd in enumerate(self.sound_gen.sounds[kind][:3]):
                path = os.path.join(self._sfx_dir, f"{kind}_{i}.wav")
                self.sound_gen.save_wav(path, snd, volume=volume)
                eff = QSoundEffect(self); eff.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
                eff.setVolume(0.8); self._sfx[(kind, i)] = eff

    def _play_click(self, ch):
        if ch == '\b': return  # Skip sound for backspace
        kind = 'enter' if ch == '\n' else 'space' if ch == ' ' else 'key'
        key = (kind, random.randint(0, 2)); sfx = self._sfx.get(key)
        if sfx: sfx.play()

    def _scan_input_folder(self):
        files = []
        if not os.path.isdir(INPUT_DIR): return files
        for fname in sorted(os.listdir(INPUT_DIR), key=str.lower):
            fpath = os.path.join(INPUT_DIR, fname)
            if os.path.isfile(fpath):
                ext = os.path.splitext(fname)[1].lower()
                if ext in SUPPORTED_EXTENSIONS or ext == '':
                    files.append((fname, fpath))
        return files

    def _refresh_input_files(self):
        self.input_file_cb.blockSignals(True)
        current_data = self.input_file_cb.currentData()
        self.input_file_cb.clear()
        self.input_file_cb.addItem("— Select file from input/ —", None)
        files = self._scan_input_folder(); selected_idx = 0
        for i, (display, fpath) in enumerate(files):
            size_kb = os.path.getsize(fpath) / 1024
            label = f"{display}  ({size_kb:.1f} KB)"
            self.input_file_cb.addItem(label, fpath)
            if fpath == current_data: selected_idx = i + 1
        if files: self.input_file_cb.setCurrentIndex(selected_idx)
        self.input_file_cb.blockSignals(False)
        self.statusBar().showMessage(f"📂 input/ — {len(files)} file(s)")

    def _on_input_file_selected(self, index):
        fpath = self.input_file_cb.itemData(index)
        if not fpath or not os.path.isfile(fpath): return
        try:
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f: content = f.read()
            self.editor.setPlainText(content); self._current_input_file = fpath
            fname = os.path.basename(fpath); self.title_edit.setText(f"{fname} — Code Editor")
            self.statusBar().showMessage(f"Loaded: {fname}")
        except Exception as e:
            QMessageBox.warning(self, "Load Error", f"Could not read file:\n{e}")

    def _on_file_dropped(self, fpath):
        ext = os.path.splitext(fpath)[1].lower()
        if ext in SUPPORTED_EXTENSIONS:
            try:
                with open(fpath, 'r', encoding='utf-8', errors='replace') as f: content = f.read()
                self.editor.setPlainText(content); self._current_input_file = fpath
                self.title_edit.setText(f"{os.path.basename(fpath)} — Code Editor")
                self.statusBar().showMessage(f"Dropped: {os.path.basename(fpath)}")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not read dropped file:\n{e}")

    def _save_to_input(self):
        code = self.editor.toPlainText()
        if not code.strip(): return
        name, ok = QInputDialog.getText(self, "Save to input/", "Filename:", text="snippet.py")
        if not ok or not name.strip(): return
        name = name.strip()
        if not os.path.splitext(name)[1]: name += ".py"
        fpath = os.path.join(INPUT_DIR, name)
        if os.path.exists(fpath):
            if QMessageBox.question(self, "Overwrite?", f"'{name}' already exists. Overwrite?") != QMessageBox.Yes: return
        try:
            with open(fpath, 'w', encoding='utf-8') as f: f.write(code)
            self._current_input_file = fpath; self._refresh_input_files()
        except Exception as e:
            QMessageBox.warning(self, "Save Error", f"Could not save file:\n{e}")

    def _select_bg_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Background Image", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if path:
            self._bg_image_path = path
            self._static_preview()

    def _clear_bg_image(self):
        self._bg_image_path = None
        self._static_preview()

    def _get_auto_output_path(self):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        if self._current_input_file and os.path.isfile(self._current_input_file):
            base = os.path.splitext(os.path.basename(self._current_input_file))[0]
        else: base = "code_typing"
        
        fmt = self.format_cb.currentText()
        if "WebM" in fmt: ext = ".webm"
        elif "GIF" in fmt: ext = ".gif"
        else: ext = ".mp4"
        
        output_path = os.path.join(OUTPUT_DIR, f"{base}{ext}")
        if os.path.exists(output_path):
            counter = 2
            while os.path.exists(os.path.join(OUTPUT_DIR, f"{base}_{counter}{ext}")): counter += 1
            output_path = os.path.join(OUTPUT_DIR, f"{base}_{counter}{ext}")
        return output_path

    def _build_ui(self):
        cw = QWidget(); self.setCentralWidget(cw)
        root = QHBoxLayout(cw); root.setSpacing(8)

        # ── Left panel ──
        left = QWidget(); ll = QVBoxLayout(left); ll.setContentsMargins(4, 4, 4, 4)

        eg = QGroupBox("Code Input"); el = QVBoxLayout(eg)
        file_row = QHBoxLayout(); file_row.addWidget(QLabel("📂 input/:"))
        self.input_file_cb = QComboBox(); self.input_file_cb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.input_file_cb.currentIndexChanged.connect(self._on_input_file_selected)
        file_row.addWidget(self.input_file_cb, 1)
        
        refresh_btn = QPushButton("🔄"); refresh_btn.setFixedWidth(32); refresh_btn.clicked.connect(self._refresh_input_files)
        file_row.addWidget(refresh_btn)
        save_btn = QPushButton("💾 Save"); save_btn.clicked.connect(self._save_to_input)
        file_row.addWidget(save_btn)
        browse_btn = QPushButton("📂"); browse_btn.setFixedWidth(32); browse_btn.clicked.connect(self._load_file)
        file_row.addWidget(browse_btn)
        el.addLayout(file_row)

        self.editor = DropTextEdit(); self.editor.setFont(QFont("Consolas", 11))
        self.editor.setPlainText(self._sample_py()); self.editor.setAcceptRichText(False)
        self.editor.files_dropped.connect(self._on_file_dropped)
        self.editor.textChanged.connect(self._on_code_changed)
        el.addWidget(self.editor)
        
        bl = QHBoxLayout()
        for label, fn in [("Python", self._sample_py), ("JavaScript", self._sample_js), ("Load File", self._load_file)]:
            b = QPushButton(label); b.clicked.connect(fn); bl.addWidget(b)
        el.addLayout(bl); ll.addWidget(eg, 3)

        # ── Settings group ──
        sg = QGroupBox("Settings"); sl = QVBoxLayout(sg)

        vg = QGroupBox("Visuals"); vl = QFormLayout(vg)
        self.theme_cb = QComboBox(); self.theme_cb.addItems(THEMES.keys())
        self.theme_cb.currentTextChanged.connect(self._on_setting_changed)
        vl.addRow("Theme:", self.theme_cb)
        self.font_cb = QFontComboBox(); self.font_cb.setFontFilters(QFontComboBox.MonospacedFonts)
        self.font_cb.setCurrentFont(QFont("Consolas")); self.font_cb.currentFontChanged.connect(self._on_setting_changed)
        vl.addRow("Font:", self.font_cb)
        self.size_sp = QSpinBox(); self.size_sp.setRange(10, 48); self.size_sp.setValue(22)
        self.size_sp.valueChanged.connect(self._on_setting_changed); vl.addRow("Font Size:", self.size_sp)
        self.tab_sp = QSpinBox(); self.tab_sp.setRange(2, 8); self.tab_sp.setValue(4)
        self.tab_sp.valueChanged.connect(self._on_setting_changed); vl.addRow("Tab Size:", self.tab_sp)
        self.title_edit = QLineEdit("main.py — Code Editor"); self.title_edit.textChanged.connect(self._on_setting_changed)
        vl.addRow("Window Title:", self.title_edit)
        self.ln_chk = QCheckBox("Line Numbers"); self.ln_chk.setChecked(True); self.ln_chk.toggled.connect(self._on_setting_changed)
        vl.addRow(self.ln_chk)
        self.chrome_chk = QCheckBox("Window Chrome"); self.chrome_chk.setChecked(True); self.chrome_chk.toggled.connect(self._on_setting_changed)
        vl.addRow(self.chrome_chk)
        
        self.lang_cb = QComboBox(); self.lang_cb.addItems(["Python", "JavaScript", "C/C++/Java"])
        self.lang_cb.currentTextChanged.connect(self._on_setting_changed); vl.addRow("Language:", self.lang_cb)
        self.res_cb = QComboBox(); self.res_cb.addItems(RESOLUTION_PRESETS.keys())
        self.res_cb.currentTextChanged.connect(self._on_setting_changed); vl.addRow("Resolution:", self.res_cb)
        self.kb_chk = QCheckBox("Show Keyboard"); self.kb_chk.toggled.connect(self._on_setting_changed)
        vl.addRow(self.kb_chk)
        
        bg_row = QHBoxLayout()
        self.bg_btn = QPushButton("🖼 BG Image"); self.bg_btn.clicked.connect(self._select_bg_image)
        self.bg_clear_btn = QPushButton("✖"); self.bg_clear_btn.setFixedWidth(30); self.bg_clear_btn.clicked.connect(self._clear_bg_image)
        bg_row.addWidget(self.bg_btn); bg_row.addWidget(self.bg_clear_btn)
        vl.addRow(bg_row)
        sl.addWidget(vg)

        ag = QGroupBox("Animation & Sound"); al = QFormLayout(ag)
        self.wpm_sp = QSpinBox(); self.wpm_sp.setRange(20, 600); self.wpm_sp.setValue(100)
        self.wpm_sp.valueChanged.connect(self._on_setting_changed); al.addRow("WPM:", self.wpm_sp)
        self.typo_sp = QSpinBox(); self.typo_sp.setRange(0, 50); self.typo_sp.setValue(1); self.typo_sp.setSuffix(" %")
        self.typo_sp.valueChanged.connect(self._on_setting_changed); al.addRow("Typo Rate:", self.typo_sp)
        self.start_pause_sp = QSpinBox(); self.start_pause_sp.setRange(0, 10); self.start_pause_sp.setValue(1); self.start_pause_sp.setSuffix(" s")
        self.start_pause_sp.valueChanged.connect(self._on_setting_changed); al.addRow("Start Pause:", self.start_pause_sp)
        self.end_pause_sp = QSpinBox(); self.end_pause_sp.setRange(0, 10); self.end_pause_sp.setValue(2); self.end_pause_sp.setSuffix(" s")
        self.end_pause_sp.valueChanged.connect(self._on_setting_changed); al.addRow("End Pause:", self.end_pause_sp)
        
        self.snd_profile_cb = QComboBox(); self.snd_profile_cb.addItems(["Mechanical", "Typewriter", "Soft Membrane"])
        self.snd_profile_cb.currentTextChanged.connect(lambda _: self._init_sounds(self.snd_profile_cb.currentText()))
        al.addRow("Sound Profile:", self.snd_profile_cb)
        self.snd_vol_sl = QSlider(Qt.Horizontal); self.snd_vol_sl.setRange(0, 100); self.snd_vol_sl.setValue(50)
        self.snd_vol_sl.valueChanged.connect(self._on_setting_changed); al.addRow("Sound Vol:", self.snd_vol_sl)
        sl.addWidget(ag)

        xg = QGroupBox("Export"); xl = QFormLayout(xg)
        self.format_cb = QComboBox(); self.format_cb.addItems(["MP4 (H.264)", "WebM (VP9)", "GIF"])
        self.format_cb.currentTextChanged.connect(self._on_setting_changed); xl.addRow("Format:", self.format_cb)
        self.fps_sp = QSpinBox(); self.fps_sp.setRange(10, 60); self.fps_sp.setValue(30)
        self.fps_sp.valueChanged.connect(self._on_setting_changed); xl.addRow("FPS:", self.fps_sp)
        self.crf_sp = QSpinBox(); self.crf_sp.setRange(0, 51); self.crf_sp.setValue(18)
        self.crf_sp.valueChanged.connect(self._on_setting_changed); xl.addRow("CRF:", self.crf_sp)
        sl.addWidget(xg)

        ll.addWidget(sg, 2)

        # ── Right panel ──
        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(4, 4, 4, 4)
        self.preview_lbl = QLabel("Preview"); self.preview_lbl.setAlignment(Qt.AlignCenter)
        self.preview_lbl.setStyleSheet("background:#000;border-radius:8px;")
        self.preview_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        rl.addWidget(self.preview_lbl, 1)

        tl_layout = QHBoxLayout()
        self.timeline_slider = QSlider(Qt.Horizontal); self.timeline_slider.setRange(0, 1000)
        self.timeline_slider.sliderMoved.connect(self._on_timeline_scrub)
        self.timeline_slider.sliderPressed.connect(self._on_timeline_pressed)
        self.timeline_slider.sliderReleased.connect(self._on_timeline_released)
        tl_layout.addWidget(QLabel("⏪")); tl_layout.addWidget(self.timeline_slider, 1); tl_layout.addWidget(QLabel("⏩"))
        rl.addLayout(tl_layout)

        btn_row = QHBoxLayout()
        self.play_btn = QPushButton("▶ Play"); self.play_btn.clicked.connect(self._toggle_play)
        self.export_btn = QPushButton("💾 Export Video"); self.export_btn.clicked.connect(self._start_export)
        self.cancel_btn = QPushButton("✖ Cancel"); self.cancel_btn.clicked.connect(self._cancel_export); self.cancel_btn.setEnabled(False)
        self.progress_bar = QProgressBar(); self.progress_bar.setValue(0)
        btn_row.addWidget(self.play_btn); btn_row.addWidget(self.export_btn); btn_row.addWidget(self.cancel_btn)
        rl.addLayout(btn_row)
        rl.addWidget(self.progress_bar)

        root.addWidget(left, 2); root.addWidget(right, 3)

    def _build_menu(self): pass
    def _build_shortcuts(self): pass
    def _restore_settings(self): pass

    def _on_setting_changed(self):
        self._static_preview()

    def _on_code_changed(self):
        self._code_debounce.start()

    def _static_preview(self):
        code = self.editor.toPlainText()
        if not code.strip(): return
        res_name = self.res_cb.currentText(); w, h = RESOLUTION_PRESETS.get(res_name, (1920, 1080))
        self.renderer = CodeRenderer(
            width=w, height=h, theme_name=self.theme_cb.currentText(),
            font_family=self.font_cb.currentFont().family(), font_size=self.size_sp.value(),
            show_line_numbers=self.ln_chk.isChecked(), show_window_chrome=self.chrome_chk.isChecked(),
            tab_size=self.tab_sp.value(), title_text=self.title_edit.text(),
            language=self.lang_cb.currentText(), show_keyboard=self.kb_chk.isChecked()
        )
        if self._bg_image_path: self.renderer.set_background_image(self._bg_image_path)
        
        self.animator = TypingAnimator(
            code, base_wpm=self.wpm_sp.value(), humanize=True,
            typo_rate=self.typo_sp.value() / 100.0,
            start_pause=self.start_pause_sp.value(),
            end_pause=self.end_pause_sp.value()
        )
        qimg = self.renderer.render_frame(self.animator.display_chars, len(self.animator.display_chars), False)
        self._show_preview(qimg)
        self._play_offset = 0
        self.timeline_slider.setValue(0)

    def _show_preview(self, qimg):
        pixmap = QPixmap.fromImage(qimg)
        self.preview_lbl.setPixmap(pixmap.scaled(self.preview_lbl.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _toggle_play(self):
        if self.is_playing: self._pause()
        else: self._play()

    def _play(self):
        if not self.animator or not self.renderer: return
        self.is_playing = True; self._play_t0 = _time.time(); self._last_vis = 0
        self._preview_timer.start(); self.play_btn.setText("⏸ Pause")

    def _pause(self):
        self.is_playing = False; self._preview_timer.stop()
        self._play_offset += _time.time() - self._play_t0
        self.play_btn.setText("▶ Play")

    def _tick(self):
        if not self.animator or not self.renderer: return
        elapsed = _time.time() - self._play_t0 + self._play_offset
        duration = self.animator.duration()
        
        if not self._scrubbing:
            pct = min(1.0, elapsed / duration)
            self.timeline_slider.blockSignals(True); self.timeline_slider.setValue(int(pct * 1000)); self.timeline_slider.blockSignals(False)
        
        if elapsed >= duration: self._pause(); return
            
        nv = self.animator.visible_at(elapsed)
        if nv != self._last_vis:
            self._last_vis = nv
            qimg = self._render_at(elapsed); self._show_preview(qimg)
            if nv > 0: self._play_click(self.animator.display_chars[nv - 1])

    def _render_at(self, t):
        nv = self.animator.visible_at(t); cur_vis = True; last_ts = 0
        for ts, idx, _ in self.animator.timeline:
            if idx == nv - 1: last_ts = ts; break
        since = t - last_ts
        if since > 0.25: cur_vis = (int(since / 0.53) % 2) == 0
        pressed_key = None
        if nv > 0:
            last_ch = self.animator.display_chars[nv - 1]
            if since < 0.1:
                if last_ch == '\n': pressed_key = 'enter'
                elif last_ch == ' ': pressed_key = 'space'
                elif last_ch == '\b': pressed_key = 'backspace'
                elif last_ch != '\t': pressed_key = last_ch.lower()
        self.renderer.pressed_key = pressed_key
        return self.renderer.render_frame(self.animator.display_chars, nv, cur_vis)

    def _on_timeline_scrub(self, value):
        self._scrubbing = True
        if not self.animator: return
        t = (value / 1000.0) * self.animator.duration()
        qimg = self._render_at(t); self._show_preview(qimg)

    def _on_timeline_pressed(self):
        self._scrubbing = True
        if self.is_playing: self._pause()

    def _on_timeline_released(self):
        self._scrubbing = False
        if not self.animator: return
        self._play_offset = (self.timeline_slider.value() / 1000.0) * self.animator.duration()

    def _start_export(self):
        if not self.animator or not self.renderer: return
        output = self._get_auto_output_path()
        self.exporter = VideoExporter(
            self.editor.toPlainText(), output, self.renderer, self.animator,
            fps=self.fps_sp.value(), sound_gen=self.sound_gen,
            volume=self.snd_vol_sl.value() / 100.0,
            codec_profile=self.format_cb.currentText(),
            crf=self.crf_sp.value()
        )
        self.exporter.progress.connect(self.progress_bar.setValue)
        self.exporter.status.connect(self.statusBar().showMessage)
        self.exporter.finished.connect(self._on_export_done)
        self.exporter.error.connect(self._on_export_error)
        self.exporter.start()
        self.export_btn.setEnabled(False); self.cancel_btn.setEnabled(True)

    def _cancel_export(self):
        if self.exporter: self.exporter.cancel()

    def _on_export_done(self, path):
        self.statusBar().showMessage(f"✅ Exported: {path}"); self.export_btn.setEnabled(True); self.cancel_btn.setEnabled(False)

    def _on_export_error(self, msg):
        QMessageBox.critical(self, "Export Error", msg); self.export_btn.setEnabled(True); self.cancel_btn.setEnabled(False)

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Code File", "", f"Code Files (*{' '.join(SUPPORTED_EXTENSIONS)})")
        if path:
            try:
                with open(path, 'r', encoding='utf-8', errors='replace') as f: self.editor.setPlainText(f.read())
                self._current_input_file = path; self.title_edit.setText(f"{os.path.basename(path)} — Code Editor")
            except Exception as e:
                QMessageBox.warning(self, "Error", str(e))

    def _sample_py(self):
        return 'def fibonacci(n: int) -> list:\n    """Generate Fibonacci sequence"""\n    if n <= 0:\n        return []\n    sequence = [0, 1]\n    for _ in range(2, n):\n        sequence.append(sequence[-1] + sequence[-2])\n    return sequence[:n]\n\nif __name__ == "__main__":\n    result = fibonacci(10)\n    print(f"Fibonacci: {result}")'

    def _sample_js(self):
        return 'const fibonacci = (n) => {\n  // Generate Fibonacci sequence\n  if (n <= 0) return [];\n  const sequence = [0, 1];\n  for (let i = 2; i < n; i++) {\n    sequence.push(sequence[i - 1] + sequence[i - 2]);\n  }\n  return sequence.slice(0, n);\n};\n\nconst result = fibonacci(10);\nconsole.log(`Fibonacci: ${result}`);'


if __name__ == "__main__":
    ensure_cwd_dirs()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())