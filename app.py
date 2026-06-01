#!/usr/bin/env python3
"""
Code Typing Video Generator
Creates MP4 videos of code being typed with realistic animation and sound effects.
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

    @classmethod
    def _compile(cls):
        if cls._COMPILED is None:
            with cls._LOCK:
                if cls._COMPILED is None:
                    pat = '|'.join(f'(?P<{n}>{p})' for n, p in cls._PATTERNS)
                    cls._COMPILED = re.compile(pat, re.MULTILINE)
        return cls._COMPILED

    @classmethod
    def tokenize(cls, text):
        return [(m.lastgroup, m.group()) for m in cls._compile().finditer(text)]


# ═══════════════════════════ SOUND GENERATOR ═══════════════════════════

class TypingSoundGenerator:
    """
    Generates highly realistic keyboard typing sounds.
    Models distinct acoustic phases based on chosen profile.
    """

    def __init__(self, sample_rate=44100, profile="Mechanical"):
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

    # ── Mechanical (Cherry MX Style) ──

    def _mech_click(self, v=0, dur=0.06):
        n = int(self.sample_rate * dur)
        t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v)
        pitch = 1.0 + (v - 3.5) * 0.06

        f_click = 3200 * pitch + rng.randint(-200, 200)
        click = np.sin(2 * np.pi * f_click * t) * np.exp(-t * 380) * 0.35

        f_thock = 380 * pitch + rng.randint(-30, 30)
        thock = np.sin(2 * np.pi * f_thock * t) * np.exp(-t * 90) * 0.45

        f_thud = 140 * pitch + rng.randint(-20, 20)
        thud_env = np.maximum(0, t - 0.012) * 160
        thud_env = thud_env * np.exp(-(t - 0.012) * 140)
        thud = np.sin(2 * np.pi * f_thud * t) * thud_env * 0.35

        noise = self._low_pass_noise(rng.randn(n), 4) * np.exp(-t * 180) * 0.12
        sig = np.clip(click + thock + thud + noise, -1, 1)
        return (sig * 32767).astype(np.int16)

    def _mech_space(self, v=0, dur=0.09):
        n = int(self.sample_rate * dur)
        t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 100)
        
        rattle = sum(
            np.sin(2 * np.pi * (2200 + i*450 + rng.randint(-100, 100)) * t) * np.exp(-t * 220)
            for i in range(3)
        ) * 0.15
        f_res = 220 + rng.randint(-20, 20)
        res = np.sin(2 * np.pi * f_res * t) * np.exp(-t * 55) * 0.65
        f_thud = 90 + rng.randint(-15, 15)
        thud_env = np.maximum(0, t - 0.018) * 120
        thud_env = thud_env * np.exp(-(t - 0.018) * 90)
        thud = np.sin(2 * np.pi * f_thud * t) * thud_env * 0.5
        noise = self._low_pass_noise(rng.randn(n), 6) * np.exp(-t * 110) * 0.18
        sig = np.clip(rattle + res + thud + noise, -1, 1)
        return (sig * 32767).astype(np.int16)

    def _mech_enter(self, v=0, dur=0.08):
        n = int(self.sample_rate * dur)
        t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 200)
        
        f_click = 2000 + rng.randint(-150, 150)
        click = np.sin(2 * np.pi * f_click * t) * np.exp(-t * 280) * 0.45
        f_res = 180 + rng.randint(-20, 20)
        res = np.sin(2 * np.pi * f_res * t) * np.exp(-t * 65) * 0.6
        f_thud = 75 + rng.randint(-10, 10)
        thud_env = np.maximum(0, t - 0.014) * 130
        thud_env = thud_env * np.exp(-(t - 0.014) * 100)
        thud = np.sin(2 * np.pi * f_thud * t) * thud_env * 0.55
        noise = self._low_pass_noise(rng.randn(n), 3) * np.exp(-t * 140) * 0.18
        sig = np.clip(click + res + thud + noise, -1, 1)
        return (sig * 32767).astype(np.int16)

    # ── Typewriter (Metallic Ring & Strike) ──

    def _typewriter_click(self, v=0, dur=0.08):
        n = int(self.sample_rate * dur)
        t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v)
        pitch = 1.0 + (v - 3.5) * 0.04
        
        # Sharp metal strike
        f_strike = 4500 * pitch + rng.randint(-300, 300)
        strike = np.sin(2 * np.pi * f_strike * t) * np.exp(-t * 500) * 0.5
        
        # Metallic ring
        f_ring = 1200 * pitch + rng.randint(-50, 50)
        ring = np.sin(2 * np.pi * f_ring * t) * np.exp(-t * 60) * 0.4
        
        noise = rng.randn(n) * np.exp(-t * 250) * 0.15
        sig = np.clip(strike + ring + noise, -1, 1)
        return (sig * 32767).astype(np.int16)

    def _typewriter_space(self, v=0, dur=0.1):
        n = int(self.sample_rate * dur)
        t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 100)
        
        f_strike = 3000 + rng.randint(-200, 200)
        strike = np.sin(2 * np.pi * f_strike * t) * np.exp(-t * 350) * 0.4
        f_ring = 800 + rng.randint(-40, 40)
        ring = np.sin(2 * np.pi * f_ring * t) * np.exp(-t * 40) * 0.6
        noise = self._low_pass_noise(rng.randn(n), 5) * np.exp(-t * 150) * 0.2
        sig = np.clip(strike + ring + noise, -1, 1)
        return (sig * 32767).astype(np.int16)

    def _typewriter_enter(self, v=0, dur=0.15):
        n = int(self.sample_rate * dur)
        t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 200)
        
        # Carriage return slide
        slide = sum(
            np.sin(2 * np.pi * (600 + i*150 + rng.randint(-50, 50)) * t) * np.exp(-t * 30)
            for i in range(3)
        ) * 0.3
        # Ding
        f_ding = 2500 + rng.randint(-100, 100)
        ding = np.sin(2 * np.pi * f_ding * t) * np.exp(-t * 25) * 0.4
        noise = self._low_pass_noise(rng.randn(n), 6) * np.exp(-t * 50) * 0.15
        sig = np.clip(slide + ding + noise, -1, 1)
        return (sig * 32767).astype(np.int16)

    # ── Soft Membrane (Quiet Thud) ──

    def _membrane_click(self, v=0, dur=0.05):
        n = int(self.sample_rate * dur)
        t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v)
        pitch = 1.0 + (v - 3.5) * 0.03
        
        f_thud = 200 * pitch + rng.randint(-20, 20)
        thud = np.sin(2 * np.pi * f_thud * t) * np.exp(-t * 120) * 0.6
        noise = self._low_pass_noise(rng.randn(n), 8) * np.exp(-t * 200) * 0.2
        sig = np.clip(thud + noise, -1, 1)
        return (sig * 32767).astype(np.int16)

    def _membrane_space(self, v=0, dur=0.06):
        n = int(self.sample_rate * dur)
        t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 100)
        
        f_thud = 120 + rng.randint(-15, 15)
        thud = np.sin(2 * np.pi * f_thud * t) * np.exp(-t * 80) * 0.7
        noise = self._low_pass_noise(rng.randn(n), 10) * np.exp(-t * 100) * 0.25
        sig = np.clip(thud + noise, -1, 1)
        return (sig * 32767).astype(np.int16)

    def _membrane_enter(self, v=0, dur=0.07):
        n = int(self.sample_rate * dur)
        t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 200)
        
        f_thud = 100 + rng.randint(-10, 10)
        thud = np.sin(2 * np.pi * f_thud * t) * np.exp(-t * 70) * 0.8
        noise = self._low_pass_noise(rng.randn(n), 10) * np.exp(-t * 90) * 0.25
        sig = np.clip(thud + noise, -1, 1)
        return (sig * 32767).astype(np.int16)

    # ── Helpers ──

    def get_sound(self, char):
        if char == '\n':
            return random.choice(self.sounds['enter'])
        if char == ' ':
            return random.choice(self.sounds['space'])
        return random.choice(self.sounds['key'])

    @staticmethod
    def save_wav(path, signal, sr=44100, volume=0.5):
        # Apply volume scaling before saving
        scaled = (signal * volume).astype(np.int16)
        with wave.open(path, 'w') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
            w.writeframes(scaled.tobytes())

    def generate_audio_track(self, char_timestamps, filepath, volume=0.5):
        if not char_timestamps:
            return
        total = max(ts for ts, _ in char_timestamps) + 0.5
        n = int(self.sample_rate * total)
        audio = np.zeros(n, dtype=np.int32)  # Mix in 32-bit space to prevent clipping
        for ts, ch in char_timestamps:
            snd = self.get_sound(ch)
            s = int(ts * self.sample_rate)
            e = min(s + len(snd), n)
            if s < n:
                # Apply volume during mixing
                mixed = audio[s:e] + (snd[:e - s] * volume).astype(np.int32)
                audio[s:e] = np.clip(mixed, -32767, 32767)
        self.save_wav(filepath, audio.astype(np.int16), self.sample_rate, 1.0)  # Volume already applied


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
        self.width = width
        self.height = height
        self.theme_name = theme_name
        self.theme = THEMES[theme_name]
        self.font_family = font_family
        self.font_size = font_size
        self.show_line_numbers = show_line_numbers
        self.show_window_chrome = show_window_chrome
        self.padding = padding
        self.tab_size = tab_size
        self.title_text = title_text
        self.title_bar_h = 42 if show_window_chrome else 0
        self.ln_width = 65 if show_line_numbers else 0
        self.code_margin = 20
        self.font = QFont(font_family, font_size)
        self.font.setStyleHint(QFont.Monospace)
        self.line_h = int(font_size * 1.55)
        self._cached_text = None
        self._cached_colors = None

    def render_frame(self, full_text, num_visible, cursor_visible=True):
        img = QImage(self.width, self.height, QImage.Format_RGB32)
        img.fill(QColor(self.theme["background"]))
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        self._draw_bg(p)
        if self.show_window_chrome:
            self._draw_chrome(p)

        visible_text = full_text[:num_visible]
        vis_lines = visible_text.split('\n')

        cursor_line = visible_text.count('\n')
        last_nl = visible_text.rfind('\n')
        cursor_col = len(visible_text) - last_nl - 1 if last_nl >= 0 else len(visible_text)

        char_colors = self._build_color_map(full_text)

        chrome = self.title_bar_h if self.show_window_chrome else 0
        area_top = self.padding + chrome
        area_h = self.height - 2 * self.padding - chrome
        max_vis = max(1, area_h // self.line_h)
        scroll_margin_top = 3
        scroll_margin_bottom = 5
        first = 0
        if cursor_line < first + scroll_margin_top:
            first = max(0, cursor_line - scroll_margin_top)
        if cursor_line >= first + max_vis - scroll_margin_bottom:
            first = max(0, cursor_line - max_vis + scroll_margin_bottom + 1)

        line_offsets = []
        off = 0
        for line in vis_lines:
            line_offsets.append(off)
            off += len(line) + 1

        fm = QFontMetrics(self.font)
        tab_advance = fm.horizontalAdvance(' ') * self.tab_size

        for i in range(max_vis):
            li = first + i
            if li >= len(vis_lines):
                break
            y = area_top + i * self.line_h

            if li == cursor_line:
                p.fillRect(QRect(self.padding - 12, y,
                                 self.width - 2 * self.padding + 24, self.line_h),
                           QColor(self.theme["current_line"]))

            if self.show_line_numbers:
                ln_font = QFont(self.font_family, self.font_size - 2)
                ln_font.setStyleHint(QFont.Monospace)
                p.setFont(ln_font)
                color = QColor(self.theme["foreground"]).darker(120) if li == cursor_line else QColor(self.theme["line_number"])
                p.setPen(color)
                p.drawText(QRect(self.padding, y, self.ln_width, self.line_h),
                           Qt.AlignRight | Qt.AlignVCenter, str(li + 1))

            p.setFont(self.font)
            start_x = self.padding + self.ln_width + self.code_margin
            line = vis_lines[li]
            global_off = line_offsets[li]

            if not line:
                if cursor_visible and li == cursor_line:
                    p.fillRect(int(start_x), int(y + 5), max(2, self.font_size // 10), self.line_h - 10, QColor(self.theme["cursor"]))
                continue

            char_x = []
            x = start_x
            for ch in line:
                char_x.append(x)
                x += tab_advance if ch == '\t' else fm.horizontalAdvance(ch)

            cur_color = char_colors[global_off] if global_off < len(char_colors) else 'foreground'
            run_start = 0

            for j in range(1, len(line) + 1):
                next_color = 'foreground'
                if j < len(line):
                    gp = global_off + j
                    next_color = char_colors[gp] if gp < len(char_colors) else 'foreground'

                if j == len(line) or next_color != cur_color:
                    run_text = line[run_start:j].replace('\t', ' ' * self.tab_size)
                    p.setPen(QColor(self.theme.get(cur_color, self.theme['foreground'])))
                    p.drawText(QPoint(int(char_x[run_start]), int(y + self.line_h * 0.78)), run_text)
                    cur_color = next_color
                    run_start = j

            if cursor_visible and li == cursor_line:
                cx = start_x
                for j in range(min(cursor_col, len(line))):
                    cx += tab_advance if line[j] == '\t' else fm.horizontalAdvance(line[j])
                p.fillRect(int(cx), int(y + 5), max(2, self.font_size // 10), self.line_h - 10, QColor(self.theme["cursor"]))

        p.end()
        return img

    def _build_color_map(self, text):
        if text == self._cached_text and self._cached_colors is not None:
            return self._cached_colors
        tokens = PythonTokenizer.tokenize(text)
        colors = ['foreground'] * len(text)
        pos = 0
        for ttype, ttxt in tokens:
            ckey = self.TOKEN_COLOR_MAP.get(ttype, 'foreground')
            for i in range(len(ttxt)):
                if pos + i < len(colors):
                    colors[pos + i] = ckey
            pos += len(ttxt)
        self._cached_text = text
        self._cached_colors = colors
        return colors

    def _draw_bg(self, p):
        g = QLinearGradient(0, 0, 0, self.height)
        bg = QColor(self.theme["background"])
        g.setColorAt(0, bg.lighter(105))
        g.setColorAt(1, bg)
        p.fillRect(0, 0, self.width, self.height, g)

    def _draw_chrome(self, p):
        x, y = self.padding - 14, self.padding - 14
        w = self.width - 2 * self.padding + 28
        h = self.height - 2 * self.padding + 28

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 60))
        p.drawRoundedRect(x + 4, y + 4, w, h, 12, 12)
        p.setBrush(QColor(self.theme["window_border"]))
        p.drawRoundedRect(x, y, w, h, 12, 12)

        tb = QColor(self.theme["title_bar"])
        p.setBrush(tb)
        p.drawRoundedRect(x, y, w, self.title_bar_h + 10, 12, 12)
        p.fillRect(x, y + 18, w, self.title_bar_h - 8, tb)

        by = y + 19
        for dx, color_key in [(20, "button_close"), (44, "button_min"), (68, "button_max")]:
            p.setBrush(QColor(self.theme[color_key]))
            p.drawEllipse(x + dx, by, 14, 14)
            p.setPen(QColor(0, 0, 0, 100))
            p.setFont(QFont("Arial", 7, QFont.Bold))
            p.drawText(QRect(x + dx, by, 14, 14), Qt.AlignCenter, {"button_close": "×", "button_min": "−", "button_max": "+"}[color_key])
            p.setPen(Qt.NoPen)

        p.setPen(QColor(self.theme["title_text"]))
        p.setFont(QFont(self.font_family, 12))
        p.drawText(QRect(x, y + 10, w, self.title_bar_h), Qt.AlignCenter, self.title_text)


# ═══════════════════════════ TYPING ANIMATOR ═══════════════════════════

class TypingAnimator:
    def __init__(self, code, base_wpm=120, humanize=True):
        self.code = code
        self.base_wpm = base_wpm
        self.humanize = humanize
        cps = (base_wpm * 5) / 60
        self.base_delay = 1.0 / cps
        self.timeline = self._build_timeline()
        self._timestamps = [ts for ts, _, _ in self.timeline]

    def _build_timeline(self):
        rng = random.Random()
        t = 0.0
        events = []
        for i, ch in enumerate(self.code):
            events.append((t, i, ch))
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
                    if self.code[i:i + len(kw)] == kw:
                        d *= 1.6
                        break
            d = max(d, 0.015)
            t += d
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
                 sound_gen=None, volume=0.5, codec_profile="YouTube 1080p", crf=18, preset="medium"):
        super().__init__()
        self.code = code
        self.output = output
        self.renderer = renderer
        self.animator = animator
        self.fps = fps
        self.sound_gen = sound_gen
        self.volume = volume
        self.codec_profile = codec_profile
        self.crf = crf
        self.preset = preset
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def _check_ffmpeg(self):
        try:
            r = subprocess.run(['ffmpeg', '-version'], capture_output=True, timeout=5)
            return r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _qimg_to_frame(self, qimg):
        qimg = qimg.convertToFormat(QImage.Format_RGB888)
        ptr = qimg.constBits()
        bpl = qimg.bytesPerLine()
        ptr.setsize(qimg.height() * bpl)
        arr = np.array(ptr).reshape((qimg.height(), bpl))
        arr = arr[:, :qimg.width() * 3].reshape((qimg.height(), qimg.width(), 3))
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

    def run(self):
        try:
            tmp = tempfile.mkdtemp()
            vid_path = os.path.join(tmp, "video_only.mp4")
            aud_path = os.path.join(tmp, "audio.wav")

            total = self.animator.duration()
            n_frames = int(total * self.fps)
            blink_period = 0.53
            w, h = self.renderer.width, self.renderer.height

            # Generate audio track
            if self.sound_gen:
                self.sound_gen.generate_audio_track(
                    self.animator.char_timestamps(), aud_path, self.volume)

            # Write intermediate video with OpenCV
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            writer = cv2.VideoWriter(vid_path, fourcc, self.fps, (w, h))

            export_start = _time.time()

            for fi in range(n_frames):
                if self._cancel:
                    writer.release()
                    self.error.emit("Cancelled")
                    return

                t = fi / self.fps
                nv = self.animator.visible_at(t)
                cur_vis = True
                last_ts = 0
                for ts, idx, _ in self.animator.timeline:
                    if idx == nv - 1:
                        last_ts = ts; break
                since = t - last_ts
                if since > 0.25:
                    cur_vis = (int(since / blink_period) % 2) == 0

                qimg = self.renderer.render_frame(self.code, nv, cur_vis)
                frame = self._qimg_to_frame(qimg)
                writer.write(frame)

                pct = int((fi + 1) / n_frames * 100)
                self.progress.emit(pct)
                if fi % max(1, n_frames // 20) == 0 and fi > 0:
                    elapsed = _time.time() - export_start
                    eta = elapsed / (fi + 1) * (n_frames - fi - 1)
                    self.status.emit(f"Rendering frames... {pct}%  (ETA: {int(eta)}s)")

            writer.release()

            has_ffmpeg = self._check_ffmpeg()
            has_audio = (self.sound_gen is not None and os.path.exists(aud_path) and os.path.getsize(aud_path) > 0)

            # The Raw Fallback just renames the mp4v file. It will NOT have audio and uses an outdated codec.
            if self.codec_profile == "Raw (Uncompressed MP4V)":
                shutil.copy2(vid_path, self.output)
                self.finished.emit(self.output)
                try: shutil.rmtree(tmp, ignore_errors=True)
                except: pass
                return

            if not has_ffmpeg:
                self.error.emit("FFmpeg is required for H.264/YouTube exports but was not found.\nPlease install FFmpeg to export in this format.")
                try: shutil.rmtree(tmp, ignore_errors=True)
                except: pass
                return

            # YouTube / High Quality Exports require proper encoding
            success = False
            vcodec = 'libx264'
            vprofile = 'high' if self.codec_profile == "YouTube 1080p" else 'main'
            acodec = 'aac'
            
            # Construct base video args
            vargs = ['-c:v', vcodec, '-profile:v', vprofile, '-preset', self.preset, 
                     '-crf', str(self.crf), '-pix_fmt', 'yuv420p', '-movflags', '+faststart']

            if has_audio:
                cmd = ['ffmpeg', '-y', '-i', vid_path, '-i', aud_path] + \
                      vargs + \
                      ['-c:a', acodec, '-b:a', '192k', '-shortest', self.output]
            else:
                cmd = ['ffmpeg', '-y', '-i', vid_path] + \
                      vargs + \
                      [self.output]

            r = subprocess.run(cmd, capture_output=True, timeout=600)
            if r.returncode == 0:
                success = True
            else:
                err_msg = r.stderr.decode('utf-8', errors='ignore')[-500:]
                self.status.emit(f"FFmpeg failed. Retrying with basic settings... Error: {err_msg}")
                # Fallback to basic youtube settings if custom ones fail
                cmd = ['ffmpeg', '-y', '-i', vid_path, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', self.output]
                r = subprocess.run(cmd, capture_output=True, timeout=600)
                if r.returncode == 0:
                    success = True

            if not success:
                shutil.copy2(vid_path, self.output)

            try: shutil.rmtree(tmp, ignore_errors=True)
            except: pass

            self.finished.emit(self.output)
        except Exception as e:
            self.error.emit(str(e))


# ═══════════════════════════ MAIN WINDOW ═══════════════════════════

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Code Typing Video Generator")
        self.setMinimumSize(1350, 850)

        self.is_playing = False
        self.animator = None
        self.renderer = None
        self.sound_gen = TypingSoundGenerator(profile="Mechanical")
        self.exporter = None
        self._last_vis = 0
        self._play_t0 = 0.0
        self._play_offset = 0.0

        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(16)
        self._preview_timer.timeout.connect(self._tick)

        self._code_debounce = QTimer(self)
        self._code_debounce.setSingleShot(True)
        self._code_debounce.setInterval(400)

        self._init_sounds()
        self._build_ui()
        self._build_menu()
        self._build_shortcuts()
        self._restore_settings()
        self._static_preview()

    def _init_sounds(self, profile="Mechanical"):
        tmp = tempfile.mkdtemp()
        self._sfx_dir = tmp
        self._sfx = {}
        
        # Regenerate generator if profile changed
        self.sound_gen = TypingSoundGenerator(profile=profile)
        volume = self.snd_vol_sl.value() / 100.0 if hasattr(self, 'snd_vol_sl') else 0.5

        for kind in ('key', 'space', 'enter'):
            for i, snd in enumerate(self.sound_gen.sounds[kind][:3]):
                path = os.path.join(tmp, f"{kind}_{i}.wav")
                self.sound_gen.save_wav(path, snd, volume=volume)
                eff = QSoundEffect(self)
                eff.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
                eff.setVolume(0.8) 
                self._sfx[(kind, i)] = eff

    def _play_click(self, ch):
        kind = 'enter' if ch == '\n' else 'space' if ch == ' ' else 'key'
        key = (kind, random.randint(0, 2))
        sfx = self._sfx.get(key)
        if sfx: sfx.play()

    def _build_ui(self):
        cw = QWidget(); self.setCentralWidget(cw)
        root = QHBoxLayout(cw); root.setSpacing(8)

        # ── LEFT ──
        left = QWidget(); ll = QVBoxLayout(left); ll.setContentsMargins(4, 4, 4, 4)

        # Code Input
        eg = QGroupBox("Code Input"); el = QVBoxLayout(eg)
        self.editor = QTextEdit()
        self.editor.setFont(QFont("Consolas", 11))
        self.editor.setPlainText(self._sample_py())
        self.editor.setAcceptRichText(False)
        self.editor.setStyleSheet("QTextEdit { background: #1e1e2e; color: #cdd6f4; border: 1px solid #45475a; border-radius: 4px; }")
        el.addWidget(self.editor)
        self.editor.textChanged.connect(self._on_code_changed)

        bl = QHBoxLayout()
        for label, fn in [("Python", self._sample_py), ("JavaScript", self._sample_js), ("Load File", self._load_file)]:
            b = QPushButton(label); b.clicked.connect(fn); bl.addWidget(b)
        el.addLayout(bl)
        ll.addWidget(eg, 3)

        # ── Settings Tabs ──
        sg = QGroupBox("Settings"); sl = QVBoxLayout(sg)

        # Visuals
        vg = QGroupBox("Visuals"); vl = QFormLayout(vg)
        self.theme_cb = QComboBox(); self.theme_cb.addItems(THEMES.keys())
        self.theme_cb.currentTextChanged.connect(self._on_setting_changed)
        vl.addRow("Theme:", self.theme_cb)

        self.font_cb = QFontComboBox(); self.font_cb.setFontFilters(QFontComboBox.MonospacedFonts)
        self.font_cb.setCurrentFont(QFont("Consolas"))
        self.font_cb.currentFontChanged.connect(self._on_setting_changed)
        vl.addRow("Font:", self.font_cb)

        self.size_sp = QSpinBox(); self.size_sp.setRange(10, 48); self.size_sp.setValue(22)
        self.size_sp.valueChanged.connect(self._on_setting_changed)
        vl.addRow("Font Size:", self.size_sp)

        self.tab_sp = QSpinBox(); self.tab_sp.setRange(2, 8); self.tab_sp.setValue(4)
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

        # Animation
        ag = QGroupBox("Animation & Sound"); al = QFormLayout(ag)
        self.wpm_sp = QSpinBox(); self.wpm_sp.setRange(20, 600); self.wpm_sp.setValue(100); self.wpm_sp.setSuffix(" WPM")
        al.addRow("Speed:", self.wpm_sp)

        self.human_chk = QCheckBox("Humanize Typing"); self.human_chk.setChecked(True)
        al.addRow(self.human_chk)

        self.snd_chk = QCheckBox("Enable Sounds"); self.snd_chk.setChecked(True)
        al.addRow(self.snd_chk)

        self.snd_profile_cb = QComboBox(); self.snd_profile_cb.addItems(["Mechanical", "Typewriter", "Soft Membrane"])
        self.snd_profile_cb.currentTextChanged.connect(self._on_sound_profile_changed)
        al.addRow("Sound Profile:", self.snd_profile_cb)

        vh = QHBoxLayout()
        self.snd_vol_sl = QSlider(Qt.Horizontal); self.snd_vol_sl.setRange(0, 100); self.snd_vol_sl.setValue(50)
        self.snd_vol_lbl = QLabel("50%")
        self.snd_vol_sl.valueChanged.connect(lambda v: (self.snd_vol_lbl.setText(f"{v}%"), self._update_volume()))
        vh.addWidget(self.snd_vol_sl); vh.addWidget(self.snd_vol_lbl)
        al.addRow("Volume:", vh)
        sl.addWidget(ag)

        # Export
        eg2 = QGroupBox("Export (YouTube Ready)"); el2 = QFormLayout(eg2)
        self.res_cb = QComboBox(); self.res_cb.addItems(["1920x1080", "1280x720", "3840x2160", "1080x1920"])
        el2.addRow("Resolution:", self.res_cb)

        self.fps_sp = QSpinBox(); self.fps_sp.setRange(10, 60); self.fps_sp.setValue(30); self.fps_sp.setSuffix(" FPS")
        el2.addRow("Frame Rate:", self.fps_sp)

        self.codec_cb = QComboBox(); self.codec_cb.addItems(["YouTube 1080p", "High Quality (H.264)", "Raw (Uncompressed MP4V)"])
        self.codec_cb.setCurrentText("YouTube 1080p")
        el2.addRow("Codec:", self.codec_cb)

        self.crf_sp = QSpinBox(); self.crf_sp.setRange(0, 51); self.crf_sp.setValue(18)
        self.crf_sp.setToolTip("0=Lossless, 18=High Quality, 28=Medium, 51=Terrible")
        el2.addRow("Quality (CRF):", self.crf_sp)

        self.preset_cb = QComboBox(); self.preset_cb.addItems(["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"])
        self.preset_cb.setCurrentText("medium")
        self.preset_cb.setToolTip("Slower = Better compression for same quality")
        el2.addRow("Speed (Preset):", self.preset_cb)

        sl.addWidget(eg2)
        ll.addWidget(sg, 2)
        root.addWidget(left, 2)

        # ── RIGHT ──
        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(4, 4, 4, 4)

        pg = QGroupBox("Preview"); pl = QVBoxLayout(pg)
        self.preview = QLabel(); self.preview.setAlignment(Qt.AlignCenter); self.preview.setMinimumSize(640, 360)
        self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview.setStyleSheet("background:#111; border-radius:8px;")
        pl.addWidget(self.preview, 1)

        # Seek Bar
        self.seek_slider = QSlider(Qt.Horizontal); self.seek_slider.setRange(0, 10000); self.seek_slider.setValue(0)
        self.seek_slider.setStyleSheet("QSlider::groove:horizontal{background:#333;height:6px;border-radius:3px} QSlider::handle:horizontal{background:#4CAF50;width:14px;margin:-4px 0;border-radius:7px} QSlider::sub-page:horizontal{background:#4CAF50;border-radius:3px}")
        self.seek_slider.sliderPressed.connect(self._on_seek_pressed)
        self.seek_slider.sliderReleased.connect(self._on_seek_released)
        self.seek_slider.sliderMoved.connect(self._on_seek_moved)
        self._seeking = False
        pl.addWidget(self.seek_slider)

        # Controls
        cl = QHBoxLayout()
        self.play_btn = QPushButton("▶ Play"); self.play_btn.setFixedHeight(36)
        self.play_btn.setStyleSheet("QPushButton{background:#4CAF50;color:#fff;border:none;border-radius:5px;font-weight:bold;font-size:13px;padding:0 18px} QPushButton:hover{background:#43a047} QPushButton:disabled{background:#555}")
        self.play_btn.clicked.connect(self._toggle_play)
        cl.addWidget(self.play_btn)

        self.stop_btn = QPushButton("■ Stop"); self.stop_btn.setFixedHeight(36)
        self.stop_btn.setStyleSheet("QPushButton{background:#f44336;color:#fff;border:none;border-radius:5px;font-weight:bold;font-size:13px;padding:0 18px} QPushButton:hover{background:#d32f2f} QPushButton:disabled{background:#555}")
        self.stop_btn.clicked.connect(self._stop)
        cl.addWidget(self.stop_btn)

        self.time_lbl = QLabel("0:00 / 0:00"); self.time_lbl.setStyleSheet("color:#aaa;font-size:12px;padding:0 8px")
        cl.addWidget(self.time_lbl); cl.addStretch()

        self.export_btn = QPushButton("⬇ Export MP4"); self.export_btn.setFixedHeight(36)
        self.export_btn.setStyleSheet("QPushButton{background:#2196F3;color:#fff;border:none;border-radius:5px;font-weight:bold;font-size:13px;padding:0 22px} QPushButton:hover{background:#1976D2} QPushButton:disabled{background:#555}")
        self.export_btn.clicked.connect(self._export)
        cl.addWidget(self.export_btn)
        pl.addLayout(cl)

        self.progress = QProgressBar(); self.progress.setVisible(False)
        pl.addWidget(self.progress)
        rl.addWidget(pg)
        root.addWidget(right, 3)

        self.statusBar().showMessage("Ready — paste code and click Play  |  Shortcuts: Space=Play  Esc=Stop  Ctrl+E=Export  Ctrl+O=Open")

    def _build_menu(self):
        mb = self.menuBar(); fm = mb.addMenu("File")
        a = QAction("Load Code...", self); a.triggered.connect(self._load_file); fm.addAction(a)
        fm.addSeparator()
        a = QAction("Exit", self); a.triggered.connect(self.close); fm.addAction(a)

    def _build_shortcuts(self):
        QShortcut(QKeySequence(Qt.Key_Space), self, self._toggle_play)
        QShortcut(QKeySequence(Qt.Key_Escape), self, self._stop)
        QShortcut(QKeySequence("Ctrl+E"), self, self._export)
        QShortcut(QKeySequence("Ctrl+O"), self, self._load_file)

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
        self.snd_profile_cb.setCurrentText(s.value("snd_profile", "Mechanical", type=str))
        self.snd_vol_sl.setValue(s.value("snd_volume", 50, type=int))
        self.title_edit.setText(s.value("title_text", "main.py — Code Editor", type=str))
        self.codec_cb.setCurrentText(s.value("codec", "YouTube 1080p", type=str))
        self.crf_sp.setValue(s.value("crf", 18, type=int))
        self.preset_cb.setCurrentText(s.value("preset", "medium", type=str))
        geo = s.value("geometry")
        if geo: self.restoreGeometry(geo)

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

    def _make_renderer(self, preview=False):
        res = self.res_cb.currentText().replace('\u00d7', 'x').replace('×', 'x')
        w, h = map(int, res.split('x'))
        if preview:
            scale = min(960 / w, 540 / h, 1.0)
            w, h = int(w * scale), int(h * scale)
            pad = max(20, int(30 * scale)); fs = max(8, int(self.size_sp.value() * scale))
        else:
            pad = 50; fs = self.size_sp.value()
        return CodeRenderer(width=w, height=h, theme_name=self.theme_cb.currentText(), font_family=self.font_cb.currentFont().family(),
                            font_size=fs, show_line_numbers=self.ln_chk.isChecked(), show_window_chrome=self.chrome_chk.isChecked(),
                            padding=pad, tab_size=self.tab_sp.value(), title_text=self.title_edit.text())

    def _make_animator(self):
        code = self.editor.toPlainText().replace('\r\n', '\n').replace('\r', '\n')
        return TypingAnimator(code, base_wpm=self.wpm_sp.value(), humanize=self.human_chk.isChecked())

    def _on_code_changed(self):
        if self.is_playing: self._stop()
        self.animator = None
        self._code_debounce.start()

    def _on_setting_changed(self, *_):
        if self.is_playing: self._stop()
        self.animator = None
        self._static_preview()

    def _on_sound_profile_changed(self, profile):
        self._init_sounds(profile=profile)
        self._static_preview()

    def _update_volume(self):
        # Re-save sounds with new volume so live preview matches
        self._init_sounds(profile=self.snd_profile_cb.currentText())

    def _static_preview(self, *_):
        if self.is_playing: return
        try:
            r = self._make_renderer(preview=True)
            code = self.editor.toPlainText()
            if not code.strip():
                self.preview.setText("<span style='color:#666;font-size:14px'>Paste some code to preview</span>")
                return
            img = r.render_frame(code, len(code), False)
            pm = QPixmap.fromImage(img)
            self.preview.setPixmap(pm.scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception as e:
            self.preview.setText(f"Preview error: {e}")

    def _toggle_play(self):
        if self.is_playing:
            self.is_playing = False; self._preview_timer.stop()
            self._play_offset += _time.time() - self._play_t0
            self.play_btn.setText("▶ Play"); return

        self.is_playing = True
        if not self.animator:
            self.animator = self._make_animator(); self.renderer = self._make_renderer(preview=True)
            self._play_offset = 0.0; self._last_vis = 0
            self.seek_slider.setRange(0, max(1, int(self.animator.duration() * 1000)))
        self._play_t0 = _time.time(); self._preview_timer.start()
        self.play_btn.setText("⏸ Pause"); self.statusBar().showMessage("Playing...")

    def _stop(self):
        self.is_playing = False; self._preview_timer.stop()
        self.animator = None; self.renderer = None
        self._play_offset = 0.0; self._last_vis = 0
        self.play_btn.setText("▶ Play"); self.seek_slider.setValue(0)
        self._static_preview(); self.statusBar().showMessage("Stopped")

    def _on_seek_pressed(self): self._seeking = True
    def _on_seek_released(self): self._seeking = False

    def _on_seek_moved(self, value):
        if not self.animator: return
        t = value / 1000.0; self._play_offset = t; self._play_t0 = _time.time()
        self._last_vis = self.animator.visible_at(t)
        dur = self.animator.duration(); cur_vis = True
        if t < dur:
            nv = self.animator.visible_at(t); last_ts = 0
            for ts, idx, _ in self.animator.timeline:
                if idx == nv - 1: last_ts = ts; break
            since = t - last_ts
            if since > 0.2: cur_vis = (int(since / 0.53) % 2) == 0
            img = self.renderer.render_frame(self.animator.code, nv, cur_vis)
            self.preview.setPixmap(QPixmap.fromImage(img).scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.time_lbl.setText(f"{int(t)//60}:{int(t)%60:02d} / {int(dur)//60}:{int(dur)%60:02d}")

    def _tick(self):
        if not self.animator or not self.renderer: return
        t = self._play_offset + (_time.time() - self._play_t0)
        dur = self.animator.duration()
        if t >= dur: self._stop(); self.statusBar().showMessage("Playback complete"); return

        nv = self.animator.visible_at(t)
        if self.snd_chk.isChecked() and nv > self._last_vis:
            for i in range(max(self._last_vis, nv - 3), nv):
                if i < len(self.animator.code): self._play_click(self.animator.code[i])
        self._last_vis = nv

        last_ts = 0
        for ts, idx, _ in self.animator.timeline:
            if idx == nv - 1: last_ts = ts; break
        cur_vis = True; since = t - last_ts
        if since > 0.2: cur_vis = (int(since / 0.53) % 2) == 0

        img = self.renderer.render_frame(self.animator.code, nv, cur_vis)
        self.preview.setPixmap(QPixmap.fromImage(img).scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

        if not self._seeking:
            self.seek_slider.blockSignals(True); self.seek_slider.setValue(int(t * 1000)); self.seek_slider.blockSignals(False)
        self.time_lbl.setText(f"{int(t)//60}:{int(t)%60:02d} / {int(dur)//60}:{int(dur)%60:02d}")

    def _export(self):
        code = self.editor.toPlainText()
        if not code.strip():
            QMessageBox.warning(self, "Empty", "Enter some code first!"); return

        codec_profile = self.codec_cb.currentText()
        has_ffmpeg = False
        try: has_ffmpeg = subprocess.run(['ffmpeg', '-version'], capture_output=True, timeout=5).returncode == 0
        except: pass

        if codec_profile != "Raw (Uncompressed MP4V)" and not has_ffmpeg:
            QMessageBox.critical(self, "FFmpeg Required",
                                 "FFmpeg is required to export H.264/YouTube videos.\n\n"
                                 "1. Download FFmpeg from https://ffmpeg.org\n"
                                 "2. Add it to your system PATH.\n\n"
                                 "Alternatively, select 'Raw (Uncompressed MP4V)' but note that it will not have audio and is not optimized for YouTube.")
            return

        path, _ = QFileDialog.getSaveFileName(self, "Export Video", "code_typing.mp4", "MP4 (*.mp4)")
        if not path: return

        renderer = self._make_renderer(preview=False)
        animator = self._make_animator()
        snd = self.sound_gen if (has_ffmpeg and self.snd_chk.isChecked()) else None
        vol = self.snd_vol_sl.value() / 100.0

        self.exporter = VideoExporter(code, path, renderer, animator, self.fps_sp.value(), snd, vol,
                                      codec_profile=codec_profile, crf=self.crf_sp.value(), preset=self.preset_cb.currentText())
        self.exporter.progress.connect(self._on_prog)
        self.exporter.status.connect(self._on_export_status)
        self.exporter.finished.connect(self._on_done)
        self.exporter.error.connect(self._on_err)

        self._set_controls_enabled(False)
        self.progress.setVisible(True); self.progress.setValue(0)
        self.statusBar().showMessage("Exporting...")
        self.exporter.start()

    def _set_controls_enabled(self, enabled):
        self.export_btn.setEnabled(enabled); self.play_btn.setEnabled(enabled)
        self.stop_btn.setEnabled(enabled); self.editor.setReadOnly(not enabled)

    def _on_prog(self, pct): self.progress.setValue(pct)
    def _on_export_status(self, msg): self.statusBar().showMessage(msg)

    def _on_done(self, p):
        self.progress.setVisible(False); self._set_controls_enabled(True)
        self.statusBar().showMessage(f"Exported → {p}")
        QMessageBox.information(self, "Done", f"Video saved!\n\n{p}")

    def _on_err(self, msg):
        self.progress.setVisible(False); self._set_controls_enabled(True)
        self.statusBar().showMessage(f"Error: {msg}")
        QMessageBox.critical(self, "Export Error", msg)

    def _load_file(self):
        p, _ = QFileDialog.getOpenFileName(self, "Load Code", "", "Code (*.py *.js *.ts *.java *.cpp *.c *.go *.rs *.rb *.html *.css);;All (*)")
        if p:
            try: self.editor.setPlainText(open(p, encoding='utf-8').read()); self.statusBar().showMessage(f"Loaded {p}"); self._static_preview()
            except Exception as e: QMessageBox.warning(self, "Error", str(e))

    @staticmethod
    def _sample_py():
        return '''import numpy as np
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class Particle:
    """A particle in the simulation."""
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    mass: float = 1.0
    color: str = "#ffffff"

class ParticleSimulation:
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.particles: List[Particle] = []
        self.gravity = 9.81
        self.dt = 0.016

    def add_particle(self, x, y, **kwargs):
        p = Particle(x=x, y=y, **kwargs)
        self.particles.append(p)
        return p

    def update(self):
        for p in self.particles:
            p.vy += self.gravity * self.dt
            p.x += p.vx * self.dt
            p.y += p.vy * self.dt

            if p.y > self.height - 10:
                p.y = self.height - 10
                p.vy *= -0.8

            if p.x < 10 or p.x > self.width - 10:
                p.vx *= -0.9

    def total_energy(self) -> float:
        return sum(
            0.5 * p.mass * (p.vx**2 + p.vy**2)
            for p in self.particles
        )

def main():
    sim = ParticleSimulation(800, 600)
    for _ in range(50):
        sim.add_particle(
            x=np.random.uniform(50, 750),
            y=np.random.uniform(50, 300),
            vx=np.random.uniform(-100, 100),
            vy=np.random.uniform(-50, 50),
        )
    print(f"Particles: {len(sim.particles)}")
    for step in range(1000):
        sim.update()
        if step % 100 == 0:
            print(f"Step {step}: E={sim.total_energy():.1f}")

if __name__ == "__main__":
    main()'''

    @staticmethod
    def _sample_js():
        return '''class EventEmitter {
  constructor() {
    this.listeners = new Map();
  }

  on(event, callback) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, []);
    }
    this.listeners.get(event).push(callback);
    return this;
  }

  off(event, callback) {
    const cbs = this.listeners.get(event);
    if (cbs) {
      const i = cbs.indexOf(callback);
      if (i > -1) cbs.splice(i, 1);
    }
    return this;
  }

  emit(event, ...args) {
    const cbs = this.listeners.get(event);
    if (cbs) cbs.forEach(cb => cb(...args));
    return this;
  }
}

function createStore(initialState) {
  const emitter = new EventEmitter();
  let state = { ...initialState };

  return {
    getState: () => ({ ...state }),
    setState: (updates) => {
      const prev = { ...state };
      state = { ...state, ...updates };
      emitter.emit("change", state, prev);
    },
    subscribe: (cb) => {
      emitter.on("change", cb);
      return () => emitter.off("change", cb);
    }
  };
}

const store = createStore({ count: 0, name: "World" });
store.subscribe((s) => console.log("State:", s));
store.setState({ count: 1 });
store.setState({ name: "JavaScript" });'''

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not self.is_playing: QTimer.singleShot(100, self._static_preview)

    def closeEvent(self, e):
        self._save_settings()
        if self.exporter and self.exporter.isRunning(): self.exporter.cancel(); self.exporter.wait(3000)
        e.accept()


# ═══════════════════════════ ENTRY POINT ═══════════════════════════

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(30, 30, 30)); pal.setColor(QPalette.WindowText, QColor(200, 200, 200))
    pal.setColor(QPalette.Base, QColor(25, 25, 25)); pal.setColor(QPalette.AlternateBase, QColor(35, 35, 35))
    pal.setColor(QPalette.ToolTipBase, QColor(25, 25, 25)); pal.setColor(QPalette.ToolTipText, QColor(200, 200, 200))
    pal.setColor(QPalette.Text, QColor(200, 200, 200)); pal.setColor(QPalette.Button, QColor(45, 45, 45))
    pal.setColor(QPalette.ButtonText, QColor(200, 200, 200)); pal.setColor(QPalette.Link, QColor(42, 130, 218))
    pal.setColor(QPalette.Highlight, QColor(42, 130, 218)); pal.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    app.setPalette(pal)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()