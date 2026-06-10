#!/usr/bin/env python3
"""
Code Typing Video Generator
Creates MP4 videos of code being typed with realistic animation and sound effects.

Folder structure (auto-created in CWD):
  input/   ← Drop .py .js .ts .txt etc. files here
  output/  ← Exported MP4s land here automatically
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
    QLineEdit
)
from PySide6.QtCore import (
    Qt, QTimer, QThread, Signal, QRect, QPoint, QUrl, QSettings
)
from PySide6.QtGui import (
    QPainter, QFont, QColor, QPixmap, QFontMetrics, QImage,
    QLinearGradient, QAction, QPalette, QKeySequence, QShortcut
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


def ensure_cwd_dirs():
    """Create input/, output/, tmp/ in CWD if they don't exist."""
    for d in (INPUT_DIR, OUTPUT_DIR, TMP_DIR):
        os.makedirs(d, exist_ok=True)


# ═══════════════════════════════ THEMES ═══════════════════════════════

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

class PythonTokenizer:
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
    _COMPILED = None
    _LOCK = threading.Lock()
    logger = logging.getLogger("PythonTokenizer")

    @classmethod
    def _compile(cls):
        if cls._COMPILED is None:
            with cls._LOCK:
                if cls._COMPILED is None:
                    cls.logger.info("Compiling regex patterns for tokenizer...")
                    pat = '|'.join(f'(?P<{n}>{p})' for n, p in cls._PATTERNS)
                    cls._COMPILED = re.compile(pat, re.MULTILINE)
                    cls.logger.debug("Tokenizer regex compiled successfully.")
        return cls._COMPILED

    @classmethod
    def tokenize(cls, text):
        return [(m.lastgroup, m.group()) for m in cls._compile().finditer(text)]


# ═══════════════════════════ SOUND GENERATOR ═══════════════════════════

