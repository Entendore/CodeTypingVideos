"""
Configuration constants for the Code Typing Video Generator.

Centralises paths, supported file extensions, resolution presets,
keyboard layout, color themes, and logging setup so other modules
can stay focused on behaviour rather than magic values.
"""

from __future__ import annotations

import logging
import os
from typing import Dict, Tuple


# ── Logging ───────────────────────────────────────────────────────────
def configure_logging(level: int = logging.INFO) -> None:
    """Configure root logging. Safe to call multiple times — updates level if root handlers already exist."""
    root = logging.getLogger()
    if root.handlers:
        # Already configured — just update the level.
        root.setLevel(level)
        for h in root.handlers:
            h.setLevel(level)
        return
    logging.basicConfig(
        level=level,
        format="%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)-25s | %(message)s",
        datefmt="%H:%M:%S",
    )


# ── CWD-based directories ─────────────────────────────────────────────
CWD: str = os.getcwd()
INPUT_DIR: str = os.path.join(CWD, "input")
OUTPUT_DIR: str = os.path.join(CWD, "output")
TMP_DIR: str = os.path.join(CWD, "tmp")


def ensure_cwd_dirs() -> None:
    """Make sure input/, output/, tmp/ exist next to the executable."""
    for d in (INPUT_DIR, OUTPUT_DIR, TMP_DIR):
        os.makedirs(d, exist_ok=True)


# ── Supported input extensions ────────────────────────────────────────
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h",
    ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt",
    ".scala", ".r", ".m", ".sh", ".bash", ".zsh", ".fish", ".ps1",
    ".sql", ".html", ".css", ".scss", ".less", ".json", ".yaml",
    ".yml", ".toml", ".ini", ".cfg", ".conf", ".txt", ".md", ".rst",
    ".lua", ".vim", ".el", ".clj", ".ex", ".exs", ".erl", ".hs",
    ".ml", ".fs", ".dart", ".groovy", ".v", ".sv", ".vhd", ".tcl",
})


# ── Extension → language mapping ──────────────────────────────────
# Maps file extensions to the UI language name used by TOKENIZER_MAP.
# Extensions not listed here are treated as "Plain Text" (no highlighting).
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


# ── Resolution presets ────────────────────────────────────────────────
RESOLUTION_PRESETS: Dict[str, Tuple[int, int]] = {
    "YouTube 1080p": (1920, 1080),
    "YouTube 4K": (3840, 2160),
    "YouTube 720p": (1280, 720),
    "YouTube Short (9:16)": (1080, 1920),
    "TikTok / Reels": (1080, 1920),
    "Instagram Square": (1080, 1080),
    "Twitter / X": (1280, 720),
}


# ── YouTube codec presets ─────────────────────────────────────────────
# YouTube's official recommended encoding settings for SDR uploads.
# Source: https://support.google.com/youtube/answer/1722171
#
# Each preset maps a resolution label to the recommended video bitrate
# (in bits per second) at 30 fps and 60 fps, plus the max H.264 level.
# Audio is always AAC stereo at 128 kbps for SDR.
YOUTUBE_SDR_BITRATES: Dict[str, Dict[str, int]] = {
    # resolution_label → {"30fps": bps, "60fps": bps, "level": h264_level * 10}
    "720p":  {"30fps": 5_000_000,  "60fps": 7_500_000,  "level": 31},  # 3.1
    "1080p": {"30fps": 8_000_000,  "60fps": 12_000_000, "level": 40},  # 4.0
    "1440p": {"30fps": 16_000_000, "60fps": 24_000_000, "level": 50},  # 5.0
    "2160p": {"30fps": 40_000_000, "60fps": 60_000_000, "level": 51},  # 5.1 (4K)
}

# YouTube Shorts must be 60 seconds or shorter and vertical (9:16) or
# square (1:1). We enforce 60s as the hard cap.
YOUTUBE_SHORT_MAX_DURATION: float = 60.0  # seconds

# Vertical aspect ratio (width / height) for YouTube Shorts.
YOUTUBE_SHORT_ASPECT_RATIO: float = 9.0 / 16.0  # ≈ 0.5625


def is_short_resolution(width: int, height: int) -> bool:
    """Return True if the given resolution is vertical (9:16-ish)."""
    if width <= 0 or height <= 0:
        return False
    ratio = width / height
    # Allow a small tolerance for non-standard vertical sizes.
    return ratio <= 0.65  # 9:16 = 0.5625; allow up to ~2:3


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
    # Use the shorter dimension so vertical Shorts are bucketed by their
    # horizontal-equivalent resolution.
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


