"""
Code Typing Video Generator (single-file edition)

Creates MP4 / WebM / GIF videos of code being typed with realistic
animation, syntax highlighting, optional keyboard overlay, and
procedurally generated typing sounds.

Requirements: Python 3.9+, PySide6, numpy, FFmpeg (on PATH).
Version: 1.7.0
"""
from __future__ import annotations
import bisect, json, logging, math, os, random, re, shutil, struct, subprocess, sys, tempfile, threading, time as _time, types, wave
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Type, Union, NamedTuple
import numpy as np
from PySide6.QtCore import QEvent, QPoint, QRect, QSettings, QThread, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QAction, QColor, QFont, QFontDatabase, QFontMetrics, QImage, QKeySequence,
    QLinearGradient, QPainter, QPalette, QPixmap, QShortcut)
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
    QDoubleSpinBox, QFileDialog, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton, QSizePolicy, QSlider,
    QSpinBox, QSplitter, QStatusBar, QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget)

__version__ = "1.7.0"

# ======================================================================
# config.py
# ======================================================================

"""
Configuration constants for the Code Typing Video Generator.

Centralises paths, supported file extensions, resolution presets,
keyboard layout, color themes, and logging setup so other modules
can stay focused on behaviour rather than magic values.
"""

def configure_logging(level=logging.INFO):
    """Configure root logging. Safe to call multiple times — updates level if root handlers already exist."""
    root = logging.getLogger()
    if root.handlers:
        root.setLevel(level)
        for h in root.handlers:
            h.setLevel(level); return
    logging.basicConfig( level=level, format="%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)-25s | %(message)s", datefmt="%H:%M:%S",
    )

CWD: str = os.getcwd()
INPUT_DIR: str = os.path.join(CWD, "input")
OUTPUT_DIR: str = os.path.join(CWD, "output")
TMP_DIR: str = os.path.join(CWD, "tmp")

def ensure_cwd_dirs():
    """Make sure input/, output/, tmp/ exist next to the executable."""
    for d in (INPUT_DIR, OUTPUT_DIR, TMP_DIR):
        os.makedirs(d, exist_ok=True)

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h",
    ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt",
    ".scala", ".r", ".m", ".sh", ".bash", ".zsh", ".fish", ".ps1",
    ".sql", ".html", ".css", ".scss", ".less", ".json", ".yaml",
    ".yml", ".toml", ".ini", ".cfg", ".conf", ".txt", ".md", ".rst",
    ".lua", ".vim", ".el", ".clj", ".ex", ".exs", ".erl", ".hs",
    ".ml", ".fs", ".dart", ".groovy", ".v", ".sv", ".vhd", ".tcl",
})

EXT_TO_LANGUAGE: dict[str, str] = {
    ".py":  "Python",
    ".js":  "JavaScript",
    ".jsx": "JavaScript",
    ".ts":  "TypeScript",
    ".tsx": "TypeScript",
    ".java": "C/C++/Java",
    ".c":   "C/C++/Java",
    ".cpp": "C/C++/Java",
    ".h":   "C/C++/Java",
    ".hpp": "C/C++/Java",
    ".cs":  "C/C++/Java",
    ".go":  "Go",
    ".rs":  "Rust",
}

RESOLUTION_PRESETS: Dict[str, Tuple[int, int]] = {
    "YouTube 1080p": (1920, 1080),
    "YouTube 4K": (3840, 2160),
    "YouTube 720p": (1280, 720),
    "YouTube Short (9:16)": (1080, 1920),
    "TikTok / Reels": (1080, 1920),
    "Instagram Square": (1080, 1080),
    "Twitter / X": (1280, 720),
}

YOUTUBE_SDR_BITRATES: Dict[str, Dict[str, int]] = {
    "720p":  {"30fps": 5_000_000,  "60fps": 7_500_000,  "level": 31},  # 3.1
    "1080p": {"30fps": 8_000_000,  "60fps": 12_000_000, "level": 40},  # 4.0
    "1440p": {"30fps": 16_000_000, "60fps": 24_000_000, "level": 50},  # 5.0
    "2160p": {"30fps": 40_000_000, "60fps": 60_000_000, "level": 51},  # 5.1 (4K)
}

YOUTUBE_SHORT_MAX_DURATION: float = 60.0  # seconds

YOUTUBE_SHORT_ASPECT_RATIO: float = 9.0 / 16.0  # ≈ 0.5625

def is_short_resolution(width: int, height):
    """Return True if the given resolution is vertical (9:16-ish)."""
    if width <= 0 or height <= 0:
        return False
    ratio = width / height
    return ratio <= 0.65  # 9:16 = 0.5625, allow up to ~2:3

def youtube_bitrate_for(
    width: int, height: int, fps: int
) -> Tuple[int, int]:
    """Return (video_bitrate_bps, h264_level_x10) for a YouTube SDR upload.

    Picks the standard resolution bucket (720p / 1080p / 1440p / 2160p)
    based on the **shorter** dimension of the frame, then selects the
    30- or 60-fps bitrate. Using the shorter dimension means a vertical
    1080×1920 Short is correctly bucketed as "1080p" (not "1440p").
    Falls back to 1080p@30fps for unknown sizes.
    """
    short_side = min(width, height)
    if short_side >= 2160:
        bucket = "2160p"
    elif short_side >= 1440:
        bucket = "1440p"
    elif short_side >= 1080:
        bucket = "1080p"
    else:
        bucket = "720p"

    entry = YOUTUBE_SDR_BITRATES.get(bucket, YOUTUBE_SDR_BITRATES["1080p"])
    bitrate = entry["60fps"] if fps >= 50 else entry["30fps"]
    level = entry["level"]
    return bitrate, level

GPU_VRAM_TIERS: list[dict] = [
    {   # Tier 0 — GTX 1080 / 1060 / similar 4-8 GB cards "name": "GTX 1080-class (4-8 GB)", "min_vram_mb": 4096, "nvenc_preset": "p4", "nvenc_rc": "vbr", "nvenc_surfaces": 8, "nvenc_lookahead": False, "nvenc_aq": "spatial", "nvenc_multipass": "disabled", "frame_chunk": 4, "max_res_width": 1920, "max_res_height": 1080,
    },
    {   # Tier 0.5 — RTX 2060 Super / 2070 / 3060 Ti (8 GB, Turing+) "name": "RTX 2070-class 8 GB (Turing+)", "min_vram_mb": 8192, "nvenc_preset": "p5", "nvenc_rc": "vbr", "nvenc_surfaces": 12, "nvenc_lookahead": False, "nvenc_aq": "spatial", "nvenc_multipass": "quarter_res", "frame_chunk": 6, "max_res_width": 2560, "max_res_height": 1440,
    },
    {   # Tier 1 — RTX 3070 / 4060 Ti / similar 10-12 GB cards "name": "RTX 3070-class (10-12 GB)", "min_vram_mb": 10240, "nvenc_preset": "p6", "nvenc_rc": "vbr", "nvenc_surfaces": 16, "nvenc_lookahead": False, "nvenc_aq": "spatial", "nvenc_multipass": "quarter_res", "frame_chunk": 8, "max_res_width": 2560, "max_res_height": 1440,
    },
    {   # Tier 2 — RTX 3080 / 4070 / similar 12-16 GB cards "name": "RTX 3080-class (12-16 GB)", "min_vram_mb": 12288, "nvenc_preset": "p6", "nvenc_rc": "vbr", "nvenc_surfaces": 24, "nvenc_lookahead": True, "nvenc_aq": "spatial", "nvenc_multipass": "full_res", "frame_chunk": 8, "max_res_width": 3840, "max_res_height": 2160,
    },
    {   # Tier 3 — RTX 4090 / 3090 / similar 20+ GB cards "name": "RTX 4090-class (20+ GB)", "min_vram_mb": 20480, "nvenc_preset": "p7", "nvenc_rc": "vbr", "nvenc_surfaces": 32, "nvenc_lookahead": True, "nvenc_aq": "spatial", "nvenc_multipass": "full_res", "frame_chunk": 12, "max_res_width": 3840, "max_res_height": 2160,
    },
]

GPU_VRAM_SAFETY_MARGIN: float = 0.75

GPU_VRAM_POLL_INTERVAL: int = 60

GPU_VRAM_LOW_WATERMARK: float = 0.15

def gpu_tier_for_vram(total_vram_mb):
    """Return the highest GPU_VRAM_TIERS entry that fits the given VRAM."""
    for tier in reversed(GPU_VRAM_TIERS):
        if total_vram_mb >= tier["min_vram_mb"]:
            return tier
    return GPU_VRAM_TIERS[0]

KEYBOARD_LAYOUTS: Dict[str, list[list[str]]] = {
    "QWERTY (US)": [ list("`1234567890-="), list("qwertyuiop[]\\"), list("asdfghjkl;'"), list("zxcvbnm,./"), [" "],
    ],
    "QWERTZ (German)": [ list("^1234567890ß´"), list("qwertzuiopü+"), list("asdfghjklöä"), list("yxcvbnm,./"), [" "],
    ],
    "AZERTY (French)": [ list("²&é\"'(-è_çà"), list("azertyuiop^$"), list("qsdfghjklmù*"), list("wxcvbn,;:!?"), [" "],
    ],
    "QWERTY (UK)": [ list("`1234567890-="), list("qwertyuiop[]"), list("asdfghjkl;'#"), list("\\zxcvbnm,./"), [" "],
    ],
    "Dvorak (US)": [ list("`1234567890[]"), list("',.pyfgcrl/="), list("aoeuidhtns-"), list(";qjkxbmwvz"), [" "],
    ],
    "Colemak": [ list("`1234567890-="), list("qwfpgjluy;[]\\"), list("arstdhneio'"), list("zxcvbk,./"), [" "],
    ],
    "JIS (Japanese)": [ list("1234567890-^\\"), list("qwertyuiop@["), list("asdfghjkl;:]"), list("zxcvbnm,./\\"), [" "],
    ],
}

KEYBOARD_ROWS: list[list[str]] = KEYBOARD_LAYOUTS["QWERTY (US)"]

KEY_WIDTH: int = 40
KEY_HEIGHT: int = 40
KEY_MARGIN: int = 4

KB_POSITIONS: Tuple[str, ...] = (
    "Below Code",      # Keyboard sits below the code area (default for 16:9)
    "Overlay Bottom",  # Semi-transparent keyboard overlaid on bottom of code
    "Right Panel",     # Keyboard in a side panel (good for 9:16 vertical)
)

KB_DEFAULTS: Dict[str, Dict[str, object]] = {
    "YouTube 1080p":         {"position": "Below Code",    "scale": 100, "gap": 20},
    "YouTube 4K":            {"position": "Below Code",    "scale": 100, "gap": 40},
    "YouTube 720p":          {"position": "Below Code",    "scale": 100, "gap": 15},
    "YouTube Short (9:16)":  {"position": "Right Panel",   "scale": 70,  "gap": 10},
    "TikTok / Reels":        {"position": "Right Panel",   "scale": 70,  "gap": 10},
    "Instagram Square":      {"position": "Overlay Bottom","scale": 80,  "gap": 10},
    "Twitter / X":           {"position": "Below Code",    "scale": 100, "gap": 15},
}

THEMES: Dict[str, Dict[str, str]] = {
    "Dracula": { "background": "#282a36", "foreground": "#f8f8f2", "comment": "#6272a4", "keyword": "#ff79c6", "string": "#f1fa8c", "number": "#bd93f9", "function": "#50fa7b", "builtin": "#8be9fd", "decorator": "#50fa7b", "operator": "#ff79c6", "class_name": "#8be9fd", "line_number": "#6272a4", "current_line": "#44475a", "cursor": "#f8f8f2", "title_bar": "#21222c", "title_text": "#8be9fd", "window_border": "#191a21", "button_close": "#ff5555", "button_min": "#f1fa8c", "button_max": "#50fa7b",
    },
    "One Dark": { "background": "#282c34", "foreground": "#abb2bf", "comment": "#5c6370", "keyword": "#c678dd", "string": "#98c379", "number": "#d19a66", "function": "#61afef", "builtin": "#e5c07b", "decorator": "#56b6c2", "operator": "#c678dd", "class_name": "#e5c07b", "line_number": "#4b5263", "current_line": "#2c313c", "cursor": "#528bff", "title_bar": "#21252b", "title_text": "#61afef", "window_border": "#181a1f", "button_close": "#e06c75", "button_min": "#e5c07b", "button_max": "#98c379",
    },
    "Monokai": { "background": "#272822", "foreground": "#f8f8f2", "comment": "#75715e", "keyword": "#f92672", "string": "#e6db74", "number": "#ae81ff", "function": "#a6e22e", "builtin": "#66d9ef", "decorator": "#a6e22e", "operator": "#f92672", "class_name": "#66d9ef", "line_number": "#75715e", "current_line": "#3e3d32", "cursor": "#f8f8f2", "title_bar": "#1e1f1c", "title_text": "#a6e22e", "window_border": "#1e1f1c", "button_close": "#f92672", "button_min": "#e6db74", "button_max": "#a6e22e",
    },
    "Nord": { "background": "#2e3440", "foreground": "#d8dee9", "comment": "#616e88", "keyword": "#81a1c1", "string": "#a3be8c", "number": "#b48ead", "function": "#88c0d0", "builtin": "#5e81ac", "decorator": "#8fbcbb", "operator": "#81a1c1", "class_name": "#8fbcbb", "line_number": "#4c566a", "current_line": "#3b4252", "cursor": "#d8dee9", "title_bar": "#242933", "title_text": "#88c0d0", "window_border": "#242933", "button_close": "#bf616a", "button_min": "#ebcb8b", "button_max": "#a3be8c",
    },
    "GitHub Dark": { "background": "#0d1117", "foreground": "#c9d1d9", "comment": "#8b949e", "keyword": "#ff7b72", "string": "#a5d6ff", "number": "#79c0ff", "function": "#d2a8ff", "builtin": "#ffa657", "decorator": "#d2a8ff", "operator": "#ff7b72", "class_name": "#ffa657", "line_number": "#484f58", "current_line": "#161b22", "cursor": "#c9d1d9", "title_bar": "#010409", "title_text": "#58a6ff", "window_border": "#010409", "button_close": "#f85149", "button_min": "#d29922", "button_max": "#3fb950",
    },
    "Solarized Dark": { "background": "#002b36", "foreground": "#839496", "comment": "#586e75", "keyword": "#859900", "string": "#2aa198", "number": "#d33682", "function": "#268bd2", "builtin": "#b58900", "decorator": "#cb4b16", "operator": "#859900", "class_name": "#b58900", "line_number": "#586e75", "current_line": "#073642", "cursor": "#839496", "title_bar": "#002b36", "title_text": "#268bd2", "window_border": "#001e26", "button_close": "#dc322f", "button_min": "#b58900", "button_max": "#859900",
    },
    "Catppuccin Mocha": { "background": "#1e1e2e", "foreground": "#cdd6f4", "comment": "#6c7086", "keyword": "#cba6f7", "string": "#a6e3a1", "number": "#fab387", "function": "#89b4fa", "builtin": "#f9e2af", "decorator": "#f5c2e7", "operator": "#89dceb", "class_name": "#f9e2af", "line_number": "#6c7086", "current_line": "#313244", "cursor": "#f5e0dc", "title_bar": "#181825", "title_text": "#89b4fa", "window_border": "#11111b", "button_close": "#f38ba8", "button_min": "#f9e2af", "button_max": "#a6e3a1",
    },
    "Light (Solarized)": { "background": "#fdf6e3", "foreground": "#657b83", "comment": "#93a1a1", "keyword": "#859900", "string": "#2aa198", "number": "#d33682", "function": "#268bd2", "builtin": "#b58900", "decorator": "#cb4b16", "operator": "#859900", "class_name": "#b58900", "line_number": "#93a1a1", "current_line": "#eee8d5", "cursor": "#657b83", "title_bar": "#eee8d5", "title_text": "#268bd2", "window_border": "#eee8d5", "button_close": "#dc322f", "button_min": "#b58900", "button_max": "#859900",
    },
}

SETTINGS_ORG = "Z.ai"
SETTINGS_APP = "CodeTypingVideoGenerator"

PRESET_DIR: str = os.path.join(CWD, "presets")

def ensure_preset_dir():
    """Make sure the presets/ directory exists."""
    os.makedirs(PRESET_DIR, exist_ok=True)

UI_PALETTE = {
    "bg_app":        "#1e1f22",  # main window background
    "bg_panel":      "#2b2d31",  # sidebar / groupbox background
    "bg_input":      "#1e1f22",  # line edit / combo background
    "bg_hover":      "#35373c",  # hover state
    "bg_pressed":    "#404249",  # pressed state
    "border":        "#3f4147",  # default border
    "border_focus":  "#5865f2",  # focus border (accent)
    "text":          "#e6e7e9",  # primary text
    "text_dim":      "#9aa0a6",  # secondary text
    "accent":        "#5865f2",  # primary accent (slate blue)
    "accent_hover":  "#4752c4",  # accent hover
    "accent_pressed":"#3c45a5",  # accent pressed
    "success":       "#23a55a",  # green (export success)
    "danger":        "#f23f43",  # red (cancel / error)
    "warning":       "#f0b232",  # amber (warnings)
    "shadow":        "rgba(0,0,0,80)",
}

UI_SPACING = {
    "xs": 4,
    "sm": 6,
    "md": 8,
    "lg": 12,
    "xl": 16,
    "xxl": 24,
    "radius": 6,
    "radius_lg": 10,
    "radius_sm": 4,
    "control_h": 30,   # standard button / combo height
    "control_h_lg": 38, # primary action button height
    "play_btn": 42,    # play/pause button height
    "panel_header": 36, # panel header bar height
}

UI_FONT_STACK = "Inter, 'Segoe UI', 'SF Pro Text', Roboto, 'Helvetica Neue', Arial, 'Liberation Sans', 'DejaVu Sans', sans-serif"
UI_MONO_STACK = ("'JetBrains Mono', 'Cascadia Code', 'Fira Code', 'Source Code Pro', "
                 "'IBM Plex Mono', Inconsolata, Hack, 'Space Mono', mononoki, "
                 "Consolas, 'SF Mono', Menlo, 'Liberation Mono', 'DejaVu Sans Mono', monospace")

ICON_PLAY = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="none">'
    '<path d="M4 2.5v11l9.5-5.5z" fill="currentColor"/></svg>'
)
ICON_PAUSE = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="none">'
    '<path d="M3 2h3v12H3zM10 2h3v12h-3z" fill="currentColor"/></svg>'
)
ICON_EXPORT = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="none">'
    '<path d="M8 1v8m0 0L5 6m3 3l3-3M2 11v2a1 1 0 001 1h10a1 1 0 001-1v-2" '
    'stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>'
)
ICON_SNAPSHOT = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="none">'
    '<rect x="2" y="3" width="12" height="10" rx="1.5" stroke="currentColor" stroke-width="1.3" fill="none"/>'
    '<circle cx="8" cy="8" r="2.5" stroke="currentColor" stroke-width="1.3" fill="none"/>'
    '<circle cx="12" cy="5" r="0.8" fill="currentColor"/></svg>'
)
ICON_CANCEL = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="none">'
    '<circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.3" fill="none"/>'
    '<path d="M6 6l4 4m0-4l-4 4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>'
)
ICON_CODE = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 16 16" fill="none">'
    '<path d="M5.5 3L1 8l4.5 5M10.5 3L15 8l-4.5 5" stroke="currentColor" '
    'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>'
)
ICON_SETTINGS = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 16 16" fill="none">'
    '<circle cx="8" cy="8" r="2" stroke="currentColor" stroke-width="1.3" fill="none"/>'
    '<path d="M8 1v2m0 10v2M1 8h2m10 0h2m-1.5-5.5l-1.4 1.4M4.9 11.1l-1.4 1.4m0-9.8l1.4 1.4m6.2 6.2l1.4 1.4" '
    'stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>'
)
ICON_PREVIEW = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 16 16" fill="none">'
    '<rect x="1" y="2" width="14" height="10" rx="1.5" stroke="currentColor" stroke-width="1.3" fill="none"/>'
    '<path d="M5 13h6m-3 0v1" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>'
)

def app_stylesheet():
    """Return the global QSS stylesheet for the application."""
    p = UI_PALETTE
    s = UI_SPACING
    return f"""
    /* ── Global ─────────────────────────────────────────────────── */
    QWidget {{ background-color: {p['bg_app']}; color: {p['text']}; font-family: {UI_FONT_STACK}; font-size: 13px;
    }}
    QToolTip {{ background-color: {p['bg_panel']}; color: {p['text']}; border: 1px solid {p['border']}; border-radius: {s['radius']}px; padding: {s['sm']}px {s['md']}px;
    }}

    /* ── Main window ────────────────────────────────────────────── */
    QMainWindow {{ background-color: {p['bg_app']};
    }}

    /* ── Group boxes ────────────────────────────────────────────── */
    QGroupBox {{ background-color: {p['bg_panel']}; border: 1px solid {p['border']}; border-radius: {s['radius_lg']}px; margin-top: {s['xl']}px; padding: {s['lg']}px {s['md']}px {s['md']}px {s['md']}px; font-weight: 600;
    }}
    QGroupBox::title {{ subcontrol-origin: margin;; subcontrol-position: top left; left: {s['md']}px; padding: 0 {s['sm']}px; background-color: {p['bg_panel']}; color: {p['text_dim']}; font-size: 11px;; font-weight: 600;; letter-spacing: 0.5px;; text-transform: uppercase;
    }}

    /* ── Buttons ────────────────────────────────────────────────── */
    QPushButton {{ background-color: {p['bg_hover']}; color: {p['text']}; border: 1px solid {p['border']}; border-radius: {s['radius']}px; padding: {s['sm']}px {s['lg']}px; min-height: {s['control_h']}px; font-weight: 500;
    }}
    QPushButton:hover {{ background-color: {p['bg_pressed']}; border-color: {p['text_dim']};
    }}
    QPushButton:pressed {{ background-color: {p['border']};
    }}
    QPushButton:disabled {{ background-color: {p['bg_app']}; color: {p['border']}; border-color: {p['border']};
    }}

    /* ── Primary action buttons (accent, gradient feel) ─────────── */
    QPushButton#primaryBtn {{ background-color: qlineargradient( x1:0, y1:0, x2:0, y2:1, stop:0 {p['accent']}, stop:1 {p['accent_hover']} );; color: #ffffff;; border: none; min-height: {s['control_h_lg']}px; font-weight: 600; padding-left: {s['xl']}px; padding-right: {s['xl']}px;
    }}
    QPushButton#primaryBtn:hover {{ background-color: {p['accent_hover']}; border: 1px solid rgba(255,255,255,30);
    }}
    QPushButton#primaryBtn:pressed {{ background-color: {p['accent_pressed']};
    }}
    QPushButton#primaryBtn:disabled {{ background-color: {p['border']}; color: {p['text_dim']};
    }}

    /* ── Play / Pause button (accent ring, larger) ──────────────── */
    QPushButton#playBtn {{ background-color: {p['bg_panel']}; color: {p['accent']}; border: 2px solid {p['accent']}; border-radius: {s['radius_lg']}px; min-height: {s['play_btn']}px; min-width: {s['play_btn']}px; font-weight: 600;; font-size: 14px;; padding: 0px;
    }}
    QPushButton#playBtn:hover {{ background-color: {p['accent']}; color: #ffffff;
    }}
    QPushButton#playBtn:pressed {{ background-color: {p['accent_pressed']}; border-color: {p['accent_pressed']}; color: #ffffff;
    }}

    /* ── Danger buttons (cancel / delete) ───────────────────────── */
    QPushButton#dangerBtn {{ background-color: transparent; color: {p['danger']}; border: 1px solid {p['danger']}; border-radius: {s['radius']}px;
    }}
    QPushButton#dangerBtn:hover {{ background-color: {p['danger']}; color: #ffffff;
    }}

    /* ── Sample-code pill buttons ───────────────────────────────── */
    QPushButton#sampleBtn {{ background-color: transparent; color: {p['text_dim']}; border: 1px solid {p['border']}; border-radius: 14px; padding: {s['xs']}px {s['lg']}px; min-height: 26px;; font-size: 12px;; font-weight: 500;
    }}
    QPushButton#sampleBtn:hover {{ color: {p['text']}; border-color: {p['accent']}; background-color: rgba(88,101,242,12);
    }}

    /* ── Inputs: line edits, combos, spin boxes ─────────────────── */
    QLineEdit, QComboBox, QSpinBox, QFontComboBox {{ background-color: {p['bg_input']}; color: {p['text']}; border: 1px solid {p['border']}; border-radius: {s['radius']}px; padding: {s['xs']}px {s['sm']}px; min-height: {s['control_h']}px; selection-background-color: {p['accent']}; selection-color: #ffffff;
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QFontComboBox:focus {{ border: 1px solid {p['border_focus']};
    }}
    QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QFontComboBox:hover {{ border-color: {p['text_dim']};
    }}
    QComboBox::drop-down {{ border: none;; width: 22px;
    }}
    QComboBox::down-arrow {{ image: none;; border-left: 4px solid transparent;; border-right: 4px solid transparent; border-top: 5px solid {p['text_dim']}; margin-right: 8px;
    }}
    QComboBox QAbstractItemView {{ background-color: {p['bg_panel']}; color: {p['text']}; border: 1px solid {p['border']}; border-radius: {s['radius']}px; selection-background-color: {p['accent']}; selection-color: #ffffff; padding: {s['xs']}px; outline: none;
    }}

    /* ── Sliders ────────────────────────────────────────────────── */
    QSlider::groove:horizontal {{ background: {p['bg_input']}; height: 4px;; border-radius: 2px;
    }}
    QSlider::sub-page:horizontal {{ background: qlineargradient( x1:0, y1:0, x2:1, y2:0, stop:0 {p['accent']}, stop:1 {p['accent_hover']} );; border-radius: 2px;
    }}
    QSlider::handle:horizontal {{ background: {p['text']}; width: 14px;; height: 14px;; margin: -5px 0;; border-radius: 7px; border: 2px solid {p['bg_app']};
    }}
    QSlider::handle:horizontal:hover {{ background: {p['accent']}; border-color: {p['accent']};
    }}

    /* ── Timeline slider (wider groove, accent-filled) ──────────── */
    QSlider#timelineSlider::groove:horizontal {{ height: 6px;; border-radius: 3px;
    }}
    QSlider#timelineSlider::handle:horizontal {{ width: 16px;; height: 16px;; margin: -5px 0;; border-radius: 8px;
    }}
    QSlider#timelineSlider::handle:horizontal:hover {{ background: {p['accent']}; width: 18px;; margin: -6px 0;
    }}

    /* ── Progress bar ───────────────────────────────────────────── */
    QProgressBar {{ background-color: {p['bg_input']}; border: 1px solid {p['border']}; border-radius: {s['radius']}px; text-align: center; color: {p['text']}; min-height: {s['control_h']}px; font-weight: 500;
    }}
    QProgressBar::chunk {{ background: qlineargradient( x1:0, y1:0, x2:1, y2:0, stop:0 {p['accent']}, stop:1 {p['accent_hover']} ); border-radius: {s['radius'] - 1}px;
    }}

    /* ── Checkboxes ─────────────────────────────────────────────── */
    QCheckBox {{ spacing: {s['sm']}px; min-height: {s['control_h']}px;
    }}
    QCheckBox::indicator {{ width: 16px;; height: 16px;; border-radius: 3px; border: 1px solid {p['border']}; background-color: {p['bg_input']};
    }}
    QCheckBox::indicator:hover {{ border-color: {p['accent']};
    }}
    QCheckBox::indicator:checked {{ background-color: {p['accent']}; border-color: {p['accent']}; image: none;
    }}

    /* ── Tabs (used for the settings panel) ─────────────────────── */
    QTabWidget::pane {{ border: 1px solid {p['border']}; border-radius: {s['radius_lg']}px; background-color: {p['bg_panel']}; padding: {s['md']}px; top: -1px;
    }}
    QTabBar::tab {{ background-color: transparent; color: {p['text_dim']}; padding: {s['sm']}px {s['lg']}px; margin-right: 2px;; border: 1px solid transparent;; border-bottom: none; border-top-left-radius: {s['radius']}px; border-top-right-radius: {s['radius']}px; font-weight: 500;; font-size: 12px; min-height: {s['control_h']}px;
    }}
    QTabBar::tab:hover {{ background-color: {p['bg_hover']}; color: {p['text']};
    }}
    QTabBar::tab:selected {{ background-color: {p['bg_panel']}; color: {p['text']}; border-color: {p['border']}; border-bottom: 2px solid {p['accent']};
    }}

    /* ── Scroll bars (slim, refined) ────────────────────────────── */
    QScrollBar:vertical {{ background: transparent;; width: 8px;; margin: 0;
    }}
    QScrollBar::handle:vertical {{ background: {p['border']}; min-height: 30px;; border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {p['text_dim']};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none;
    }}
    QScrollBar:horizontal {{ background: transparent;; height: 8px;; margin: 0;
    }}
    QScrollBar::handle:horizontal {{ background: {p['border']}; min-width: 30px;; border-radius: 4px;
    }}
    QScrollBar::handle:horizontal:hover {{ background: {p['text_dim']};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0;
    }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none;
    }}

    /* ── Text edit (code editor) ────────────────────────────────── */
    QTextEdit {{ background-color: {p['bg_input']}; color: {p['text']}; border: 1px solid {p['border']}; border-radius: {s['radius']}px; font-family: {UI_MONO_STACK}; font-size: 13px; padding: {s['sm']}px; selection-background-color: {p['accent']}; selection-color: #ffffff;
    }}
    QTextEdit:focus {{ border-color: {p['border_focus']};
    }}

    /* ── Labels ─────────────────────────────────────────────────── */
    QLabel {{ background: transparent;
    }}
    QLabel#sectionHeader {{ color: {p['text_dim']}; font-size: 11px;; font-weight: 600;; letter-spacing: 0.5px;; text-transform: uppercase; padding: {s['xs']}px 0;
    }}
    QLabel#previewPlaceholder {{ color: {p['text_dim']}; font-size: 14px;
    }}
    QLabel#timeLabel {{ color: {p['text_dim']}; font-family: {UI_MONO_STACK}; font-size: 12px; padding: 0 {s['sm']}px; min-width: 42px;
    }}

    /* ── Panel header bar ───────────────────────────────────────── */
    QLabel#panelHeader {{ color: {p['text']}; font-size: 12px;; font-weight: 600;; letter-spacing: 0.3px; background-color: {p['bg_panel']}; padding: {s['sm']}px {s['lg']}px; border-top-left-radius: {s['radius_lg']}px; border-top-right-radius: {s['radius_lg']}px;
    }}

    /* ── Status bar ─────────────────────────────────────────────── */
    QStatusBar {{ background-color: {p['bg_panel']}; color: {p['text_dim']}; border-top: 1px solid {p['border']}; font-size: 12px; padding: 2px {s['md']}px;
    }}
    QStatusBar::item {{ border: none; }}
    QLabel#statusPermanent {{ color: {p['text_dim']}; font-size: 11px; padding: 0 {s['lg']}px; border-left: 1px solid {p['border']};
    }}

    /* ── Menu bar ───────────────────────────────────────────────── */
    QMenuBar {{ background-color: {p['bg_app']}; color: {p['text']}; border-bottom: 1px solid {p['border']}; padding: 2px;
    }}
    QMenuBar::item {{ background: transparent; padding: {s['sm']}px {s['lg']}px; border-radius: {s['radius']}px;
    }}
    QMenuBar::item:selected {{ background-color: {p['bg_hover']};
    }}
    QMenu {{ background-color: {p['bg_panel']}; color: {p['text']}; border: 1px solid {p['border']}; border-radius: {s['radius']}px; padding: {s['xs']}px;
    }}
    QMenu::item {{ padding: {s['sm']}px {s['lg']}px; border-radius: {s['radius']}px;
    }}
    QMenu::item:selected {{ background-color: {p['accent']}; color: #ffffff;
    }}
    QMenu::separator {{ height: 1px; background: {p['border']}; margin: {s['xs']}px {s['sm']}px;
    }}

    /* ── Splitter handle (thin, subtle) ─────────────────────────── */
    QSplitter::handle:horizontal {{ background-color: {p['border']}; width: 1px;
    }}
    QSplitter::handle:horizontal:hover {{ background-color: {p['accent']}; width: 2px;
    }}

    /* ── Form layout labels ─────────────────────────────────────── */
    QLabel[class="formLabel"] {{ color: {p['text_dim']}; font-size: 12px;
    }}

    /* ── Message box ────────────────────────────────────────────── */
    QMessageBox {{ background-color: {p['bg_panel']};
    }}
    QMessageBox QLabel {{ color: {p['text']}; font-size: 13px;
    }}
    QMessageBox QPushButton {{ min-width: 80px;
    }}

    /* ── Input dialog ───────────────────────────────────────────── */
    QDialog {{ background-color: {p['bg_panel']}; color: {p['text']};
    }}

    /* ── Preview container frame ────────────────────────────────── */
    QFrame#previewFrame {{ background-color: #0a0a0f; border: 1px solid {p['border']}; border-radius: {s['radius_lg']}px;
    }}
    QFrame#previewFrame:hover {{ border-color: {p['text_dim']};
    }}

    /* ── Drop zone highlight ────────────────────────────────────── */
    QTextEdit#codeEditor[dropActive="true"] {{ border: 2px dashed {p['accent']}; background-color: rgba(88,101,242,8);
    }}

    /* ── Vertical separator (used between button groups) ────────── */
    QFrame#vsep {{ color: {p['border']}; max-width: 1px; margin: 0 {s['sm']}px;
    }}

    /* ── Toolbar frame (top action bar) ─────────────────────────── */
    QFrame#toolbar {{ background-color: {p['bg_panel']}; border: 1px solid {p['border']}; border-bottom: none; border-radius: {s['radius_lg']}px {s['radius_lg']}px 0 0; padding: {s['sm']}px {s['md']}px;
    }}

    /* ── Thin progress bar under toolbar ────────────────────────── */
    QProgressBar#toolbarProgress {{ background-color: {p['bg_input']}; border: none; border-radius: 0; min-height: 3px; max-height: 3px;
    }}
    QProgressBar#toolbarProgress::chunk {{ background: {p['accent']}; border-radius: 0;
    }}

    /* ── Vertical splitter handle ───────────────────────────────── */
    QSplitter::handle:vertical {{ background-color: {p['border']}; height: 1px;
    }}
    QSplitter::handle:vertical:hover {{ background-color: {p['accent']}; height: 2px;
    }}

    /* ── Panel body (used for left/right panels) ────────────────── */
    QWidget#panelBody {{ background-color: {p['bg_panel']}; border: 1px solid {p['border']}; border-top: none; border-radius: 0 0 {s['radius_lg']}px {s['radius_lg']}px;
    }}

    """

# ======================================================================
# tokenizers.py
# ======================================================================

"""
Syntax-highlighting tokenizers.

Each tokenizer compiles a single master regex on first use (thread-safe,
double-checked locking) and returns ``(token_type, token_text)`` tuples
that the renderer maps to theme colors.

Languages supported:
  - Python
  - JavaScript / TypeScript (shared)
  - C / C++ / Java
  - Go
  - Rust
"""

_LANG_DATA: Dict[str, Dict] = {
    "Python": {
        "keywords": {"def", "class", "if", "elif", "else", "for", "while", "return", "import", "from", "as", "try", "except", "finally", "with", "raise", "pass", "break", "continue", "and", "or", "not", "in", "is", "lambda", "yield", "global", "nonlocal", "assert", "del", "async", "await", "True", "False", "None"},
        "builtins": {"print", "len", "range", "int", "str", "float", "list", "dict", "set", "tuple", "type", "isinstance", "enumerate", "zip", "map", "filter", "sorted", "reversed", "any", "all", "min", "max", "sum", "abs", "round", "input", "open", "super", "property", "staticmethod", "classmethod", "hasattr", "getattr", "setattr", "delattr", "object", "Exception", "ValueError", "TypeError", "KeyError", "IndexError", "AttributeError", "RuntimeError", "self", "cls"},
        "extra_patterns": [
            ("triple_string", r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\''),
            ("decorator",     r"@\w+"),
        ],
        "comment": r"#[^\n]*",
        "string":  r'"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\'',
        "number":  r"\b\d+\.?\d*(?:e[+-]?\d+)?\b|0[xXoObB][0-9a-fA-F]+\b",
    },
    "JavaScript": {
        "keywords": {"var", "let", "const", "if", "else", "for", "while", "do", "switch", "case", "break", "continue", "function", "return", "class", "new", "this", "super", "extends", "import", "export", "from", "default", "try", "catch", "finally", "throw", "typeof", "instanceof", "in", "of", "async", "await", "yield", "true", "false", "null", "undefined", "void", "delete", "interface", "type", "enum", "implements", "namespace", "public", "private", "protected", "readonly", "abstract", "as", "is", "number", "string", "boolean", "any", "unknown", "never"},
        "builtins": {"console", "document", "window", "Math", "Array", "Object", "String", "Number", "Boolean", "Promise", "Symbol", "Map", "Set", "Date", "RegExp", "Error", "JSON", "parseInt", "parseFloat", "isNaN", "isFinite", "require", "module", "process"},
        "extra_patterns": [],
        "comment": r"//[^\n]*|/\*[\s\S]*?\*/",
        "string":  r'"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\'|`[^`\\]*(?:\\.[^`\\]*)*`',
        "number":  r"\b\d+\.?\d*(?:e[+-]?\d+)?\b|0x[0-9a-fA-F]+\b",
        "operator": r"[+\-*/%=<>!&|^~?]+",
    },
    "TypeScript": "JavaScript",
    "C/C++/Java": {
        "keywords": {"int", "float", "double", "char", "void", "if", "else", "for", "while", "do", "switch", "case", "break", "continue", "return", "struct", "typedef", "enum", "union", "const", "static", "extern", "unsigned", "signed", "long", "short", "class", "public", "private", "protected", "virtual", "override", "namespace", "using", "new", "delete", "try", "catch", "throw", "true", "false", "null", "auto", "nullptr", "template", "typename"},
        "builtins": {"printf", "scanf", "malloc", "free", "sizeof", "strlen", "std", "cout", "cin", "endl", "string", "vector", "map", "set"},
        "extra_patterns": [],
        "comment": r"//[^\n]*|/\*[\s\S]*?\*/",
        "string":  r'"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\'',
        "number":  r"\b\d+\.?\d*(?:e[+-]?\d+)?\b|0x[0-9a-fA-F]+\b",
    },
    "Go": {
        "keywords": {"break", "case", "chan", "const", "continue", "default", "defer", "else", "fallthrough", "for", "func", "go", "goto", "if", "import", "interface", "map", "package", "range", "return", "select", "struct", "switch", "type", "var", "nil", "true", "false", "iota"},
        "builtins": {"fmt", "os", "io", "strings", "strconv", "math", "time", "len", "cap", "make", "new", "append", "copy", "delete", "panic", "recover", "print", "println"},
        "extra_patterns": [],
        "comment": r"//[^\n]*|/\*[\s\S]*?\*/",
        "string":  r'"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\'|`[^`]*`',
        "number":  r"\b\d+\.?\d*(?:e[+-]?\d+)?\b|0x[0-9a-fA-F]+\b",
    },
    "Rust": {
        "keywords": {"fn", "let", "mut", "const", "static", "if", "else", "for", "while", "loop", "match", "return", "break", "continue", "in", "as", "use", "mod", "pub", "struct", "enum", "trait", "impl", "where", "self", "Self", "super", "crate", "extern", "ref", "move", "async", "await", "dyn", "unsafe", "true", "false"},
        "builtins": {"println", "print", "format", "vec", "String", "Vec", "Option", "Result", "Box", "Rc", "Arc", "Some", "None", "Ok", "Err", "HashMap", "BTreeMap", "HashSet"},
        "extra_patterns": [],
        "comment": r"//[^\n]*|/\*[\s\S]*?\*/",
        "string":  r'"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\'',
        "number":  r"\b\d+\.?\d*(?:e[+-]?\d+)?\b|0x[0-9a-fA-F]+\b",
        "operator": r"[+\-*/%=<>!&|^~?]+",
    },
}

# Resolve string aliases (e.g. "TypeScript" -> "JavaScript")
for _k, _v in list(_LANG_DATA.items()):
    if isinstance(_v, str) and _v in _LANG_DATA:
        _LANG_DATA[_k] = _LANG_DATA[_v]

LANGUAGES: List[str] = list(_LANG_DATA.keys())


class Tokenizer:
    """Language-aware tokenizer with lazy, thread-safe regex compilation."""

    _COMPILED: Dict[str, re.Pattern] = {}
    _LOCK = threading.Lock()

    @classmethod
    def _compile(cls, lang: str) -> re.Pattern:
        if lang not in cls._COMPILED:
            with cls._LOCK:
                if lang not in cls._COMPILED:
                    data = _LANG_DATA[lang]
                    patterns = list(data.get("extra_patterns", []))
                    patterns.extend([
                        ("comment",    data["comment"]),
                        ("string",     data["string"]),
                        ("number",     data["number"]),
                        ("keyword",    r"\b(?:" + "|".join(data["keywords"]) + r")\b"),
                        ("builtin",    r"\b(?:" + "|".join(data["builtins"]) + r")\b"),
                        ("function",   r"\b([a-zA-Z_]\w*)\s*(?=\()"),
                        ("identifier", r"\b[a-zA-Z_]\w*\b"),
                        ("operator",   data.get("operator", r"[+\-*/%=<>!&|^~]+")),
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
        """Return list of (token_type, token_text) for the given source."""
        compiled = cls._COMPILED.get(lang)
        if compiled is None:
            compiled = cls._compile(lang)
        return [(m.lastgroup, m.group()) for m in compiled.finditer(text)]
# ======================================================================
# widgets.py
# ======================================================================

"""
Custom Qt widgets used by the main window.
"""

class DropTextEdit(QTextEdit):
    """A QTextEdit that accepts file drops with visual drag-hover feedback."""

    files_dropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent); self.setAcceptDrops(True); self._drag_active = False; self._placeholder_text = "Type or drop a code file here..."; self._ph_color = QColor("#9aa0a6")
        self._ph_fm: Optional[QFontMetrics] = None; self._ph_font: Optional[QFont] = None

    def setPlaceholderText(self, text):
        self._placeholder_text = text; self.viewport().update()

    def placeholderText(self):
        return self._placeholder_text

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.toPlainText() and not self.hasFocus():
            font = self.font()
            if self._ph_font is not font:
                self._ph_font = font
                self._ph_fm = QFontMetrics(font)
            fm = self._ph_fm
            rect = self.viewport().rect().adjusted(8, 8, -8, -8)
            painter = QPainter(self.viewport())
            painter.setPen(self._ph_color)
            painter.drawText(rect, Qt.AlignTop | Qt.TextWordWrap, self._placeholder_text)
            painter.end()

    def dragEnterEvent(self, event): 
        if event.mimeData().hasUrls():
            event.acceptProposedAction(); self._drag_active = True; self.setProperty("dropActive", "true"); self.style().unpolish(self); self.style().polish(self); self.viewport().update()
        else:
            super().dragEnterEvent(event)

    def dragLeaveEvent(self, event): 
        self._drag_active = False; self.setProperty("dropActive", "false"); self.style().unpolish(self); self.style().polish(self); self.viewport().update(); super().dragLeaveEvent(event)

    def dragMoveEvent(self, event): 
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):  
        self._drag_active = False; self.setProperty("dropActive", "false"); self.style().unpolish(self); self.style().polish(self); self.viewport().update()
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    event.acceptProposedAction(); self.files_dropped.emit(url.toLocalFile()); break
        else:
            super().dropEvent(event)

# ======================================================================
# sound.py
# ======================================================================

"""
Procedural typing-sound generator (v4 — physical modelling DSP).

Synthesises short WAV-style int16 buffers (no external assets needed)
for six keyboard profiles and mixes them into a full audio track
aligned to a list of character timestamps.

Profiles
--------
  * Mechanical          — Cherry MX Blue / Brown hybrid thock
  * Typewriter          — sharp strike + bell on Enter
  * Soft Membrane       — quiet rubber-dome thud
  * Laptop Chiclet      — short, low-profile click (Apple Magic Keyboard)
  * Topre Electrostatic — premium electrostatic thock (HHKB / Realforce)
  * Custom Linear       — smooth analog linear (Holy Panda / Gateron)
  * Cash Register       — satisfying cash-register "cha-ching" per keystroke
  * Pinball             — bright coil-plunger + bumper pings
  * Telegraph           — rhythmic morse-code-style dots and dashes
  * Arcade Button       — microswitch click with cabinet resonance
  * Gunshot             — punchy percussive "boom" per keystroke
  * Gunshot Silenced    — suppressed thump — low, dark, subtle
  * Crystal Singing Bowl — ethereal glass/harmonic bowl with shimmering overtones
  * Synth Bubble        — squelchy resonant synth bubbles and whooshes
  * Tibetan Bowl        — deep meditative singing bowl with harmonic ringing

Per-character sound variety (11 categories)
--------------------------------------------
  * ``key``         — ordinary letter keys (8 variants)
  * ``space``       — spacebar (4 variants; longer & lower)
  * ``enter``       — return key (4 variants
  includes bell on Typewriter)
  * ``backspace``   — backspace (4 variants; slightly sharper)
  * ``tab``         — tab key (4 variants)
  * ``quote``       — quote / apostrophe (4 variants; softer, Shift-held)
  * ``bracket``     — bracket / brace (4 variants; metallic ring)
  * ``digit``       — digit keys (4 variants; pitched differently)
  * ``modifier``    — Shift / Ctrl / Cmd (4 variants; very short)
  * ``punctuation`` — period, comma, colon, semicolon, etc. (4 variants)
  * ``escape``      — Escape key (4 variants; distinctive)

DSP improvements over v3
-------------------------
  * **Karplus-Strong string synthesis** (``_karplus_strong``,
    ``_karplus_strong_v2``): physically-modelled plucked string
    algorithm using delay-line + averaging filter.  Produces natural
    bright-to-dark timbral evolution.  Used for typewriter typebar
    arms, cash register coins, telegraph relay springs, pinball
    bumper caps, arcade microswitch springs, and MX switch springs.
  * **State Variable Filter (SVF)** (``_svf_filter``): TPT zero-delay-
    feedback SVF by Vadim Zavalishin — the industry-standard filter
    topology in virtual analog synthesizers.  Provides simultaneous
    LP/HP/BP/Notch outputs, resonance control (Q), and numerical
    stability at all parameter settings.  Replaces Butterworth for
    musical filtering.
  * **Modal synthesis** (``_modal_impact``, ``_metal_plate_modes``,
    ``_wood_bar_modes``, ``_bell_modes``): physically-modelled impact
    using vibration mode analysis.  Metal plate modes use Bessel-
    function-zero ratios (for coins, bumpers, microswitch contacts).
    Wood bar modes use Euler-Bernoulli beam theory ratios (for
    typebars, telegraph sounders, cabinet resonances).  Bell modes
    use church bell partial ratios (hum, prime, minor third, etc.).
  * **Noise-excited resonator** (``_noise_excited_resonator``):
    physically-motivated model where a noise burst (the "hit")
    excites a resonant system (the "body").  Models how real
    acoustic impacts work: broadband energy → resonant filtering →
    ringing decay.  Used for keycap impacts, gunshot booms, housing
    thuds.
  * **SVF resonant noise** (``_svf_resonant_noise``): noise-burst
    excitation filtered through a resonant SVF, producing realistic
    resonant noise (hisses, buzzes, rattles) with proper decay.
  * **Comb filter** (``_comb_filter``): for metallic "tube" resonance
    and early reflection patterns.
  * **Schroeder allpass diffuser** (``_allpass_diffusion``): for
    reverb tail diffusion (standard algorithmic reverb building block).
  * **Phase-integrated frequency sweep** (``_frequency_sweep``):
    proper cumulative-phase frequency sweeps (replaces naive freq*t
    that causes phase discontinuities).
    for precomputed filter coefficients, avoiding redundant bilinear
    transform calculations.
  * **NaN-safe normalisation**: ``_normalise`` sanitises input before
    processing, preventing propagation of numerical artifacts.

  *Retained from v3*: vectorised IIR filtering, FFT-based noise
    shaping, FFT convolution reverb, FM-synthesis click transients,
    multi-partial body resonance, spectral tilt, peak limiter, mid-side
    stereo enhancement, frequency-dependent panning.
"""

def _apply_iir(signal: np.ndarray, b: np.ndarray, a):
    """Apply an IIR filter via truncated impulse response + convolution."""
    n = len(signal)
    if n == 0:
        return signal.copy()
    nb, na = len(b), len(a)

    if n < 512 or (na - 1) >= 4:
        x = signal.astype(np.float64); out = np.zeros(n, dtype=np.float64)
        for i in range(n):
            yi = b[0] * x[i]
            for j in range(1, nb):
                if i >= j:
                    yi += b[j] * x[i - j]
            for j in range(1, na):
                if i >= j:
                    yi -= a[j] * out[i - j]; out[i] = yi
        return out

    max_ir = min(n, 4096)
    ir = np.zeros(max_ir, dtype=np.float64)
    peak = 0.0
    ir[0] = b[0]
    for i in range(1, max_ir):
        x_i = b[i] if i < nb else 0.0; fb = 0.0
        for j in range(1, na):
            fb -= a[j] * ir[i - j]; ir[i] = x_i + fb; a_abs = abs(ir[i])
        if a_abs > peak:
            peak = a_abs
        if i > 20 and peak > 0 and a_abs < peak * 1e-4:
            ir = ir[:i + 1]; break
    else:
        ir = ir[:max_ir]

    return np.convolve(signal, ir, mode='full')[:n]

def _butter_lowpass(signal: np.ndarray, cutoff_ratio=0.15,
                    order: int = 2) -> np.ndarray:
    """Second-order Butterworth low-pass filter (all-numpy, no scipy).

    Parameters
    ----------
    signal : 1-D array
    cutoff_ratio : float in (0, 0.5)
        Cutoff as a fraction of the Nyquist frequency.; 0.15 at 44100 Hz  ->  ~3.3 kHz cutoff.
    order : int (1 or 2)
        Filter order.  2 gives a steeper rolloff.

    Implementation: designs biquad (or first-order) coefficients, then
    delegates to :func:`_apply_iir` for convolution-based application.
    """
    wc = np.tan(np.pi * cutoff_ratio)  # pre-warped angular cutoff
    x = signal.astype(np.float64)
    if order == 1:
        b0 = wc / (1.0 + wc); a1 = (1.0 - wc) / (1.0 + wc)
        return _apply_iir(x, np.array([b0]), np.array([1.0, a1]))
    k = wc * wc
    norm = 1.0 / (1.0 + np.sqrt(2) * wc + k)
    b0 = k * norm;  b1 = 2.0 * b0;  b2 = b0
    a1 = 2.0 * (k - 1.0) * norm
    a2 = (1.0 - np.sqrt(2) * wc + k) * norm
    return _apply_iir(x, np.array([b0, b1, b2]), np.array([1.0, a1, a2]))

def _highpass(signal: np.ndarray, cutoff_ratio=0.02):
    """First-order high-pass filter to remove DC and sub-bass rumble."""
    if cutoff_ratio <= 0 or cutoff_ratio >= 0.5:
        return signal.astype(np.float64)
    wc = np.tan(np.pi * cutoff_ratio)
    b0 = 1.0 / (1.0 + wc)
    a1 = (1.0 - wc) / (1.0 + wc)
    return _apply_iir(signal.astype(np.float64), np.array([b0, -b0]), np.array([1.0, -a1]))

def _bandpass_noise(n: int, rng: np.random.RandomState,
                    lo_hz: float = 2000, hi_hz: float = 5000,
                    sr: int = 44100) -> np.ndarray:
    """Generate band-pass filtered white noise (keycap rattle model).

    Uses :func:`_apply_iir` for both the high-pass and low-pass stages,
    eliminating two Python-level for-loops.
    """
    noise = rng.randn(n).astype(np.float64)
    rc_hp = 1.0 / (2 * np.pi * lo_hz) * sr
    alpha_hp = rc_hp / (1 + rc_hp)
    hp = _apply_iir(noise, np.array([alpha_hp, -alpha_hp]), np.array([1.0, -(1 - alpha_hp)]))
    return _butter_lowpass(hp, min(hi_hz / (sr * 0.5), 0.48), order=2)

def _env_adsr(t: np.ndarray, attack=0.0005, decay=0.02,
               sustain_level: float = 0.3, release: float = 0.04,
               delay: float = 0.0) -> np.ndarray:
    """Multi-stage ADSR-style envelope.

    Models:
      - attack:  fast ramp to peak (switch stem compressing spring)
      - decay:   initial ring-down
      - sustain: residual vibration
      - release: final tail-off

    The sustain is implemented as an exponential decay from a higher
    level that transitions smoothly into the release phase, which
    gives a more natural sound than a pure exponential.
    """
    shifted = np.maximum(0.0, t - delay)
    env = np.zeros_like(t)
    if attack > 0:
        mask_a = shifted < attack
        if np.any(mask_a):
            env[mask_a] = 1.0 - np.exp(-shifted[mask_a] / (attack * 0.3))
    else:
        mask_a = np.zeros(len(t), dtype=bool)
    mask_d = ~mask_a
    if np.any(mask_d):
        post_attack = shifted[mask_d] - attack; decay_rate = -np.log(max(sustain_level, 0.01)) / max(decay, 0.001); env[mask_d] = np.exp(-post_attack * decay_rate)
    return np.clip(env, 0.0, 1.0)

def _spring_ring(t: np.ndarray, freq=5200, decay=800,
                 rng: np.random.RandomState = None,
                 detune: float = 150, sr: int = 44100) -> np.ndarray:
    """Model the metal spring resonance inside MX-style switches.

    Two closely-spaced detuned sines that beat briefly, giving a
    characteristic "ting" that decays fast.
    """
    f1 = freq + (rng.randint(-int(detune), int(detune)) if rng else 0)
    f2 = freq + (rng.randint(-int(detune), int(detune)) if rng else 0) + detune * 0.7
    ring = (np.sin(2 * np.pi * f1 * t) + 0.6 * np.sin(2 * np.pi * f2 * t))
    ring *= np.exp(-t * decay) * 0.18
    return ring

def _early_reverb(signal: np.ndarray, sr=44100,
                  delays_ms: Tuple[float, ...] = (8, 17, 27),
                  feedback: float = 0.25, wet: float = 0.12) -> np.ndarray:
    """Simple early-reflections reverb using delay lines.

    Adds a sense of space without expensive convolution.
    """
    out = signal.astype(np.float64)
    for d_ms in delays_ms:
        d = int(sr * d_ms / 1000)
        if d <= 0 or d >= len(signal):
            continue
        delayed = np.zeros_like(out); delayed[d:] = out[:-d] * feedback; out = out + delayed * wet
    return out

def _normalise(signal: np.ndarray, target_db=-3.0):
    """Normalise an int16 signal to ``target_db`` below full scale."""
    clean = np.nan_to_num(signal.astype(np.float64), nan=0.0, posinf=0.0, neginf=0.0)
    peak = float(np.max(np.abs(clean)))
    if peak < 1e-10:
        return np.zeros_like(signal, dtype=np.int16)
    target = int(32767 * 10 ** (target_db / 20))
    scale = target / peak
    return np.clip(clean * scale, -32768, 32767).astype(np.int16)

def _soft_clip(signal: np.ndarray, threshold=0.85):
    """Tanh-based soft clipper to prevent harsh digital distortion."""
    scaled = signal.astype(np.float64) / 32768.0
    clipped = np.tanh(scaled / threshold) * threshold
    return (clipped * 32768).astype(np.int16)

def _pink_noise(n: int, sr=44100, seed=42):
    """Generate pink noise (1/f spectrum) for room tone."""
    rng = np.random.RandomState(seed)
    white = rng.randn(n).astype(np.float64)
    b = np.array([0.049922035, -0.095993537, 0.050612699, -0.004400824])
    a = np.array([1.0, -2.494956002, 2.017265875, -0.522189400])
    pink = _apply_iir(white, b, a)
    transient = min(24, n)
    if transient > 0 and transient < n:
        pink[:transient] *= np.linspace(0, 1, transient) ** 2
    peak = np.max(np.abs(pink))
    if peak > 0:
        pink *= 0.003 / peak
    return pink

def _noise_shaped(n: int, rng: np.random.RandomState,
                   lo_hz: float = 200, hi_hz: float = 8000,
                   sr: int = 44100, tilt_db: float = -6.0) -> np.ndarray:
    """Spectrally-shaped noise burst via FFT (replaces cascaded IIR filters).

    Instead of applying multiple cascaded first-order low-pass stages in
    Python loops (old approach, O(n * stages)), this shapes the noise
    spectrum in the frequency domain:

      1. Generate white noise.
      2. FFT to get the magnitude spectrum.
      3. Multiply by a smooth spectral envelope that combines:
         - High-frequency rolloff  (``tilt_db`` per octave); - Band-pass bounds        (``lo_hz`` to ``hi_hz``)
      4. IFFT back to time domain.

    This is O(n log n) regardless of the number of spectral shaping
    parameters, and produces much smoother, more natural spectral
    shapes than cascaded first-order filters.
    """
    noise = rng.randn(n).astype(np.float64)

    spectrum = np.fft.rfft(noise)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)

    freqs_safe = np.maximum(freqs, 1.0)

    if abs(tilt_db) > 0.5:
        ref_hz = 1000.0
        with np.errstate(divide='ignore', invalid='ignore'):
            gain_db = tilt_db * np.log2(freqs_safe / ref_hz); gain_db = np.where(np.isfinite(gain_db), gain_db, 0.0); envelope = 10.0 ** (gain_db / 20.0)
    else:
        envelope = np.ones(len(freqs), dtype=np.float64)

    hp_slope = 1.0 / (1.0 + (lo_hz / freqs_safe) ** 4)
    lp_slope = 1.0 / (1.0 + (freqs_safe / hi_hz) ** 4)
    envelope *= hp_slope * lp_slope

    if len(envelope) > 10:
        win = np.exp(-0.5 * np.linspace(-2.5, 2.5, len(envelope)) ** 2); envelope = envelope ** (0.3 + 0.7 * win)

    spectrum *= envelope
    shaped = np.fft.irfft(spectrum, n=n)

    fade = min(8, n)
    if fade > 1:
        shaped[:fade] *= np.linspace(0, 1, fade) ** 2

    return shaped

def _fm_click(t: np.ndarray, f_carrier: float, f_mod: float,
               mod_index: float, rng: np.random.RandomState,
               decay: float = 500.0, detune: float = 0.0) -> np.ndarray:
    """FM-synthesis based click transient for realistic metallic sounds.

    Uses a modulator -> carrier FM pair which naturally produces
    inharmonic sidebands that mimic the complex spectral content of
    mechanical impacts (spring steel, metal contacts, etc.).

    Parameters
    ----------
    f_carrier : float  -- carrier frequency (Hz)
    f_mod     : float  -- modulator frequency (Hz)
    mod_index : float  -- FM depth (higher = brighter, more harmonics)
    decay     : float  -- exponential decay rate
    detune    : float  -- random frequency detune range (Hz)
    """
    fc = f_carrier + (rng.randint(-int(detune), int(detune + 1)) if detune else 0)
    fm = f_mod + (rng.randint(-int(detune * 0.3), int(detune * 0.3 + 1)) if detune else 0)
    mod_phase = 2 * np.pi * fm * t
    modulator = np.sin(mod_phase) * mod_index
    carrier_phase = 2 * np.pi * fc * t + modulator
    am = 1.0 + 0.15 * np.sin(2 * np.pi * fm * 0.5 * t)
    click = np.sin(carrier_phase) * am * np.exp(-t * decay)
    return click

def _resonant_body(t: np.ndarray, f0: float, rng: np.random.RandomState,
                    n_partials: int = 5, decay_base: float = 150.0,
                    inharmonicity: float = 0.002, delay: float = 0.0,
                    amplitude_rolloff: float = 0.55) -> np.ndarray:
    """Multi-partial body resonance for realistic thock/thud sounds.

    Models the complex resonance of a keyboard case/housing as a set of
    harmonically-related partials with:
    - Natural amplitude rolloff (higher partials are quieter)
    - Frequency-dependent decay (higher partials decay faster)
    - Slight inharmonicity (real wooden/plastic cases aren't perfect resonators)
    - Configurable delay for the resonance to "excite" after the initial impact

    Parameters
    ----------
    f0               : float  -- fundamental resonance frequency (Hz)
    n_partials       : int    -- number of harmonic partials
    decay_base       : float  -- base decay rate for fundamental
    inharmonicity    : float  -- stretching factor (0 = perfectly harmonic)
    delay            : float  -- onset delay in seconds
    amplitude_rolloff: float  -- each partial is this fraction of the previous
    """
    out = np.zeros_like(t, dtype=np.float64)
    for k in range(1, n_partials + 1):
        f_k = k * f0 * np.sqrt(1.0 + k * k * inharmonicity); f_k += rng.randint(-int(f0 * 0.01), int(f0 * 0.01 + 1)); decay_k = decay_base * (1.0 + 0.4 * (k - 1)); amp = amplitude_rolloff ** (k - 1)
        phase_off = rng.uniform(0, 2 * np.pi); out += np.sin(2 * np.pi * f_k * t + phase_off) * np.exp(-t * decay_k) * amp
    if delay > 0:
        out *= _env_adsr(t, 0.002, 0.01, 0.5, 0.04, delay=delay)
    return out

def _spring_model_v2(t: np.ndarray, freq=5200, decay=800,
                      rng: np.random.RandomState = None,
                      detune: float = 200, n_partials: int = 4,
                      sr: int = 44100) -> np.ndarray:
    """Upgraded spring resonance with multiple inharmonic partials.

    Real metal springs produce a cluster of closely-spaced frequencies
    due to transverse, longitudinal, and torsional vibration modes.
    This models 4+ modes with slight inharmonicity for a richer 'ting'.
    """
    out = np.zeros_like(t, dtype=np.float64)
    for k in range(n_partials):
        ratio = 1.0 + k * 0.31 + k * k * 0.02  # inharmonic spacing
        f_k = freq * ratio
        if rng:
            f_k += rng.randint(-int(detune), int(detune + 1))
        d_k = decay * (1.0 + k * 0.6)
        amp = 0.6 ** k
        phase_off = rng.uniform(0, 2 * np.pi) if rng else 0
        out += np.sin(2 * np.pi * f_k * t + phase_off) * np.exp(-t * d_k) * amp
    return out * 0.18

def _spectral_tilt(signal: np.ndarray, sr=44100,
                    tilt_db_oct: float = -3.0) -> np.ndarray:
    """Apply a spectral tilt (dB/octave) to a signal.

    Positive tilt boosts treble, negative tilt boosts bass.
    Uses :func:`_apply_iir` with first-order shelving coefficients,
    replacing the old per-sample Python loops.
    """
    if abs(tilt_db_oct) < 0.1:
        return signal.astype(np.float64)

    out = signal.astype(np.float64)
    n_stages = max(1, round(abs(tilt_db_oct) / 6.0))
    for _ in range(n_stages):
        if tilt_db_oct < 0:
            alpha = 0.12; lp = _apply_iir(out, np.array([alpha]), np.array([1.0, -(1 - alpha)])); out = out * 0.7 + lp * 0.3
        else:
            alpha = 0.12; hp = _apply_iir(out, np.array([alpha, -alpha]), np.array([1.0, -(1 - alpha)])); out = out * 0.7 + hp * 0.3
    return out

def _generate_ir(sr=44100, duration=0.06,
                   room_size: float = 0.5, damping: float = 0.6) -> np.ndarray:
    """Generate a synthetic impulse response for convolution reverb.

    Creates a physically-plausible short IR using:
      - Early reflections: exponentially-spaced delay taps modelling
        first- and second-order wall bounces with proper inverse-square; amplitude decay and frequency-dependent absorption.
      - Diffuse tail: exponentially-decaying filtered noise modelling
        late reverberation, with proper spectral darkening over time.

    Parameters
    ----------
    room_size : float in (0, 1) -- larger = longer reverb tail
    damping  : float in (0, 1) -- higher = faster decay
    """
    n = int(sr * duration)
    ir = np.zeros(n, dtype=np.float64)
    rng = np.random.RandomState(12345)

    n_taps = 8
    base_delay_ms = 3.0 + room_size * 5.0  # 3-8ms first reflection
    for i in range(n_taps):
        delay_ms = base_delay_ms * (1.8 ** i); delay_samps = int(delay_ms * sr / 1000)
        amp = (0.5 ** i) * (0.3 + 0.7 * damping) * rng.uniform(0.6, 1.0)
        brightness = 0.7 ** i  # 1.0 = full bright, decreasing for later taps
        if delay_samps >= n:
            break
        ir[delay_samps] += amp * rng.choice([-1, 1]) * brightness
        if delay_samps + 1 < n:
            ir[delay_samps + 1] += amp * 0.3 * rng.choice([-1, 1]) * brightness
        if delay_samps + 2 < n:
            ir[delay_samps + 2] += amp * 0.1 * rng.choice([-1, 1]) * brightness * 0.5

    tail_start = min(int(base_delay_ms * (1.8 ** n_taps) * sr / 1000), n - 1)
    tail_len = n - tail_start
    if tail_len > 10:
        tail = rng.randn(tail_len).astype(np.float64); tail = _butter_lowpass(tail, 0.15, order=1)  # dark tail
        t_tail = np.arange(tail_len) / sr
        tail *= np.exp(-t_tail * (15.0 / max(room_size, 0.1)) * (1.2 - damping * 0.8)); ir[tail_start:] += tail * 0.15

    peak = np.max(np.abs(ir))
    if peak > 0:
        ir /= peak
    return ir

def _fft_convolve(signal: np.ndarray, ir):
    """Fast FFT-based convolution (much faster than direct for long signals)."""
    n_sig = len(signal)
    n_ir = len(ir)
    if n_sig < 256 or n_ir < 16:
        return np.convolve(signal, ir, mode='full')[:n_sig]
    block_size = 1
    while block_size < 2 * n_ir:
        block_size *= 2
    out = np.zeros(n_sig + n_ir - 1, dtype=np.float64)
    ir_padded = np.zeros(block_size, dtype=np.float64)
    ir_padded[:n_ir] = ir
    ir_fft = np.fft.rfft(ir_padded)
    pos = 0
    while pos < n_sig:
        block_end = min(pos + block_size // 2, n_sig); block = np.zeros(block_size, dtype=np.float64); block[:block_end - pos] = signal[pos:block_end]
        conv = np.fft.irfft(np.fft.rfft(block) * ir_fft, n=block_size); end = min(pos + block_size, len(out)); out[pos:end] += conv[:end - pos]; pos = block_end
    return out[:n_sig]

def _peak_limiter(signal: np.ndarray, sr=44100,
                    ceiling_db: float = -1.5, release_ms: float = 50.0) -> np.ndarray:
    """Transparent peak limiter (block-based, mostly vectorised).

    Prevents clipping while preserving transient punch.  Uses a
    block-envelope approach: the signal is divided into small blocks
    (~1 ms each), the peak of each block is found with numpy, then
    the block peaks are smoothed with an exponential release in a
    tiny Python loop (typically <100 iterations).  The smoothed
    envelope is then expanded back to sample level with numpy repeat.

    Memory-efficient (v1.9): processes in chunks to avoid allocating
    multiple full-length float64 arrays simultaneously on long tracks.

    Parameters
    ----------
    signal     : 1-D float32 or float64 array
    ceiling_db : float  — maximum peak level in dBFS
    release_ms : float  — release time in milliseconds
    """
    n = len(signal)
    if n == 0:
        return signal
    use_f32 = signal.dtype == np.float32
    x = np.abs(signal)
    ceiling = 10 ** (ceiling_db / 20.0) * 32767.0

    block_size = max(1, int(sr * 0.001))
    n_blocks = (n + block_size - 1) // block_size

    block_peaks = np.empty(n_blocks, dtype=np.float64)
    for i in range(n_blocks):
        s = i * block_size; e = min(s + block_size, n); block_peaks[i] = np.max(x[s:e])

    release_per_sample = np.exp(-1.0 / (release_ms * 0.001 * sr))
    release_per_block = release_per_sample ** block_size
    smoothed = np.empty(n_blocks, dtype=np.float64)
    smoothed[0] = block_peaks[0]
    for i in range(1, n_blocks):
        smoothed[i] = max(block_peaks[i], smoothed[i - 1] * release_per_block)

    envelope = np.repeat(smoothed, block_size)[:n]

    over = envelope > ceiling
    if np.any(over):
        out = signal.copy(); out[over] *= ceiling / envelope[over]; return out
    return signal

def _mid_side_enhance(stereo: np.ndarray, width=1.3):
    """Mid-side stereo width enhancement (memory-efficient chunked version)."""
    CHUNK_SAMPLES = 4_000_000  # ~90s of stereo at 44.1 kHz per chunk
    total = len(stereo)
    result = np.empty_like(stereo)

    for start in range(0, total, CHUNK_SAMPLES):
        end = min(start + CHUNK_SAMPLES, total); chunk = stereo[start:end]; n = len(chunk) // 2
        if n == 0:
            continue
        left = chunk[0::2].astype(np.float32); right = chunk[1::2].astype(np.float32); mid = (left + right) * 0.5; left -= right; side = left; side *= width
        result[start:end:2] = np.clip(mid + side, -32768, 32767).astype(np.int16); result[start + 1:end:2] = np.clip(mid - side, -32768, 32767).astype(np.int16)

    return result

def _shape_attack(signal: np.ndarray, attack_ms=0.5,
                   hardness: float = 2.0, sr: int = 44100) -> np.ndarray:
    """Shape the attack transient for a more natural 'pop'.

    Applies a very short logarithmic attack envelope to the first few
    milliseconds of a sound, giving it a sharper, more realistic onset
    instead of an instant full-amplitude start.

    Parameters
    ----------
    attack_ms : float  -- attack duration in ms (0.3 - 2.0 typical)
    hardness  : float  -- shape exponent (higher = sharper; 1.0 = linear)
    """
    n = len(signal)
    out = signal.astype(np.float64)
    attack_n = int(attack_ms * sr / 1000)
    if attack_n < 2 or attack_n >= n:
        return signal
    envelope = np.linspace(0, 1, attack_n) ** hardness
    out[:attack_n] *= envelope
    return out


def _svf_filter(signal: np.ndarray, freq: float, q=0.707,
                sr: int = 44100, mode: str = 'lp') -> np.ndarray:
    """State Variable Filter — the musically superior alternative to Butterworth.

    Unlike Butterworth (which only gives LP), the SVF simultaneously
    computes LP, HP, BP, and Notch outputs from a single 2-state
    recursive filter.  Key advantages:

    * **Resonance (Q) control** — can boost frequencies near cutoff,
      producing the "ringing" characteristic of real acoustic resonances.
    * **Simultaneous outputs** — can mix LP+HP for a band-reject, or
      LP+BP for a more natural rolloff, without running the filter twice.
    * **Numerically stable** at all parameter settings (no bilinear transform pole-zero flipping issues that plague direct-form IIR).
    * **Smoothly modulatable** — freq/Q can change per-sample for
      filter sweeps without clicks or instability.

    The topology used is the "TPT" (Topologies Preserving Transform)
    zero-delay-feedback SVF by Vadim Zavalishin, which is the
    industry-standard in modern VA (virtual analog) synthesizers.

    Parameters
    ----------
    signal : 1-D array
    freq   : cutoff frequency in Hz
    q      : resonance (1/sqrt(2) = Butterworth, >1 = resonant peak)
    sr     : sample rate
    mode   : 'lp', 'hp', 'bp', 'notch', or 'peak'

    Returns
    -------
    Filtered signal (same length).
    """
    x = signal.astype(np.float64)
    n = len(x)
    if n == 0:
        return x

    freq_clamped = min(freq, sr * 0.45)
    wc = np.tan(np.pi * freq_clamped / sr)
    g = wc  # integrator gain
    k = 1.0 / (2.0 * max(q, 0.01))  # standard TPT SVF feedback coefficient
    denom = 1.0 + g * (g + k)
    a1 = 1.0 / denom
    a2 = g * a1
    a3 = g * g * a1
    a4 = k * a1

    lp = 0.0
    bp = 0.0

    out = np.empty(n, dtype=np.float64)
    for i in range(n):
        hp = (x[i] - lp * g * (g + k) - bp * k) * a1; bp_new = bp + g * hp; lp_new = lp + g * bp_new; bp_new = max(-10.0, min(10.0, bp_new)); lp_new = max(-10.0, min(10.0, lp_new)); lp, bp = lp_new, bp_new
        if mode == 'lp':
            out[i] = lp
        elif mode == 'hp':
            out[i] = hp
        elif mode == 'bp':
            out[i] = bp
        elif mode == 'notch':
            out[i] = hp + lp
        else:  # 'peak'
            out[i] = hp - lp

    return out

def _svf_resonant_noise(n: int, rng: np.random.RandomState,
                         freq: float, q: float, sr: int = 44100,
                         decay: float = 300.0) -> np.ndarray:
    """Generate noise-burst excitation filtered through a resonant SVF.

    This is a physically-motivated model: a broadband impulse (noise)
    excites a resonant system (the SVF), which rings at its natural
    frequency with a decay controlled by Q.  Much more realistic than
    adding a sine wave and filtered noise separately.

    Parameters
    ----------
    n      : length in samples
    rng    : random state
    freq   : resonant frequency (Hz)
    q      : quality factor (higher = longer ring, sharper peak)
    decay  : additional exponential decay rate (per second)
    """
    noise = rng.randn(n).astype(np.float64)
    exc_len = min(int(0.001 * sr), n)  # 1ms excitation burst
    if exc_len > 0:
        noise[exc_len:] *= 0.0; noise[:exc_len] *= np.linspace(1.0, 0.5, exc_len)

    filtered = _svf_filter(noise, freq, q, sr, mode='bp')

    t = np.arange(n, dtype=np.float64) / sr
    filtered *= np.exp(-t * decay)
    return filtered

def _karplus_strong(freq: float, duration: float, sr=44100,
                     brightness: float = 0.5, damping: float = 0.5,
                     rng: np.random.RandomState = None) -> np.ndarray:
    """Karplus-Strong string synthesis — physically-modelled plucked string.

    The algorithm works by:
    1. Filling a delay line with a short noise burst (the "pluck").
    2. Repeatedly reading from the delay line, averaging adjacent samples,
       and writing back.  This low-pass averaging simulates energy loss
       in a vibrating string, naturally producing a timbre that brightens
       then darkens over time — exactly like a real plucked string.

    Key physical properties modelled:
    * **Pitch** → delay line length (N = sr/freq samples)
    * **Brightness** → probability of applying the averaging filter
      (1.0 = muffled, 0.0 = bright/sharp initial pluck)
    * **Sustain/damping** → mix between averaged and original sample
      (0.0 = instant damping, 1.0 = long sustain)
    * **Inharmonicity** → slight stretching of the delay line over time
      (higher harmonics decay faster, pitch droops slightly)

    This is THE standard algorithm for realistic plucked-string sounds
    and is far superior to a simple decaying sine wave for:
    * Typewriter typebar arms (metallic "clang")
    * Cash register coins (metallic "ping")
    * Telegraph relay springs
    * Pinball bumper caps
    * Any metallic/struck-string sound

    Parameters
    ----------
    freq        : fundamental frequency (Hz)
    duration    : output length (seconds)
    sr          : sample rate
    brightness  : 0.0 (sharp/bright) to 1.0 (muffled/warm)
    damping     : 0.0 (long sustain) to 1.0 (quick damping)
    rng         : random state for initial noise burst

    Returns
    -------
    1-D float64 array of length int(duration * sr).
    """
    n = int(duration * sr)
    if n == 0:
        return np.array([], dtype=np.float64)

    if rng is None:
        rng = np.random.RandomState(42)

    period = max(2, int(sr / freq))
    buf_len = n + period
    buf = np.zeros(buf_len, dtype=np.float64)

    n_excite = min(period * 2, n)
    raw_noise = rng.randn(n_excite)
    excite_spectrum = np.fft.rfft(raw_noise)
    freqs_excite = np.fft.rfftfreq(n_excite, 1.0 / sr)
    rolloff = 1.0 / (1.0 + (freqs_excite / (freq * 8.0)) ** 4)
    excite_spectrum *= rolloff
    excitation = np.fft.irfft(excite_spectrum, n=n_excite)
    peak = np.max(np.abs(excitation))
    if peak > 0:
        excitation /= peak

    buf[:n_excite] = excitation

    blend = 0.5 * damping + 0.3  # 0.3-0.8 range
    stretch = 1.0 + 0.0002 * (1.0 - brightness)

    avg_prob = 0.3 + 0.6 * brightness  # 0.3 (bright) to 0.9 (muffled)

    write_pos = 0
    read_pos = period

    for i in range(n_excite, buf_len):
        rp = read_pos; rp_int = int(rp); rp_frac = rp - rp_int
        if rp_int + 1 < buf_len:
            delayed = buf[rp_int] * (1.0 - rp_frac) + buf[min(rp_int + 1, buf_len - 1)] * rp_frac
        else:
            delayed = buf[min(rp_int, buf_len - 1)]
        if rp_int > 0:
            prev = buf[rp_int - 1]; averaged = 0.5 * (delayed + prev)
        else:
            averaged = delayed
        if rng.rand() > avg_prob:
            filtered = delayed  # no filtering = brighter
        else:
            filtered = averaged
        buf[i] = blend * filtered + (1.0 - blend) * delayed; read_pos += stretch; write_pos += 1

    return buf[:n]

def _karplus_strong_v2(freq: float, duration: float, sr=44100,
                        brightness: float = 0.4, damping: float = 0.6,
                        rng: np.random.RandomState = None,
                        n_strings: int = 1, detune_hz: float = 5.0,
                        freq_spread: float = 0.002) -> np.ndarray:
    """Multi-string Karplus-Strong for richer, chorus-like metallic sounds.

    Runs multiple KS generators at slightly different frequencies
    (simulating multiple vibration modes or a chorus of strings).
    The beating between strings creates a natural, organic quality
    that a single KS generator can't achieve.

    Parameters
    ----------
    freq        : base fundamental frequency (Hz)
    n_strings   : number of parallel KS generators (1-4)
    detune_hz   : random frequency offset per string
    freq_spread : fractional frequency spread (inharmonicity)
    """
    n = int(duration * sr)
    out = np.zeros(n, dtype=np.float64)

    for s in range(n_strings):
        f_var = freq + (rng.randint(-int(detune_hz * 10), int(detune_hz * 10 + 1)) / 10.0 if rng else 0); f_var *= (1.0 + s * freq_spread)
        b_var = np.clip(brightness + (rng.uniform(-0.1, 0.1) if rng else 0), 0.0, 1.0); d_var = np.clip(damping + (rng.uniform(-0.1, 0.1) if rng else 0), 0.0, 1.0)
        out += _karplus_strong(f_var, duration, sr, b_var, d_var, rng)

    peak = np.max(np.abs(out))
    if peak > 0:
        out /= peak
    return out

def _modal_impact(n: int, rng: np.random.RandomState,
                   modes: List[Tuple[float, float, float, float]],
                   sr: int = 44100, noise_mix: float = 0.15,
                   noise_decay: float = 400.0) -> np.ndarray:
    """Physically-modelled impact using modal analysis.

    Instead of guessing what sine frequencies sound good, this uses
    a list of vibration *modes*, each with:
    - frequency (Hz)
    - amplitude (relative)
    - decay rate (1/s)
    - phase offset (radians)

    Real objects vibrate in discrete modes.  For example:
    * A struck metal plate has modes at Bessel-function-zero frequencies
    * A wooden bar has modes following Euler-Bernoulli beam theory
    * A bell has modes at (roughly) 1 : 2.0 : 3.0 : 4.5 : 6.0 ratios

    This function lets you define those modes explicitly, producing
    far more realistic results than random sine waves.

    Parameters
    ----------
    modes : list of (freq_hz, amplitude, decay_rate, phase_rad) tuples
    noise_mix   : mix level of noise burst (0.0 = pure modal, 1.0 = noisy)
    noise_decay : decay rate for the noise burst component
    """
    t = np.arange(n, dtype=np.float64) / sr
    out = np.zeros(n, dtype=np.float64)

    for freq, amp, decay, phase in modes:
        f = freq + rng.randint(-int(freq * 0.005), int(freq * 0.005) + 1); d = decay + rng.uniform(-decay * 0.05, decay * 0.05); out += np.sin(2 * np.pi * f * t + phase) * np.exp(-t * d) * amp

    if noise_mix > 0.01:
        noise = rng.randn(n).astype(np.float64); noise *= np.exp(-t * noise_decay)
        if n > 20:
            noise = _svf_filter(noise, min(freq * 3 if modes else 4000, sr * 0.48), 0.707, sr, mode='lp'); out += noise * noise_mix

    return out

def _metal_plate_modes(f0: float, n_modes=6,
                        rng: np.random.RandomState = None) -> List[Tuple[float, float, float, float]]:
    """Generate vibration mode frequencies for a struck metal plate.

    Uses approximate Bessel-function-zero ratios for a circular plate,
    which is the physically correct model for:
    * Coin impacts
    * Bell/gong strikes
    * Metallic bumper caps (pinball)
    * Microswitch contacts

    The ratios are based on the (m,n) modes of a clamped circular
    plate, where the frequencies go roughly as:
    j(m,n)^2 / j(0,1)^2
    with j(m,n) being Bessel function zeros.

    For simplicity and robustness, we use the well-known approximate
    ratios: 1.0, 2.14, 3.59, 5.27, 7.20, 9.37, ...

    Parameters
    ----------
    f0      : fundamental frequency (Hz)
    n_modes : number of modes to generate
    rng     : for random phase offsets (natural variation)
    """
    if rng is None:
        rng = np.random.RandomState(42)

    bessel_ratios = [1.0, 2.14, 3.59, 5.27, 7.20, 9.37, 11.8, 14.5]
    amp_rolloff = 0.55
    base_decay = 800.0  # 1/s for fundamental

    modes = []
    for k in range(min(n_modes, len(bessel_ratios))):
        ratio = bessel_ratios[k]; f_k = f0 * ratio; f_k += rng.randint(-int(f0 * 0.008), int(f0 * 0.008) + 1); amp = amp_rolloff ** k; decay = base_decay * (1.0 + 0.8 * k); phase = rng.uniform(0, 2 * np.pi)
        modes.append((f_k, amp, decay, phase))

    return modes

def _wood_bar_modes(f0: float, n_modes=5,
                     rng: np.random.RandomState = None) -> List[Tuple[float, float, float, float]]:
    """Generate vibration mode frequencies for a struck wooden bar.

    Uses Euler-Bernoulli beam theory ratios for a free-free bar:
    f_n / f_1 ≈ (2n+1)^2 / 3^2 for the first few modes.

    Ratios: 1.0, 2.78, 5.41, 8.93, 13.3, ...

    Good for: typewriter typebar arms, telegraph sounder, wooden
    cabinet resonances.
    """
    if rng is None:
        rng = np.random.RandomState(42)

    bar_ratios = [1.0, 2.78, 5.41, 8.93, 13.3, 18.4]
    amp_rolloff = 0.50
    base_decay = 500.0

    modes = []
    for k in range(min(n_modes, len(bar_ratios))):
        ratio = bar_ratios[k]; f_k = f0 * ratio; f_k += rng.randint(-int(f0 * 0.005), int(f0 * 0.005) + 1); amp = amp_rolloff ** k; decay = base_decay * (1.0 + 0.5 * k); phase = rng.uniform(0, 2 * np.pi)
        modes.append((f_k, amp, decay, phase))

    return modes

def _bell_modes(f0: float, n_modes=7,
                 rng: np.random.RandomState = None) -> List[Tuple[float, float, float, float]]:
    """Generate vibration mode frequencies for a bell/chime.

    Real bells have partials at approximately:
    Hum : 0.5 * f0
    Prime : 1.0 * f0
    Minor Third : 1.2 * f0
    Fifth : 1.5 * f0
    Nominal : 2.0 * f0
    Decieme : 2.5 * f0
    Undecime : 3.0 * f0

    Good for: typewriter bell, cash register ding, arcade chime.
    """
    if rng is None:
        rng = np.random.RandomState(42)

    bell_ratios = [0.5, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 3.8]
    bell_amps = [0.35, 0.60, 0.25, 0.20, 0.40, 0.15, 0.10, 0.06]
    base_decay = 4.0  # bells ring for a LONG time

    modes = []
    for k in range(min(n_modes, len(bell_ratios))):
        f_k = f0 * bell_ratios[k]; f_k += rng.randint(-int(f0 * 0.003), int(f0 * 0.003) + 1); amp = bell_amps[k] if k < len(bell_amps) else 0.05; decay = base_decay * (1.0 + 1.5 * k)
        phase = rng.uniform(0, 2 * np.pi); modes.append((f_k, amp, decay, phase))

    return modes

def _noise_excited_resonator(n: int, rng: np.random.RandomState,
                              center_freq: float, bandwidth: float,
                              q: float = 5.0, sr: int = 44100,
                              excitation_decay: float = 200.0) -> np.ndarray:
    """Noise-excited resonant body model.

    Physically-motivated model: a short noise burst (the "hit")
    excites a resonant system (the "body"), which rings at its
    natural frequency.  This is how real acoustic impacts work:

    1. Impact creates broadband energy (noise burst)
    2. The body's resonances filter this energy
    3. The body rings at its natural frequencies, decaying over time

    This produces much more natural results than separately adding
    a sine wave and noise, because the spectral content of the
    resonance is *shaped by the excitation*.

    Parameters
    ----------
    center_freq     : resonant frequency (Hz)
    bandwidth       : spectral width of excitation noise (Hz, 0 = DC)
    q               : resonance sharpness (higher = more ringing)
    excitation_decay: how fast the excitation noise dies (1/s)
    """
    t = np.arange(n, dtype=np.float64) / sr

    if bandwidth > 0:
        noise = rng.randn(n).astype(np.float64); spectrum = np.fft.rfft(noise); freqs = np.fft.rfftfreq(n, 1.0 / sr); sigma = max(bandwidth, 100.0)
        excitation_envelope = np.exp(-0.5 * ((freqs - center_freq) / sigma) ** 2); excitation_envelope += 0.3 * np.exp(-0.5 * (freqs / (center_freq * 0.5)) ** 2); spectrum *= excitation_envelope
        noise = np.fft.irfft(spectrum, n=n)
    else:
        noise = rng.randn(n).astype(np.float64)

    attack_samples = min(int(0.0005 * sr), n)
    if attack_samples > 1:
        noise[:attack_samples] *= np.linspace(0, 1, attack_samples) ** 0.5

    noise *= np.exp(-t * excitation_decay)

    resonant = _svf_filter(noise, center_freq, q, sr, mode='bp')
    body_thud = _svf_filter(noise, center_freq * 0.25, 0.707, sr, mode='lp') * 0.3

    return resonant + body_thud

def _comb_filter(signal: np.ndarray, delay_ms: float, feedback=0.5,
                  sr: int = 44100) -> np.ndarray:
    """Comb filter for metallic resonance and early reflections.

    A comb filter creates evenly-spaced frequency peaks (like the
    teeth of a comb), which is exactly what happens when sound
    bounces between two parallel surfaces.  This is useful for:

    * Adding metallic "tube" resonance to sounds
    * Creating early reflection patterns for reverb
    * Simulating string-like resonance without full KS

    Parameters
    ----------
    delay_ms : comb delay in milliseconds
    feedback : feedback gain (0-1, higher = more resonance/ringing)
    """
    feedback = min(feedback, 0.95)  # safety clamp to prevent runaway
    n = len(signal)
    if n == 0 or delay_ms <= 0:
        return signal.astype(np.float64)

    delay_samples = int(delay_ms * sr / 1000)
    if delay_samples >= n:
        return signal.astype(np.float64)

    x = signal.astype(np.float64)
    y = np.zeros(n, dtype=np.float64)

    for i in range(n):
        delayed = x[i - delay_samples] if i >= delay_samples else 0.0; y[i] = x[i] + feedback * delayed

    return y

def _allpass_diffusion(signal: np.ndarray, delay_ms=5.0,
                        feedback: float = 0.6, sr: int = 44100) -> np.ndarray:
    """Schroeder allpass diffuser for reverb tail diffusion.

    Allpass filters pass all frequencies equally (hence "allpass")
    but delay the phase in a frequency-dependent way.  When used
    in series, they "diffuse" the reverb tail, turning discrete
    echoes into a smooth wash of sound.

    This is a standard building block in algorithmic reverb design.
    """
    n = len(signal)
    if n == 0 or delay_ms <= 0:
        return signal.astype(np.float64)

    delay_samples = max(1, int(delay_ms * sr / 1000))
    x = signal.astype(np.float64)
    y = np.zeros(n, dtype=np.float64)
    buffer = np.zeros(delay_samples, dtype=np.float64)
    buf_pos = 0

    for i in range(n):
        delayed = buffer[buf_pos]; y[i] = -feedback * x[i] + delayed; buffer[buf_pos] = x[i] + feedback * delayed; buf_pos = (buf_pos + 1) % delay_samples

    return y

def _frequency_sweep(duration: float, f_start: float, f_end: float,
                      sr: int = 44100, phase_offset: float = 0.0) -> np.ndarray:
    """Generate a sinusoidal frequency sweep with proper phase continuity.

    Uses cumulative phase integration (not naive freq*t) to avoid
    phase discontinuities that cause audible clicks.

    Parameters
    ----------
    f_start, f_end : start and end frequencies (Hz)
    phase_offset   : initial phase (radians)
    """
    n = int(duration * sr)
    t = np.arange(n, dtype=np.float64) / sr
    freq = np.linspace(f_start, f_end, n)
    phase = phase_offset + 2 * np.pi * np.cumsum(freq) / sr
    return np.sin(phase)

_KEY_POSITIONS: Dict[str, float] = {}
_QWERTY_ROWS = [
    list("`1234567890-="),
    list("qwertyuiop[]\\"),
    list("asdfghjkl;'"),
    list("zxcvbnm,./"),
    [" "],
]
for _row_idx, _row in enumerate(_QWERTY_ROWS):
    for _col_idx, _ch in enumerate(_row):
        if len(_row) <= 1:
            _KEY_POSITIONS[_ch] = 0.0
        else:
            _KEY_POSITIONS[_ch] = -1.0 + 2.0 * _col_idx / (len(_row) - 1)

class TypingSoundGenerator:
    """Generate and mix procedural keyboard typing sounds."""

    PROFILES = ("Mechanical", "Typewriter", "Soft Membrane", "Laptop Chiclet", "Topre Electrostatic", "Custom Linear", "Cash Register", "Pinball", "Telegraph", "Arcade Button", "Gunshot", "Gunshot Silenced", "Crystal Singing Bowl", "Synth Bubble", "Tibetan Bowl")

    SOUND_CATEGORIES = ("key", "space", "enter", "backspace", "tab", "quote", "bracket", "digit", "modifier", "punctuation", "escape")

    @staticmethod
    def _to_int16(out):
        """Clip and convert float signal to normalised int16."""
        peak = float(np.max(np.abs(np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0))))
        if peak < 1e-10:
            return np.zeros(len(out), dtype=np.int16)
        target = 32767 * 10 ** (-3.0 / 20)
        scale = target / peak
        return np.clip(out * scale, -32768, 32767).astype(np.int16)
    def _rb_sum(self, v, dur, voff, bodies, nfl, nfh, ntilt, ndec, namp, hp=0.015):
        """Sum of _resonant_body calls + shaped noise + highpass + to_int16."""
        sr = self.sample_rate; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + voff); out = sum(_resonant_body(t, rng=rng, **kw) * a for kw, a in bodies)
        ns = _noise_shaped(n, rng, nfl, nfh, sr, tilt_db=ntilt); out = out + ns * np.exp(-t * ndec) * namp
        return self._to_int16(_highpass(out, hp))

    _CATEGORY_MAPS: Dict[str, Dict[str, str]] = { "Mechanical": {}, "Typewriter": {}, "Soft Membrane": {}, "Laptop Chiclet": {}, "Topre Electrostatic": {}, "Custom Linear": {}, "Cash Register": { "\n": "jackpot", " ": "coin", "\t": "coin_tray", "\x1b": "drawer_slam", "\b": "receipt_tear", "'\"`": "small_item", "()[]{}": "med_item", "digit": "beep", ".;:,!?": "scanner", }, "Pinball": { "\n": "multiplier", " ": "plunger", "\t": "tilt", "\x1b": "drain", "\b": "flipper", "'\"`": "bumper_a", "()[]{}": "bumper_b", "digit": "bumper_c", ".;:,!?": "target", }, "Telegraph": { "\n": "dash", " ": "long_gap", "\t": "repeater_click", "\x1b": "end_transmission", "\b": "correction", "'\"`": "dot", "()[]{}": "dash", "digit": "dot", ".;:,!?": "dot", }, "Arcade Button": { "\n": "start_coin", " ": "punch", "\t": "macro", "\x1b": "insert_coin", "\b": "delete_buzz", "'\"`": "a_btn", "()[]{}": "b_btn", "digit": "a_btn", ".;:,!?": "b_btn", }, "Gunshot": { "\n": "shotgun", " ": "rifle", "\t": "burst", "\x1b": "cannon", "\b": "silenced_hit", "'\"`": "pistol", "()[]{}": "revolver", "digit": "pistol", ".;:,!?": "revolver", }, "Gunshot Silenced": { "\n": "heavy_thump", " ": "medium_thump", "\t": "triple_tap", "\x1b": "deep_boom", "\b": "gas_leak", "'\"`": "soft_pfft", "()[]{}": "low_pop", "digit": "soft_pfft", ".;:,!?": "low_pop", }, "Crystal Singing Bowl": { "\n": "full_bowl", " ": "deep_ring", "\t": "shimmer_sweep", "\x1b": "dissonant", "\b": "fade_out", "'\"`": "harmonic_a", "()[]{}": "harmonic_b", "digit": "chime", ".;:,!?": "sparkle", }, "Synth Bubble": { "\n": "whoosh", " ": "deep_bubble", "\t": "squelch_sweep", "\x1b": "glitch", "\b": "deflate", "'\"`": "bubble_a", "()[]{}": "bubble_b", "digit": "blip", ".;:,!?": "squelch", }, "Tibetan Bowl": { "\n": "large_bowl", " ": "bass_bowl", "\t": "harmonic_tap", "\x1b": "deep_gong", "\b": "mallet_damp", "'\"`": "overtone_a", "()[]{}": "overtone_b", "digit": "small_bell", ".;:,!?": "rim_tap", },
    }

    _EXTRA_CATEGORIES: Dict[str, Tuple[str, ...]] = { "Cash Register": ("jackpot", "coin", "coin_tray", "drawer_slam", "receipt_tear", "small_item", "med_item", "beep", "scanner"), "Pinball": ("multiplier", "plunger", "tilt", "drain", "flipper", "bumper_a", "bumper_b", "bumper_c", "target"), "Telegraph": ("dash", "long_gap", "repeater_click", "end_transmission", "correction", "dot"), "Arcade Button": ("start_coin", "punch", "macro", "insert_coin", "delete_buzz", "a_btn", "b_btn"), "Gunshot": ("shotgun", "rifle", "burst", "cannon", "silenced_hit", "pistol", "revolver"), "Gunshot Silenced": ("heavy_thump", "medium_thump", "triple_tap", "deep_boom", "gas_leak", "soft_pfft", "low_pop"), "Crystal Singing Bowl": ("full_bowl", "deep_ring", "shimmer_sweep", "dissonant", "fade_out", "harmonic_a", "harmonic_b", "chime", "sparkle"), "Synth Bubble": ("whoosh", "deep_bubble", "squelch_sweep", "glitch", "deflate", "bubble_a", "bubble_b", "blip", "squelch"), "Tibetan Bowl": ("large_bowl", "bass_bowl", "harmonic_tap", "deep_gong", "mallet_damp", "overtone_a", "overtone_b", "small_bell", "rim_tap"),
    }

    def __init__(self, sample_rate=44100, profile: str = "Mechanical") -> None:
        self.logger = logging.getLogger("TypingSoundGenerator")
        if profile not in self.PROFILES:
            self.logger.warning("Unknown profile %r; falling back to 'Mechanical'", profile); profile = "Mechanical"
        self.sample_rate = sample_rate; self.profile = profile
        self.sounds: Dict[str, List[np.ndarray]] = {}; self._generate_all()

    def _generate_all(self):
        """Build the full per-category sound bank for the active profile."""
        builders = self._profile_builders(); self.sounds = {}
        for category, (fn, n_variants) in builders.items():
            self.sounds[category] = [fn(i) for i in range(n_variants)]

    def _profile_builders(self):
        """Return a dict of {category: (builder_fn, n_variants)}."""
        p = self.profile
        _dispatch = { "Mechanical": self._mech_builders, "Typewriter": self._typewriter_builders, "Soft Membrane": self._membrane_builders, "Laptop Chiclet": self._chiclet_builders, "Topre Electrostatic": self._topre_builders, "Custom Linear": self._linear_builders, "Cash Register": self._cashreg_builders, "Pinball": self._pinball_builders, "Telegraph": self._telegraph_builders, "Arcade Button": self._arcade_builders, "Gunshot": self._gunshot_builders, "Crystal Singing Bowl": self._crystal_bowl_builders, "Synth Bubble": self._synth_bubble_builders, "Tibetan Bowl": self._tibetan_bowl_builders,
        }
        return _dispatch.get(p, self._silenced_builders)()

    def _mech_builders(self):
        return { "key":         (self._mech_click, 8), "space":       (self._mech_space, 4), "enter":       (self._mech_enter, 4), "backspace":   (self._mech_backspace, 4), "tab":         (self._mech_tab, 4), "quote":       (self._mech_quote, 4), "bracket":     (self._mech_bracket, 4), "digit":       (self._mech_digit, 4), "modifier":    (self._mech_modifier, 4), "punctuation": (self._mech_punctuation, 4), "escape":      (self._mech_escape, 4),
        }

    def _mech_click(self, v=0, dur=0.08):
        sr, n = self.sample_rate, int(self.sample_rate * 0.08); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v); pitch = 1.0 + (v - 3.5) * 0.05
        impact = _noise_excited_resonator(n, rng, center_freq=4500 * pitch, bandwidth=8000, q=3.0, sr=sr, excitation_decay=1500) * 0.10
        impact = _shape_attack(impact, attack_ms=0.3, hardness=3.0); click = _fm_click(t, f_carrier=3400 * pitch, f_mod=1800 * pitch, mod_index=2.5, rng=rng, decay=450, detune=250)
        click *= _env_adsr(t, 0.0003, 0.015, 0.1, 0.03) * 0.32; ks_spring = _karplus_strong(5400 * pitch, dur * 0.7, sr, brightness=0.25, damping=0.7, rng=rng); ks_len = min(len(ks_spring), n)
        spring = np.zeros(n, dtype=np.float64); spring[:ks_len] = ks_spring[:ks_len]; spring *= _env_adsr(t, 0.001, 0.01, 0.05, 0.02) * 0.14
        spring = _comb_filter(spring, delay_ms=0.18, feedback=0.35, sr=sr) * 0.12; body_modes = _wood_bar_modes(360 * pitch, n_modes=5, rng=rng)
        thock = _modal_impact(n, rng, body_modes, sr, noise_mix=0.08, noise_decay=600) * 0.45; res_modes = _wood_bar_modes(700 * pitch, n_modes=3, rng=rng)
        res2 = _modal_impact(n, rng, res_modes, sr, noise_mix=0.05, noise_decay=500) * 0.10; rattle = _svf_resonant_noise(n, rng, freq=3500 * pitch, q=4.0, sr=sr, decay=350) * 0.08
        thud = _noise_excited_resonator(n, rng, center_freq=130 * pitch, bandwidth=300, q=2.0, sr=sr, excitation_decay=500) * 0.20
        thud *= _env_adsr(t, 0.010, 0.02, 0.08, 0.04, delay=0.012); out = impact + click + spring + thock + res2 + rattle + thud; out = _svf_filter(out, 330, 0.707, sr, mode='hp')
        out = _spectral_tilt(out, sr, tilt_db_oct=-2.0); out = _svf_filter(out, 9200, 1.0, sr, mode='lp'); return self._to_int16(out)

    def _mech_space(self, v=0):
        sr, dur = self.sample_rate, 0.11; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 100); rattle = _noise_shaped(n, rng, 1800, 4500, sr, tilt_db=-3.0)
        rattle *= np.exp(-t * 200) * 0.18; res = _resonant_body(t, f0=200, rng=rng, n_partials=5, decay_base=120, inharmonicity=0.003, delay=0.015, amplitude_rolloff=0.50) * 0.60
        thud = _resonant_body(t, f0=85, rng=rng, n_partials=3, decay_base=100, inharmonicity=0.002, delay=0.018, amplitude_rolloff=0.45) * 0.45
        click = _fm_click(t, f_carrier=2200, f_mod=1100, mod_index=2.0, rng=rng, decay=300, detune=200); click *= _env_adsr(t, 0.0003, 0.015, 0.08, 0.03) * 0.20; out = rattle + res + thud + click
        out = _highpass(out, 0.015); out = _spectral_tilt(out, sr, tilt_db_oct=-2.0); return self._to_int16(out)

    def _mech_enter(self, v=0):
        sr, dur = self.sample_rate, 0.10; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 200)
        click = _fm_click(t, f_carrier=2000, f_mod=1000, mod_index=2.5, rng=rng, decay=400, detune=180); click *= _env_adsr(t, 0.0003, 0.012, 0.08, 0.03) * 0.40
        res = _resonant_body(t, f0=160, rng=rng, n_partials=5, decay_base=130, inharmonicity=0.003, delay=0.010, amplitude_rolloff=0.50) * 0.65
        thud = _resonant_body(t, f0=70, rng=rng, n_partials=3, decay_base=110, inharmonicity=0.002, delay=0.016, amplitude_rolloff=0.45) * 0.50
        rattle = _noise_shaped(n, rng, 2000, 5000, sr, tilt_db=-3.0); rattle *= np.exp(-t * 280) * 0.12; out = click + res + thud + rattle; out = _highpass(out, 0.015)
        out = _spectral_tilt(out, sr, tilt_db_oct=-2.0); return self._to_int16(out)

    def _mech_backspace(self, v=0):
        sr, dur = self.sample_rate, 0.065; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 300); pitch = 1.12 + (v - 1.5) * 0.04
        click = _fm_click(t, f_carrier=3800 * pitch, f_mod=1900 * pitch, mod_index=2.8, rng=rng, decay=480, detune=250); click *= _env_adsr(t, 0.0003, 0.012, 0.08, 0.02) * 0.38
        thock = _resonant_body(t, f0=440 * pitch, rng=rng, n_partials=5, decay_base=150, inharmonicity=0.003, delay=0.005, amplitude_rolloff=0.50) * 0.35
        spring = _spring_model_v2(t, 5600 * pitch, 900, rng, 150, n_partials=4, sr=sr) * 0.10; rattle = _noise_shaped(n, rng, 2800, 5500, sr, tilt_db=-3.0); rattle *= np.exp(-t * 400) * 0.08
        out = click + thock + spring + rattle; out = _highpass(out, 0.015); out = _spectral_tilt(out, sr, tilt_db_oct=-2.0); return self._to_int16(out)

    def _mech_tab(self, v=0):
        sr, dur = self.sample_rate, 0.07; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 400)
        click = _fm_click(t, f_carrier=2600, f_mod=1300, mod_index=2.2, rng=rng, decay=420, detune=200); click *= _env_adsr(t, 0.0003, 0.015, 0.08, 0.03) * 0.35
        thock = _resonant_body(t, f0=340, rng=rng, n_partials=5, decay_base=140, inharmonicity=0.003, delay=0.008, amplitude_rolloff=0.50) * 0.42
        rattle = _noise_shaped(n, rng, 2200, 4800, sr, tilt_db=-3.0); rattle *= np.exp(-t * 350) * 0.09; out = click + thock + rattle; out = _highpass(out, 0.015)
        out = _spectral_tilt(out, sr, tilt_db_oct=-2.0); return self._to_int16(out)

    def _mech_quote(self, v=0):
        sr, dur = self.sample_rate, 0.065; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 500)
        click = _fm_click(t, f_carrier=2800, f_mod=1400, mod_index=2.0, rng=rng, decay=450, detune=200); click *= _env_adsr(t, 0.0004, 0.018, 0.08, 0.03) * 0.28
        thock = _resonant_body(t, f0=360, rng=rng, n_partials=5, decay_base=145, inharmonicity=0.003, delay=0.008, amplitude_rolloff=0.50) * 0.40
        rattle = _noise_shaped(n, rng, 2000, 4500, sr, tilt_db=-3.0); rattle *= np.exp(-t * 320) * 0.07; out = click + thock + rattle; out = _highpass(out, 0.015)
        out = _spectral_tilt(out, sr, tilt_db_oct=-2.0); return self._to_int16(out)

    def _mech_bracket(self, v=0):
        sr, dur = self.sample_rate, 0.065; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 600)
        click = _fm_click(t, f_carrier=3400, f_mod=1700, mod_index=2.5, rng=rng, decay=380, detune=200); click *= _env_adsr(t, 0.0003, 0.012, 0.06, 0.02) * 0.30
        ks_ring = _karplus_strong(5200, dur * 0.6, sr, brightness=0.2, damping=0.65, rng=rng); ks_len = min(len(ks_ring), n); ring = np.zeros(n, dtype=np.float64); ring[:ks_len] = ks_ring[:ks_len]
        ring = _comb_filter(ring, delay_ms=0.15, feedback=0.40, sr=sr) * 0.16
        thock = _resonant_body(t, f0=400, rng=rng, n_partials=5, decay_base=145, inharmonicity=0.003, delay=0.006, amplitude_rolloff=0.50) * 0.42
        out = click + ring + thock; out = _highpass(out, 0.015); out = _spectral_tilt(out, sr, tilt_db_oct=-2.0); return self._to_int16(out)

    def _mech_digit(self, v=0):
        sr, dur = self.sample_rate, 0.065; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 700); pitch = 1.08 + (v - 1.5) * 0.03
        click = _fm_click(t, f_carrier=3500 * pitch, f_mod=1750 * pitch, mod_index=2.4, rng=rng, decay=440, detune=220); click *= _env_adsr(t, 0.0003, 0.014, 0.08, 0.03) * 0.32
        thock = _resonant_body(t, f0=420 * pitch, rng=rng, n_partials=5, decay_base=145, inharmonicity=0.003, delay=0.008, amplitude_rolloff=0.50) * 0.44
        rattle = _noise_shaped(n, rng, 2200, 5000, sr, tilt_db=-3.0); rattle *= np.exp(-t * 320) * 0.08; out = click + thock + rattle; out = _highpass(out, 0.015)
        out = _spectral_tilt(out, sr, tilt_db_oct=-2.0); return self._to_int16(out)

    def _mech_modifier(self, v=0):
        sr, dur = self.sample_rate, 0.04; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 800)
        click = _fm_click(t, f_carrier=2400, f_mod=1200, mod_index=2.0, rng=rng, decay=550, detune=180); click *= _env_adsr(t, 0.0002, 0.010, 0.06, 0.02) * 0.22
        rattle = _noise_shaped(n, rng, 2500, 5000, sr, tilt_db=-3.0); rattle *= np.exp(-t * 500) * 0.06; out = click + rattle; out = _highpass(out, 0.015); out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return self._to_int16(out)

    def _mech_punctuation(self, v=0):
        """Period, comma, colon, semicolon — slightly softer than letters."""
        sr, dur = self.sample_rate, 0.065; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 900)
        click = _fm_click(t, f_carrier=3000, f_mod=1500, mod_index=2.2, rng=rng, decay=460, detune=200); click *= _env_adsr(t, 0.0004, 0.016, 0.08, 0.03) * 0.28
        thock = _resonant_body(t, f0=370, rng=rng, n_partials=5, decay_base=140, inharmonicity=0.003, delay=0.008, amplitude_rolloff=0.50) * 0.42
        rattle = _noise_shaped(n, rng, 2200, 4800, sr, tilt_db=-3.0); rattle *= np.exp(-t * 340) * 0.07; out = click + thock + rattle; out = _highpass(out, 0.015)
        out = _spectral_tilt(out, sr, tilt_db_oct=-2.0); return self._to_int16(out)

    def _mech_escape(self, v=0):
        """Escape key — top-left position, slightly different resonance."""
        sr, dur = self.sample_rate, 0.07; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 950)
        click = _fm_click(t, f_carrier=3200, f_mod=1600, mod_index=2.3, rng=rng, decay=430, detune=200); click *= _env_adsr(t, 0.0003, 0.014, 0.06, 0.03) * 0.30
        res = _resonant_body(t, f0=480, rng=rng, n_partials=4, decay_base=160, inharmonicity=0.002, delay=0.006, amplitude_rolloff=0.50) * 0.45
        spring = _spring_model_v2(t, 5800, 800, rng, 200, n_partials=4, sr=sr) * 0.12; out = click + res + spring; out = _highpass(out, 0.015); out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return self._to_int16(out)

    def _typewriter_builders(self):
        return { "key":         (self._typewriter_click, 8), "space":       (self._typewriter_space, 4), "enter":       (self._typewriter_enter, 4), "backspace":   (self._typewriter_backspace, 4), "tab":         (self._typewriter_tab, 4), "quote":       (self._typewriter_quote, 4), "bracket":     (self._typewriter_bracket, 4), "digit":       (self._typewriter_digit, 4), "modifier":    (self._typewriter_modifier, 4), "punctuation": (self._typewriter_punctuation, 4), "escape":      (self._typewriter_modifier, 4),  # alias
        }

    def _typewriter_click(self, v=0):
        sr, dur = self.sample_rate, 0.10; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v); pitch = 1.0 + (v - 3.5) * 0.04
        ks_strike = _karplus_strong(4800 * pitch, dur * 0.8, sr, brightness=0.3, damping=0.55, rng=rng); ks_len = min(len(ks_strike), n); strike = np.zeros(n, dtype=np.float64)
        strike[:ks_len] = ks_strike[:ks_len]; fm_crack = _fm_click(t, f_carrier=4800 * pitch, f_mod=2400 * pitch, mod_index=2.0, rng=rng, decay=800, detune=300)
        strike += fm_crack * _env_adsr(t, 0.0002, 0.005, 0.05, 0.02) * 0.25; strike *= _env_adsr(t, 0.0002, 0.008, 0.15, 0.04) * 0.50; bar_modes = _wood_bar_modes(1100 * pitch, n_modes=4, rng=rng)
        ring = _modal_impact(n, rng, bar_modes, sr, noise_mix=0.06, noise_decay=400) * 0.35; ring *= _env_adsr(t, 0.002, 0.01, 0.15, 0.04, delay=0.002)
        clack = _noise_excited_resonator(n, rng, center_freq=780, bandwidth=2000, q=3.5, sr=sr, excitation_decay=350) * 0.20; noise = _noise_shaped(n, rng, 400, 7000, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 220) * 0.15; out = strike + ring + clack + noise; out = _svf_filter(out, 330, 0.707, sr, mode='hp'); out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return self._to_int16(out)

    def _typewriter_space(self, v=0):
        sr, dur = self.sample_rate, 0.12; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 100)
        ks_s = _karplus_strong(3200, dur * 0.7, sr, brightness=0.35, damping=0.6, rng=rng); ks_l = min(len(ks_s), n); strike = np.zeros(n, dtype=np.float64); strike[:ks_l] = ks_s[:ks_l]
        fm_c = _fm_click(t, f_carrier=3200, f_mod=1600, mod_index=2.0, rng=rng, decay=600, detune=200); strike += fm_c * _env_adsr(t, 0.0003, 0.005, 0.05, 0.02) * 0.20
        strike *= _env_adsr(t, 0.0003, 0.01, 0.15, 0.04) * 0.40; ring = _resonant_body(t, f0=780, rng=rng, n_partials=4, decay_base=90, inharmonicity=0.002, delay=0.005, amplitude_rolloff=0.45) * 0.55
        noise = _noise_shaped(n, rng, 300, 6000, sr, tilt_db=-9.0); noise *= np.exp(-t * 130) * 0.18; out = strike + ring + noise; out = _highpass(out, 0.015); out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return self._to_int16(out)

    def _typewriter_enter(self, v=0):
        sr, dur = self.sample_rate, 0.20; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 200)
        sweep = _frequency_sweep(dur, 1400 + rng.randint(-100, 100), 500, sr) * np.exp(-t * 28) * 0.30; bell = _bell_modes(2400 + rng.randint(-80, 80), n_modes=7, rng=rng)
        ding = _modal_impact(n, rng, bell, sr, noise_mix=0.03, noise_decay=50) * 0.6; ding *= _env_adsr(t, 0.001, 0.01, 0.6, 0.12, delay=0.05); noise = _noise_shaped(n, rng, 200, 5000, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 45) * 0.12; out = sweep + ding + noise; out = _highpass(out, 0.015); out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return self._to_int16(out)

    def _typewriter_backspace(self, v=0):
        sr, dur = self.sample_rate, 0.08; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 300)
        strike = _fm_click(t, f_carrier=4400, f_mod=2200, mod_index=3.0, rng=rng, decay=600, detune=300); strike *= _env_adsr(t, 0.0002, 0.008, 0.12, 0.03) * 0.45
        ring = _resonant_body(t, f0=1050, rng=rng, n_partials=4, decay_base=110, inharmonicity=0.002, delay=0.002, amplitude_rolloff=0.45) * 0.35
        noise = _noise_shaped(n, rng, 400, 7000, sr, tilt_db=-9.0); noise *= np.exp(-t * 260) * 0.12; out = strike + ring + noise; out = _highpass(out, 0.015); out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return self._to_int16(out)

    def _typewriter_tab(self, v=0):
        sr, dur = self.sample_rate, 0.10; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 400)
        strike = _fm_click(t, f_carrier=1500, f_mod=750, mod_index=2.5, rng=rng, decay=55, detune=150); strike *= np.exp(-t * 55) * 0.38; noise = _noise_shaped(n, rng, 300, 6000, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 100) * 0.12; out = strike + noise; out = _highpass(out, 0.015); out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return self._to_int16(out)

    def _typewriter_quote(self, v=0):
        sr, dur = self.sample_rate, 0.09; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 500)
        strike = _fm_click(t, f_carrier=4500, f_mod=2250, mod_index=3.0, rng=rng, decay=580, detune=300); strike *= _env_adsr(t, 0.0002, 0.010, 0.12, 0.03) * 0.42
        ring = _resonant_body(t, f0=1100, rng=rng, n_partials=4, decay_base=110, inharmonicity=0.002, amplitude_rolloff=0.45) * 0.30
        noise = _noise_shaped(n, rng, 400, 7000, sr, tilt_db=-9.0); noise *= np.exp(-t * 250) * 0.10; out = strike + ring + noise; out = _highpass(out, 0.015); out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return self._to_int16(out)

    def _typewriter_bracket(self, v=0):
        sr, dur = self.sample_rate, 0.09; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 600)
        strike = _fm_click(t, f_carrier=4700, f_mod=2350, mod_index=3.2, rng=rng, decay=560, detune=300); strike *= _env_adsr(t, 0.0002, 0.009, 0.10, 0.03) * 0.45
        ring = _resonant_body(t, f0=1250, rng=rng, n_partials=4, decay_base=105, inharmonicity=0.002, amplitude_rolloff=0.45) * 0.35
        noise = _noise_shaped(n, rng, 400, 7000, sr, tilt_db=-9.0); noise *= np.exp(-t * 240) * 0.12; out = strike + ring + noise; out = _highpass(out, 0.015); out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return self._to_int16(out)

    def _typewriter_digit(self, v=0):
        sr, dur = self.sample_rate, 0.09; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 700)
        strike = _fm_click(t, f_carrier=4500, f_mod=2250, mod_index=3.0, rng=rng, decay=580, detune=300); strike *= _env_adsr(t, 0.0002, 0.009, 0.12, 0.03) * 0.48
        ring = _resonant_body(t, f0=1200, rng=rng, n_partials=4, decay_base=100, inharmonicity=0.002, amplitude_rolloff=0.45) * 0.38
        noise = _noise_shaped(n, rng, 400, 7000, sr, tilt_db=-9.0); noise *= np.exp(-t * 230) * 0.13; out = strike + ring + noise; out = _highpass(out, 0.015); out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return self._to_int16(out)

    def _typewriter_modifier(self, v=0):
        sr, dur = self.sample_rate, 0.05; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 800)
        strike = _fm_click(t, f_carrier=4000, f_mod=2000, mod_index=2.5, rng=rng, decay=600, detune=250); strike *= np.exp(-t * 600) * 0.30; noise = _noise_shaped(n, rng, 400, 7000, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 280) * 0.08; out = strike + noise; out = _highpass(out, 0.015); out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return self._to_int16(out)

    def _typewriter_punctuation(self, v=0):
        sr, dur = self.sample_rate, 0.09; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 900)
        strike = _fm_click(t, f_carrier=4600, f_mod=2300, mod_index=3.0, rng=rng, decay=580, detune=300); strike *= _env_adsr(t, 0.0002, 0.010, 0.10, 0.03) * 0.40
        ring = _resonant_body(t, f0=1150, rng=rng, n_partials=4, decay_base=110, inharmonicity=0.002, amplitude_rolloff=0.45) * 0.32
        noise = _noise_shaped(n, rng, 400, 7000, sr, tilt_db=-9.0); noise *= np.exp(-t * 250) * 0.10; out = strike + ring + noise; out = _highpass(out, 0.015); out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return self._to_int16(out)

    def _membrane_builders(self):
        b = self
        return { "key":         (b._membrane_click, 8), "space":       (b._membrane_space, 4), "enter":       (b._membrane_enter, 4), "backspace":   (b._membrane_backspace, 4), "tab":         (b._membrane_tab, 4), "quote":       (b._membrane_quote, 4), "bracket":     (b._membrane_bracket, 4), "digit":       (b._membrane_digit, 4), "modifier":    (b._membrane_modifier, 4), "punctuation": (b._membrane_punctuation, 4), "escape":      (b._membrane_modifier, 4),
        }

    def _membrane_click(self, v=0):
        sr, dur = self.sample_rate, 0.065; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v); pitch = 1.0 + (v - 3.5) * 0.03
        thud = _resonant_body(t, f0=200 * pitch, rng=rng, n_partials=3, decay_base=180, inharmonicity=0.005, amplitude_rolloff=0.45) * 0.60
        f_click = 1400 + rng.randint(-100, 100); click = np.sin(2 * np.pi * f_click * t) * np.exp(-t * 420) * 0.15; noise = _noise_shaped(n, rng, 100, 4000, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 180) * 0.22; out = thud + click + noise; out = _highpass(out, 0.015)
        return self._to_int16(out)

    def _membrane_space(self, v=0):
        return self._rb_sum(v, 0.075, 100, [({'f0': 120, 'n_partials': 2, 'decay_base': 140, 'inharmonicity': 0.005, 'delay': 0.008, 'amplitude_rolloff': 0.4}, 0.7)], 80, 3000, -9.0, 90, 0.25)
    def _membrane_enter(self, v=0):
        return self._rb_sum(v, 0.085, 200, [({'f0': 100, 'n_partials': 2, 'decay_base': 130, 'inharmonicity': 0.005, 'delay': 0.01, 'amplitude_rolloff': 0.4}, 0.8)], 60, 2500, -9.0, 80, 0.25)
    def _membrane_backspace(self, v=0):
        return self._rb_sum(v, 0.055, 300, [({'f0': 240, 'n_partials': 3, 'decay_base': 190, 'inharmonicity': 0.005, 'amplitude_rolloff': 0.45}, 0.55)], 120, 4500, -9.0, 240, 0.18)
    def _membrane_tab(self, v=0):
        return self._rb_sum(v, 0.06, 400, [({'f0': 180, 'n_partials': 3, 'decay_base': 170, 'inharmonicity': 0.005, 'amplitude_rolloff': 0.45}, 0.55)], 100, 4000, -9.0, 200, 0.18)
    def _membrane_quote(self, v=0):
        return self._rb_sum(v, 0.055, 500, [({'f0': 220, 'n_partials': 3, 'decay_base': 200, 'inharmonicity': 0.005, 'amplitude_rolloff': 0.45}, 0.45)], 100, 4000, -9.0, 220, 0.15)
    def _membrane_bracket(self, v=0):
        sr, dur = self.sample_rate, 0.06; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 600)
        thud = _resonant_body(t, f0=210, rng=rng, n_partials=3, decay_base=170, inharmonicity=0.005, amplitude_rolloff=0.45) * 0.50
        f_click = 1600 + rng.randint(-100, 100); click = np.sin(2 * np.pi * f_click * t) * np.exp(-t * 400) * 0.10; noise = _noise_shaped(n, rng, 100, 4000, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 210) * 0.16; out = thud + click + noise; out = _highpass(out, 0.015)
        return self._to_int16(out)

    def _membrane_digit(self, v=0):
        return self._rb_sum(v, 0.055, 700, [({'f0': 230, 'n_partials': 3, 'decay_base': 190, 'inharmonicity': 0.005, 'amplitude_rolloff': 0.45}, 0.55)], 100, 4000, -9.0, 190, 0.18)
    def _membrane_modifier(self, v=0):
        return self._rb_sum(v, 0.04, 800, [({'f0': 260, 'n_partials': 2, 'decay_base': 200, 'inharmonicity': 0.005, 'amplitude_rolloff': 0.4}, 0.35)], 120, 4500, -9.0, 280, 0.12)
    def _membrane_punctuation(self, v=0):
        return self._membrane_quote(v + 950)

    def _chiclet_builders(self):
        b = self
        return { "key":         (b._chiclet_click, 8), "space":       (b._chiclet_space, 4), "enter":       (b._chiclet_enter, 4), "backspace":   (b._chiclet_backspace, 4), "tab":         (b._chiclet_tab, 4), "quote":       (b._chiclet_quote, 4), "bracket":     (b._chiclet_bracket, 4), "digit":       (b._chiclet_digit, 4), "modifier":    (b._chiclet_modifier, 4), "punctuation": (b._chiclet_punctuation, 4), "escape":      (b._chiclet_modifier, 4),
        }

    def _chiclet_click(self, v=0):
        sr, dur = self.sample_rate, 0.05; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v); pitch = 1.0 + (v - 3.5) * 0.025
        click = _fm_click(t, f_carrier=2600 * pitch, f_mod=1300 * pitch, mod_index=1.5, rng=rng, decay=520, detune=150); click *= _env_adsr(t, 0.0002, 0.008, 0.08, 0.02) * 0.40
        thock = _resonant_body(t, f0=520 * pitch, rng=rng, n_partials=3, decay_base=200, inharmonicity=0.003, delay=0.005, amplitude_rolloff=0.50) * 0.30
        rattle = _noise_shaped(n, rng, 2500, 5500, sr, tilt_db=-3.0); rattle *= np.exp(-t * 500) * 0.10; out = click + thock + rattle; out = _highpass(out, 0.015)
        return self._to_int16(out)

    def _chiclet_space(self, v=0):
        sr, dur = self.sample_rate, 0.065; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 100)
        thud = _resonant_body(t, f0=180, rng=rng, n_partials=3, decay_base=160, inharmonicity=0.003, delay=0.008, amplitude_rolloff=0.50) * 0.55
        click = _fm_click(t, f_carrier=2200, f_mod=1100, mod_index=1.5, rng=rng, decay=520, detune=150); click *= np.exp(-t * 520) * 0.22; rattle = _noise_shaped(n, rng, 2000, 4500, sr, tilt_db=-3.0)
        rattle *= np.exp(-t * 350) * 0.10; out = thud + click + rattle; out = _highpass(out, 0.015)
        return self._to_int16(out)

    def _chiclet_enter(self, v=0):
        sr, dur = self.sample_rate, 0.065; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 200)
        thud = _resonant_body(t, f0=160, rng=rng, n_partials=3, decay_base=150, inharmonicity=0.003, delay=0.010, amplitude_rolloff=0.50) * 0.60
        click = _fm_click(t, f_carrier=2400, f_mod=1200, mod_index=1.5, rng=rng, decay=500, detune=150); click *= np.exp(-t * 500) * 0.25; rattle = _noise_shaped(n, rng, 2200, 4800, sr, tilt_db=-3.0)
        rattle *= np.exp(-t * 320) * 0.12; out = thud + click + rattle; out = _highpass(out, 0.015)
        return self._to_int16(out)

    def _chiclet_backspace(self, v=0):
        sr, dur = self.sample_rate, 0.042; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 300)
        click = _fm_click(t, f_carrier=2900, f_mod=1450, mod_index=1.5, rng=rng, decay=680, detune=150); click *= np.exp(-t * 680) * 0.36
        thock = _resonant_body(t, f0=560, rng=rng, n_partials=3, decay_base=220, inharmonicity=0.003, amplitude_rolloff=0.50) * 0.24
        out = click + thock; out = _highpass(out, 0.015); return self._to_int16(out)

    def _chiclet_tab(self, v=0):
        sr, dur = self.sample_rate, 0.048; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 400)
        click = _fm_click(t, f_carrier=2500, f_mod=1250, mod_index=1.5, rng=rng, decay=620, detune=150); click *= np.exp(-t * 620) * 0.34
        thock = _resonant_body(t, f0=480, rng=rng, n_partials=3, decay_base=220, inharmonicity=0.003, amplitude_rolloff=0.50) * 0.26
        out = click + thock; out = _highpass(out, 0.015); return self._to_int16(out)

    def _chiclet_quote(self, v=0):
        sr, dur = self.sample_rate, 0.042; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 500)
        click = _fm_click(t, f_carrier=2400, f_mod=1200, mod_index=1.5, rng=rng, decay=650, detune=150); click *= np.exp(-t * 650) * 0.30
        thock = _resonant_body(t, f0=500, rng=rng, n_partials=3, decay_base=230, inharmonicity=0.003, amplitude_rolloff=0.50) * 0.24
        out = click + thock; out = _highpass(out, 0.015); return self._to_int16(out)

    def _chiclet_bracket(self, v=0):
        sr, dur = self.sample_rate, 0.045; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 600)
        click = _fm_click(t, f_carrier=2800, f_mod=1400, mod_index=1.5, rng=rng, decay=630, detune=150); click *= np.exp(-t * 630) * 0.32
        ring = _spring_model_v2(t, 4800, 400, rng, 100, n_partials=4, sr=sr) * 0.08
        thock = _resonant_body(t, f0=540, rng=rng, n_partials=3, decay_base=220, inharmonicity=0.003, amplitude_rolloff=0.50) * 0.26
        out = click + ring + thock; out = _highpass(out, 0.015); return self._to_int16(out)

    def _chiclet_digit(self, v=0):
        sr, dur = self.sample_rate, 0.048; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 700); pitch = 1.06 + (v - 1.5) * 0.02
        click = _fm_click(t, f_carrier=2700 * pitch, f_mod=1350 * pitch, mod_index=1.5, rng=rng, decay=640, detune=150); click *= np.exp(-t * 640) * 0.34
        thock = _resonant_body(t, f0=560 * pitch, rng=rng, n_partials=3, decay_base=210, inharmonicity=0.003, amplitude_rolloff=0.50) * 0.28
        out = click + thock; out = _highpass(out, 0.015); return self._to_int16(out)

    def _chiclet_modifier(self, v=0):
        sr, dur = self.sample_rate, 0.032; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 800)
        click = _fm_click(t, f_carrier=2200, f_mod=1100, mod_index=1.5, rng=rng, decay=850, detune=150); click *= np.exp(-t * 850) * 0.24; out = click; out = _highpass(out, 0.015)
        return self._to_int16(out)

    def _chiclet_punctuation(self, v=0):
        return self._chiclet_click(v + 950)

    def _topre_builders(self):
        b = self
        return { "key":         (b._topre_click, 8), "space":       (b._topre_space, 4), "enter":       (b._topre_enter, 4), "backspace":   (b._topre_backspace, 4), "tab":         (b._topre_tab, 4), "quote":       (b._topre_quote, 4), "bracket":     (b._topre_bracket, 4), "digit":       (b._topre_digit, 4), "modifier":    (b._topre_modifier, 4), "punctuation": (b._topre_punctuation, 4), "escape":      (b._topre_escape, 4),
        }

    def _topre_click(self, v=0):
        """Topre signature: deep, satisfying thock with rubber dome."""
        sr, dur = self.sample_rate, 0.09; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v); pitch = 1.0 + (v - 3.5) * 0.03
        dome = _resonant_body(t, f0=280 * pitch, rng=rng, n_partials=4, decay_base=120, inharmonicity=0.001, delay=0.010, amplitude_rolloff=0.50) * 0.55
        comp = _resonant_body(t, f0=580 * pitch, rng=rng, n_partials=3, decay_base=150, inharmonicity=0.001, delay=0.008, amplitude_rolloff=0.40) * 0.25
        f_spring = 1800 + rng.randint(-100, 100); spring = np.sin(2 * np.pi * f_spring * t) * np.exp(-t * 300) * 0.08
        housing = _resonant_body(t, f0=160, rng=rng, n_partials=3, decay_base=110, inharmonicity=0.001, delay=0.015, amplitude_rolloff=0.45) * 0.30
        noise = _noise_shaped(n, rng, 80, 3500, sr, tilt_db=-9.0); noise *= np.exp(-t * 120) * 0.20; out = dome + comp + spring + housing + noise; out = _highpass(out, 0.010)
        return self._to_int16(out)

    def _topre_space(self, v=0):
        return self._rb_sum(v, 0.12, 100, [({'f0': 160, 'n_partials': 4, 'decay_base': 100, 'inharmonicity': 0.001, 'delay': 0.015, 'amplitude_rolloff': 0.5}, 0.65), ({'f0': 100, 'n_partials': 3, 'decay_base': 90, 'inharmonicity': 0.001, 'delay': 0.02, 'amplitude_rolloff': 0.45}, 0.35)], 60, 2500, -9.0, 80, 0.25, 0.01)
    def _topre_enter(self, v=0):
        return self._rb_sum(v, 0.1, 200, [({'f0': 140, 'n_partials': 4, 'decay_base': 95, 'inharmonicity': 0.001, 'delay': 0.015, 'amplitude_rolloff': 0.5}, 0.7), ({'f0': 90, 'n_partials': 3, 'decay_base': 85, 'inharmonicity': 0.001, 'delay': 0.018, 'amplitude_rolloff': 0.45}, 0.35)], 50, 2200, -9.0, 70, 0.22, 0.01)
    def _topre_backspace(self, v=0):
        return self._rb_sum(v, 0.07, 300, [({'f0': 300, 'n_partials': 4, 'decay_base': 120, 'inharmonicity': 0.001, 'delay': 0.008, 'amplitude_rolloff': 0.5}, 0.55), ({'f0': 600, 'n_partials': 3, 'decay_base': 200, 'inharmonicity': 0.001, 'amplitude_rolloff': 0.45}, 0.18)], 80, 4000, -9.0, 140, 0.15, 0.01)
    def _topre_tab(self, v=0):
        return self._rb_sum(v, 0.08, 400, [({'f0': 260, 'n_partials': 4, 'decay_base': 115, 'inharmonicity': 0.001, 'delay': 0.01, 'amplitude_rolloff': 0.5}, 0.55), ({'f0': 170, 'n_partials': 3, 'decay_base': 105, 'inharmonicity': 0.001, 'delay': 0.012, 'amplitude_rolloff': 0.45}, 0.3)], 80, 3500, -9.0, 130, 0.18, 0.01)
    def _topre_quote(self, v=0):
        return self._topre_click(v + 500)

    def _topre_bracket(self, v=0):
        sr, dur = self.sample_rate, 0.085; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 600)
        dome = _resonant_body(t, f0=270, rng=rng, n_partials=4, decay_base=115, inharmonicity=0.001, delay=0.010, amplitude_rolloff=0.50) * 0.52
        f_spring = 1600 + rng.randint(-100, 100); spring = np.sin(2 * np.pi * f_spring * t) * np.exp(-t * 280) * 0.10; noise = _noise_shaped(n, rng, 80, 3500, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 120) * 0.18; out = dome + spring + noise; out = _highpass(out, 0.010)
        return self._to_int16(out)

    def _topre_digit(self, v=0):
        return self._topre_click(v + 700)

    def _topre_modifier(self, v=0):
        return self._rb_sum(v, 0.05, 800, [({'f0': 320, 'n_partials': 4, 'decay_base': 140, 'inharmonicity': 0.001, 'delay': 0.006, 'amplitude_rolloff': 0.5}, 0.4)], 80, 4500, -9.0, 200, 0.12, 0.01)
    def _topre_punctuation(self, v=0):
        return self._topre_click(v + 900)

    def _topre_escape(self, v=0):
        return self._rb_sum(v, 0.07, 950, [({'f0': 290, 'n_partials': 4, 'decay_base': 120, 'inharmonicity': 0.001, 'delay': 0.008, 'amplitude_rolloff': 0.5}, 0.5), ({'f0': 580, 'n_partials': 3, 'decay_base': 220, 'inharmonicity': 0.001, 'amplitude_rolloff': 0.45}, 0.15)], 80, 4000, -9.0, 150, 0.14, 0.01)
    def _linear_builders(self):
        b = self
        return { "key":         (b._linear_click, 8), "space":       (b._linear_space, 4), "enter":       (b._linear_enter, 4), "backspace":   (b._linear_backspace, 4), "tab":         (b._linear_tab, 4), "quote":       (b._linear_quote, 4), "bracket":     (b._linear_bracket, 4), "digit":       (b._linear_digit, 4), "modifier":    (b._linear_modifier, 4), "punctuation": (b._linear_punctuation, 4), "escape":      (b._linear_escape, 4),
        }

    def _linear_click(self, v=0):
        """Smooth linear switch: no click, just a soft bottom-out thud."""
        sr, dur = self.sample_rate, 0.075; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v); pitch = 1.0 + (v - 3.5) * 0.03
        bottom = _resonant_body(t, f0=220 * pitch, rng=rng, n_partials=3, decay_base=130, inharmonicity=0.002, delay=0.008, amplitude_rolloff=0.50) * 0.55
        friction = _noise_shaped(n, rng, 2000, 6000, sr, tilt_db=-6.0); friction *= np.exp(-t * 500) * 0.06
        spring = _resonant_body(t, f0=400 * pitch, rng=rng, n_partials=3, decay_base=160, inharmonicity=0.002, delay=0.025, amplitude_rolloff=0.50) * 0.20
        housing = _resonant_body(t, f0=150, rng=rng, n_partials=3, decay_base=120, inharmonicity=0.002, delay=0.012, amplitude_rolloff=0.45) * 0.28
        noise = _noise_shaped(n, rng, 60, 3000, sr, tilt_db=-9.0); noise *= np.exp(-t * 140) * 0.15; out = bottom + friction + spring + housing + noise; out = _highpass(out, 0.015)
        return self._to_int16(out)

    def _linear_space(self, v=0):
        return self._rb_sum(v, 0.09, 100, [({'f0': 130, 'n_partials': 3, 'decay_base': 100, 'inharmonicity': 0.002, 'delay': 0.015, 'amplitude_rolloff': 0.5}, 0.65), ({'f0': 95, 'n_partials': 3, 'decay_base': 90, 'inharmonicity': 0.002, 'delay': 0.02, 'amplitude_rolloff': 0.45}, 0.3)], 50, 2500, -9.0, 80, 0.2)
    def _linear_enter(self, v=0):
        return self._rb_sum(v, 0.085, 200, [({'f0': 120, 'n_partials': 3, 'decay_base': 100, 'inharmonicity': 0.002, 'delay': 0.015, 'amplitude_rolloff': 0.5}, 0.68), ({'f0': 85, 'n_partials': 3, 'decay_base': 85, 'inharmonicity': 0.002, 'delay': 0.018, 'amplitude_rolloff': 0.45}, 0.3)], 50, 2500, -9.0, 75, 0.18)
    def _linear_backspace(self, v=0):
        return self._rb_sum(v, 0.06, 300, [({'f0': 250, 'n_partials': 3, 'decay_base': 140, 'inharmonicity': 0.002, 'delay': 0.006, 'amplitude_rolloff': 0.5}, 0.5)], 80, 3500, -9.0, 160, 0.15)
    def _linear_tab(self, v=0):
        return self._rb_sum(v, 0.07, 400, [({'f0': 200, 'n_partials': 3, 'decay_base': 125, 'inharmonicity': 0.002, 'delay': 0.01, 'amplitude_rolloff': 0.5}, 0.52), ({'f0': 420, 'n_partials': 3, 'decay_base': 160, 'inharmonicity': 0.002, 'delay': 0.02, 'amplitude_rolloff': 0.5}, 0.18)], 80, 3500, -9.0, 140, 0.15)
    def _linear_quote(self, v=0):
        return self._linear_click(v + 500)

    def _linear_bracket(self, v=0):
        return self._rb_sum(v, 0.075, 600, [({'f0': 230, 'n_partials': 3, 'decay_base': 125, 'inharmonicity': 0.002, 'delay': 0.01, 'amplitude_rolloff': 0.5}, 0.5), ({'f0': 440, 'n_partials': 3, 'decay_base': 200, 'inharmonicity': 0.002, 'amplitude_rolloff': 0.5}, 0.12)], 80, 3500, -9.0, 140, 0.14)
    def _linear_digit(self, v=0):
        return self._linear_click(v + 700)

    def _linear_modifier(self, v=0):
        return self._rb_sum(v, 0.045, 800, [({'f0': 280, 'n_partials': 3, 'decay_base': 150, 'inharmonicity': 0.002, 'delay': 0.005, 'amplitude_rolloff': 0.5}, 0.38)], 80, 4000, -9.0, 220, 0.1)
    def _linear_punctuation(self, v=0):
        return self._linear_click(v + 900)

    def _linear_escape(self, v=0):
        return self._linear_click(v + 950)

    def _cashreg_builders(self):
        b = self
        return { "key":           (b._cashreg_key, 6), "jackpot":       (b._cashreg_jackpot, 3), "coin":          (b._cashreg_coin, 4), "coin_tray":     (b._cashreg_coin_tray, 3), "drawer_slam":   (b._cashreg_drawer_slam, 3), "receipt_tear":  (b._cashreg_receipt_tear, 3), "small_item":    (b._cashreg_small_item, 4), "med_item":      (b._cashreg_med_item, 4), "beep":          (b._cashreg_beep, 4), "scanner":       (b._cashreg_scanner, 4),
        }

    def _cashreg_key(self, v=0):
        """Quick register keypress — short mechanical click + tiny ding."""
        sr, dur = self.sample_rate, 0.055; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v); pitch = 1.0 + (v - 2.5) * 0.04
        f_click = 3000 * pitch + rng.randint(-200, 200); click = np.sin(2 * np.pi * f_click * t) * _env_adsr(t, 0.0002, 0.008, 0.05, 0.02) * 0.30; f_ding = 4200 * pitch + rng.randint(-150, 150)
        ding = np.sin(2 * np.pi * f_ding * t) * _env_adsr(t, 0.001, 0.006, 0.08, 0.015, delay=0.008) * 0.20; f_thud = 450 + rng.randint(-30, 30)
        thud = np.sin(2 * np.pi * f_thud * t) * _env_adsr(t, 0.003, 0.012, 0.08, 0.02, delay=0.004) * 0.25; out = click + ding + thud
        return self._to_int16(out)

    def _cashreg_jackpot(self, v=0):
        """Cash register jackpot — rising arpeggio 'cha-ching!'."""
        sr, dur = self.sample_rate, 0.35; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 10); f1 = 1800 + rng.randint(-100, 100); f2 = 3200 + rng.randint(-100, 100)
        mask1 = (t < 0.10).astype(np.float64); t1 = np.clip(t, 0, 0.10); note1 = np.sin(2 * np.pi * f1 * t) * np.exp(-t * 18) * 0.40 * mask1; mask2 = (t >= 0.10).astype(np.float64)
        t2 = np.clip(t - 0.10, 0, None); note2 = np.sin(2 * np.pi * f2 * t) * np.exp(-t2 * 10) * 0.55 * mask2; shim_modes = _metal_plate_modes(f2 * 2.5, n_modes=5, rng=rng)
        shim = _modal_impact(n, rng, shim_modes, sr, noise_mix=0.02, noise_decay=30) * 0.18 * mask2
        ring_ks = _karplus_strong(5500 + rng.randint(-300, 300), dur * 0.9, sr, brightness=0.2, damping=0.3, rng=rng); ring_ks_len = min(len(ring_ks), n); ring = np.zeros(n, dtype=np.float64)
        ring[:ring_ks_len] = ring_ks[:ring_ks_len]; ring *= np.exp(-t * 12) * 0.14; out = note1 + note2 + shim + ring
        return self._to_int16(out)

    def _cashreg_coin(self, v=0):
        """Single coin dropping into tray — bright metallic ping."""
        sr, dur = self.sample_rate, 0.18; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 100); pitch = 1.0 + v * 0.06
        coin_ks = _karplus_strong_v2(6200 * pitch, dur * 0.85, sr, brightness=0.15, damping=0.4, rng=rng, n_strings=2, detune_hz=80, freq_spread=0.003)
        ks_len = min(len(coin_ks), n); ping = np.zeros(n, dtype=np.float64); ping[:ks_len] = coin_ks[:ks_len]; ping *= np.exp(-t * 20) * 0.45
        coin_modes = _metal_plate_modes(3800 * pitch, n_modes=4, rng=rng); wobble = _modal_impact(n, rng, coin_modes, sr, noise_mix=0.05, noise_decay=60) * 0.22
        rattle = _bandpass_noise(n, rng, 3000, 7000, sr) * np.exp(-t * 35) * 0.12; bounce_delay = int(0.06 * sr)
        if bounce_delay < n - 100:
            t_b = t[bounce_delay:] - t[bounce_delay]; f_b = 5500 * pitch + rng.randint(-300, 300); bounce = np.sin(2 * np.pi * f_b * t_b) * np.exp(-t_b * 45) * 0.25; buf = np.zeros(n, dtype=np.float64)
            buf[bounce_delay:bounce_delay + len(bounce)] = bounce
        else:
            buf = np.zeros(n, dtype=np.float64); out = ping + wobble + rattle + buf
        return self._to_int16(out)

    def _cashreg_coin_tray(self, v=0):
        """Handful of coins scattered into tray — cascading pings."""
        sr, dur = self.sample_rate, 0.30; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 200); out = np.zeros(n, dtype=np.float64)
        for i in range(5 + v):
            delay = int(rng.uniform(0, 0.15) * sr); f = rng.uniform(4000, 7000); length = int(rng.uniform(0.04, 0.10) * sr); end = min(delay + length, n); t_seg = np.arange(end - delay) / sr
            seg = np.sin(2 * np.pi * f * t_seg) * np.exp(-t_seg * rng.uniform(20, 50)) * rng.uniform(0.15, 0.35); out[delay:end] += seg; f_thud = 200 + rng.randint(-20, 20)
        thud = np.sin(2 * np.pi * f_thud * t) * _env_adsr(t, 0.005, 0.02, 0.12, 0.05, delay=0.01) * 0.30; out += thud
        return self._to_int16(out)

    def _cashreg_drawer_slam(self, v=0):
        """Cash drawer sliding open and slamming shut."""
        sr, dur = self.sample_rate, 0.40; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 300); f_start = 800 + rng.randint(-50, 50); f_end = 200
        freq = f_start + (f_end - f_start) * (t / dur); phase = 2 * np.pi * np.cumsum(freq) / sr; slide = np.sin(phase) * np.exp(-t * 8) * 0.25
        slide_noise = _butter_lowpass(rng.randn(n), 0.25, 1) * np.exp(-t * 6) * 0.20; slam_t = 0.24; slam_env = np.exp(-np.maximum(0, t - slam_t) * 60) * (t >= slam_t).astype(float)
        f_slam = 150 + rng.randint(-15, 15); slam = np.sin(2 * np.pi * f_slam * t) * slam_env * 0.50; latch_t = 0.30; latch_env = np.exp(-np.maximum(0, t - latch_t) * 120) * (t >= latch_t).astype(float)
        f_latch = 3500 + rng.randint(-200, 200); latch = np.sin(2 * np.pi * f_latch * t) * latch_env * 0.30; out = slide + slide_noise + slam + latch
        return self._to_int16(out)

    def _cashreg_receipt_tear(self, v=0):
        """Receipt paper tearing — textured noise burst."""
        sr, dur = self.sample_rate, 0.12; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 400); tear = _bandpass_noise(n, rng, 1500, 6000, sr) * np.exp(-t * 25) * 0.45
        crinkle = _butter_lowpass(rng.randn(n), 0.18, 1) * np.exp(-t * 30) * 0.25; rip = rng.randn(min(60, n)) * np.exp(-np.linspace(0, 2000, min(60, n))) * 0.20; rip = np.pad(rip, (0, n - len(rip)))
        out = tear + crinkle + rip; return self._to_int16(out)

    def _cashreg_small_item(self, v=0):
        """Small item scanned — quick double beep."""
        sr, dur = self.sample_rate, 0.10; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 500); pitch = 1.0 + v * 0.05; f1 = 2800 * pitch + rng.randint(-100, 100)
        beep1 = np.sin(2 * np.pi * f1 * t) * np.exp(-np.maximum(0, t - 0.03) * 80) * (t < 0.06).astype(float) * 0.35; f2 = 3200 * pitch + rng.randint(-100, 100); t2 = np.clip(t - 0.05, 0, None)
        beep2 = np.sin(2 * np.pi * f2 * t) * np.exp(-t2 * 80) * (t >= 0.05).astype(float) * 0.40; out = beep1 + beep2
        return self._to_int16(out)

    def _cashreg_med_item(self, v=0):
        """Medium item — barcode scanner beep + thud."""
        sr, dur = self.sample_rate, 0.12; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 600); pitch = 1.0 + v * 0.04
        scan = _frequency_sweep(0.08, 3500 * pitch + rng.randint(-100, 100), 2000 * pitch + rng.randint(-50, 50), sr); scan = np.pad(scan, (0, n - len(scan)))[:n]; scan *= np.exp(-t * 22) * 0.35
        f_conf = 2600 * pitch + rng.randint(-80, 80); conf = np.sin(2 * np.pi * f_conf * t) * np.exp(-np.maximum(0, t - 0.06) * 60) * (t >= 0.06).astype(float) * 0.30; f_thud = 180 + rng.randint(-15, 15)
        thud = np.sin(2 * np.pi * f_thud * t) * _env_adsr(t, 0.005, 0.02, 0.10, 0.04, delay=0.01) * 0.30; out = scan + conf + thud
        return self._to_int16(out)

    def _cashreg_beep(self, v=0):
        """Numeric keypad beep — clean electronic tone."""
        sr, dur = self.sample_rate, 0.06; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 700); pitch = 0.85 + v * 0.08  # different pitch per digit variant
        f = 2200 * pitch + rng.randint(-80, 80); beep = np.sin(2 * np.pi * f * t) * _env_adsr(t, 0.001, 0.005, 0.15, 0.02) * 0.40
        sq = np.sign(np.sin(2 * np.pi * f * 0.5 * t)) * _env_adsr(t, 0.001, 0.005, 0.08, 0.015) * 0.10; out = beep + sq
        return self._to_int16(out)

    def _cashreg_scanner(self, v=0):
        """Barcode scanner — laser sweep + confirmation chirp."""
        sr, dur = self.sample_rate, 0.15; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 900); sweep_dur = 0.07
        sweep_raw = _frequency_sweep(sweep_dur, 4000 + rng.randint(-200, 200), 1500 + rng.randint(-100, 100), sr); mask_sweep = (t < sweep_dur).astype(float)
        sweep_raw = np.pad(sweep_raw, (0, n - len(sweep_raw)))[:n]; sweep = sweep_raw * 0.35 * mask_sweep; f_c1 = 2400 + rng.randint(-80, 80); f_c2 = 3000 + rng.randint(-80, 80)
        mask_chirp = (t >= 0.08).astype(float); t_c = np.clip(t - 0.08, 0, None)
        chirp = (np.sin(2 * np.pi * f_c1 * t) * np.exp(-t_c * 50) * 0.35 + np.sin(2 * np.pi * f_c2 * t) * np.exp(-t_c * 55) * 0.20) * mask_chirp
        out = sweep + chirp; return self._to_int16(out)

    def _pinball_builders(self):
        b = self
        return { "key":         (b._pinball_key, 6), "multiplier":  (b._pinball_multiplier, 3), "plunger":     (b._pinball_plunger, 4), "tilt":        (b._pinball_tilt, 3), "drain":       (b._pinball_drain, 3), "flipper":     (b._pinball_flipper, 4), "bumper_a":    (b._pinball_bumper_a, 4), "bumper_b":    (b._pinball_bumper_b, 4), "bumper_c":    (b._pinball_bumper_c, 4), "target":      (b._pinball_target, 4),
        }

    def _pinball_key(self, v=0):
        """Generic playfield sound — plastic ball hitting a rail."""
        sr, dur = self.sample_rate, 0.07; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v); pitch = 1.0 + (v - 2.5) * 0.05; f_hit = 4000 * pitch + rng.randint(-250, 250)
        hit = np.sin(2 * np.pi * f_hit * t) * np.exp(-t * 500) * 0.35; f_ring = 1800 * pitch + rng.randint(-100, 100); ring = np.sin(2 * np.pi * f_ring * t) * np.exp(-t * 120) * 0.25
        f_body = 300 + rng.randint(-25, 25); body = np.sin(2 * np.pi * f_body * t) * _env_adsr(t, 0.004, 0.015, 0.10, 0.025, delay=0.006) * 0.30; out = hit + ring + body
        return self._to_int16(out)

    def _pinball_multiplier(self, v=0):
        """Multiplier activated — rising electronic arpeggio."""
        sr, dur = self.sample_rate, 0.30; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 10); out = np.zeros(n, dtype=np.float64); base_freqs = [800, 1200, 1800]
        for i, f_base in enumerate(base_freqs):
            f = f_base + rng.randint(-50, 50); delay = i * 0.06; t_seg = np.clip(t - delay, 0, None); seg = np.sin(2 * np.pi * f * t) * np.exp(-t_seg * 12) * 0.35 * (t >= delay).astype(float); out += seg
        f_hi = 3500 + rng.randint(-200, 200); t_seg = np.clip(t - 0.18, 0, None); hi = np.sin(2 * np.pi * f_hi * t) * np.exp(-t_seg * 10) * 0.30 * (t >= 0.18).astype(float); out += hi
        return self._to_int16(out)

    def _pinball_plunger(self, v=0):
        """Spring plunger launch — rising coil whine + thwack."""
        sr, dur = self.sample_rate, 0.25; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 100); f_start = 200 + rng.randint(-20, 20); f_end = 1200 + rng.randint(-80, 80)
        freq = f_start + (f_end - f_start) * np.clip(t / 0.15, 0, 1); phase = 2 * np.pi * np.cumsum(freq) / sr; whine = np.sin(phase) * (t < 0.15).astype(float) * 0.30
        thwack_env = np.exp(-np.maximum(0, t - 0.15) * 80) * (t >= 0.15).astype(float); f_thwack = 600 + rng.randint(-40, 40); thwack = np.sin(2 * np.pi * f_thwack * t) * thwack_env * 0.45
        f_echo = 2000 + rng.randint(-150, 150); echo = np.sin(2 * np.pi * f_echo * t) * np.exp(-np.maximum(0, t - 0.18) * 40) * (t >= 0.18).astype(float) * 0.20; out = whine + thwack + echo
        return self._to_int16(out)

    def _pinball_tilt(self, v=0):
        """Tilt warning — harsh buzzer."""
        sr, dur = self.sample_rate, 0.25; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 200); f_buzz = 280 + rng.randint(-20, 20)
        buzzer = np.sign(np.sin(2 * np.pi * f_buzz * t)) * _env_adsr(t, 0.002, 0.02, 0.5, 0.08) * 0.30; f_warn = 880 + rng.randint(-40, 40)
        warn = np.sin(2 * np.pi * f_warn * t) * _env_adsr(t, 0.002, 0.01, 0.3, 0.06) * 0.25; rattle = _bandpass_noise(n, rng, 200, 2000, sr) * _env_adsr(t, 0.005, 0.03, 0.3, 0.06) * 0.15
        out = buzzer + warn + rattle; return self._to_int16(out)

    def _pinball_drain(self, v=0):
        """Ball drain — descending tone + sad thud."""
        sr, dur = self.sample_rate, 0.35; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 300); f_start = 600 + rng.randint(-40, 40); f_end = 150
        freq = f_start + (f_end - f_start) * (t / dur); phase = 2 * np.pi * np.cumsum(freq) / sr; desc = np.sin(phase) * np.exp(-t * 8) * 0.35; f_thud = 100 + rng.randint(-10, 10)
        thud = np.sin(2 * np.pi * f_thud * t) * _env_adsr(t, 0.01, 0.04, 0.25, 0.08, delay=0.05) * 0.45; noise = _butter_lowpass(rng.randn(n), 0.15, 2) * np.exp(-t * 12) * 0.15; out = desc + thud + noise
        return self._to_int16(out)

    def _pinball_flipper(self, v=0):
        """Flipper activation — solenoid slap + return spring."""
        sr, dur = self.sample_rate, 0.09; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 400); f_sol = 500 + rng.randint(-30, 30)
        sol = np.sin(2 * np.pi * f_sol * t) * _env_adsr(t, 0.001, 0.008, 0.12, 0.025) * 0.50; impact = _bandpass_noise(n, rng, 500, 3000, sr) * np.exp(-t * 200) * 0.20; t_ret = np.clip(t - 0.03, 0, None)
        f_ret = 350 + rng.randint(-25, 25); ret = np.sin(2 * np.pi * f_ret * t) * np.exp(-t_ret * 120) * (t >= 0.03).astype(float) * 0.20; out = sol + impact + ret
        return self._to_int16(out)

    def _pinball_bumper_a(self, v=0):
        """Pop bumper A — high ping + thud."""
        sr, dur = self.sample_rate, 0.08; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 500)
        cap_modes = _metal_plate_modes(4500 + rng.randint(-300, 300), n_modes=5, rng=rng); ping = _modal_impact(n, rng, cap_modes, sr, noise_mix=0.12, noise_decay=500) * 0.42
        thud = _noise_excited_resonator(n, rng, center_freq=350 + rng.randint(-25, 25), bandwidth=1000, q=2.5, sr=sr, excitation_decay=400) * 0.30
        thud *= _env_adsr(t, 0.003, 0.012, 0.10, 0.02, delay=0.004); ring_ks = _karplus_strong(2200 + rng.randint(-150, 150), dur * 0.7, sr, brightness=0.2, damping=0.6, rng=rng)
        ring_ks_len = min(len(ring_ks), n); ring = np.zeros(n, dtype=np.float64); ring[:ring_ks_len] = ring_ks[:ring_ks_len]; ring = _comb_filter(ring, delay_ms=0.22, feedback=0.30, sr=sr) * 0.14
        out = ping + thud + ring; return self._to_int16(out)

    def _pinball_bumper_b(self, v=0):
        """Pop bumper B — different pitch range."""
        sr, dur = self.sample_rate, 0.08; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 600)
        cap_modes = _metal_plate_modes(5200 + rng.randint(-300, 300), n_modes=5, rng=rng); ping = _modal_impact(n, rng, cap_modes, sr, noise_mix=0.12, noise_decay=550) * 0.40
        thud = _noise_excited_resonator(n, rng, center_freq=380 + rng.randint(-25, 25), bandwidth=1000, q=2.5, sr=sr, excitation_decay=400) * 0.28
        thud *= _env_adsr(t, 0.003, 0.012, 0.10, 0.02, delay=0.004); ring_ks = _karplus_strong(2800 + rng.randint(-150, 150), dur * 0.7, sr, brightness=0.2, damping=0.6, rng=rng)
        ring_ks_len = min(len(ring_ks), n); ring = np.zeros(n, dtype=np.float64); ring[:ring_ks_len] = ring_ks[:ring_ks_len]; ring = _comb_filter(ring, delay_ms=0.20, feedback=0.30, sr=sr) * 0.14
        out = ping + thud + ring; return self._to_int16(out)

    def _pinball_bumper_c(self, v=0):
        """Pop bumper C — lowest pitch bumper."""
        sr, dur = self.sample_rate, 0.085; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 700)
        cap_modes = _metal_plate_modes(3800 + rng.randint(-250, 250), n_modes=5, rng=rng); ping = _modal_impact(n, rng, cap_modes, sr, noise_mix=0.12, noise_decay=450) * 0.44
        thud = _noise_excited_resonator(n, rng, center_freq=300 + rng.randint(-25, 25), bandwidth=1000, q=2.5, sr=sr, excitation_decay=400) * 0.34
        thud *= _env_adsr(t, 0.004, 0.012, 0.12, 0.02, delay=0.005); out = ping + thud
        return self._to_int16(out)

    def _pinball_target(self, v=0):
        """Drop target / standup target — metallic clang."""
        sr, dur = self.sample_rate, 0.065; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 900)
        target_modes = _metal_plate_modes(3000 + rng.randint(-200, 200), n_modes=5, rng=rng); clang = _modal_impact(n, rng, target_modes, sr, noise_mix=0.10, noise_decay=600) * 0.42
        body = _noise_excited_resonator(n, rng, center_freq=250 + rng.randint(-20, 20), bandwidth=800, q=2.0, sr=sr, excitation_decay=450) * 0.28
        body *= _env_adsr(t, 0.003, 0.010, 0.08, 0.02, delay=0.004); out = clang + body
        return self._to_int16(out)

    def _telegraph_builders(self):
        b = self
        return { "key":               (b._telegraph_key, 6), "dash":              (b._telegraph_dash, 4), "long_gap":          (b._telegraph_long_gap, 3), "repeater_click":    (b._telegraph_repeater, 3), "end_transmission":  (b._telegraph_end, 3), "correction":        (b._telegraph_correction, 3), "dot":               (b._telegraph_dot, 4),
        }

    def _telegraph_key(self, v=0):
        """Standard telegraph key tap — electromagnetic relay click."""
        sr, dur = self.sample_rate, 0.06; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v); pitch = 1.0 + (v - 2.5) * 0.04
        ks_relay = _karplus_strong(2800 * pitch + rng.randint(-200, 200), dur * 0.6, sr, brightness=0.3, damping=0.65, rng=rng); ks_len = min(len(ks_relay), n); strike = np.zeros(n, dtype=np.float64)
        strike[:ks_len] = ks_relay[:ks_len]; strike *= _env_adsr(t, 0.0002, 0.008, 0.10, 0.025) * 0.40
        em = _svf_resonant_noise(n, rng, freq=120 * pitch + rng.randint(-10, 10), q=8.0, sr=sr, decay=180) * 0.15; contact_modes = _metal_plate_modes(5000 + rng.randint(-300, 300), n_modes=3, rng=rng)
        click = _modal_impact(n, rng, contact_modes, sr, noise_mix=0.05, noise_decay=1200) * 0.18; wood_modes = _wood_bar_modes(180 + rng.randint(-15, 15), n_modes=3, rng=rng)
        wood = _modal_impact(n, rng, wood_modes, sr, noise_mix=0.04, noise_decay=300) * 0.20; wood *= _env_adsr(t, 0.005, 0.015, 0.08, 0.03, delay=0.006); out = strike + em + click + wood
        return self._to_int16(out)

    def _telegraph_dot(self, v=0):
        """Short dot — quick tap (on/off)."""
        sr, dur = self.sample_rate, 0.05; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 100); f_tap = 3200 + rng.randint(-200, 200)
        tap = np.sin(2 * np.pi * f_tap * t) * np.exp(-t * 500) * 0.40; f_base = 160 + rng.randint(-12, 12); base = np.sin(2 * np.pi * f_base * t) * np.exp(-t * 150) * 0.20; out = tap + base
        return self._to_int16(out)

    def _telegraph_dash(self, v=0):
        """Long dash — sustained tone (3x dot length)."""
        sr, dur = self.sample_rate, 0.15; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 200); f_tone = 800 + rng.randint(-40, 40)
        tone = np.sin(2 * np.pi * f_tone * t) * _env_adsr(t, 0.0005, 0.01, 0.6, 0.04) * 0.35; f_buzz = 120 + rng.randint(-10, 10)
        buzz = np.sin(2 * np.pi * f_buzz * t) * _env_adsr(t, 0.001, 0.01, 0.4, 0.03) * 0.15; close_click = rng.randn(min(30, n)) * 0.15 * np.exp(-np.linspace(0, 3000, min(30, n)))
        close_click = np.pad(close_click, (0, n - len(close_click))); open_click = np.zeros(n, dtype=np.float64); open_idx = int(0.13 * sr)
        if open_idx + 30 < n:
            open_click[open_idx:open_idx + 30] = rng.randn(30) * 0.10 * np.exp(-np.linspace(0, 2500, 30)); out = tone + buzz + close_click + open_click
        return self._to_int16(out)

    def _telegraph_long_gap(self, v=0):
        """Long gap — quiet pause with subtle room ambience."""
        sr, dur = self.sample_rate, 0.20; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 300); f_hum = 60; hum = np.sin(2 * np.pi * f_hum * t) * 0.02
        tick_idx = rng.randint(n // 3, 2 * n // 3); tick = np.zeros(n, dtype=np.float64); tick_len = min(40, n - tick_idx)
        if tick_len > 0:
            tick[tick_idx:tick_idx + tick_len] = rng.randn(tick_len) * np.exp(-np.linspace(0, 1000, tick_len)) * 0.08; out = hum + tick
        return self._to_int16(out)

    def _telegraph_repeater(self, v=0):
        """Repeater click — rapid double-tap mechanical sound."""
        sr, dur = self.sample_rate, 0.10; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 400); f_click = 3500 + rng.randint(-200, 200)
        tap1 = np.sin(2 * np.pi * f_click * t) * np.exp(-t * 400) * 0.35; tap2_env = np.exp(-np.maximum(0, t - 0.04) * 400) * (t >= 0.04).astype(float); f_click2 = 3600 + rng.randint(-200, 200)
        tap2 = np.sin(2 * np.pi * f_click2 * t) * tap2_env * 0.35; snap = _bandpass_noise(n, rng, 500, 3000, sr) * np.exp(-t * 200) * 0.12; out = tap1 + tap2 + snap
        return self._to_int16(out)

    def _telegraph_end(self, v=0):
        """End of transmission — three dots + long dash (sign-off)."""
        sr, dur = self.sample_rate, 0.60; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 500); out = np.zeros(n, dtype=np.float64); f_base = 800 + rng.randint(-40, 40)
        for i in range(3):
            delay = i * 0.08; t_seg = np.clip(t - delay, 0, None); seg = np.sin(2 * np.pi * f_base * t) * np.exp(-t_seg * 300) * 0.35 * (t >= delay).astype(float); out += seg; dash_delay = 0.28
        t_seg = np.clip(t - dash_delay, 0, None); dash = np.sin(2 * np.pi * f_base * t) * np.exp(-t_seg * 8) * 0.40 * (t >= dash_delay).astype(float); out += dash; final_delay = 0.50
        t_f = np.clip(t - final_delay, 0, None); final = np.sin(2 * np.pi * 4000 * t) * np.exp(-t_f * 600) * 0.20 * (t >= final_delay).astype(float); out += final
        return self._to_int16(out)

    def _telegraph_correction(self, v=0):
        """Correction signal — rapid buzz (error indication)."""
        sr, dur = self.sample_rate, 0.12; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 600); f_buzz = 600 + rng.randint(-30, 30)
        buzz = np.sign(np.sin(2 * np.pi * f_buzz * t)) * _env_adsr(t, 0.001, 0.01, 0.4, 0.04) * 0.25; f_err = 930 + rng.randint(-40, 40)
        err = np.sin(2 * np.pi * f_err * t) * _env_adsr(t, 0.001, 0.01, 0.3, 0.03) * 0.25; rattle = _butter_lowpass(rng.randn(n), 0.25, 1) * np.exp(-t * 100) * 0.12; out = buzz + err + rattle
        return self._to_int16(out)

    def _arcade_builders(self):
        b = self
        return { "key":           (b._arcade_key, 6), "start_coin":    (b._arcade_start_coin, 3), "punch":         (b._arcade_punch, 4), "macro":         (b._arcade_macro, 3), "insert_coin":   (b._arcade_insert_coin, 3), "delete_buzz":   (b._arcade_delete_buzz, 3), "a_btn":         (b._arcade_a_btn, 4), "b_btn":         (b._arcade_b_btn, 4),
        }

    def _arcade_key(self, v=0):
        """Standard arcade button press — microswitch click + cabinet."""
        sr, dur = self.sample_rate, 0.06; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v); pitch = 1.0 + (v - 2.5) * 0.04
        sw_modes = _metal_plate_modes(3200 * pitch + rng.randint(-200, 200), n_modes=4, rng=rng); click = _modal_impact(n, rng, sw_modes, sr, noise_mix=0.08, noise_decay=800) * 0.35
        click *= _env_adsr(t, 0.0002, 0.006, 0.06, 0.02); ks_sw = _karplus_strong(4800 * pitch + rng.randint(-300, 300), dur * 0.5, sr, brightness=0.2, damping=0.7, rng=rng); ks_len = min(len(ks_sw), n)
        spring = np.zeros(n, dtype=np.float64); spring[:ks_len] = ks_sw[:ks_len]; spring *= np.exp(-t * 400) * 0.15; f_dome = 600 + rng.randint(-40, 40)
        dome = np.sin(2 * np.pi * f_dome * t) * _env_adsr(t, 0.002, 0.010, 0.08, 0.02, delay=0.003) * 0.25; f_cab = 120 + rng.randint(-10, 10); cab = np.sin(2 * np.pi * f_cab * t) * np.exp(-t * 80) * 0.15
        out = click + spring + dome + cab; return self._to_int16(out)

    def _arcade_a_btn(self, v=0):
        """A button — bright, punchy microswitch."""
        sr, dur = self.sample_rate, 0.055; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 100); pitch = 1.0 + v * 0.05; f_click = 3500 * pitch + rng.randint(-200, 200)
        click = np.sin(2 * np.pi * f_click * t) * _env_adsr(t, 0.0002, 0.006, 0.05, 0.015) * 0.38; f_spring = 5200 * pitch + rng.randint(-300, 300)
        spring = np.sin(2 * np.pi * f_spring * t) * np.exp(-t * 450) * 0.12; f_cab = 130 + rng.randint(-10, 10); cab = np.sin(2 * np.pi * f_cab * t) * np.exp(-t * 90) * 0.18; out = click + spring + cab
        return self._to_int16(out)

    def _arcade_b_btn(self, v=0):
        """B button — slightly deeper than A."""
        sr, dur = self.sample_rate, 0.058; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 200); pitch = 0.92 + v * 0.04; f_click = 3000 * pitch + rng.randint(-200, 200)
        click = np.sin(2 * np.pi * f_click * t) * _env_adsr(t, 0.0002, 0.007, 0.06, 0.018) * 0.36; f_spring = 4600 * pitch + rng.randint(-250, 250)
        spring = np.sin(2 * np.pi * f_spring * t) * np.exp(-t * 400) * 0.12; f_cab = 110 + rng.randint(-10, 10); cab = np.sin(2 * np.pi * f_cab * t) * np.exp(-t * 85) * 0.20; out = click + spring + cab
        return self._to_int16(out)

    def _arcade_punch(self, v=0):
        """Punch button (fighting game) — heavy thwack."""
        sr, dur = self.sample_rate, 0.07; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 300); f_impact = 800 + rng.randint(-50, 50)
        impact = np.sin(2 * np.pi * f_impact * t) * _env_adsr(t, 0.0005, 0.008, 0.12, 0.02) * 0.45; f_click = 3000 + rng.randint(-200, 200); click = np.sin(2 * np.pi * f_click * t) * np.exp(-t * 500) * 0.25
        f_cab = 100 + rng.randint(-8, 8); cab = np.sin(2 * np.pi * f_cab * t) * _env_adsr(t, 0.004, 0.015, 0.12, 0.03, delay=0.006) * 0.30; out = impact + click + cab
        return self._to_int16(out)

    def _arcade_macro(self, v=0):
        """Macro button — rapid triple click."""
        sr, dur = self.sample_rate, 0.12; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 400); out = np.zeros(n, dtype=np.float64)
        for i in range(3):
            delay = i * 0.03; t_seg = np.clip(t - delay, 0, None); f = 3200 + rng.randint(-200, 200) + i * 200; seg = np.sin(2 * np.pi * f * t) * np.exp(-t_seg * 350) * 0.30 * (t >= delay).astype(float)
            out += seg; f_cab = 110 + rng.randint(-8, 8); cab = np.sin(2 * np.pi * f_cab * t) * np.exp(-t * 60) * 0.15; out += cab
        return self._to_int16(out)

    def _arcade_start_coin(self, v=0):
        """Start button / coin credit — classic ascending chime."""
        sr = self.sample_rate; dur = 0.25; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 500); out = np.zeros(n, dtype=np.float64)
        for i, f_base in enumerate([1200, 1800]):
            f = f_base + rng.randint(-60, 60); delay = i * 0.08; t_seg = np.clip(t - delay, 0, None); chime_modes = _bell_modes(f, n_modes=5, rng=rng); seg_n = n - int(delay * sr)
            if seg_n > 0:
                seg_raw = _modal_impact(seg_n, rng, chime_modes, sr, noise_mix=0.02, noise_decay=30); seg = np.zeros(n, dtype=np.float64); seg_start = int(delay * sr); seg_end = min(seg_start + seg_n, n)
                seg[seg_start:seg_end] = seg_raw[:seg_end - seg_start]; seg *= np.exp(-t_seg * 12) * 0.35
            else:
                seg = np.zeros(n, dtype=np.float64); out += seg; t_seg = np.clip(t - 0.16, 0, None); hi_modes = _metal_plate_modes(3600 + rng.randint(-200, 200), n_modes=3, rng=rng); hi_n = n - int(0.16 * sr)
        if hi_n > 0:
            hi_raw = _modal_impact(hi_n, rng, hi_modes, sr, noise_mix=0.03, noise_decay=40); hi = np.zeros(n, dtype=np.float64); hi_start = int(0.16 * sr); hi_end = min(hi_start + hi_n, n)
            hi[hi_start:hi_end] = hi_raw[:hi_end - hi_start]; hi *= np.exp(-t_seg * 15) * 0.22
        else:
            hi = np.zeros(n, dtype=np.float64); out += hi
        return self._to_int16(out)

    def _arcade_insert_coin(self, v=0):
        """Insert coin — coin sliding in + credit ding."""
        sr, dur = self.sample_rate, 0.30; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 600); slide = _butter_lowpass(rng.randn(n), 0.30, 1) * np.exp(-t * 12) * 0.20
        f_thud = 250 + rng.randint(-20, 20); thud = np.sin(2 * np.pi * f_thud * t) * _env_adsr(t, 0.005, 0.02, 0.10, 0.04, delay=0.08) * 0.35; f_ding = 2800 + rng.randint(-150, 150)
        t_seg = np.clip(t - 0.15, 0, None); ding = np.sin(2 * np.pi * f_ding * t) * np.exp(-t_seg * 18) * 0.35 * (t >= 0.15).astype(float); out = slide + thud + ding
        return self._to_int16(out)

    def _arcade_delete_buzz(self, v=0):
        """Delete/back buzz — error buzzer."""
        sr, dur = self.sample_rate, 0.15; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 700); f_buzz = 200 + rng.randint(-15, 15)
        buzz = np.sign(np.sin(2 * np.pi * f_buzz * t)) * _env_adsr(t, 0.002, 0.01, 0.3, 0.04) * 0.30; f_dis = 265 + rng.randint(-15, 15)
        dis = np.sign(np.sin(2 * np.pi * f_dis * t)) * _env_adsr(t, 0.002, 0.01, 0.2, 0.03) * 0.15; out = buzz + dis
        return self._to_int16(out)

    def _gunshot_builders(self):
        b = self
        return { "key":           (b._gunshot_key, 6), "shotgun":       (b._gunshot_shotgun, 3), "rifle":         (b._gunshot_rifle, 4), "burst":         (b._gunshot_burst, 3), "cannon":        (b._gunshot_cannon, 3), "silenced_hit":  (b._gunshot_silenced_hit, 3), "pistol":        (b._gunshot_pistol, 4), "revolver":      (b._gunshot_revolver, 4),
        }

    def _gunshot_key(self, v=0):
        """Generic shot — short percussive boom."""
        sr, dur = self.sample_rate, 0.10; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v); pitch = 1.0 + (v - 2.5) * 0.06; crack_len = min(120, n)
        crack = rng.randn(crack_len) * np.exp(-np.linspace(0, 1500, crack_len)) * 0.30; crack = np.pad(crack, (0, n - len(crack)))
        boom = _noise_excited_resonator(n, rng, center_freq=80 * pitch + rng.randint(-8, 8), bandwidth=500, q=3.0, sr=sr, excitation_decay=250) * 0.50
        boom *= _env_adsr(t, 0.002, 0.02, 0.25, 0.05, delay=0.005); mid = _svf_resonant_noise(n, rng, freq=400 * pitch + rng.randint(-30, 30), q=4.0, sr=sr, decay=120) * 0.22
        echo_base = _svf_resonant_noise(n, rng, freq=120 * pitch + rng.randint(-10, 10), q=6.0, sr=sr, decay=30) * 0.20; echo = _comb_filter(echo_base, delay_ms=12.0, feedback=0.45, sr=sr)
        echo *= _env_adsr(t, 0.015, 0.03, 0.15, 0.06, delay=0.03); out = crack + boom + mid + echo; out = _svf_filter(out, 8800, 0.707, sr, mode='lp')
        return self._to_int16(out)

    def _gunshot_pistol(self, v=0):
        """Pistol shot — sharp crack + quick decay."""
        sr, dur = self.sample_rate, 0.12; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 100); pitch = 1.0 + v * 0.06; crack_len = min(150, n)
        crack = rng.randn(crack_len) * np.exp(-np.linspace(0, 1200, crack_len)) * 0.35; crack = np.pad(crack, (0, n - len(crack)))
        body = _noise_excited_resonator(n, rng, center_freq=120 * pitch + rng.randint(-10, 10), bandwidth=600, q=3.5, sr=sr, excitation_decay=300) * 0.45
        body *= _env_adsr(t, 0.001, 0.015, 0.20, 0.04, delay=0.003); slide_delay = int(0.06 * sr)
        if slide_delay + 60 < n:
            f_slide = 2500 + rng.randint(-200, 200); t_s = np.arange(60) / sr; slide = np.sin(2 * np.pi * f_slide * t_s) * np.exp(-t_s * 200) * 0.15; buf = np.zeros(n, dtype=np.float64)
            buf[slide_delay:slide_delay + 60] = slide
        else:
            buf = np.zeros(n, dtype=np.float64); out = crack + body + buf; out = _svf_filter(out, 8400, 0.707, sr, mode='lp')
        return self._to_int16(out)

    def _gunshot_revolver(self, v=0):
        """Revolver — deeper boom + cylinder rotation click."""
        sr, dur = self.sample_rate, 0.14; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 200); pitch = 1.0 + v * 0.05; crack_len = min(180, n)
        crack = rng.randn(crack_len) * np.exp(-np.linspace(0, 900, crack_len)) * 0.30; crack = np.pad(crack, (0, n - len(crack)))
        boom = _noise_excited_resonator(n, rng, center_freq=70 * pitch + rng.randint(-6, 6), bandwidth=400, q=3.0, sr=sr, excitation_decay=200) * 0.50
        boom *= _env_adsr(t, 0.003, 0.025, 0.28, 0.05, delay=0.005); cyl_delay = int(0.08 * sr)
        if cyl_delay + 50 < n:
            f_cyl = 4000 + rng.randint(-300, 300); t_c = np.arange(50) / sr; cyl = np.sin(2 * np.pi * f_cyl * t_c) * np.exp(-t_c * 300) * 0.15; buf = np.zeros(n, dtype=np.float64)
            buf[cyl_delay:cyl_delay + 50] = cyl
        else:
            buf = np.zeros(n, dtype=np.float64); out = crack + boom + buf; out = _svf_filter(out, 7700, 0.707, sr, mode='lp')
        return self._to_int16(out)

    def _gunshot_shotgun(self, v=0):
        """Shotgun blast — long, powerful boom with chamber echo."""
        sr, dur = self.sample_rate, 0.25; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 300); crack_len = min(300, n)
        crack = rng.randn(crack_len) * np.exp(-np.linspace(0, 500, crack_len)) * 0.30; crack = np.pad(crack, (0, n - len(crack))); f_boom = 55 + rng.randint(-5, 5)
        boom = np.sin(2 * np.pi * f_boom * t) * _env_adsr(t, 0.003, 0.03, 0.35, 0.08, delay=0.005) * 0.60; rack_delay = int(0.12 * sr); rack_len = min(120, n - rack_delay)
        if rack_len > 0:
            f_rack = 300 + rng.randint(-25, 25); t_r = np.arange(rack_len) / sr; rack = np.sin(2 * np.pi * f_rack * t_r) * np.exp(-t_r * 60) * 0.25
            click = rng.randn(min(40, rack_len)) * np.exp(-np.linspace(0, 800, min(40, rack_len))) * 0.20; click = np.pad(click, (0, max(0, rack_len - len(click)))); buf = np.zeros(n, dtype=np.float64)
            buf[rack_delay:rack_delay + rack_len] = rack + click
        else:
            buf = np.zeros(n, dtype=np.float64); out = crack + boom + buf; out = _butter_lowpass(out, 0.32, 1)
        return self._to_int16(out)

    def _gunshot_rifle(self, v=0):
        """Rifle shot — sharp crack + long echo."""
        sr, dur = self.sample_rate, 0.20; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 400); pitch = 1.0 + v * 0.04; crack_len = min(200, n)
        crack = rng.randn(crack_len) * np.exp(-np.linspace(0, 800, crack_len)) * 0.35; crack = np.pad(crack, (0, n - len(crack))); f_boom = 90 * pitch + rng.randint(-8, 8)
        boom = np.sin(2 * np.pi * f_boom * t) * _env_adsr(t, 0.002, 0.02, 0.22, 0.06, delay=0.004) * 0.50; f_echo = 100 * pitch + rng.randint(-8, 8)
        echo = np.sin(2 * np.pi * f_echo * t) * _env_adsr(t, 0.02, 0.04, 0.15, 0.08, delay=0.04) * 0.25; bolt_delay = int(0.10 * sr)
        if bolt_delay + 40 < n:
            f_bolt = 3500 + rng.randint(-200, 200); t_b = np.arange(40) / sr; bolt = np.sin(2 * np.pi * f_bolt * t_b) * np.exp(-t_b * 250) * 0.15; buf = np.zeros(n, dtype=np.float64)
            buf[bolt_delay:bolt_delay + 40] = bolt
        else:
            buf = np.zeros(n, dtype=np.float64); out = crack + boom + echo + buf; out = _butter_lowpass(out, 0.36, 1)
        return self._to_int16(out)

    def _gunshot_burst(self, v=0):
        """Burst fire — 3 rapid shots."""
        sr, dur = self.sample_rate, 0.25; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 500); out = np.zeros(n, dtype=np.float64)
        for i in range(3):
            delay = int(i * 0.06 * sr); seg_len = min(int(0.08 * sr), n - delay)
            if seg_len <= 0:
                continue
            t_seg = np.arange(seg_len) / sr; crack = rng.randn(min(80, seg_len)) * np.exp(-np.linspace(0, 1500, min(80, seg_len))) * 0.30; crack = np.pad(crack, (0, max(0, seg_len - len(crack))))
            f_boom = 90 + rng.randint(-8, 8); boom = np.sin(2 * np.pi * f_boom * t_seg) * _env_adsr(t_seg, 0.002, 0.015, 0.15, 0.03, delay=0.003) * 0.45; seg = crack + boom; buf = np.zeros(n, dtype=np.float64)
            buf[delay:delay + seg_len] = seg; out += buf; out = _butter_lowpass(out, 0.36, 1)
        return self._to_int16(out)

    def _gunshot_cannon(self, v=0):
        """Cannon — massive deep boom with long decay."""
        sr, dur = self.sample_rate, 0.40; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 600); crack_len = min(400, n)
        crack = rng.randn(crack_len) * np.exp(-np.linspace(0, 300, crack_len)) * 0.35; crack = np.pad(crack, (0, n - len(crack))); f_boom = 40 + rng.randint(-4, 4)
        boom = np.sin(2 * np.pi * f_boom * t) * _env_adsr(t, 0.005, 0.04, 0.40, 0.12, delay=0.008) * 0.65; f_shock = 200 + rng.randint(-15, 15)
        shock = np.sin(2 * np.pi * f_shock * t) * _env_adsr(t, 0.003, 0.02, 0.18, 0.06, delay=0.005) * 0.30
        rumble = _butter_lowpass(rng.randn(n), 0.08, 2) * _env_adsr(t, 0.01, 0.05, 0.30, 0.12, delay=0.02) * 0.20; out = crack + boom + shock + rumble; out = _butter_lowpass(out, 0.30, 1)
        out = np.nan_to_num(out, 0.0); return self._to_int16(out)

    def _gunshot_silenced_hit(self, v=0):
        """Silenced pistol — quiet mechanical action (used in Gunshot profile for backspace)."""
        sr, dur = self.sample_rate, 0.06; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 700); f_pop = 300 + rng.randint(-25, 25)
        pop = np.sin(2 * np.pi * f_pop * t) * _env_adsr(t, 0.001, 0.008, 0.10, 0.02) * 0.35; f_mech = 2000 + rng.randint(-150, 150); mech = np.sin(2 * np.pi * f_mech * t) * np.exp(-t * 300) * 0.15
        gas = _butter_lowpass(rng.randn(n), 0.12, 2) * np.exp(-t * 120) * 0.20; out = pop + mech + gas
        return self._to_int16(out)

    def _silenced_builders(self):
        b = self
        return { "key":           (b._silenced_key, 6), "heavy_thump":   (b._silenced_heavy, 3), "medium_thump":  (b._silenced_medium, 4), "triple_tap":    (b._silenced_triple, 3), "deep_boom":     (b._silenced_deep, 3), "gas_leak":      (b._silenced_gas_leak, 3), "soft_pfft":     (b._silenced_soft, 4), "low_pop":       (b._silenced_pop, 4),
        }

    def _silenced_key(self, v=0):
        """Suppressed shot — quiet pop + gas hiss."""
        sr, dur = self.sample_rate, 0.08; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v); pitch = 1.0 + (v - 2.5) * 0.05; f_pop = 200 * pitch + rng.randint(-15, 15)
        pop = np.sin(2 * np.pi * f_pop * t) * _env_adsr(t, 0.001, 0.008, 0.10, 0.02) * 0.40; gas = _svf_resonant_noise(n, rng, freq=800, q=1.5, sr=sr, decay=100) * 0.25
        f_mech = 1800 + rng.randint(-150, 150); mech = np.sin(2 * np.pi * f_mech * t) * np.exp(-t * 250) * 0.10; out = pop + gas + mech
        return self._to_int16(out)

    def _silenced_soft(self, v=0):
        """Soft pfft — very quiet, subtle."""
        sr, dur = self.sample_rate, 0.06; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 100); f_pop = 250 + rng.randint(-20, 20)
        pop = np.sin(2 * np.pi * f_pop * t) * np.exp(-t * 150) * 0.35; gas = _butter_lowpass(rng.randn(n), 0.12, 2) * np.exp(-t * 130) * 0.22; out = pop + gas
        return self._to_int16(out)

    def _silenced_pop(self, v=0):
        """Low pop — slightly louder suppressed shot."""
        sr, dur = self.sample_rate, 0.07; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 200); f_pop = 180 + rng.randint(-15, 15)
        pop = np.sin(2 * np.pi * f_pop * t) * _env_adsr(t, 0.001, 0.010, 0.12, 0.02) * 0.42; gas = _butter_lowpass(rng.randn(n), 0.13, 2) * np.exp(-t * 110) * 0.25; f_mech = 1500 + rng.randint(-120, 120)
        mech = np.sin(2 * np.pi * f_mech * t) * np.exp(-t * 280) * 0.08; out = pop + gas + mech
        return self._to_int16(out)

    def _silenced_medium(self, v=0):
        """Medium thump — suppressed but noticeable."""
        sr, dur = self.sample_rate, 0.09; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 300); f_thump = 150 + rng.randint(-12, 12)
        thump = np.sin(2 * np.pi * f_thump * t) * _env_adsr(t, 0.002, 0.012, 0.15, 0.03, delay=0.004) * 0.50; gas = _butter_lowpass(rng.randn(n), 0.14, 2) * np.exp(-t * 90) * 0.28
        f_mech = 1600 + rng.randint(-120, 120); mech = np.sin(2 * np.pi * f_mech * t) * np.exp(-t * 220) * 0.10; out = thump + gas + mech
        return self._to_int16(out)

    def _silenced_heavy(self, v=0):
        """Heavy thump — suppressed large caliber."""
        sr, dur = self.sample_rate, 0.12; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 400); f_thump = 100 + rng.randint(-8, 8)
        thump = np.sin(2 * np.pi * f_thump * t) * _env_adsr(t, 0.003, 0.018, 0.20, 0.04, delay=0.006) * 0.55; f_sub = 50 + rng.randint(-4, 4)
        sub = np.sin(2 * np.pi * f_sub * t) * _env_adsr(t, 0.005, 0.025, 0.18, 0.05, delay=0.010) * 0.35; gas = _svf_resonant_noise(n, rng, freq=600, q=1.2, sr=sr, decay=70) * 0.22; out = thump + sub + gas
        out = np.nan_to_num(out, 0.0); return self._to_int16(out)

    def _silenced_deep(self, v=0):
        """Deep boom — suppressed but powerful."""
        sr, dur = self.sample_rate, 0.18; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 500); f_boom = 65 + rng.randint(-5, 5)
        boom = np.sin(2 * np.pi * f_boom * t) * _env_adsr(t, 0.004, 0.02, 0.25, 0.06, delay=0.008) * 0.60; gas = _svf_resonant_noise(n, rng, freq=500, q=1.0, sr=sr, decay=40) * 0.25
        gas *= _env_adsr(t, 0.006, 0.03, 0.20, 0.06, delay=0.008); f_slide = 1200 + rng.randint(-100, 100)
        slide = np.sin(2 * np.pi * f_slide * t) * np.exp(-np.maximum(0, t - 0.06) * 150) * (t >= 0.06).astype(float) * 0.12; out = boom + gas + slide; out = np.nan_to_num(out, 0.0)
        return self._to_int16(out)

    def _silenced_triple(self, v=0):
        """Triple tap — three quick suppressed pops."""
        sr, dur = self.sample_rate, 0.18; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 600); out = np.zeros(n, dtype=np.float64)
        for i in range(3):
            delay = int(i * 0.045 * sr); seg_len = min(int(0.06 * sr), n - delay)
            if seg_len <= 0:
                continue
            t_seg = np.arange(seg_len) / sr; f = 200 + rng.randint(-15, 15); pop = np.sin(2 * np.pi * f * t_seg) * _env_adsr(t_seg, 0.001, 0.008, 0.10, 0.02) * 0.38
            gas = _butter_lowpass(rng.randn(seg_len), 0.14, 2) * np.exp(-t_seg * 120) * 0.18; seg = pop + gas; buf = np.zeros(n, dtype=np.float64); buf[delay:delay + seg_len] = seg; out += buf
        return self._to_int16(out)

    def _silenced_gas_leak(self, v=0):
        """Gas leak — long, slow hiss (for Escape/backspace)."""
        sr, dur = self.sample_rate, 0.15; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 700)
        gas = _butter_lowpass(rng.randn(n), 0.10, 2) * _env_adsr(t, 0.01, 0.04, 0.3, 0.05) * 0.30; f_tone = 80 + rng.randint(-6, 6); tone = np.sin(2 * np.pi * f_tone * t) * np.exp(-t * 50) * 0.15
        out = gas + tone; return self._to_int16(out)

    def _crystal_bowl_builders(self):
        b = self
        return { "key":            (b._crystal_bowl_key, 8), "full_bowl":      (b._crystal_bowl_full, 3), "deep_ring":      (b._crystal_bowl_deep_ring, 4), "shimmer_sweep":  (b._crystal_bowl_shimmer_sweep, 3), "dissonant":      (b._crystal_bowl_dissonant, 3), "fade_out":       (b._crystal_bowl_fade_out, 3), "harmonic_a":     (b._crystal_bowl_harmonic_a, 4), "harmonic_b":     (b._crystal_bowl_harmonic_b, 4), "chime":          (b._crystal_bowl_chime, 4), "sparkle":        (b._crystal_bowl_sparkle, 4),
        }

    def _crystal_bowl_key(self, v=0):
        """Crystal bowl tap — glass-like harmonic ring with shimmer."""
        sr, dur = self.sample_rate, 0.22; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v); pitch = 1.0 + (v - 3.5) * 0.08; f0 = 880 * pitch + rng.randint(-20, 20)
        modes = _bell_modes(f0, n_modes=6, rng=rng); modes = [(f, a * 0.7, d, p) for f, a, d, p in modes]; modes[0] = (modes[0][0], modes[0][1] * 0.5, modes[0][2], modes[0][3])
        bowl = _modal_impact(n, rng, modes, sr, noise_mix=0.03, noise_decay=800) * 0.50; shimmer = _svf_resonant_noise(n, rng, freq=6800 * pitch + rng.randint(-200, 200), q=6.0, sr=sr, decay=50) * 0.15
        shimmer *= _env_adsr(t, 0.002, 0.04, 0.15, 0.06, delay=0.008); f_hi = f0 * 3.17  # inharmonic partial for crystal character
        overtone = np.sin(2 * np.pi * f_hi * t) * np.exp(-t * 6.0) * 0.18
        beat1 = np.sin(2 * np.pi * f0 * 2.003 * t) * np.exp(-t * 5.5) * 0.08; beat2 = np.sin(2 * np.pi * f0 * 1.997 * t) * np.exp(-t * 5.5) * 0.08; out = bowl + shimmer + overtone + beat1 + beat2
        out = _svf_filter(out, 200, 0.707, sr, mode='hp'); out = _svf_filter(out, 11000, 0.707, sr, mode='lp'); return self._to_int16(out)

    def _crystal_bowl_full(self, v=0):
        """Full bowl strike — rich harmonic bloom (for Enter)."""
        sr, dur = self.sample_rate, 0.50; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 100); pitch = 0.85 + v * 0.10; f0 = 520 * pitch + rng.randint(-15, 15)
        modes = _bell_modes(f0, n_modes=8, rng=rng); bowl = _modal_impact(n, rng, modes, sr, noise_mix=0.02, noise_decay=600) * 0.55
        vibrato = np.sin(2 * np.pi * (f0 * 2.0) * t * (1 + 0.003 * np.sin(2 * np.pi * 5.5 * t))); vibrato *= np.exp(-t * 3.0) * 0.22
        shimmer = _svf_resonant_noise(n, rng, freq=5500 + rng.randint(-200, 200), q=5.0, sr=sr, decay=35) * 0.12; shimmer = _comb_filter(shimmer, delay_ms=5.2, feedback=0.55, sr=sr)
        b1 = np.sin(2 * np.pi * f0 * 3.01 * t) * np.exp(-t * 3.5) * 0.10; b2 = np.sin(2 * np.pi * f0 * 2.99 * t) * np.exp(-t * 3.5) * 0.10; out = bowl + vibrato + shimmer + b1 + b2
        out = _svf_filter(out, 180, 0.707, sr, mode='hp'); out = _svf_filter(out, 10500, 0.8, sr, mode='lp'); return self._to_int16(out)

    def _crystal_bowl_deep_ring(self, v=0):
        """Deep resonant ring (for Space)."""
        sr, dur = self.sample_rate, 0.35; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 200); pitch = 0.7 + v * 0.08; f0 = 380 * pitch + rng.randint(-10, 10)
        modes = _bell_modes(f0, n_modes=5, rng=rng); ring = _modal_impact(n, rng, modes, sr, noise_mix=0.02, noise_decay=500) * 0.55; sub = np.sin(2 * np.pi * f0 * 0.5 * t) * np.exp(-t * 2.5) * 0.20
        wobble = np.sin(2 * np.pi * f0 * t * (1 + 0.002 * np.sin(2 * np.pi * 3.0 * t))); wobble *= np.exp(-t * 3.0) * 0.15; out = ring + sub + wobble; out = _svf_filter(out, 120, 0.707, sr, mode='hp')
        return self._to_int16(out)

    def _crystal_bowl_shimmer_sweep(self, v=0):
        """Frequency sweep shimmer (for Tab)."""
        sr, dur = self.sample_rate, 0.30; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 300); f_start = 1200 + v * 200; f_end = 4000 + v * 300
        sweep = _frequency_sweep(dur, f_start, f_end, sr) * 0.30; sweep *= _env_adsr(t, 0.002, 0.05, 0.18, 0.08, delay=0.005); modes = _bell_modes(f_end, n_modes=4, rng=rng)
        ring = _modal_impact(n, rng, modes, sr, noise_mix=0.01, noise_decay=400) * 0.30; ring *= _env_adsr(t, 0.02, 0.04, 0.15, 0.06, delay=0.04)
        shimmer = _svf_resonant_noise(n, rng, freq=7500, q=5.0, sr=sr, decay=40) * 0.10; out = sweep + ring + shimmer; out = _svf_filter(out, 600, 0.707, sr, mode='hp')
        return self._to_int16(out)

    def _crystal_bowl_dissonant(self, v=0):
        """Dissonant cluster — trippy minor-second clash (for Escape)."""
        sr, dur = self.sample_rate, 0.40; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 400); f1 = 660 + rng.randint(-15, 15)
        f2 = f1 * 1.0595  # semitone above — maximum tension
        modes1 = _bell_modes(f1, n_modes=4, rng=rng); modes2 = _bell_modes(f2, n_modes=4, rng=rng)
        d1 = _modal_impact(n, rng, modes1, sr, noise_mix=0.01, noise_decay=500) * 0.35; d2 = _modal_impact(n, rng, modes2, sr, noise_mix=0.01, noise_decay=500) * 0.35
        tri = np.sin(2 * np.pi * f1 * 1.414 * t) * np.exp(-t * 4.0) * 0.12; out = d1 + d2 + tri; out = _svf_filter(out, 200, 0.707, sr, mode='hp')
        return self._to_int16(out)

    def _crystal_bowl_fade_out(self, v=0):
        """Reverse fade — sound that decays from nothing (for Backspace)."""
        sr, dur = self.sample_rate, 0.18; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 500); pitch = 1.0 + v * 0.06; f0 = 1100 * pitch + rng.randint(-20, 20)
        modes = _bell_modes(f0, n_modes=4, rng=rng); ring = _modal_impact(n, rng, modes, sr, noise_mix=0.02, noise_decay=1200) * 0.45; ring *= np.exp(-t * 18.0); out = ring
        out = _svf_filter(out, 400, 0.707, sr, mode='hp'); return self._to_int16(out)

    def _crystal_bowl_harmonic_a(self, v=0):
        """Pure harmonic overtone A — clean 5th above fundamental."""
        sr, dur = self.sample_rate, 0.25; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 600); f0 = 1320 + v * 80
        tone = np.sin(2 * np.pi * f0 * t) * np.exp(-t * 5.0) * 0.30; fifth = np.sin(2 * np.pi * f0 * 1.5 * t) * np.exp(-t * 6.5) * 0.20; beat = np.sin(2 * np.pi * f0 * 2.002 * t) * np.exp(-t * 7.0) * 0.10
        out = tone + fifth + beat; out = _svf_filter(out, 300, 0.707, sr, mode='hp'); return self._to_int16(out)

    def _crystal_bowl_harmonic_b(self, v=0):
        """Harmonic overtone B — major third with warble."""
        sr, dur = self.sample_rate, 0.28; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 700); f0 = 990 + v * 70
        tone = np.sin(2 * np.pi * f0 * t * (1 + 0.004 * np.sin(2 * np.pi * 6.0 * t))); tone *= np.exp(-t * 4.5) * 0.30; third = np.sin(2 * np.pi * f0 * 1.25 * t) * np.exp(-t * 6.0) * 0.18; out = tone + third
        out = _svf_filter(out, 250, 0.707, sr, mode='hp'); return self._to_int16(out)

    def _crystal_bowl_chime(self, v=0):
        """Small crystal chime — bright, short (for digits)."""
        sr, dur = self.sample_rate, 0.15; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 800); f0 = 2200 + v * 150 + rng.randint(-50, 50)
        modes = _bell_modes(f0, n_modes=3, rng=rng); chime = _modal_impact(n, rng, modes, sr, noise_mix=0.02, noise_decay=700) * 0.55; sp = np.sin(2 * np.pi * f0 * 3.0 * t) * np.exp(-t * 12.0) * 0.10
        out = chime + sp; out = _svf_filter(out, 1000, 0.707, sr, mode='hp'); return self._to_int16(out)

    def _crystal_bowl_sparkle(self, v=0):
        """Sparkle — tiny high-pitched crystalline ping (for punctuation)."""
        sr, dur = self.sample_rate, 0.12; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 900); f0 = 3500 + v * 200 + rng.randint(-100, 100)
        ping = np.sin(2 * np.pi * f0 * t) * np.exp(-t * 10.0) * 0.35; crack = np.sin(2 * np.pi * f0 * 2.37 * t) * np.exp(-t * 14.0) * 0.15
        noise = rng.randn(min(30, n)) * np.exp(-np.linspace(0, 200, min(30, n))) * 0.12; noise = np.pad(noise, (0, max(0, n - len(noise)))); out = ping + crack + noise
        return self._to_int16(out)

    def _synth_bubble_builders(self):
        b = self
        return { "key":            (b._synth_bubble_key, 8), "whoosh":         (b._synth_bubble_whoosh, 3), "deep_bubble":    (b._synth_bubble_deep, 4), "squelch_sweep":  (b._synth_bubble_squelch_sweep, 3), "glitch":         (b._synth_bubble_glitch, 3), "deflate":        (b._synth_bubble_deflate, 3), "bubble_a":       (b._synth_bubble_a, 4), "bubble_b":       (b._synth_bubble_b, 4), "blip":           (b._synth_bubble_blip, 4), "squelch":        (b._synth_bubble_squelch, 4),
        }

    def _synth_bubble_key(self, v=0):
        """Resonant synth bubble — squelchy filtered noise sweep."""
        sr, dur = self.sample_rate, 0.14; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v); pitch = 1.0 + (v - 3.5) * 0.07; f_center = 600 * pitch + rng.randint(-30, 30)
        bubble = _svf_resonant_noise(n, rng, freq=f_center, q=8.0, sr=sr, decay=80) * 0.45; bubble *= _env_adsr(t, 0.002, 0.015, 0.06, 0.04, delay=0.003); pop_delay = int(0.025 * sr)
        if pop_delay < n:
            f_pop = 1200 * pitch + rng.randint(-60, 60); t_pop = np.arange(n - pop_delay) / sr; pop = np.sin(2 * np.pi * f_pop * t_pop) * np.exp(-t_pop * 200) * 0.20; buf = np.zeros(n, dtype=np.float64)
            buf[pop_delay:] = pop
        else:
            buf = np.zeros(n, dtype=np.float64); thud = _noise_excited_resonator(n, rng, center_freq=80 * pitch, bandwidth=200, q=2.0, sr=sr, excitation_decay=600) * 0.15
        thud *= _env_adsr(t, 0.005, 0.02, 0.08, 0.03, delay=0.002); air = _svf_resonant_noise(n, rng, freq=2800 * pitch, q=2.0, sr=sr, decay=45) * 0.08; out = bubble + buf + thud + air
        out = _svf_filter(out, 250, 0.707, sr, mode='hp'); out = _svf_filter(out, 6000, 0.707, sr, mode='lp'); return self._to_int16(out)

    def _synth_bubble_whoosh(self, v=0):
        """Whoosh — sweeping filtered noise (for Enter)."""
        sr, dur = self.sample_rate, 0.30; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 100); f_start = 200 + v * 50; f_end = 3000 + v * 200
        sweep = _frequency_sweep(dur, f_start, f_end, sr) * 0.25; sweep *= _env_adsr(t, 0.005, 0.06, 0.18, 0.08, delay=0.005); noise = _noise_shaped(n, rng, 400, 4000, sr, tilt_db=4.0) * 0.15
        noise *= _env_adsr(t, 0.005, 0.06, 0.18, 0.08, delay=0.005); bubble = _svf_resonant_noise(n, rng, freq=1800 + v * 100, q=6.0, sr=sr, decay=40) * 0.15
        bubble *= _env_adsr(t, 0.03, 0.06, 0.15, 0.06, delay=0.06); out = sweep + noise + bubble; out = _svf_filter(out, 180, 0.707, sr, mode='hp')
        return self._to_int16(out)

    def _synth_bubble_deep(self, v=0):
        """Deep bubble — lower pitched, larger (for Space)."""
        sr, dur = self.sample_rate, 0.22; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 200); pitch = 0.6 + v * 0.08
        bubble = _svf_resonant_noise(n, rng, freq=320 * pitch + rng.randint(-15, 15), q=10.0, sr=sr, decay=60) * 0.50; bubble *= _env_adsr(t, 0.003, 0.02, 0.10, 0.05, delay=0.004); pop_delay = int(0.04 * sr)
        if pop_delay < n:
            f_pop = 600 * pitch + rng.randint(-30, 30); t_pop = np.arange(n - pop_delay) / sr; pop = np.sin(2 * np.pi * f_pop * t_pop) * np.exp(-t_pop * 120) * 0.25; buf = np.zeros(n, dtype=np.float64)
            buf[pop_delay:] = pop
        else:
            buf = np.zeros(n, dtype=np.float64); sub = _noise_excited_resonator(n, rng, center_freq=55 * pitch, bandwidth=120, q=2.5, sr=sr, excitation_decay=500) * 0.18
        sub *= _env_adsr(t, 0.008, 0.025, 0.12, 0.04, delay=0.005); out = bubble + buf + sub; out = _svf_filter(out, 40, 0.707, sr, mode='hp'); out = _svf_filter(out, 5000, 0.707, sr, mode='lp')
        return self._to_int16(out)

    def _synth_bubble_squelch_sweep(self, v=0):
        """Squelch with frequency sweep (for Tab)."""
        sr, dur = self.sample_rate, 0.25; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 300); f_start = 2000 + v * 200; f_end = 300 + v * 50
        sweep = _frequency_sweep(dur, f_start, f_end, sr) * 0.30; sweep *= _env_adsr(t, 0.001, 0.03, 0.12, 0.06); squelch = _svf_resonant_noise(n, rng, freq=f_end + 200, q=12.0, sr=sr, decay=55) * 0.30
        squelch *= _env_adsr(t, 0.003, 0.04, 0.14, 0.06, delay=0.01); out = sweep + squelch; out = _svf_filter(out, 200, 0.707, sr, mode='hp')
        return self._to_int16(out)

    def _synth_bubble_glitch(self, v=0):
        """Digital glitch — stuttering micro-slices (for Escape)."""
        sr, dur = self.sample_rate, 0.20; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 400); out = np.zeros(n, dtype=np.float64)
        for i in range(4):
            delay = int(i * 0.035 * sr); seg_len = min(int(0.04 * sr), n - delay)
            if seg_len <= 0:
                continue
            t_seg = np.arange(seg_len) / sr; f = 400 + rng.randint(0, 2000); bub = _svf_resonant_noise(seg_len, rng, freq=f, q=8.0, sr=sr, decay=30) * 0.35
            bub *= _env_adsr(t_seg, 0.001, 0.008, 0.02, 0.01); buf = np.zeros(n, dtype=np.float64); buf[delay:delay + seg_len] = bub; out += buf
        crash = rng.randn(min(60, n)) * np.exp(-np.linspace(0, 400, min(60, n))) * 0.15; crash = np.pad(crash, (0, max(0, n - len(crash)))); out += crash
        return self._to_int16(out)

    def _synth_bubble_deflate(self, v=0):
        """Deflating bubble — pitch drops rapidly (for Backspace)."""
        sr, dur = self.sample_rate, 0.16; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 500); f_start = 1500 + v * 100; f_end = 80 + v * 10
        deflation = _frequency_sweep(dur, f_start, f_end, sr) * 0.35; deflation *= _env_adsr(t, 0.001, 0.02, 0.10, 0.05); noise = _svf_resonant_noise(n, rng, freq=900, q=3.0, sr=sr, decay=60) * 0.15
        noise *= _env_adsr(t, 0.005, 0.03, 0.10, 0.04, delay=0.02); out = deflation + noise; out = _svf_filter(out, 60, 0.707, sr, mode='hp')
        return self._to_int16(out)

    def _synth_bubble_a(self, v=0):
        """Small bubble A — higher pitch, quicker (for quotes)."""
        sr, dur = self.sample_rate, 0.10; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 600); f = 1200 + v * 100 + rng.randint(-50, 50)
        bub = _svf_resonant_noise(n, rng, freq=f, q=9.0, sr=sr, decay=70) * 0.50; bub *= _env_adsr(t, 0.001, 0.012, 0.05, 0.03); pop_d = int(0.02 * sr)
        if pop_d < n:
            t_p = np.arange(n - pop_d) / sr; pop = np.sin(2 * np.pi * f * 2.5 * t_p) * np.exp(-t_p * 250) * 0.18; buf = np.zeros(n, dtype=np.float64); buf[pop_d:] = pop
        else:
            buf = np.zeros(n, dtype=np.float64); out = bub + buf
        return self._to_int16(out)

    def _synth_bubble_b(self, v=0):
        """Bubble B — medium pitch, fatter (for brackets)."""
        sr, dur = self.sample_rate, 0.12; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 700); f = 800 + v * 80 + rng.randint(-40, 40)
        bub = _svf_resonant_noise(n, rng, freq=f, q=10.0, sr=sr, decay=55) * 0.50; bub *= _env_adsr(t, 0.002, 0.015, 0.06, 0.03, delay=0.002); pop_d = int(0.025 * sr)
        if pop_d < n:
            t_p = np.arange(n - pop_d) / sr; pop = np.sin(2 * np.pi * f * 2.0 * t_p) * np.exp(-t_p * 180) * 0.20; buf = np.zeros(n, dtype=np.float64); buf[pop_d:] = pop
        else:
            buf = np.zeros(n, dtype=np.float64); out = bub + buf
        return self._to_int16(out)

    def _synth_bubble_blip(self, v=0):
        """Blip — very short synth beep (for digits)."""
        sr, dur = self.sample_rate, 0.06; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 800); f = 1800 + v * 120 + rng.randint(-60, 60)
        blip = np.sin(2 * np.pi * f * t) * np.exp(-t * 60) * 0.40; blip2 = np.sin(2 * np.pi * f * 1.005 * t) * np.exp(-t * 55) * 0.15; out = blip + blip2
        return self._to_int16(out)

    def _synth_bubble_squelch(self, v=0):
        """Squelch — wet, resonant pop (for punctuation)."""
        sr, dur = self.sample_rate, 0.09; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 900); f = 700 + v * 60 + rng.randint(-30, 30)
        squelch = _svf_resonant_noise(n, rng, freq=f, q=12.0, sr=sr, decay=55) * 0.50; squelch *= _env_adsr(t, 0.001, 0.010, 0.04, 0.02)
        sub = _noise_excited_resonator(n, rng, center_freq=120, bandwidth=200, q=2.0, sr=sr, excitation_decay=800) * 0.12; out = squelch + sub
        return self._to_int16(out)

    def _tibetan_bowl_builders(self):
        b = self
        return { "key":            (b._tibetan_bowl_key, 8), "large_bowl":     (b._tibetan_bowl_large, 3), "bass_bowl":      (b._tibetan_bowl_bass, 4), "harmonic_tap":   (b._tibetan_bowl_harmonic_tap, 3), "deep_gong":      (b._tibetan_bowl_gong, 3), "mallet_damp":    (b._tibetan_bowl_mallet_damp, 3), "overtone_a":     (b._tibetan_bowl_overtone_a, 4), "overtone_b":     (b._tibetan_bowl_overtone_b, 4), "small_bell":     (b._tibetan_bowl_small_bell, 4), "rim_tap":        (b._tibetan_bowl_rim_tap, 4),
        }

    def _tibetan_bowl_key(self, v=0):
        """Tibetan bowl tap — deep harmonic ring with slow decay."""
        sr, dur = self.sample_rate, 0.35; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v); pitch = 1.0 + (v - 3.5) * 0.06; f0 = 290 * pitch + rng.randint(-8, 8)
        modes = _bell_modes(f0, n_modes=7, rng=rng); modes = [(f, a * (1.3 if i < 2 else 0.8), d, p) for i, (f, a, d, p) in enumerate(modes)]
        bowl = _modal_impact(n, rng, modes, sr, noise_mix=0.02, noise_decay=400) * 0.55
        thock = _noise_excited_resonator(n, rng, center_freq=1800 * pitch, bandwidth=3000, q=2.0, sr=sr, excitation_decay=2000) * 0.12
        thock *= _env_adsr(t, 0.0005, 0.005, 0.01, 0.005); sub = np.sin(2 * np.pi * f0 * 0.5 * t) * np.exp(-t * 2.0) * 0.15; vibrato_depth = 0.002 + v * 0.0003; vibrato_rate = 4.5 + v * 0.2
        vib = np.sin(2 * np.pi * f0 * t * (1 + vibrato_depth * np.sin(2 * np.pi * vibrato_rate * t))); vib *= np.exp(-t * 2.5) * 0.12; out = bowl + thock + sub + vib
        out = _svf_filter(out, 80, 0.707, sr, mode='hp'); out = _svf_filter(out, 8000, 0.707, sr, mode='lp'); return self._to_int16(out)

    def _tibetan_bowl_large(self, v=0):
        """Large bowl strike — long, deep, meditative (for Enter)."""
        sr, dur = self.sample_rate, 0.70; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 100); pitch = 0.8 + v * 0.08; f0 = 180 * pitch + rng.randint(-5, 5)
        modes = _bell_modes(f0, n_modes=8, rng=rng); modes = [(f, a * (1.4 if i < 2 else 0.7), d, p) for i, (f, a, d, p) in enumerate(modes)]
        bowl = _modal_impact(n, rng, modes, sr, noise_mix=0.01, noise_decay=350) * 0.60; thud = _noise_excited_resonator(n, rng, center_freq=1200, bandwidth=2500, q=1.5, sr=sr, excitation_decay=2500) * 0.10
        thud *= _env_adsr(t, 0.001, 0.008, 0.015, 0.008); drone = np.sin(2 * np.pi * f0 * 0.5 * t) * np.exp(-t * 1.2) * 0.22; vib = np.sin(2 * np.pi * f0 * t * (1 + 0.003 * np.sin(2 * np.pi * 3.5 * t)))
        vib *= np.exp(-t * 1.5) * 0.15; b1 = np.sin(2 * np.pi * f0 * 2.005 * t) * np.exp(-t * 2.0) * 0.08; b2 = np.sin(2 * np.pi * f0 * 1.995 * t) * np.exp(-t * 2.0) * 0.08
        out = bowl + thud + drone + vib + b1 + b2; out = _svf_filter(out, 50, 0.707, sr, mode='hp'); out = _svf_filter(out, 7500, 0.707, sr, mode='lp'); return self._to_int16(out)

    def _tibetan_bowl_bass(self, v=0):
        """Bass bowl — deep and warm (for Space)."""
        sr, dur = self.sample_rate, 0.50; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 200); pitch = 0.65 + v * 0.06; f0 = 140 * pitch + rng.randint(-4, 4)
        modes = _bell_modes(f0, n_modes=5, rng=rng); bowl = _modal_impact(n, rng, modes, sr, noise_mix=0.01, noise_decay=300) * 0.55; sub = np.sin(2 * np.pi * f0 * 0.5 * t) * np.exp(-t * 1.5) * 0.25
        vib = np.sin(2 * np.pi * f0 * t * (1 + 0.003 * np.sin(2 * np.pi * 4.0 * t))); vib *= np.exp(-t * 2.0) * 0.12; out = bowl + sub + vib; out = _svf_filter(out, 40, 0.707, sr, mode='hp')
        out = _svf_filter(out, 6000, 0.707, sr, mode='lp'); return self._to_int16(out)

    def _tibetan_bowl_harmonic_tap(self, v=0):
        """Harmonic tap — emphasises upper partials (for Tab)."""
        sr, dur = self.sample_rate, 0.30; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 300); f0 = 350 + v * 30 + rng.randint(-10, 10)
        modes = _bell_modes(f0, n_modes=6, rng=rng); modes = [(f, a * (0.4 if i < 2 else 1.2), d, p) for i, (f, a, d, p) in enumerate(modes)]
        ring = _modal_impact(n, rng, modes, sr, noise_mix=0.01, noise_decay=350) * 0.50; tap = _fm_click(t, f_carrier=2800, f_mod=1400, mod_index=1.5, rng=rng, decay=600, detune=100)
        tap *= _env_adsr(t, 0.0005, 0.005, 0.01, 0.005) * 0.20; out = ring + tap; out = _svf_filter(out, 150, 0.707, sr, mode='hp')
        return self._to_int16(out)

    def _tibetan_bowl_gong(self, v=0):
        """Deep gong — massive, long decay (for Escape)."""
        sr, dur = self.sample_rate, 0.90; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 400); f0 = 100 + rng.randint(-3, 3)
        modes = _bell_modes(f0, n_modes=9, rng=rng); gong = _modal_impact(n, rng, modes, sr, noise_mix=0.01, noise_decay=250) * 0.55
        thud = _noise_excited_resonator(n, rng, center_freq=80, bandwidth=300, q=2.0, sr=sr, excitation_decay=400) * 0.25; thud *= _env_adsr(t, 0.003, 0.02, 0.20, 0.10, delay=0.005)
        drone = np.sin(2 * np.pi * f0 * 0.5 * t) * np.exp(-t * 0.8) * 0.20; out = gong + thud + drone; out = _svf_filter(out, 35, 0.707, sr, mode='hp'); out = _svf_filter(out, 6000, 0.707, sr, mode='lp')
        return self._to_int16(out)

    def _tibetan_bowl_mallet_damp(self, v=0):
        """Mallet damp — quick thud, short decay (for Backspace)."""
        sr, dur = self.sample_rate, 0.12; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 500); f0 = 300 + v * 20 + rng.randint(-10, 10)
        modes = _bell_modes(f0, n_modes=3, rng=rng); tap = _modal_impact(n, rng, modes, sr, noise_mix=0.03, noise_decay=1500) * 0.50; tap *= np.exp(-t * 15.0)  # rapid damping
        thud = _noise_excited_resonator(n, rng, center_freq=200, bandwidth=800, q=1.5, sr=sr, excitation_decay=2000) * 0.20; thud *= _env_adsr(t, 0.001, 0.008, 0.03, 0.02); out = tap + thud
        out = _svf_filter(out, 100, 0.707, sr, mode='hp'); return self._to_int16(out)

    def _tibetan_bowl_overtone_a(self, v=0):
        """Overtone A — singing bowl's upper harmonic (for quotes)."""
        sr, dur = self.sample_rate, 0.30; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 600); f0 = 580 + v * 40 + rng.randint(-15, 15)
        modes = _bell_modes(f0, n_modes=5, rng=rng); modes = [(f, a * (0.3 if i == 0 else 1.0), d, p) for i, (f, a, d, p) in enumerate(modes)]
        ring = _modal_impact(n, rng, modes, sr, noise_mix=0.01, noise_decay=350) * 0.45; vib = np.sin(2 * np.pi * f0 * 2.0 * t * (1 + 0.002 * np.sin(2 * np.pi * 5.0 * t))); vib *= np.exp(-t * 3.5) * 0.15
        out = ring + vib; out = _svf_filter(out, 200, 0.707, sr, mode='hp'); return self._to_int16(out)

    def _tibetan_bowl_overtone_b(self, v=0):
        """Overtone B — another harmonic, slightly different character (for brackets)."""
        sr, dur = self.sample_rate, 0.28; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 700); f0 = 440 + v * 35 + rng.randint(-12, 12)
        modes = _bell_modes(f0, n_modes=5, rng=rng); ring = _modal_impact(n, rng, modes, sr, noise_mix=0.01, noise_decay=300) * 0.45; b1 = np.sin(2 * np.pi * f0 * 3.003 * t) * np.exp(-t * 3.0) * 0.10
        b2 = np.sin(2 * np.pi * f0 * 2.997 * t) * np.exp(-t * 3.0) * 0.10; out = ring + b1 + b2; out = _svf_filter(out, 150, 0.707, sr, mode='hp')
        return self._to_int16(out)

    def _tibetan_bowl_small_bell(self, v=0):
        """Small bell — bright, clear (for digits)."""
        sr, dur = self.sample_rate, 0.18; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 800); f0 = 1100 + v * 80 + rng.randint(-30, 30)
        modes = _bell_modes(f0, n_modes=4, rng=rng); bell = _modal_impact(n, rng, modes, sr, noise_mix=0.02, noise_decay=500) * 0.55
        transient = _fm_click(t, f_carrier=3000, f_mod=1500, mod_index=1.2, rng=rng, decay=800, detune=80); transient *= _env_adsr(t, 0.0005, 0.005, 0.01, 0.005) * 0.15; out = bell + transient
        out = _svf_filter(out, 400, 0.707, sr, mode='hp'); return self._to_int16(out)

    def _tibetan_bowl_rim_tap(self, v=0):
        """Rim tap — metallic, bright (for punctuation)."""
        sr, dur = self.sample_rate, 0.15; n = int(sr * dur); t = np.linspace(0, dur, n, False); rng = np.random.RandomState(v + 900); f0 = 2200 + v * 100 + rng.randint(-80, 80)
        modes = _metal_plate_modes(f0, n_modes=5, rng=rng); rim = _modal_impact(n, rng, modes, sr, noise_mix=0.03, noise_decay=600) * 0.45; crack_len = min(40, n)
        crack = rng.randn(crack_len) * np.exp(-np.linspace(0, 1500, crack_len)) * 0.15; crack = np.pad(crack, (0, max(0, n - len(crack)))); body_modes = _bell_modes(f0 * 0.25, n_modes=3, rng=rng)
        body = _modal_impact(n, rng, body_modes, sr, noise_mix=0.01, noise_decay=300) * 0.15; out = rim + crack + body; out = _svf_filter(out, 300, 0.707, sr, mode='hp')
        return self._to_int16(out)

    def _category_for(self, char):
        """Dispatch a character to the right sound category."""
        cmap = self._CATEGORY_MAPS.get(self.profile, {})
        if cmap:
            if char == "\n":
                return cmap.get("\n", "key")
            if char == " ":
                return cmap.get(" ", "key")
            if char == "\t":
                return cmap.get("\t", "key")
            if char == "\x1b":
                return cmap.get("\x1b", "key")
            if char == "\b":
                return cmap.get("\b", "key")
            if char in "'\"`":
                return cmap.get("'\"`", "key")
            if char in "()[]{}":
                return cmap.get("()[]{}", "key")
            if char.isdigit():
                return cmap.get("digit", "key")
            if char in ".;:,!?":
                return cmap.get(".;:,!?", "key")
            return "key"
        if char == "\n":
            return "enter"
        if char == " ":
            return "space"
        if char == "\t":
            return "tab"
        if char == "\x1b":
            return "escape"
        if char == "\b":
            return "backspace"
        if char in "'\"`":
            return "quote"
        if char in "()[]{}":
            return "bracket"
        if char.isdigit():
            return "digit"
        if char in ".;:,!?":
            return "punctuation"
        return "key"

    def get_sound(self, char):
        """Pick a random variant of the sound matching the given character."""
        category = self._category_for(char); sounds = self.sounds.get(category) or self.sounds["key"]
        return random.choice(sounds)

    @staticmethod
    def save_wav(path: str, signal: np.ndarray, sr=44100, volume: float = 0.5, channels: int = 1) -> None:
        """Write an int16 signal to a WAV file (mono or stereo)."""
        scaled = np.clip(signal.astype(np.float64) * volume, -32768, 32767).astype(np.int16)
        with wave.open(path, "w") as w:
            w.setnchannels(channels); w.setsampwidth(2); w.setframerate(sr); w.writeframes(scaled.tobytes())

    def generate_audio_track( self, char_timestamps: List[Tuple[float, str]], filepath: str, volume: float = 0.5,
    ) -> None:
        """Mix a full stereo audio track aligned to ``char_timestamps``.
        v3 mix bus improvements:
          - Convolution reverb (synthetic IR) replaces simple delay-line; reverb for much more realistic spatial depth.; - Per-sound micro-convolution: each keystroke gets a tiny room
            imprint before hitting the mix bus, so even rapid typing; sounds like it's in a real room.; - Frequency-dependent panning: low frequencies are panned
            less aggressively than highs (bass is omnidirectional).; - Mid-side stereo enhancement for a wider, more immersive image.; - Peak limiter with envelope follower replaces simple tanh
            clipping — preserves transient punch while preventing; digital overs.; - Stereo room tone with subtle cross-delay for depth.
          - Per-channel spectral tilt for natural warmth.
        """
        if not char_timestamps:
            return
        sr = self.sample_rate; total = max(ts for ts, _ in char_timestamps) + 0.5; n = int(sr * total); ir = _generate_ir(sr, duration=0.08, room_size=0.45, damping=0.65)
        mix_mem_mb = n * 4 * 2 / (1024 * 1024)  # float32, 2 channels
        self.logger.info( "Audio mix buffers: %d samples (%.1f s), %.1f MB (float32)", n, total, mix_mem_mb,
        )
        audio_l = np.zeros(n, dtype=np.float32); audio_r = np.zeros(n, dtype=np.float32)
        for ts, ch in char_timestamps:
            snd = self.get_sound(ch); s = int(ts * sr); e = min(s + len(snd), n)
            if s >= n:
                continue
            chunk = snd[:e - s].astype(np.float32); pan = _KEY_POSITIONS.get(ch.lower(), 0.0); pan = max(-1.0, min(1.0, pan)); chunk_rev = _fft_convolve(chunk, ir * 0.35)  # wet signal
            pan_rev = pan * 0.5  # reverb is more omnidirectional
            gain_l_rev = np.cos((pan_rev + 1) * np.pi / 4); gain_r_rev = np.sin((pan_rev + 1) * np.pi / 4)
            gain_l = np.cos((pan + 1) * np.pi / 4)
            gain_r = np.sin((pan + 1) * np.pi / 4); chunk_scaled = chunk * volume; chunk_rev_scaled = chunk_rev * volume * 0.3  # reverb level
            sl = slice(s, e)
            mix_l = chunk_scaled * gain_l + chunk_rev_scaled * gain_l_rev; mix_r = chunk_scaled * gain_r + chunk_rev_scaled * gain_r_rev
            audio_l[sl] += mix_l; audio_r[sl] += mix_r
        audio_l = _peak_limiter(audio_l, sr, ceiling_db=-1.5, release_ms=40.0); audio_r = _peak_limiter(audio_r, sr, ceiling_db=-1.5, release_ms=40.0)
        stereo = np.empty(n * 2, dtype=np.int16); stereo[0::2] = np.clip(audio_l, -32768, 32767).astype(np.int16); stereo[1::2] = np.clip(audio_r, -32768, 32767).astype(np.int16)
        stereo = _mid_side_enhance(stereo, width=1.25)
        ROOM_CHUNK = 4_000_000  # ~90s per chunk
        room_l_full = np.zeros(n, dtype=np.float32); room_r_full = np.zeros(n, dtype=np.float32)
        cross_delay = int(0.004 * sr)  # 4ms cross-delay
        for cs in range(0, n, ROOM_CHUNK):
            ce = min(cs + ROOM_CHUNK, n); cn = ce - cs; rl = _pink_noise(cn, sr, seed=42 + cs).astype(np.float32); rr = _pink_noise(cn, sr, seed=12345 + cs).astype(np.float32)
            if cs > 0 and cross_delay < cn:
                rr[cross_delay:] += rr[:-cross_delay] * 0.5; room_l_full[cs:ce] += rl * 0.35; room_r_full[cs:ce] += rr * 0.65
        room_contrib = np.empty(n * 2, dtype=np.int16)
        room_contrib[0::2] = np.clip(room_l_full * volume * 0.12 * 32767, -32768, 32767).astype(np.int16); room_contrib[1::2] = np.clip(room_r_full * volume * 0.12 * 32767, -32768, 32767).astype(np.int16)
        del room_l_full, room_r_full  # free ~3.6 GB (was float64)
        stereo = np.clip(stereo.astype(np.int32) + room_contrib.astype(np.int32), -32768, 32767).astype(np.int16)
        self.save_wav(filepath, stereo, sr, 1.0, channels=2)

# ======================================================================
# animator.py
# ======================================================================

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

Event = Tuple[float, int, str]

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
for _ch in list("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    _QWERTY_POS[_ch] = _QWERTY_POS[_ch.lower()]
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

def _key_distance(a: str, b):
    """Approximate physical distance between two keys on a QWERTY layout."""
    pa = _QWERTY_POS.get(a.lower())
    pb = _QWERTY_POS.get(b.lower())
    if pa is None or pb is None:
        return 10.0
    return math.hypot(pa[0] - pb[0], pa[1] - pb[1])

class TypingStats(NamedTuple):
    """Snapshot of typing metrics at a single point in time."""
    elapsed: float
    chars_typed: int
    keystrokes: int
    correct_keystrokes: int
    wpm: float
    accuracy: float

class TypingAnimator:
    """Pre-compute a typing timeline and answer "how many chars are visible at time t"."""

    PAUSE_KEYWORDS = ( "def ", "class ", "import ", "from ", "return ", "if ", "for ", "while ", "with ", "try:", "except ", "function ", "const ", "let ", "var ", "public ", "private ", "func ", "fn ", "package ",
    )

    _KW_FIRST_CHARS: frozenset = frozenset(kw[0] for kw in PAUSE_KEYWORDS)

    STRUCTURAL_PAUSES: Dict[str, Tuple[float, float, float]] = { "\n": (0.18, 0.55, 0.55),   # line end ":":  (0.15, 0.45, 0.45),   # block opener "=":  (0.08, 0.25, 0.25),   # assignment "(":  (0.06, 0.18, 0.20),   # call opener
    }

    SENTENCE_FINAL = {".", "!", "?"}

    def __init__( self, code: str, base_wpm: int = 120, humanize: bool = True, typo_rate: float = 0.015, start_pause: float = 0.5, end_pause: float = 1.5, seed: Optional[int] = None, speed_ramp: str = "None", ramp_strength: float = 0.5, burst_typing: bool = True, thinking_pauses: bool = True, fatigue: float = 0.0,
    ) -> None:
        """
        Parameters; ----------; speed_ramp : {"None", "Ease In", "Ease Out", "Ease In-Out"}; Optionally slow the typing rate at the start and/or end of; the clip for a cinematic effect.
        ramp_strength : float in [0, 1]; How strongly the ramp affects timing. 0 = no effect, 1 =; typing is 3x slower at the ramped endpoints.; burst_typing : bool
            If True (default), typing comes in rolls of 2-6 fast; keystrokes separated by short micro-pauses, matching the; rhythm of real typing.; thinking_pauses : bool
            If True (default), occasionally insert a 0.4-1.6s "thinking"; pause at structural boundaries.; fatigue : float in [0, 1]; 0 = no fatigue; 1 = typing is ~40% slower by the end of a
            long clip. Useful for long-form (10+ minute) typing videos.
        """
        self.logger = logging.getLogger("TypingAnimator")
        self.code = code; self.base_wpm = base_wpm; self.humanize = humanize; self.typo_rate = typo_rate; self.start_pause = start_pause; self.end_pause = end_pause
        self.speed_ramp = speed_ramp if speed_ramp in ( "None", "Ease In", "Ease Out", "Ease In-Out"
        ) else "None"
        self.ramp_strength = max(0.0, min(1.0, ramp_strength)); self.burst_typing = burst_typing and humanize; self.thinking_pauses = thinking_pauses and humanize; self.fatigue = max(0.0, min(1.0, fatigue))
        cps = (base_wpm * 5) / 60  # 1 word = 5 chars (industry standard)
        self.base_delay = 1.0 / cps; self._keystrokes_prefix: List[int] = []; self._correct_prefix: List[int] = []
        self._resolved_prefix: List[int] = []; self._typo_indices: set[int] = set(); self.display_chars: List[str] = []; self.timeline: List[Event] = self._build_timeline(seed)
        self._timestamps: List[float] = [ts for ts, _, _ in self.timeline]; self._build_stats_prefix()

    def _build_timeline(self, seed):
        rng = random.Random(seed); t = 0.0; events: List[Event] = []; n_chars = len(self.code); roll_remaining = 0  # first character always starts a fresh roll
        for i, ch in enumerate(self.code):
            if ( self.humanize and self.typo_rate > 0 and ch not in ("\n", " ", "\t") and rng.random() < self.typo_rate
            ):
                typo_char = self._make_typo(ch, rng); self.display_chars.append(typo_char); events.append((t, len(self.display_chars) - 1, typo_char)); self._typo_indices.add(len(events) - 1)
                t += self.base_delay * rng.uniform(0.4, 0.9) * self._ramp_factor(i, n_chars); notice = rng.uniform(0.12, 0.35); t += notice * self._ramp_factor(i, n_chars); self.display_chars.append("\b")
                events.append((t, len(self.display_chars) - 1, "\b")); t += self.base_delay * rng.uniform(0.3, 0.6) * self._ramp_factor(i, n_chars); self.display_chars.append(ch)
            events.append((t, len(self.display_chars) - 1, ch)); d = self._char_delay(ch, i, rng); d *= self._ramp_factor(i, n_chars); d *= self._fatigue_factor(i, n_chars)
            if self.burst_typing:
                roll_remaining -= 1
                if roll_remaining <= 0:
                    if not (self.thinking_pauses and self._is_structural(ch, i)):
                        d += rng.uniform(0.06, 0.18); roll_remaining = self._new_roll(rng)
                else:
                    d *= rng.uniform(0.55, 0.85)
            if self.thinking_pauses:
                d += self._structural_pause(ch, i, rng)
            if self.humanize and rng.random() < 0.012:
                d += rng.uniform(0.4, 1.6); t += max(d, 0.012); sp = self.start_pause
        for i in range(len(events)):
            ts, idx, ch = events[i]; events[i] = (ts + sp, idx, ch)
        return events

    @staticmethod
    def _new_roll(rng: random.Random):
        """Return a fresh burst-typing roll length (2-6 keystrokes)."""
        return rng.randint(2, 6)

    def _fatigue_factor(self, i: int, n):
        """Return a multiplier in [1, 1 + 0.4*fatigue] that grows over time."""
        if self.fatigue <= 0 or n == 0:
            return 1.0
        progress = i / max(1, n - 1)
        return 1.0 + 0.4 * self.fatigue * progress

    def _ramp_factor(self, i: int, n):
        """Return a multiplier in [1, 1 + 2*ramp_strength] for the ramp."""
        if self.speed_ramp == "None" or self.ramp_strength <= 0 or n == 0:
            return 1.0
        progress = i / max(1, n - 1)  # 0 at start, 1 at end
        if self.speed_ramp == "Ease In":
            factor = 1.0 + math.cos(progress * math.pi / 2) * 2.0 * self.ramp_strength
        elif self.speed_ramp == "Ease Out":
            factor = 1.0 + math.sin(progress * math.pi / 2) * 2.0 * self.ramp_strength
        else:  # Ease In-Out
            factor = 1.0 + (math.cos(progress * 2.0 * math.pi) + 1.0) * self.ramp_strength
        return max(0.2, factor)

    def _char_delay(self, ch: str, i: int, rng: random.Random):
        """Base per-character delay, before burst / structural adjustments."""
        d = self.base_delay
        if self.humanize:
            d *= rng.uniform(0.55, 1.45)
            if ch == "\n":
                d *= rng.uniform(2.2, 5.5)
            elif ch == " ":
                d *= rng.uniform(0.7, 1.4)
            elif ch == "\t":
                d *= rng.uniform(1.1, 1.8)
            elif ch in self.SENTENCE_FINAL:
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
                d *= rng.uniform(1.05, 1.5)
            elif ch in "'\"`":
                d *= rng.uniform(1.1, 1.7)
            elif ch.isdigit():
                d *= rng.uniform(0.95, 1.3)
            elif ch.isupper():
                d *= rng.uniform(1.05, 1.45)
            if i >= 1:
                prev = self.code[i - 1]; dist = _key_distance(ch, prev)
                if dist < 0.5:
                    d *= 0.65
                elif dist < 2.0:
                    d *= rng.uniform(0.7, 0.95)
                elif dist > 4.0:
                    d *= rng.uniform(1.05, 1.3)
            if i >= 2 and ch == self.code[i - 1] == self.code[i - 2]:
                d *= 0.65
            if ch in self._KW_FIRST_CHARS:
                for kw in self.PAUSE_KEYWORDS:
                    if self.code.startswith(kw, i):
                        d *= 1.6; break
        return d

    @staticmethod
    def _make_typo(ch: str, rng: random.Random):
        """Generate a realistic typo for ``ch``."""
        lower = ch.lower(); pos = _QWERTY_POS.get(lower); roll = rng.random()
        if pos is not None and roll < 0.70:
            r, c = pos; candidates: List[str] = []
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
            return ch
        if pos is not None and roll < 0.95:
            r, c = pos; row = _QWERTY_ROWS[r]
            if len(row) > 1:
                idx = c; other = (idx + rng.choice((-1, 1))) % len(row); typo = row[other]
                return typo.upper() if ch.isupper() else typo
        typo = rng.choice("abcdefghijklmnopqrstuvwxyz")
        return typo.upper() if ch.isupper() else typo

    def _is_structural(self, ch: str, i):
        """Return True if this position is a structural boundary."""
        return ch in self.STRUCTURAL_PAUSES

    def _structural_pause(self, ch: str, i: int, rng: random.Random):
        """Return an extra delay for a structural boundary, or 0."""
        if ch in self.STRUCTURAL_PAUSES:
            lo, hi, prob = self.STRUCTURAL_PAUSES[ch]
            if rng.random() < prob:
                base = rng.uniform(lo, hi)
                if ch == "\n" and i >= 1 and self.code[i - 1] == "\n":
                    base *= rng.uniform(1.8, 3.0)
                return base
        return 0.0

    def _build_stats_prefix(self):
        """Precompute prefix sums of (keystrokes, correct_keystrokes)."""
        keystrokes = 0; correct = 0; self._keystrokes_prefix = []; self._correct_prefix = []; self._resolved_prefix = []; resolved_len = 0
        for event_idx, (_, _, ch) in enumerate(self.timeline):
            keystrokes += 1
            if ch == "\b":
                if resolved_len > 0:
                    resolved_len -= 1
            elif event_idx not in self._typo_indices:
                correct += 1; resolved_len += 1
            else:
                resolved_len += 1; self._keystrokes_prefix.append(keystrokes); self._correct_prefix.append(correct); self._resolved_prefix.append(resolved_len)

    def duration(self):
        if not self.timeline:
            return self.start_pause + self.end_pause
        return self.timeline[-1][0] + self.end_pause

    def visible_at(self, t):
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

    def stats_at(self, t):
        """Return typing statistics at time ``t``."""
        if t < self.start_pause or not self.timeline:
            return TypingStats(0.0, 0, 0, 0, 0.0, 1.0)
        idx = bisect.bisect_right(self._timestamps, t)
        if idx == 0:
            return TypingStats(0.0, 0, 0, 0, 0.0, 1.0)
        ts, _, _ = self.timeline[idx - 1]; elapsed = max(1e-6, ts - self.start_pause); keystrokes = self._keystrokes_prefix[idx - 1]; correct = self._correct_prefix[idx - 1]
        chars_typed = self._resolved_prefix[idx - 1]; wpm = (chars_typed / 5.0) / (elapsed / 60.0) if elapsed > 0 else 0.0; accuracy = correct / keystrokes if keystrokes > 0 else 1.0
        return TypingStats(elapsed, chars_typed, keystrokes, correct, wpm, accuracy)

# ======================================================================
# renderer.py
# ======================================================================

"""
Code renderer.

Paints a single frame of the typing animation into a QImage:
  - optional background image or gradient
  - optional window chrome (title bar + traffic-light buttons)
  - line numbers, current-line highlight, blinking caret
  - syntax-coloured code using the configured tokenizer
  - optional on-screen keyboard overlay showing the last pressed key

Performance optimisations
-------------------------
  * Static background + window chrome are pre-rendered once into a cached
    QPixmap and blitted per frame instead of being redrawn every frame.
  * The full source code is tokenised exactly once per ``display_chars``
    list. Each frame then takes an O(1) slice of the precomputed colour
    array instead of re-tokenising the growing visible text.
  * ``visible_text`` is computed in O(1) via a precomputed ``is_clean``
    table that tells us whether the current frame has an unresolved
    typo (rare) or is a clean prefix of the final source (common).
  * Per-line horizontal layout (``char_x`` positions) is cached by line
    text so that already-typed lines are laid out for free on subsequent
    frames.
  * An optional ``target`` QImage can be supplied to ``render_frame`` so
    the exporter can reuse a single scratch buffer instead of allocating
    a new ~8 MB image per frame.
  * All caches are guarded by a ``threading.Lock`` so the renderer is
    safe to use from the export worker thread while the UI thread holds
    a reference (the UI stops the preview timer during export).
"""

OVERLAY_POSITIONS = ("Top-Left", "Top-Right", "Bottom-Left", "Bottom-Right")

class CodeRenderer:
    """Render an individual frame of the typing animation."""

    TOKEN_COLOR_MAP: Dict[str, str] = { "keyword": "keyword", "builtin": "builtin", "string": "string", "triple_string": "string", "number": "number", "comment": "comment", "decorator": "decorator", "function": "function", "class_name": "class_name", "operator": "operator",
    }

    CURSOR_BLINK_PERIOD = 0.53  # seconds
    _LINE_CACHE_MAX = 512       # max unique lines whose layout we cache
    MIN_FONT_SIZE = 8
    MAX_FONT_SIZE = 60

    @staticmethod
    def auto_font_size( code_lines: int, width: int, height: int, padding: int = 50, show_window_chrome: bool = True, show_line_numbers: bool = True, show_keyboard: bool = False, tab_size: int = 4, target_lines: Optional[int] = None, keyboard_position: str = "Below Code", keyboard_scale: float = 1.0, keyboard_gap: int = 20, code: Optional[str] = None, font_family: str = "Consolas",
    ) -> int:
        """Calculate the largest font size that fits *code_lines* lines.
        If *target_lines* is given the font is sized so that exactly
        that many lines fill the vertical space (useful when you want
        the code to look spacious rather than crammed).; If *code* is provided, the horizontal constraint is based on the
        actual longest line (accounting for tabs), rather than a fixed; 120-char assumption.
        The calculation accounts for all space usage:
        - Padding on all sides; - Window chrome (title bar + rounded corners); - Line numbers column; - Code margin; - Keyboard overlay (below code or right panel)
        - A small safety margin to prevent edge-case overlaps
        """
        chrome = 42 if show_window_chrome else 0; ref = min(width, height) / 1080.0; kb_h = 0; kb_panel_w = 0
        if show_keyboard:
            scaled_kh = KEY_HEIGHT * ref * keyboard_scale; scaled_km = KEY_MARGIN * ref * keyboard_scale; scaled_kw = KEY_WIDTH * ref * keyboard_scale
            if keyboard_position == "Below Code":
                kb_total_h = (scaled_kh + scaled_km) * 5; kb_h = kb_total_h + 30 + keyboard_gap
            elif keyboard_position == "Right Panel":
                kb_total_w = (scaled_kw + scaled_km) * 15; kb_panel_w = int(kb_total_w + keyboard_gap * 2 + padding)
        else:
            scaled_kh = 0; scaled_km = 0; scaled_kw = 0; safety_margin_v = 6  # Prevents edge-case vertical overlaps
        area_h = height - 2 * padding - chrome - kb_h - safety_margin_v; ln_width = 65 if show_line_numbers else 0; code_margin = 20
        start_x = padding + ln_width + code_margin; safety_margin_h = 4  # Prevents edge-case horizontal overlaps
        area_w = width - padding - start_x - safety_margin_h - kb_panel_w; effective_lines = target_lines if target_lines else code_lines
        if effective_lines > 0 and area_h > 0:
            fs_v = int((area_h / (effective_lines * 1.55)) - 0.5)
        else:
            fs_v = CodeRenderer.MAX_FONT_SIZE
        if code is not None:
            max_cols = 0
            for line in code.split('\n'):
                expanded = line.replace('\t', ' ' * tab_size); max_cols = max(max_cols, len(expanded)); max_cols = max(max_cols, 1)  # At least 1 column
        else:
            max_cols = 120; char_width_ratio = 0.61
        if max_cols > 0 and area_w > 0:
            fs_h = int((area_w / (max_cols * char_width_ratio)) - 0.5)
        else:
            fs_h = CodeRenderer.MAX_FONT_SIZE; fs = min(fs_v, fs_h)
        return max(CodeRenderer.MIN_FONT_SIZE, min(fs, CodeRenderer.MAX_FONT_SIZE))

    def __init__( self, width: int = 1920, height: int = 1080, theme_name: str = "Dracula", font_family: str = "Consolas", font_size: int = 24, show_line_numbers: bool = True, show_window_chrome: bool = True, padding: int = 50, tab_size: int = 4, title_text: str = "main.py — Code Editor", language: str = "Python", show_keyboard: bool = False, keyboard_gap: int = 20, keyboard_scale: float = 1.0, keyboard_layout: str = "QWERTY (US)", keyboard_position: str = "Below Code", keyboard_opacity: float = 1.0, keyboard_radius: int = 6, show_stats: bool = False, stats_position: str = "Bottom-Right",
    ) -> None:
        self.logger = logging.getLogger("CodeRenderer"); self.width = width; self.height = height; self.theme_name = theme_name
        if theme_name not in THEMES:
            raise ValueError(f"Unknown theme '{theme_name}'; available: {', '.join(THEMES)}"); self.theme = THEMES[theme_name]
        self.font_family = font_family; self.font_size = font_size; self.show_line_numbers = show_line_numbers; self.show_window_chrome = show_window_chrome
        self.padding = padding; self.tab_size = tab_size; self.title_text = title_text; self.language = language; self.show_keyboard = show_keyboard
        self.keyboard_gap = max(0, keyboard_gap); self.keyboard_layout_name = keyboard_layout; self._kb_rows = KEYBOARD_LAYOUTS.get(keyboard_layout, KEYBOARD_LAYOUTS["QWERTY (US)"])
        self.keyboard_position = keyboard_position if keyboard_position in KB_POSITIONS else "Below Code"; self.keyboard_opacity = max(0.1, min(1.0, keyboard_opacity))
        self.keyboard_radius = max(0, keyboard_radius); self.show_stats = show_stats; self.stats_position = stats_position if stats_position in OVERLAY_POSITIONS else "Bottom-Right"
        self.pressed_key: Optional[str] = None; self.current_time: float = 0.0; self.animator_ref = None
        self.bg_image: Optional[QPixmap] = None
        self.title_bar_h = 42 if show_window_chrome else 0; self.ln_width = 65 if show_line_numbers else 0; self.code_margin = 20
        self.font = QFont(font_family, font_size); self.font.setStyleHint(QFont.Monospace); self.line_h = int(font_size * 1.55); self._fm = QFontMetrics(self.font)
        self._tab_advance = self._fm.horizontalAdvance(" ") * self.tab_size; self._start_x = self.padding + self.ln_width + self.code_margin; self._ln_font = QFont(font_family, max(8, font_size - 2))
        self._ln_font.setStyleHint(QFont.Monospace); self._glyph_font = QFont("Arial", 7, QFont.Bold); self._title_font = QFont(font_family, 12); ref = min(width, height) / 1080.0
        self._kb_key_w = KEY_WIDTH * ref * keyboard_scale; self._kb_key_h = KEY_HEIGHT * ref * keyboard_scale; self._kb_key_margin = KEY_MARGIN * ref * keyboard_scale
        self._kb_total_w = (self._kb_key_w + self._kb_key_margin) * 15; self._kb_total_h = (self._kb_key_h + self._kb_key_margin) * 5; self._kb_font_size = max(7, int(9 * self._kb_key_h / KEY_HEIGHT))
        self._kb_font = QFont("Arial", self._kb_font_size); self._stats_font = QFont(font_family, max(10, font_size - 6)); self._stats_font.setStyleHint(QFont.Monospace)
        self._stats_fm = QFontMetrics(self._stats_font); self._stats_line_h = int(self._stats_fm.height() * 1.15)
        self._stats_lines = [ "WPM:     0.0", "Keys:      0", "Acc:   100.0%", "Time:  00:00",
        ]; self._stats_pad = 10
        self._stats_box_w = max( self._stats_fm.horizontalAdvance(line) for line in self._stats_lines
        ) + 2 * self._stats_pad
        self._stats_box_h = ( self._stats_line_h * len(self._stats_lines) + 2 * self._stats_pad
        )
        self._qcolors: Dict[str, QColor] = {}
        for key, val in self.theme.items():
            if isinstance(val, str) and val.startswith("#"):
                self._qcolors[key] = QColor(val)
        self._qc_current_line = self._qcolors.get("current_line", QColor("#44475a")); self._qc_cursor = self._qcolors.get("cursor", QColor("#f8f8f2"))
        self._qc_line_num = self._qcolors.get("line_number", QColor("#6272a4")); self._qc_fg = self._qcolors.get("foreground", QColor("#f8f8f2"))
        self._qc_line_num_active = QColor(self._qc_fg).darker(120); self._qc_overlay_bg = QColor(0, 0, 0, 140); self._qc_stats_accent = self._qcolors.get("keyword", QColor("#ff79c6")); self._qc_glyph_shadow = QColor(0, 0, 0, 100)
        self._kb_pressed_brush = self._qcolors.get("keyword", QColor("#ff79c6")).lighter(130); self._kb_normal_brush = self._qcolors.get("current_line", QColor("#44475a"))
        self._kb_pressed_pen = self._qcolors.get("background", QColor("#282a36")); self._kb_normal_pen = self._qcolors.get("foreground", QColor("#f8f8f2"))
        self._tokenizer_lang: str = language if language in _LANG_DATA else "Python"; self._cache_lock = threading.Lock(); self._static_layer: Optional[QPixmap] = None; self._static_layer_dirty: bool = True
        self._cached_display_chars_id: Optional[int] = None; self._cached_display_chars_len: int = 0; self._cached_resolved: str = ""; self._cached_resolved_colors: List[str] = []
        self._cached_is_clean: List[bool] = []; self._cached_stack_len: List[int] = []; self._cached_color_qc: List[QColor] = []; self._color_qc: List[QColor] = []
        self._line_layout_cache: "OrderedDict[str, Tuple[List[int], int]]" = OrderedDict(); self._cached_text: Optional[str] = None; self._cached_colors: Optional[List[str]] = None

    def set_background_image(self, path):
        with self._cache_lock:
            if path and os.path.exists(path):
                self.bg_image = QPixmap(path)
            else:
                self.bg_image = None; self._static_layer_dirty = True

    def invalidate_cache(self):
        """Drop all caches. Call when theme / font / size etc. change."""
        with self._cache_lock:
            self._static_layer = None; self._static_layer_dirty = True; self._line_layout_cache.clear(); self._cached_display_chars_id = None; self._cached_resolved = ""; self._cached_resolved_colors = []
            self._cached_is_clean = []; self._cached_stack_len = []; self._cached_color_qc = []; self._color_qc = []; self._cached_text = None; self._cached_colors = None

    def render_frame( self, full_text: List[str], num_visible: int, cursor_visible: bool = True, target: Optional[QImage] = None,
    ) -> QImage:
        """Render a single frame.
        If ``target`` is supplied it is drawn into in-place (the caller
        maintains ownership); otherwise a fresh QImage is allocated.
        """
        if target is not None and (target.width() != self.width or target.height() != self.height):
            raise ValueError( f"Target QImage size ({target.width()}x{target.height()}) " f"must match renderer size ({self.width}x{self.height})"
            )
        img = target if target is not None else QImage( self.width, self.height, QImage.Format_RGB32
        )
        p = QPainter(img); p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.TextAntialiasing); p.drawPixmap(0, 0, self._get_static_layer())
        resolved, resolved_colors, color_qc, is_clean, stack_len = self._get_cache(full_text)
        if 0 <= num_visible < len(is_clean) and is_clean[num_visible]:
            vl = stack_len[num_visible]; visible_text = resolved[:vl]; char_colors = resolved_colors[:vl]; vis_color_qc = color_qc[:vl]
        else:
            visible_text = self._resolve_backspaces(full_text[:num_visible]); char_colors = self._tokenize_to_colors(visible_text); vis_color_qc = self._color_qc
        vis_lines = visible_text.split("\n")
        cursor_line = visible_text.count("\n"); last_nl = visible_text.rfind("\n"); cursor_col = len(visible_text) - last_nl - 1 if last_nl >= 0 else len(visible_text)
        chrome = self.title_bar_h if self.show_window_chrome else 0; area_top = self.padding + chrome; area_h = self.height - 2 * self.padding - chrome
        kb_panel_w = 0  # extra width consumed by "Right Panel" mode
        if self.show_keyboard:
            if self.keyboard_position == "Below Code":
                area_h -= self._kb_total_h + 30 + self.keyboard_gap
            elif self.keyboard_position == "Right Panel":
                kb_panel_w = int(self._kb_total_w + self.keyboard_gap * 2 + self.padding)
        if self.show_window_chrome:
            clip_left = self.padding - 14; clip_right = self.width - self.padding + 14 - kb_panel_w
        else:
            clip_left = 0; clip_right = self.width - kb_panel_w
        code_clip = QRect(clip_left, area_top, clip_right - clip_left, area_h); p.setClipRect(code_clip); max_vis = int(max(1, area_h // self.line_h))
        scroll_margin_top = 3; scroll_margin_bottom = min(5, max_vis - 1); first = 0
        if cursor_line >= first + max_vis - scroll_margin_bottom:
            first = max(0, cursor_line - max_vis + scroll_margin_bottom + 1)
        if cursor_line < first + scroll_margin_top:
            first = max(0, cursor_line - scroll_margin_top)
        line_offsets: List[int] = []; off = 0
        for line in vis_lines:
            line_offsets.append(off); off += len(line) + 1
        for i in range(max_vis):
            li = first + i
            y = area_top + i * self.line_h
            if li >= len(vis_lines):
                break
            if li == cursor_line:
                p.fillRect( QRect(self.padding - 12, y, self.width - 2 * self.padding + 24, self.line_h), self._qc_current_line,
                )
            if self.show_line_numbers:
                p.setFont(self._ln_font)
                p.setPen( self._qc_line_num_active if li == cursor_line else self._qc_line_num
                )
                p.drawText( QRect(self.padding, y, self.ln_width, self.line_h), Qt.AlignRight | Qt.AlignVCenter, str(li + 1),
                )
            p.setFont(self.font); start_x = self._start_x; line = vis_lines[li]; global_off = line_offsets[li]
            if not line:
                if cursor_visible and li == cursor_line:
                    self._draw_caret(p, int(start_x), int(y + 5)); continue
                    char_x, _ = self._get_line_layout(line); cur_qc = vis_color_qc[global_off] if global_off < len(vis_color_qc) else self._qc_fg; run_start = 0
            for j in range(1, len(line) + 1):
                next_qc = self._qc_fg
                if j < len(line):
                    gp = global_off + j; next_qc = vis_color_qc[gp] if gp < len(vis_color_qc) else self._qc_fg
                if j == len(line) or next_qc is not cur_qc:
                    run_text = line[run_start:j].replace("\t", " " * self.tab_size); p.setPen(cur_qc)
                    p.drawText( QPoint(int(char_x[run_start]), int(y + self.line_h * 0.78)), run_text,
                    ); cur_qc = next_qc; run_start = j
            if cursor_visible and li == cursor_line:
                idx = min(cursor_col, len(char_x))
                if idx < len(char_x):
                    cx = char_x[idx]
                else:
                    last_x = char_x[-1] if char_x else self._start_x
                    if line and line[-1] == "\t":
                        cx = last_x + self._tab_advance
                    elif line:
                        cx = last_x + self._fm.horizontalAdvance(line[-1])
                    else:
                        cx = last_x; self._draw_caret(p, int(cx), int(y + 5)); p.setClipping(False)
        if self.show_keyboard:
            self._draw_keyboard(p, self.pressed_key)
        if self.show_stats and self.animator_ref is not None:
            self._draw_stats(p)
        p.end()
        return img

    def _get_static_layer(self):
        with self._cache_lock:
            if self._static_layer is not None and not self._static_layer_dirty:
                return self._static_layer
            pm = QPixmap(self.width, self.height); pm.fill(QColor(self.theme["background"])); p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.TextAntialiasing)
            self._draw_bg(p)
            if self.show_window_chrome:
                self._draw_chrome(p)
            p.end(); self._static_layer = pm; self._static_layer_dirty = False
            return pm

    def _get_cache( self, full_text: List[str]
    ) -> Tuple[str, List[str], List[QColor], List[bool], List[int]]:
        """Return (resolved, resolved_colors, color_qc, is_clean, stack_len).
        Recomputes only when ``full_text`` is a different list object; than the one currently cached (compared by ``id()``).
        """
        with self._cache_lock:
            if id(full_text) != self._cached_display_chars_id or len(full_text) != self._cached_display_chars_len:
                resolved = self._resolve_backspaces(full_text); self._cached_resolved = resolved; self._cached_resolved_colors = self._tokenize_to_colors(resolved); self._cached_color_qc = self._color_qc
                self._cached_is_clean, self._cached_stack_len = self._precompute_clean( full_text, resolved
                )
                self._cached_display_chars_id = id(full_text); self._cached_display_chars_len = len(full_text)
            return ( self._cached_resolved, self._cached_resolved_colors, self._cached_color_qc, self._cached_is_clean, self._cached_stack_len,
            )

    @staticmethod
    def _resolve_backspaces(chars):
        """Process ``\b`` characters to produce the final visible string."""
        out: List[str] = []
        for ch in chars:
            if ch == "\b":
                if out:
                    out.pop()
            else:
                out.append(ch)
        return "".join(out)

    @staticmethod
    def _precompute_clean( display_chars: List[str], resolved: str
    ) -> Tuple[List[bool], List[int]]:
        """Precompute is_clean[] and stack_len[] tables.
        ``is_clean[i]`` is True iff processing ``display_chars[:i]``
        yields a string that is a prefix of ``resolved`` (i.e. no
        unresolved typo is currently on screen).
        ``stack_len[i]`` is the length of the visible string after; processing ``display_chars[:i]``.
        """
        n = len(display_chars); is_clean: List[bool] = [True] * (n + 1); stack_len: List[int] = [0] * (n + 1); stack: List[Tuple[str, bool]] = []; incorrect = 0; rlen = len(resolved)
        for i in range(n):
            ch = display_chars[i]
            if ch == "\b":
                if stack:
                    _, was_correct = stack.pop()
                    if not was_correct:
                        incorrect -= 1
            else:
                pos = len(stack); was_correct = pos < rlen and ch == resolved[pos]; stack.append((ch, was_correct))
                if not was_correct:
                    incorrect += 1; is_clean[i + 1] = incorrect == 0; stack_len[i + 1] = len(stack)
        return is_clean, stack_len

    def _tokenize_to_colors(self, text):
        """Tokenise ``text`` once and return a per-char colour-key list."""
        tokens = Tokenizer.tokenize(text, self._tokenizer_lang); colors: List[str] = ["foreground"] * len(text); pos = 0; get = self.TOKEN_COLOR_MAP.get  # local alias avoids dict lookup
        n = len(colors)
        qcolors = self._qcolors; fg = self._qc_fg; self._color_qc: List[QColor] = [fg] * n
        for ttype, ttxt in tokens:
            ckey = get(ttype, "foreground"); qc = qcolors.get(ckey, fg); end = pos + len(ttxt)
            if end > n:
                end = n
            colors[pos:end] = [ckey] * (end - pos); self._color_qc[pos:end] = [qc] * (end - pos); pos = end
        return colors

    def _build_color_map(self, text):
        if text == self._cached_text and self._cached_colors is not None:
            return self._cached_colors
        self._cached_colors = self._tokenize_to_colors(text); self._cached_text = text
        return self._cached_colors

    def _get_line_layout(self, line) -> Tuple[List[int], int]:
        """Return (char_x_positions, total_width) for ``line``."""
        cached = self._line_layout_cache.get(line)
        if cached is not None:
            return cached
        with self._cache_lock:
            cached = self._line_layout_cache.get(line)
            if cached is not None:
                return cached
            char_x: List[int] = []; x = self._start_x; tab = self._tab_advance; ham = self._fm.horizontalAdvance  # local alias
            for ch in line:
                char_x.append(x); x += tab if ch == "\t" else ham(ch); result = (char_x, x)
            if len(self._line_layout_cache) >= self._LINE_CACHE_MAX:
                self._line_layout_cache.popitem(last=False)  # FIFO evict
            self._line_layout_cache[line] = result
            return result

    def _draw_caret(self, p: QPainter, x: int, y):
        w = max(2, self.font_size // 10); p.fillRect(x, y, w, self.line_h - 10, self._qc_cursor)

    def _draw_bg(self, p: QPainter):
        if self.bg_image:
            scaled = self.bg_image.scaled( self.width, self.height, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation,
            )
            x = (self.width - scaled.width()) // 2; y = (self.height - scaled.height()) // 2; p.drawPixmap(x, y, scaled)
        else:
            g = QLinearGradient(0, 0, 0, self.height); bg = self._qcolors.get("background", QColor("#282a36")); g.setColorAt(0, bg.lighter(105)); g.setColorAt(1, bg); p.fillRect(0, 0, self.width, self.height, g)

    def _draw_chrome(self, p: QPainter):
        x = self.padding - 14; y = self.padding - 14; w = self.width - 2 * self.padding + 28; h = self.height - 2 * self.padding + 28
        p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 60)); p.drawRoundedRect(x + 4, y + 4, w, h, 12, 12); p.setBrush(self._qcolors.get("window_border", QColor("#1e1f29")))
        p.drawRoundedRect(x, y, w, h, 12, 12); tb = self._qcolors.get("title_bar", QColor("#1e1f29")); p.setBrush(tb); p.drawRoundedRect(x, y, w, self.title_bar_h + 10, 12, 12)
        p.fillRect(x, y + 18, w, self.title_bar_h - 8, tb); by = y + 19; glyphs = {"button_close": "×", "button_min": "−", "button_max": "+"}
        for dx, color_key in [(20, "button_close"), (44, "button_min"), (68, "button_max")]:
            p.setBrush(self._qcolors.get(color_key, QColor("#ff5f57"))); p.drawEllipse(x + dx, by, 14, 14); p.setPen(self._qc_glyph_shadow); p.setFont(self._glyph_font)
            p.drawText(QRect(x + dx, by, 14, 14), Qt.AlignCenter, glyphs[color_key]); p.setPen(Qt.NoPen); p.setPen(self._qcolors.get("title_text", QColor("#cccccc"))); p.setFont(self._title_font)
        p.drawText(QRect(x, y + 10, w, self.title_bar_h), Qt.AlignCenter, self.title_text)

    def _draw_stats(self, p: QPainter):
        """Draw a small stats panel (WPM, keystrokes, accuracy, elapsed)."""
        stats = self.animator_ref.stats_at(self.current_time)
        lines = [ f"WPM:   {stats.wpm:6.1f}", f"Keys:  {stats.keystrokes:6d}", f"Acc:   {stats.accuracy * 100:5.1f}%", f"Time:  {self._format_time(stats.elapsed)}",
        ]; pad = self._stats_pad; box_w = self._stats_box_w; box_h = self._stats_box_h
        x, y = self._overlay_origin(box_w, box_h, self.stats_position); p.setPen(Qt.NoPen); p.setBrush(self._qc_overlay_bg); p.drawRoundedRect(x, y, box_w, box_h, 8, 8); p.setBrush(self._qc_stats_accent)
        p.drawRoundedRect(x, y, 4, box_h, 2, 2); p.setFont(self._stats_font); p.setPen(self._qc_fg)
        for i, line in enumerate(lines):
            p.drawText( QRect(x + pad + 4, y + pad + i * self._stats_line_h, box_w - 2 * pad, self._stats_line_h), Qt.AlignLeft | Qt.AlignVCenter, line,
            )

    @staticmethod
    def _format_time(s):
        m = int(s) // 60; sec = int(s) % 60
        return f"{m:02d}:{sec:02d}"

    def _overlay_origin(self, box_w: int, box_h: int, position):
        """Return (x, y) for an overlay box of the given size at the."""
        margin = 24
        if position == "Top-Left":
            return margin, margin
        if position == "Top-Right":
            return self.width - box_w - margin, margin
        if position == "Bottom-Left":
            return margin, self.height - box_h - margin
        return self.width - box_w - margin, self.height - box_h - margin

    def _draw_keyboard(self, p: QPainter, pressed_key):
        kw = self._kb_key_w; kh = self._kb_key_h; km = self._kb_key_margin; total_w = self._kb_total_w; total_h = self._kb_total_h; radius = self.keyboard_radius
        if self.keyboard_position == "Right Panel":
            panel_x = self.width - int(total_w) - self.padding - self.keyboard_gap; start_x = panel_x
            start_y = max( self.padding + self.title_bar_h, (self.height - int(total_h)) // 2,
            )
        elif self.keyboard_position == "Overlay Bottom":
            start_x = (self.width - int(total_w)) // 2; start_y = self.height - int(total_h) - self.padding // 2
        else:
            start_x = (self.width - int(total_w)) // 2; start_y = self.height - int(total_h) - 30 - self.keyboard_gap
        if self.keyboard_opacity < 1.0:
            p.save(); p.setOpacity(self.keyboard_opacity); p.setFont(self._kb_font)
        for r, row in enumerate(self._kb_rows):
            row_offset_x = r * int(kw / 2)
            for c, key in enumerate(row):
                w = kw; label = key.upper(); current_pressed = pressed_key
                if key == " ":
                    w = kw * 6; row_offset_x = int((total_w - w) // 2)
                    if current_pressed == "space":
                        current_pressed = " "; x = start_x + row_offset_x + c * (kw + km); y = start_y + r * (kh + km); is_pressed = (current_pressed == key); p.setPen(Qt.NoPen)
                if is_pressed:
                    p.setBrush(self._kb_pressed_brush)
                else:
                    p.setBrush(self._kb_normal_brush); p.drawRoundedRect(int(x), int(y), int(w), int(kh), radius, radius); p.setPen(self._kb_pressed_pen if is_pressed else self._kb_normal_pen)
                p.drawText(QRect(int(x), int(y), int(w), int(kh)), Qt.AlignCenter, label)
        if self.keyboard_opacity < 1.0:
            p.restore()

# ======================================================================
# exporter.py
# ======================================================================

"""
Video exporter.

Runs in a QThread and pipes raw RGB frames from the renderer into
FFmpeg, producing MP4 / WebM / GIF. Optional audio track is generated
from the animator's character timestamps.

This module also contains the **batch rendering** engine
(:class:`BatchItem`, :class:`BatchSettings`, :class:`BatchExporter`)
which exports a queue of code files (or inline snippets) sequentially,
reusing a single sound generator across all items and building a fresh
CodeRenderer + TypingAnimator per item.

Performance optimisations
-------------------------
  * A single scratch QImage is reused across all frames so we avoid
    allocating ~8 MB per frame (1920×1080 × 4 bytes × 1800 frames =
    ~14 GB of allocations in a typical export).
  * ``_qimg_to_raw_rgb`` has a fast path for Format_RGB32 images with
    no scanline padding (the overwhelmingly common case) that reads
    the buffer directly via numpy and reverses the BGRA byte order
    in-place, skipping the expensive ``convertToFormat(RGB888)`` copy.
  * Frame render time is measured and averaged; the export FPS is
    emitted as a status message so users can verify the speedup.
  * The unused ``cv2`` dependency and ``_qimg_to_frame`` dead code
    from the original implementation have been removed.

Smart GPU memory management (v1.8)
-----------------------------------
  * ``_detect_gpu_info`` queries ``nvidia-smi`` once to get total and
    free VRAM (MiB), GPU name, and driver version.  Falls back to (0, 0)
    on non-NVIDIA systems or when nvidia-smi is unavailable.
  * ``_smart_gpu_tier`` picks the highest ``GPU_VRAM_TIERS`` entry
    whose ``min_vram_mb`` fits the detected total VRAM, producing a
    tuned set of NVENC parameters (preset, surfaces, lookahead,
    multipass, frame chunk size).
  * Frame chunking: raw RGB frames are buffered in a ``bytearray``
    and flushed to the FFmpeg pipe every N frames (N = tier's
    ``frame_chunk``).  This reduces syscall overhead and lets the GPU
    encoder batch more efficiently.  The chunk size scales from 4 frames
    on GTX 1080-class to 12 on RTX 4090-class.
  * VRAM monitoring: every ``GPU_VRAM_POLL_INTERVAL`` frames (default
    60, ~2s at 30fps), ``nvidia-smi`` is polled again.  If free VRAM
    drops below ``GPU_VRAM_LOW_WATERMARK``, a warning is logged and the
    frame chunk size is halved to reduce GPU-side buffering pressure.
    If VRAM is critically low (<5%), the export still completes but
    warns the user to close other GPU applications.
  * NVENC-specific flags (``-rc``, ``-surfaces``, ``-lookahead``,
    ``-multipass``, ``-aq``) are now injected automatically based on
    the detected tier instead of using a single hardcoded preset.
  * ``gpu_info_signal`` emits a human-readable GPU summary (name,
    VRAM, tier) so the main window can display it next to the GPU
    encoding checkbox.
"""

class VideoExporter(QThread):
    """Background thread that exports the animation to a video file."""

    progress = Signal(int)
    status = Signal(str)
    finished_ok = Signal(str)   # emits output path on success
    error = Signal(str)
    gpu_info = Signal(str)     # emits "GPU Name | 8192 MB | Tier: RTX 2070-class"

    def __init__( self, code: str, output: str, renderer: CodeRenderer, animator: TypingAnimator, fps: int = 30, sound_gen: Optional[TypingSoundGenerator] = None, volume: float = 0.5, codec_profile: str = "MP4 (H.264)", crf: int = 18, preset: str = "medium", subtitle_path: Optional[str] = None, use_hw_accel: bool = False, metadata_title: str = "", metadata_description: str = "", max_duration: Optional[float] = None,
    ) -> None:
        super().__init__(); self.code = code; self.output = output; self.renderer = renderer; self.animator = animator; self.fps = fps; self.sound_gen = sound_gen; self.volume = volume
        self.codec_profile = codec_profile; self.crf = crf; self.preset = preset; self.subtitle_path = subtitle_path; self.use_hw_accel = use_hw_accel
        self.metadata_title = metadata_title.strip(); self.metadata_description = metadata_description.strip(); self.max_duration = max_duration; self.logger = logging.getLogger("VideoExporter")
        self._cancel_event = threading.Event(); self.renderer.animator_ref = animator
        self._raw_buf: Optional[np.ndarray] = np.empty( (self.renderer.height, self.renderer.width, 3), dtype=np.uint8
        )

    def cancel(self):
        self._cancel_event.set()

    @staticmethod
    def _check_ffmpeg():
        try:
            r = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
            return r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def _detect_gpu_info():
        """Query nvidia-smi for GPU name, total VRAM, and free VRAM (MiB)."""
        try:
            r = subprocess.run( [ "nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits", ], capture_output=True, timeout=5,
            )
            if r.returncode != 0:
                return ("", 0, 0)
            line = r.stdout.decode("utf-8", errors="ignore").strip(); parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                name = parts[0]; total = int(parts[1]); free = int(parts[2])
                return (name, total, free)
        except Exception:
            pass
        return ("", 0, 0)

    @staticmethod
    def _poll_gpu_free_vram():
        """Quick poll of free VRAM (MiB).  Returns 0 on failure."""
        try:
            r = subprocess.run( [ "nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits", ], capture_output=True, timeout=5,
            )
            if r.returncode == 0:
                return int(r.stdout.decode("utf-8", errors="ignore").strip())
        except Exception:
            pass
        return 0

    @staticmethod
    def _detect_hw_encoder() -> Optional[Tuple[str, str]]:
        """Detect an available hardware H.264 encoder."""
        try:
            r = subprocess.run( ["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, timeout=5,
            )
            text = (r.stdout + r.stderr).decode("utf-8", errors="ignore")
        except Exception:
            return None
        candidates = [ ("h264_nvenc", "p4"), ("h264_qsv", "veryfast"), ("h264_videotoolbox", ""), ("h264_amf", "speed"),
        ]
        for enc, preset in candidates:
            if enc in text:
                return (enc, preset)
        return None

    @staticmethod
    def _smart_gpu_tier(total_vram_mb):
        """Return the best GPU_VRAM_TIERS entry for the given VRAM."""
        tier = gpu_tier_for_vram(total_vram_mb)
        return tier

    @staticmethod
    def _build_nvenc_args(tier: dict, w: int, h: int, bitrate_kbps=0):
        """Build NVENC-specific FFmpeg arguments from a GPU tier config."""
        args: list[str] = []; args += ["-preset", tier["nvenc_preset"]]; args += ["-rc", tier["nvenc_rc"]]
        if bitrate_kbps > 0:
            args += ["-b:v", f"{bitrate_kbps}k"]; args += ["-maxrate", f"{bitrate_kbps}k"]; args += ["-bufsize", f"{bitrate_kbps * 2}k"]
        else:
            args += ["-b:v", "0", "-cq", "20"]; args += ["-aq", tier["nvenc_aq"]]
        if tier["nvenc_multipass"] != "disabled":
            args += ["-multipass", tier["nvenc_multipass"]]
        surfaces = tier["nvenc_surfaces"]
        if tier["nvenc_lookahead"]:
            args += ["-lookahead_level", "auto"]
        if w > tier["max_res_width"] or h > tier["max_res_height"]:
            surfaces = max(4, surfaces // 2)
            logging.getLogger("VideoExporter").info( "Resolution %dx%d exceeds tier max %dx%d; " "clamping NVENC surfaces to %d.", w, h, tier["max_res_width"], tier["max_res_height"], surfaces,
            )
        args += ["-surfaces", str(surfaces)]; args += ["-pix_fmt", "yuv420p"]
        return args

    def _write_srt(self, path: str, max_time=None):
        """Write a .srt subtitle file with one cue per typed line."""
        line_starts: dict[int, float] = {}; line_texts: dict[int, str] = {}; cur_line = 0; cur_chars: list[str] = []; line_starts[0] = self.animator.start_pause
        for ts, _, ch in self.animator.timeline:
            if ch == "\b":
                if cur_chars:
                    cur_chars.pop()
            elif ch == "\n":
                line_texts[cur_line] = "".join(cur_chars); cur_line += 1; cur_chars = []
                if cur_line not in line_starts:
                    line_starts[cur_line] = ts
            else:
                cur_chars.append(ch); line_texts[cur_line] = "".join(cur_chars); ordered = sorted(line_starts.items()); cues = []
        for i, (ln, start) in enumerate(ordered):
            end = ordered[i + 1][1] if i + 1 < len(ordered) else self.animator.duration()
            if max_time is not None:
                end = min(end, max_time); text = line_texts.get(ln, "").rstrip()
            if not text:
                continue
            cues.append((start, end, f"[{ln + 1}] {text}"))
        if not cues:
            return
        def _fmt(t):
            ms = int(t * 1000); h, ms = divmod(ms, 3600_000); m, ms = divmod(ms, 60_000); s, ms = divmod(ms, 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
        with open(path, "w", encoding="utf-8") as f:
            for i, (start, end, text) in enumerate(cues, 1):
                f.write(f"{i}\n{_fmt(start)} --> {_fmt(end)}\n{text}\n\n")

    def _qimg_to_raw_rgb(self, qimg: QImage):
        """Convert a QImage to raw RGB24 bytes for FFmpeg."""
        w, h = qimg.width(), qimg.height(); bpl = qimg.bytesPerLine()
        if qimg.format() == QImage.Format_RGB32 and bpl == w * 4:
            ptr = qimg.constBits()
            if hasattr(ptr, "setsize"):
                ptr.setsize(h * bpl); arr = np.array(ptr, dtype=np.uint8).reshape((h, w, 4)); buf = self._raw_buf
                if buf is not None and buf.shape == (h, w, 3):
                    buf[:, :, 0] = arr[:, :, 2]  # R
                    buf[:, :, 1] = arr[:, :, 1]  # G
                    buf[:, :, 2] = arr[:, :, 0]  # B
                    return buf.tobytes()
                out = np.empty((h, w, 3), dtype=np.uint8); out[:, :, 0] = arr[:, :, 2]  # R
                out[:, :, 1] = arr[:, :, 1]  # G
                out[:, :, 2] = arr[:, :, 0]  # B
                return out.tobytes()
        qimg = qimg.convertToFormat(QImage.Format_RGB888); w, h = qimg.width(), qimg.height(); bpl = qimg.bytesPerLine(); ptr = qimg.constBits()
        if isinstance(ptr, memoryview):
            raw = ptr.tobytes()
            if len(raw) < h * bpl:
                return self._qimg_to_raw_rgb_scanline(qimg, w, h, bpl)
        elif hasattr(ptr, "setsize"):
            ptr.setsize(h * bpl); arr = np.array(ptr, dtype=np.uint8).reshape((h, bpl))
            if bpl != w * 3:
                arr = arr[:, : w * 3]
            return np.ascontiguousarray(arr).tobytes()
        else:
            raw = ptr.tobytes() if hasattr(ptr, "tobytes") else bytes(ptr); raw = raw[: h * bpl]
        if bpl == w * 3:
            return raw
        arr = np.frombuffer(raw, dtype=np.uint8).reshape((h, bpl))
        return np.ascontiguousarray(arr[:, : w * 3]).tobytes()

    @staticmethod
    def _qimg_to_raw_rgb_scanline(qimg: QImage, w: int, h: int, bpl):
        rows = []
        for y in range(h):
            scan = qimg.scanLine(y)
            if isinstance(scan, memoryview):
                rows.append(scan.tobytes()[: w * 3])
            elif hasattr(scan, "setsize"):
                scan.setsize(bpl); rows.append(bytes(scan)[: w * 3])
            else:
                rows.append(bytes(scan)[: w * 3])
        return b"".join(rows)

    def _render_frame_at( self, t: float, blink_period: float = 0.53, scratch: Optional[QImage] = None,
    ) -> QImage:
        nv = self.animator.visible_at(t); cur_vis = True; last_ts = 0.0; since = 0.0
        if nv > 0:
            idx = bisect.bisect_right(self.animator._timestamps, t)
            if idx > 0:
                last_ts = self.animator.timeline[idx - 1][0]; since = t - last_ts
        if since > 0.25:
            cur_vis = (int(since / blink_period) % 2) == 0; pressed_key: Optional[str] = None
        if nv > 0:
            last_ch = self.animator.display_chars[nv - 1]
            if since < 0.1:
                if last_ch == "\n":
                    pressed_key = "enter"
                elif last_ch == " ":
                    pressed_key = "space"
                elif last_ch == "\b":
                    pressed_key = "backspace"
                elif last_ch != "\t":
                    pressed_key = last_ch.lower(); self.renderer.pressed_key = pressed_key; self.renderer.current_time = t
        return self.renderer.render_frame( self.animator.display_chars, nv, cur_vis, target=scratch
        )

    def run(self):  # noqa: D401  (QThread override)
        tmp = None
        try:
            self.logger.info( "╔══ Export started ════════════════════════════════════════════════"
            )
            self.logger.info("  Codec profile : %s", self.codec_profile); self.logger.info("  Output file  : %s", self.output)
            self.logger.info("  Resolution   : %dx%d", self.renderer.width, self.renderer.height); self.logger.info("  FPS          : %d", self.fps)
            self.logger.info("  Sound profile: %s", self.sound_gen.profile if self.sound_gen else "(none)"); self.logger.info("  Volume       : %.0f%%", self.volume * 100)
            self.logger.info( "╚═══════════════════════════════════════════════════════════════"
            )
            os.makedirs(TMP_DIR, exist_ok=True); tmp = tempfile.mkdtemp(dir=TMP_DIR, prefix="export_"); self.logger.debug("Temporary directory: %s", tmp); aud_path = os.path.join(tmp, "audio.wav")
            total = self.animator.duration(); self.logger.info("Animation duration: %.2f seconds (%d characters)", total, len(self.animator.display_chars))
            is_short = "Short" in self.codec_profile; effective_max = self.max_duration
            if is_short and effective_max is None:
                effective_max = YOUTUBE_SHORT_MAX_DURATION
            if effective_max is not None and total > effective_max:
                self.logger.warning( "Source duration %.1fs exceeds limit %.0fs; truncating.", total, effective_max,
                )
                self.status.emit( f"Note: source is {total:.1f}s; truncating to " f"{effective_max:.0f}s (YouTube Shorts limit)."
                ); total = effective_max
            n_frames = max(1, int(total * self.fps)); self.logger.info("Total frames to render: %d (%.2fs × %d fps)", n_frames, total, self.fps)
            blink_period = self.renderer.CURSOR_BLINK_PERIOD; w, h = self.renderer.width, self.renderer.height
            if is_short and not is_short_resolution(w, h):
                self.logger.warning( "YouTube Short selected but resolution %dx%d is not vertical 9:16.", w, h
                )
                self.status.emit( f"Warning: YouTube Short selected but resolution is " f"{w}x{h} (not vertical 9:16). Consider switching to " f"'YouTube Short (9:16)' in the Resolution dropdown."
                ); is_gif = "GIF" in self.codec_profile
            has_audio = (self.sound_gen is not None and not is_gif)
            if not self._check_ffmpeg():
                self.logger.critical("FFmpeg not found on PATH — cannot export."); self.error.emit("FFmpeg is required for exports but was not found on PATH."); shutil.rmtree(tmp, ignore_errors=True); return
            if has_audio:
                self.logger.info( "Generating audio track (%s, volume %.0f%%)...", self.sound_gen.profile, self.volume * 100,
                )
                est_duration = self.animator.duration(); est_samples = int(est_duration * 44100); est_audio_mb = (est_samples * 4 * 2 + est_samples * 2) / (1024 * 1024)
                self.logger.info( "Estimated audio memory: ~%.0f MB (%.1f s, %d samples, float32 mix)", est_audio_mb, est_duration, est_samples,
                )
                t0 = _time.perf_counter()
                if effective_max is not None and effective_max < self.animator.duration():
                    char_ts = [ (ts, ch) for ts, ch in self.animator.char_timestamps() if ts <= effective_max
                    ]
                    self.logger.debug("Audio: using %d/%d timestamps (truncated)", len(char_ts), len(self.animator.char_timestamps())); self.sound_gen.generate_audio_track(char_ts, aud_path, self.volume)
                else:
                    self.sound_gen.generate_audio_track( self.animator.char_timestamps(), aud_path, self.volume
                    )
                has_audio = os.path.exists(aud_path) and os.path.getsize(aud_path) > 0
                if has_audio:
                    aud_size_mb = os.path.getsize(aud_path) / (1024 * 1024)
                    self.logger.info( "Audio track generated in %.2fs (%.2f MB)", _time.perf_counter() - t0, aud_size_mb,
                    )
                else:
                    self.logger.warning("Audio track generation produced no output.")
            self._export_ffmpeg_pipe(tmp, aud_path, n_frames, w, h, has_audio, blink_period)
            if self._cancel_event.is_set():
                if os.path.exists(self.output):
                    try:
                        os.remove(self.output)
                    except OSError:
                        pass
                shutil.rmtree(tmp, ignore_errors=True); return
            if self.subtitle_path:
                try:
                    self.logger.info("Writing subtitle file: %s", self.subtitle_path); self._write_srt(self.subtitle_path, max_time=total); self.status.emit(f"Subtitles: {self.subtitle_path}")
                    self.logger.info("Subtitles written successfully.")
                except Exception as e:
                    self.logger.warning("Failed to write subtitles: %s", e)
            self.logger.info("Export complete → %s", self.output); self.finished_ok.emit(self.output); shutil.rmtree(tmp, ignore_errors=True)
        except Exception as e:
            self.logger.error("Export failed: %s", e, exc_info=True); self.error.emit(str(e))
            if os.path.exists(self.output):
                try:
                    os.remove(self.output)
                except OSError:
                    pass
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)

    def _export_ffmpeg_pipe( self, tmp: str, aud_path: str, n_frames: int, w: int, h: int, has_audio: bool, blink_period: float,
    ) -> None:
        self.logger.debug("Building FFmpeg command for %s...", self.codec_profile); gpu_name, gpu_total_mb, gpu_free_mb = self._detect_gpu_info(); gpu_tier = None
        frame_chunk = 1  # default: write every frame (software path)
        if gpu_total_mb > 0:
            gpu_tier = self._smart_gpu_tier(gpu_total_mb); frame_chunk = gpu_tier["frame_chunk"]
            self.logger.info( "GPU detected: %s (%d MB total, %d MB free) → tier: %s", gpu_name, gpu_total_mb, gpu_free_mb, gpu_tier["name"],
            )
            self.gpu_info.emit( f"{gpu_name} | {gpu_total_mb} MB | Tier: {gpu_tier['name']}"
            )
        else:
            self.logger.debug("No NVIDIA GPU detected (or nvidia-smi unavailable).")
        cmd = [ "ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(self.fps), "-i", "pipe:0",
        ]; is_nvenc = False  # track whether we're using NVENC for chunking
        if "GIF" in self.codec_profile:
            self.logger.info("Codec: GIF (fps capped at %d, palette-based dithering)", min(self.fps, 15))
            cmd += [ "-vf", f"fps={min(self.fps, 15)},scale={w}:-1:flags=lanczos," f"split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
            ]
        elif "WebM" in self.codec_profile:
            if has_audio:
                cmd += ["-i", aud_path]; self.logger.info("Codec: WebM (VP9 video, CRF 30; Opus audio)"); cmd += ["-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0", "-pix_fmt", "yuv420p"]
            if has_audio:
                cmd += ["-c:a", "libopus", "-b:a", "128k", "-ac", "2"]
        elif "YouTube" in self.codec_profile:
            video_bitrate, level_x10 = youtube_bitrate_for(w, h, self.fps); level_str = f"{level_x10 // 10}.{level_x10 % 10}"
            if has_audio:
                cmd += ["-i", aud_path]
            bitrate_kbps = video_bitrate // 1000; is_short = "Short" in self.codec_profile; profile_label = "YouTube Short" if is_short else "YouTube Video"
            self.logger.info( "%s: %dx%d @ %dfps → %d kbps video, H.264 level %s", profile_label, w, h, self.fps, bitrate_kbps, level_str,
            )
            self.status.emit( f"{profile_label}: {w}x{h} @ {self.fps}fps, " f"{bitrate_kbps} kbps H.264 (level {level_str})"
            )
            hw = self._detect_hw_encoder() if self.use_hw_accel else None
            if hw is not None:
                enc_name, _hw_preset = hw
                if "nvenc" in enc_name and gpu_tier is not None:
                    is_nvenc = True
                    self.logger.info( "Smart NVENC: tier=%s, preset=%s, surfaces=%d, " "multipass=%s, lookahead=%s, chunk=%d frames", gpu_tier["name"], gpu_tier["nvenc_preset"], gpu_tier["nvenc_surfaces"], gpu_tier["nvenc_multipass"], gpu_tier["nvenc_lookahead"], frame_chunk,
                    )
                    self.status.emit( f"NVENC ({gpu_tier['name']}): {gpu_tier['nvenc_preset']} preset, " f"{gpu_tier['nvenc_surfaces']} surfaces, chunk={frame_chunk}"
                    )
                    cmd += ["-c:v", enc_name]; cmd += ["-profile:v", "high", "-level", level_str]; cmd += self._build_nvenc_args(gpu_tier, w, h, bitrate_kbps); cmd += ["-movflags", "+faststart"]
                else:
                    self.logger.info("Hardware encoder detected: %s (non-NVENC, using generic hw path)", enc_name)
                    cmd += [ "-c:v", enc_name, "-profile:v", "high", "-level", level_str, "-pix_fmt", "yuv420p", "-b:v", f"{bitrate_kbps}k", "-maxrate", f"{bitrate_kbps}k", "-bufsize", f"{bitrate_kbps * 2}k",
                    ]
                    if "qsv" in enc_name:
                        cmd += ["-rc_mode", "vbr"]
                    elif "amf" in enc_name:
                        cmd += ["-rc_mode", "VBR_PEAK"]; cmd += ["-movflags", "+faststart"]
                    if _hw_preset:
                        cmd += ["-preset", _hw_preset]
            else:
                if self.use_hw_accel:
                    self.logger.info( "Hardware acceleration requested but no GPU encoder " "found; falling back to libx264."
                    )
                cmd += [ "-c:v", "libx264", "-profile:v", "high", "-level", level_str, "-preset", self.preset, "-b:v", f"{bitrate_kbps}k", "-maxrate", f"{bitrate_kbps}k", "-bufsize", f"{bitrate_kbps * 2}k", "-pix_fmt", "yuv420p", "-bf", "2", "-refs", "4", "-g", str(self.fps * 2), "-movflags", "+faststart",  # GOP = 2s (keyframe every 2s)
                ]
            if has_audio:
                self.logger.debug("Audio codec: AAC 128kbps stereo (YouTube SDR)"); cmd += ["-c:a", "aac", "-b:a", "128k", "-ac", "2"]
            if self.metadata_title:
                cmd += ["-metadata", f"title={self.metadata_title}"]
            if self.metadata_description:
                cmd += ["-metadata", f"description={self.metadata_description}"]; cmd += ["-metadata", f"encoder=CodeTypingVideoGenerator ({profile_label})"]
        else:  # MP4 (H.264)
            hw = self._detect_hw_encoder() if self.use_hw_accel else None
            if has_audio:
                cmd += ["-i", aud_path]
            if hw is not None:
                enc_name, _hw_preset = hw
                if "nvenc" in enc_name and gpu_tier is not None:
                    is_nvenc = True
                    self.logger.info( "Smart NVENC: tier=%s, preset=%s, surfaces=%d, " "multipass=%s, lookahead=%s, chunk=%d frames", gpu_tier["name"], gpu_tier["nvenc_preset"], gpu_tier["nvenc_surfaces"], gpu_tier["nvenc_multipass"], gpu_tier["nvenc_lookahead"], frame_chunk,
                    )
                    self.status.emit( f"NVENC ({gpu_tier['name']}): {gpu_tier['nvenc_preset']} preset, " f"{gpu_tier['nvenc_surfaces']} surfaces, chunk={frame_chunk}"
                    )
                    cmd += ["-c:v", enc_name]; nvenc_args = self._build_nvenc_args(gpu_tier, w, h); nvenc_args = [a for a in nvenc_args if a != "20"]
                    for idx_a in range(len(nvenc_args)):
                        if nvenc_args[idx_a] == "-cq":
                            nvenc_args[idx_a + 1] = str(self.crf)
                            break
                    cmd += nvenc_args; cmd += ["-movflags", "+faststart"]
                else:
                    self.logger.info("Hardware encoder detected: %s (non-NVENC, using generic hw path)", enc_name); self.status.emit(f"Using hardware encoder: {enc_name}")
                    cmd += [ "-c:v", enc_name, "-pix_fmt", "yuv420p",
                    ]
                    if "qsv" in enc_name:
                        cmd += ["-rc_mode", "vbr", "-global_quality", str(self.crf * 5)]
                    elif "amf" in enc_name:
                        cmd += ["-rc_mode", "VBR_PEAK", "-quality", str(self.crf)]
                    elif "videotoolbox" in enc_name:
                        cmd += ["-q:v", str(self.crf)]
                    else:
                        cmd += ["-b:v", "0", "-cq", str(self.crf)]; cmd += ["-movflags", "+faststart"]
                    if _hw_preset:
                        cmd += ["-preset", _hw_preset]
            else:
                if self.use_hw_accel:
                    self.logger.info( "Hardware acceleration requested but no GPU encoder " "found; falling back to libx264."
                    )
                self.logger.info("Software encoder: libx264 (preset=%s, CRF=%d)", self.preset, self.crf)
                cmd += [ "-c:v", "libx264", "-profile:v", "high", "-level", "4.2", "-preset", self.preset, "-crf", str(self.crf), "-pix_fmt", "yuv420p", "-bf", "2", "-refs", "4", "-movflags", "+faststart",
                ]
            if has_audio:
                self.logger.debug("Audio codec: AAC 192kbps stereo"); cmd += ["-c:a", "aac", "-b:a", "192k"]
        cmd.append(self.output); self.logger.debug("FFmpeg command: %s", " ".join(cmd))
        proc = subprocess.Popen( cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        stderr_chunks: list[bytes] = []
        def _drain():
            while True:
                chunk = proc.stderr.read(8192)  # type: ignore[union-attr]
                if not chunk:
                    break
                stderr_chunks.append(chunk)
        drain_t = threading.Thread(target=_drain, daemon=True); drain_t.start()
        scratch = QImage(w, h, QImage.Format_RGB32)
        export_start = _time.time()
        frame_size = w * h * 3; frame_render_total = 0.0; chunk_buf = bytearray(frame_size * frame_chunk) if frame_chunk > 1 else None
        chunk_fill = 0  # number of frames currently in the buffer
        effective_chunk = frame_chunk  # may be reduced under VRAM pressure
        total_vram_for_monitor = gpu_total_mb  # 0 if no GPU detected
        low_vram_warned = False
        critical_vram_warned = False
        try:
            self.logger.info("Starting frame render + encode pipeline (%d frames, chunk=%d)...", n_frames, effective_chunk)
            for fi in range(n_frames):
                if self._cancel_event.is_set():
                    self.logger.info("Export cancelled by user at frame %d/%d.", fi, n_frames)
                    try:
                        proc.stdin.close()  # type: ignore[union-attr]
                    except Exception:
                        pass
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=3)
                    self.error.emit("Cancelled")
                    return
                t = fi / self.fps; rt0 = _time.perf_counter(); qimg = self._render_frame_at(t, blink_period, scratch=scratch)
                raw = self._qimg_to_raw_rgb(qimg); frame_render_total += _time.perf_counter() - rt0
                if len(raw) != frame_size:
                    raise RuntimeError( f"Frame {fi}: size {len(raw)} != expected {frame_size}"
                    )
                if chunk_buf is not None:
                    chunk_buf[chunk_fill * frame_size : (chunk_fill + 1) * frame_size] = raw; chunk_fill += 1
                    if chunk_fill >= effective_chunk or fi == n_frames - 1:
                        try:
                            proc.stdin.write( bytes(chunk_buf[: chunk_fill * frame_size])
                            )  # type: ignore[union-attr]
                        except BrokenPipeError:
                            self.logger.warning( "Broken pipe from FFmpeg at frame %d — FFmpeg may have exited early.", fi,
                            )
                            break
                        chunk_fill = 0
                else:
                    try:
                        proc.stdin.write(raw)  # type: ignore[union-attr]
                    except BrokenPipeError:
                        self.logger.warning( "Broken pipe from FFmpeg at frame %d — FFmpeg may have exited early.", fi,
                        ); break
                if ( is_nvenc and total_vram_for_monitor > 0 and fi > 0 and fi % GPU_VRAM_POLL_INTERVAL == 0
                ):
                    free_mb = self._poll_gpu_free_vram()
                    if free_mb > 0:
                        free_frac = free_mb / total_vram_for_monitor
                        if free_frac < 0.05 and not critical_vram_warned:
                            self.logger.warning( "CRITICAL: GPU VRAM critically low (%d MB free / %d MB total, %.1f%%). " "Close other GPU applications to avoid encoding failures.", free_mb, total_vram_for_monitor, free_frac * 100,
                            )
                            self.status.emit( "WARNING: GPU VRAM critically low! Close other GPU apps."
                            ); critical_vram_warned = True
                            if effective_chunk > 1:
                                effective_chunk = 1; chunk_buf = None  # disable chunking
                                self.logger.info( "VRAM critical — disabled frame chunking to reduce GPU pressure."
                                )
                        elif free_frac < GPU_VRAM_LOW_WATERMARK and not low_vram_warned:
                            self.logger.warning( "GPU VRAM running low (%d MB free / %d MB total, %.1f%%). " "Consider closing other GPU applications for best performance.", free_mb, total_vram_for_monitor, free_frac * 100,
                            )
                            self.status.emit( f"GPU VRAM low ({free_mb} MB free). Closing other GPU apps is recommended."
                            ); low_vram_warned = True
                            if effective_chunk > 1:
                                effective_chunk = max(1, effective_chunk // 2)
                                self.logger.info( "VRAM low — reduced frame chunk to %d.", effective_chunk
                                )
                                if effective_chunk == 1:
                                    chunk_buf = None; pct = int((fi + 1) / n_frames * 100); self.progress.emit(pct)
                if fi % max(1, n_frames // 20) == 0 and fi > 0:
                    pct = int((fi + 1) / n_frames * 100); elapsed = _time.time() - export_start; eta = elapsed / (fi + 1) * (n_frames - fi - 1)
                    self.logger.debug( "Progress: %d%% (%d/%d frames, %.1fs elapsed, ETA %ds)", pct, fi + 1, n_frames, elapsed, int(eta),
                    )
                    self.status.emit(f"Encoding... {pct}% (ETA: {int(eta)}s)")
            if chunk_buf is not None and chunk_fill > 0:
                try:
                    proc.stdin.write( bytes(chunk_buf[: chunk_fill * frame_size])
                    )  # type: ignore[union-attr]
                except BrokenPipeError:
                    pass
            try:
                proc.stdin.close()  # type: ignore[union-attr]
            except Exception:
                pass
            proc.wait(timeout=600); drain_t.join(timeout=5)
            if proc.returncode != 0:
                err = b"".join(stderr_chunks).decode("utf-8", errors="ignore")[-800:]; self.logger.error("FFmpeg exited with code %d.\n%s", proc.returncode, err); raise RuntimeError(f"FFmpeg encoding failed: {err}")
            total_export_time = _time.time() - export_start
            if n_frames > 0 and frame_render_total > 0:
                avg_ms = frame_render_total / n_frames * 1000; avg_fps = n_frames / frame_render_total
                self.logger.info( "Render stats: %d frames in %.2fs (%.1f ms/frame, %.1f fps render throughput)", n_frames, frame_render_total, avg_ms, avg_fps,
                )
                self.status.emit( f"Rendered {n_frames} frames at {avg_fps:.1f} fps ({avg_ms:.1f} ms/frame)"
                )
            out_size = os.path.getsize(self.output) if os.path.exists(self.output) else 0; out_size_mb = out_size / (1024 * 1024)
            self.logger.info( "Export finished in %.1fs total → %s (%.2f MB)", total_export_time, self.output, out_size_mb,
            )
        except Exception:
            self.logger.exception("Error during frame encoding loop")
            try:
                proc.stdin.close()  # type: ignore[union-attr]
            except Exception:
                pass; proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill(); proc.wait(timeout=3); raise

@dataclass
class BatchItem:
    """One item in the batch queue."""

    file_path: Optional[str] = None
    inline_code: Optional[str] = None
    display_name: str = ""
    language_override: Optional[str] = None
    title_override: Optional[str] = None
    output_name: Optional[str] = None

    status: str = "Pending"  # Pending / Rendering / Done / Failed / Skipped
    error: Optional[str] = None
    output_path: Optional[str] = None

    def resolve_display_name(self):
        """Return a human-friendly name for list display."""
        if self.display_name:
            return self.display_name
        if self.file_path:
            return os.path.basename(self.file_path)
        return "(inline snippet)"

@dataclass
class BatchSettings:
    """Snapshot of all export-relevant settings from the main window."""

    theme_name: str = "Dracula"
    font_family: str = "Consolas"
    font_size: int = 22
    autofit: bool = True
    max_lines: int = 0
    tab_size: int = 4
    padding: int = 50
    title_text: str = "main.py — Code Editor"
    show_line_numbers: bool = True
    show_window_chrome: bool = True
    language: str = "Python"
    show_keyboard: bool = False
    keyboard_gap: int = 20
    keyboard_scale: float = 1.0
    keyboard_layout: str = "QWERTY (US)"
    keyboard_position: str = "Below Code"
    keyboard_opacity: float = 1.0
    keyboard_radius: int = 6
    show_stats: bool = False
    stats_position: str = "Bottom-Right"
    bg_image: Optional[str] = None
    resolution: str = "YouTube 1080p"

    wpm: int = 100
    typo_rate: float = 0.01
    start_pause: float = 1.0
    end_pause: float = 2.0
    speed_ramp: str = "None"
    ramp_strength: float = 0.5
    burst_typing: bool = True
    thinking_pauses: bool = True
    fatigue: float = 0.0

    fps: int = 30
    crf: int = 18
    preset: str = "medium"
    codec_profile: str = "MP4 (H.264)"
    sound_profile: str = "Mechanical"
    sound_volume: float = 0.5
    use_hw_accel: bool = False
    export_srt: bool = False
    metadata_title: str = ""
    metadata_description: str = ""

class BatchExporter(QThread):
    """Sequentially export a queue of code files to video."""

    item_started = Signal(int, str)
    item_progress = Signal(int)
    item_finished = Signal(int, str)
    item_failed = Signal(int, str)
    batch_progress = Signal(int)
    status = Signal(str)
    batch_finished = Signal(int, int)

    def __init__( self, items: List[BatchItem], settings: BatchSettings, parent=None,
    ) -> None:
        super().__init__(parent); self.items = items; self.settings = settings; self.logger = logging.getLogger("BatchExporter"); self._cancel = False; self._current_exporter: Optional[VideoExporter] = None
        self._sound_gen: Optional[TypingSoundGenerator] = None

    def cancel(self):
        """Cancel the batch: stops the current item and skips the rest."""
        self._cancel = True
        if self._current_exporter is not None:
            self._current_exporter.cancel()

    def run(self):
        total = len(self.items)
        if total == 0:
            self.batch_finished.emit(0, 0); return
        succeeded = 0; failed = 0; skipped = 0
        try:
            self._sound_gen = TypingSoundGenerator( profile=self.settings.sound_profile
            )
        except Exception as e:
            self.logger.error("Failed to init sound generator: %s", e); self._sound_gen = None
        for i, item in enumerate(self.items):
            if self._cancel:
                item.status = "Skipped"; skipped += 1; continue
            self.item_started.emit(i, item.resolve_display_name())
            self.status.emit( f"[{i + 1}/{total}] Rendering: {item.resolve_display_name()}"
            ); item.status = "Rendering"
            try:
                output_path = self._export_item(item, i, total)
                if output_path is not None:
                    item.status = "Done"; item.output_path = output_path; succeeded += 1; self.item_finished.emit(i, output_path)
                else:
                    item.status = "Skipped"; skipped += 1
            except Exception as e:
                self.logger.error( "Item %d (%s) failed: %s", i, item.resolve_display_name(), e, exc_info=True,
                ); item.status = "Failed"
                item.error = str(e); failed += 1; self.item_failed.emit(i, str(e)); pct = int((i + 1) / total * 100); self.batch_progress.emit(pct); self._sound_gen = None; self._current_exporter = None
        summary = f"Batch complete: {succeeded}/{total} succeeded"
        if failed:
            summary += f", {failed} failed"
        if skipped:
            summary += f", {skipped} skipped"; self.status.emit(summary); self.batch_finished.emit(succeeded, total)

    def _export_item( self, item: BatchItem, index: int, total: int
    ) -> Optional[str]:
        """Export one item. Returns the output path on success, or
        ``None`` if the batch was cancelled mid-item."""; s = self.settings
        if item.file_path is not None:
            with open(item.file_path, "r", encoding="utf-8", errors="replace") as f:
                code = f.read()
        elif item.inline_code is not None:
            code = item.inline_code
        else:
            raise ValueError("BatchItem has neither file_path nor inline_code")
        if not code.strip():
            raise ValueError("Source code is empty")
        if item.language_override:
            language = item.language_override
        elif item.file_path:
            ext = os.path.splitext(item.file_path)[1].lower(); language = EXT_TO_LANGUAGE.get(ext, s.language)
        else:
            language = s.language
        if item.title_override:
            title = item.title_override
        elif item.file_path:
            title = f"{os.path.basename(item.file_path)} \u2014 Code Editor"
        else:
            title = s.title_text; os.makedirs(OUTPUT_DIR, exist_ok=True)
        if item.output_name:
            base = item.output_name
        elif item.file_path:
            base = os.path.splitext(os.path.basename(item.file_path))[0]
        else:
            base = f"snippet_{index + 1:03d}"; fmt = s.codec_profile
        if "WebM" in fmt:
            ext = ".webm"
        elif "GIF" in fmt:
            ext = ".gif"
        elif "YouTube Short" in fmt:
            ext = "_short.mp4"
        elif "YouTube" in fmt:
            ext = "_yt.mp4"
        else:
            ext = ".mp4"; output_path = os.path.join(OUTPUT_DIR, f"{base}{ext}")
        if os.path.exists(output_path):
            counter = 2
            while os.path.exists( os.path.join(OUTPUT_DIR, f"{base}_{counter}{ext}")
            ):
                counter += 1; output_path = os.path.join(OUTPUT_DIR, f"{base}_{counter}{ext}"); w, h = RESOLUTION_PRESETS.get(s.resolution, (1920, 1080))
        if s.autofit:
            code_lines = code.count("\n") + 1; target = s.max_lines or None
            font_size = CodeRenderer.auto_font_size( code_lines=code_lines, width=w, height=h, padding=s.padding, show_window_chrome=s.show_window_chrome, show_line_numbers=s.show_line_numbers, show_keyboard=s.show_keyboard, tab_size=s.tab_size, target_lines=target, keyboard_position=s.keyboard_position, keyboard_scale=s.keyboard_scale, keyboard_gap=s.keyboard_gap, code=code, font_family=s.font_family,
            )
        else:
            font_size = s.font_size
        renderer = CodeRenderer( width=w, height=h, theme_name=s.theme_name, font_family=s.font_family, font_size=font_size, show_line_numbers=s.show_line_numbers, show_window_chrome=s.show_window_chrome, padding=s.padding, tab_size=s.tab_size, title_text=title, language=language, show_keyboard=s.show_keyboard, keyboard_gap=s.keyboard_gap, keyboard_scale=s.keyboard_scale, keyboard_layout=s.keyboard_layout, keyboard_position=s.keyboard_position, keyboard_opacity=s.keyboard_opacity, keyboard_radius=s.keyboard_radius, show_stats=s.show_stats, stats_position=s.stats_position,
        )
        if s.bg_image:
            renderer.set_background_image(s.bg_image)
        animator = TypingAnimator( code, base_wpm=s.wpm, humanize=True, typo_rate=s.typo_rate, start_pause=s.start_pause, end_pause=s.end_pause, speed_ramp=s.speed_ramp, ramp_strength=s.ramp_strength, burst_typing=s.burst_typing, thinking_pauses=s.thinking_pauses, fatigue=s.fatigue,
        ); renderer.animator_ref = animator
        subtitle_path: Optional[str] = None
        if s.export_srt and "GIF" not in fmt:
            sub_base, _ = os.path.splitext(output_path); subtitle_path = sub_base + ".srt"
        exporter = VideoExporter( code=code, output=output_path, renderer=renderer, animator=animator, fps=s.fps, sound_gen=self._sound_gen, volume=s.sound_volume, codec_profile=s.codec_profile, crf=s.crf, preset=s.preset, subtitle_path=subtitle_path, use_hw_accel=s.use_hw_accel, metadata_title=s.metadata_title, metadata_description=s.metadata_description,
        ); self._current_exporter = exporter
        result = {"ok": False, "error": None, "path": None}
        def _on_progress(pct):
            self.item_progress.emit(pct)
        def _on_status(msg):
            self.status.emit( f"[{index + 1}/{total}] {item.resolve_display_name()}: {msg}"
            )
        def _on_done(path):
            result["ok"] = True; result["path"] = path
        def _on_error(msg):
            result["error"] = msg; exporter.progress.connect(_on_progress); exporter.status.connect(_on_status); exporter.finished_ok.connect(_on_done); exporter.error.connect(_on_error); exporter.run()
        self._current_exporter = None
        if self._cancel:
            return None  # batch was cancelled mid-item
        if result["ok"]:
            return result["path"]
        if result["error"]:
            raise RuntimeError(result["error"])
        raise RuntimeError( "Export finished without emitting success or error signal"
        )

# ======================================================================
# main_window.py
# ======================================================================

"""
Main application window.

Wires together the editor, settings panel, live preview, timeline
scrubber, and exporter. Provides menu actions and keyboard shortcuts,
and persists user preferences via QSettings.
"""

SAMPLE_PY = (
    'def fibonacci(n: int) -> list:\n'
    '    """Generate Fibonacci sequence"""\n'
    '    if n <= 0:\n'
    '        return []\n'
    '    sequence = [0, 1]\n'
    '    for _ in range(2, n):\n'
    '        sequence.append(sequence[-1] + sequence[-2])\n'
    '    return sequence[:n]\n\n'
    'if __name__ == "__main__":\n'
    '    result = fibonacci(10)\n'
    '    print(f"Fibonacci: {result}")'
)

SAMPLE_JS = (
    'const fibonacci = (n) => {\n'
    '  // Generate Fibonacci sequence\n'
    '  if (n <= 0) return []\n'
    '  const sequence = [0, 1];\n'
    '  for (let i = 2; i < n; i++) {\n'
    '    sequence.push(sequence[i - 1] + sequence[i - 2]);\n'
    '  }\n'
    '  return sequence.slice(0, n)\n'
    '};\n\n'
    'const result = fibonacci(10);\n'
    'console.log(`Fibonacci: ${result}`);'
)

SAMPLE_GO = (
    'package main\n\n'
    'import "fmt"\n\n'
    '// fibonacci returns the first n Fibonacci numbers.\n'
    'func fibonacci(n int) []int {\n'
    '    if n <= 0 {\n'
    '        return []int{}\n'
    '    }\n'
    '    seq := []int{0, 1}\n'
    '    for i := 2; i < n; i++ {\n'
    '        seq = append(seq, seq[i-1]+seq[i-2])\n'
    '    }\n'
    '    return seq[:n]\n'
    '}\n\n'
    'func main() {\n'
    '    fmt.Println(fibonacci(10))\n'
    '}\n'
)

SAMPLE_RUST = (
    'fn fibonacci(n: usize) -> Vec<u64> {\n'
    '    let mut seq = vec![0, 1];\n'
    '    while seq.len() < n {\n'
    '        let next = seq[seq.len() - 1] + seq[seq.len() - 2];\n'
    '        seq.push(next);\n'
    '    }\n'
    '    seq.truncate(n);\n'
    '    seq\n'
    '}\n\n'
    'fn main() {\n'
    '    println!("{:?}", fibonacci(10));\n'
    '}\n'
)

SAMPLE_TS = (
    'interface FibonacciResult {\n'
    '    sequence: number[];\n'
    '    sum: number;\n'
    '}\n\n'
    'function fibonacci(n: number): FibonacciResult {\n'
    '    // Generate Fibonacci sequence\n'
    '    if (n <= 0) return { sequence: [], sum: 0 }\n'
    '    const sequence: number[] = [0, 1];\n'
    '    for (let i = 2; i < n; i++) {\n'
    '        sequence.push(sequence[i - 1] + sequence[i - 2]);\n'
    '    }\n'
    '    const result = sequence.slice(0, n);\n'
    '    return { sequence: result, sum: result.reduce((a, b) => a + b, 0) }\n'
    '}\n\n'
    'const { sequence, sum } = fibonacci(10);\n'
    'console.log(`Fibonacci: ${sequence}`);\n'
    'console.log(`Sum: ${sum}`);'
)

SAMPLE_C = (
    '#include <stdio.h>\n'
    '#include <stdlib.h>\n\n'
    '/* Generate first n Fibonacci numbers */\n'
    'int* fibonacci(int n) {\n'
    '    if (n <= 0) return NULL\n'
    '    int* seq = (int*)malloc(n * sizeof(int));\n'
    '    if (!seq) return NULL\n'
    '    if (n >= 1) seq[0] = 0;\n'
    '    if (n >= 2) seq[1] = 1;\n'
    '    for (int i = 2; i < n; i++) {\n'
    '        seq[i] = seq[i - 1] + seq[i - 2];\n'
    '    }\n'
    '    return seq\n'
    '}\n\n'
    'int main() {\n'
    '    int n = 10;\n'
    '    int* result = fibonacci(n);\n'
    '    for (int i = 0; i < n; i++) {\n'
    '        printf("%d ", result[i]);\n'
    '    }\n'
    '    printf("\\n");\n'
    '    free(result);\n'
    '    return 0\n'
    '}'
)

SAMPLE_CODE: dict[str, str] = {
    "Python": SAMPLE_PY,
    "JavaScript": SAMPLE_JS,
    "TypeScript": SAMPLE_TS,
    "C/C++/Java": SAMPLE_C,
    "Go": SAMPLE_GO,
    "Rust": SAMPLE_RUST,
}

LANGUAGE_EXTENSIONS: dict[str, list[str]] = {
    "Python": [".py"],
    "JavaScript": [".js", ".jsx"],
    "TypeScript": [".ts", ".tsx"],
    "C/C++/Java": [".java", ".c", ".cpp", ".h", ".hpp", ".cs"],
    "Go": [".go"],
    "Rust": [".rs"],
}

HIGHLIGHTED_EXTENSIONS: set[str] = set(EXT_TO_LANGUAGE.keys())

def _panel_header(icon: str, title):
    """Return a styled section-header widget with an icon and label."""
    w = QWidget()
    w.setObjectName("panelHeader")
    lay = QHBoxLayout(w)
    lay.setContentsMargins(12, 8, 12, 8)
    lay.setSpacing(8)
    icon_lbl = QLabel(icon)
    icon_lbl.setStyleSheet("font-size: 16px;")
    lay.addWidget(icon_lbl)
    txt = QLabel(title)
    txt.setObjectName("panelHeaderText")
    lay.addWidget(txt)
    lay.addStretch()
    return w

def _form2col():
    """Return a pre-configured 4-column form grid (label, widget, label, widget)."""
    g = QGridLayout()
    g.setSpacing(8)
    g.setColumnStretch(1, 1)
    g.setColumnStretch(3, 1)
    return g

def _slider_row(
    name: str,
    lo: int,
    hi: int,
    default: int,
    suffix: str,
    tooltip: str = "",
) -> tuple[QHBoxLayout, QSlider, QLabel]:
    """Return (layout, slider, value_label) for a labelled slider row."""
    row = QHBoxLayout()
    row.setSpacing(6)
    sl = QSlider(Qt.Horizontal)
    sl.setRange(lo, hi)
    sl.setValue(default)
    if tooltip:
        sl.setToolTip(tooltip)
    val_lbl = QLabel(f"{default}{suffix}")
    val_lbl.setFixedWidth(48)
    val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def _update(v):
        val_lbl.setText(f"{v}{suffix}")

    sl.valueChanged.connect(_update)
    row.addWidget(sl, 1)
    row.addWidget(val_lbl)
    return row, sl, val_lbl

class MainWindow(QMainWindow):
    """Top-level application window."""

    def __init__(self):
        super().__init__(); self.logger = logging.getLogger("MainWindow"); self.setWindowTitle("Code Typing Video Generator"); self.setMinimumSize(1350, 850); ensure_cwd_dirs(); ensure_preset_dir()
        self.is_playing = False; self.animator: Optional[TypingAnimator] = None; self.renderer: Optional[CodeRenderer] = None; self.sound_gen = TypingSoundGenerator(profile="Mechanical")
        self.exporter: Optional[VideoExporter] = None; self._last_vis = 0; self._play_t0 = 0.0; self._play_offset = 0.0; self._current_input_file: Optional[str] = None; self._sfx_dir: Optional[str] = None
        self._sfx: dict[tuple[str, int], QSoundEffect] = {}; self._preview_sfx: Optional[QSoundEffect] = None; self._preview_tmp: Optional[str] = None; self._scrubbing = False
        self._preview_scratch: Optional[QImage] = None; self._bg_image_path: Optional[str] = None; self._settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self._preview_timer = QTimer(self); self._preview_timer.setInterval(16); self._preview_timer.timeout.connect(self._tick); self._code_debounce = QTimer(self); self._code_debounce.setSingleShot(True)
        self._code_debounce.setInterval(400); self._code_debounce.timeout.connect(self._static_preview); self._build_ui(); self._build_menu(); self._build_shortcuts(); self._init_sounds()
        self._restore_settings(); self._refresh_input_files(); self._initial_preview_pending = True; self.installEventFilter(self)

    def eventFilter(self, obj, event):
        if ( getattr(self, "_initial_preview_pending", False) and event.type() == QEvent.Show and obj is self
        ):
            self._initial_preview_pending = False; self.removeEventFilter(self); QTimer.singleShot(0, self._static_preview)
        return super().eventFilter(obj, event)

    def _init_sounds(self, profile="Mechanical"):
        if self._sfx_dir and os.path.isdir(self._sfx_dir):
            shutil.rmtree(self._sfx_dir, ignore_errors=True)
        os.makedirs(TMP_DIR, exist_ok=True); self._sfx_dir = tempfile.mkdtemp(dir=TMP_DIR, prefix="sfx_"); self._sfx = {}
        self.sound_gen = TypingSoundGenerator(profile=profile); volume = self.snd_vol_sl.value() / 100.0 if hasattr(self, "snd_vol_sl") else 0.5
        for kind in self.sound_gen.sounds.keys():
            sounds = self.sound_gen.sounds.get(kind)
            if not sounds:
                continue
            for i, snd in enumerate(sounds[:3]):
                path = os.path.join(self._sfx_dir, f"{kind}_{i}.wav"); self.sound_gen.save_wav(path, snd, volume=volume); eff = QSoundEffect(self); eff.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
                eff.setVolume(0.8); self._sfx[(kind, i)] = eff

    def _play_click(self, ch):
        """Play the matching sound for a typed character (live preview only)."""
        if ch == "\b":
            cmap = self.sound_gen._CATEGORY_MAPS.get(self.sound_gen.profile, {}); kind = cmap.get("\b", "backspace") if cmap else "backspace"
        else:
            kind = self.sound_gen._category_for(ch); n_variants = min(3, len(self.sound_gen.sounds.get(kind, [])))
        if n_variants == 0:
            kind = "key"; n_variants = min(3, len(self.sound_gen.sounds.get(kind, [])))
        if n_variants == 0:
            return
        sfx = self._sfx.get((kind, random.randint(0, n_variants - 1)))
        if sfx:
            sfx.play()

    def _scan_input_folder(self, lang_filter: str | None = None) -> List[Tuple[str, str]]:
        """Scan input/ folder recursively. If *lang_filter* is set, only return."""
        files: List[Tuple[str, str]] = []
        if not os.path.isdir(INPUT_DIR):
            return files
        allowed_exts: set[str] | None = None
        if lang_filter:
            allowed_exts = set(LANGUAGE_EXTENSIONS.get(lang_filter, []))
        for dirpath, dirnames, filenames in os.walk(INPUT_DIR):
            dirnames.sort(key=str.lower)
            for fname in sorted(filenames, key=str.lower):
                fpath = os.path.join(dirpath, fname)
                if not os.path.isfile(fpath):
                    continue
                ext = os.path.splitext(fname)[1].lower()
                if ext not in SUPPORTED_EXTENSIONS and ext != "":
                    continue
                if allowed_exts is not None and ext not in allowed_exts:
                    continue
                rel_path = os.path.relpath(fpath, INPUT_DIR); files.append((rel_path, fpath))
        return files

    def _refresh_input_files(self):
        lang_filter = self.lang_filter_cb.currentData(); self.input_file_cb.blockSignals(True); current_data = self.input_file_cb.currentData(); self.input_file_cb.clear()
        self.input_file_cb.addItem("\u2014 Select file from input/ \u2014", None); files = self._scan_input_folder(lang_filter=lang_filter); selected_idx = 0
        for i, (rel_path, fpath) in enumerate(files):
            display = rel_path; size_kb = os.path.getsize(fpath) / 1024; label = f"{display}  ({size_kb:.1f} KB)"; self.input_file_cb.addItem(label, fpath)
            if fpath == current_data:
                selected_idx = i + 1
        if files:
            self.input_file_cb.setCurrentIndex(selected_idx); self.input_file_cb.blockSignals(False); filter_tag = f" [{lang_filter}]" if lang_filter else ""
        folder_count = len(set(os.path.dirname(p) for _, p in files)) if files else 0; subfolder_note = f" ({folder_count} subfolder{'s' if folder_count != 1 else ''})" if folder_count > 1 else ""
        self.statusBar().showMessage(f"input/{filter_tag} \u2014 {len(files)} file(s){subfolder_note}")

    def _on_lang_filter_changed(self, index):
        self._refresh_input_files()

    def _on_sample_selected(self, index):
        lang_name = self.sample_cb.currentData()
        if not lang_name or lang_name not in SAMPLE_CODE:
            return
        self.editor.setPlainText(SAMPLE_CODE[lang_name]); self._current_input_file = None; self.lang_cb.setCurrentText(lang_name); self.sample_cb.blockSignals(True); self.sample_cb.setCurrentIndex(0)
        self.sample_cb.blockSignals(False); self.statusBar().showMessage(f"Loaded {lang_name} sample")

    def _auto_detect_language(self, fpath):
        """Set the language dropdown based on the file extension."""
        ext = os.path.splitext(fpath)[1].lower(); lang = EXT_TO_LANGUAGE.get(ext)
        if lang and lang in _LANG_DATA:
            self.lang_cb.setCurrentText(lang)

    def _on_input_file_selected(self, index):
        fpath = self.input_file_cb.itemData(index)
        if not fpath or not os.path.isfile(fpath):
            return
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(); self.editor.setPlainText(content); self._current_input_file = fpath; fname = os.path.basename(fpath); self.title_edit.setText(f"{fname} \u2014 Code Editor")
            self._auto_detect_language(fpath); rel_path = os.path.relpath(fpath, INPUT_DIR) if fpath.startswith(INPUT_DIR) else fname; self.statusBar().showMessage(f"Loaded: {rel_path}")
        except Exception as e:
            QMessageBox.warning(self, "Load Error", f"Could not read file:\n{e}")

    def _on_file_dropped(self, fpath):
        ext = os.path.splitext(fpath)[1].lower()
        if ext in SUPPORTED_EXTENSIONS:
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read(); self.editor.setPlainText(content); self._current_input_file = fpath; self.title_edit.setText(f"{os.path.basename(fpath)} \u2014 Code Editor"); self._auto_detect_language(fpath)
                self.statusBar().showMessage(f"Dropped: {os.path.basename(fpath)}")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not read dropped file:\n{e}")

    def _save_to_input(self):
        code = self.editor.toPlainText()
        if not code.strip():
            return
        name, ok = QInputDialog.getText(self, "Save to input/", "Filename:", text="snippet.py")
        if not ok or not name.strip():
            return
        name = name.strip()
        if not os.path.splitext(name)[1]:
            name += ".py"; fpath = os.path.join(INPUT_DIR, name)
        if os.path.exists(fpath):
            if QMessageBox.question(self, "Overwrite?", f"'{name}' already exists. Overwrite?") != QMessageBox.Yes:
                return
        try:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(code); self._current_input_file = fpath; self._refresh_input_files()
        except Exception as e:
            QMessageBox.warning(self, "Save Error", f"Could not save file:\n{e}")

    def _select_bg_image(self):
        path, _ = QFileDialog.getOpenFileName( self, "Select Background Image", "", "Images (*.png *.jpg *.jpeg *.bmp)",
        )
        if path:
            self._bg_image_path = path; self._static_preview()

    def _clear_bg_image(self):
        self._bg_image_path = None; self._static_preview()

    def _save_snapshot(self):
        """Save the current preview frame as a PNG to output/."""
        if not self.renderer or not self.animator:
            QMessageBox.information(self, "Snapshot", "Nothing to snapshot yet."); return
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        if self._current_input_file:
            base = os.path.splitext(os.path.basename(self._current_input_file))[0]
            t = (self.timeline_slider.value() / 1000.0) * self.animator.duration(); path = os.path.join(OUTPUT_DIR, f"{base}_snapshot_{int(t * 1000):06d}ms.png"); qimg = self._render_at(t)
        else:
            base = "code_typing"
            t = (self.timeline_slider.value() / 1000.0) * self.animator.duration(); path = os.path.join(OUTPUT_DIR, f"{base}_snapshot_{int(t * 1000):06d}ms.png"); qimg = self._render_at(t)
        if qimg is None:
            return
        if qimg.save(path, "PNG"):
            self.statusBar().showMessage(f"Snapshot saved: {path}")
        else:
            QMessageBox.warning(self, "Snapshot Error", f"Could not save PNG to:\n{path}")

    PRESET_KEYS = [ "theme", "font", "font_size", "tab_size", "title", "line_numbers", "window_chrome", "language", "resolution", "show_keyboard", "keyboard_gap", "keyboard_scale", "keyboard_layout", "keyboard_position", "keyboard_opacity", "keyboard_radius", "padding", "wpm", "typo_rate", "start_pause", "end_pause", "sound_profile", "sound_volume", "format", "fps", "crf", "speed_ramp", "ramp_strength", "burst_typing", "thinking_pauses", "fatigue", "show_stats", "stats_position", "use_hw_accel", "export_srt", "yt_title", "yt_description", "autofit_font", "max_lines",
    ]

    def _collect_preset(self):
        """Read all preset-able settings from the UI into a dict."""
        return { "theme": self.theme_cb.currentText(), "font": self._current_font_family, "font_size": self.size_sp.value(), "tab_size": self.tab_sp.value(), "title": self.title_edit.text(), "line_numbers": self.ln_chk.isChecked(), "window_chrome": self.chrome_chk.isChecked(), "language": self.lang_cb.currentText(), "resolution": self.res_cb.currentText(), "show_keyboard": self.kb_chk.isChecked(), "keyboard_gap": self.kb_gap_sl.value(), "keyboard_scale": self.kb_scale_sl.value(), "keyboard_layout": self.kb_layout_cb.currentText(), "keyboard_position": self.kb_pos_cb.currentText(), "keyboard_opacity": self.kb_opacity_sl.value(), "keyboard_radius": self.kb_radius_sp.value(), "padding": self.padding_sp.value(), "wpm": self.wpm_sp.value(), "typo_rate": self.typo_sp.value(), "start_pause": self.start_pause_sp.value(), "end_pause": self.end_pause_sp.value(), "sound_profile": self.snd_profile_cb.currentText(), "sound_volume": self.snd_vol_sl.value(), "format": self.format_cb.currentText(), "fps": self.fps_sp.value(), "crf": self.crf_sp.value(), "speed_ramp": self.ramp_cb.currentText(), "ramp_strength": self.ramp_strength_sl.value(), "burst_typing": self.burst_chk.isChecked(), "thinking_pauses": self.thinking_chk.isChecked(), "fatigue": self.fatigue_sl.value(), "show_stats": self.stats_chk.isChecked(), "stats_position": self.stats_pos_cb.currentText(), "use_hw_accel": self.hw_chk.isChecked(), "export_srt": self.srt_chk.isChecked(), "yt_title": self.yt_title_edit.text(), "yt_description": self.yt_desc_edit.text(),
        }

    def _apply_preset(self, data: dict):
        """Apply a preset dict back to the UI."""
        _widgets = [ self.theme_cb, self.font_cb, self.size_sp, self.tab_sp, self.title_edit, self.ln_chk, self.chrome_chk, self.lang_cb, self.res_cb, self.kb_chk, self.kb_gap_sl, self.kb_scale_sl, self.kb_layout_cb, self.kb_pos_cb, self.kb_opacity_sl, self.kb_radius_sp, self.padding_sp, self.wpm_sp, self.typo_sp, self.start_pause_sp, self.end_pause_sp, self.snd_profile_cb, self.snd_vol_sl, self.format_cb, self.fps_sp, self.crf_sp, self.ramp_cb, self.ramp_strength_sl, self.burst_chk, self.thinking_chk, self.fatigue_sl, self.stats_chk, self.stats_pos_cb, self.hw_chk, self.srt_chk, self.yt_title_edit, self.yt_desc_edit, self.autofit_chk,
        ]
        for _w in _widgets:
            _w.blockSignals(True)
        try:
            if "theme" in data:
                self.theme_cb.setCurrentText(data["theme"])
            if "font" in data:
                idx = self._find_font_index(self.font_cb, data["font"])
                if idx >= 0:
                    self.font_cb.setCurrentIndex(idx)
            if "font_size" in data:
                self.size_sp.setValue(int(data["font_size"]))
            if "tab_size" in data:
                self.tab_sp.setValue(int(data["tab_size"]))
            if "title" in data:
                self.title_edit.setText(data["title"])
            if "line_numbers" in data:
                self.ln_chk.setChecked(bool(data["line_numbers"]))
            if "window_chrome" in data:
                self.chrome_chk.setChecked(bool(data["window_chrome"]))
            if "language" in data:
                self.lang_cb.setCurrentText(data["language"])
            if "resolution" in data:
                self.res_cb.setCurrentText(data["resolution"])
            if "show_keyboard" in data:
                self.kb_chk.setChecked(bool(data["show_keyboard"]))
            if "keyboard_gap" in data:
                self.kb_gap_sl.setValue(int(data["keyboard_gap"]))
            if "keyboard_scale" in data:
                self.kb_scale_sl.setValue(int(float(data["keyboard_scale"])))
            if "keyboard_layout" in data:
                self.kb_layout_cb.setCurrentText(data["keyboard_layout"])
            if "keyboard_position" in data:
                self.kb_pos_cb.setCurrentText(data["keyboard_position"])
            if "keyboard_opacity" in data:
                self.kb_opacity_sl.setValue(int(data["keyboard_opacity"]))
            if "keyboard_radius" in data:
                self.kb_radius_sp.setValue(int(data["keyboard_radius"]))
            if "padding" in data:
                self.padding_sp.setValue(int(data["padding"]))
            if "wpm" in data:
                self.wpm_sp.setValue(int(data["wpm"]))
            if "typo_rate" in data:
                self.typo_sp.setValue(int(data["typo_rate"]))
            if "start_pause" in data:
                self.start_pause_sp.setValue(float(data["start_pause"]))
            if "end_pause" in data:
                self.end_pause_sp.setValue(float(data["end_pause"]))
            if "sound_profile" in data:
                self.snd_profile_cb.setCurrentText(data["sound_profile"])
            if "sound_volume" in data:
                self.snd_vol_sl.setValue(int(data["sound_volume"]))
            if "format" in data:
                self.format_cb.setCurrentText(data["format"])
            if "fps" in data:
                self.fps_sp.setValue(int(data["fps"]))
            if "crf" in data:
                self.crf_sp.setValue(int(data["crf"]))
            if "speed_ramp" in data:
                self.ramp_cb.setCurrentText(data["speed_ramp"])
            if "ramp_strength" in data:
                self.ramp_strength_sl.setValue(int(float(data["ramp_strength"])))
            if "burst_typing" in data:
                self.burst_chk.setChecked(bool(data["burst_typing"]))
            if "thinking_pauses" in data:
                self.thinking_chk.setChecked(bool(data["thinking_pauses"]))
            if "fatigue" in data:
                self.fatigue_sl.setValue(int(float(data["fatigue"])))
            if "show_stats" in data:
                self.stats_chk.setChecked(bool(data["show_stats"]))
            if "stats_position" in data:
                self.stats_pos_cb.setCurrentText(data["stats_position"])
            if "use_hw_accel" in data:
                self.hw_chk.setChecked(bool(data["use_hw_accel"]))
            if "export_srt" in data:
                self.srt_chk.setChecked(bool(data["export_srt"]))
            if "yt_title" in data:
                self.yt_title_edit.setText(data["yt_title"])
            if "yt_description" in data:
                self.yt_desc_edit.setText(data["yt_description"])
        finally:
            for _w in _widgets:
                _w.blockSignals(False)
        if "sound_profile" in data:
            self._init_sounds(data["sound_profile"]); self._static_preview()

    @staticmethod
    def _list_presets():
        """Return the names of all preset files in presets/ (without extension)."""
        if not os.path.isdir(PRESET_DIR):
            return []
        return sorted( os.path.splitext(f)[0] for f in os.listdir(PRESET_DIR) if f.endswith(".json")
        )

    def _save_preset(self):
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:")
        if not ok or not name.strip():
            return
        name = name.strip(); path = os.path.join(PRESET_DIR, f"{name}.json")
        if os.path.exists(path):
            if QMessageBox.question( self, "Overwrite?", f"Preset '{name}' exists. Overwrite?"
            ) != QMessageBox.Yes:
                return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._collect_preset(), f, indent=2); self.statusBar().showMessage(f"Preset saved: {name}")
        except Exception as e:
            QMessageBox.warning(self, "Preset Error", f"Could not save preset:\n{e}")

    def _load_preset(self):
        presets = self._list_presets()
        if not presets:
            QMessageBox.information(self, "Load Preset", "No presets found in presets/."); return
        name, ok = QInputDialog.getItem( self, "Load Preset", "Choose a preset:", presets, 0, False
        )
        if not ok or not name:
            return
        path = os.path.join(PRESET_DIR, f"{name}.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f); self._apply_preset(data); self.statusBar().showMessage(f"Preset loaded: {name}")
        except Exception as e:
            QMessageBox.warning(self, "Preset Error", f"Could not load preset:\n{e}")

    def _delete_preset(self):
        presets = self._list_presets()
        if not presets:
            QMessageBox.information(self, "Delete Preset", "No presets found in presets/."); return
        name, ok = QInputDialog.getItem( self, "Delete Preset", "Choose a preset to delete:", presets, 0, False
        )
        if not ok or not name:
            return
        if QMessageBox.question( self, "Confirm Delete", f"Delete preset '{name}'?"
        ) != QMessageBox.Yes:
            return
        path = os.path.join(PRESET_DIR, f"{name}.json")
        try:
            os.remove(path); self.statusBar().showMessage(f"Preset deleted: {name}")
        except Exception as e:
            QMessageBox.warning(self, "Preset Error", f"Could not delete preset:\n{e}")

    def _get_auto_output_path(self):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        if self._current_input_file and os.path.isfile(self._current_input_file):
            base = os.path.splitext(os.path.basename(self._current_input_file))[0]
        else:
            base = "code_typing"
        fmt = self.format_cb.currentText()
        if "WebM" in fmt:
            ext = ".webm"
        elif "GIF" in fmt:
            ext = ".gif"
        elif "YouTube Short" in fmt:
            ext = "_short.mp4"
        elif "YouTube" in fmt:
            ext = "_yt.mp4"
        else:
            ext = ".mp4"
        output_path = os.path.join(OUTPUT_DIR, f"{base}{ext}")
        if os.path.exists(output_path):
            counter = 2
            while os.path.exists(os.path.join(OUTPUT_DIR, f"{base}_{counter}{ext}")):
                counter += 1; output_path = os.path.join(OUTPUT_DIR, f"{base}_{counter}{ext}")
        return output_path

    @staticmethod
    def _vsep():
        """Return a thin vertical separator line."""
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.VLine); sep.setFrameShadow(QFrame.Shadow.Sunken); sep.setFixedWidth(1)
        return sep

    @staticmethod
    def _hsep():
        """Return a thin horizontal separator line."""
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine); sep.setFrameShadow(QFrame.Shadow.Sunken); sep.setFixedHeight(1)
        return sep

    def _build_ui(self):
        """Build the main window layout."""
        s = UI_SPACING; p = UI_PALETTE; cw = QWidget(); self.setCentralWidget(cw); root = QVBoxLayout(cw); root.setSpacing(0); root.setContentsMargins(s["lg"], s["lg"], s["lg"], 0); toolbar = QFrame()
        toolbar.setObjectName("toolbar"); tl = QHBoxLayout(toolbar); tl.setContentsMargins(0, 0, 0, 0); tl.setSpacing(s["sm"]); self.play_btn = QPushButton(">  Play"); self.play_btn.setObjectName("playBtn")
        self.play_btn.setFixedSize(110, s["control_h_lg"]); self.play_btn.clicked.connect(self._toggle_play); tl.addWidget(self.play_btn); self.snapshot_btn = QPushButton("Snapshot")
        self.snapshot_btn.clicked.connect(self._save_snapshot); tl.addWidget(self.snapshot_btn); self.batch_btn = QPushButton("Batch Render...")
        self.batch_btn.setToolTip( "Open the batch render dialog to export multiple code " "files in one go."
        )
        self.batch_btn.clicked.connect(self._open_batch_dialog); tl.addWidget(self.batch_btn); tl.addWidget(self._vsep()); tl.addStretch(); settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self._show_settings_window); tl.addWidget(settings_btn); self.cancel_btn = QPushButton("Cancel"); self.cancel_btn.setObjectName("dangerBtn")
        self.cancel_btn.clicked.connect(self._cancel_export); self.cancel_btn.setEnabled(False); tl.addWidget(self.cancel_btn); self.export_btn = QPushButton("Export Video")
        self.export_btn.setObjectName("primaryBtn"); self.export_btn.clicked.connect(self._start_export); tl.addWidget(self.export_btn); root.addWidget(toolbar); self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0); self.progress_bar.setFixedHeight(3); self.progress_bar.setTextVisible(False); self.progress_bar.setObjectName("toolbarProgress"); root.addWidget(self.progress_bar)
        self._horiz_splitter = QSplitter(Qt.Horizontal); self._horiz_splitter.setHandleWidth(1); self._horiz_splitter.setChildrenCollapsible(False); left = QWidget(); ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0); ll.setSpacing(s["sm"]); ll.addWidget(_panel_header(ICON_CODE, "CODE INPUT")); left_body = QWidget(); left_body.setObjectName("panelBody")
        el = QVBoxLayout(left_body); el.setContentsMargins(s["lg"], s["md"], s["lg"], s["lg"]); el.setSpacing(s["sm"]); file_row = QHBoxLayout(); file_row.setSpacing(s["xs"]); fl = QLabel("Filter:")
        fl.setStyleSheet(f"color: {p['text_dim']}; font-size: 12px; font-weight: 500;"); file_row.addWidget(fl); self.lang_filter_cb = QComboBox(); self.lang_filter_cb.setFixedWidth(140)
        self.lang_filter_cb.addItem("All Files", None)
        for ln in LANGUAGES:
            self.lang_filter_cb.addItem(ln, ln); self.lang_filter_cb.currentIndexChanged.connect(self._on_lang_filter_changed); file_row.addWidget(self.lang_filter_cb); il = QLabel("input/:")
        il.setStyleSheet(f"color: {p['text_dim']}; font-size: 12px; font-weight: 500;"); file_row.addWidget(il); self.input_file_cb = QComboBox()
        self.input_file_cb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed); self.input_file_cb.currentIndexChanged.connect(self._on_input_file_selected); file_row.addWidget(self.input_file_cb, 1)
        rb = QPushButton("Refresh"); rb.setFixedWidth(64); rb.clicked.connect(self._refresh_input_files); file_row.addWidget(rb); sb = QPushButton("Save"); sb.clicked.connect(self._save_to_input)
        file_row.addWidget(sb); bb = QPushButton("Open..."); bb.setFixedWidth(72); bb.clicked.connect(self._load_file); file_row.addWidget(bb); el.addLayout(file_row); sample_row = QHBoxLayout()
        sample_row.setSpacing(s["xs"]); sl2 = QLabel("Sample:"); sl2.setStyleSheet(f"color: {p['text_dim']}; font-size: 12px; font-weight: 500;"); sample_row.addWidget(sl2); self.sample_cb = QComboBox()
        self.sample_cb.setFixedWidth(200); self.sample_cb.addItem("\u2014 Load a sample \u2026", None)
        for ln in LANGUAGES:
            self.sample_cb.addItem(ln, ln); self.sample_cb.currentIndexChanged.connect(self._on_sample_selected); sample_row.addWidget(self.sample_cb); sample_row.addStretch(); el.addLayout(sample_row)
        self.editor = DropTextEdit(); self.editor.setObjectName("codeEditor"); self.editor.setFont(QFont("Consolas", 11)); self.editor.setPlainText(SAMPLE_PY); self.editor.setAcceptRichText(False)
        self.editor.files_dropped.connect(self._on_file_dropped); self.editor.textChanged.connect(self._on_code_changed); el.addWidget(self.editor, 1); ll.addWidget(left_body, 1)
        self._horiz_splitter.addWidget(left); right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(s["sm"]); rl.addWidget(_panel_header(ICON_PREVIEW, "PREVIEW"))
        right_body = QWidget(); right_body.setObjectName("panelBody"); rbl = QVBoxLayout(right_body); rbl.setContentsMargins(s["lg"], s["md"], s["lg"], s["lg"]); rbl.setSpacing(s["sm"])
        preview_frame = QFrame(); preview_frame.setObjectName("previewFrame"); pfl = QVBoxLayout(preview_frame); pfl.setContentsMargins(s["md"], s["md"], s["md"], s["md"]); pfl.setSpacing(0)
        self.preview_lbl = QLabel("Preview"); self.preview_lbl.setAlignment(Qt.AlignCenter); self.preview_lbl.setObjectName("previewPlaceholder")
        self.preview_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding); pfl.addWidget(self.preview_lbl); rbl.addWidget(preview_frame, 1); transport = QHBoxLayout()
        transport.setSpacing(s["sm"]); self.time_current_lbl = QLabel("00:00"); self.time_current_lbl.setObjectName("timeLabel"); self.time_current_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.timeline_slider = QSlider(Qt.Horizontal); self.timeline_slider.setObjectName("timelineSlider"); self.timeline_slider.setRange(0, 1000)
        self.timeline_slider.sliderMoved.connect(self._on_timeline_scrub); self.timeline_slider.sliderPressed.connect(self._on_timeline_pressed)
        self.timeline_slider.sliderReleased.connect(self._on_timeline_released); self.time_total_lbl = QLabel("00:00"); self.time_total_lbl.setObjectName("timeLabel")
        self.time_total_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter); transport.addWidget(self.time_current_lbl); transport.addWidget(self.timeline_slider, 1); transport.addWidget(self.time_total_lbl)
        rbl.addLayout(transport); rl.addWidget(right_body, 1); self._horiz_splitter.addWidget(right); self._horiz_splitter.setStretchFactor(0, 2); self._horiz_splitter.setStretchFactor(1, 3)
        self._horiz_splitter.setSizes([450, 700]); root.addWidget(self._horiz_splitter); self._status_res_lbl = QLabel("1920x1080"); self._status_res_lbl.setObjectName("statusPermanent")
        self.statusBar().addPermanentWidget(self._status_res_lbl); self._status_font_lbl = QLabel("22px"); self._status_font_lbl.setObjectName("statusPermanent")
        self.statusBar().addPermanentWidget(self._status_font_lbl); self._status_lang_lbl = QLabel("Python"); self._status_lang_lbl.setObjectName("statusPermanent")
        self.statusBar().addPermanentWidget(self._status_lang_lbl); self._status_dur_lbl = QLabel("00:00"); self._status_dur_lbl.setObjectName("statusPermanent")
        self.statusBar().addPermanentWidget(self._status_dur_lbl); self._settings_win = QDialog(self); self._settings_win.setWindowTitle("Settings"); self._settings_win.resize(560, 680)
        self._settings_win.setMinimumSize(440, 520); self._settings_win.setAttribute(Qt.WA_DeleteOnClose, False); sw_root = QVBoxLayout(self._settings_win)
        sw_root.setContentsMargins(s["lg"], s["lg"], s["lg"], s["lg"]); sw_root.setSpacing(s["md"]); sw_root.addWidget(_panel_header(ICON_SETTINGS, "SETTINGS")); self.settings_tabs = QTabWidget()
        self.settings_tabs.setDocumentMode(True)
        # ================= TAB 1: Theme ============================
        theme_tab = QWidget(); thl = QVBoxLayout(theme_tab); thl.setContentsMargins(s["md"], s["lg"], s["md"], s["lg"]); thl.setSpacing(s["sm"]); tg = _form2col(); r = 0
        tg.addWidget(QLabel("Theme:"), r, 0, Qt.AlignRight | Qt.AlignVCenter); self.theme_cb = QComboBox(); self.theme_cb.addItems(THEMES.keys())
        self.theme_cb.currentTextChanged.connect(self._on_setting_changed); tg.addWidget(self.theme_cb, r, 1); tg.addWidget(QLabel("Font:"), r, 2, Qt.AlignRight | Qt.AlignVCenter); self.font_cb = QComboBox()
        self.font_cb.setEditable(True); self.font_cb.setInsertPolicy(QComboBox.NoInsert); self._populate_font_list("All Scripts"); self.font_cb.setCurrentText("Consolas")
        self.font_cb.currentTextChanged.connect(self._on_setting_changed); tg.addWidget(self.font_cb, r, 3); r += 1; tg.addWidget(QLabel("Resolution:"), r, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.res_cb = QComboBox(); self.res_cb.addItems(RESOLUTION_PRESETS.keys()); self.res_cb.currentTextChanged.connect(self._on_resolution_changed); tg.addWidget(self.res_cb, r, 1)
        tg.addWidget(QLabel("Language:"), r, 2, Qt.AlignRight | Qt.AlignVCenter); self.lang_cb = QComboBox(); self.lang_cb.addItems(LANGUAGES)
        self.lang_cb.currentTextChanged.connect(self._on_setting_changed); tg.addWidget(self.lang_cb, r, 3); r += 1; tg.addWidget(QLabel("Font Script:"), r, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.font_script_cb = QComboBox()
        self.font_script_cb.addItems([ "All Scripts", "Latin / Western", "CJK (Chinese, Japanese, Korean)", "Arabic / Persian / Urdu", "Devanagari (Hindi, Sanskrit)", "Cyrillic (Russian, Ukrainian)", "Thai", "Hebrew", "Georgian", "Armenian", "Ethiopic", "Tibetan", "Monospace Only",
        ])
        self.font_script_cb.setCurrentText("All Scripts"); self.font_script_cb.currentTextChanged.connect(self._on_font_script_changed); tg.addWidget(self.font_script_cb, r, 1, 1, 3); r += 1
        tg.addWidget(QLabel("Background:"), r, 0, Qt.AlignRight | Qt.AlignVCenter); bg_row = QHBoxLayout(); bg_row.setSpacing(s["xs"]); self.bg_btn = QPushButton("BG Image")
        self.bg_btn.clicked.connect(self._select_bg_image); self.bg_clear_btn = QPushButton("Clear"); self.bg_clear_btn.setFixedWidth(60); self.bg_clear_btn.clicked.connect(self._clear_bg_image)
        bg_row.addWidget(self.bg_btn); bg_row.addWidget(self.bg_clear_btn); bg_row.addStretch(); tg.addLayout(bg_row, r, 1, 1, 3); thl.addLayout(tg); thl.addStretch()
        self.settings_tabs.addTab(theme_tab, "Theme")
        # ================= TAB 2: Editor ===========================
        editor_tab = QWidget(); edl = QVBoxLayout(editor_tab); edl.setContentsMargins(s["md"], s["lg"], s["md"], s["lg"]); edl.setSpacing(s["sm"]); self.autofit_chk = QCheckBox("Auto-fit Font Size")
        self.autofit_chk.setChecked(True)
        self.autofit_chk.setToolTip( "Automatically calculate the largest font size that fits " "the code in the chosen resolution. " "Uncheck to set font size manually."
        )
        self.autofit_chk.toggled.connect(self._on_autofit_toggled); edl.addWidget(self.autofit_chk); eg = _form2col(); r = 0; self._visible_lines_label = QLabel("Visible Lines:")
        eg.addWidget(self._visible_lines_label, r, 0, Qt.AlignRight | Qt.AlignVCenter); self.max_lines_sp = QSpinBox(); self.max_lines_sp.setRange(0, 200); self.max_lines_sp.setValue(0)
        self.max_lines_sp.setSpecialValueText("All")
        self.max_lines_sp.setToolTip( "0 = fit all code lines.  Set a number to show exactly " "that many lines (font scales to fill editor)."
        )
        self.max_lines_sp.valueChanged.connect(self._on_setting_changed); eg.addWidget(self.max_lines_sp, r, 1); eg.addWidget(QLabel("Font Size:"), r, 2, Qt.AlignRight | Qt.AlignVCenter)
        self.size_sp = QSpinBox(); self.size_sp.setRange(8, 72); self.size_sp.setValue(22); self.size_sp.setSuffix(" px"); self.size_sp.setSingleStep(2)
        self.size_sp.setToolTip( "Manual font size (px). Use arrow keys Up/Down.\n" "Only active when Auto-fit is unchecked."
        )
        self.size_sp.valueChanged.connect(self._on_setting_changed); self.size_sp.setEnabled(False); eg.addWidget(self.size_sp, r, 3); r += 1
        eg.addWidget(QLabel("Tab Size:"), r, 0, Qt.AlignRight | Qt.AlignVCenter); self.tab_sp = QSpinBox(); self.tab_sp.setRange(2, 8); self.tab_sp.setValue(4)
        self.tab_sp.valueChanged.connect(self._on_setting_changed); eg.addWidget(self.tab_sp, r, 1); eg.addWidget(QLabel("Padding:"), r, 2, Qt.AlignRight | Qt.AlignVCenter); self.padding_sp = QSpinBox()
        self.padding_sp.setRange(0, 100); self.padding_sp.setValue(50); self.padding_sp.setSuffix(" px"); self.padding_sp.setToolTip("Padding (px) around the code block.")
        self.padding_sp.valueChanged.connect(self._on_setting_changed); eg.addWidget(self.padding_sp, r, 3); r += 1; eg.addWidget(QLabel("Title:"), r, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.title_edit = QLineEdit("main.py \u2014 Code Editor"); self.title_edit.textChanged.connect(self._on_setting_changed); eg.addWidget(self.title_edit, r, 1, 1, 3); r += 1; chk_row = QHBoxLayout()
        chk_row.setSpacing(s["xl"]); self.ln_chk = QCheckBox("Line Numbers"); self.ln_chk.setChecked(True); self.ln_chk.toggled.connect(self._on_setting_changed); chk_row.addWidget(self.ln_chk)
        self.chrome_chk = QCheckBox("Window Chrome"); self.chrome_chk.setChecked(True); self.chrome_chk.toggled.connect(self._on_setting_changed); chk_row.addWidget(self.chrome_chk); chk_row.addStretch()
        eg.addLayout(chk_row, r, 0, 1, 4); edl.addLayout(eg); edl.addStretch(); self.settings_tabs.addTab(editor_tab, "Editor")
        # ================= TAB 3: Keyboard =========================
        kb_tab = QWidget(); kbl = QVBoxLayout(kb_tab); kbl.setContentsMargins(s["md"], s["lg"], s["md"], s["lg"]); kbl.setSpacing(s["sm"]); self.kb_chk = QCheckBox("Show Keyboard")
        self.kb_chk.toggled.connect(self._on_kb_toggled); kbl.addWidget(self.kb_chk); kbg = _form2col(); r = 0; kbg.addWidget(QLabel("Layout:"), r, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.kb_layout_cb = QComboBox(); self.kb_layout_cb.addItems(KEYBOARD_LAYOUTS.keys()); self.kb_layout_cb.setToolTip("Choose the keyboard layout shown in the overlay.")
        self.kb_layout_cb.currentTextChanged.connect(self._on_setting_changed); kbg.addWidget(self.kb_layout_cb, r, 1); kbg.addWidget(QLabel("Position:"), r, 2, Qt.AlignRight | Qt.AlignVCenter)
        self.kb_pos_cb = QComboBox(); self.kb_pos_cb.addItems(KB_POSITIONS)
        self.kb_pos_cb.setToolTip( "Below Code: keyboard under the editor (16:9).\n" "Overlay Bottom: semi-transparent over code (1:1).\n" "Right Panel: keyboard on the right (9:16 vertical)."
        )
        self.kb_pos_cb.currentTextChanged.connect(self._on_kb_pos_changed); kbg.addWidget(self.kb_pos_cb, r, 3); r += 1; kbg.addWidget(QLabel("Gap:"), r, 0, Qt.AlignRight | Qt.AlignVCenter)
        gap_row, self.kb_gap_sl, self.kb_gap_val = _slider_row( "Gap", 0, 400, 20, " px", "Spacing between code and keyboard."); self.kb_gap_sl.valueChanged.connect(self._on_setting_changed)
        kbg.addLayout(gap_row, r, 1); kbg.addWidget(QLabel("Scale:"), r, 2, Qt.AlignRight | Qt.AlignVCenter)
        scale_row, self.kb_scale_sl, self.kb_scale_val = _slider_row( "Scale", 30, 200, 100, "%", "Keyboard size. 100% = auto-scaled.")
        self.kb_scale_sl.valueChanged.connect(self._on_setting_changed); kbg.addLayout(scale_row, r, 3); r += 1; kbg.addWidget(QLabel("Opacity:"), r, 0, Qt.AlignRight | Qt.AlignVCenter)
        op_row, self.kb_opacity_sl, self.kb_opacity_val = _slider_row( "Opacity", 10, 100, 100, "%", "Keyboard opacity. 100% = solid. Lower = see-through.")
        self.kb_opacity_sl.valueChanged.connect(self._on_setting_changed); kbg.addLayout(op_row, r, 1); kbg.addWidget(QLabel("Radius:"), r, 2, Qt.AlignRight | Qt.AlignVCenter); self.kb_radius_sp = QSpinBox()
        self.kb_radius_sp.setRange(0, 20); self.kb_radius_sp.setValue(6); self.kb_radius_sp.setSuffix(" px"); self.kb_radius_sp.setToolTip("Corner radius of each key.")
        self.kb_radius_sp.valueChanged.connect(self._on_setting_changed); kbg.addWidget(self.kb_radius_sp, r, 3); kbl.addLayout(kbg); kbl.addStretch(); self.settings_tabs.addTab(kb_tab, "Keyboard")
        # ================= TAB 4: Timing ===========================
        timing_tab = QWidget(); til = QVBoxLayout(timing_tab); til.setContentsMargins(s["md"], s["lg"], s["md"], s["lg"]); til.setSpacing(s["sm"]); tig = _form2col(); r = 0
        tig.addWidget(QLabel("WPM:"), r, 0, Qt.AlignRight | Qt.AlignVCenter); self.wpm_sp = QSpinBox(); self.wpm_sp.setRange(20, 500); self.wpm_sp.setValue(100); self.wpm_sp.setSuffix(" WPM")
        self.wpm_sp.valueChanged.connect(self._on_setting_changed); tig.addWidget(self.wpm_sp, r, 1); tig.addWidget(QLabel("Typo Rate:"), r, 2, Qt.AlignRight | Qt.AlignVCenter); self.typo_sp = QSpinBox()
        self.typo_sp.setRange(0, 20); self.typo_sp.setValue(1); self.typo_sp.setSuffix("%"); self.typo_sp.setToolTip("Probability of a typo per printable character.")
        self.typo_sp.valueChanged.connect(self._on_setting_changed); tig.addWidget(self.typo_sp, r, 3); r += 1; tig.addWidget(QLabel("Start Pause:"), r, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.start_pause_sp = QDoubleSpinBox(); self.start_pause_sp.setRange(0.0, 10.0); self.start_pause_sp.setDecimals(1); self.start_pause_sp.setSingleStep(0.5); self.start_pause_sp.setValue(1.0)
        self.start_pause_sp.setSuffix(" s"); self.start_pause_sp.valueChanged.connect(self._on_setting_changed); tig.addWidget(self.start_pause_sp, r, 1)
        tig.addWidget(QLabel("End Pause:"), r, 2, Qt.AlignRight | Qt.AlignVCenter); self.end_pause_sp = QDoubleSpinBox(); self.end_pause_sp.setRange(0.0, 10.0); self.end_pause_sp.setDecimals(1)
        self.end_pause_sp.setSingleStep(0.5); self.end_pause_sp.setValue(2.0); self.end_pause_sp.setSuffix(" s"); self.end_pause_sp.valueChanged.connect(self._on_setting_changed)
        tig.addWidget(self.end_pause_sp, r, 3); r += 1; tig.addWidget(QLabel("Speed Ramp:"), r, 0, Qt.AlignRight | Qt.AlignVCenter); self.ramp_cb = QComboBox()
        self.ramp_cb.addItems(["None", "Ease In", "Ease Out", "Ease In-Out"]); self.ramp_cb.currentTextChanged.connect(self._on_setting_changed); tig.addWidget(self.ramp_cb, r, 1)
        tig.addWidget(QLabel("Ramp Str:"), r, 2, Qt.AlignRight | Qt.AlignVCenter)
        ramp_row, self.ramp_strength_sl, self.ramp_strength_val = _slider_row( "Ramp", 0, 100, 50, "%", "Strength of the speed ramp effect (0-100%).")
        self.ramp_strength_sl.valueChanged.connect(self._on_setting_changed); tig.addLayout(ramp_row, r, 3); r += 1; chk_row2 = QHBoxLayout(); chk_row2.setSpacing(s["xl"])
        self.burst_chk = QCheckBox("Burst Typing"); self.burst_chk.setChecked(True); self.burst_chk.setToolTip("Model natural typing bursts of 2-6 fast keystrokes.")
        self.burst_chk.toggled.connect(self._on_setting_changed); chk_row2.addWidget(self.burst_chk); self.thinking_chk = QCheckBox("Thinking Pauses"); self.thinking_chk.setChecked(True)
        self.thinking_chk.setToolTip("Insert occasional pauses at structural boundaries."); self.thinking_chk.toggled.connect(self._on_setting_changed); chk_row2.addWidget(self.thinking_chk)
        chk_row2.addStretch(); tig.addLayout(chk_row2, r, 0, 1, 4); r += 1; tig.addWidget(QLabel("Fatigue:"), r, 0, Qt.AlignRight | Qt.AlignVCenter)
        fatigue_row, self.fatigue_sl, self.fatigue_val = _slider_row( "Fatigue", 0, 100, 0, "%", "Gradual slowdown over the clip (0=none, 100=~40% slower by end).")
        self.fatigue_sl.valueChanged.connect(self._on_setting_changed); tig.addLayout(fatigue_row, r, 1, 1, 3); til.addLayout(tig); til.addStretch(); self.settings_tabs.addTab(timing_tab, "Timing")
        # ================= TAB 5: Overlay ==========================
        ov_tab = QWidget(); ol = QVBoxLayout(ov_tab); ol.setContentsMargins(s["md"], s["lg"], s["md"], s["lg"]); ol.setSpacing(s["sm"]); self.stats_chk = QCheckBox("Show Statistics Overlay")
        self.stats_chk.setToolTip("Display WPM, keystrokes, accuracy, and elapsed time."); self.stats_chk.toggled.connect(self._on_setting_changed); ol.addWidget(self.stats_chk); og = _form2col(); r = 0
        og.addWidget(QLabel("Stats Pos:"), r, 0, Qt.AlignRight | Qt.AlignVCenter); self.stats_pos_cb = QComboBox(); self.stats_pos_cb.addItems(list(OVERLAY_POSITIONS))
        self.stats_pos_cb.currentTextChanged.connect(self._on_setting_changed); og.addWidget(self.stats_pos_cb, r, 1, 1, 3); r += 1
        ol.addLayout(og); ol.addStretch(); self.settings_tabs.addTab(ov_tab, "Overlay")
        # ================= TAB 6: Export ===========================
        exp_tab = QWidget(); exl = QVBoxLayout(exp_tab); exl.setContentsMargins(s["md"], s["lg"], s["md"], s["lg"]); exl.setSpacing(s["sm"]); exg = _form2col(); r = 0
        exg.addWidget(QLabel("Format:"), r, 0, Qt.AlignRight | Qt.AlignVCenter); self.format_cb = QComboBox()
        self.format_cb.addItems([ "MP4 (H.264)", "WebM (VP9)", "GIF", "YouTube Video", "YouTube Short",
        ])
        self.format_cb.currentTextChanged.connect(self._on_format_changed); exg.addWidget(self.format_cb, r, 1); exg.addWidget(QLabel("FPS:"), r, 2, Qt.AlignRight | Qt.AlignVCenter); self.fps_sp = QSpinBox()
        self.fps_sp.setRange(10, 120); self.fps_sp.setValue(30); self.fps_sp.setSuffix(" fps"); self.fps_sp.valueChanged.connect(self._on_setting_changed); exg.addWidget(self.fps_sp, r, 3); r += 1
        exg.addWidget(QLabel("CRF:"), r, 0, Qt.AlignRight | Qt.AlignVCenter); self.crf_sp = QSpinBox(); self.crf_sp.setRange(0, 51); self.crf_sp.setValue(18)
        self.crf_sp.setToolTip("Constant Rate Factor (lower = better quality, larger file)."); self.crf_sp.valueChanged.connect(self._on_setting_changed); exg.addWidget(self.crf_sp, r, 1)
        exg.addWidget(QLabel("Sound:"), r, 2, Qt.AlignRight | Qt.AlignVCenter); self.snd_profile_cb = QComboBox()
        self.snd_profile_cb.addItems([ "Mechanical", "Typewriter", "Soft Membrane", "Laptop Chiclet", "Topre Electrostatic", "Custom Linear", "Cash Register", "Pinball", "Telegraph", "Arcade Button", "Gunshot", "Gunshot Silenced", "Crystal Singing Bowl", "Synth Bubble", "Tibetan Bowl",
        ])
        self.snd_profile_cb.currentTextChanged.connect(self._on_sound_profile_changed); exg.addWidget(self.snd_profile_cb, r, 3); self.snd_preview_btn = QPushButton("Preview")
        self.snd_preview_btn.setToolTip( "Play a short demo sequence of the selected sound preset."
        )
        self.snd_preview_btn.setFixedWidth(70); self.snd_preview_btn.clicked.connect(self._preview_sound_preset); exg.addWidget(self.snd_preview_btn, r + 1, 2, 1, 2, Qt.AlignRight); r += 1
        exg.addWidget(QLabel("Volume:"), r, 0, Qt.AlignRight | Qt.AlignVCenter); vol_row, self.snd_vol_sl, self.snd_vol_val = _slider_row( "Volume", 0, 100, 50, "%", "Export audio volume (0-100%).")
        self.snd_vol_sl.valueChanged.connect(self._on_setting_changed); exg.addLayout(vol_row, r, 1); r += 1; chk_row3 = QHBoxLayout(); chk_row3.setSpacing(s["xl"]); self.hw_chk = QCheckBox("GPU Encoding")
        self.hw_chk.setToolTip("Use NVENC / QSV / AMF / VideoToolbox if available."); self.hw_chk.toggled.connect(self._on_setting_changed); chk_row3.addWidget(self.hw_chk)
        self.srt_chk = QCheckBox("Export SRT"); self.srt_chk.setToolTip("Write a .srt sidecar file with one cue per typed line."); chk_row3.addWidget(self.srt_chk); chk_row3.addStretch()
        exg.addLayout(chk_row3, r, 0, 1, 4); r += 1; exg.addWidget(QLabel("YT Title:"), r, 0, Qt.AlignRight | Qt.AlignVCenter); self.yt_title_edit = QLineEdit()
        self.yt_title_edit.setPlaceholderText("Video title (embedded in MP4)"); exg.addWidget(self.yt_title_edit, r, 1, 1, 3); r += 1; exg.addWidget(QLabel("YT Desc:"), r, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.yt_desc_edit = QLineEdit(); self.yt_desc_edit.setPlaceholderText("Video description (embedded in MP4)"); exg.addWidget(self.yt_desc_edit, r, 1, 1, 3); exl.addLayout(exg); exl.addStretch()
        self.settings_tabs.addTab(exp_tab, "Export"); sw_root.addWidget(self.settings_tabs); btn_row = QHBoxLayout(); btn_row.addStretch(); self.settings_apply_btn = QPushButton("Apply")
        self.settings_apply_btn.setToolTip( "Apply the current settings and refresh the preview."
        )
        self.settings_apply_btn.clicked.connect(self._on_settings_apply); btn_row.addWidget(self.settings_apply_btn); self.settings_ok_btn = QPushButton("OK")
        self.settings_ok_btn.setObjectName("primaryBtn")
        self.settings_ok_btn.setToolTip( "Apply the current settings and close this dialog."
        )
        self.settings_ok_btn.clicked.connect(self._on_settings_ok); btn_row.addWidget(self.settings_ok_btn); self.settings_close_btn = QPushButton("Close")
        self.settings_close_btn.setToolTip( "Close this dialog. Recent changes are kept."
        )
        self.settings_close_btn.clicked.connect(self._settings_win.accept); btn_row.addWidget(self.settings_close_btn); sw_root.addLayout(btn_row)

    def _on_settings_apply(self):
        """Apply current settings (refresh the preview)."""
        self._static_preview()

    def _on_settings_ok(self):
        """Apply current settings and close the dialog."""
        self._static_preview(); self._settings_win.accept()

    def _show_settings_window(self):
        """Open the Settings dialog as a popup."""
        sw = getattr(self, '_settings_win', None)
        if sw is None:
            return
        if not sw.isVisible():
            sw.show(); sw.raise_(); sw.activateWindow()

    def _build_menu(self):
        mb = self.menuBar(); file_menu = mb.addMenu("&File"); file_menu.addAction(self._action("Open File...", self._load_file, QKeySequence.Open))
        file_menu.addAction(self._action("Save to input/", self._save_to_input, QKeySequence.Save)); file_menu.addSeparator()
        file_menu.addAction(self._action("Refresh input/", self._refresh_input_files, QKeySequence.Refresh)); file_menu.addSeparator()
        file_menu.addAction(self._action("Exit", self.close, QKeySequence.Quit)); view_menu = mb.addMenu("&View"); view_menu.addAction(self._action("Play / Pause", self._toggle_play, QKeySequence("Space")))
        view_menu.addAction(self._action("Snapshot PNG", self._save_snapshot, QKeySequence("Ctrl+Shift+S"))); view_menu.addAction(self._action("Export Video", self._start_export, QKeySequence("Ctrl+E")))
        view_menu.addAction(self._action("Cancel Export", self._cancel_export, QKeySequence("Ctrl+."))); view_menu.addSeparator()
        view_menu.addAction(self._action("Batch Render...", self._open_batch_dialog, QKeySequence("Ctrl+Shift+B")))
        view_menu.addAction(self._action("Settings...", self._show_settings_window, QKeySequence("Ctrl+,"))); preset_menu = mb.addMenu("&Presets")
        preset_menu.addAction(self._action("Save Preset As...", self._save_preset)); preset_menu.addAction(self._action("Load Preset...", self._load_preset))
        preset_menu.addAction(self._action("Delete Preset...", self._delete_preset)); help_menu = mb.addMenu("&Help"); help_menu.addAction(self._action("About", self._show_about))

    def _action(self, text: str, slot, shortcut=None):
        act = QAction(text, self); act.triggered.connect(slot)
        if shortcut is not None:
            act.setShortcut(shortcut)
        return act

    def _build_shortcuts(self):
        QShortcut(QKeySequence("F5"), self, activated=self._refresh_input_files); QShortcut(QKeySequence("Ctrl+Shift+E"), self, activated=self._start_export)

    def _restore_settings(self):
        s = self._settings
        if s.contains("theme"):
            self.theme_cb.setCurrentText(s.value("theme", "Dracula"))
        if s.contains("font"):
            idx = self._find_font_index(self.font_cb, s.value("font", "Consolas"))
            if idx >= 0:
                self.font_cb.setCurrentIndex(idx); self.autofit_chk.setChecked(s.value("autofit_font", True, type=bool)); self.max_lines_sp.setValue(int(s.value("max_lines", 0)))
        self.size_sp.setValue(int(s.value("font_size", 22))); self.tab_sp.setValue(int(s.value("tab_size", 4)))
        if s.contains("title"):
            self.title_edit.setText(s.value("title", "main.py — Code Editor")); self.ln_chk.setChecked(s.value("line_numbers", True, type=bool))
        self.chrome_chk.setChecked(s.value("window_chrome", True, type=bool))
        if s.contains("language"):
            self.lang_cb.setCurrentText(s.value("language", "Python"))
        if s.contains("resolution"):
            self.res_cb.setCurrentText(s.value("resolution", "YouTube 1080p")); self.kb_chk.setChecked(s.value("show_keyboard", False, type=bool)); self.kb_gap_sl.setValue(int(s.value("keyboard_gap", 20)))
        self.kb_scale_sl.setValue(int(s.value("keyboard_scale", 100)))
        if s.contains("keyboard_layout"):
            self.kb_layout_cb.setCurrentText(s.value("keyboard_layout", "QWERTY (US)"))
        if s.contains("keyboard_position"):
            self.kb_pos_cb.setCurrentText(s.value("keyboard_position", "Below Code")); self.kb_opacity_sl.setValue(int(s.value("keyboard_opacity", 100)))
        self.kb_radius_sp.setValue(int(s.value("keyboard_radius", 6))); self.padding_sp.setValue(int(s.value("padding", 50))); self.wpm_sp.setValue(int(s.value("wpm", 100)))
        self.typo_sp.setValue(int(s.value("typo_rate", 1))); self.start_pause_sp.setValue(float(s.value("start_pause", 1))); self.end_pause_sp.setValue(float(s.value("end_pause", 2)))
        if s.contains("sound_profile"):
            self.snd_profile_cb.setCurrentText(s.value("sound_profile", "Mechanical")); self.snd_vol_sl.setValue(int(s.value("sound_volume", 50)))
        if s.contains("format"):
            self.format_cb.setCurrentText(s.value("format", "MP4 (H.264)")); self.fps_sp.setValue(int(s.value("fps", 30))); self.crf_sp.setValue(int(s.value("crf", 18)))
        if s.contains("speed_ramp"):
            self.ramp_cb.setCurrentText(s.value("speed_ramp", "None")); self.ramp_strength_sl.setValue(int(s.value("ramp_strength", 50))); self.burst_chk.setChecked(s.value("burst_typing", True, type=bool))
        self.thinking_chk.setChecked(s.value("thinking_pauses", True, type=bool)); self.fatigue_sl.setValue(int(s.value("fatigue", 0))); self.stats_chk.setChecked(s.value("show_stats", False, type=bool))
        if s.contains("stats_position"):
            self.stats_pos_cb.setCurrentText(s.value("stats_position", "Bottom-Right"))
        self.hw_chk.setChecked(s.value("use_hw_accel", False, type=bool)); self.srt_chk.setChecked(s.value("export_srt", False, type=bool))
        if s.contains("yt_title"):
            self.yt_title_edit.setText(s.value("yt_title", ""))
        if s.contains("yt_description"):
            self.yt_desc_edit.setText(s.value("yt_description", ""))
        bg = s.value("bg_image_path", "")
        if bg and os.path.isfile(bg):
            self._bg_image_path = bg

    def _save_settings(self):
        s = self._settings; s.setValue("theme", self.theme_cb.currentText()); s.setValue("font", self._current_font_family); s.setValue("autofit_font", self.autofit_chk.isChecked())
        s.setValue("max_lines", self.max_lines_sp.value()); s.setValue("font_size", self.size_sp.value()); s.setValue("tab_size", self.tab_sp.value()); s.setValue("title", self.title_edit.text())
        s.setValue("line_numbers", self.ln_chk.isChecked()); s.setValue("window_chrome", self.chrome_chk.isChecked()); s.setValue("language", self.lang_cb.currentText())
        s.setValue("resolution", self.res_cb.currentText()); s.setValue("show_keyboard", self.kb_chk.isChecked()); s.setValue("keyboard_gap", self.kb_gap_sl.value())
        s.setValue("keyboard_scale", self.kb_scale_sl.value()); s.setValue("keyboard_layout", self.kb_layout_cb.currentText()); s.setValue("keyboard_position", self.kb_pos_cb.currentText())
        s.setValue("keyboard_opacity", self.kb_opacity_sl.value()); s.setValue("keyboard_radius", self.kb_radius_sp.value()); s.setValue("padding", self.padding_sp.value())
        s.setValue("wpm", self.wpm_sp.value()); s.setValue("typo_rate", self.typo_sp.value()); s.setValue("start_pause", self.start_pause_sp.value()); s.setValue("end_pause", self.end_pause_sp.value())
        s.setValue("sound_profile", self.snd_profile_cb.currentText()); s.setValue("sound_volume", self.snd_vol_sl.value()); s.setValue("format", self.format_cb.currentText())
        s.setValue("fps", self.fps_sp.value()); s.setValue("crf", self.crf_sp.value()); s.setValue("speed_ramp", self.ramp_cb.currentText()); s.setValue("ramp_strength", self.ramp_strength_sl.value())
        s.setValue("burst_typing", self.burst_chk.isChecked()); s.setValue("thinking_pauses", self.thinking_chk.isChecked()); s.setValue("fatigue", self.fatigue_sl.value())
        s.setValue("show_stats", self.stats_chk.isChecked()); s.setValue("stats_position", self.stats_pos_cb.currentText()); s.setValue("use_hw_accel", self.hw_chk.isChecked())
        s.setValue("export_srt", self.srt_chk.isChecked()); s.setValue("yt_title", self.yt_title_edit.text()); s.setValue("yt_description", self.yt_desc_edit.text())
        s.setValue("bg_image_path", self._bg_image_path or "")

    def closeEvent(self, event):  # noqa: N802 (Qt override)
        """Save settings and close both windows when the main window closes."""
        self._preview_timer.stop(); self._code_debounce.stop()
        if self.is_playing:
            self.is_playing = False
        self._save_settings(); sw = getattr(self, '_settings_win', None)
        if sw is not None:
            sw.close()
        super().closeEvent(event)

    _WS_NAME_MAP: dict[str, list[str]] = { "Latin / Western": ["Latin", "Greek", "Cyrillic"], "CJK (Chinese, Japanese, Korean)": [ "SimplifiedChinese", "TraditionalChinese", "Japanese", "Korean", ], "Arabic / Persian / Urdu": ["Arabic"], "Devanagari (Hindi, Sanskrit)": ["Devanagari"], "Cyrillic (Russian, Ukrainian)": ["Cyrillic"], "Thai": ["Thai"], "Hebrew": ["Hebrew"], "Georgian": ["Georgian"], "Armenian": ["Armenian"], "Ethiopic": ["Ethiopic", "Geez"], "Tibetan": ["Tibetan"],
    }

    _TAG_LABELS: dict[str, str] = { "CJK (Chinese, Japanese, Korean)": "CJK", "Arabic / Persian / Urdu": "Arabic", "Devanagari (Hindi, Sanskrit)": "Devanagari", "Thai": "Thai", "Hebrew": "Hebrew", "Georgian": "Georgian", "Armenian": "Armenian", "Ethiopic": "Ethiopic", "Tibetan": "Tibetan",
    }

    _ws_cache: dict[str, set] = {}
    _script_ws_int_cache: dict[str, list[int]] = {}

    @staticmethod
    def _ws_for(label):
        if label in MainWindow._script_ws_int_cache:
            return MainWindow._script_ws_int_cache[label]
        names = MainWindow._WS_NAME_MAP.get(label, []); result = []
        for name in names:
            val = getattr(QFontDatabase.WritingSystem, name, None)
            if val is not None:
                result.append(val.value)
        MainWindow._script_ws_int_cache[label] = result
        return result

    @staticmethod
    def _build_ws_cache(families: list):
        fd = QFontDatabase(); MainWindow._ws_cache.clear()
        for f in families:
            ws_list = fd.writingSystems(f); MainWindow._ws_cache[f] = set(ws.value if isinstance(ws, QFontDatabase.WritingSystem) else int(ws) for ws in ws_list)

    @staticmethod
    def _font_supports_script(family: str, script_label):
        if script_label == "Monospace Only":
            fd = QFontDatabase()
            return fd.isFixedPitch(family)
        if script_label == "All Scripts":
            return True
        ws_set = MainWindow._ws_cache.get(family, set()); needed = MainWindow._ws_for(script_label)
        if not needed:
            return True
        return any(s in ws_set for s in needed)

    @staticmethod
    def _get_font_script_tags(family):
        """Return a short tag string like 'CJK, Thai' for fonts that."""
        ws_set = MainWindow._ws_cache.get(family, set()); tags = []
        for label, short in MainWindow._TAG_LABELS.items():
            needed = MainWindow._ws_for(label)
            if any(s in ws_set for s in needed):
                tags.append(short)
        return ", ".join(tags) if tags else ""

    @staticmethod
    def _find_font_index(combo: QComboBox, family):
        """Find the combo index for *family*, tolerating the."""
        idx = combo.findText(family)
        if idx >= 0:
            return idx
        for i in range(combo.count()):
            text = combo.itemText(i); base = text.split("  [")[0].strip() if "  [" in text else text
            if base == family:
                return i
        return -1

    @property
    def _current_font_family(self):
        """Return the selected font family name, stripped of any."""
        text = self.font_cb.currentText(); idx = text.rfind("  [")
        if idx > 0 and text.endswith("]"):
            return text[:idx]
        return text

    def _populate_font_list(self, script_filter):
        """Populate the font combo box filtered by *script_filter*."""
        fd = QFontDatabase(); families = fd.families(); current_font = self.font_cb.currentText()
        mono_families = set()
        matched = []
        if len(MainWindow._ws_cache) != len(families):
            MainWindow._build_ws_cache(families)
        if script_filter == "Monospace Only":
            for f in families:
                if fd.isFixedPitch(f):
                    mono_families.add(f)
        for f in families:
            if script_filter == "Monospace Only":
                if f not in mono_families:
                    continue
            elif script_filter != "All Scripts":
                if not self._font_supports_script(f, script_filter):
                    continue
            tags = self._get_font_script_tags(f)
            if tags:
                label = f"{f}  [{tags}]"
            else:
                label = f
            matched.append((f, label))
        priority = ( "Consolas", "JetBrains Mono", "Cascadia Code", "Fira Code", "Source Code Pro", "IBM Plex Mono", "Inconsolata", "Hack", "Space Mono", "mononoki", "SF Mono", "Menlo", "DejaVu Sans Mono", "Liberation Mono", "Sarasa Mono SC", "Sarasa Mono J", "Sarasa Mono K", "LXGW WenKai Mono", "Noto Sans Mono CJK SC", "Noto Sans Mono CJK JP", "Noto Sans Mono CJK KR", "WenQuanYi Zen Hei Mono",
        )
        priority_index = {name: i for i, name in enumerate(priority)}
        def sort_key(item):
            family, _label = item; base = family.split(",")[0].strip()
            if base in priority_index:
                return (0, priority_index[base], base.lower())
            return (1, 0, base.lower())
        matched.sort(key=sort_key); self.font_cb.blockSignals(True); self.font_cb.clear()
        for _family, label in matched:
            self.font_cb.addItem(label)
        idx = self._find_font_index(self.font_cb, current_font)
        if idx < 0:
            idx = self._find_font_index(self.font_cb, "Consolas")
        if idx >= 0:
            self.font_cb.setCurrentIndex(idx); self.font_cb.blockSignals(False)

    def _on_font_script_changed(self, script_filter):
        """Re-populate font list when the script filter changes."""
        self._populate_font_list(script_filter); self._on_setting_changed()

    def _on_autofit_toggled(self, checked):
        self.size_sp.setEnabled(not checked); self._visible_lines_label.setVisible(checked); self.max_lines_sp.setVisible(checked)
        if not checked:
            self.size_sp.setFocus(Qt.FocusReason.OtherFocusReason); self.size_sp.selectAll(); self._static_preview()

    def _on_kb_pos_changed(self, pos):
        """Auto-set opacity hint when switching to Overlay mode."""
        if pos == "Overlay Bottom" and self.kb_opacity_sl.value() == 100:
            self.kb_opacity_sl.setValue(50); self._on_setting_changed()

    def _on_kb_toggled(self, checked):
        self._on_setting_changed()

    def _on_resolution_changed(self, res_name):
        self._apply_kb_defaults_for_resolution(res_name); self._on_setting_changed()

    def _apply_kb_defaults_for_resolution(self, res_name):
        """Apply smart keyboard defaults when the resolution changes."""
        defaults = KB_DEFAULTS.get(res_name)
        if not defaults:
            return
        self.kb_pos_cb.setCurrentText(defaults["position"]); self.kb_scale_sl.setValue(int(defaults["scale"])); self.kb_gap_sl.setValue(int(defaults["gap"]))

    def _on_setting_changed(self):
        self._static_preview()

    def _on_format_changed(self):
        """Handle format-dropdown changes (e.g. switching to YouTube Short)."""
        fmt = self.format_cb.currentText()
        if fmt == "YouTube Short":
            current_res = self.res_cb.currentText()
            if current_res not in ("YouTube Short (9:16)", "TikTok / Reels"):
                idx = self.res_cb.findText("YouTube Short (9:16)")
                if idx >= 0:
                    self.res_cb.setCurrentIndex(idx); self._check_youtube_duration(); self._static_preview()

    def _on_sound_profile_changed(self, profile):
        """Re-initialise sound effects when the profile changes."""
        self._init_sounds(profile); self._on_setting_changed()

    def _preview_sound_preset(self):
        """Play a short demo sequence of the currently selected sound preset."""
        if not hasattr(self, "_preview_sfx") or self._preview_sfx is None:
            self._preview_sfx = None; self._preview_tmp = None
        if self._preview_sfx is not None:
            self._preview_sfx.stop(); self._preview_sfx.deleteLater(); self._preview_sfx = None
        if self._preview_tmp is not None:
            try:
                os.remove(self._preview_tmp)
            except OSError:
                pass
            self._preview_tmp = None
        gen = self.sound_gen; volume = self.snd_vol_sl.value() / 100.0; sr = gen.sample_rate; gap_samples = int(sr * 0.12)  # 120 ms gap between sounds
        gap = np.zeros(gap_samples, dtype=np.float64); categories = list(gen.sounds.keys())
        if not categories:
            return
        is_keyboard = not gen._CATEGORY_MAPS.get(gen.profile, {})
        if is_keyboard:
            demo_order = ["key", "key", "space", "key", "key", "enter"]; demo_order = [c for c in demo_order if c in gen.sounds]
            if not demo_order:
                demo_order = categories[:6]
        else:
            demo_order = categories[:6]
        parts: list[np.ndarray] = []
        for cat in demo_order:
            variants = gen.sounds.get(cat, [])
            if not variants:
                continue
            snd = variants[0].astype(np.float64); parts.append(snd); parts.append(gap)
        if not parts:
            return
        demo_signal = np.concatenate(parts); peak = np.max(np.abs(demo_signal))
        if peak > 0:
            demo_signal = demo_signal / peak * 0.6; tmp_path = os.path.join(TMP_DIR, "_snd_preview.wav"); gen.save_wav(tmp_path, demo_signal.astype(np.float64), sr=sr, volume=volume, channels=1)
        sfx = QSoundEffect(self); sfx.setSource(QUrl.fromLocalFile(os.path.abspath(tmp_path))); sfx.setVolume(0.9); sfx.play(); self._preview_sfx = sfx; self._preview_tmp = tmp_path
        QTimer.singleShot(int(len(demo_signal) / sr * 1000) + 2000, self._cleanup_preview_sfx)

    def _cleanup_preview_sfx(self):
        """Delete the one-shot preview QSoundEffect and its temp file."""
        if self._preview_sfx is not None:
            self._preview_sfx.stop(); self._preview_sfx.deleteLater(); self._preview_sfx = None
        if self._preview_tmp is not None:
            try:
                os.remove(self._preview_tmp)
            except OSError:
                pass
            self._preview_tmp = None

    def _check_youtube_duration(self):
        """Emit a status-bar warning if a YouTube Short would exceed 60s."""
        fmt = self.format_cb.currentText()
        if fmt != "YouTube Short":
            return
        if not self.animator:
            return
        dur = self.animator.duration()
        if dur > YOUTUBE_SHORT_MAX_DURATION:
            self.statusBar().showMessage( f"YouTube Short: source is {dur:.1f}s — will be truncated to " f"{YOUTUBE_SHORT_MAX_DURATION:.0f}s on export.", 8000,
            )
        else:
            self.statusBar().showMessage( f"YouTube Short: {dur:.1f}s (within 60s limit).", 5000,
            )

    def _on_code_changed(self):
        self._code_debounce.start()

    def _load_sample(self, sample):
        self.editor.setPlainText(sample); self._current_input_file = None

    def _static_preview(self):
        code = self.editor.toPlainText()
        if not code.strip():
            self.animator = None; self.renderer = None; self._preview_scratch = None  # PERF (v1.7): free ~8 MB when not needed
            self.timeline_slider.setValue(0); self._update_time_labels(0.0, 0.0); return
        res_name = self.res_cb.currentText(); w, h = RESOLUTION_PRESETS.get(res_name, (1920, 1080))
        if self.autofit_chk.isChecked():
            code_lines = code.count("\n") + 1; target = self.max_lines_sp.value() or None
            font_size = CodeRenderer.auto_font_size( code_lines=code_lines, width=w, height=h, padding=self.padding_sp.value(), show_window_chrome=self.chrome_chk.isChecked(), show_line_numbers=self.ln_chk.isChecked(), show_keyboard=self.kb_chk.isChecked(), tab_size=self.tab_sp.value(), target_lines=target, keyboard_position=self.kb_pos_cb.currentText(), keyboard_scale=self.kb_scale_sl.value() / 100.0, keyboard_gap=self.kb_gap_sl.value(), code=code,
            )
            self.size_sp.blockSignals(True); self.size_sp.setValue(font_size); self.size_sp.blockSignals(False)
        else:
            font_size = self.size_sp.value()
        self.renderer = CodeRenderer( width=w, height=h, theme_name=self.theme_cb.currentText(), font_family=self._current_font_family, font_size=font_size, show_line_numbers=self.ln_chk.isChecked(), show_window_chrome=self.chrome_chk.isChecked(), padding=self.padding_sp.value(), tab_size=self.tab_sp.value(), title_text=self.title_edit.text(), language=self.lang_cb.currentText(), show_keyboard=self.kb_chk.isChecked(), keyboard_gap=self.kb_gap_sl.value(), keyboard_scale=self.kb_scale_sl.value() / 100.0, keyboard_layout=self.kb_layout_cb.currentText(), keyboard_position=self.kb_pos_cb.currentText(), keyboard_opacity=self.kb_opacity_sl.value() / 100.0, keyboard_radius=self.kb_radius_sp.value(), show_stats=self.stats_chk.isChecked(), stats_position=self.stats_pos_cb.currentText(),
        ); self._preview_scratch = None
        if self._bg_image_path:
            self.renderer.set_background_image(self._bg_image_path)
        self.animator = TypingAnimator( code, base_wpm=self.wpm_sp.value(), humanize=True, typo_rate=self.typo_sp.value() / 100.0, start_pause=self.start_pause_sp.value(), end_pause=self.end_pause_sp.value(), speed_ramp=self.ramp_cb.currentText(), ramp_strength=self.ramp_strength_sl.value() / 100.0, burst_typing=self.burst_chk.isChecked(), thinking_pauses=self.thinking_chk.isChecked(), fatigue=self.fatigue_sl.value() / 100.0,
        ); self.renderer.animator_ref = self.animator
        self.renderer.current_time = self.animator.duration()
        qimg = self.renderer.render_frame( self.animator.display_chars, len(self.animator.display_chars), False
        )
        self._show_preview(qimg); self._play_offset = 0; self.timeline_slider.setValue(0); self._update_time_labels(0.0, self.animator.duration()); w, h = RESOLUTION_PRESETS.get(res_name, (1920, 1080))
        self._status_res_lbl.setText(f"{w}x{h}")
        # hack with a proper if/else so the intent is obvious.
        line_h = self.renderer.line_h
        if line_h > 0:
            avail_h = (self.renderer.height - 2 * self.renderer.padding - self.renderer.title_bar_h); visible_lines = avail_h // line_h; lines_str = str(visible_lines) if visible_lines > 0 else "?"
        else:
            lines_str = "?"
        self._status_font_lbl.setText(f"{font_size}px · {lines_str} lines"); self._status_lang_lbl.setText(self.lang_cb.currentText())
        self._status_dur_lbl.setText(self._format_time(self.animator.duration()))

    @staticmethod
    def _format_time(seconds):
        """Format seconds as M:SS (or H:MM:SS for long clips)."""
        if seconds < 0:
            seconds = 0.0
        total = int(seconds)
        if total >= 3600:
            h, rem = divmod(total, 3600); m, s = divmod(rem, 60)
            return f"{h:d}:{m:02d}:{s:02d}"
        m, s = divmod(total, 60)
        return f"{m:d}:{s:02d}"

    def _update_time_labels(self, current: float, total):
        """Update the transport-bar time labels."""
        self.time_current_lbl.setText(self._format_time(current)); self.time_total_lbl.setText(self._format_time(total))

    def _show_preview(self, qimg):
        pixmap = QPixmap.fromImage(qimg); self.preview_lbl.setObjectName("")  # remove placeholder styling once we have content
        self.preview_lbl.setStyleSheet("")
        self.preview_lbl.setPixmap( pixmap.scaled( self.preview_lbl.size(), Qt.KeepAspectRatio, Qt.FastTransformation, )
        )

    def _toggle_play(self):
        if self.is_playing:
            self._pause()
        else:
            self._play()

    def _play(self):
        if not self.animator or not self.renderer:
            return
        self.is_playing = True; self._play_t0 = _time.time(); self._last_vis = 0; self._preview_timer.start(); self.play_btn.setText("||  Pause")

    def _pause(self):
        self.is_playing = False; self._preview_timer.stop(); self._play_offset += _time.time() - self._play_t0; self.play_btn.setText(">  Play")

    def _tick(self):
        if not self.animator or not self.renderer:
            return
        elapsed = _time.time() - self._play_t0 + self._play_offset; duration = self.animator.duration()
        if not self._scrubbing:
            pct = min(1.0, elapsed / duration); self.timeline_slider.blockSignals(True); self.timeline_slider.setValue(int(pct * 1000)); self.timeline_slider.blockSignals(False)
            self._update_time_labels(elapsed, duration)
        if elapsed >= duration:
            self._pause(); return
        nv = self.animator.visible_at(elapsed)
        if nv != self._last_vis:
            self._last_vis = nv; qimg = self._render_at(elapsed, nv=nv); self._show_preview(qimg)
            if nv > 0:
                self._play_click(self.animator.display_chars[nv - 1])

    def _render_at(self, t: float, nv=None):
        if not self.animator or not self.renderer:
            return None
        if nv is None:
            nv = self.animator.visible_at(t)
        cur_vis = True; idx = bisect.bisect_right(self.animator._timestamps, t); last_ts = 0.0; since = 0.0
        if idx > 0:
            last_ts = self.animator.timeline[idx - 1][0]; since = t - last_ts
        if since > 0.25:
            cur_vis = (int(since / 0.53) % 2) == 0; pressed_key = None
        if nv > 0:
            last_ch = self.animator.display_chars[nv - 1]
            if since < 0.1:
                if last_ch == "\n":
                    pressed_key = "enter"
                elif last_ch == " ":
                    pressed_key = "space"
                elif last_ch == "\b":
                    pressed_key = "backspace"
                elif last_ch != "\t":
                    pressed_key = last_ch.lower()
            self.renderer.pressed_key = pressed_key; self.renderer.current_time = t; w, h = self.renderer.width, self.renderer.height; scratch = self._preview_scratch
        else:
            w, h = self.renderer.width, self.renderer.height; scratch = self._preview_scratch
        if scratch is None or scratch.width() != w or scratch.height() != h:
            self._preview_scratch = QImage(w, h, QImage.Format_RGB32); scratch = self._preview_scratch
        return self.renderer.render_frame(self.animator.display_chars, nv, cur_vis, target=scratch)

    def _on_timeline_scrub(self, value):
        self._scrubbing = True
        if not self.animator:
            return
        duration = self.animator.duration(); t = (value / 1000.0) * duration; qimg = self._render_at(t)
        if qimg is not None:
            self._show_preview(qimg); self._update_time_labels(t, duration)

    def _on_timeline_pressed(self):
        self._scrubbing = True
        if self.is_playing:
            self._pause()

    def _on_timeline_released(self):
        self._scrubbing = False
        if not self.animator:
            return
        self._play_offset = (self.timeline_slider.value() / 1000.0) * self.animator.duration(); self._play_t0 = _time.time(); self._last_vis = -1  # force refresh on next tick

    def _start_export(self):
        if not self.animator or not self.renderer:
            return
        if self.is_playing:
            self._pause()
        if self.exporter is not None and self.exporter.isRunning():
            self.exporter.cancel(); self.exporter.wait(10000)
        output = self._get_auto_output_path(); subtitle_path: Optional[str] = None
        if self.srt_chk.isChecked() and "GIF" not in self.format_cb.currentText():
            base, _ = os.path.splitext(output); subtitle_path = base + ".srt"
        self.exporter = VideoExporter( self.editor.toPlainText(), output, self.renderer, self.animator, fps=self.fps_sp.value(), sound_gen=self.sound_gen, volume=self.snd_vol_sl.value() / 100.0, codec_profile=self.format_cb.currentText(), crf=self.crf_sp.value(), subtitle_path=subtitle_path, use_hw_accel=self.hw_chk.isChecked(), metadata_title=self.yt_title_edit.text(), metadata_description=self.yt_desc_edit.text(),
        )
        self.exporter.progress.connect(self.progress_bar.setValue); self.exporter.status.connect(self.statusBar().showMessage); self.exporter.finished_ok.connect(self._on_export_done)
        self.exporter.error.connect(self._on_export_error); self.exporter.start(); self.export_btn.setEnabled(False); self.cancel_btn.setEnabled(True)

    def _cancel_export(self):
        if self.exporter:
            self.exporter.cancel()

    def _on_export_done(self, path):
        self.statusBar().showMessage(f"Exported: {path}"); self.export_btn.setEnabled(True); self.cancel_btn.setEnabled(False); QMessageBox.information(self, "Export Complete", f"Video saved to:\n{path}")

    def _on_export_error(self, msg):
        self.export_btn.setEnabled(True); self.cancel_btn.setEnabled(False); QMessageBox.critical(self, "Export Error", msg)

    def _capture_batch_settings(self):
        """Snapshot the current UI settings into a BatchSettings instance."""
        return BatchSettings( theme_name=self.theme_cb.currentText(), font_family=self._current_font_family, font_size=self.size_sp.value(), autofit=self.autofit_chk.isChecked(), max_lines=self.max_lines_sp.value(), tab_size=self.tab_sp.value(), padding=self.padding_sp.value(), title_text=self.title_edit.text(), show_line_numbers=self.ln_chk.isChecked(), show_window_chrome=self.chrome_chk.isChecked(), language=self.lang_cb.currentText(), show_keyboard=self.kb_chk.isChecked(), keyboard_gap=self.kb_gap_sl.value(), keyboard_scale=self.kb_scale_sl.value() / 100.0, keyboard_layout=self.kb_layout_cb.currentText(), keyboard_position=self.kb_pos_cb.currentText(), keyboard_opacity=self.kb_opacity_sl.value() / 100.0, keyboard_radius=self.kb_radius_sp.value(), show_stats=self.stats_chk.isChecked(), stats_position=self.stats_pos_cb.currentText(), bg_image=self._bg_image_path, resolution=self.res_cb.currentText(), wpm=self.wpm_sp.value(), typo_rate=self.typo_sp.value() / 100.0, start_pause=self.start_pause_sp.value(), end_pause=self.end_pause_sp.value(), speed_ramp=self.ramp_cb.currentText(), ramp_strength=self.ramp_strength_sl.value() / 100.0, burst_typing=self.burst_chk.isChecked(), thinking_pauses=self.thinking_chk.isChecked(), fatigue=self.fatigue_sl.value() / 100.0, fps=self.fps_sp.value(), crf=self.crf_sp.value(), preset="medium", codec_profile=self.format_cb.currentText(), sound_profile=self.snd_profile_cb.currentText(), sound_volume=self.snd_vol_sl.value() / 100.0, use_hw_accel=self.hw_chk.isChecked(), export_srt=self.srt_chk.isChecked(), metadata_title=self.yt_title_edit.text(), metadata_description=self.yt_desc_edit.text(),
        )
    
    def _open_batch_dialog(self):
        """Open the batch render dialog using the BatchDialog class."""
        settings = self._capture_batch_settings(); items: List[BatchItem] = []; dlg = BatchDialog(items, settings, parent=self); dlg.set_current_editor_code(self.editor.toPlainText()); dlg.exec()

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName( self, "Open Code File", "", f"Code Files (*{' '.join(SUPPORTED_EXTENSIONS)})",
        )
        if path:
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    self.editor.setPlainText(f.read()); self._current_input_file = path; self.title_edit.setText(f"{os.path.basename(path)} \u2014 Code Editor"); self._auto_detect_language(path)
            except Exception as e:
                QMessageBox.warning(self, "Error", str(e))

    def _show_about(self):
        QMessageBox.about( self, "About Code Typing Video Generator", "<h3>Code Typing Video Generator</h3>" "<p>Generate MP4/WebM/GIF videos of code being typed with realistic " "animation and procedural sound effects.</p>" "<p><b>Features:</b> syntax highlighting (Python/JS/TS/C/C++/Java/Go/Rust), " "8 themes, live stats overlay (WPM/keystrokes/accuracy), " "speed ramp, burst typing, thinking pauses, fatigue, " "context-aware QWERTY typos, 15 sound profiles (Mechanical / Typewriter / " "Soft Membrane / Laptop Chiclet / Topre / Custom Linear / " "Cash Register / Pinball / Telegraph / Arcade / Gunshot / " "Silenced / Crystal Bowl / Synth Bubble / Tibetan Bowl) " "YouTube Video & YouTube Short export modes with YouTube-recommended " "H.264 bitrates/levels + 60s Shorts cap + embedded metadata, " "hardware-accelerated encoding (NVENC/QSV/AMF/VT), SRT subtitle export, " "PNG snapshots, named presets, <b>batch rendering</b> " "(queue multiple files / inline snippets and export them all in one go).</p>" "<p><b>Shortcuts:</b> Space = play/pause, Ctrl+E = export, " "Ctrl+Shift+S = snapshot, Ctrl+Shift+B = batch render, " "Ctrl+, = settings, Ctrl+. = cancel, F5 = refresh input/.</p>",
        )

_STATUS_ICONS = {
    "Pending":   "\u25cb",   # ○ (white circle)
    "Rendering": "\u25b6",   # ▶ (right-pointing triangle)
    "Done":      "\u2713",   # ✓ (check mark)
    "Failed":    "\u2717",   # ✗ (ballot X)
    "Skipped":   "\u2212",   # − (minus sign)
}

_STATUS_COLORS = {
    "Pending":   UI_PALETTE["text_dim"],
    "Rendering": UI_PALETTE["accent"],
    "Done":      UI_PALETTE["success"],
    "Failed":    UI_PALETTE["danger"],
    "Skipped":   UI_PALETTE["text_dim"],
}

class BatchDialog(QDialog):
    """Dialog for managing and running a batch render queue."""

    _COL_STATUS = 0
    _COL_NAME = 1
    _COL_TYPE = 2
    _COL_DETAILS = 3

    def __init__( self, items: List[BatchItem], settings: BatchSettings, parent=None,
    ) -> None:
        super().__init__(parent); self.setWindowTitle("Batch Render"); self.setMinimumSize(720, 520); self.resize(800, 600); self._items = items; self._settings = settings
        self._exporter: Optional[BatchExporter] = None; self._is_running = False; self._build_ui(); self._refresh_table(); self._update_button_states()

    def _build_ui(self):
        s = UI_SPACING; root = QVBoxLayout(self); root.setContentsMargins(s["lg"], s["lg"], s["lg"], s["lg"]); root.setSpacing(s["md"]); summary = self._settings_summary(); summary_lbl = QLabel(summary)
        summary_lbl.setStyleSheet( f"color: {UI_PALETTE['text_dim']}; font-size: 12px; " f"padding: {s['sm']}px {s['md']}px; " f"background-color: {UI_PALETTE['bg_panel']}; " f"border-radius: {s['radius']}px;"
        )
        summary_lbl.setWordWrap(True); root.addWidget(summary_lbl); queue_header = QHBoxLayout(); queue_header.setSpacing(s["sm"]); lbl = QLabel("Queue:")
        lbl.setStyleSheet( f"color: {UI_PALETTE['text']}; font-weight: 600; font-size: 13px;"
        )
        queue_header.addWidget(lbl); queue_header.addStretch(); self.add_files_btn = QPushButton("Add Files..."); self.add_files_btn.clicked.connect(self._add_files)
        queue_header.addWidget(self.add_files_btn); self.add_current_btn = QPushButton("Add Current Editor")
        self.add_current_btn.setToolTip( "Add the current editor content as an inline snippet."
        )
        self.add_current_btn.clicked.connect(self._add_current_editor); queue_header.addWidget(self.add_current_btn); self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self._remove_selected); queue_header.addWidget(self.remove_btn); self.clear_btn = QPushButton("Clear All"); self.clear_btn.clicked.connect(self._clear_all)
        queue_header.addWidget(self.clear_btn); root.addLayout(queue_header); reorder_row = QHBoxLayout(); reorder_row.setSpacing(s["sm"]); reorder_row.addStretch(); self.up_btn = QPushButton("Move Up")
        self.up_btn.setFixedWidth(90); self.up_btn.clicked.connect(lambda: self._move_selected(-1)); reorder_row.addWidget(self.up_btn); self.down_btn = QPushButton("Move Down")
        self.down_btn.setFixedWidth(90); self.down_btn.clicked.connect(lambda: self._move_selected(1)); reorder_row.addWidget(self.down_btn); root.addLayout(reorder_row); self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels( ["Status", "Name", "Type", "Details"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows); self.table.setSelectionMode(QAbstractItemView.ExtendedSelection); self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True); self.table.verticalHeader().setVisible(False); hdr = self.table.horizontalHeader(); hdr.setSectionResizeMode(self._COL_STATUS, QHeaderView.Fixed)
        hdr.resizeSection(self._COL_STATUS, 60); hdr.setSectionResizeMode(self._COL_NAME, QHeaderView.Stretch); hdr.setSectionResizeMode(self._COL_TYPE, QHeaderView.Fixed)
        hdr.resizeSection(self._COL_TYPE, 80); hdr.setSectionResizeMode(self._COL_DETAILS, QHeaderView.Stretch); self.table.itemSelectionChanged.connect(self._update_button_states)
        root.addWidget(self.table, 1); prog_box = QVBoxLayout(); prog_box.setSpacing(s["xs"]); overall_row = QHBoxLayout(); overall_lbl = QLabel("Overall:"); overall_lbl.setFixedWidth(60)
        overall_row.addWidget(overall_lbl); self.overall_bar = QProgressBar(); self.overall_bar.setValue(0); overall_row.addWidget(self.overall_bar, 1); self.overall_count_lbl = QLabel("0 / 0")
        self.overall_count_lbl.setFixedWidth(60); self.overall_count_lbl.setAlignment(Qt.AlignCenter); overall_row.addWidget(self.overall_count_lbl); prog_box.addLayout(overall_row); item_row = QHBoxLayout()
        item_lbl = QLabel("Item:"); item_lbl.setFixedWidth(60); item_row.addWidget(item_lbl); self.item_bar = QProgressBar(); self.item_bar.setValue(0); item_row.addWidget(self.item_bar, 1)
        self.item_pct_lbl = QLabel(""); self.item_pct_lbl.setFixedWidth(60); self.item_pct_lbl.setAlignment(Qt.AlignCenter); item_row.addWidget(self.item_pct_lbl); prog_box.addLayout(item_row)
        self.status_lbl = QLabel("Ready.")
        self.status_lbl.setStyleSheet( f"color: {UI_PALETTE['text_dim']}; font-size: 12px;"
        )
        prog_box.addWidget(self.status_lbl); root.addLayout(prog_box); btn_row = QHBoxLayout(); btn_row.addStretch(); self.start_btn = QPushButton("Start Batch"); self.start_btn.setObjectName("primaryBtn")
        self.start_btn.clicked.connect(self._start_batch); btn_row.addWidget(self.start_btn); self.cancel_btn = QPushButton("Cancel Batch"); self.cancel_btn.setObjectName("dangerBtn")
        self.cancel_btn.setEnabled(False); self.cancel_btn.clicked.connect(self._cancel_batch); btn_row.addWidget(self.cancel_btn); self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self._on_close); btn_row.addWidget(self.close_btn); root.addLayout(btn_row)

    def _settings_summary(self):
        """Build a one-paragraph summary of the captured settings."""
        s = self._settings
        parts = [ f"Resolution: {s.resolution}", f"Format: {s.codec_profile}", f"Theme: {s.theme_name}", f"WPM: {s.wpm}", f"Sound: {s.sound_profile}", f"FPS: {s.fps}",
        ]
        if s.show_keyboard:
            parts.append(f"Keyboard: {s.keyboard_layout}")
        if s.show_stats:
            parts.append("Stats overlay")
        return "  |  ".join(parts)

    def _add_files(self):
        """Open a multi-select file dialog and add chosen files."""
        ext_str = " ".join(SUPPORTED_EXTENSIONS)
        paths, _ = QFileDialog.getOpenFileNames( self, "Select Code Files for Batch", "", f"Code Files (*{ext_str});;All Files (*)",
        )
        if not paths:
            return
        added = 0
        for p in paths:
            if any(it.file_path == p for it in self._items):
                continue
            self._items.append(BatchItem(file_path=p)); added += 1; self._refresh_table(); self._update_button_states()
        if added:
            self.status_lbl.setText( f"Added {added} file(s). Queue has {len(self._items)} item(s)."
            )

    def _add_current_editor(self):
        """Add the main window's current editor content as inline code."""
        code = getattr(self, "_current_editor_code", "")
        if not code.strip():
            QMessageBox.information( self, "Add Current Editor", "The editor is empty. Nothing to add."
            ); return
        default_name = f"snippet_{len(self._items) + 1}"
        name, ok = QInputDialog.getText( self, "Name Snippet", "Snippet name:", text=default_name
        )
        if not ok or not name.strip():
            return
        self._items.append( BatchItem(inline_code=code, display_name=name.strip())
        )
        self._refresh_table(); self._update_button_states()
        self.status_lbl.setText( f"Added inline snippet '{name.strip()}'. " f"Queue has {len(self._items)} item(s)."
        )

    def set_current_editor_code(self, code):
        """Store the current editor content for 'Add Current Editor'."""
        self._current_editor_code = code

    def _remove_selected(self):
        rows = sorted( set(idx.row() for idx in self.table.selectedIndexes()), reverse=True,
        )
        if not rows:
            return
        for r in rows:
            if 0 <= r < len(self._items):
                del self._items[r]; self._refresh_table(); self._update_button_states()

    def _clear_all(self):
        if not self._items:
            return
        if QMessageBox.question( self, "Clear Queue", f"Remove all {len(self._items)} item(s) from the queue?"
        ) != QMessageBox.Yes:
            return
        self._items.clear(); self._refresh_table(); self._update_button_states()

    def _move_selected(self, delta):
        """Move the selected row(s) up (delta=-1) or down (delta=+1)."""
        rows = sorted(set(idx.row() for idx in self.table.selectedIndexes()))
        if not rows:
            return
        n = len(self._items); move_set = set(rows)
        if delta == -1:
            ordered = sorted(rows)
            for r in ordered:
                if r > 0 and (r - 1) not in move_set:
                    self._items[r - 1], self._items[r] = ( self._items[r], self._items[r - 1]
                    )
        else:
            ordered = sorted(rows, reverse=True)
            for r in ordered:
                if r < n - 1 and (r + 1) not in move_set:
                    self._items[r], self._items[r + 1] = ( self._items[r + 1], self._items[r]
                    )
        self._refresh_table()
        if rows:
            self.table.selectRow(max(0, min(rows[0] + delta, n - 1)))

    def _refresh_table(self):
        self.table.setRowCount(len(self._items))
        for i, item in enumerate(self._items):
            status_text = item.status; icon = _STATUS_ICONS.get(status_text, ""); status_item = QTableWidgetItem(f"{icon}  {status_text}")
            status_item.setForeground(QColor( _STATUS_COLORS.get(status_text, UI_PALETTE["text"])
            ))
            self.table.setItem(i, self._COL_STATUS, status_item); name = item.resolve_display_name(); self.table.setItem(i, self._COL_NAME, QTableWidgetItem(name))
            if item.file_path:
                type_text = "File"
            else:
                type_text = "Inline"
            self.table.setItem(i, self._COL_TYPE, QTableWidgetItem(type_text))
            if item.status == "Done" and item.output_path:
                details = f"-> {os.path.basename(item.output_path)}"
            elif item.status == "Failed" and item.error:
                details = f"Error: {item.error[:80]}"
            elif item.status == "Rendering":
                details = "Rendering..."
            elif item.status == "Skipped":
                details = "Skipped (batch cancelled)"
            else:
                details = ""
            self.table.setItem(i, self._COL_DETAILS, QTableWidgetItem(details))

    def _update_button_states(self):
        has_selection = bool(self.table.selectedIndexes()); has_items = len(self._items) > 0; self.remove_btn.setEnabled(has_selection and not self._is_running)
        self.clear_btn.setEnabled(has_items and not self._is_running); self.up_btn.setEnabled(has_selection and not self._is_running); self.down_btn.setEnabled(has_selection and not self._is_running)
        self.add_files_btn.setEnabled(not self._is_running); self.add_current_btn.setEnabled(not self._is_running); self.start_btn.setEnabled(has_items and not self._is_running)
        self.close_btn.setEnabled(not self._is_running)

    def _start_batch(self):
        if not self._items:
            return
        if self._is_running:
            return
        for item in self._items:
            item.status = "Pending"; item.error = None; item.output_path = None
        self._refresh_table(); self.overall_bar.setValue(0); self.item_bar.setValue(0)
        self.overall_count_lbl.setText(f"0 / {len(self._items)}"); self.item_pct_lbl.setText("")
        self._exporter = BatchExporter( list(self._items),  # pass a copy of the list self._settings, parent=self,
        )
        self._exporter.item_started.connect(self._on_item_started); self._exporter.item_progress.connect(self._on_item_progress); self._exporter.item_finished.connect(self._on_item_finished)
        self._exporter.item_failed.connect(self._on_item_failed); self._exporter.batch_progress.connect(self._on_batch_progress); self._exporter.status.connect(self._on_status)
        self._exporter.batch_finished.connect(self._on_batch_finished); self._is_running = True; self._update_button_states(); self.cancel_btn.setEnabled(True); self.start_btn.setEnabled(False)
        self._exporter.start()

    def _cancel_batch(self):
        if self._exporter is not None:
            self.status_lbl.setText("Cancelling..."); self._exporter.cancel()

    def _on_item_started(self, index: int, name):
        if 0 <= index < len(self._items):
            self._items[index].status = "Rendering"; self._refresh_table(); self.item_bar.setValue(0); self.item_pct_lbl.setText("0%")
        self.overall_count_lbl.setText( f"{index + 1} / {len(self._items)}"
        )

    def _on_item_progress(self, pct):
        self.item_bar.setValue(pct); self.item_pct_lbl.setText(f"{pct}%")

    def _on_item_finished(self, index: int, output_path):
        if 0 <= index < len(self._items):
            self._items[index].status = "Done"; self._items[index].output_path = output_path; self._refresh_table()

    def _on_item_failed(self, index: int, error):
        if 0 <= index < len(self._items):
            self._items[index].status = "Failed"; self._items[index].error = error; self._refresh_table()

    def _on_batch_progress(self, pct):
        self.overall_bar.setValue(pct)

    def _on_status(self, msg):
        self.status_lbl.setText(msg)

    def _on_batch_finished(self, succeeded: int, total):
        self._is_running = False; self._update_button_states(); self.cancel_btn.setEnabled(False); self.start_btn.setEnabled(len(self._items) > 0); self.item_bar.setValue(0); self.item_pct_lbl.setText("")
        for item in self._items:
            if item.status == "Rendering":
                item.status = "Skipped"
        self._refresh_table()
        if total == 0:
            return
        msg = f"Batch complete: {succeeded} of {total} item(s) succeeded."
        if succeeded == total:
            QMessageBox.information(self, "Batch Complete", msg)
        elif succeeded > 0:
            QMessageBox.warning(self, "Batch Partially Complete", msg)
        else:
            QMessageBox.critical(self, "Batch Failed", msg)

    def _on_close(self):
        if self._is_running:
            reply = QMessageBox.question( self, "Batch Running", "A batch is still running. Cancel it and close?", QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
            self._cancel_batch()
            if self._exporter is not None:
                self._exporter.wait(30000)
            if self._is_running:
                self._is_running = False; self._update_button_states(); self.accept()

    def closeEvent(self, event):
        """Intercept the window-close button too."""
        if self._is_running:
            self._on_close()
            if self._is_running:
                event.ignore(); return
            super().closeEvent(event)

    def keyPressEvent(self, event):
        """Intercept Escape when a batch is running."""
        if event.key() == Qt.Key_Escape and self._is_running:
            self._on_close()
            if self._is_running:
                event.ignore(); return
            super().keyPressEvent(event)

# ======================================================================
# app.py
# ======================================================================

"""
Code Typing Video Generator — application entry point.

Creates the input/, output/, tmp/ folders, configures logging,
launches the QApplication, applies the global professional stylesheet,
and shows the main window.

Run with:
    python -m code_typing_generator.app
or (when installed as a script):
    python app.py
"""

def main():
    configure_logging(level=logging.INFO)
    ensure_cwd_dirs()

    app = QApplication(sys.argv)
    app.setApplicationName("Code Typing Video Generator")
    app.setOrganizationName("Z.ai")
    app.setStyle("Fusion")

    default_font = QFont(UI_FONT_STACK.split(",")[0].strip().strip("'\""), 10)
    app.setFont(default_font)

    app.setStyleSheet(app_stylesheet())

    pal = QPalette()
    p = UI_PALETTE
    pal.setColor(QPalette.Window, QColor(p["bg_app"]))
    pal.setColor(QPalette.WindowText, QColor(p["text"]))
    pal.setColor(QPalette.Base, QColor(p["bg_input"]))
    pal.setColor(QPalette.AlternateBase, QColor(p["bg_panel"]))
    pal.setColor(QPalette.Text, QColor(p["text"]))
    pal.setColor(QPalette.Button, QColor(p["bg_panel"]))
    pal.setColor(QPalette.ButtonText, QColor(p["text"]))
    pal.setColor(QPalette.Highlight, QColor(p["accent"]))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ToolTipBase, QColor(p["bg_panel"]))
    pal.setColor(QPalette.ToolTipText, QColor(p["text"]))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor(p["text_dim"]))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(p["text_dim"]))
    app.setPalette(pal)

    win = MainWindow()
    win.show()
    return app.exec()

if __name__ == "__main__":
    sys.exit(main())
