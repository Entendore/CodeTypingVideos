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

from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple, Union

from PySide6.QtCore import Qt, QRect, QPoint
from PySide6.QtGui import (
    QPainter, QFont, QColor, QPixmap, QFontMetrics, QImage, QLinearGradient,
)

from .config import THEMES, KEYBOARD_LAYOUTS, KEY_WIDTH, KEY_HEIGHT, KEY_MARGIN, KB_POSITIONS
from .tokenizers import TOKENIZER_MAP, PythonTokenizer, BaseTokenizer


# Overlay position presets (used by the stats / watermark overlays).
OVERLAY_POSITIONS = ("Top-Left", "Top-Right", "Bottom-Left", "Bottom-Right")


class CodeRenderer:
    """Render an individual frame of the typing animation."""

    TOKEN_COLOR_MAP: Dict[str, str] = {
        "keyword": "keyword", "builtin": "builtin", "string": "string",
        "triple_string": "string", "number": "number", "comment": "comment",
        "decorator": "decorator", "function": "function",
        "class_name": "class_name", "operator": "operator",
    }

    CURSOR_BLINK_PERIOD = 0.53  # seconds
    _LINE_CACHE_MAX = 512       # max unique lines whose layout we cache
    MIN_FONT_SIZE = 8
    MAX_FONT_SIZE = 60

    @staticmethod
    def auto_font_size(
        code_lines: int,
        width: int,
        height: int,
        padding: int = 50,
        show_window_chrome: bool = True,
        show_line_numbers: bool = True,
        show_keyboard: bool = False,
        tab_size: int = 4,
        target_lines: Optional[int] = None,
        keyboard_position: str = "Below Code",
        keyboard_scale: float = 1.0,
        keyboard_gap: int = 20,
        code: Optional[str] = None,
        font_family: str = "Consolas",
    ) -> int:
        """Calculate the largest font size that fits *code_lines* lines.

        If *target_lines* is given the font is sized so that exactly
        that many lines fill the vertical space (useful when you want
        the code to look spacious rather than crammed).

        If *code* is provided, the horizontal constraint is based on the
        actual longest line (accounting for tabs), rather than a fixed
        120-char assumption.

        The calculation accounts for all space usage:
        - Padding on all sides
        - Window chrome (title bar + rounded corners)
        - Line numbers column
        - Code margin
        - Keyboard overlay (below code or right panel)
        - A small safety margin to prevent edge-case overlaps
        """
        # ── Chrome height ─────────────────────────────────────────────
        # Title bar is 42px. The rounded rect extends 10px below for
        # the corner radius, but code starts at padding + title_bar_h.
        # We use 42px which matches render_frame's calculation.
        chrome = 42 if show_window_chrome else 0

        # ── Keyboard space calculation ────────────────────────────────
        # Must exactly match the calculations in __init__ and render_frame
        ref = min(width, height) / 1080.0
        kb_h = 0
        kb_panel_w = 0

        if show_keyboard:
            scaled_kh = KEY_HEIGHT * ref * keyboard_scale
            scaled_km = KEY_MARGIN * ref * keyboard_scale
            scaled_kw = KEY_WIDTH * ref * keyboard_scale

            if keyboard_position == "Below Code":
                # Must match render_frame:
                #   area_h -= self._kb_total_h + 30 + self.keyboard_gap
                # where _kb_total_h = (scaled_kh + scaled_km) * 5
                kb_total_h = (scaled_kh + scaled_km) * 5
                kb_h = kb_total_h + 30 + keyboard_gap
            elif keyboard_position == "Right Panel":
                # Must match render_frame:
                #   kb_panel_w = int(self._kb_total_w + self.keyboard_gap * 2 + self.padding)
                # where _kb_total_w = (scaled_kw + scaled_km) * 15
                kb_total_w = (scaled_kw + scaled_km) * 15
                kb_panel_w = int(kb_total_w + keyboard_gap * 2 + padding)
        else:
            scaled_kh = 0
            scaled_km = 0
            scaled_kw = 0

        # ── Available vertical space ──────────────────────────────────
        # Must match render_frame:
        #   area_top = self.padding + chrome
        #   area_h = self.height - 2 * self.padding - chrome - kb_h
        safety_margin_v = 6  # Prevents edge-case vertical overlaps
        area_h = height - 2 * padding - chrome - kb_h - safety_margin_v

        # ── Available horizontal space ────────────────────────────────
        # Must match render_frame / __init__:
        #   _start_x = padding + ln_width + code_margin
        #   Right edge ≈ width - padding - kb_panel_w
        ln_width = 65 if show_line_numbers else 0
        code_margin = 20
        start_x = padding + ln_width + code_margin
        safety_margin_h = 4  # Prevents edge-case horizontal overlaps
        area_w = width - padding - start_x - safety_margin_h - kb_panel_w

        # ── Vertical constraint ───────────────────────────────────────
        # Line height is: line_h = int(font_size * 1.55)
        # For N lines, total height = N * int(fs * 1.55)
        # 
        # Due to int() truncation, int(fs * 1.55) <= fs * 1.55
        # So N * int(fs * 1.55) <= N * fs * 1.55
        # 
        # We need: N * int(fs * 1.55) <= area_h
        # Approximate: fs * 1.55 <= area_h / N - small_buffer
        # The buffer accounts for cumulative int() truncation error.
        effective_lines = target_lines if target_lines else code_lines
        if effective_lines > 0 and area_h > 0:
            # Subtract 0.5 to account for int() truncation and rounding
            fs_v = int((area_h / (effective_lines * 1.55)) - 0.5)
        else:
            fs_v = CodeRenderer.MAX_FONT_SIZE

        # ── Horizontal constraint ─────────────────────────────────────
        # Calculate the maximum columns that need to fit
        if code is not None:
            # Calculate actual max line width (tabs expanded to spaces)
            max_cols = 0
            for line in code.split('\n'):
                # Expand tabs to spaces
                expanded = line.replace('\t', ' ' * tab_size)
                max_cols = max(max_cols, len(expanded))
            max_cols = max(max_cols, 1)  # At least 1 column
        else:
            # Heuristic: assume max 120 chars if code not provided
            max_cols = 120

        # Char width ratio for monospace fonts.
        # Measured values for common fonts (at various sizes):
        #   Consolas:        ~0.600
        #   Courier New:     ~0.600
        #   Fira Code:       ~0.600
        #   JetBrains Mono:  ~0.600
        #   Source Code Pro: ~0.600
        #   Cascadia Code:   ~0.600
        # We use 0.60 as a safe default. Slightly higher (0.61) adds
        # extra safety for fonts that might be slightly wider.
        char_width_ratio = 0.61

        if max_cols > 0 and area_w > 0:
            # Subtract 0.5 to add safety buffer
            fs_h = int((area_w / (max_cols * char_width_ratio)) - 0.5)
        else:
            fs_h = CodeRenderer.MAX_FONT_SIZE

        # ── Final size ────────────────────────────────────────────────
        # Use the smaller constraint to ensure both dimensions fit
        fs = min(fs_v, fs_h)

        # Clamp to valid range
        return max(CodeRenderer.MIN_FONT_SIZE, min(fs, CodeRenderer.MAX_FONT_SIZE))

    def __init__(
        self,
        width: int = 1920,
        height: int = 1080,
        theme_name: str = "Dracula",
        font_family: str = "Consolas",
        font_size: int = 24,
        show_line_numbers: bool = True,
        show_window_chrome: bool = True,
        padding: int = 50,
        tab_size: int = 4,
        title_text: str = "main.py — Code Editor",
        language: str = "Python",
        show_keyboard: bool = False,
        keyboard_gap: int = 20,
        keyboard_scale: float = 1.0,
        keyboard_layout: str = "QWERTY (US)",
        keyboard_position: str = "Below Code",
        keyboard_opacity: float = 1.0,
        keyboard_radius: int = 6,
        show_stats: bool = False,
        stats_position: str = "Bottom-Right",
        watermark_text: str = "",
        watermark_image: Optional[str] = None,
        watermark_position: str = "Bottom-Right",
        watermark_opacity: float = 0.4,
    ) -> None:
        self.logger = logging.getLogger("CodeRenderer")
        self.width = width
        self.height = height
        self.theme_name = theme_name
        if theme_name not in THEMES:
            raise ValueError(f"Unknown theme '{theme_name}'; available: {', '.join(THEMES)}")
        self.theme = THEMES[theme_name]
        self.font_family = font_family
        self.font_size = font_size
        self.show_line_numbers = show_line_numbers
        self.show_window_chrome = show_window_chrome
        self.padding = padding
        self.tab_size = tab_size
        self.title_text = title_text
        self.language = language
        self.show_keyboard = show_keyboard
        self.keyboard_gap = max(0, keyboard_gap)
        self.keyboard_layout_name = keyboard_layout
        self._kb_rows = KEYBOARD_LAYOUTS.get(keyboard_layout, KEYBOARD_LAYOUTS["QWERTY (US)"])
        self.keyboard_position = keyboard_position if keyboard_position in KB_POSITIONS else "Below Code"
        self.keyboard_opacity = max(0.1, min(1.0, keyboard_opacity))
        self.keyboard_radius = max(0, keyboard_radius)
        self.show_stats = show_stats
        self.stats_position = stats_position if stats_position in OVERLAY_POSITIONS else "Bottom-Right"
        self.watermark_text = watermark_text
        self.watermark_image: Optional[QPixmap] = None
        self.watermark_position = watermark_position if watermark_position in OVERLAY_POSITIONS else "Bottom-Right"
        self.watermark_opacity = max(0.0, min(1.0, watermark_opacity))

        self.pressed_key: Optional[str] = None
        # The exporter / preview sets current_time so the stats overlay
        # can compute live WPM/keystrokes/elapsed.
        self.current_time: float = 0.0
        # Reference to the animator; set by the exporter so the stats
        # overlay can call stats_at(t).
        self.animator_ref = None
        self.bg_image: Optional[QPixmap] = None

        if watermark_image and os.path.exists(watermark_image):
            self.watermark_image = QPixmap(watermark_image)

        self.title_bar_h = 42 if show_window_chrome else 0
        self.ln_width = 65 if show_line_numbers else 0
        self.code_margin = 20
        self.font = QFont(font_family, font_size)
        self.font.setStyleHint(QFont.Monospace)
        self.line_h = int(font_size * 1.55)

        # Precomputed font metrics & layout constants (constant for the
        # lifetime of this renderer instance).
        self._fm = QFontMetrics(self.font)
        self._tab_advance = self._fm.horizontalAdvance(" ") * self.tab_size
        self._start_x = self.padding + self.ln_width + self.code_margin

        # PERF (v1.5.1): pre-create the smaller line-number font and the
        # traffic-light glyph font once, instead of constructing a new
        # QFont per visible line per frame (which previously dominated
        # the per-frame allocation cost on long clips).
        self._ln_font = QFont(font_family, max(8, font_size - 2))
        self._ln_font.setStyleHint(QFont.Monospace)
        self._glyph_font = QFont("Arial", 7, QFont.Bold)
        self._title_font = QFont(font_family, 12)

        # Scaled keyboard dimensions — base sizes are for 1080p; scale
        # linearly with resolution so the keyboard looks proportional on
        # 4K, Shorts, etc.  keyboard_scale lets the user tweak further.
        ref = min(width, height) / 1080.0
        self._kb_key_w = KEY_WIDTH * ref * keyboard_scale
        self._kb_key_h = KEY_HEIGHT * ref * keyboard_scale
        self._kb_key_margin = KEY_MARGIN * ref * keyboard_scale
        # PERF (v1.5.1): pre-compute total keyboard bounds once instead
        # of recomputing them every render_frame() call.
        self._kb_total_w = (self._kb_key_w + self._kb_key_margin) * 15
        self._kb_total_h = (self._kb_key_h + self._kb_key_margin) * 5

        # PERF (v1.6): pre-create the keyboard overlay font once in
        # __init__ instead of constructing a new QFont every frame in
        # _draw_keyboard.
        self._kb_font_size = max(7, int(9 * self._kb_key_h / KEY_HEIGHT))
        self._kb_font = QFont("Arial", self._kb_font_size)

        # PERF (v1.6): pre-create the stats overlay font and its metrics
        # once, instead of allocating a new QFont + QFontMetrics every
        # frame in _draw_stats.
        self._stats_font = QFont(font_family, max(10, font_size - 6))
        self._stats_font.setStyleHint(QFont.Monospace)
        self._stats_fm = QFontMetrics(self._stats_font)
        self._stats_line_h = int(self._stats_fm.height() * 1.15)
        self._stats_lines = [
            "WPM:     0.0",
            "Keys:      0",
            "Acc:   100.0%",
            "Time:  00:00",
        ]
        self._stats_pad = 10
        self._stats_box_w = max(
            self._stats_fm.horizontalAdvance(line) for line in self._stats_lines
        ) + 2 * self._stats_pad
        self._stats_box_h = (
            self._stats_line_h * len(self._stats_lines) + 2 * self._stats_pad
        )

        # PERF (v1.6): pre-create the watermark font and its metrics once
        # instead of allocating a new QFont + QFontMetrics every frame in
        # _draw_watermark.
        self._wm_font = QFont(font_family, max(10, font_size - 4))
        self._wm_font.setBold(True)
        self._wm_fm = QFontMetrics(self._wm_font)
        self._wm_target_w = int(self.width * 0.08)
        self._wm_scaled: Optional[QPixmap] = None
        self._wm_cached_text = ""  # to detect text changes

        # PERF (v1.6): pre-compute theme QColor objects once, instead of
        # constructing new QColor objects from hex strings on every
        # setPen/setBrush call in the per-frame render path.
        self._qcolors: Dict[str, QColor] = {}
        for key, val in self.theme.items():
            if isinstance(val, str) and val.startswith("#"):
                self._qcolors[key] = QColor(val)

        # PERF (v1.7): pre-compute QColors for the current-line highlight,
        # line number, cursor, and common overlay colours so that zero
        # QColor objects are allocated on the per-frame render path.
        self._qc_current_line = self._qcolors.get("current_line", QColor("#44475a"))
        self._qc_cursor = self._qcolors.get("cursor", QColor("#f8f8f2"))
        self._qc_line_num = self._qcolors.get("line_number", QColor("#6272a4"))
        self._qc_fg = self._qcolors.get("foreground", QColor("#f8f8f2"))
        # Pre-compute a darker variant of the foreground for active line numbers.
        self._qc_line_num_active = QColor(self._qc_fg)
        self._qc_line_num_active.darker(120)
        # Pre-compute overlay panel colours (used in _draw_stats and _draw_watermark).
        self._qc_overlay_bg = QColor(0, 0, 0, 140)
        self._qc_stats_accent = self._qcolors.get("keyword", QColor("#ff79c6"))
        self._qc_glyph_shadow = QColor(0, 0, 0, 100)

        # PERF (v1.7): pre-compute keyboard key colours (brushes + pens)
        # so zero QColor objects are allocated per key per frame in
        # _draw_keyboard.  The keyboard can have ~60 keys × 30 fps = 1800
        # QColor allocations per second in the old code.
        self._kb_pressed_brush = self._qcolors.get("keyword", QColor("#ff79c6")).lighter(130)
        self._kb_normal_brush = self._qcolors.get("current_line", QColor("#44475a"))
        self._kb_pressed_pen = self._qcolors.get("background", QColor("#282a36"))
        self._kb_normal_pen = self._qcolors.get("foreground", QColor("#f8f8f2"))

        self._tokenizer: BaseTokenizer = TOKENIZER_MAP.get(language, PythonTokenizer)

        # ── caches (all guarded by _cache_lock) ─────────────────────────
        self._cache_lock = threading.Lock()

        # Static layer: bg gradient/image + window chrome, pre-rendered
        # once into a QPixmap and blitted per frame.
        self._static_layer: Optional[QPixmap] = None
        self._static_layer_dirty: bool = True

        # Per-display_chars precomputation: resolved text, colour array,
        # and is_clean / stack_len tables for O(1) visible_text lookup.
        self._cached_display_chars_id: Optional[int] = None
        self._cached_display_chars_len: int = 0
        self._cached_resolved: str = ""
        self._cached_resolved_colors: List[str] = []
        self._cached_is_clean: List[bool] = []
        self._cached_stack_len: List[int] = []
        self._cached_color_qc: List[QColor] = []
        # Working list built by _tokenize_to_colors, then stored in cache.
        self._color_qc: List[QColor] = []

        # Per-line horizontal layout cache (line_text -> (char_x, total_w)).
        self._line_layout_cache: "OrderedDict[str, Tuple[List[int], int]]" = OrderedDict()

        # Legacy single-shot cache (kept for API compatibility with
        # older callers that used _build_color_map directly).
        self._cached_text: Optional[str] = None
        self._cached_colors: Optional[List[str]] = None

    # ── public API ────────────────────────────────────────────────────
    def set_background_image(self, path: Optional[str]) -> None:
        with self._cache_lock:
            if path and os.path.exists(path):
                self.bg_image = QPixmap(path)
            else:
                self.bg_image = None
            self._static_layer_dirty = True

    def set_watermark_image(self, path: Optional[str]) -> None:
        with self._cache_lock:
            if path and os.path.exists(path):
                self.watermark_image = QPixmap(path)
            else:
                self.watermark_image = None

    def invalidate_cache(self) -> None:
        """Drop all caches. Call when theme / font / size etc. change."""
        with self._cache_lock:
            self._static_layer = None
            self._static_layer_dirty = True
            self._line_layout_cache.clear()
            self._cached_display_chars_id = None
            self._cached_resolved = ""
            self._cached_resolved_colors = []
            self._cached_is_clean = []
            self._cached_stack_len = []
            self._cached_color_qc = []
            self._color_qc = []
            self._cached_text = None
            self._cached_colors = None

    def render_frame(
        self,
        full_text: List[str],
        num_visible: int,
        cursor_visible: bool = True,
        target: Optional[QImage] = None,
    ) -> QImage:
        """Render a single frame.

        If ``target`` is supplied it is drawn into in-place (the caller
        maintains ownership); otherwise a fresh QImage is allocated.
        """
        if target is not None and (target.width() != self.width or target.height() != self.height):
            raise ValueError(
                f"Target QImage size ({target.width()}x{target.height()}) "
                f"must match renderer size ({self.width}x{self.height})"
            )
        img = target if target is not None else QImage(
            self.width, self.height, QImage.Format_RGB32
        )

        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        # Blit the cached static layer (bg + chrome). This covers the
        # whole image, so no prior fill is needed.
        p.drawPixmap(0, 0, self._get_static_layer())

        # ── Resolve visible_text & colours (O(1) fast path) ──────────
        resolved, resolved_colors, color_qc, is_clean, stack_len = self._get_cache(full_text)
        if 0 <= num_visible < len(is_clean) and is_clean[num_visible]:
            vl = stack_len[num_visible]
            visible_text = resolved[:vl]
            char_colors = resolved_colors[:vl]
            vis_color_qc = color_qc[:vl]
        else:
            # Active typo (rare) — fall back to slow resolution.
            visible_text = self._resolve_backspaces(full_text[:num_visible])
            char_colors = self._tokenize_to_colors(visible_text)
            vis_color_qc = self._color_qc

        vis_lines = visible_text.split("\n")
        cursor_line = visible_text.count("\n")
        last_nl = visible_text.rfind("\n")
        cursor_col = len(visible_text) - last_nl - 1 if last_nl >= 0 else len(visible_text)

        chrome = self.title_bar_h if self.show_window_chrome else 0
        area_top = self.padding + chrome
        area_h = self.height - 2 * self.padding - chrome

        # Keyboard geometry is now precomputed in __init__ (PERF v1.5.1).
        kb_panel_w = 0  # extra width consumed by "Right Panel" mode

        if self.show_keyboard:
            if self.keyboard_position == "Below Code":
                area_h -= self._kb_total_h + 30 + self.keyboard_gap
            elif self.keyboard_position == "Right Panel":
                kb_panel_w = int(self._kb_total_w + self.keyboard_gap * 2 + self.padding)

        # Clip code text to the window chrome inner area so long lines
        # don't bleed past the border on narrow resolutions (e.g. 1080×1920).
        # Use the chrome boundaries so line numbers and the current-line
        # highlight are fully preserved.
        if self.show_window_chrome:
            clip_left = self.padding - 14
            clip_right = self.width - self.padding + 14 - kb_panel_w
        else:
            clip_left = 0
            clip_right = self.width - kb_panel_w
        code_clip = QRect(clip_left, area_top, clip_right - clip_left, area_h)
        p.setClipRect(code_clip)

        max_vis = int(max(1, area_h // self.line_h))
        scroll_margin_top = 3
        scroll_margin_bottom = min(5, max_vis - 1)
        first = 0
        if cursor_line >= first + max_vis - scroll_margin_bottom:
            first = max(0, cursor_line - max_vis + scroll_margin_bottom + 1)
        if cursor_line < first + scroll_margin_top:
            first = max(0, cursor_line - scroll_margin_top)

        line_offsets: List[int] = []
        off = 0
        for line in vis_lines:
            line_offsets.append(off)
            off += len(line) + 1

        for i in range(max_vis):
            li = first + i
            if li >= len(vis_lines):
                break
            y = area_top + i * self.line_h

            if li == cursor_line:
                p.fillRect(
                    QRect(self.padding - 12, y, self.width - 2 * self.padding + 24, self.line_h),
                    self._qc_current_line,
                )

            if self.show_line_numbers:
                p.setFont(self._ln_font)
                p.setPen(
                    self._qc_line_num_active
                    if li == cursor_line
                    else self._qc_line_num
                )
                p.drawText(
                    QRect(self.padding, y, self.ln_width, self.line_h),
                    Qt.AlignRight | Qt.AlignVCenter,
                    str(li + 1),
                )

            p.setFont(self.font)
            start_x = self._start_x
            line = vis_lines[li]
            global_off = line_offsets[li]

            if not line:
                if cursor_visible and li == cursor_line:
                    self._draw_caret(p, int(start_x), int(y + 5))
                continue

            # Cached horizontal layout for this line.
            char_x, _ = self._get_line_layout(line)

            # Group consecutive same-color chars into runs.
            # PERF (v1.7): uses the pre-built QColor list (color_qc) with
            # identity comparison (`is` / `is not`) instead of string
            # comparison + dict lookup.  This avoids a dict.get() call
            # per colour run per line per frame.
            cur_qc = vis_color_qc[global_off] if global_off < len(vis_color_qc) else self._qc_fg
            run_start = 0
            for j in range(1, len(line) + 1):
                next_qc = self._qc_fg
                if j < len(line):
                    gp = global_off + j
                    next_qc = vis_color_qc[gp] if gp < len(vis_color_qc) else self._qc_fg
                if j == len(line) or next_qc is not cur_qc:
                    run_text = line[run_start:j].replace("\t", " " * self.tab_size)
                    p.setPen(cur_qc)
                    p.drawText(
                        QPoint(int(char_x[run_start]), int(y + self.line_h * 0.78)),
                        run_text,
                    )
                    cur_qc = next_qc
                    run_start = j

            if cursor_visible and li == cursor_line:
                # Cached layout gives us the x-position of each char on
                # the line. If the cursor sits on an existing char we can
                # look it up directly; if it sits at the end of the line
                # we add the last char's advance to the last position.
                # CLARITY (v1.5.1): the previous version used a nested
                # ternary that was nearly impossible to read; behaviour
                # is unchanged.
                idx = min(cursor_col, len(char_x))
                if idx < len(char_x):
                    cx = char_x[idx]
                else:
                    # Cursor is past the last char — advance one more.
                    last_x = char_x[-1] if char_x else self._start_x
                    if line and line[-1] == "\t":
                        cx = last_x + self._tab_advance
                    elif line:
                        cx = last_x + self._fm.horizontalAdvance(line[-1])
                    else:
                        cx = last_x
                self._draw_caret(p, int(cx), int(y + 5))

        # Remove clip before drawing overlays.
        p.setClipping(False)

        if self.show_keyboard:
            self._draw_keyboard(p, self.pressed_key)

        if self.show_stats and self.animator_ref is not None:
            self._draw_stats(p)

        if self.watermark_image is not None or self.watermark_text:
            self._draw_watermark(p)

        p.end()
        return img

    # ── static layer (bg + chrome) ────────────────────────────────────
    def _get_static_layer(self) -> QPixmap:
        with self._cache_lock:
            if self._static_layer is not None and not self._static_layer_dirty:
                return self._static_layer
            pm = QPixmap(self.width, self.height)
            pm.fill(QColor(self.theme["background"]))
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            p.setRenderHint(QPainter.TextAntialiasing)
            self._draw_bg(p)
            if self.show_window_chrome:
                self._draw_chrome(p)
            p.end()
            self._static_layer = pm
            self._static_layer_dirty = False
            return pm

    # ── per-display_chars cache ───────────────────────────────────────
    def _get_cache(
        self, full_text: List[str]
    ) -> Tuple[str, List[str], List[QColor], List[bool], List[int]]:
        """Return (resolved, resolved_colors, color_qc, is_clean, stack_len).

        Recomputes only when ``full_text`` is a different list object
        than the one currently cached (compared by ``id()``).
        """
        with self._cache_lock:
            if id(full_text) != self._cached_display_chars_id or len(full_text) != self._cached_display_chars_len:
                resolved = self._resolve_backspaces(full_text)
                self._cached_resolved = resolved
                self._cached_resolved_colors = self._tokenize_to_colors(resolved)
                self._cached_color_qc = self._color_qc
                self._cached_is_clean, self._cached_stack_len = self._precompute_clean(
                    full_text, resolved
                )
                self._cached_display_chars_id = id(full_text)
                self._cached_display_chars_len = len(full_text)
            return (
                self._cached_resolved,
                self._cached_resolved_colors,
                self._cached_color_qc,
                self._cached_is_clean,
                self._cached_stack_len,
            )

    @staticmethod
    def _resolve_backspaces(chars: List[str]) -> str:
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
    def _precompute_clean(
        display_chars: List[str], resolved: str
    ) -> Tuple[List[bool], List[int]]:
        """Precompute is_clean[] and stack_len[] tables.

        ``is_clean[i]`` is True iff processing ``display_chars[:i]``
        yields a string that is a prefix of ``resolved`` (i.e. no
        unresolved typo is currently on screen).

        ``stack_len[i]`` is the length of the visible string after
        processing ``display_chars[:i]``.
        """
        n = len(display_chars)
        is_clean: List[bool] = [True] * (n + 1)
        stack_len: List[int] = [0] * (n + 1)
        # Stack of (char, matches_resolved) pairs.
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
            is_clean[i + 1] = incorrect == 0
            stack_len[i + 1] = len(stack)
        return is_clean, stack_len

    def _tokenize_to_colors(self, text: str) -> List[str]:
        """Tokenise ``text`` once and return a per-char colour-key list.

        PERF (v1.6): uses slice assignment instead of per-char inner loop,
        which is ~3x faster for long tokens (strings, comments).
        PERF (v1.7): pre-builds a ``_color_qc_map`` that maps colour keys
        to pre-computed QColors, so the render_frame colour-run loop can
        look up QColors with a single dict.get() instead of two dict lookups.
        """
        tokens = self._tokenizer.tokenize(text)
        colors: List[str] = ["foreground"] * len(text)
        pos = 0
        get = self.TOKEN_COLOR_MAP.get  # local alias avoids dict lookup
        n = len(colors)
        # PERF (v1.7): build the per-char QColor lookup table alongside
        # the string colour keys.  Both lists share the same slice
        # assignments so they stay in sync.  The render loop uses
        # _color_qc with identity comparison for zero per-frame allocs.
        qcolors = self._qcolors
        fg = self._qc_fg
        self._color_qc: List[QColor] = [fg] * n
        for ttype, ttxt in tokens:
            ckey = get(ttype, "foreground")
            qc = qcolors.get(ckey, fg)
            end = pos + len(ttxt)
            if end > n:
                end = n
            colors[pos:end] = [ckey] * (end - pos)
            self._color_qc[pos:end] = [qc] * (end - pos)
            pos = end
        return colors

    # Kept for backward compatibility with older callers.
    def _build_color_map(self, text: str) -> List[str]:
        if text == self._cached_text and self._cached_colors is not None:
            return self._cached_colors
        self._cached_colors = self._tokenize_to_colors(text)
        self._cached_text = text
        return self._cached_colors

    # ── per-line layout cache ─────────────────────────────────────────
    def _get_line_layout(self, line: str) -> Tuple[List[int], int]:
        """Return (char_x_positions, total_width) for ``line``.

        Results are cached by line text; the cache is bounded to
        ``_LINE_CACHE_MAX`` entries with FIFO eviction.

        PERF (v1.6): the common case (cache hit) is now lock-free.
        We read the dict outside the lock; the OrderedDict is only
        mutated under the lock on cache miss.  This avoids acquiring
        the lock for every visible line on every frame — typically
        30–60 lock acquisitions/frame are reduced to 0 on cache hits.
        """
        # Lock-free fast path: read-only dict lookup.
        cached = self._line_layout_cache.get(line)
        if cached is not None:
            # Note: we skip move_to_end() on the fast path for
            # lock safety, which means eviction is still roughly FIFO
            # rather than true LRU. This is fine because the working
            # set of visible lines is typically much smaller than
            # _LINE_CACHE_MAX (512).
            return cached

        # Slow path: acquire lock, re-check, compute, insert.
        with self._cache_lock:
            # Re-check after acquiring lock (another thread may have
            # inserted while we waited).
            cached = self._line_layout_cache.get(line)
            if cached is not None:
                return cached

            char_x: List[int] = []
            x = self._start_x
            tab = self._tab_advance
            ham = self._fm.horizontalAdvance  # local alias
            for ch in line:
                char_x.append(x)
                x += tab if ch == "\t" else ham(ch)
            result = (char_x, x)

            if len(self._line_layout_cache) >= self._LINE_CACHE_MAX:
                self._line_layout_cache.popitem(last=False)  # FIFO evict
            self._line_layout_cache[line] = result
            return result

    # ── drawing primitives ────────────────────────────────────────────
    def _draw_caret(self, p: QPainter, x: int, y: int) -> None:
        w = max(2, self.font_size // 10)
        p.fillRect(x, y, w, self.line_h - 10, self._qc_cursor)

    def _draw_bg(self, p: QPainter) -> None:
        if self.bg_image:
            scaled = self.bg_image.scaled(
                self.width, self.height,
                Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation,
            )
            x = (self.width - scaled.width()) // 2
            y = (self.height - scaled.height()) // 2
            p.drawPixmap(x, y, scaled)
        else:
            g = QLinearGradient(0, 0, 0, self.height)
            bg = self._qcolors.get("background", QColor("#282a36"))
            g.setColorAt(0, bg.lighter(105))
            g.setColorAt(1, bg)
            p.fillRect(0, 0, self.width, self.height, g)

    def _draw_chrome(self, p: QPainter) -> None:
        x = self.padding - 14
        y = self.padding - 14
        w = self.width - 2 * self.padding + 28
        h = self.height - 2 * self.padding + 28

        # Drop shadow
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 60))
        p.drawRoundedRect(x + 4, y + 4, w, h, 12, 12)

        # Window border
        p.setBrush(self._qcolors.get("window_border", QColor("#1e1f29")))
        p.drawRoundedRect(x, y, w, h, 12, 12)

        # Title bar
        tb = self._qcolors.get("title_bar", QColor("#1e1f29"))
        p.setBrush(tb)
        p.drawRoundedRect(x, y, w, self.title_bar_h + 10, 12, 12)
        p.fillRect(x, y + 18, w, self.title_bar_h - 8, tb)

        # Traffic-light buttons
        by = y + 19
        glyphs = {"button_close": "×", "button_min": "−", "button_max": "+"}
        for dx, color_key in [(20, "button_close"), (44, "button_min"), (68, "button_max")]:
            p.setBrush(self._qcolors.get(color_key, QColor("#ff5f57")))
            p.drawEllipse(x + dx, by, 14, 14)
            p.setPen(self._qc_glyph_shadow)
            p.setFont(self._glyph_font)
            p.drawText(QRect(x + dx, by, 14, 14), Qt.AlignCenter, glyphs[color_key])
            p.setPen(Qt.NoPen)

        p.setPen(self._qcolors.get("title_text", QColor("#cccccc")))
        p.setFont(self._title_font)
        p.drawText(QRect(x, y + 10, w, self.title_bar_h), Qt.AlignCenter, self.title_text)

    # ── statistics overlay ────────────────────────────────────────────
    def _draw_stats(self, p: QPainter) -> None:
        """Draw a small stats panel (WPM, keystrokes, accuracy, elapsed).

        PERF (v1.6): font, QFontMetrics, and box dimensions are all
        pre-computed in ``__init__`` — this method only formats the
        four stat strings and draws.  No QFont or QFontMetrics objects
        are allocated per frame.
        """
        stats = self.animator_ref.stats_at(self.current_time)
        lines = [
            f"WPM:   {stats.wpm:6.1f}",
            f"Keys:  {stats.keystrokes:6d}",
            f"Acc:   {stats.accuracy * 100:5.1f}%",
            f"Time:  {self._format_time(stats.elapsed)}",
        ]
        pad = self._stats_pad
        box_w = self._stats_box_w
        box_h = self._stats_box_h

        x, y = self._overlay_origin(box_w, box_h, self.stats_position)

        # Translucent dark panel for readability.
        p.setPen(Qt.NoPen)
        p.setBrush(self._qc_overlay_bg)
        p.drawRoundedRect(x, y, box_w, box_h, 8, 8)

        # Accent left border.
        p.setBrush(self._qc_stats_accent)
        p.drawRoundedRect(x, y, 4, box_h, 2, 2)

        p.setFont(self._stats_font)
        p.setPen(self._qc_fg)
        for i, line in enumerate(lines):
            p.drawText(
                QRect(x + pad + 4, y + pad + i * self._stats_line_h, box_w - 2 * pad, self._stats_line_h),
                Qt.AlignLeft | Qt.AlignVCenter,
                line,
            )

    @staticmethod
    def _format_time(s: float) -> str:
        m = int(s) // 60
        sec = int(s) % 60
        return f"{m:02d}:{sec:02d}"

    # ── watermark overlay ─────────────────────────────────────────────
    def _draw_watermark(self, p: QPainter) -> None:
        """Draw a text and/or image watermark with adjustable opacity.

        PERF (v1.6): font, QFontMetrics, and scaled watermark pixmap are
        pre-computed in ``__init__`` (scaled image recomputed only when
        the source changes).  No per-frame QFont / QFontMetrics /
        QPixmap.scaleToWidth calls.
        """
        text = self.watermark_text.strip()
        fm = self._wm_fm

        # Only recompute the scaled image when the source image changes
        # (detected via set_watermark_image which sets _wm_scaled = None).
        if self.watermark_image is not None and self._wm_scaled is None:
            self._wm_scaled = self.watermark_image.scaledToWidth(
                self._wm_target_w, Qt.SmoothTransformation
            )

        text_w = fm.horizontalAdvance(text) if text else 0
        text_h = fm.height() if text else 0
        img_w = self._wm_scaled.width() if self._wm_scaled else 0
        img_h = self._wm_scaled.height() if self._wm_scaled else 0

        pad = 12
        if img_w > 0 and text_w > 0:
            box_w = max(img_w, text_w) + 2 * pad
            box_h = img_h + text_h + 2 * pad + 6
        elif img_w > 0:
            box_w = img_w + 2 * pad
            box_h = img_h + 2 * pad
        else:
            box_w = text_w + 2 * pad
            box_h = text_h + 2 * pad

        x, y = self._overlay_origin(box_w, box_h, self.watermark_position)

        # Apply opacity to all subsequent draws.
        p.save()
        p.setOpacity(self.watermark_opacity)

        if self._wm_scaled is not None:
            p.drawPixmap(x + (box_w - img_w) // 2, y + pad, self._wm_scaled)

        if text:
            p.setFont(self._wm_font)
            p.setPen(self._qc_fg)
            ty = y + pad + img_h + (6 if img_h > 0 else 0) + fm.ascent()
            p.drawText(x + (box_w - text_w) // 2, ty, text)

        p.restore()

    # ── overlay positioning helper ────────────────────────────────────
    def _overlay_origin(self, box_w: int, box_h: int, position: str) -> Tuple[int, int]:
        """Return (x, y) for an overlay box of the given size at the
        given corner of the frame, with a margin from the edge."""
        margin = 24
        if position == "Top-Left":
            return margin, margin
        if position == "Top-Right":
            return self.width - box_w - margin, margin
        if position == "Bottom-Left":
            return margin, self.height - box_h - margin
        # Default: Bottom-Right
        return self.width - box_w - margin, self.height - box_h - margin

    def _draw_keyboard(self, p: QPainter, pressed_key: Optional[str]) -> None:
        kw = self._kb_key_w
        kh = self._kb_key_h
        km = self._kb_key_margin
        total_w = self._kb_total_w
        total_h = self._kb_total_h
        radius = self.keyboard_radius
        # ── Determine position ──────────────────────────────────────
        if self.keyboard_position == "Right Panel":
            # Vertically centered on the right side.
            panel_x = self.width - int(total_w) - self.padding - self.keyboard_gap
            start_x = panel_x
            start_y = max(
                self.padding + self.title_bar_h,
                (self.height - int(total_h)) // 2,
            )
        elif self.keyboard_position == "Overlay Bottom":
            # Overlaid at the bottom of the code area, semi-transparent.
            start_x = (self.width - int(total_w)) // 2
            start_y = self.height - int(total_h) - self.padding // 2
        else:
            # "Below Code" — classic position below the editor area.
            start_x = (self.width - int(total_w)) // 2
            start_y = self.height - int(total_h) - 30 - self.keyboard_gap

        # ── Apply opacity for overlay mode ──────────────────────────
        if self.keyboard_opacity < 1.0:
            p.save()
            p.setOpacity(self.keyboard_opacity)

        p.setFont(self._kb_font)

        for r, row in enumerate(self._kb_rows):
            row_offset_x = r * int(kw / 2)
            for c, key in enumerate(row):
                w = kw
                label = key.upper()
                current_pressed = pressed_key
                if key == " ":
                    w = kw * 6
                    row_offset_x = int((total_w - w) // 2)
                    if current_pressed == "space":
                        current_pressed = " "

                x = start_x + row_offset_x + c * (kw + km)
                y = start_y + r * (kh + km)

                is_pressed = (current_pressed == key)
                p.setPen(Qt.NoPen)
                # PERF (v1.7): pre-compute keyboard key colours once instead of
                # constructing QColor objects every frame per key.
                if is_pressed:
                    p.setBrush(self._kb_pressed_brush)
                else:
                    p.setBrush(self._kb_normal_brush)
                p.drawRoundedRect(int(x), int(y), int(w), int(kh), radius, radius)

                p.setPen(self._kb_pressed_pen if is_pressed else self._kb_normal_pen)
                p.drawText(QRect(int(x), int(y), int(w), int(kh)), Qt.AlignCenter, label)

        # Restore opacity.
        if self.keyboard_opacity < 1.0:
            p.restore()