# ── Smart GPU memory & NVENC configuration ────────────────────────────
# VRAM tiers (in MiB).  Each tier maps to a set of NVENC parameters tuned
# for that memory budget.  The app detects the GPU's free + total VRAM at
# export time and picks the highest tier that fits.
#
# Tier 0 ("GTX 1080"):     4-8 GB  — conservative surfaces, VBR, p4 preset
# Tier 1 ("RTX 2070"):     8-11 GB — balanced, VBR HQ, p5 preset
# Tier 2 ("RTX 3080"):    11-16 GB — more surfaces, 2-pass VBR, p6 preset
# Tier 3 ("RTX 4090"):   16+ GB    — maximum quality, lookahead, p7 preset
#
# The "surfaces" value controls how many reference frames NVENC keeps on
# the GPU.  Each surface at 1080p costs ~12 MB; at 2160p ~48 MB.
# The "frame_chunk" value controls how many raw RGB frames we buffer
# before writing to the FFmpeg pipe — larger chunks reduce syscalls and
# let the GPU batch encode more efficiently.

GPU_VRAM_TIERS: list[dict] = [
    {   # Tier 0 — GTX 1080 / 1060 / similar 4-8 GB cards
        "name": "GTX 1080-class (4-8 GB)",
        "min_vram_mb": 4096,
        "nvenc_preset": "p4",
        "nvenc_rc": "vbr",
        "nvenc_surfaces": 8,
        "nvenc_lookahead": False,
        "nvenc_aq": "spatial",
        "nvenc_multipass": "disabled",
        "frame_chunk": 4,
        "max_res_width": 1920,
        "max_res_height": 1080,
    },
    {   # Tier 0.5 — RTX 2060 Super / 2070 / 3060 Ti (8 GB, Turing+)
        # v1.9: Split from old Tier 1 for 8 GB cards that benefit from
        # quarter_res multipass but shouldn't get 16 surfaces.
        "name": "RTX 2070-class 8 GB (Turing+)",
        "min_vram_mb": 8192,
        "nvenc_preset": "p5",
        "nvenc_rc": "vbr",
        "nvenc_surfaces": 12,
        "nvenc_lookahead": False,
        "nvenc_aq": "spatial",
        "nvenc_multipass": "quarter_res",
        "frame_chunk": 6,
        "max_res_width": 2560,
        "max_res_height": 1440,
    },
    {   # Tier 1 — RTX 3070 / 4060 Ti / similar 10-12 GB cards
        "name": "RTX 3070-class (10-12 GB)",
        "min_vram_mb": 10240,
        "nvenc_preset": "p6",
        "nvenc_rc": "vbr",
        "nvenc_surfaces": 16,
        "nvenc_lookahead": False,
        "nvenc_aq": "spatial",
        "nvenc_multipass": "quarter_res",
        "frame_chunk": 8,
        "max_res_width": 2560,
        "max_res_height": 1440,
    },
    {   # Tier 2 — RTX 3080 / 4070 / similar 12-16 GB cards
        "name": "RTX 3080-class (12-16 GB)",
        "min_vram_mb": 12288,
        "nvenc_preset": "p6",
        "nvenc_rc": "vbr",
        "nvenc_surfaces": 24,
        "nvenc_lookahead": True,
        "nvenc_aq": "spatial",
        "nvenc_multipass": "full_res",
        "frame_chunk": 8,
        "max_res_width": 3840,
        "max_res_height": 2160,
    },
    {   # Tier 3 — RTX 4090 / 3090 / similar 20+ GB cards
        "name": "RTX 4090-class (20+ GB)",
        "min_vram_mb": 20480,
        "nvenc_preset": "p7",
        "nvenc_rc": "vbr",
        "nvenc_surfaces": 32,
        "nvenc_lookahead": True,
        "nvenc_aq": "spatial",
        "nvenc_multipass": "full_res",
        "frame_chunk": 12,
        "max_res_width": 3840,
        "max_res_height": 2160,
    },
]

# VRAM safety margin — we use this fraction of *free* VRAM as the
# effective budget so the OS and other GPU tasks (display compositor,
# browser, etc.) are not starved.
GPU_VRAM_SAFETY_MARGIN: float = 0.75