class TypingSoundGenerator:
    def __init__(self, sample_rate=44100, profile="Mechanical"):
        self.logger = logging.getLogger("TypingSoundGenerator")
        self.sample_rate = sample_rate
        self.profile = profile
        self.sounds = {}
        self.logger.info(f"Initializing with profile: '{profile}' at {sample_rate}Hz")
        self._generate_all()

    def _generate_all(self):
        self.logger.debug(f"Generating sound variants for profile '{self.profile}'...")
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
        self.logger.debug("Sound variants generated.")

    def _low_pass_noise(self, noise, kernel_size=4):
        kernel = np.ones(kernel_size) / kernel_size
        return np.convolve(noise, kernel, mode='same')

    # ── Mechanical ──
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

    # ── Typewriter ──
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

    # ── Soft Membrane ──
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
        logger = logging.getLogger("TypingSoundGenerator")
        scaled = (signal * volume).astype(np.int16)
        with wave.open(path, 'w') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
            w.writeframes(scaled.tobytes())
        logger.debug(f"Saved WAV to {os.path.basename(path)} (Vol: {volume:.2f}, Samples: {len(signal)})")

    def generate_audio_track(self, char_timestamps, filepath, volume=0.5):
        self.logger.info(f"Generating full audio track for export (Vol: {volume:.2f})...")
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
        self.logger.info(f"Audio track saved to {os.path.basename(filepath)} (Duration: {total:.2f}s)")


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
                 padding=50, tab_size=4, title_text="main.py — Code Editor"):
        self.logger = logging.getLogger("CodeRenderer")
        self.width = width; self.height = height; self.theme_name = theme_name
        self.theme = THEMES[theme_name]; self.font_family = font_family; self.font_size = font_size
        self.show_line_numbers = show_line_numbers; self.show_window_chrome = show_window_chrome
        self.padding = padding; self.tab_size = tab_size; self.title_text = title_text
        self.title_bar_h = 42 if show_window_chrome else 0
        self.ln_width = 65 if show_line_numbers else 0; self.code_margin = 20
        self.font = QFont(font_family, font_size); self.font.setStyleHint(QFont.Monospace)
        self.line_h = int(font_size * 1.55)
        self._cached_text = None; self._cached_colors = None
        self.logger.info(f"Renderer initialized: {width}x{height}, Theme: {theme_name}, Font: {font_family} {font_size}")

    def render_frame(self, full_text, num_visible, cursor_visible=True):
        img = QImage(self.width, self.height, QImage.Format_RGB32)
        img.fill(QColor(self.theme["background"]))
        p = QPainter(img); p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.TextAntialiasing)
        self._draw_bg(p)
        if self.show_window_chrome: self._draw_chrome(p)

        visible_text = full_text[:num_visible]; vis_lines = visible_text.split('\n')
        cursor_line = visible_text.count('\n'); last_nl = visible_text.rfind('\n')
        cursor_col = len(visible_text) - last_nl - 1 if last_nl >= 0 else len(visible_text)
        char_colors = self._build_color_map(full_text)

        chrome = self.title_bar_h if self.show_window_chrome else 0; area_top = self.padding + chrome
        area_h = self.height - 2 * self.padding - chrome; max_vis = max(1, area_h // self.line_h)
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

        p.end()
        return img

    def _build_color_map(self, text):
        if text == self._cached_text and self._cached_colors is not None:
            self.logger.debug("Color map cache HIT.")
            return self._cached_colors
        self.logger.debug("Color map cache MISS. Tokenizing...")
        tokens = PythonTokenizer.tokenize(text); colors = ['foreground'] * len(text); pos = 0
        for ttype, ttxt in tokens:
            ckey = self.TOKEN_COLOR_MAP.get(ttype, 'foreground')
            for i in range(len(ttxt)):
                if pos + i < len(colors): colors[pos + i] = ckey
            pos += len(ttxt)
        self._cached_text = text; self._cached_colors = colors
        return colors

    def _draw_bg(self, p):
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


# ═══════════════════════════ TYPING ANIMATOR ═══════════════════════════

class TypingAnimator:
    def __init__(self, code, base_wpm=120, humanize=True):
        self.logger = logging.getLogger("TypingAnimator")
        self.code = code; self.base_wpm = base_wpm; self.humanize = humanize
        cps = (base_wpm * 5) / 60; self.base_delay = 1.0 / cps
        self.logger.info(f"Building timeline (WPM: {base_wpm}, Humanize: {humanize}, Chars: {len(code)})...")
        self.timeline = self._build_timeline()
        self._timestamps = [ts for ts, _, _ in self.timeline]
        self.logger.info(f"Timeline built. Total duration: {self.duration():.2f}s")

    def _build_timeline(self):
        rng = random.Random(); t = 0.0; events = []
        for i, ch in enumerate(self.code):
            events.append((t, i, ch)); d = self.base_delay
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
        return events

    def duration(self):
        return self.timeline[-1][0] + 0.8 if self.timeline else 1.0

    def visible_at(self, t):
        import bisect
        idx = bisect.bisect_right(self._timestamps, t)
        if idx == 0: return 0
        return self.timeline[idx - 1][1] + 1

    def char_timestamps(self):
        return [(ts, ch) for ts, _, ch in self.timeline]


# ═══════════════════════════ VIDEO EXPORTER ═══════════════════════════

class VideoExporter(QThread):
    progress = Signal(int)
    status = Signal(str)
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, code, output, renderer, animator, fps=30,
                 sound_gen=None, volume=0.5, codec_profile="YouTube 1080p",
                 crf=18, preset="medium"):
        super().__init__()
        self.logger = logging.getLogger("VideoExporter")
        self.code = code; self.output = output; self.renderer = renderer
        self.animator = animator; self.fps = fps; self.sound_gen = sound_gen
        self.volume = volume; self.codec_profile = codec_profile
        self.crf = crf; self.preset = preset; self._cancel = False
        self.logger.info(
            f"Exporter initialized. Output: {output}, FPS: {fps}, "
            f"Codec: {codec_profile}, CRF: {crf}, Preset: {preset}")

    def cancel(self):
        self.logger.warning("Cancel signal received! Stopping export...")
        self._cancel = True

    def _check_ffmpeg(self):
        try:
            r = subprocess.run(['ffmpeg', '-version'],
                               capture_output=True, timeout=5)
            return r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    # ── QImage → raw bytes ──────────────────────────────────────

    def _qimg_to_raw_rgb(self, qimg):
        """Extract contiguous RGB888 bytes from a QImage.
        Handles both old sip.voidptr and new memoryview returns."""
        qimg = qimg.convertToFormat(QImage.Format_RGB888)
        w, h = qimg.width(), qimg.height()
        bpl = qimg.bytesPerLine()
        ptr = qimg.constBits()

        if isinstance(ptr, memoryview):
            # PySide6 >= 6.5 returns memoryview — use tobytes()
            raw = ptr.tobytes()
            if len(raw) < h * bpl:
                return self._qimg_to_raw_rgb_scanline(qimg, w, h, bpl)
        elif hasattr(ptr, 'setsize'):
            # Older PySide6 returns sip.voidptr
            ptr.setsize(h * bpl)
            arr = np.array(ptr, dtype=np.uint8).reshape((h, bpl))
            if bpl != w * 3:
                arr = arr[:, :w * 3]
            return np.ascontiguousarray(arr).tobytes()
        else:
            raw = ptr.tobytes() if hasattr(ptr, 'tobytes') else bytes(ptr)

        raw = raw[:h * bpl]
        if bpl == w * 3:
            return raw
        arr = np.frombuffer(raw, dtype=np.uint8).reshape((h, bpl))
        return np.ascontiguousarray(arr[:, :w * 3]).tobytes()

    def _qimg_to_raw_rgb_scanline(self, qimg, w, h, bpl):
        """Fallback: build RGB bytes row-by-row via scanLine()."""
        rows = []
        for y in range(h):
            scan = qimg.scanLine(y)
            if isinstance(scan, memoryview):
                rows.append(scan.tobytes()[:w * 3])
            elif hasattr(scan, 'setsize'):
                scan.setsize(bpl)
                rows.append(bytes(scan)[:w * 3])
            else:
                rows.append(bytes(scan)[:w * 3])
        return b''.join(rows)

    def _qimg_to_frame(self, qimg):
        """Convert QImage → OpenCV BGR frame (for Raw MP4V fallback)."""
        raw = self._qimg_to_raw_rgb(qimg)
        w, h = qimg.width(), qimg.height()
        arr = np.frombuffer(raw, dtype=np.uint8).reshape((h, w, 3)).copy()
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

    # ── Frame rendering helper ──────────────────────────────────

    def _render_frame_at(self, t, blink_period=0.53):
        nv = self.animator.visible_at(t)
        cur_vis = True; last_ts = 0
        for ts, idx, _ in self.animator.timeline:
            if idx == nv - 1:
                last_ts = ts; break
        since = t - last_ts
        if since > 0.25:
            cur_vis = (int(since / blink_period) % 2) == 0
        return self.renderer.render_frame(self.code, nv, cur_vis)

    # ── Main export entry point ─────────────────────────────────

    def run(self):
        tmp = None
        try:
            # Temp dir in CWD/tmp/
            os.makedirs(TMP_DIR, exist_ok=True)
            tmp = tempfile.mkdtemp(dir=TMP_DIR, prefix='export_')
            aud_path = os.path.join(tmp, "audio.wav")
            total = self.animator.duration()
            n_frames = int(total * self.fps)
            blink_period = 0.53
            w, h = self.renderer.width, self.renderer.height

            self.logger.info(
                f"Starting export. Frames: {n_frames}, "
                f"Resolution: {w}x{h}, Duration: {total:.1f}s")

            if self.sound_gen:
                self.sound_gen.generate_audio_track(
                    self.animator.char_timestamps(), aud_path, self.volume)

            has_ffmpeg = self._check_ffmpeg()
            has_audio = (self.sound_gen is not None
                         and os.path.exists(aud_path)
                         and os.path.getsize(aud_path) > 0)

            if self.codec_profile == "Raw (Uncompressed MP4V)":
                self._export_raw(tmp, n_frames, w, h, blink_period)
            elif has_ffmpeg:
                self._export_ffmpeg_pipe(
                    tmp, aud_path, n_frames, w, h, has_audio, blink_period)
            else:
                self.error.emit(
                    "FFmpeg is required for H.264/YouTube exports "
                    "but was not found on PATH.")
                shutil.rmtree(tmp, ignore_errors=True); tmp = None
                return

            self.finished.emit(self.output)
            try:
                shutil.rmtree(tmp, ignore_errors=True); tmp = None
                self.logger.debug("Cleaned up temp dir.")
            except Exception:
                pass

        except Exception as e:
            self.logger.critical(f"Export crashed: {e}", exc_info=True)
            self.error.emit(str(e))
            if tmp:
                try: shutil.rmtree(tmp, ignore_errors=True)
                except: pass

    # ── FFmpeg pipe export (best quality, single-pass) ──────────

    def _export_ffmpeg_pipe(self, tmp, aud_path, n_frames, w, h,
                            has_audio, blink_period):
        """Pipe raw RGB frames directly to FFmpeg — no intermediate
        lossy mp4v file, single H.264 encoding pass = best quality."""

        self.logger.info("Exporting via FFmpeg pipe (single-pass H.264)...")

        vprofile = 'high' if 'YouTube' in self.codec_profile else 'main'
        vlevel = '4.2' if 'YouTube' in self.codec_profile else '4.1'

        cmd = [
            'ffmpeg', '-y',
            '-f', 'rawvideo', '-pix_fmt', 'rgb24',
            '-s', f'{w}x{h}', '-r', str(self.fps),
            '-i', 'pipe:0',
        ]
        if has_audio:
            cmd += ['-i', aud_path]

        cmd += [
            '-c:v', 'libx264',
            '-profile:v', vprofile,
            '-level', vlevel,
            '-preset', self.preset,
            '-crf', str(self.crf),
            '-pix_fmt', 'yuv420p',
            '-bf', '2',
            '-refs', '4',
            '-movflags', '+faststart',
        ]
        if has_audio:
            cmd += ['-c:a', 'aac', '-b:a', '192k', '-shortest']
        cmd.append(self.output)

        self.logger.info(f"FFmpeg: {' '.join(cmd)}")

        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

        stderr_chunks = []
        def _drain():
            while True:
                chunk = proc.stderr.read(8192)
                if not chunk: break
                stderr_chunks.append(chunk)
        drain_t = threading.Thread(target=_drain, daemon=True)
        drain_t.start()

        export_start = _time.time()
        frame_size = w * h * 3

        try:
            for fi in range(n_frames):
                if self._cancel:
                    try: proc.stdin.close()
                    except: pass
                    proc.terminate()
                    self.error.emit("Cancelled")
                    return

                t = fi / self.fps
                qimg = self._render_frame_at(t, blink_period)
                raw = self._qimg_to_raw_rgb(qimg)

                if len(raw) != frame_size:
                    raise RuntimeError(
                        f"Frame {fi}: size {len(raw)} != expected {frame_size}")

                try:
                    proc.stdin.write(raw)
                except BrokenPipeError:
                    self.logger.error("FFmpeg pipe broken during write.")
                    break

                pct = int((fi + 1) / n_frames * 100)
                self.progress.emit(pct)
                if fi % max(1, n_frames // 20) == 0 and fi > 0:
                    elapsed = _time.time() - export_start
                    eta = elapsed / (fi + 1) * (n_frames - fi - 1)
                    msg = f"Encoding... {pct}% (ETA: {int(eta)}s)"
                    self.status.emit(msg)
                    self.logger.debug(msg)

            try: proc.stdin.close()
            except: pass
            proc.wait(timeout=600)
            drain_t.join(timeout=5)

            if proc.returncode != 0:
                err = b''.join(stderr_chunks).decode(
                    'utf-8', errors='ignore')[-800:]
                self.logger.error(f"FFmpeg rc={proc.returncode}: {err}")
                raise RuntimeError(f"FFmpeg encoding failed: {err}")

            elapsed = _time.time() - export_start
            self.logger.info(
                f"FFmpeg export complete. {n_frames} frames in "
                f"{elapsed:.1f}s ({n_frames/elapsed:.1f} fps avg)")

        except Exception:
            try: proc.stdin.close()
            except: pass
            proc.terminate()
            raise

    # ── Raw MP4V fallback (OpenCV only, no re-encode) ──────────

    def _export_raw(self, tmp, n_frames, w, h, blink_period):
        vid_path = os.path.join(tmp, "video_only.mp4")
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(vid_path, fourcc, self.fps, (w, h))
        export_start = _time.time()

        for fi in range(n_frames):
            if self._cancel:
                writer.release(); self.error.emit("Cancelled"); return
            t = fi / self.fps
            qimg = self._render_frame_at(t, blink_period)
            frame = self._qimg_to_frame(qimg); writer.write(frame)
            pct = int((fi + 1) / n_frames * 100); self.progress.emit(pct)
            if fi % max(1, n_frames // 20) == 0 and fi > 0:
                elapsed = _time.time() - export_start
                eta = elapsed / (fi + 1) * (n_frames - fi - 1)
                msg = f"Rendering... {pct}% (ETA: {int(eta)}s)"
                self.status.emit(msg); self.logger.debug(msg)

        writer.release()
        shutil.copy2(vid_path, self.output)
        self.logger.info(f"Raw MP4V written to: {self.output}")


# ═══════════════════════════ MAIN WINDOW ═══════════════════════════

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("MainWindow")
        self.setWindowTitle("Code Typing Video Generator")
        self.setMinimumSize(1350, 850)

        # ── Ensure CWD folders exist ──
        ensure_cwd_dirs()

        self.is_playing = False; self.animator = None; self.renderer = None
        self.sound_gen = TypingSoundGenerator(profile="Mechanical")
        self.exporter = None; self._last_vis = 0; self._play_t0 = 0.0
        self._play_offset = 0.0; self._current_input_file = None
        self._sfx_dir = None; self._sfx = {}

        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(16)
        self._preview_timer.timeout.connect(self._tick)
        self._code_debounce = QTimer(self)
        self._code_debounce.setSingleShot(True)
        self._code_debounce.setInterval(400)
        self._code_debounce.timeout.connect(self._static_preview)

        self.logger.info("Initializing UI and Sounds...")
        self._build_ui()
        self._build_menu()
        self._build_shortcuts()
        self._init_sounds()
        self._restore_settings()
        self._refresh_input_files()
        self._static_preview()
        self.logger.info("Application startup complete.")

    # ── Sound system ────────────────────────────────────────────

    def _init_sounds(self, profile="Mechanical"):
        # Clean up old sfx dir
        if self._sfx_dir and os.path.isdir(self._sfx_dir):
            try: shutil.rmtree(self._sfx_dir, ignore_errors=True)
            except: pass

        os.makedirs(TMP_DIR, exist_ok=True)
        self._sfx_dir = tempfile.mkdtemp(dir=TMP_DIR, prefix='sfx_')
        self._sfx = {}
        self.sound_gen = TypingSoundGenerator(profile=profile)
        volume = self.snd_vol_sl.value() / 100.0 if hasattr(self, 'snd_vol_sl') else 0.5
        self.logger.info(f"Initializing preview sounds (Profile: {profile}, Vol: {volume:.2f})")
        for kind in ('key', 'space', 'enter'):
            for i, snd in enumerate(self.sound_gen.sounds[kind][:3]):
                path = os.path.join(self._sfx_dir, f"{kind}_{i}.wav")
                self.sound_gen.save_wav(path, snd, volume=volume)
                eff = QSoundEffect(self)
                eff.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
                eff.setVolume(0.8)
                self._sfx[(kind, i)] = eff

    def _play_click(self, ch):
        kind = 'enter' if ch == '\n' else 'space' if ch == ' ' else 'key'
        key = (kind, random.randint(0, 2)); sfx = self._sfx.get(key)
        if sfx: sfx.play()

    # ── Input / Output folder helpers ───────────────────────────

    def _scan_input_folder(self):
        """Return sorted list of (display_name, full_path) for files in input/."""
        files = []
        if not os.path.isdir(INPUT_DIR):
            return files
        for fname in sorted(os.listdir(INPUT_DIR), key=str.lower):
            fpath = os.path.join(INPUT_DIR, fname)
            if os.path.isfile(fpath):
                ext = os.path.splitext(fname)[1].lower()
                if ext in SUPPORTED_EXTENSIONS or ext == '':
                    files.append((fname, fpath))
        return files

    def _refresh_input_files(self):
        """Re-scan input/ folder and update the combo box."""
        self.input_file_cb.blockSignals(True)
        current_data = self.input_file_cb.currentData()
        self.input_file_cb.clear()
        self.input_file_cb.addItem("— Select file from input/ —", None)

        files = self._scan_input_folder()
        selected_idx = 0
        for i, (display, fpath) in enumerate(files):
            size_kb = os.path.getsize(fpath) / 1024
            label = f"{display}  ({size_kb:.1f} KB)"
            self.input_file_cb.addItem(label, fpath)
            if fpath == current_data:
                selected_idx = i + 1  # +1 for the placeholder

        if files:
            self.input_file_cb.setCurrentIndex(selected_idx)
        self.input_file_cb.blockSignals(False)

        count = len(files)
        self.logger.info(f"Scanned input/ folder: {count} file(s) found.")
        self.statusBar().showMessage(
            f"📂 input/ — {count} file(s)  |  📂 output/ — auto-export destination")

    def _on_input_file_selected(self, index):
        """Load selected file from input/ into the editor."""
        fpath = self.input_file_cb.itemData(index)
        if not fpath or not os.path.isfile(fpath):
            return

        try:
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            self.editor.setPlainText(content)
            self._current_input_file = fpath

            # Auto-update window title to match filename
            fname = os.path.basename(fpath)
            self.title_edit.setText(f"{fname} — Code Editor")

            self.logger.info(f"Loaded: {fpath}")
            self.statusBar().showMessage(f"Loaded: {fname}")
        except Exception as e:
            self.logger.error(f"Failed to load {fpath}: {e}")
            QMessageBox.warning(self, "Load Error", f"Could not read file:\n{e}")

    def _save_to_input(self):
        """Save current editor content as a new file in input/."""
        code = self.editor.toPlainText()
        if not code.strip():
            QMessageBox.information(self, "Empty", "Nothing to save — editor is empty.")
            return

        name, ok = QInputDialog.getText(
            self, "Save to input/", "Filename:",
            text="snippet.py")
        if not ok or not name.strip():
            return

        name = name.strip()
        if not os.path.splitext(name)[1]:
            name += ".py"

        fpath = os.path.join(INPUT_DIR, name)
        if os.path.exists(fpath):
            resp = QMessageBox.question(
                self, "Overwrite?",
                f"'{name}' already exists in input/. Overwrite?",
                QMessageBox.Yes | QMessageBox.No)
            if resp != QMessageBox.Yes:
                return

        try:
            with open(fpath, 'w', encoding='utf-8') as f:
                f.write(code)
            self._current_input_file = fpath
            self._refresh_input_files()
            # Select the newly saved file
            for i in range(self.input_file_cb.count()):
                if self.input_file_cb.itemData(i) == fpath:
                    self.input_file_cb.setCurrentIndex(i)
                    break
            self.logger.info(f"Saved to: {fpath}")
            self.statusBar().showMessage(f"Saved: {name} → input/")
        except Exception as e:
            QMessageBox.warning(self, "Save Error", f"Could not save file:\n{e}")

    def _get_auto_output_path(self):
        """Determine the automatic output path for export."""
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        if self._current_input_file and os.path.isfile(self._current_input_file):
            base = os.path.splitext(os.path.basename(self._current_input_file))[0]
        else:
            base = "code_typing"

        output_path = os.path.join(OUTPUT_DIR, f"{base}.mp4")

        # Avoid overwriting: append _2, _3, etc.
        if os.path.exists(output_path):
            counter = 2
            while os.path.exists(os.path.join(OUTPUT_DIR, f"{base}_{counter}.mp4")):
                counter += 1
            output_path = os.path.join(OUTPUT_DIR, f"{base}_{counter}.mp4")

        return output_path

    # ── UI construction ─────────────────────────────────────────

    def _build_ui(self):
        cw = QWidget(); self.setCentralWidget(cw)
        root = QHBoxLayout(cw); root.setSpacing(8)

        # ── Left panel ──
        left = QWidget(); ll = QVBoxLayout(left); ll.setContentsMargins(4, 4, 4, 4)

        # ── Code Input group ──
        eg = QGroupBox("Code Input"); el = QVBoxLayout(eg)

        # Input file row
        file_row = QHBoxLayout()
        file_row.addWidget(QLabel("📂 input/:"))
        self.input_file_cb = QComboBox()
        self.input_file_cb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.input_file_cb.setStyleSheet(
            "QComboBox{background:#1e1e2e;color:#cdd6f4;border:1px solid #45475a;"
            "border-radius:4px;padding:4px 8px}"
            "QComboBox::drop-down{border:none}"
            "QComboBox QAbstractItemView{background:#1e1e2e;color:#cdd6f4;"
            "selection-background-color:#45475a}")
        self.input_file_cb.currentIndexChanged.connect(self._on_input_file_selected)
        file_row.addWidget(self.input_file_cb, 1)

        refresh_btn = QPushButton("🔄")
        refresh_btn.setFixedWidth(32); refresh_btn.setToolTip("Refresh file list")
        refresh_btn.clicked.connect(self._refresh_input_files)
        refresh_btn.setStyleSheet(
            "QPushButton{background:#333;color:#fff;border:1px solid #555;"
            "border-radius:4px} QPushButton:hover{background:#555}")
        file_row.addWidget(refresh_btn)

        save_btn = QPushButton("💾 Save")
        save_btn.setToolTip("Save editor content to input/ folder")
        save_btn.clicked.connect(self._save_to_input)
        save_btn.setStyleSheet(
            "QPushButton{background:#4CAF50;color:#fff;border:none;"
            "border-radius:4px;padding:4px 10px;font-weight:bold}"
            "QPushButton:hover{background:#43a047}")
        file_row.addWidget(save_btn)

        browse_btn = QPushButton("📂")
        browse_btn.setFixedWidth(32); browse_btn.setToolTip("Browse for file")
        browse_btn.clicked.connect(self._load_file)
        browse_btn.setStyleSheet(
            "QPushButton{background:#333;color:#fff;border:1px solid #555;"
            "border-radius:4px} QPushButton:hover{background:#555}")
        file_row.addWidget(browse_btn)

        el.addLayout(file_row)

        # Editor
        self.editor = QTextEdit()
        self.editor.setFont(QFont("Consolas", 11))
        self.editor.setPlainText(self._sample_py())
        self.editor.setAcceptRichText(False)
        self.editor.setStyleSheet(
            "QTextEdit{background:#1e1e2e;color:#cdd6f4;"
            "border:1px solid #45475a;border-radius:4px}")
        el.addWidget(self.editor)
        self.editor.textChanged.connect(self._on_code_changed)

        # Sample buttons row
        bl = QHBoxLayout()
        for label, fn in [("Python", self._sample_py),
                          ("JavaScript", self._sample_js),
                          ("Load File", self._load_file)]:
            b = QPushButton(label); b.clicked.connect(fn); bl.addWidget(b)
        el.addLayout(bl); ll.addWidget(eg, 3)

        # ── Settings group ──
        sg = QGroupBox("Settings"); sl = QVBoxLayout(sg)

        # Visuals
        vg = QGroupBox("Visuals"); vl = QFormLayout(vg)
        self.theme_cb = QComboBox()
        self.theme_cb.addItems(THEMES.keys())
        self.theme_cb.currentTextChanged.connect(self._on_setting_changed)
        vl.addRow("Theme:", self.theme_cb)
        self.font_cb = QFontComboBox()
        self.font_cb.setFontFilters(QFontComboBox.MonospacedFonts)
        self.font_cb.setCurrentFont(QFont("Consolas"))
        self.font_cb.currentFontChanged.connect(self._on_setting_changed)
        vl.addRow("Font:", self.font_cb)
        self.size_sp = QSpinBox(); self.size_sp.setRange(10, 48)
        self.size_sp.setValue(22)
        self.size_sp.valueChanged.connect(self._on_setting_changed)
        vl.addRow("Font Size:", self.size_sp)
        self.tab_sp = QSpinBox(); self.tab_sp.setRange(2, 8)
        self.tab_sp.setValue(4)
        self.tab_sp.valueChanged.connect(self._on_setting_changed)
        vl.addRow("Tab Size:", self.tab_sp)
        self.title_edit = QLineEdit("main.py — Code Editor")
        self.title_edit.textChanged.connect(self._on_setting_changed)
        vl.addRow("Window Title:", self.title_edit)
        self.ln_chk = QCheckBox("Line Numbers"); self.ln_chk.setChecked(True)
        self.ln_chk.toggled.connect(self._on_setting_changed)
        vl.addRow(self.ln_chk)
        self.chrome_chk = QCheckBox("Window Chrome"); self.chrome_chk.setChecked(True)
        self.chrome_chk.toggled.connect(self._on_setting_changed)
        vl.addRow(self.chrome_chk)
        sl.addWidget(vg)

        # Animation & Sound
        ag = QGroupBox("Animation & Sound"); al = QFormLayout(ag)
        self.wpm_sp = QSpinBox(); self.wpm_sp.setRange(20, 600)
        self.wpm_sp.setValue(100); self.wpm_sp.setSuffix(" WPM")
        al.addRow("Speed:", self.wpm_sp)
        self.human_chk = QCheckBox("Humanize Typing")
        self.human_chk.setChecked(True); al.addRow(self.human_chk)
        self.snd_chk = QCheckBox("Enable Sounds")
        self.snd_chk.setChecked(True); al.addRow(self.snd_chk)
        self.snd_profile_cb = QComboBox()
        self.snd_profile_cb.addItems(["Mechanical", "Typewriter", "Soft Membrane"])
        self.snd_profile_cb.currentTextChanged.connect(self._on_sound_profile_changed)
        al.addRow("Sound Profile:", self.snd_profile_cb)
        vh = QHBoxLayout()
        self.snd_vol_sl = QSlider(Qt.Horizontal)
        self.snd_vol_sl.setRange(0, 100); self.snd_vol_sl.setValue(50)
        self.snd_vol_lbl = QLabel("50%")
        self.snd_vol_sl.valueChanged.connect(
            lambda v: (self.snd_vol_lbl.setText(f"{v}%"), self._update_volume()))
        vh.addWidget(self.snd_vol_sl); vh.addWidget(self.snd_vol_lbl)
        al.addRow("Volume:", vh)
        sl.addWidget(ag)

        # Export
        eg2 = QGroupBox("Export → output/"); el2 = QFormLayout(eg2)
        self.output_path_lbl = QLabel("output/code_typing.mp4")
        self.output_path_lbl.setStyleSheet("color:#89b4fa;font-size:11px")
        self.output_path_lbl.setWordWrap(True)
        el2.addRow("Auto output:", self.output_path_lbl)
        self.res_cb = QComboBox()
        self.res_cb.addItems(["1920x1080", "1280x720", "3840x2160", "1080x1920"])
        el2.addRow("Resolution:", self.res_cb)
        self.fps_sp = QSpinBox(); self.fps_sp.setRange(10, 60)
        self.fps_sp.setValue(30); self.fps_sp.setSuffix(" FPS")
        el2.addRow("Frame Rate:", self.fps_sp)
        self.codec_cb = QComboBox()
        self.codec_cb.addItems([
            "YouTube 1080p", "High Quality (H.264)", "Raw (Uncompressed MP4V)"])
        self.codec_cb.setCurrentText("YouTube 1080p")
        el2.addRow("Codec:", self.codec_cb)
        self.crf_sp = QSpinBox(); self.crf_sp.setRange(0, 51)
        self.crf_sp.setValue(18)
        el2.addRow("Quality (CRF):", self.crf_sp)
        self.preset_cb = QComboBox()
        self.preset_cb.addItems([
            "ultrafast", "superfast", "veryfast", "faster", "fast",
            "medium", "slow", "slower", "veryslow"])
        self.preset_cb.setCurrentText("medium")
        el2.addRow("Speed (Preset):", self.preset_cb)
        sl.addWidget(eg2)

        ll.addWidget(sg, 2)
        root.addWidget(left, 2)

        # ── Right panel (preview) ──
        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(4, 4, 4, 4)
        pg = QGroupBox("Preview"); pl = QVBoxLayout(pg)
        self.preview = QLabel(); self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(640, 360)
        self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview.setStyleSheet("background:#111;border-radius:8px;")
        pl.addWidget(self.preview, 1)

        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 10000); self.seek_slider.setValue(0)
        self.seek_slider.setStyleSheet(
            "QSlider::groove:horizontal{background:#333;height:6px;border-radius:3px}"
            "QSlider::handle:horizontal{background:#4CAF50;width:14px;"
            "margin:-4px 0;border-radius:7px}"
            "QSlider::sub-page:horizontal{background:#4CAF50;border-radius:3px}")
        self.seek_slider.sliderPressed.connect(self._on_seek_pressed)
        self.seek_slider.sliderReleased.connect(self._on_seek_released)
        self.seek_slider.sliderMoved.connect(self._on_seek_moved)
        self._seeking = False
        pl.addWidget(self.seek_slider)

        cl = QHBoxLayout()
        self.play_btn = QPushButton("▶ Play"); self.play_btn.setFixedHeight(36)
        self.play_btn.setStyleSheet(
            "QPushButton{background:#4CAF50;color:#fff;border:none;"
            "border-radius:5px;font-weight:bold;font-size:13px;padding:0 18px}"
            "QPushButton:hover{background:#43a047}"
            "QPushButton:disabled{background:#555}")
        self.play_btn.clicked.connect(self._toggle_play)
        cl.addWidget(self.play_btn)

        self.stop_btn = QPushButton("■ Stop"); self.stop_btn.setFixedHeight(36)
        self.stop_btn.setStyleSheet(
            "QPushButton{background:#f44336;color:#fff;border:none;"
            "border-radius:5px;font-weight:bold;font-size:13px;padding:0 18px}"
            "QPushButton:hover{background:#d32f2f}"
            "QPushButton:disabled{background:#555}")
        self.stop_btn.clicked.connect(self._stop)
        cl.addWidget(self.stop_btn)

        self.time_lbl = QLabel("0:00 / 0:00")
        self.time_lbl.setStyleSheet("color:#aaa;font-size:12px;padding:0 8px")
        cl.addWidget(self.time_lbl); cl.addStretch()

        self.export_btn = QPushButton("⬇ Export MP4"); self.export_btn.setFixedHeight(36)
        self.export_btn.setStyleSheet(
            "QPushButton{background:#2196F3;color:#fff;border:none;"
            "border-radius:5px;font-weight:bold;font-size:13px;padding:0 22px}"
            "QPushButton:hover{background:#1976D2}"
            "QPushButton:disabled{background:#555}")
        self.export_btn.clicked.connect(self._export)
        cl.addWidget(self.export_btn)

        pl.addLayout(cl)
        self.progress = QProgressBar(); self.progress.setVisible(False)
        pl.addWidget(self.progress)
        rl.addWidget(pg)
        root.addWidget(right, 3)

        self.statusBar().showMessage(
            "📂 input/ → load files  |  📂 output/ → auto-export  |  "
            "Shortcuts: Space=Play  Esc=Stop  Ctrl+E=Export  Ctrl+O=Open")

    def _build_menu(self):
        mb = self.menuBar()
        fm = mb.addMenu("File")
        a = QAction("Open File...", self); a.triggered.connect(self._load_file)
        fm.addAction(a)
        a = QAction("Refresh input/ Folder", self)
        a.triggered.connect(self._refresh_input_files)
        fm.addAction(a)
        fm.addSeparator()
        a = QAction("Open input/ Folder", self)
        a.triggered.connect(lambda: os.startfile(INPUT_DIR) if sys.platform == 'win32' else None)
        fm.addAction(a)
        a = QAction("Open output/ Folder", self)
        a.triggered.connect(lambda: os.startfile(OUTPUT_DIR) if sys.platform == 'win32' else None)
        fm.addAction(a)
        fm.addSeparator()
        a = QAction("Exit", self); a.triggered.connect(self.close)
        fm.addAction(a)

    def _build_shortcuts(self):
        QShortcut(QKeySequence(Qt.Key_Space), self, self._toggle_play)
        QShortcut(QKeySequence(Qt.Key_Escape), self, self._stop)
        QShortcut(QKeySequence("Ctrl+E"), self, self._export)
        QShortcut(QKeySequence("Ctrl+O"), self, self._load_file)
        QShortcut(QKeySequence("Ctrl+R"), self, self._refresh_input_files)
        QShortcut(QKeySequence("Ctrl+S"), self, self._save_to_input)

    # ── Settings persistence ────────────────────────────────────

    def _restore_settings(self):
        s = QSettings("CodeTypingVideo", "CodeTypingVideo")
        self.theme_cb.setCurrentText(s.value("theme", "Dracula", type=str))
        self.font_cb.setCurrentFont(QFont(s.value("font", "Consolas", type=str)))
        self.size_sp.setValue(s.value("font_size", 22, type=int))
        self.wpm_sp.setValue(s.value("wpm", 100, type=int))
        self.fps_sp.setValue(s.value("fps", 30, type=int))
        self.tab_sp.setValue(s.value("tab_size", 4, type=int))
        self.res_cb.setCurrentText(s.value("resolution", "1920x1080", type=str))
        self.ln_chk.setChecked(s.value("line_numbers", True, type=bool))
        self.chrome_chk.setChecked(s.value("window_chrome", True, type=bool))
        self.human_chk.setChecked(s.value("humanize", True, type=bool))
        self.snd_chk.setChecked(s.value("sounds", True, type=bool))
        self.snd_profile_cb.setCurrentText(
            s.value("snd_profile", "Mechanical", type=str))
        self.snd_vol_sl.setValue(s.value("snd_volume", 50, type=int))
        self.title_edit.setText(
            s.value("title_text", "main.py — Code Editor", type=str))
        self.codec_cb.setCurrentText(s.value("codec", "YouTube 1080p", type=str))
        self.crf_sp.setValue(s.value("crf", 18, type=int))
        self.preset_cb.setCurrentText(s.value("preset", "medium", type=str))
        geo = s.value("geometry")
        if geo: self.restoreGeometry(geo)
        self._update_output_path_label()
        self.logger.info("User settings restored.")

    def _save_settings(self):
        s = QSettings("CodeTypingVideo", "CodeTypingVideo")
        s.setValue("theme", self.theme_cb.currentText())
        s.setValue("font", self.font_cb.currentFont().family())
        s.setValue("font_size", self.size_sp.value())
        s.setValue("wpm", self.wpm_sp.value())
        s.setValue("fps", self.fps_sp.value())
        s.setValue("tab_size", self.tab_sp.value())
        s.setValue("resolution", self.res_cb.currentText())
        s.setValue("line_numbers", self.ln_chk.isChecked())
        s.setValue("window_chrome", self.chrome_chk.isChecked())
        s.setValue("humanize", self.human_chk.isChecked())
        s.setValue("sounds", self.snd_chk.isChecked())
        s.setValue("snd_profile", self.snd_profile_cb.currentText())
        s.setValue("snd_volume", self.snd_vol_sl.value())
        s.setValue("title_text", self.title_edit.text())
        s.setValue("codec", self.codec_cb.currentText())
        s.setValue("crf", self.crf_sp.value())
        s.setValue("preset", self.preset_cb.currentText())
        s.setValue("geometry", self.saveGeometry())
        self.logger.info("User settings saved.")

    # ── Renderer / Animator factories ───────────────────────────

    def _make_renderer(self, preview=False):
        res = self.res_cb.currentText().replace('\u00d7', 'x').replace('×', 'x')
        w, h = map(int, res.split('x'))
        if preview:
            scale = min(960 / w, 540 / h, 1.0)
            w, h = int(w * scale), int(h * scale)
            pad = max(20, int(30 * scale)); fs = max(8, int(self.size_sp.value() * scale))
        else:
            pad = 50; fs = self.size_sp.value()
        return CodeRenderer(
            width=w, height=h, theme_name=self.theme_cb.currentText(),
            font_family=self.font_cb.currentFont().family(), font_size=fs,
            show_line_numbers=self.ln_chk.isChecked(),
            show_window_chrome=self.chrome_chk.isChecked(),
            padding=pad, tab_size=self.tab_sp.value(),
            title_text=self.title_edit.text())

    def _make_animator(self):
        code = self.editor.toPlainText().replace('\r\n', '\n').replace('\r', '\n')
        return TypingAnimator(code, base_wpm=self.wpm_sp.value(),
                              humanize=self.human_chk.isChecked())

    # ── Event handlers ──────────────────────────────────────────

    def _on_code_changed(self):
        if self.is_playing: self._stop()
        self.animator = None; self._code_debounce.start()
        self._update_output_path_label()

    def _on_setting_changed(self, *args):
        if self.is_playing: self._stop()
        self.animator = None; self._static_preview()

    def _on_sound_profile_changed(self, profile):
        self.logger.info(f"Sound profile changed to: {profile}")
        self._init_sounds(profile=profile); self._static_preview()

    def _update_volume(self):
        self._init_sounds(profile=self.snd_profile_cb.currentText())

    def _update_output_path_label(self):
        path = self._get_auto_output_path()
        rel = os.path.relpath(path, CWD)
        self.output_path_lbl.setText(rel)
        self.output_path_lbl.setToolTip(path)

    # ── Preview ─────────────────────────────────────────────────

    def _static_preview(self, *_):
        if self.is_playing: return
        try:
            r = self._make_renderer(preview=True)
            code = self.editor.toPlainText()
            if not code.strip():
                self.preview.setText(
                    "<span style='color:#666;font-size:14px'>"
                    "Paste code or select a file from input/</span>")
                return
            img = r.render_frame(code, len(code), False)
            pm = QPixmap.fromImage(img)
            self.preview.setPixmap(
                pm.scaled(self.preview.size(),
                          Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception as e:
            self.logger.error(f"Preview rendering error: {e}", exc_info=True)
            self.preview.setText(f"Preview error: {e}")

    # ── Playback ────────────────────────────────────────────────

    def _toggle_play(self):
        if self.is_playing:
            self.is_playing = False; self._preview_timer.stop()
            self._play_offset += _time.time() - self._play_t0
            self.play_btn.setText("▶ Play")
            self.logger.info("Playback paused.")
        else:
            self.is_playing = True
            if not self.animator:
                self.animator = self._make_animator()
                self.renderer = self._make_renderer(preview=True)
                self._play_offset = 0.0; self._last_vis = 0
                self.seek_slider.setRange(
                    0, max(1, int(self.animator.duration() * 1000)))
            self._play_t0 = _time.time()
            self._preview_timer.start()
            self.play_btn.setText("⏸ Pause")
            self.logger.info("Playback started/resumed.")

    def _stop(self):
        self.is_playing = False; self._preview_timer.stop()
        self.animator = None; self.renderer = None
        self._play_offset = 0.0; self._last_vis = 0
        self.play_btn.setText("▶ Play")
        self.seek_slider.setValue(0)
        self._static_preview()
        self.logger.info("Playback stopped.")

    def _on_seek_pressed(self):
        self._seeking = True

    def _on_seek_released(self):
        self._seeking = False

    def _on_seek_moved(self, value):
        if not self.animator: return
        t = value / 1000.0
        self._play_offset = t; self._play_t0 = _time.time()
        self._last_vis = self.animator.visible_at(t)
        dur = self.animator.duration(); cur_vis = True
        if t < dur:
            nv = self.animator.visible_at(t); last_ts = 0
            for ts, idx, _ in self.animator.timeline:
                if idx == nv - 1: last_ts = ts; break
            since = t - last_ts
            if since > 0.2: cur_vis = (int(since / 0.53) % 2) == 0
            img = self.renderer.render_frame(self.animator.code, nv, cur_vis)
            self.preview.setPixmap(
                QPixmap.fromImage(img).scaled(
                    self.preview.size(),
                    Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.time_lbl.setText(
                f"{int(t)//60}:{int(t)%60:02d} / "
                f"{int(dur)//60}:{int(dur)%60:02d}")

    def _tick(self):
        if not self.animator or not self.renderer: return
        t = self._play_offset + (_time.time() - self._play_t0)
        dur = self.animator.duration()
        if t >= dur:
            self._stop()
            self.statusBar().showMessage("Playback complete")
            return
        nv = self.animator.visible_at(t)
        if self.snd_chk.isChecked() and nv > self._last_vis:
            for i in range(max(self._last_vis, nv - 3), nv):
                if i < len(self.animator.code):
                    self._play_click(self.animator.code[i])
        self._last_vis = nv; last_ts = 0
        for ts, idx, _ in self.animator.timeline:
            if idx == nv - 1: last_ts = ts; break
        cur_vis = True; since = t - last_ts
        if since > 0.2: cur_vis = (int(since / 0.53) % 2) == 0
        img = self.renderer.render_frame(self.animator.code, nv, cur_vis)
        self.preview.setPixmap(
            QPixmap.fromImage(img).scaled(
                self.preview.size(),
                Qt.KeepAspectRatio, Qt.SmoothTransformation))
        if not self._seeking:
            self.seek_slider.blockSignals(True)
            self.seek_slider.setValue(int(t * 1000))
            self.seek_slider.blockSignals(False)
        self.time_lbl.setText(
            f"{int(t)//60}:{int(t)%60:02d} / "
            f"{int(dur)//60}:{int(dur)%60:02d}")

    # ── File operations ─────────────────────────────────────────

    def _load_file(self):
        """Open file dialog, copy selected file to input/, and load it."""
        fpath, _ = QFileDialog.getOpenFileName(
            self, "Load Code File", INPUT_DIR,
            "Code Files (*.py *.js *.ts *.java *.c *.cpp *.h *.go *.rs "
            "*.rb *.php *.swift *.kt *.sql *.html *.css *.json *.yaml "
            "*.txt *.md *.sh *.lua *.dart);;All Files (*)")
        if not fpath: return

        # Copy to input/ folder if not already there
        fname = os.path.basename(fpath)
        dest = os.path.join(INPUT_DIR, fname)
        if os.path.abspath(fpath) != os.path.abspath(dest):
            if os.path.exists(dest):
                resp = QMessageBox.question(
                    self, "Copy to input/?",
                    f"'{fname}' already exists in input/. Overwrite?",
                    QMessageBox.Yes | QMessageBox.No)
                if resp != QMessageBox.Yes:
                    # Load the file directly without copying
                    self._load_file_path(fpath)
                    return
            try:
                shutil.copy2(fpath, dest)
                self.logger.info(f"Copied to input/: {fname}")
            except Exception as e:
                self.logger.warning(f"Could not copy to input/: {e}")

        self._refresh_input_files()
        self._load_file_path(dest)

    def _load_file_path(self, fpath):
        """Load a specific file path into the editor."""
        try:
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            self.editor.setPlainText(content)
            self._current_input_file = fpath
            fname = os.path.basename(fpath)
            self.title_edit.setText(f"{fname} — Code Editor")
            # Select in combo box
            for i in range(self.input_file_cb.count()):
                if self.input_file_cb.itemData(i) == fpath:
                    self.input_file_cb.blockSignals(True)
                    self.input_file_cb.setCurrentIndex(i)
                    self.input_file_cb.blockSignals(False)
                    break
            self._update_output_path_label()
            self.logger.info(f"Loaded: {fpath}")
            self.statusBar().showMessage(f"Loaded: {fname}")
        except Exception as e:
            QMessageBox.warning(self, "Load Error", f"Could not read file:\n{e}")

    # ── Export ──────────────────────────────────────────────────

    def _export(self):
        code = self.editor.toPlainText()
        if not code.strip():
            QMessageBox.warning(self, "Empty", "No code to export.")
            return
        if self.exporter and self.exporter.isRunning():
            QMessageBox.warning(self, "Busy", "Export already in progress.")
            return

        output_path = self._get_auto_output_path()

        renderer = self._make_renderer(preview=False)
        animator = self._make_animator()

        self.exporter = VideoExporter(
            code=code, output=output_path, renderer=renderer,
            animator=animator, fps=self.fps_sp.value(),
            sound_gen=self.sound_gen if self.snd_chk.isChecked() else None,
            volume=self.snd_vol_sl.value() / 100.0,
            codec_profile=self.codec_cb.currentText(),
            crf=self.crf_sp.value(),
            preset=self.preset_cb.currentText())

        self.exporter.progress.connect(self._on_export_progress)
        self.exporter.status.connect(self.statusBar().showMessage)
        self.exporter.finished.connect(self._on_export_finished)
        self.exporter.error.connect(self._on_export_error)

        self._set_ui_enabled(False)
        self.progress.setVisible(True); self.progress.setValue(0)

        rel = os.path.relpath(output_path, CWD)
        self.statusBar().showMessage(f"Exporting → {rel} ...")
        self.logger.info(f"Export started → {output_path}")
        self.exporter.start()

    def _on_export_progress(self, pct):
        self.progress.setValue(pct)

    def _on_export_finished(self, path):
        self._set_ui_enabled(True)
        self.progress.setVisible(False)
        rel = os.path.relpath(path, CWD)
        self.statusBar().showMessage(f"✅ Export complete → {rel}")
        self.logger.info(f"Export finished: {path}")

        # Open output folder
        if sys.platform == 'win32':
            os.startfile(OUTPUT_DIR)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', OUTPUT_DIR])
        else:
            subprocess.Popen(['xdg-open', OUTPUT_DIR])

        QMessageBox.information(
            self, "Export Complete",
            f"Video saved to:\n{rel}\n\n"
            f"Size: {os.path.getsize(path) / (1024*1024):.1f} MB")

    def _on_export_error(self, msg):
        self._set_ui_enabled(True)
        self.progress.setVisible(False)
        self.statusBar().showMessage(f"❌ Export failed")
        self.logger.error(f"Export error: {msg}")
        QMessageBox.critical(self, "Export Error", msg)

    def _set_ui_enabled(self, enabled):
        for w in (self.editor, self.export_btn, self.play_btn,
                  self.input_file_cb, self.theme_cb, self.font_cb,
                  self.res_cb, self.codec_cb, self.wpm_sp, self.fps_sp):
            w.setEnabled(enabled)

    # ── Window events ───────────────────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self.is_playing:
            self._static_preview()

    def closeEvent(self, event):
        self._save_settings()
        if self.exporter and self.exporter.isRunning():
            self.exporter.cancel()
            self.exporter.wait(3000)
        # Clean up temp dirs
        if self._sfx_dir and os.path.isdir(self._sfx_dir):
            try: shutil.rmtree(self._sfx_dir, ignore_errors=True)
            except: pass
        # Clean up tmp/ export leftovers
        if os.path.isdir(TMP_DIR):
            try: shutil.rmtree(TMP_DIR, ignore_errors=True)
            except: pass
        super().closeEvent(event)

    # ── Sample code ─────────────────────────────────────────────

    def _sample_py(self):
        return '''#!/usr/bin/env python3
"""
Code Typing Video Generator
Creates satisfying videos of code being typed with sound effects.
"""

import numpy as np
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Particle:
    """A single particle in the simulation."""
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    mass: float = 1.0
    color: str = "#ffffff"

    def update(self, dt: float, gravity: float = 9.81):
        """Update particle position using Verlet integration."""
        self.vy += gravity * dt
        self.x += self.vx * dt
        self.y += self.vy * dt

    @property
    def kinetic_energy(self) -> float:
        return 0.5 * self.mass * (self.vx**2 + self.vy**2)


class ParticleSystem:
    """Manages a collection of particles with physics."""

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.particles: List[Particle] = []
        self.time = 0.0

    def add_particle(self, x: float, y: float, **kwargs) -> Particle:
        particle = Particle(x=x, y=y, **kwargs)
        self.particles.append(particle)
        return particle

    def step(self, dt: float = 0.016):
        """Advance simulation by one timestep."""
        self.time += dt
        for p in self.particles:
            p.update(dt)
            # Boundary collision
            if p.y > self.height:
                p.y = self.height
                p.vy *= -0.8  # Energy loss on bounce
            if p.x < 0 or p.x > self.width:
                p.vx *= -0.9

    def find_nearest(self, x: float, y: float) -> Optional[Particle]:
        """Find the particle closest to a point."""
        if not self.particles:
            return None
        return min(self.particles,
                   key=lambda p: (p.x - x)**2 + (p.y - y)**2)

    @property
    def total_energy(self) -> float:
        return sum(p.kinetic_energy for p in self.particles)


if __name__ == "__main__":
    system = ParticleSystem(800, 600)
    for i in range(50):
        system.add_particle(
            x=np.random.uniform(0, 800),
            y=np.random.uniform(0, 300),
            vx=np.random.uniform(-50, 50),
            vy=np.random.uniform(-20, 20),
            color=np.random.choice(["#ff6b6b", "#4ecdc4", "#45b7d1"])
        )

    for _ in range(300):
        system.step(dt=0.016)

    print(f"Total energy: {system.total_energy:.2f} J")
    print(f"Particles: {len(system.particles)}")
    print(f"Sim time: {system.time:.2f}s")
'''

    def _sample_js(self):
        return '''/**
 * Real-time Particle System
 * High-performance canvas rendering with WebGL
 */

class ParticleSystem {
  constructor(config = {}) {
    this.particles = [];
    this.maxCount = config.maxCount || 10000;
    this.gravity = config.gravity || -9.81;
    this.bounds = config.bounds || { width: 800, height: 600 };
    this.gl = null;
    this.buffers = {};
  }

  async init(canvas) {
    this.gl = canvas.getContext("webgl2");
    if (!this.gl) throw new Error("WebGL2 not supported");

    this._setupShaders();
    this._createBuffers();
    return this;
  }

  _setupShaders() {
    const vsSource = `#version 300 es
      in vec2 a_position;
      in vec4 a_color;
      out vec4 v_color;
      uniform mat4 u_projection;
      void main() {
        gl_Position = u_projection * vec4(a_position, 0.0, 1.0);
        gl_PointSize = 3.0;
        v_color = a_color;
      }
    `;

    const fsSource = `#version 300 es
      precision mediump float;
      in vec4 v_color;
      out vec4 fragColor;
      void main() {
        fragColor = v_color;
      }
    `;

    this.program = this._compileProgram(vsSource, fsSource);
  }

  _compileProgram(vs, fs) {
    const gl = this.gl;
    const vert = gl.createShader(gl.VERTEX_SHADER);
    gl.shaderSource(vert, vs);
    gl.compileShader(vert);

    const frag = gl.createShader(gl.FRAGMENT_SHADER);
    gl.shaderSource(frag, fs);
    gl.compileShader(frag);

    const prog = gl.createProgram();
    gl.attachShader(prog, vert);
    gl.attachShader(prog, frag);
    gl.linkProgram(prog);
    return prog;
  }

  emit(count, origin, spread = 1.0) {
    for (let i = 0; i < count; i++) {
      if (this.particles.length >= this.maxCount) break;
      this.particles.push({
        x: origin.x + (Math.random() - 0.5) * spread * 50,
        y: origin.y + (Math.random() - 0.5) * spread * 50,
        vx: (Math.random() - 0.5) * 100,
        vy: Math.random() * 80 + 20,
        life: 1.0,
        decay: 0.005 + Math.random() * 0.01,
        r: Math.random(),
        g: 0.5 + Math.random() * 0.5,
        b: 0.8 + Math.random() * 0.2
      });
    }
  }

  update(dt) {
    for (let i = this.particles.length - 1; i >= 0; i--) {
      const p = this.particles[i];
      p.vy += this.gravity * dt;
      p.x += p.vx * dt;
      p.y += p.vy * dt;
      p.life -= p.decay;

      if (p.life <= 0 || p.y < -10) {
        this.particles.splice(i, 1);
      }
    }
  }

  get count() {
    return this.particles.length;
  }
}

// Initialize and run
const system = new ParticleSystem({ maxCount: 5000 });
system.init(document.querySelector("canvas")).then(() => {
  console.log("Particle system ready!");
  console.log(`Max particles: ${system.maxCount}`);
});
'''


# ═══════════════════════════ ENTRY POINT ═══════════════════════════

def main():
    ensure_cwd_dirs()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Dark palette
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#1e1e2e"))
    palette.setColor(QPalette.WindowText, QColor("#cdd6f4"))
    palette.setColor(QPalette.Base, QColor("#181825"))
    palette.setColor(QPalette.AlternateBase, QColor("#1e1e2e"))
    palette.setColor(QPalette.ToolTipBase, QColor("#1e1e2e"))
    palette.setColor(QPalette.ToolTipText, QColor("#cdd6f4"))
    palette.setColor(QPalette.Text, QColor("#cdd6f4"))
    palette.setColor(QPalette.Button, QColor("#313244"))
    palette.setColor(QPalette.ButtonText, QColor("#cdd6f4"))
    palette.setColor(QPalette.BrightText, QColor("#f38ba8"))
    palette.setColor(QPalette.Highlight, QColor("#89b4fa"))
    palette.setColor(QPalette.HighlightedText, QColor("#1e1e2e"))
    app.setPalette(palette)

    window = MainWindow()
    window.show()
    logging.getLogger("Main").info("Main window shown. Entering event loop.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()