# How often (in frames) to poll nvidia-smi for VRAM usage during export.
# Polling has ~30ms overhead per call; at 30fps a 60-frame interval means
# roughly once every 2 seconds — low overhead but fast enough to catch
# runaway memory growth.
GPU_VRAM_POLL_INTERVAL: int = 60

# If free VRAM drops below this fraction of total VRAM during export,
# we log a warning and suggest the user close other GPU apps.
GPU_VRAM_LOW_WATERMARK: float = 0.15


def gpu_tier_for_vram(total_vram_mb: int) -> dict:
    """Return the highest GPU_VRAM_TIERS entry that fits the given VRAM.

    Falls back to tier 0 (the most conservative) if the GPU has less than
    4 GB (extremely rare for NVENC-capable hardware).
    """
    for tier in reversed(GPU_VRAM_TIERS):
        if total_vram_mb >= tier["min_vram_mb"]:
            return tier
    return GPU_VRAM_TIERS[0]


# ── Keyboard overlay geometry ─────────────────────────────────────────
KEYBOARD_LAYOUTS: Dict[str, list[list[str]]] = {
    "QWERTY (US)": [
        list("`1234567890-="),
        list("qwertyuiop[]\\"),
        list("asdfghjkl;'"),
        list("zxcvbnm,./"),
        [" "],
    ],
    "QWERTZ (German)": [
        list("^1234567890ß´"),
        list("qwertzuiopü+"),
        list("asdfghjklöä"),
        list("yxcvbnm,./"),
        [" "],
    ],
    "AZERTY (French)": [
        list("²&é\"'(-è_çà"),
        list("azertyuiop^$"),
        list("qsdfghjklmù*"),
        list("wxcvbn,;:!?"),
        [" "],
    ],
    "QWERTY (UK)": [
        list("`1234567890-="),
        list("qwertyuiop[]"),
        list("asdfghjkl;'#"),
        list("\\zxcvbnm,./"),
        [" "],
    ],
    "Dvorak (US)": [
        list("`1234567890[]"),
        list("',.pyfgcrl/="),
        list("aoeuidhtns-"),
        list(";qjkxbmwvz"),
        [" "],
    ],
    "Colemak": [
        list("`1234567890-="),
        list("qwfpgjluy;[]\\"),
        list("arstdhneio'"),
        list("zxcvbk,./"),
        [" "],
    ],
    "JIS (Japanese)": [
        list("1234567890-^\\"),
        list("qwertyuiop@["),
        list("asdfghjkl;:]"),
        list("zxcvbnm,./\\"),
        [" "],
    ],
}

# Default layout used for backwards compatibility.
KEYBOARD_ROWS: list[list[str]] = KEYBOARD_LAYOUTS["QWERTY (US)"]

KEY_WIDTH: int = 40
KEY_HEIGHT: int = 40
KEY_MARGIN: int = 4

# Keyboard position modes.
KB_POSITIONS: Tuple[str, ...] = (
    "Below Code",      # Keyboard sits below the code area (default for 16:9)
    "Overlay Bottom",  # Semi-transparent keyboard overlaid on bottom of code
    "Right Panel",     # Keyboard in a side panel (good for 9:16 vertical)
)

# Smart defaults per resolution: (position, scale_pct, gap).
KB_DEFAULTS: Dict[str, Dict[str, object]] = {
    "YouTube 1080p":         {"position": "Below Code",    "scale": 100, "gap": 20},
    "YouTube 4K":            {"position": "Below Code",    "scale": 100, "gap": 40},
    "YouTube 720p":          {"position": "Below Code",    "scale": 100, "gap": 15},
    "YouTube Short (9:16)":  {"position": "Right Panel",   "scale": 70,  "gap": 10},
    "TikTok / Reels":        {"position": "Right Panel",   "scale": 70,  "gap": 10},
    "Instagram Square":      {"position": "Overlay Bottom","scale": 80,  "gap": 10},
    "Twitter / X":           {"position": "Below Code",    "scale": 100, "gap": 15},
}


# ── Color themes ──────────────────────────────────────────────────────
THEMES: Dict[str, Dict[str, str]] = {
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
    "Light (Solarized)": {
        "background": "#fdf6e3", "foreground": "#657b83", "comment": "#93a1a1",
        "keyword": "#859900", "string": "#2aa198", "number": "#d33682",
        "function": "#268bd2", "builtin": "#b58900", "decorator": "#cb4b16",
        "operator": "#859900", "class_name": "#b58900",
        "line_number": "#93a1a1", "current_line": "#eee8d5",
        "cursor": "#657b83", "title_bar": "#eee8d5", "title_text": "#268bd2",
        "window_border": "#eee8d5", "button_close": "#dc322f",
        "button_min": "#b58900", "button_max": "#859900",
    },
}


# ── QSettings keys ────────────────────────────────────────────────────
SETTINGS_ORG = "Z.ai"
SETTINGS_APP = "CodeTypingVideoGenerator"

# Directory where named preset files (JSON) are stored.
PRESET_DIR: str = os.path.join(CWD, "presets")


def ensure_preset_dir() -> None:
    """Make sure the presets/ directory exists."""
    os.makedirs(PRESET_DIR, exist_ok=True)


# ── Professional UI stylesheet ────────────────────────────────────────
# A modern dark theme applied to the entire QApplication. Uses a cohesive
# palette (slate blue accent on near-black background), rounded corners
# on all interactive widgets, subtle hover/pressed states, and consistent
# spacing. Designed to look at home next to VS Code, OBS, or DaVinci.
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

# Spacing & sizing constants (px).
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

# Font families that look professional across platforms. We try them in
# order and Qt picks the first one available on the system.
UI_FONT_STACK = "Inter, 'Segoe UI', 'SF Pro Text', Roboto, 'Helvetica Neue', Arial, 'Liberation Sans', 'DejaVu Sans', sans-serif"
UI_MONO_STACK = ("'JetBrains Mono', 'Cascadia Code', 'Fira Code', 'Source Code Pro', "
                 "'IBM Plex Mono', Inconsolata, Hack, 'Space Mono', mononoki, "
                 "Consolas, 'SF Mono', Menlo, 'Liberation Mono', 'DejaVu Sans Mono', monospace")

# ── SVG icon strings (inline for zero-dependency icons) ────────────────
# Each icon is a tiny 16x16 or 20x20 SVG used in buttons and headers.
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


def app_stylesheet() -> str:
    """Return the global QSS stylesheet for the application.

    Applied once via ``app.setStyleSheet(app_stylesheet())`` in app.py.
    Uses the palette in UI_PALETTE and the spacing in UI_SPACING.
    """
    p = UI_PALETTE
    s = UI_SPACING
    return f"""
    /* ── Global ─────────────────────────────────────────────────── */
    QWidget {{
        background-color: {p['bg_app']};
        color: {p['text']};
        font-family: {UI_FONT_STACK};
        font-size: 13px;
    }}
    QToolTip {{
        background-color: {p['bg_panel']};
        color: {p['text']};
        border: 1px solid {p['border']};
        border-radius: {s['radius']}px;
        padding: {s['sm']}px {s['md']}px;
    }}

    /* ── Main window ────────────────────────────────────────────── */
    QMainWindow {{
        background-color: {p['bg_app']};
    }}

    /* ── Group boxes ────────────────────────────────────────────── */
    QGroupBox {{
        background-color: {p['bg_panel']};
        border: 1px solid {p['border']};
        border-radius: {s['radius_lg']}px;
        margin-top: {s['xl']}px;
        padding: {s['lg']}px {s['md']}px {s['md']}px {s['md']}px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: {s['md']}px;
        padding: 0 {s['sm']}px;
        background-color: {p['bg_panel']};
        color: {p['text_dim']};
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.5px;
        text-transform: uppercase;
    }}

    /* ── Buttons ────────────────────────────────────────────────── */
    QPushButton {{
        background-color: {p['bg_hover']};
        color: {p['text']};
        border: 1px solid {p['border']};
        border-radius: {s['radius']}px;
        padding: {s['sm']}px {s['lg']}px;
        min-height: {s['control_h']}px;
        font-weight: 500;
    }}
    QPushButton:hover {{
        background-color: {p['bg_pressed']};
        border-color: {p['text_dim']};
    }}
    QPushButton:pressed {{
        background-color: {p['border']};
    }}
    QPushButton:disabled {{
        background-color: {p['bg_app']};
        color: {p['border']};
        border-color: {p['border']};
    }}

    /* ── Primary action buttons (accent, gradient feel) ─────────── */
    QPushButton#primaryBtn {{
        background-color: qlineargradient(
            x1:0, y1:0, x2:0, y2:1,
            stop:0 {p['accent']},
            stop:1 {p['accent_hover']}
        );
        color: #ffffff;
        border: none;
        min-height: {s['control_h_lg']}px;
        font-weight: 600;
        padding-left: {s['xl']}px;
        padding-right: {s['xl']}px;
    }}
    QPushButton#primaryBtn:hover {{
        background-color: {p['accent_hover']};
        border: 1px solid rgba(255,255,255,30);
    }}
    QPushButton#primaryBtn:pressed {{
        background-color: {p['accent_pressed']};
    }}
    QPushButton#primaryBtn:disabled {{
        background-color: {p['border']};
        color: {p['text_dim']};
    }}

    /* ── Play / Pause button (accent ring, larger) ──────────────── */
    QPushButton#playBtn {{
        background-color: {p['bg_panel']};
        color: {p['accent']};
        border: 2px solid {p['accent']};
        border-radius: {s['radius_lg']}px;
        min-height: {s['play_btn']}px;
        min-width: {s['play_btn']}px;
        font-weight: 600;
        font-size: 14px;
        padding: 0px;
    }}
    QPushButton#playBtn:hover {{
        background-color: {p['accent']};
        color: #ffffff;
    }}
    QPushButton#playBtn:pressed {{
        background-color: {p['accent_pressed']};
        border-color: {p['accent_pressed']};
        color: #ffffff;
    }}

    /* ── Danger buttons (cancel / delete) ───────────────────────── */
    QPushButton#dangerBtn {{
        background-color: transparent;
        color: {p['danger']};
        border: 1px solid {p['danger']};
        border-radius: {s['radius']}px;
    }}
    QPushButton#dangerBtn:hover {{
        background-color: {p['danger']};
        color: #ffffff;
    }}

    /* ── Sample-code pill buttons ───────────────────────────────── */
    QPushButton#sampleBtn {{
        background-color: transparent;
        color: {p['text_dim']};
        border: 1px solid {p['border']};
        border-radius: 14px;
        padding: {s['xs']}px {s['lg']}px;
        min-height: 26px;
        font-size: 12px;
        font-weight: 500;
    }}
    QPushButton#sampleBtn:hover {{
        color: {p['text']};
        border-color: {p['accent']};
        background-color: rgba(88,101,242,12);
    }}

    /* ── Inputs: line edits, combos, spin boxes ─────────────────── */
    QLineEdit, QComboBox, QSpinBox, QFontComboBox {{
        background-color: {p['bg_input']};
        color: {p['text']};
        border: 1px solid {p['border']};
        border-radius: {s['radius']}px;
        padding: {s['xs']}px {s['sm']}px;
        min-height: {s['control_h']}px;
        selection-background-color: {p['accent']};
        selection-color: #ffffff;
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QFontComboBox:focus {{
        border: 1px solid {p['border_focus']};
    }}
    QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QFontComboBox:hover {{
        border-color: {p['text_dim']};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 22px;
    }}
    QComboBox::down-arrow {{
        image: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid {p['text_dim']};
        margin-right: 8px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {p['bg_panel']};
        color: {p['text']};
        border: 1px solid {p['border']};
        border-radius: {s['radius']}px;
        selection-background-color: {p['accent']};
        selection-color: #ffffff;
        padding: {s['xs']}px;
        outline: none;
    }}

    /* ── Sliders ────────────────────────────────────────────────── */
    QSlider::groove:horizontal {{
        background: {p['bg_input']};
        height: 4px;
        border-radius: 2px;
    }}
    QSlider::sub-page:horizontal {{
        background: qlineargradient(
            x1:0, y1:0, x2:1, y2:0,
            stop:0 {p['accent']},
            stop:1 {p['accent_hover']}
        );
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background: {p['text']};
        width: 14px;
        height: 14px;
        margin: -5px 0;
        border-radius: 7px;
        border: 2px solid {p['bg_app']};
    }}
    QSlider::handle:horizontal:hover {{
        background: {p['accent']};
        border-color: {p['accent']};
    }}

    /* ── Timeline slider (wider groove, accent-filled) ──────────── */
    QSlider#timelineSlider::groove:horizontal {{
        height: 6px;
        border-radius: 3px;
    }}
    QSlider#timelineSlider::handle:horizontal {{
        width: 16px;
        height: 16px;
        margin: -5px 0;
        border-radius: 8px;
    }}
    QSlider#timelineSlider::handle:horizontal:hover {{
        background: {p['accent']};
        width: 18px;
        margin: -6px 0;
    }}

    /* ── Progress bar ───────────────────────────────────────────── */
    QProgressBar {{
        background-color: {p['bg_input']};
        border: 1px solid {p['border']};
        border-radius: {s['radius']}px;
        text-align: center;
        color: {p['text']};
        min-height: {s['control_h']}px;
        font-weight: 500;
    }}
    QProgressBar::chunk {{
        background: qlineargradient(
            x1:0, y1:0, x2:1, y2:0,
            stop:0 {p['accent']},
            stop:1 {p['accent_hover']}
        );
        border-radius: {s['radius'] - 1}px;
    }}

    /* ── Checkboxes ─────────────────────────────────────────────── */
    QCheckBox {{
        spacing: {s['sm']}px;
        min-height: {s['control_h']}px;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 3px;
        border: 1px solid {p['border']};
        background-color: {p['bg_input']};
    }}
    QCheckBox::indicator:hover {{
        border-color: {p['accent']};
    }}
    QCheckBox::indicator:checked {{
        background-color: {p['accent']};
        border-color: {p['accent']};
        image: none;
    }}

    /* ── Tabs (used for the settings panel) ─────────────────────── */
    QTabWidget::pane {{
        border: 1px solid {p['border']};
        border-radius: {s['radius_lg']}px;
        background-color: {p['bg_panel']};
        padding: {s['md']}px;
        top: -1px;
    }}
    QTabBar::tab {{
        background-color: transparent;
        color: {p['text_dim']};
        padding: {s['sm']}px {s['lg']}px;
        margin-right: 2px;
        border: 1px solid transparent;
        border-bottom: none;
        border-top-left-radius: {s['radius']}px;
        border-top-right-radius: {s['radius']}px;
        font-weight: 500;
        font-size: 12px;
        min-height: {s['control_h']}px;
    }}
    QTabBar::tab:hover {{
        background-color: {p['bg_hover']};
        color: {p['text']};
    }}
    QTabBar::tab:selected {{
        background-color: {p['bg_panel']};
        color: {p['text']};
        border-color: {p['border']};
        border-bottom: 2px solid {p['accent']};
    }}

    /* ── Scroll bars (slim, refined) ────────────────────────────── */
    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {p['border']};
        min-height: 30px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {p['text_dim']};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: none;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 8px;
        margin: 0;
    }}
    QScrollBar::handle:horizontal {{
        background: {p['border']};
        min-width: 30px;
        border-radius: 4px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {p['text_dim']};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: none;
    }}

    /* ── Text edit (code editor) ────────────────────────────────── */
    QTextEdit {{
        background-color: {p['bg_input']};
        color: {p['text']};
        border: 1px solid {p['border']};
        border-radius: {s['radius']}px;
        font-family: {UI_MONO_STACK};
        font-size: 13px;
        padding: {s['sm']}px;
        selection-background-color: {p['accent']};
        selection-color: #ffffff;
    }}
    QTextEdit:focus {{
        border-color: {p['border_focus']};
    }}

    /* ── Labels ─────────────────────────────────────────────────── */
    QLabel {{
        background: transparent;
    }}
    QLabel#sectionHeader {{
        color: {p['text_dim']};
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.5px;
        text-transform: uppercase;
        padding: {s['xs']}px 0;
    }}
    QLabel#previewPlaceholder {{
        color: {p['text_dim']};
        font-size: 14px;
    }}
    QLabel#timeLabel {{
        color: {p['text_dim']};
        font-family: {UI_MONO_STACK};
        font-size: 12px;
        padding: 0 {s['sm']}px;
        min-width: 42px;
    }}

    /* ── Panel header bar ───────────────────────────────────────── */
    QLabel#panelHeader {{
        color: {p['text']};
        font-size: 12px;
        font-weight: 600;
        letter-spacing: 0.3px;
        background-color: {p['bg_panel']};
        padding: {s['sm']}px {s['lg']}px;
        border-top-left-radius: {s['radius_lg']}px;
        border-top-right-radius: {s['radius_lg']}px;
    }}

    /* ── Status bar ─────────────────────────────────────────────── */
    QStatusBar {{
        background-color: {p['bg_panel']};
        color: {p['text_dim']};
        border-top: 1px solid {p['border']};
        font-size: 12px;
        padding: 2px {s['md']}px;
    }}
    QStatusBar::item {{ border: none; }}
    QLabel#statusPermanent {{
        color: {p['text_dim']};
        font-size: 11px;
        padding: 0 {s['lg']}px;
        border-left: 1px solid {p['border']};
    }}

    /* ── Menu bar ───────────────────────────────────────────────── */
    QMenuBar {{
        background-color: {p['bg_app']};
        color: {p['text']};
        border-bottom: 1px solid {p['border']};
        padding: 2px;
    }}
    QMenuBar::item {{
        background: transparent;
        padding: {s['sm']}px {s['lg']}px;
        border-radius: {s['radius']}px;
    }}
    QMenuBar::item:selected {{
        background-color: {p['bg_hover']};
    }}
    QMenu {{
        background-color: {p['bg_panel']};
        color: {p['text']};
        border: 1px solid {p['border']};
        border-radius: {s['radius']}px;
        padding: {s['xs']}px;
    }}
    QMenu::item {{
        padding: {s['sm']}px {s['lg']}px;
        border-radius: {s['radius']}px;
    }}
    QMenu::item:selected {{
        background-color: {p['accent']};
        color: #ffffff;
    }}
    QMenu::separator {{
        height: 1px;
        background: {p['border']};
        margin: {s['xs']}px {s['sm']}px;
    }}

    /* ── Splitter handle (thin, subtle) ─────────────────────────── */
    QSplitter::handle:horizontal {{
        background-color: {p['border']};
        width: 1px;
    }}
    QSplitter::handle:horizontal:hover {{
        background-color: {p['accent']};
        width: 2px;
    }}

    /* ── Form layout labels ─────────────────────────────────────── */
    QLabel[class="formLabel"] {{
        color: {p['text_dim']};
        font-size: 12px;
    }}

    /* ── Message box ────────────────────────────────────────────── */
    QMessageBox {{
        background-color: {p['bg_panel']};
    }}
    QMessageBox QLabel {{
        color: {p['text']};
        font-size: 13px;
    }}
    QMessageBox QPushButton {{
        min-width: 80px;
    }}

    /* ── Input dialog ───────────────────────────────────────────── */
    QDialog {{
        background-color: {p['bg_panel']};
        color: {p['text']};
    }}

    /* ── Preview container frame ────────────────────────────────── */
    QFrame#previewFrame {{
        background-color: #0a0a0f;
        border: 1px solid {p['border']};
        border-radius: {s['radius_lg']}px;
    }}
    QFrame#previewFrame:hover {{
        border-color: {p['text_dim']};
    }}

    /* ── Drop zone highlight ────────────────────────────────────── */
    QTextEdit#codeEditor[dropActive="true"] {{
        border: 2px dashed {p['accent']};
        background-color: rgba(88,101,242,8);
    }}

    /* ── Vertical separator (used between button groups) ────────── */
    QFrame#vsep {{
        color: {p['border']};
        max-width: 1px;
        margin: 0 {s['sm']}px;
    }}

    /* ── Toolbar frame (top action bar) ─────────────────────────── */
    QFrame#toolbar {{
        background-color: {p['bg_panel']};
        border: 1px solid {p['border']};
        border-bottom: none;
        border-radius: {s['radius_lg']}px {s['radius_lg']}px 0 0;
        padding: {s['sm']}px {s['md']}px;
    }}

    /* ── Thin progress bar under toolbar ────────────────────────── */
    QProgressBar#toolbarProgress {{
        background-color: {p['bg_input']};
        border: none;
        border-radius: 0;
        min-height: 3px;
        max-height: 3px;
    }}
    QProgressBar#toolbarProgress::chunk {{
        background: {p['accent']};
        border-radius: 0;
    }}

    /* ── Vertical splitter handle ───────────────────────────────── */
    QSplitter::handle:vertical {{
        background-color: {p['border']};
        height: 1px;
    }}
    QSplitter::handle:vertical:hover {{
        background-color: {p['accent']};
        height: 2px;
    }}

    /* ── Panel body (used for left/right panels) ────────────────── */
    QWidget#panelBody {{
        background-color: {p['bg_panel']};
        border: 1px solid {p['border']};
        border-top: none;
        border-radius: 0 0 {s['radius_lg']}px {s['radius_lg']}px;
    }}

    """
