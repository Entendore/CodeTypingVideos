"""
Main application window.

Wires together the editor, settings panel, live preview, timeline
scrubber, and exporter. Provides menu actions and keyboard shortcuts,
and persists user preferences via QSettings.
"""

from __future__ import annotations

import bisect
import json
import logging
import os
import random
import shutil
import tempfile
import time as _time
from typing import List, Optional, Tuple

import numpy as np

from PySide6.QtCore import Qt, QTimer, QUrl, QSettings, QEvent
from PySide6.QtGui import (
    QAction, QColor, QKeySequence, QShortcut, QFont, QFontDatabase, QFontMetrics,
    QPixmap, QImage,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
    QFileDialog, QFrame, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QSizePolicy, QSlider, QSpinBox, QSplitter, QGridLayout, QTabWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from PySide6.QtMultimedia import QSoundEffect

from .config import (
    INPUT_DIR, OUTPUT_DIR, TMP_DIR, SUPPORTED_EXTENSIONS,
    EXT_TO_LANGUAGE, RESOLUTION_PRESETS, THEMES, SETTINGS_ORG, SETTINGS_APP,
    PRESET_DIR, ensure_cwd_dirs, ensure_preset_dir,
    YOUTUBE_SHORT_MAX_DURATION, UI_SPACING, UI_PALETTE,
    ICON_CODE, ICON_SETTINGS, ICON_PREVIEW,
    KB_POSITIONS, KB_DEFAULTS,
)
from .tokenizers import TOKENIZER_MAP
from .sound import TypingSoundGenerator
from .renderer import CodeRenderer, OVERLAY_POSITIONS
from .animator import TypingAnimator
from .exporter import (
    VideoExporter, BatchItem, BatchSettings, BatchExporter,
)
from .widgets import DropTextEdit


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
    '  if (n <= 0) return [];\n'
    '  const sequence = [0, 1];\n'
    '  for (let i = 2; i < n; i++) {\n'
    '    sequence.push(sequence[i - 1] + sequence[i - 2]);\n'
    '  }\n'
    '  return sequence.slice(0, n);\n'
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
    '    if (n <= 0) return { sequence: [], sum: 0 };\n'
    '    const sequence: number[] = [0, 1];\n'
    '    for (let i = 2; i < n; i++) {\n'
    '        sequence.push(sequence[i - 1] + sequence[i - 2]);\n'
    '    }\n'
    '    const result = sequence.slice(0, n);\n'
    '    return { sequence: result, sum: result.reduce((a, b) => a + b, 0) };\n'
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
    '    if (n <= 0) return NULL;\n'
    '    int* seq = (int*)malloc(n * sizeof(int));\n'
    '    if (!seq) return NULL;\n'
    '    if (n >= 1) seq[0] = 0;\n'
    '    if (n >= 2) seq[1] = 1;\n'
    '    for (int i = 2; i < n; i++) {\n'
    '        seq[i] = seq[i - 1] + seq[i - 2];\n'
    '    }\n'
    '    return seq;\n'
    '}\n\n'
    'int main() {\n'
    '    int n = 10;\n'
    '    int* result = fibonacci(n);\n'
    '    for (int i = 0; i < n; i++) {\n'
    '        printf("%d ", result[i]);\n'
    '    }\n'
    '    printf("\\n");\n'
    '    free(result);\n'
    '    return 0;\n'
    '}'
)

# All sample code snippets keyed by language name (matches TOKENIZER_MAP keys).
SAMPLE_CODE: dict[str, str] = {
    "Python": SAMPLE_PY,
    "JavaScript": SAMPLE_JS,
    "TypeScript": SAMPLE_TS,
    "C/C++/Java": SAMPLE_C,
    "Go": SAMPLE_GO,
    "Rust": SAMPLE_RUST,
}

# Extensions grouped by language for filtering.
LANGUAGE_EXTENSIONS: dict[str, list[str]] = {
    "Python": [".py"],
    "JavaScript": [".js", ".jsx"],
    "TypeScript": [".ts", ".tsx"],
    "C/C++/Java": [".java", ".c", ".cpp", ".h", ".hpp", ".cs"],
    "Go": [".go"],
    "Rust": [".rs"],
}

# All extensions that map to a highlighted language.
HIGHLIGHTED_EXTENSIONS: set[str] = set(EXT_TO_LANGUAGE.keys())


# ─────────────────────────────────────────────────────────────────────
# Module-level UI helpers (used by _build_ui)
# ─────────────────────────────────────────────────────────────────────

def _panel_header(icon: str, title: str) -> QWidget:
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


def _form2col() -> QGridLayout:
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

    def _update(v: int) -> None:
        val_lbl.setText(f"{v}{suffix}")

    sl.valueChanged.connect(_update)
    row.addWidget(sl, 1)
    row.addWidget(val_lbl)
    return row, sl, val_lbl


class MainWindow(QMainWindow):
    """Top-level application window."""

    def __init__(self) -> None:
        super().__init__()
        self.logger = logging.getLogger("MainWindow")
        self.setWindowTitle("Code Typing Video Generator")
        self.setMinimumSize(1350, 850)

        ensure_cwd_dirs()
        ensure_preset_dir()

        # State
        self.is_playing = False
        self.animator: Optional[TypingAnimator] = None
        self.renderer: Optional[CodeRenderer] = None
        self.sound_gen = TypingSoundGenerator(profile="Mechanical")
        self.exporter: Optional[VideoExporter] = None
        self._last_vis = 0
        self._play_t0 = 0.0
        self._play_offset = 0.0
        self._current_input_file: Optional[str] = None
        self._sfx_dir: Optional[str] = None
        self._sfx: dict[tuple[str, int], QSoundEffect] = {}
        self._preview_sfx: Optional[QSoundEffect] = None
        self._preview_tmp: Optional[str] = None
        self._scrubbing = False
        # PERF (v1.7): pre-allocate a scratch QImage for live preview so
        # we don't allocate a new ~8 MB image on every preview tick.
        self._preview_scratch: Optional[QImage] = None
        self._bg_image_path: Optional[str] = None
        self._watermark_image_path: Optional[str] = None
        self._settings = QSettings(SETTINGS_ORG, SETTINGS_APP)

        # Timers
        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(16)
        self._preview_timer.timeout.connect(self._tick)
        self._code_debounce = QTimer(self)
        self._code_debounce.setSingleShot(True)
        self._code_debounce.setInterval(400)
        self._code_debounce.timeout.connect(self._static_preview)

        # Build UI
        self._build_ui()
        self._build_menu()
        self._build_shortcuts()
        self._init_sounds()
        self._restore_settings()
        self._refresh_input_files()
        # Defer the first preview render until the widget has been laid
        # out so that preview_lbl.size() returns the real on-screen size
        # rather than a tiny default.  Without this the scaled-down
        # preview pixmap can appear to show only a fraction of the frame.
        self._initial_preview_pending = True
        self.installEventFilter(self)

    def eventFilter(self, obj, event):
        if (
            getattr(self, "_initial_preview_pending", False)
            and event.type() == QEvent.Show
            and obj is self
        ):
            self._initial_preview_pending = False
            self.removeEventFilter(self)
            # Give the layout one more pass before rendering.
            QTimer.singleShot(0, self._static_preview)
        return super().eventFilter(obj, event)

    # ─────────────────────────────────────────────────────────────────
    # Sound
    # ─────────────────────────────────────────────────────────────────
    def _init_sounds(self, profile: str = "Mechanical") -> None:
        if self._sfx_dir and os.path.isdir(self._sfx_dir):
            shutil.rmtree(self._sfx_dir, ignore_errors=True)
        os.makedirs(TMP_DIR, exist_ok=True)
        self._sfx_dir = tempfile.mkdtemp(dir=TMP_DIR, prefix="sfx_")
        self._sfx = {}
        self.sound_gen = TypingSoundGenerator(profile=profile)
        volume = self.snd_vol_sl.value() / 100.0 if hasattr(self, "snd_vol_sl") else 0.5
        # Pre-render WAV files for every sound category so live preview
        # can dispatch to the right one without re-rendering per keystroke.
        # BUG FIX (v1.5.1): previously iterated over SOUND_CATEGORIES
        # (the 11 standard keyboard categories), which meant thematic
        # profiles (Cash Register, Pinball, Telegraph, Arcade, Gunshot,
        # Silenced, Crystal Bowl, Synth Bubble, Tibetan Bowl) had NO
        # preview SFX loaded — their categories are named differently
        # (e.g. "jackpot", "plunger", "dash") and were silently
        # skipped. We now iterate over the actual categories present
        # in ``sound_gen.sounds`` so every profile gets its preview SFX.
        for kind in self.sound_gen.sounds.keys():
            sounds = self.sound_gen.sounds.get(kind)
            if not sounds:
                continue
            for i, snd in enumerate(sounds[:3]):
                path = os.path.join(self._sfx_dir, f"{kind}_{i}.wav")
                self.sound_gen.save_wav(path, snd, volume=volume)
                eff = QSoundEffect(self)
                eff.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
                eff.setVolume(0.8)
                self._sfx[(kind, i)] = eff

    def _play_click(self, ch: str) -> None:
        """Play the matching sound for a typed character (live preview only)."""
        if ch == "\b":
            # Backspace sounds are now synthesised — play them too.
            # Look up the profile-specific backspace category (or the
            # standard "backspace" name for keyboard profiles).
            cmap = self.sound_gen._CATEGORY_MAPS.get(self.sound_gen.profile, {})
            kind = cmap.get("\b", "backspace") if cmap else "backspace"
        else:
            kind = self.sound_gen._category_for(ch)
        # Pick a random variant — clamp to the number we actually pre-rendered.
        n_variants = min(3, len(self.sound_gen.sounds.get(kind, [])))
        if n_variants == 0:
            # Fall back to "key" if the profile doesn't define this category.
            kind = "key"
            n_variants = min(3, len(self.sound_gen.sounds.get(kind, [])))
        if n_variants == 0:
            return
        sfx = self._sfx.get((kind, random.randint(0, n_variants - 1)))
        if sfx:
            sfx.play()

    # ─────────────────────────────────────────────────────────────────
    # Input folder
    # ─────────────────────────────────────────────────────────────────
    def _scan_input_folder(self, lang_filter: str | None = None) -> List[Tuple[str, str]]:
        """Scan input/ folder recursively. If *lang_filter* is set, only return 
        files whose extension belongs to that language. Returns (relative_path, full_path) 
        tuples so subfolder structure is visible."""
        files: List[Tuple[str, str]] = []
        if not os.path.isdir(INPUT_DIR):
            return files
        allowed_exts: set[str] | None = None
        if lang_filter:
            allowed_exts = set(LANGUAGE_EXTENSIONS.get(lang_filter, []))
        
        for dirpath, dirnames, filenames in os.walk(INPUT_DIR):
            # Sort subdirectories and filenames for consistent ordering
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
                # Compute relative path from input/ for display
                rel_path = os.path.relpath(fpath, INPUT_DIR)
                files.append((rel_path, fpath))
        return files

    def _refresh_input_files(self) -> None:
        lang_filter = self.lang_filter_cb.currentData()
        self.input_file_cb.blockSignals(True)
        current_data = self.input_file_cb.currentData()
        self.input_file_cb.clear()
        self.input_file_cb.addItem("\u2014 Select file from input/ \u2014", None)
        files = self._scan_input_folder(lang_filter=lang_filter)
        selected_idx = 0
        for i, (rel_path, fpath) in enumerate(files):
            # Show filename with subfolder path for clarity
            # For top-level files, just show filename; for nested, show relative path
            display = rel_path
            size_kb = os.path.getsize(fpath) / 1024
            label = f"{display}  ({size_kb:.1f} KB)"
            self.input_file_cb.addItem(label, fpath)
            if fpath == current_data:
                selected_idx = i + 1
        if files:
            self.input_file_cb.setCurrentIndex(selected_idx)
        self.input_file_cb.blockSignals(False)
        filter_tag = f" [{lang_filter}]" if lang_filter else ""
        folder_count = len(set(os.path.dirname(p) for _, p in files)) if files else 0
        subfolder_note = f" ({folder_count} subfolder{'s' if folder_count != 1 else ''})" if folder_count > 1 else ""
        self.statusBar().showMessage(f"input/{filter_tag} \u2014 {len(files)} file(s){subfolder_note}")

    def _on_lang_filter_changed(self, index: int) -> None:
        self._refresh_input_files()

    def _on_sample_selected(self, index: int) -> None:
        lang_name = self.sample_cb.currentData()
        if not lang_name or lang_name not in SAMPLE_CODE:
            return
        self.editor.setPlainText(SAMPLE_CODE[lang_name])
        self._current_input_file = None
        self.lang_cb.setCurrentText(lang_name)
        self.sample_cb.blockSignals(True)
        self.sample_cb.setCurrentIndex(0)
        self.sample_cb.blockSignals(False)
        self.statusBar().showMessage(f"Loaded {lang_name} sample")

    def _auto_detect_language(self, fpath: str) -> None:
        """Set the language dropdown based on the file extension."""
        ext = os.path.splitext(fpath)[1].lower()
        lang = EXT_TO_LANGUAGE.get(ext)
        if lang and lang in TOKENIZER_MAP:
            self.lang_cb.setCurrentText(lang)

    def _on_input_file_selected(self, index: int) -> None:
        fpath = self.input_file_cb.itemData(index)
        if not fpath or not os.path.isfile(fpath):
            return
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            self.editor.setPlainText(content)
            self._current_input_file = fpath
            # Use just the filename for the title bar (not subfolder path)
            fname = os.path.basename(fpath)
            self.title_edit.setText(f"{fname} \u2014 Code Editor")
            self._auto_detect_language(fpath)
            # Show full relative path in status bar
            rel_path = os.path.relpath(fpath, INPUT_DIR) if fpath.startswith(INPUT_DIR) else fname
            self.statusBar().showMessage(f"Loaded: {rel_path}")
        except Exception as e:
            QMessageBox.warning(self, "Load Error", f"Could not read file:\n{e}")

    def _on_file_dropped(self, fpath: str) -> None:
        ext = os.path.splitext(fpath)[1].lower()
        if ext in SUPPORTED_EXTENSIONS:
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                self.editor.setPlainText(content)
                self._current_input_file = fpath
                self.title_edit.setText(f"{os.path.basename(fpath)} \u2014 Code Editor")
                self._auto_detect_language(fpath)
                self.statusBar().showMessage(f"Dropped: {os.path.basename(fpath)}")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not read dropped file:\n{e}")

    def _save_to_input(self) -> None:
        code = self.editor.toPlainText()
        if not code.strip():
            return
        name, ok = QInputDialog.getText(self, "Save to input/", "Filename:", text="snippet.py")
        if not ok or not name.strip():
            return
        name = name.strip()
        if not os.path.splitext(name)[1]:
            name += ".py"
        fpath = os.path.join(INPUT_DIR, name)
        if os.path.exists(fpath):
            if QMessageBox.question(self, "Overwrite?", f"'{name}' already exists. Overwrite?") != QMessageBox.Yes:
                return
        try:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(code)
            self._current_input_file = fpath
            self._refresh_input_files()
        except Exception as e:
            QMessageBox.warning(self, "Save Error", f"Could not save file:\n{e}")

    # ─────────────────────────────────────────────────────────────────
    # Background image
    # ─────────────────────────────────────────────────────────────────
    def _select_bg_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Background Image", "",
            "Images (*.png *.jpg *.jpeg *.bmp)",
        )
        if path:
            self._bg_image_path = path
            self._static_preview()

    def _clear_bg_image(self) -> None:
        self._bg_image_path = None
        self._static_preview()

    # ─────────────────────────────────────────────────────────────────
    # Watermark image
    # ─────────────────────────────────────────────────────────────────
    def _select_watermark_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Watermark Image", "",
            "Images (*.png *.jpg *.jpeg *.bmp)",
        )
        if path:
            self._watermark_image_path = path
            self._static_preview()

    def _clear_watermark_image(self) -> None:
        self._watermark_image_path = None
        self._static_preview()

    # ─────────────────────────────────────────────────────────────────
    # PNG snapshot
    # ─────────────────────────────────────────────────────────────────
    def _save_snapshot(self) -> None:
        """Save the current preview frame as a PNG to output/."""
        if not self.renderer or not self.animator:
            QMessageBox.information(self, "Snapshot", "Nothing to snapshot yet.")
            return
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        if self._current_input_file:
            base = os.path.splitext(os.path.basename(self._current_input_file))[0]
        else:
            base = "code_typing"
        # Use the current scrubber position so users can snapshot any frame.
        t = (self.timeline_slider.value() / 1000.0) * self.animator.duration()
        path = os.path.join(OUTPUT_DIR, f"{base}_snapshot_{int(t * 1000):06d}ms.png")
        # BUG FIX: previously called _render_at(t) then immediately called
        # render_frame() again — double-rendering. Also, the first
        # _render_at already sets renderer.current_time and pressed_key.
        # Now we just call _render_at once and use its result.
        qimg = self._render_at(t)
        if qimg is None:
            return
        if qimg.save(path, "PNG"):
            self.statusBar().showMessage(f"Snapshot saved: {path}")
        else:
            QMessageBox.warning(self, "Snapshot Error", f"Could not save PNG to:\n{path}")

    # ─────────────────────────────────────────────────────────────────
    # Preset save / load / delete (JSON files in presets/)
    # ─────────────────────────────────────────────────────────────────
    # Keys persisted in a preset file. Matches the QSettings keys plus
    # the new overlay/ramp/hw/srt toggles.
    PRESET_KEYS = [
        "theme", "font", "font_size", "tab_size", "title", "line_numbers",
        "window_chrome", "language", "resolution", "show_keyboard",
        "keyboard_gap", "keyboard_scale", "keyboard_layout",
        "keyboard_position", "keyboard_opacity", "keyboard_radius", "padding",
        "wpm", "typo_rate", "start_pause", "end_pause",
        "sound_profile", "sound_volume", "format", "fps", "crf",
        "speed_ramp", "ramp_strength",
        "burst_typing", "thinking_pauses", "fatigue",
        "show_stats", "stats_position",
        "watermark_text", "watermark_position", "watermark_opacity",
        "use_hw_accel", "export_srt",
        "yt_title", "yt_description",
        "autofit_font", "max_lines",
    ]

    def _collect_preset(self) -> dict:
        """Read all preset-able settings from the UI into a dict."""
        return {
            "theme": self.theme_cb.currentText(),
            "font": self._current_font_family,
            "font_size": self.size_sp.value(),
            "tab_size": self.tab_sp.value(),
            "title": self.title_edit.text(),
            "line_numbers": self.ln_chk.isChecked(),
            "window_chrome": self.chrome_chk.isChecked(),
            "language": self.lang_cb.currentText(),
            "resolution": self.res_cb.currentText(),
            "show_keyboard": self.kb_chk.isChecked(),
            "keyboard_gap": self.kb_gap_sl.value(),
            "keyboard_scale": self.kb_scale_sl.value(),
            "keyboard_layout": self.kb_layout_cb.currentText(),
            "keyboard_position": self.kb_pos_cb.currentText(),
            "keyboard_opacity": self.kb_opacity_sl.value(),
            "keyboard_radius": self.kb_radius_sp.value(),
            "padding": self.padding_sp.value(),
            "wpm": self.wpm_sp.value(),
            "typo_rate": self.typo_sp.value(),
            "start_pause": self.start_pause_sp.value(),
            "end_pause": self.end_pause_sp.value(),
            "sound_profile": self.snd_profile_cb.currentText(),
            "sound_volume": self.snd_vol_sl.value(),
            "format": self.format_cb.currentText(),
            "fps": self.fps_sp.value(),
            "crf": self.crf_sp.value(),
            "speed_ramp": self.ramp_cb.currentText(),
            "ramp_strength": self.ramp_strength_sl.value(),
            "burst_typing": self.burst_chk.isChecked(),
            "thinking_pauses": self.thinking_chk.isChecked(),
            "fatigue": self.fatigue_sl.value(),
            "show_stats": self.stats_chk.isChecked(),
            "stats_position": self.stats_pos_cb.currentText(),
            "watermark_text": self.watermark_edit.text(),
            "watermark_position": self.wm_pos_cb.currentText(),
            "watermark_opacity": self.wm_opacity_sl.value(),
            "use_hw_accel": self.hw_chk.isChecked(),
            "export_srt": self.srt_chk.isChecked(),
            "yt_title": self.yt_title_edit.text(),
            "yt_description": self.yt_desc_edit.text(),
        }

    def _apply_preset(self, data: dict) -> None:
        """Apply a preset dict back to the UI."""
        _widgets = [
            self.theme_cb, self.font_cb, self.size_sp, self.tab_sp,
            self.title_edit, self.ln_chk, self.chrome_chk, self.lang_cb,
            self.res_cb, self.kb_chk, self.kb_gap_sl, self.kb_scale_sl,
            self.kb_layout_cb, self.kb_pos_cb, self.kb_opacity_sl,
            self.kb_radius_sp, self.padding_sp, self.wpm_sp, self.typo_sp,
            self.start_pause_sp, self.end_pause_sp, self.snd_profile_cb,
            self.snd_vol_sl, self.format_cb, self.fps_sp, self.crf_sp,
            self.ramp_cb, self.ramp_strength_sl, self.burst_chk,
            self.thinking_chk, self.fatigue_sl, self.stats_chk,
            self.stats_pos_cb, self.watermark_edit, self.wm_pos_cb,
            self.wm_opacity_sl, self.hw_chk, self.srt_chk,
            self.yt_title_edit, self.yt_desc_edit, self.autofit_chk,
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
                # BUG FIX: was int() which truncated floats like 1.0 to 1
                # (the slider is 30-200, so 1.0 from a preset looked broken).
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
                # BUG FIX: was int() which truncated 0.5 to 0 (slider is 0-100).
                self.ramp_strength_sl.setValue(int(float(data["ramp_strength"])))
            if "burst_typing" in data:
                self.burst_chk.setChecked(bool(data["burst_typing"]))
            if "thinking_pauses" in data:
                self.thinking_chk.setChecked(bool(data["thinking_pauses"]))
            if "fatigue" in data:
                # BUG FIX: was int() which truncated 0.0 to 0 (already correct
                # for 0, but float values like 0.3 would truncate to 0).
                self.fatigue_sl.setValue(int(float(data["fatigue"])))
            if "show_stats" in data:
                self.stats_chk.setChecked(bool(data["show_stats"]))
            if "stats_position" in data:
                self.stats_pos_cb.setCurrentText(data["stats_position"])
            if "watermark_text" in data:
                self.watermark_edit.setText(data["watermark_text"])
            if "watermark_position" in data:
                self.wm_pos_cb.setCurrentText(data["watermark_position"])
            if "watermark_opacity" in data:
                # BUG FIX: was int() which truncated 0.4 to 0 (slider is 5-100).
                self.wm_opacity_sl.setValue(int(float(data["watermark_opacity"])))
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
        # Re-init sounds if profile changed (must happen unblocked).
        if "sound_profile" in data:
            self._init_sounds(data["sound_profile"])
        self._static_preview()

    @staticmethod
    def _list_presets() -> list[str]:
        """Return the names of all preset files in presets/ (without extension)."""
        if not os.path.isdir(PRESET_DIR):
            return []
        return sorted(
            os.path.splitext(f)[0]
            for f in os.listdir(PRESET_DIR)
            if f.endswith(".json")
        )

    def _save_preset(self) -> None:
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        path = os.path.join(PRESET_DIR, f"{name}.json")
        if os.path.exists(path):
            if QMessageBox.question(
                self, "Overwrite?", f"Preset '{name}' exists. Overwrite?"
            ) != QMessageBox.Yes:
                return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._collect_preset(), f, indent=2)
            self.statusBar().showMessage(f"Preset saved: {name}")
        except Exception as e:
            QMessageBox.warning(self, "Preset Error", f"Could not save preset:\n{e}")

    def _load_preset(self) -> None:
        presets = self._list_presets()
        if not presets:
            QMessageBox.information(self, "Load Preset", "No presets found in presets/.")
            return
        name, ok = QInputDialog.getItem(
            self, "Load Preset", "Choose a preset:", presets, 0, False
        )
        if not ok or not name:
            return
        path = os.path.join(PRESET_DIR, f"{name}.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._apply_preset(data)
            self.statusBar().showMessage(f"Preset loaded: {name}")
        except Exception as e:
            QMessageBox.warning(self, "Preset Error", f"Could not load preset:\n{e}")

    def _delete_preset(self) -> None:
        presets = self._list_presets()
        if not presets:
            QMessageBox.information(self, "Delete Preset", "No presets found in presets/.")
            return
        name, ok = QInputDialog.getItem(
            self, "Delete Preset", "Choose a preset to delete:", presets, 0, False
        )
        if not ok or not name:
            return
        if QMessageBox.question(
            self, "Confirm Delete", f"Delete preset '{name}'?"
        ) != QMessageBox.Yes:
            return
        path = os.path.join(PRESET_DIR, f"{name}.json")
        try:
            os.remove(path)
            self.statusBar().showMessage(f"Preset deleted: {name}")
        except Exception as e:
            QMessageBox.warning(self, "Preset Error", f"Could not delete preset:\n{e}")

    # ─────────────────────────────────────────────────────────────────
    # Output path
    # ─────────────────────────────────────────────────────────────────
    def _get_auto_output_path(self) -> str:
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
            # Use a distinctive suffix so Shorts are easy to find.
            ext = "_short.mp4"
        elif "YouTube" in fmt:
            ext = "_yt.mp4"
        else:
            ext = ".mp4"

        output_path = os.path.join(OUTPUT_DIR, f"{base}{ext}")
        if os.path.exists(output_path):
            counter = 2
            while os.path.exists(os.path.join(OUTPUT_DIR, f"{base}_{counter}{ext}")):
                counter += 1
            output_path = os.path.join(OUTPUT_DIR, f"{base}_{counter}{ext}")
        return output_path

    # ─────────────────────────────────────────────────────────────────
    # UI helpers
    # ─────────────────────────────────────────────────────────────────
    @staticmethod
    def _vsep() -> QFrame:
        """Return a thin vertical separator line."""
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        sep.setFixedWidth(1)
        return sep

    @staticmethod
    def _hsep() -> QFrame:
        """Return a thin horizontal separator line."""
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        sep.setFixedHeight(1)
        return sep

    # ─────────────────────────────────────────────────────────────────
    # UI construction
    # ─────────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        """Build the main window layout.

        Main window: toolbar + Code editor (left) + Preview (right).
        Settings: a popup QDialog opened from the toolbar's "Settings"
        button. The dialog has 6 tabs (Theme / Editor / Keyboard /
        Timing / Overlay / Export) and standard OK / Apply / Close
        buttons at the bottom.
        """
        s = UI_SPACING
        p = UI_PALETTE

        cw = QWidget()
        self.setCentralWidget(cw)
        root = QVBoxLayout(cw)
        root.setSpacing(0)
        root.setContentsMargins(s["lg"], s["lg"], s["lg"], 0)

        toolbar = QFrame()
        toolbar.setObjectName("toolbar")
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(s["sm"])

        # Initial label uses ASCII ">" instead of the ▶ (\u25b6) glyph so
        # the button renders identically on every platform — the same
        # convention used by _play() / _pause() when toggling state.
        self.play_btn = QPushButton(">  Play")
        self.play_btn.setObjectName("playBtn")
        self.play_btn.setFixedSize(110, s["control_h_lg"])
        self.play_btn.clicked.connect(self._toggle_play)
        tl.addWidget(self.play_btn)

        self.snapshot_btn = QPushButton("Snapshot")
        self.snapshot_btn.clicked.connect(self._save_snapshot)
        tl.addWidget(self.snapshot_btn)

        self.batch_btn = QPushButton("Batch Render...")
        self.batch_btn.setToolTip(
            "Open the batch render dialog to export multiple code "
            "files in one go."
        )
        self.batch_btn.clicked.connect(self._open_batch_dialog)
        tl.addWidget(self.batch_btn)

        tl.addWidget(self._vsep())
        tl.addStretch()

        # Plain "Settings" label (no gear glyph) for cross-platform
        # rendering consistency.
        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self._show_settings_window)
        tl.addWidget(settings_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("dangerBtn")
        self.cancel_btn.clicked.connect(self._cancel_export)
        self.cancel_btn.setEnabled(False)
        tl.addWidget(self.cancel_btn)

        self.export_btn = QPushButton("Export Video")
        self.export_btn.setObjectName("primaryBtn")
        self.export_btn.clicked.connect(self._start_export)
        tl.addWidget(self.export_btn)

        root.addWidget(toolbar)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(3)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setObjectName("toolbarProgress")
        root.addWidget(self.progress_bar)

        self._horiz_splitter = QSplitter(Qt.Horizontal)
        self._horiz_splitter.setHandleWidth(1)
        self._horiz_splitter.setChildrenCollapsible(False)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(s["sm"])
        ll.addWidget(_panel_header(ICON_CODE, "CODE INPUT"))

        left_body = QWidget()
        left_body.setObjectName("panelBody")
        el = QVBoxLayout(left_body)
        el.setContentsMargins(s["lg"], s["md"], s["lg"], s["lg"])
        el.setSpacing(s["sm"])

        file_row = QHBoxLayout()
        file_row.setSpacing(s["xs"])
        fl = QLabel("Filter:")
        fl.setStyleSheet(f"color: {p['text_dim']}; font-size: 12px; font-weight: 500;")
        file_row.addWidget(fl)

        self.lang_filter_cb = QComboBox()
        self.lang_filter_cb.setFixedWidth(140)
        self.lang_filter_cb.addItem("All Files", None)
        for ln in TOKENIZER_MAP:
            self.lang_filter_cb.addItem(ln, ln)
        self.lang_filter_cb.currentIndexChanged.connect(self._on_lang_filter_changed)
        file_row.addWidget(self.lang_filter_cb)

        il = QLabel("input/:")
        il.setStyleSheet(f"color: {p['text_dim']}; font-size: 12px; font-weight: 500;")
        file_row.addWidget(il)

        self.input_file_cb = QComboBox()
        self.input_file_cb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.input_file_cb.currentIndexChanged.connect(self._on_input_file_selected)
        file_row.addWidget(self.input_file_cb, 1)

        rb = QPushButton("Refresh")
        rb.setFixedWidth(64)
        rb.clicked.connect(self._refresh_input_files)
        file_row.addWidget(rb)
        sb = QPushButton("Save")
        sb.clicked.connect(self._save_to_input)
        file_row.addWidget(sb)
        bb = QPushButton("Open...")
        bb.setFixedWidth(72)
        bb.clicked.connect(self._load_file)
        file_row.addWidget(bb)
        el.addLayout(file_row)

        sample_row = QHBoxLayout()
        sample_row.setSpacing(s["xs"])
        sl2 = QLabel("Sample:")
        sl2.setStyleSheet(f"color: {p['text_dim']}; font-size: 12px; font-weight: 500;")
        sample_row.addWidget(sl2)

        self.sample_cb = QComboBox()
        self.sample_cb.setFixedWidth(200)
        self.sample_cb.addItem("\u2014 Load a sample \u2026", None)
        for ln in TOKENIZER_MAP:
            self.sample_cb.addItem(ln, ln)
        self.sample_cb.currentIndexChanged.connect(self._on_sample_selected)
        sample_row.addWidget(self.sample_cb)
        sample_row.addStretch()
        el.addLayout(sample_row)

        self.editor = DropTextEdit()
        self.editor.setObjectName("codeEditor")
        self.editor.setFont(QFont("Consolas", 11))
        self.editor.setPlainText(SAMPLE_PY)
        self.editor.setAcceptRichText(False)
        self.editor.files_dropped.connect(self._on_file_dropped)
        self.editor.textChanged.connect(self._on_code_changed)
        el.addWidget(self.editor, 1)

        ll.addWidget(left_body, 1)
        self._horiz_splitter.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(s["sm"])
        rl.addWidget(_panel_header(ICON_PREVIEW, "PREVIEW"))

        right_body = QWidget()
        right_body.setObjectName("panelBody")
        rbl = QVBoxLayout(right_body)
        rbl.setContentsMargins(s["lg"], s["md"], s["lg"], s["lg"])
        rbl.setSpacing(s["sm"])

        preview_frame = QFrame()
        preview_frame.setObjectName("previewFrame")
        pfl = QVBoxLayout(preview_frame)
        pfl.setContentsMargins(s["md"], s["md"], s["md"], s["md"])
        pfl.setSpacing(0)

        self.preview_lbl = QLabel("Preview")
        self.preview_lbl.setAlignment(Qt.AlignCenter)
        self.preview_lbl.setObjectName("previewPlaceholder")
        self.preview_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        pfl.addWidget(self.preview_lbl)
        rbl.addWidget(preview_frame, 1)

        transport = QHBoxLayout()
        transport.setSpacing(s["sm"])
        self.time_current_lbl = QLabel("00:00")
        self.time_current_lbl.setObjectName("timeLabel")
        self.time_current_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.timeline_slider = QSlider(Qt.Horizontal)
        self.timeline_slider.setObjectName("timelineSlider")
        self.timeline_slider.setRange(0, 1000)
        self.timeline_slider.sliderMoved.connect(self._on_timeline_scrub)
        self.timeline_slider.sliderPressed.connect(self._on_timeline_pressed)
        self.timeline_slider.sliderReleased.connect(self._on_timeline_released)
        self.time_total_lbl = QLabel("00:00")
        self.time_total_lbl.setObjectName("timeLabel")
        self.time_total_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        transport.addWidget(self.time_current_lbl)
        transport.addWidget(self.timeline_slider, 1)
        transport.addWidget(self.time_total_lbl)
        rbl.addLayout(transport)

        rl.addWidget(right_body, 1)
        self._horiz_splitter.addWidget(right)

        self._horiz_splitter.setStretchFactor(0, 2)
        self._horiz_splitter.setStretchFactor(1, 3)
        self._horiz_splitter.setSizes([450, 700])
        root.addWidget(self._horiz_splitter)

        self._status_res_lbl = QLabel("1920x1080")
        self._status_res_lbl.setObjectName("statusPermanent")
        self.statusBar().addPermanentWidget(self._status_res_lbl)
        self._status_font_lbl = QLabel("22px")
        self._status_font_lbl.setObjectName("statusPermanent")
        self.statusBar().addPermanentWidget(self._status_font_lbl)
        self._status_lang_lbl = QLabel("Python")
        self._status_lang_lbl.setObjectName("statusPermanent")
        self.statusBar().addPermanentWidget(self._status_lang_lbl)
        self._status_dur_lbl = QLabel("00:00")
        self._status_dur_lbl.setObjectName("statusPermanent")
        self.statusBar().addPermanentWidget(self._status_dur_lbl)

        # ── Settings dialog ─────────────────────────────────────────
        # The settings live in a popup QDialog opened from the toolbar's
        # "Settings" button. The dialog is modeless (non-modal) so the
        # live preview keeps updating as the user tweaks settings.
        # Standard OK / Apply / Close buttons sit at the bottom.
        self._settings_win = QDialog(self)
        self._settings_win.setWindowTitle("Settings")
        self._settings_win.resize(560, 680)
        self._settings_win.setMinimumSize(440, 520)
        # Don't delete on close — we reuse the same dialog instance.
        self._settings_win.setAttribute(Qt.WA_DeleteOnClose, False)

        sw_root = QVBoxLayout(self._settings_win)
        sw_root.setContentsMargins(s["lg"], s["lg"], s["lg"], s["lg"])
        sw_root.setSpacing(s["md"])

        sw_root.addWidget(_panel_header(ICON_SETTINGS, "SETTINGS"))

        self.settings_tabs = QTabWidget()
        self.settings_tabs.setDocumentMode(True)

        # ================= TAB 1: Theme ============================
        theme_tab = QWidget()
        thl = QVBoxLayout(theme_tab)
        thl.setContentsMargins(s["md"], s["lg"], s["md"], s["lg"])
        thl.setSpacing(s["sm"])
        tg = _form2col()

        r = 0
        tg.addWidget(QLabel("Theme:"), r, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.theme_cb = QComboBox()
        self.theme_cb.addItems(THEMES.keys())
        self.theme_cb.currentTextChanged.connect(self._on_setting_changed)
        tg.addWidget(self.theme_cb, r, 1)

        tg.addWidget(QLabel("Font:"), r, 2, Qt.AlignRight | Qt.AlignVCenter)
        self.font_cb = QComboBox()
        self.font_cb.setEditable(True)
        self.font_cb.setInsertPolicy(QComboBox.NoInsert)
        self._populate_font_list("All Scripts")
        self.font_cb.setCurrentText("Consolas")
        self.font_cb.currentTextChanged.connect(self._on_setting_changed)
        tg.addWidget(self.font_cb, r, 3)

        r += 1
        tg.addWidget(QLabel("Resolution:"), r, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.res_cb = QComboBox()
        self.res_cb.addItems(RESOLUTION_PRESETS.keys())
        self.res_cb.currentTextChanged.connect(self._on_resolution_changed)
        tg.addWidget(self.res_cb, r, 1)

        tg.addWidget(QLabel("Language:"), r, 2, Qt.AlignRight | Qt.AlignVCenter)
        self.lang_cb = QComboBox()
        self.lang_cb.addItems(list(TOKENIZER_MAP.keys()))
        self.lang_cb.currentTextChanged.connect(self._on_setting_changed)
        tg.addWidget(self.lang_cb, r, 3)

        r += 1
        tg.addWidget(QLabel("Font Script:"), r, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.font_script_cb = QComboBox()
        self.font_script_cb.addItems([
            "All Scripts", "Latin / Western",
            "CJK (Chinese, Japanese, Korean)",
            "Arabic / Persian / Urdu",
            "Devanagari (Hindi, Sanskrit)",
            "Cyrillic (Russian, Ukrainian)", "Thai", "Hebrew",
            "Georgian", "Armenian", "Ethiopic", "Tibetan",
            "Monospace Only",
        ])
        self.font_script_cb.setCurrentText("All Scripts")
        self.font_script_cb.currentTextChanged.connect(self._on_font_script_changed)
        tg.addWidget(self.font_script_cb, r, 1, 1, 3)

        r += 1
        tg.addWidget(QLabel("Background:"), r, 0, Qt.AlignRight | Qt.AlignVCenter)
        bg_row = QHBoxLayout()
        bg_row.setSpacing(s["xs"])
        self.bg_btn = QPushButton("BG Image")
        self.bg_btn.clicked.connect(self._select_bg_image)
        self.bg_clear_btn = QPushButton("Clear")
        self.bg_clear_btn.setFixedWidth(60)
        self.bg_clear_btn.clicked.connect(self._clear_bg_image)
        bg_row.addWidget(self.bg_btn)
        bg_row.addWidget(self.bg_clear_btn)
        bg_row.addStretch()
        tg.addLayout(bg_row, r, 1, 1, 3)

        thl.addLayout(tg)
        thl.addStretch()
        self.settings_tabs.addTab(theme_tab, "Theme")

        # ================= TAB 2: Editor ===========================
        editor_tab = QWidget()
        edl = QVBoxLayout(editor_tab)
        edl.setContentsMargins(s["md"], s["lg"], s["md"], s["lg"])
        edl.setSpacing(s["sm"])

        self.autofit_chk = QCheckBox("Auto-fit Font Size")
        self.autofit_chk.setChecked(True)
        self.autofit_chk.setToolTip(
            "Automatically calculate the largest font size that fits "
            "the code in the chosen resolution. "
            "Uncheck to set font size manually."
        )
        self.autofit_chk.toggled.connect(self._on_autofit_toggled)
        edl.addWidget(self.autofit_chk)

        eg = _form2col()
        r = 0
        self._visible_lines_label = QLabel("Visible Lines:")
        eg.addWidget(self._visible_lines_label, r, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.max_lines_sp = QSpinBox()
        self.max_lines_sp.setRange(0, 200)
        self.max_lines_sp.setValue(0)
        self.max_lines_sp.setSpecialValueText("All")
        self.max_lines_sp.setToolTip(
            "0 = fit all code lines.  Set a number to show exactly "
            "that many lines (font scales to fill editor)."
        )
        self.max_lines_sp.valueChanged.connect(self._on_setting_changed)
        eg.addWidget(self.max_lines_sp, r, 1)

        eg.addWidget(QLabel("Font Size:"), r, 2, Qt.AlignRight | Qt.AlignVCenter)
        self.size_sp = QSpinBox()
        self.size_sp.setRange(8, 72)
        self.size_sp.setValue(22)
        self.size_sp.setSuffix(" px")
        self.size_sp.setSingleStep(2)
        self.size_sp.setToolTip(
            "Manual font size (px). Use arrow keys Up/Down.\n"
            "Only active when Auto-fit is unchecked."
        )
        self.size_sp.valueChanged.connect(self._on_setting_changed)
        self.size_sp.setEnabled(False)
        eg.addWidget(self.size_sp, r, 3)

        r += 1
        eg.addWidget(QLabel("Tab Size:"), r, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.tab_sp = QSpinBox()
        self.tab_sp.setRange(2, 8)
        self.tab_sp.setValue(4)
        self.tab_sp.valueChanged.connect(self._on_setting_changed)
        eg.addWidget(self.tab_sp, r, 1)

        eg.addWidget(QLabel("Padding:"), r, 2, Qt.AlignRight | Qt.AlignVCenter)
        self.padding_sp = QSpinBox()
        self.padding_sp.setRange(0, 100)
        self.padding_sp.setValue(50)
        self.padding_sp.setSuffix(" px")
        self.padding_sp.setToolTip("Padding (px) around the code block.")
        self.padding_sp.valueChanged.connect(self._on_setting_changed)
        eg.addWidget(self.padding_sp, r, 3)

        r += 1
        eg.addWidget(QLabel("Title:"), r, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.title_edit = QLineEdit("main.py \u2014 Code Editor")
        self.title_edit.textChanged.connect(self._on_setting_changed)
        eg.addWidget(self.title_edit, r, 1, 1, 3)

        r += 1
        chk_row = QHBoxLayout()
        chk_row.setSpacing(s["xl"])
        self.ln_chk = QCheckBox("Line Numbers")
        self.ln_chk.setChecked(True)
        self.ln_chk.toggled.connect(self._on_setting_changed)
        chk_row.addWidget(self.ln_chk)
        self.chrome_chk = QCheckBox("Window Chrome")
        self.chrome_chk.setChecked(True)
        self.chrome_chk.toggled.connect(self._on_setting_changed)
        chk_row.addWidget(self.chrome_chk)
        chk_row.addStretch()
        eg.addLayout(chk_row, r, 0, 1, 4)

        edl.addLayout(eg)
        edl.addStretch()
        self.settings_tabs.addTab(editor_tab, "Editor")

        # ================= TAB 3: Keyboard =========================
        kb_tab = QWidget()
        kbl = QVBoxLayout(kb_tab)
        kbl.setContentsMargins(s["md"], s["lg"], s["md"], s["lg"])
        kbl.setSpacing(s["sm"])

        self.kb_chk = QCheckBox("Show Keyboard")
        self.kb_chk.toggled.connect(self._on_kb_toggled)
        kbl.addWidget(self.kb_chk)

        kbg = _form2col()
        r = 0
        kbg.addWidget(QLabel("Layout:"), r, 0, Qt.AlignRight | Qt.AlignVCenter)
        from .config import KEYBOARD_LAYOUTS
        self.kb_layout_cb = QComboBox()
        self.kb_layout_cb.addItems(KEYBOARD_LAYOUTS.keys())
        self.kb_layout_cb.setToolTip("Choose the keyboard layout shown in the overlay.")
        self.kb_layout_cb.currentTextChanged.connect(self._on_setting_changed)
        kbg.addWidget(self.kb_layout_cb, r, 1)

        kbg.addWidget(QLabel("Position:"), r, 2, Qt.AlignRight | Qt.AlignVCenter)
        self.kb_pos_cb = QComboBox()
        self.kb_pos_cb.addItems(KB_POSITIONS)
        self.kb_pos_cb.setToolTip(
            "Below Code: keyboard under the editor (16:9).\n"
            "Overlay Bottom: semi-transparent over code (1:1).\n"
            "Right Panel: keyboard on the right (9:16 vertical)."
        )
        self.kb_pos_cb.currentTextChanged.connect(self._on_kb_pos_changed)
        kbg.addWidget(self.kb_pos_cb, r, 3)

        r += 1
        kbg.addWidget(QLabel("Gap:"), r, 0, Qt.AlignRight | Qt.AlignVCenter)
        gap_row, self.kb_gap_sl, self.kb_gap_val = _slider_row(
            "Gap", 0, 400, 20, " px", "Spacing between code and keyboard.")
        self.kb_gap_sl.valueChanged.connect(self._on_setting_changed)
        kbg.addLayout(gap_row, r, 1)

        kbg.addWidget(QLabel("Scale:"), r, 2, Qt.AlignRight | Qt.AlignVCenter)
        scale_row, self.kb_scale_sl, self.kb_scale_val = _slider_row(
            "Scale", 30, 200, 100, "%", "Keyboard size. 100% = auto-scaled.")
        self.kb_scale_sl.valueChanged.connect(self._on_setting_changed)
        kbg.addLayout(scale_row, r, 3)

        r += 1
        kbg.addWidget(QLabel("Opacity:"), r, 0, Qt.AlignRight | Qt.AlignVCenter)
        op_row, self.kb_opacity_sl, self.kb_opacity_val = _slider_row(
            "Opacity", 10, 100, 100, "%",
            "Keyboard opacity. 100% = solid. Lower = see-through.")
        self.kb_opacity_sl.valueChanged.connect(self._on_setting_changed)
        kbg.addLayout(op_row, r, 1)

        kbg.addWidget(QLabel("Radius:"), r, 2, Qt.AlignRight | Qt.AlignVCenter)
        self.kb_radius_sp = QSpinBox()
        self.kb_radius_sp.setRange(0, 20)
        self.kb_radius_sp.setValue(6)
        self.kb_radius_sp.setSuffix(" px")
        self.kb_radius_sp.setToolTip("Corner radius of each key.")
        self.kb_radius_sp.valueChanged.connect(self._on_setting_changed)
        kbg.addWidget(self.kb_radius_sp, r, 3)

        kbl.addLayout(kbg)
        kbl.addStretch()
        self.settings_tabs.addTab(kb_tab, "Keyboard")

        # ================= TAB 4: Timing ===========================
        timing_tab = QWidget()
        til = QVBoxLayout(timing_tab)
        til.setContentsMargins(s["md"], s["lg"], s["md"], s["lg"])
        til.setSpacing(s["sm"])
        tig = _form2col()

        r = 0
        tig.addWidget(QLabel("WPM:"), r, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.wpm_sp = QSpinBox()
        self.wpm_sp.setRange(20, 500)
        self.wpm_sp.setValue(100)
        self.wpm_sp.setSuffix(" WPM")
        self.wpm_sp.valueChanged.connect(self._on_setting_changed)
        tig.addWidget(self.wpm_sp, r, 1)

        tig.addWidget(QLabel("Typo Rate:"), r, 2, Qt.AlignRight | Qt.AlignVCenter)
        self.typo_sp = QSpinBox()
        self.typo_sp.setRange(0, 20)
        self.typo_sp.setValue(1)
        self.typo_sp.setSuffix("%")
        self.typo_sp.setToolTip("Probability of a typo per printable character.")
        self.typo_sp.valueChanged.connect(self._on_setting_changed)
        tig.addWidget(self.typo_sp, r, 3)

        r += 1
        tig.addWidget(QLabel("Start Pause:"), r, 0, Qt.AlignRight | Qt.AlignVCenter)
        # BUG FIX (v1.5.1): QSpinBox only supports integer steps, so the
        # previous setSingleStep(0.5) was silently coerced to 0 (no step)
        # — the +/- buttons did nothing. Switched to QDoubleSpinBox with
        # 1 decimal place so the 0.5s step actually works.
        self.start_pause_sp = QDoubleSpinBox()
        self.start_pause_sp.setRange(0.0, 10.0)
        self.start_pause_sp.setDecimals(1)
        self.start_pause_sp.setSingleStep(0.5)
        self.start_pause_sp.setValue(1.0)
        self.start_pause_sp.setSuffix(" s")
        self.start_pause_sp.valueChanged.connect(self._on_setting_changed)
        tig.addWidget(self.start_pause_sp, r, 1)

        tig.addWidget(QLabel("End Pause:"), r, 2, Qt.AlignRight | Qt.AlignVCenter)
        self.end_pause_sp = QDoubleSpinBox()
        self.end_pause_sp.setRange(0.0, 10.0)
        self.end_pause_sp.setDecimals(1)
        self.end_pause_sp.setSingleStep(0.5)
        self.end_pause_sp.setValue(2.0)
        self.end_pause_sp.setSuffix(" s")
        self.end_pause_sp.valueChanged.connect(self._on_setting_changed)
        tig.addWidget(self.end_pause_sp, r, 3)

        r += 1
        tig.addWidget(QLabel("Speed Ramp:"), r, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.ramp_cb = QComboBox()
        self.ramp_cb.addItems(["None", "Ease In", "Ease Out", "Ease In-Out"])
        self.ramp_cb.currentTextChanged.connect(self._on_setting_changed)
        tig.addWidget(self.ramp_cb, r, 1)

        tig.addWidget(QLabel("Ramp Str:"), r, 2, Qt.AlignRight | Qt.AlignVCenter)
        ramp_row, self.ramp_strength_sl, self.ramp_strength_val = _slider_row(
            "Ramp", 0, 100, 50, "%", "Strength of the speed ramp effect (0-100%).")
        self.ramp_strength_sl.valueChanged.connect(self._on_setting_changed)
        tig.addLayout(ramp_row, r, 3)

        r += 1
        chk_row2 = QHBoxLayout()
        chk_row2.setSpacing(s["xl"])
        self.burst_chk = QCheckBox("Burst Typing")
        self.burst_chk.setChecked(True)
        self.burst_chk.setToolTip("Model natural typing bursts of 2-6 fast keystrokes.")
        self.burst_chk.toggled.connect(self._on_setting_changed)
        chk_row2.addWidget(self.burst_chk)
        self.thinking_chk = QCheckBox("Thinking Pauses")
        self.thinking_chk.setChecked(True)
        self.thinking_chk.setToolTip("Insert occasional pauses at structural boundaries.")
        self.thinking_chk.toggled.connect(self._on_setting_changed)
        chk_row2.addWidget(self.thinking_chk)
        chk_row2.addStretch()
        tig.addLayout(chk_row2, r, 0, 1, 4)

        r += 1
        tig.addWidget(QLabel("Fatigue:"), r, 0, Qt.AlignRight | Qt.AlignVCenter)
        fatigue_row, self.fatigue_sl, self.fatigue_val = _slider_row(
            "Fatigue", 0, 100, 0, "%",
            "Gradual slowdown over the clip (0=none, 100=~40% slower by end).")
        self.fatigue_sl.valueChanged.connect(self._on_setting_changed)
        tig.addLayout(fatigue_row, r, 1, 1, 3)

        til.addLayout(tig)
        til.addStretch()
        self.settings_tabs.addTab(timing_tab, "Timing")

        # ================= TAB 5: Overlay ==========================
        ov_tab = QWidget()
        ol = QVBoxLayout(ov_tab)
        ol.setContentsMargins(s["md"], s["lg"], s["md"], s["lg"])
        ol.setSpacing(s["sm"])

        self.stats_chk = QCheckBox("Show Statistics Overlay")
        self.stats_chk.setToolTip("Display WPM, keystrokes, accuracy, and elapsed time.")
        self.stats_chk.toggled.connect(self._on_setting_changed)
        ol.addWidget(self.stats_chk)

        og = _form2col()
        r = 0
        og.addWidget(QLabel("Stats Pos:"), r, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.stats_pos_cb = QComboBox()
        self.stats_pos_cb.addItems(list(OVERLAY_POSITIONS))
        self.stats_pos_cb.currentTextChanged.connect(self._on_setting_changed)
        og.addWidget(self.stats_pos_cb, r, 1, 1, 3)

        r += 1
        og.addWidget(QLabel("Watermark:"), r, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.watermark_edit = QLineEdit()
        self.watermark_edit.setPlaceholderText("e.g. @yourhandle")
        self.watermark_edit.textChanged.connect(self._on_setting_changed)
        og.addWidget(self.watermark_edit, r, 1, 1, 3)

        r += 1
        wm_img_row = QHBoxLayout()
        wm_img_row.setSpacing(s["xs"])
        self.wm_img_btn = QPushButton("Image\u2026")
        self.wm_img_btn.clicked.connect(self._select_watermark_image)
        wm_img_row.addWidget(self.wm_img_btn)
        self.wm_img_clear_btn = QPushButton("Clear")
        self.wm_img_clear_btn.setFixedWidth(60)
        self.wm_img_clear_btn.clicked.connect(self._clear_watermark_image)
        wm_img_row.addWidget(self.wm_img_clear_btn)
        wm_img_row.addStretch()
        og.addLayout(wm_img_row, r, 0, 1, 2)

        og.addWidget(QLabel("WM Pos:"), r, 2, Qt.AlignRight | Qt.AlignVCenter)
        self.wm_pos_cb = QComboBox()
        self.wm_pos_cb.addItems(list(OVERLAY_POSITIONS))
        self.wm_pos_cb.currentTextChanged.connect(self._on_setting_changed)
        og.addWidget(self.wm_pos_cb, r, 3)

        r += 1
        og.addWidget(QLabel("WM Opacity:"), r, 0, Qt.AlignRight | Qt.AlignVCenter)
        wm_op_row, self.wm_opacity_sl, self.wm_opacity_val = _slider_row(
            "WM Opacity", 5, 100, 40, "%", "Watermark opacity (5-100%).")
        self.wm_opacity_sl.valueChanged.connect(self._on_setting_changed)
        og.addLayout(wm_op_row, r, 1, 1, 3)

        ol.addLayout(og)
        ol.addStretch()
        self.settings_tabs.addTab(ov_tab, "Overlay")

        # ================= TAB 6: Export ===========================
        exp_tab = QWidget()
        exl = QVBoxLayout(exp_tab)
        exl.setContentsMargins(s["md"], s["lg"], s["md"], s["lg"])
        exl.setSpacing(s["sm"])
        exg = _form2col()

        r = 0
        exg.addWidget(QLabel("Format:"), r, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.format_cb = QComboBox()
        self.format_cb.addItems([
            "MP4 (H.264)", "WebM (VP9)", "GIF",
            "YouTube Video", "YouTube Short",
        ])
        self.format_cb.currentTextChanged.connect(self._on_format_changed)
        exg.addWidget(self.format_cb, r, 1)

        exg.addWidget(QLabel("FPS:"), r, 2, Qt.AlignRight | Qt.AlignVCenter)
        self.fps_sp = QSpinBox()
        self.fps_sp.setRange(10, 120)
        self.fps_sp.setValue(30)
        self.fps_sp.setSuffix(" fps")
        self.fps_sp.valueChanged.connect(self._on_setting_changed)
        exg.addWidget(self.fps_sp, r, 3)

        r += 1
        exg.addWidget(QLabel("CRF:"), r, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.crf_sp = QSpinBox()
        self.crf_sp.setRange(0, 51)
        self.crf_sp.setValue(18)
        self.crf_sp.setToolTip("Constant Rate Factor (lower = better quality, larger file).")
        self.crf_sp.valueChanged.connect(self._on_setting_changed)
        exg.addWidget(self.crf_sp, r, 1)

        exg.addWidget(QLabel("Sound:"), r, 2, Qt.AlignRight | Qt.AlignVCenter)
        self.snd_profile_cb = QComboBox()
        self.snd_profile_cb.addItems([
            "Mechanical", "Typewriter", "Soft Membrane", "Laptop Chiclet",
            "Topre Electrostatic", "Custom Linear", "Cash Register",
            "Pinball", "Telegraph", "Arcade Button", "Gunshot",
            "Gunshot Silenced", "Crystal Singing Bowl", "Synth Bubble",
            "Tibetan Bowl",
        ])
        self.snd_profile_cb.currentTextChanged.connect(self._on_sound_profile_changed)
        exg.addWidget(self.snd_profile_cb, r, 3)

        # Preview button — plays a short demo of the selected sound preset.
        self.snd_preview_btn = QPushButton("Preview")
        self.snd_preview_btn.setToolTip(
            "Play a short demo sequence of the selected sound preset."
        )
        self.snd_preview_btn.setFixedWidth(70)
        self.snd_preview_btn.clicked.connect(self._preview_sound_preset)
        exg.addWidget(self.snd_preview_btn, r + 1, 2, 1, 2, Qt.AlignRight)

        r += 1
        exg.addWidget(QLabel("Volume:"), r, 0, Qt.AlignRight | Qt.AlignVCenter)
        vol_row, self.snd_vol_sl, self.snd_vol_val = _slider_row(
            "Volume", 0, 100, 50, "%", "Export audio volume (0-100%).")
        self.snd_vol_sl.valueChanged.connect(self._on_setting_changed)
        exg.addLayout(vol_row, r, 1)

        r += 1
        chk_row3 = QHBoxLayout()
        chk_row3.setSpacing(s["xl"])
        self.hw_chk = QCheckBox("GPU Encoding")
        self.hw_chk.setToolTip("Use NVENC / QSV / AMF / VideoToolbox if available.")
        self.hw_chk.toggled.connect(self._on_setting_changed)
        chk_row3.addWidget(self.hw_chk)
        self.srt_chk = QCheckBox("Export SRT")
        self.srt_chk.setToolTip("Write a .srt sidecar file with one cue per typed line.")
        chk_row3.addWidget(self.srt_chk)
        chk_row3.addStretch()
        exg.addLayout(chk_row3, r, 0, 1, 4)

        r += 1
        exg.addWidget(QLabel("YT Title:"), r, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.yt_title_edit = QLineEdit()
        self.yt_title_edit.setPlaceholderText("Video title (embedded in MP4)")
        exg.addWidget(self.yt_title_edit, r, 1, 1, 3)

        r += 1
        exg.addWidget(QLabel("YT Desc:"), r, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.yt_desc_edit = QLineEdit()
        self.yt_desc_edit.setPlaceholderText("Video description (embedded in MP4)")
        exg.addWidget(self.yt_desc_edit, r, 1, 1, 3)

        exl.addLayout(exg)
        exl.addStretch()
        self.settings_tabs.addTab(exp_tab, "Export")

        sw_root.addWidget(self.settings_tabs)

        # ── Dialog button box (OK / Apply / Close) ───────────────────
        # OK       — apply current settings and close the dialog.
        # Apply    — apply current settings (refresh preview) but keep
        #            the dialog open, so the user can keep tweaking.
        # Close    — close the dialog without forcing a refresh (the
        #            most recent live preview state is already current).
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.settings_apply_btn = QPushButton("Apply")
        self.settings_apply_btn.setToolTip(
            "Apply the current settings and refresh the preview."
        )
        self.settings_apply_btn.clicked.connect(self._on_settings_apply)
        btn_row.addWidget(self.settings_apply_btn)

        self.settings_ok_btn = QPushButton("OK")
        self.settings_ok_btn.setObjectName("primaryBtn")
        self.settings_ok_btn.setToolTip(
            "Apply the current settings and close this dialog."
        )
        self.settings_ok_btn.clicked.connect(self._on_settings_ok)
        btn_row.addWidget(self.settings_ok_btn)

        self.settings_close_btn = QPushButton("Close")
        self.settings_close_btn.setToolTip(
            "Close this dialog. Recent changes are kept."
        )
        self.settings_close_btn.clicked.connect(self._settings_win.accept)
        btn_row.addWidget(self.settings_close_btn)

        sw_root.addLayout(btn_row)

    def _on_settings_apply(self) -> None:
        """Apply current settings (refresh the preview)."""
        self._static_preview()

    def _on_settings_ok(self) -> None:
        """Apply current settings and close the dialog."""
        self._static_preview()
        self._settings_win.accept()

    def _show_settings_window(self) -> None:
        """Open the Settings dialog as a popup.

        The dialog is modeless (non-modal) so the live preview keeps
        updating as the user tweaks settings. Calling this while the
        dialog is already visible just raises it to the front.
        """
        sw = getattr(self, '_settings_win', None)
        if sw is None:
            return
        if not sw.isVisible():
            sw.show()
        sw.raise_()
        sw.activateWindow()

    def _build_menu(self) -> None:
        mb = self.menuBar()

        file_menu = mb.addMenu("&File")
        file_menu.addAction(self._action("Open File...", self._load_file, QKeySequence.Open))
        file_menu.addAction(self._action("Save to input/", self._save_to_input, QKeySequence.Save))
        file_menu.addSeparator()
        file_menu.addAction(self._action("Refresh input/", self._refresh_input_files, QKeySequence.Refresh))
        file_menu.addSeparator()
        file_menu.addAction(self._action("Exit", self.close, QKeySequence.Quit))

        view_menu = mb.addMenu("&View")
        view_menu.addAction(self._action("Play / Pause", self._toggle_play, QKeySequence("Space")))
        view_menu.addAction(self._action("Snapshot PNG", self._save_snapshot, QKeySequence("Ctrl+Shift+S")))
        view_menu.addAction(self._action("Export Video", self._start_export, QKeySequence("Ctrl+E")))
        view_menu.addAction(self._action("Cancel Export", self._cancel_export, QKeySequence("Ctrl+.")))
        view_menu.addSeparator()
        view_menu.addAction(self._action("Batch Render...", self._open_batch_dialog, QKeySequence("Ctrl+Shift+B")))
        view_menu.addAction(self._action("Settings...", self._show_settings_window, QKeySequence("Ctrl+,")))

        preset_menu = mb.addMenu("&Presets")
        preset_menu.addAction(self._action("Save Preset As...", self._save_preset))
        preset_menu.addAction(self._action("Load Preset...", self._load_preset))
        preset_menu.addAction(self._action("Delete Preset...", self._delete_preset))

        help_menu = mb.addMenu("&Help")
        help_menu.addAction(self._action("About", self._show_about))

    def _action(self, text: str, slot, shortcut: Optional[QKeySequence] = None) -> QAction:
        act = QAction(text, self)
        act.triggered.connect(slot)
        if shortcut is not None:
            act.setShortcut(shortcut)
        return act

    def _build_shortcuts(self) -> None:
        # Extra shortcuts not bound to menu items.
        QShortcut(QKeySequence("F5"), self, activated=self._refresh_input_files)
        QShortcut(QKeySequence("Ctrl+Shift+E"), self, activated=self._start_export)

    # ─────────────────────────────────────────────────────────────────
    # Settings persistence
    # ─────────────────────────────────────────────────────────────────

    def _restore_settings(self) -> None:
        s = self._settings
        if s.contains("theme"):
            self.theme_cb.setCurrentText(s.value("theme", "Dracula"))
        if s.contains("font"):
            idx = self._find_font_index(self.font_cb, s.value("font", "Consolas"))
            if idx >= 0:
                self.font_cb.setCurrentIndex(idx)
        self.autofit_chk.setChecked(s.value("autofit_font", True, type=bool))
        self.max_lines_sp.setValue(int(s.value("max_lines", 0)))
        self.size_sp.setValue(int(s.value("font_size", 22)))
        self.tab_sp.setValue(int(s.value("tab_size", 4)))
        if s.contains("title"):
            self.title_edit.setText(s.value("title", "main.py — Code Editor"))
        self.ln_chk.setChecked(s.value("line_numbers", True, type=bool))
        self.chrome_chk.setChecked(s.value("window_chrome", True, type=bool))
        if s.contains("language"):
            self.lang_cb.setCurrentText(s.value("language", "Python"))
        if s.contains("resolution"):
            self.res_cb.setCurrentText(s.value("resolution", "YouTube 1080p"))
        self.kb_chk.setChecked(s.value("show_keyboard", False, type=bool))
        self.kb_gap_sl.setValue(int(s.value("keyboard_gap", 20)))
        self.kb_scale_sl.setValue(int(s.value("keyboard_scale", 100)))
        if s.contains("keyboard_layout"):
            self.kb_layout_cb.setCurrentText(s.value("keyboard_layout", "QWERTY (US)"))
        if s.contains("keyboard_position"):
            self.kb_pos_cb.setCurrentText(s.value("keyboard_position", "Below Code"))
        self.kb_opacity_sl.setValue(int(s.value("keyboard_opacity", 100)))
        self.kb_radius_sp.setValue(int(s.value("keyboard_radius", 6)))
        self.padding_sp.setValue(int(s.value("padding", 50)))
        self.wpm_sp.setValue(int(s.value("wpm", 100)))
        self.typo_sp.setValue(int(s.value("typo_rate", 1)))
        # start/end pause are floats now (QDoubleSpinBox); accept either
        # int or float from QSettings for backwards compatibility.
        self.start_pause_sp.setValue(float(s.value("start_pause", 1)))
        self.end_pause_sp.setValue(float(s.value("end_pause", 2)))
        if s.contains("sound_profile"):
            self.snd_profile_cb.setCurrentText(s.value("sound_profile", "Mechanical"))
        self.snd_vol_sl.setValue(int(s.value("sound_volume", 50)))
        if s.contains("format"):
            self.format_cb.setCurrentText(s.value("format", "MP4 (H.264)"))
        self.fps_sp.setValue(int(s.value("fps", 30)))
        self.crf_sp.setValue(int(s.value("crf", 18)))
        # New feature toggles.
        if s.contains("speed_ramp"):
            self.ramp_cb.setCurrentText(s.value("speed_ramp", "None"))
        self.ramp_strength_sl.setValue(int(s.value("ramp_strength", 50)))
        self.burst_chk.setChecked(s.value("burst_typing", True, type=bool))
        self.thinking_chk.setChecked(s.value("thinking_pauses", True, type=bool))
        self.fatigue_sl.setValue(int(s.value("fatigue", 0)))
        self.stats_chk.setChecked(s.value("show_stats", False, type=bool))
        if s.contains("stats_position"):
            self.stats_pos_cb.setCurrentText(s.value("stats_position", "Bottom-Right"))
        if s.contains("watermark_text"):
            self.watermark_edit.setText(s.value("watermark_text", ""))
        if s.contains("watermark_position"):
            self.wm_pos_cb.setCurrentText(s.value("watermark_position", "Bottom-Right"))
        self.wm_opacity_sl.setValue(int(s.value("watermark_opacity", 40)))
        self.hw_chk.setChecked(s.value("use_hw_accel", False, type=bool))
        self.srt_chk.setChecked(s.value("export_srt", False, type=bool))
        if s.contains("yt_title"):
            self.yt_title_edit.setText(s.value("yt_title", ""))
        if s.contains("yt_description"):
            self.yt_desc_edit.setText(s.value("yt_description", ""))
        bg = s.value("bg_image_path", "")
        if bg and os.path.isfile(bg):
            self._bg_image_path = bg
        wm = s.value("watermark_image_path", "")
        if wm and os.path.isfile(wm):
            self._watermark_image_path = wm

    def _save_settings(self) -> None:
        s = self._settings
        s.setValue("theme", self.theme_cb.currentText())
        s.setValue("font", self._current_font_family)
        s.setValue("autofit_font", self.autofit_chk.isChecked())
        s.setValue("max_lines", self.max_lines_sp.value())
        s.setValue("font_size", self.size_sp.value())
        s.setValue("tab_size", self.tab_sp.value())
        s.setValue("title", self.title_edit.text())
        s.setValue("line_numbers", self.ln_chk.isChecked())
        s.setValue("window_chrome", self.chrome_chk.isChecked())
        s.setValue("language", self.lang_cb.currentText())
        s.setValue("resolution", self.res_cb.currentText())
        s.setValue("show_keyboard", self.kb_chk.isChecked())
        s.setValue("keyboard_gap", self.kb_gap_sl.value())
        s.setValue("keyboard_scale", self.kb_scale_sl.value())
        s.setValue("keyboard_layout", self.kb_layout_cb.currentText())
        s.setValue("keyboard_position", self.kb_pos_cb.currentText())
        s.setValue("keyboard_opacity", self.kb_opacity_sl.value())
        s.setValue("keyboard_radius", self.kb_radius_sp.value())
        s.setValue("padding", self.padding_sp.value())
        s.setValue("wpm", self.wpm_sp.value())
        s.setValue("typo_rate", self.typo_sp.value())
        s.setValue("start_pause", self.start_pause_sp.value())
        s.setValue("end_pause", self.end_pause_sp.value())
        s.setValue("sound_profile", self.snd_profile_cb.currentText())
        s.setValue("sound_volume", self.snd_vol_sl.value())
        s.setValue("format", self.format_cb.currentText())
        s.setValue("fps", self.fps_sp.value())
        s.setValue("crf", self.crf_sp.value())
        # New feature toggles.
        s.setValue("speed_ramp", self.ramp_cb.currentText())
        s.setValue("ramp_strength", self.ramp_strength_sl.value())
        s.setValue("burst_typing", self.burst_chk.isChecked())
        s.setValue("thinking_pauses", self.thinking_chk.isChecked())
        s.setValue("fatigue", self.fatigue_sl.value())
        s.setValue("show_stats", self.stats_chk.isChecked())
        s.setValue("stats_position", self.stats_pos_cb.currentText())
        s.setValue("watermark_text", self.watermark_edit.text())
        s.setValue("watermark_position", self.wm_pos_cb.currentText())
        s.setValue("watermark_opacity", self.wm_opacity_sl.value())
        s.setValue("use_hw_accel", self.hw_chk.isChecked())
        s.setValue("export_srt", self.srt_chk.isChecked())
        s.setValue("yt_title", self.yt_title_edit.text())
        s.setValue("yt_description", self.yt_desc_edit.text())
        s.setValue("bg_image_path", self._bg_image_path or "")
        s.setValue("watermark_image_path", self._watermark_image_path or "")

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Save settings and close both windows when the main window closes.

        BUG FIX (v1.5.1): this method was previously defined twice — the
        second definition (this one) shadowed the first, so the Settings
        window was never closed when the main window was closed, leaving
        a dangling hidden window. Both behaviours are now merged here.
        """
        self._preview_timer.stop()
        self._code_debounce.stop()
        if self.is_playing:
            self.is_playing = False
        self._save_settings()
        sw = getattr(self, '_settings_win', None)
        if sw is not None:
            sw.close()
        super().closeEvent(event)

    # ─────────────────────────────────────────────────────────────────
    # Font list helpers (Unicode script support)
    # ─────────────────────────────────────────────────────────────────
    # String names only — no enum access at class load time.
    # Resolved lazily via _ws_for() with getattr fallback.
    _WS_NAME_MAP: dict[str, list[str]] = {
        "Latin / Western": ["Latin", "Greek", "Cyrillic"],
        "CJK (Chinese, Japanese, Korean)": [
            "SimplifiedChinese", "TraditionalChinese", "Japanese", "Korean",
        ],
        "Arabic / Persian / Urdu": ["Arabic"],
        "Devanagari (Hindi, Sanskrit)": ["Devanagari"],
        "Cyrillic (Russian, Ukrainian)": ["Cyrillic"],
        "Thai": ["Thai"],
        "Hebrew": ["Hebrew"],
        "Georgian": ["Georgian"],
        "Armenian": ["Armenian"],
        "Ethiopic": ["Ethiopic", "Geez"],
        "Tibetan": ["Tibetan"],
    }

    _TAG_LABELS: dict[str, str] = {
        "CJK (Chinese, Japanese, Korean)": "CJK",
        "Arabic / Persian / Urdu": "Arabic",
        "Devanagari (Hindi, Sanskrit)": "Devanagari",
        "Thai": "Thai",
        "Hebrew": "Hebrew",
        "Georgian": "Georgian",
        "Armenian": "Armenian",
        "Ethiopic": "Ethiopic",
        "Tibetan": "Tibetan",
    }

    _ws_cache: dict[str, set] = {}
    _script_ws_int_cache: dict[str, list[int]] = {}

    @staticmethod
    def _ws_for(label: str) -> list[int]:
        if label in MainWindow._script_ws_int_cache:
            return MainWindow._script_ws_int_cache[label]
        names = MainWindow._WS_NAME_MAP.get(label, [])
        result = []
        for name in names:
            val = getattr(QFontDatabase.WritingSystem, name, None)
            if val is not None:
                result.append(val.value)
        MainWindow._script_ws_int_cache[label] = result
        return result

    @staticmethod
    def _build_ws_cache(families: list) -> None:
        fd = QFontDatabase()
        MainWindow._ws_cache.clear()
        for f in families:
            ws_list = fd.writingSystems(f)
            MainWindow._ws_cache[f] = set(ws.value if isinstance(ws, QFontDatabase.WritingSystem) else int(ws) for ws in ws_list)

    @staticmethod
    def _font_supports_script(family: str, script_label: str) -> bool:
        if script_label == "Monospace Only":
            fd = QFontDatabase()
            return fd.isFixedPitch(family)
        if script_label == "All Scripts":
            return True
        ws_set = MainWindow._ws_cache.get(family, set())
        needed = MainWindow._ws_for(script_label)
        if not needed:
            return True
        return any(s in ws_set for s in needed)

    @staticmethod
    def _get_font_script_tags(family: str) -> str:
        """Return a short tag string like 'CJK, Thai' for fonts that
        support non-Latin scripts.  Uses cached writing-system data."""
        ws_set = MainWindow._ws_cache.get(family, set())
        tags = []
        for label, short in MainWindow._TAG_LABELS.items():
            needed = MainWindow._ws_for(label)
            if any(s in ws_set for s in needed):
                tags.append(short)
        return ", ".join(tags) if tags else ""

    @staticmethod
    def _find_font_index(combo: QComboBox, family: str) -> int:
        """Find the combo index for *family*, tolerating the
        '  [tag, ...]' suffix that _populate_font_list adds."""
        # Exact match first (fast path)
        idx = combo.findText(family)
        if idx >= 0:
            return idx
        # Prefix match: item may be "Family  [CJK,Thai]"
        for i in range(combo.count()):
            text = combo.itemText(i)
            base = text.split("  [")[0].strip() if "  [" in text else text
            if base == family:
                return i
        return -1

    @property
    def _current_font_family(self) -> str:
        """Return the selected font family name, stripped of any
        script-tag suffix like '  [CJK,Thai]'."""
        text = self.font_cb.currentText()
        # Strip trailing "  [tag, tag, ...]" if present
        idx = text.rfind("  [")
        if idx > 0 and text.endswith("]"):
            return text[:idx]
        return text

    def _populate_font_list(self, script_filter: str) -> None:
        """Populate the font combo box filtered by *script_filter*."""
        fd = QFontDatabase()
        families = fd.families()
        current_font = self.font_cb.currentText()

        # Build the writing-system cache once (rebuilds if font count changed)
        if len(MainWindow._ws_cache) != len(families):
            MainWindow._build_ws_cache(families)

        # Determine if "Monospace Only" — use Qt's built-in classification
        mono_families = set()
        if script_filter == "Monospace Only":
            for f in families:
                if fd.isFixedPitch(f):
                    mono_families.add(f)

        matched = []
        for f in families:
            if script_filter == "Monospace Only":
                if f not in mono_families:
                    continue
            elif script_filter != "All Scripts":
                if not self._font_supports_script(f, script_filter):
                    continue

            # Build display label with script tags for non-Latin fonts
            tags = self._get_font_script_tags(f)
            if tags:
                label = f"{f}  [{tags}]"
            else:
                label = f
            matched.append((f, label))

        # Sort alphabetically, with known-good coding fonts first.
        # BUG FIX (v1.5.1): ``priority`` was previously a ``set``, which
        # has non-deterministic iteration order in Python — so
        # ``list(priority).index(base)`` returned a random index, making
        # the "priority fonts first" ordering effectively random.
        # Switched to a tuple (ordered) so the priority order is exactly
        # as listed below.
        priority = (
            "Consolas", "JetBrains Mono", "Cascadia Code", "Fira Code",
            "Source Code Pro", "IBM Plex Mono", "Inconsolata", "Hack",
            "Space Mono", "mononoki", "SF Mono", "Menlo", "DejaVu Sans Mono",
            "Liberation Mono", "Sarasa Mono SC", "Sarasa Mono J",
            "Sarasa Mono K", "LXGW WenKai Mono", "Noto Sans Mono CJK SC",
            "Noto Sans Mono CJK JP", "Noto Sans Mono CJK KR",
            "WenQuanYi Zen Hei Mono",
        )
        priority_index = {name: i for i, name in enumerate(priority)}

        def sort_key(item):
            family, _label = item
            base = family.split(",")[0].strip()
            if base in priority_index:
                return (0, priority_index[base], base.lower())
            return (1, 0, base.lower())

        matched.sort(key=sort_key)

        self.font_cb.blockSignals(True)
        self.font_cb.clear()
        for _family, label in matched:
            self.font_cb.addItem(label)
        # Restore previous selection or default
        idx = self._find_font_index(self.font_cb, current_font)
        if idx < 0:
            idx = self._find_font_index(self.font_cb, "Consolas")
        if idx >= 0:
            self.font_cb.setCurrentIndex(idx)
        self.font_cb.blockSignals(False)

    def _on_font_script_changed(self, script_filter: str) -> None:
        """Re-populate font list when the script filter changes."""
        self._populate_font_list(script_filter)
        self._on_setting_changed()

    def _on_autofit_toggled(self, checked: bool) -> None:
        self.size_sp.setEnabled(not checked)
        self._visible_lines_label.setVisible(checked)
        self.max_lines_sp.setVisible(checked)
        if not checked:
            # Auto-focus the spinbox so arrow keys work immediately.
            self.size_sp.setFocus(Qt.FocusReason.OtherFocusReason)
            self.size_sp.selectAll()
        self._static_preview()

    def _on_kb_pos_changed(self, pos: str) -> None:
        """Auto-set opacity hint when switching to Overlay mode."""
        if pos == "Overlay Bottom" and self.kb_opacity_sl.value() == 100:
            self.kb_opacity_sl.setValue(50)
        self._on_setting_changed()

    def _on_kb_toggled(self, checked: bool) -> None:
        self._on_setting_changed()

    def _on_resolution_changed(self, res_name: str) -> None:
        self._apply_kb_defaults_for_resolution(res_name)
        self._on_setting_changed()

    def _apply_kb_defaults_for_resolution(self, res_name: str) -> None:
        """Apply smart keyboard defaults when the resolution changes."""
        defaults = KB_DEFAULTS.get(res_name)
        if not defaults:
            return
        self.kb_pos_cb.setCurrentText(defaults["position"])
        self.kb_scale_sl.setValue(int(defaults["scale"]))
        self.kb_gap_sl.setValue(int(defaults["gap"]))

    # Preview / play / scrub
    # ─────────────────────────────────────────────────────────────────
    def _on_setting_changed(self) -> None:
        self._static_preview()

    def _on_format_changed(self) -> None:
        """Handle format-dropdown changes (e.g. switching to YouTube Short)."""
        fmt = self.format_cb.currentText()
        if fmt == "YouTube Short":
            # Auto-switch to the vertical 9:16 resolution if the user
            # is currently on a horizontal one.
            current_res = self.res_cb.currentText()
            if current_res not in ("YouTube Short (9:16)", "TikTok / Reels"):
                # Find the YouTube Short preset and select it.
                idx = self.res_cb.findText("YouTube Short (9:16)")
                if idx >= 0:
                    self.res_cb.setCurrentIndex(idx)
        # Warn about YouTube Shorts duration cap if needed.
        self._check_youtube_duration()
        self._static_preview()

    def _on_sound_profile_changed(self, profile: str) -> None:
        """Re-initialise sound effects when the profile changes."""
        self._init_sounds(profile)
        self._on_setting_changed()

    def _preview_sound_preset(self) -> None:
        """Play a short demo sequence of the currently selected sound preset.

        Renders a representative mix of sounds from the active profile into
        a temporary WAV file and plays it with a one-shot ``QSoundEffect``.
        The demo plays ~6 sounds spaced 120 ms apart so the user can hear
        the character of the preset without starting a full typing preview.
        """
        if not hasattr(self, "_preview_sfx") or self._preview_sfx is None:
            self._preview_sfx = None
            self._preview_tmp = None

        # Clean up any previous preview.
        if self._preview_sfx is not None:
            self._preview_sfx.stop()
            self._preview_sfx.deleteLater()
            self._preview_sfx = None
        if self._preview_tmp is not None:
            try:
                os.remove(self._preview_tmp)
            except OSError:
                pass
            self._preview_tmp = None

        gen = self.sound_gen
        volume = self.snd_vol_sl.value() / 100.0
        sr = gen.sample_rate
        gap_samples = int(sr * 0.12)  # 120 ms gap between sounds
        gap = np.zeros(gap_samples, dtype=np.float64)

        # Pick a representative set of categories to demonstrate.
        categories = list(gen.sounds.keys())
        if not categories:
            return

        # For keyboard profiles, build a demo sequence: key, key, space,
        # key, enter.  For thematic profiles, just pick the first several
        # categories which already carry distinctive names.
        is_keyboard = not gen._CATEGORY_MAPS.get(gen.profile, {})
        if is_keyboard:
            demo_order = ["key", "key", "space", "key", "key", "enter"]
            # Only include categories that actually exist in this profile.
            demo_order = [c for c in demo_order if c in gen.sounds]
            if not demo_order:
                demo_order = categories[:6]
        else:
            # Thematic profile — pick up to 6 unique categories.
            demo_order = categories[:6]

        # Mix the demo sequence.
        parts: list[np.ndarray] = []
        for cat in demo_order:
            variants = gen.sounds.get(cat, [])
            if not variants:
                continue
            snd = variants[0].astype(np.float64)
            parts.append(snd)
            parts.append(gap)

        if not parts:
            return

        demo_signal = np.concatenate(parts)
        # Normalise so the demo is a comfortable listening level.
        peak = np.max(np.abs(demo_signal))
        if peak > 0:
            demo_signal = demo_signal / peak * 0.6

        # Write to a temp WAV and play it.
        tmp_path = os.path.join(TMP_DIR, "_snd_preview.wav")
        gen.save_wav(tmp_path, demo_signal.astype(np.float64),
                     sr=sr, volume=volume, channels=1)

        sfx = QSoundEffect(self)
        sfx.setSource(QUrl.fromLocalFile(os.path.abspath(tmp_path)))
        sfx.setVolume(0.9)
        sfx.play()

        self._preview_sfx = sfx
        self._preview_tmp = tmp_path

        # Auto-clean after the sound finishes (~2 s safety margin).
        QTimer.singleShot(int(len(demo_signal) / sr * 1000) + 2000,
                          self._cleanup_preview_sfx)

    def _cleanup_preview_sfx(self) -> None:
        """Delete the one-shot preview QSoundEffect and its temp file."""
        if self._preview_sfx is not None:
            self._preview_sfx.stop()
            self._preview_sfx.deleteLater()
            self._preview_sfx = None
        if self._preview_tmp is not None:
            try:
                os.remove(self._preview_tmp)
            except OSError:
                pass
            self._preview_tmp = None

    def _check_youtube_duration(self) -> None:
        """Emit a status-bar warning if a YouTube Short would exceed 60s."""
        fmt = self.format_cb.currentText()
        if fmt != "YouTube Short":
            return
        if not self.animator:
            return
        dur = self.animator.duration()
        if dur > YOUTUBE_SHORT_MAX_DURATION:
            self.statusBar().showMessage(
                f"YouTube Short: source is {dur:.1f}s — will be truncated to "
                f"{YOUTUBE_SHORT_MAX_DURATION:.0f}s on export.",
                8000,
            )
        else:
            self.statusBar().showMessage(
                f"YouTube Short: {dur:.1f}s (within 60s limit).", 5000,
            )

    def _on_code_changed(self) -> None:
        self._code_debounce.start()

    def _load_sample(self, sample: str) -> None:
        self.editor.setPlainText(sample)
        self._current_input_file = None

    def _static_preview(self) -> None:
        code = self.editor.toPlainText()
        if not code.strip():
            self.animator = None
            self.renderer = None
            self._preview_scratch = None  # PERF (v1.7): free ~8 MB when not needed
            self.timeline_slider.setValue(0)
            self._update_time_labels(0.0, 0.0)
            return
        res_name = self.res_cb.currentText()
        w, h = RESOLUTION_PRESETS.get(res_name, (1920, 1080))

        # Determine font size: auto-fit or manual.
        if self.autofit_chk.isChecked():
            code_lines = code.count("\n") + 1
            target = self.max_lines_sp.value() or None
            font_size = CodeRenderer.auto_font_size(
                code_lines=code_lines,
                width=w, height=h,
                padding=self.padding_sp.value(),
                show_window_chrome=self.chrome_chk.isChecked(),
                show_line_numbers=self.ln_chk.isChecked(),
                show_keyboard=self.kb_chk.isChecked(),
                tab_size=self.tab_sp.value(),
                target_lines=target,
                keyboard_position=self.kb_pos_cb.currentText(),
                # BUG FIX: these two params were missing, causing the
                # auto-font-size calculation to use defaults (scale=1.0,
                # gap=20) instead of the user's actual slider values.
                # This led to slightly wrong font sizes when the user
                # changed the keyboard scale or gap sliders.
                keyboard_scale=self.kb_scale_sl.value() / 100.0,
                keyboard_gap=self.kb_gap_sl.value(),
                code=code,
            )
            # Update the spinbox to show the computed value (without
            # triggering another preview cycle).
            self.size_sp.blockSignals(True)
            self.size_sp.setValue(font_size)
            self.size_sp.blockSignals(False)
        else:
            font_size = self.size_sp.value()

        self.renderer = CodeRenderer(
            width=w, height=h, theme_name=self.theme_cb.currentText(),
            font_family=self._current_font_family,
            font_size=font_size,
            show_line_numbers=self.ln_chk.isChecked(),
            show_window_chrome=self.chrome_chk.isChecked(),
            padding=self.padding_sp.value(),
            tab_size=self.tab_sp.value(),
            title_text=self.title_edit.text(),
            language=self.lang_cb.currentText(),
            show_keyboard=self.kb_chk.isChecked(),
            keyboard_gap=self.kb_gap_sl.value(),
            keyboard_scale=self.kb_scale_sl.value() / 100.0,
            keyboard_layout=self.kb_layout_cb.currentText(),
            keyboard_position=self.kb_pos_cb.currentText(),
            keyboard_opacity=self.kb_opacity_sl.value() / 100.0,
            keyboard_radius=self.kb_radius_sp.value(),
            show_stats=self.stats_chk.isChecked(),
            stats_position=self.stats_pos_cb.currentText(),
            watermark_text=self.watermark_edit.text(),
            watermark_image=self._watermark_image_path,
            watermark_position=self.wm_pos_cb.currentText(),
            watermark_opacity=self.wm_opacity_sl.value() / 100.0,
        )
        # PERF (v1.7): invalidate preview scratch when renderer resolution
        # changes so _render_at allocates a correctly-sized buffer.
        self._preview_scratch = None
        if self._bg_image_path:
            self.renderer.set_background_image(self._bg_image_path)

        self.animator = TypingAnimator(
            code,
            base_wpm=self.wpm_sp.value(),
            humanize=True,
            typo_rate=self.typo_sp.value() / 100.0,
            start_pause=self.start_pause_sp.value(),
            end_pause=self.end_pause_sp.value(),
            speed_ramp=self.ramp_cb.currentText(),
            ramp_strength=self.ramp_strength_sl.value() / 100.0,
            burst_typing=self.burst_chk.isChecked(),
            thinking_pauses=self.thinking_chk.isChecked(),
            fatigue=self.fatigue_sl.value() / 100.0,
        )
        # Wire the animator into the renderer so the stats overlay works
        # during live preview too.
        self.renderer.animator_ref = self.animator
        self.renderer.current_time = self.animator.duration()
        qimg = self.renderer.render_frame(
            self.animator.display_chars, len(self.animator.display_chars), False
        )
        self._show_preview(qimg)
        self._play_offset = 0
        self.timeline_slider.setValue(0)
        # Update the time labels to show the total duration.
        self._update_time_labels(0.0, self.animator.duration())
        # Update status bar permanent labels.
        w, h = RESOLUTION_PRESETS.get(res_name, (1920, 1080))
        self._status_res_lbl.setText(f"{w}x{h}")
        # CLARITY (v1.5.1): replaced the previous `line_h and X or '?'`
        # hack with a proper if/else so the intent is obvious.
        line_h = self.renderer.line_h
        if line_h > 0:
            avail_h = (self.renderer.height
                       - 2 * self.renderer.padding
                       - self.renderer.title_bar_h)
            visible_lines = avail_h // line_h
            lines_str = str(visible_lines) if visible_lines > 0 else "?"
        else:
            lines_str = "?"
        self._status_font_lbl.setText(f"{font_size}px · {lines_str} lines")
        self._status_lang_lbl.setText(self.lang_cb.currentText())
        self._status_dur_lbl.setText(self._format_time(self.animator.duration()))

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Format seconds as M:SS (or H:MM:SS for long clips)."""
        if seconds < 0:
            seconds = 0.0
        total = int(seconds)
        if total >= 3600:
            h, rem = divmod(total, 3600)
            m, s = divmod(rem, 60)
            return f"{h:d}:{m:02d}:{s:02d}"
        m, s = divmod(total, 60)
        return f"{m:d}:{s:02d}"

    def _update_time_labels(self, current: float, total: float) -> None:
        """Update the transport-bar time labels."""
        self.time_current_lbl.setText(self._format_time(current))
        self.time_total_lbl.setText(self._format_time(total))

    def _show_preview(self, qimg) -> None:
        # PERF (v1.7): use FastTransformation instead of SmoothTransformation
        # for the preview pixmap.  The preview is displayed at a much smaller
        # size than the actual QImage (typically 400x225 vs 1920x1080), so
        # the quality difference is imperceptible but FastTransformation is
        # ~3x faster for large images.
        pixmap = QPixmap.fromImage(qimg)
        self.preview_lbl.setObjectName("")  # remove placeholder styling once we have content
        self.preview_lbl.setStyleSheet("")
        self.preview_lbl.setPixmap(
            pixmap.scaled(
                self.preview_lbl.size(),
                Qt.KeepAspectRatio, Qt.FastTransformation,
            )
        )

    def _toggle_play(self) -> None:
        if self.is_playing:
            self._pause()
        else:
            self._play()

    def _play(self) -> None:
        if not self.animator or not self.renderer:
            return
        self.is_playing = True
        self._play_t0 = _time.time()
        self._last_vis = 0
        self._preview_timer.start()
        # Use ASCII text instead of ⏸/▶ glyphs for cross-platform
        # rendering consistency (per the documented improvement that
        # emoji glyphs were removed from button labels).
        self.play_btn.setText("||  Pause")

    def _pause(self) -> None:
        self.is_playing = False
        self._preview_timer.stop()
        self._play_offset += _time.time() - self._play_t0
        self.play_btn.setText(">  Play")

    def _tick(self) -> None:
        if not self.animator or not self.renderer:
            return
        elapsed = _time.time() - self._play_t0 + self._play_offset
        duration = self.animator.duration()

        if not self._scrubbing:
            pct = min(1.0, elapsed / duration)
            self.timeline_slider.blockSignals(True)
            self.timeline_slider.setValue(int(pct * 1000))
            self.timeline_slider.blockSignals(False)
            # Live-update the current-time label during playback.
            self._update_time_labels(elapsed, duration)

        if elapsed >= duration:
            self._pause()
            return

        nv = self.animator.visible_at(elapsed)
        if nv != self._last_vis:
            self._last_vis = nv
            qimg = self._render_at(elapsed, nv=nv)
            self._show_preview(qimg)
            if nv > 0:
                self._play_click(self.animator.display_chars[nv - 1])

    def _render_at(self, t: float, nv: Optional[int] = None) -> Optional[QImage]:
        if not self.animator or not self.renderer:
            return None
        # PERF (v1.7): accept an optional ``nv`` parameter so the caller
        # (_tick) can pass in the already-computed visible count, avoiding
        # a redundant bisect call (visible_at internally does bisect).
        if nv is None:
            nv = self.animator.visible_at(t)
        cur_vis = True
        # Use bisect on the precomputed timestamps for O(log n) lookup
        # instead of scanning the entire timeline linearly.
        idx = bisect.bisect_right(self.animator._timestamps, t)
        last_ts = 0.0
        if idx > 0:
            last_ts = self.animator.timeline[idx - 1][0]
        since = t - last_ts
        if since > 0.25:
            cur_vis = (int(since / 0.53) % 2) == 0
        pressed_key = None
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
        self.renderer.pressed_key = pressed_key
        # Update stats overlay time before rendering.
        self.renderer.current_time = t
        # PERF (v1.7): reuse a scratch QImage for preview rendering,
        # matching the exporter's approach.  Avoids ~8 MB allocation
        # per preview frame (16 ms timer = ~62 allocations/sec).
        w, h = self.renderer.width, self.renderer.height
        scratch = self._preview_scratch
        if scratch is None or scratch.width() != w or scratch.height() != h:
            self._preview_scratch = QImage(w, h, QImage.Format_RGB32)
            scratch = self._preview_scratch
        return self.renderer.render_frame(self.animator.display_chars, nv, cur_vis, target=scratch)

    def _on_timeline_scrub(self, value: int) -> None:
        self._scrubbing = True
        if not self.animator:
            return
        duration = self.animator.duration()
        t = (value / 1000.0) * duration
        qimg = self._render_at(t)
        if qimg is not None:
            self._show_preview(qimg)
        # Update the current-time label while scrubbing.
        self._update_time_labels(t, duration)

    def _on_timeline_pressed(self) -> None:
        self._scrubbing = True
        if self.is_playing:
            self._pause()

    def _on_timeline_released(self) -> None:
        self._scrubbing = False
        if not self.animator:
            return
        self._play_offset = (self.timeline_slider.value() / 1000.0) * self.animator.duration()
        self._play_t0 = _time.time()
        self._last_vis = -1  # force refresh on next tick

    # ─────────────────────────────────────────────────────────────────
    # Export
    # ─────────────────────────────────────────────────────────────────
    def _start_export(self) -> None:
        if not self.animator or not self.renderer:
            return
        # Stop the live preview so the renderer is not accessed
        # concurrently by the export worker thread.
        if self.is_playing:
            self._pause()
        if self.exporter is not None and self.exporter.isRunning():
            self.exporter.cancel()
            self.exporter.wait(10000)
        output = self._get_auto_output_path()

        # Optionally write a .srt file alongside the video.
        subtitle_path: Optional[str] = None
        if self.srt_chk.isChecked() and "GIF" not in self.format_cb.currentText():
            base, _ = os.path.splitext(output)
            subtitle_path = base + ".srt"

        self.exporter = VideoExporter(
            self.editor.toPlainText(), output, self.renderer, self.animator,
            fps=self.fps_sp.value(),
            sound_gen=self.sound_gen,
            volume=self.snd_vol_sl.value() / 100.0,
            codec_profile=self.format_cb.currentText(),
            crf=self.crf_sp.value(),
            subtitle_path=subtitle_path,
            use_hw_accel=self.hw_chk.isChecked(),
            metadata_title=self.yt_title_edit.text(),
            metadata_description=self.yt_desc_edit.text(),
        )
        self.exporter.progress.connect(self.progress_bar.setValue)
        self.exporter.status.connect(self.statusBar().showMessage)
        self.exporter.finished_ok.connect(self._on_export_done)
        self.exporter.error.connect(self._on_export_error)
        self.exporter.start()
        self.export_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)

    def _cancel_export(self) -> None:
        if self.exporter:
            self.exporter.cancel()

    def _on_export_done(self, path: str) -> None:
        self.statusBar().showMessage(f"Exported: {path}")
        self.export_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        QMessageBox.information(self, "Export Complete", f"Video saved to:\n{path}")

    def _on_export_error(self, msg: str) -> None:
        self.export_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        QMessageBox.critical(self, "Export Error", msg)

    # ─────────────────────────────────────────────────────────────────
    # Batch rendering
    # ─────────────────────────────────────────────────────────────────
    def _capture_batch_settings(self) -> BatchSettings:
        """Snapshot the current UI settings into a BatchSettings instance.

        This is called when the batch dialog opens so that changing the
        main window's settings during a batch does not affect in-flight
        items.
        """
        return BatchSettings(
            # Renderer
            theme_name=self.theme_cb.currentText(),
            font_family=self._current_font_family,
            font_size=self.size_sp.value(),
            autofit=self.autofit_chk.isChecked(),
            max_lines=self.max_lines_sp.value(),
            tab_size=self.tab_sp.value(),
            padding=self.padding_sp.value(),
            title_text=self.title_edit.text(),
            show_line_numbers=self.ln_chk.isChecked(),
            show_window_chrome=self.chrome_chk.isChecked(),
            language=self.lang_cb.currentText(),
            show_keyboard=self.kb_chk.isChecked(),
            keyboard_gap=self.kb_gap_sl.value(),
            keyboard_scale=self.kb_scale_sl.value() / 100.0,
            keyboard_layout=self.kb_layout_cb.currentText(),
            keyboard_position=self.kb_pos_cb.currentText(),
            keyboard_opacity=self.kb_opacity_sl.value() / 100.0,
            keyboard_radius=self.kb_radius_sp.value(),
            show_stats=self.stats_chk.isChecked(),
            stats_position=self.stats_pos_cb.currentText(),
            watermark_text=self.watermark_edit.text(),
            watermark_image=self._watermark_image_path,
            watermark_position=self.wm_pos_cb.currentText(),
            watermark_opacity=self.wm_opacity_sl.value() / 100.0,
            bg_image=self._bg_image_path,
            resolution=self.res_cb.currentText(),
            # Animator
            wpm=self.wpm_sp.value(),
            typo_rate=self.typo_sp.value() / 100.0,
            start_pause=self.start_pause_sp.value(),
            end_pause=self.end_pause_sp.value(),
            speed_ramp=self.ramp_cb.currentText(),
            ramp_strength=self.ramp_strength_sl.value() / 100.0,
            burst_typing=self.burst_chk.isChecked(),
            thinking_pauses=self.thinking_chk.isChecked(),
            fatigue=self.fatigue_sl.value() / 100.0,
            # Export
            fps=self.fps_sp.value(),
            crf=self.crf_sp.value(),
            preset="medium",
            codec_profile=self.format_cb.currentText(),
            sound_profile=self.snd_profile_cb.currentText(),
            sound_volume=self.snd_vol_sl.value() / 100.0,
            use_hw_accel=self.hw_chk.isChecked(),
            export_srt=self.srt_chk.isChecked(),
            metadata_title=self.yt_title_edit.text(),
            metadata_description=self.yt_desc_edit.text(),
        )
    
    def _open_batch_dialog(self) -> None:
        """Open the batch render dialog using the BatchDialog class.

        BUG FIX: this previously contained a full inline dialog
        implementation that duplicated the BatchDialog class below.
        The inline version had several bugs (closure issue in
        remove_item, no reorder support, no proper thread cleanup
        on close).  We now delegate to the proper BatchDialog class.
        """
        from .exporter import BatchItem, BatchSettings

        settings = self._capture_batch_settings()
        items: List[BatchItem] = []

        dlg = BatchDialog(items, settings, parent=self)
        # Pass the current editor content so "Add Current Editor" works.
        dlg.set_current_editor_code(self.editor.toPlainText())
        dlg.exec()

    # ─────────────────────────────────────────────────────────────────
    # File dialogs / samples
    # ─────────────────────────────────────────────────────────────────
    def _load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Code File", "",
            f"Code Files (*{' '.join(SUPPORTED_EXTENSIONS)})",
        )
        if path:
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    self.editor.setPlainText(f.read())
                self._current_input_file = path
                self.title_edit.setText(f"{os.path.basename(path)} \u2014 Code Editor")
                self._auto_detect_language(path)
            except Exception as e:
                QMessageBox.warning(self, "Error", str(e))

    def _show_about(self) -> None:
        QMessageBox.about(
            self, "About Code Typing Video Generator",
            "<h3>Code Typing Video Generator</h3>"
            "<p>Generate MP4/WebM/GIF videos of code being typed with realistic "
            "animation and procedural sound effects.</p>"
            "<p><b>Features:</b> syntax highlighting (Python/JS/TS/C/C++/Java/Go/Rust), "
            "8 themes, live stats overlay (WPM/keystrokes/accuracy), text & image "
            "watermarks, speed ramp, burst typing, thinking pauses, fatigue, "
            "context-aware QWERTY typos, 15 sound profiles (Mechanical / Typewriter / "
            "Soft Membrane / Laptop Chiclet / Topre / Custom Linear / "
            "Cash Register / Pinball / Telegraph / Arcade / Gunshot / "
            "Silenced / Crystal Bowl / Synth Bubble / Tibetan Bowl) "
            "YouTube Video & YouTube Short export modes with YouTube-recommended "
            "H.264 bitrates/levels + 60s Shorts cap + embedded metadata, "
            "hardware-accelerated encoding (NVENC/QSV/AMF/VT), SRT subtitle export, "
            "PNG snapshots, named presets, <b>batch rendering</b> "
            "(queue multiple files / inline snippets and export them all in one go).</p>"
            "<p><b>Shortcuts:</b> Space = play/pause, Ctrl+E = export, "
            "Ctrl+Shift+S = snapshot, Ctrl+Shift+B = batch render, "
            "Ctrl+, = settings, Ctrl+. = cancel, F5 = refresh input/.</p>",
        )


# ═══════════════════════════════════════════════════════════════════════════
# BATCH RENDER DIALOG
# ═══════════════════════════════════════════════════════════════════════════
# A QDialog that lets the user build a queue of code files (or inline
# snippets), start a batch export, and monitor per-item + overall progress.
# The dialog captures a BatchSettings snapshot from the main window when
# opened, so changing the main window's settings during a batch does not
# affect in-flight items.
#
# The batch engine itself (BatchItem, BatchSettings, BatchExporter) lives
# in exporter.py — see the BATCH RENDERING section at the bottom of that
# module.
# ═══════════════════════════════════════════════════════════════════════════

# Status icons (Unicode glyphs that render on most platforms without
# emoji support — using simple geometric / math symbols).
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

    # Column indices in the queue table.
    _COL_STATUS = 0
    _COL_NAME = 1
    _COL_TYPE = 2
    _COL_DETAILS = 3

    def __init__(
        self,
        items: List[BatchItem],
        settings: BatchSettings,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Batch Render")
        self.setMinimumSize(720, 520)
        self.resize(800, 600)

        self._items = items
        self._settings = settings
        self._exporter: Optional[BatchExporter] = None
        self._is_running = False

        self._build_ui()
        self._refresh_table()
        self._update_button_states()

    # ─────────────────────────────────────────────────────────────────
    # UI construction
    # ─────────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        s = UI_SPACING
        root = QVBoxLayout(self)
        root.setContentsMargins(s["lg"], s["lg"], s["lg"], s["lg"])
        root.setSpacing(s["md"])

        # ── Header / settings summary ─────────────────────────────────
        summary = self._settings_summary()
        summary_lbl = QLabel(summary)
        summary_lbl.setStyleSheet(
            f"color: {UI_PALETTE['text_dim']}; font-size: 12px; "
            f"padding: {s['sm']}px {s['md']}px; "
            f"background-color: {UI_PALETTE['bg_panel']}; "
            f"border-radius: {s['radius']}px;"
        )
        summary_lbl.setWordWrap(True)
        root.addWidget(summary_lbl)

        # ── Queue label + action buttons ─────────────────────────────
        queue_header = QHBoxLayout()
        queue_header.setSpacing(s["sm"])
        lbl = QLabel("Queue:")
        lbl.setStyleSheet(
            f"color: {UI_PALETTE['text']}; font-weight: 600; font-size: 13px;"
        )
        queue_header.addWidget(lbl)
        queue_header.addStretch()

        self.add_files_btn = QPushButton("Add Files...")
        self.add_files_btn.clicked.connect(self._add_files)
        queue_header.addWidget(self.add_files_btn)

        self.add_current_btn = QPushButton("Add Current Editor")
        self.add_current_btn.setToolTip(
            "Add the current editor content as an inline snippet."
        )
        self.add_current_btn.clicked.connect(self._add_current_editor)
        queue_header.addWidget(self.add_current_btn)

        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self._remove_selected)
        queue_header.addWidget(self.remove_btn)

        self.clear_btn = QPushButton("Clear All")
        self.clear_btn.clicked.connect(self._clear_all)
        queue_header.addWidget(self.clear_btn)

        root.addLayout(queue_header)

        # ── Reorder buttons ──────────────────────────────────────────
        reorder_row = QHBoxLayout()
        reorder_row.setSpacing(s["sm"])
        reorder_row.addStretch()
        self.up_btn = QPushButton("Move Up")
        self.up_btn.setFixedWidth(90)
        self.up_btn.clicked.connect(lambda: self._move_selected(-1))
        reorder_row.addWidget(self.up_btn)
        self.down_btn = QPushButton("Move Down")
        self.down_btn.setFixedWidth(90)
        self.down_btn.clicked.connect(lambda: self._move_selected(1))
        reorder_row.addWidget(self.down_btn)
        root.addLayout(reorder_row)

        # ── Queue table ──────────────────────────────────────────────
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Status", "Name", "Type", "Details"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(self._COL_STATUS, QHeaderView.Fixed)
        hdr.resizeSection(self._COL_STATUS, 60)
        hdr.setSectionResizeMode(self._COL_NAME, QHeaderView.Stretch)
        hdr.setSectionResizeMode(self._COL_TYPE, QHeaderView.Fixed)
        hdr.resizeSection(self._COL_TYPE, 80)
        hdr.setSectionResizeMode(self._COL_DETAILS, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._update_button_states)
        root.addWidget(self.table, 1)

        # ── Progress section ─────────────────────────────────────────
        prog_box = QVBoxLayout()
        prog_box.setSpacing(s["xs"])

        overall_row = QHBoxLayout()
        overall_lbl = QLabel("Overall:")
        overall_lbl.setFixedWidth(60)
        overall_row.addWidget(overall_lbl)
        self.overall_bar = QProgressBar()
        self.overall_bar.setValue(0)
        overall_row.addWidget(self.overall_bar, 1)
        self.overall_count_lbl = QLabel("0 / 0")
        self.overall_count_lbl.setFixedWidth(60)
        self.overall_count_lbl.setAlignment(Qt.AlignCenter)
        overall_row.addWidget(self.overall_count_lbl)
        prog_box.addLayout(overall_row)

        item_row = QHBoxLayout()
        item_lbl = QLabel("Item:")
        item_lbl.setFixedWidth(60)
        item_row.addWidget(item_lbl)
        self.item_bar = QProgressBar()
        self.item_bar.setValue(0)
        item_row.addWidget(self.item_bar, 1)
        self.item_pct_lbl = QLabel("")
        self.item_pct_lbl.setFixedWidth(60)
        self.item_pct_lbl.setAlignment(Qt.AlignCenter)
        item_row.addWidget(self.item_pct_lbl)
        prog_box.addLayout(item_row)

        self.status_lbl = QLabel("Ready.")
        self.status_lbl.setStyleSheet(
            f"color: {UI_PALETTE['text_dim']}; font-size: 12px;"
        )
        prog_box.addWidget(self.status_lbl)

        root.addLayout(prog_box)

        # ── Action buttons ───────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.start_btn = QPushButton("Start Batch")
        self.start_btn.setObjectName("primaryBtn")
        self.start_btn.clicked.connect(self._start_batch)
        btn_row.addWidget(self.start_btn)

        self.cancel_btn = QPushButton("Cancel Batch")
        self.cancel_btn.setObjectName("dangerBtn")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_batch)
        btn_row.addWidget(self.cancel_btn)

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self._on_close)
        btn_row.addWidget(self.close_btn)

        root.addLayout(btn_row)

    def _settings_summary(self) -> str:
        """Build a one-paragraph summary of the captured settings."""
        s = self._settings
        parts = [
            f"Resolution: {s.resolution}",
            f"Format: {s.codec_profile}",
            f"Theme: {s.theme_name}",
            f"WPM: {s.wpm}",
            f"Sound: {s.sound_profile}",
            f"FPS: {s.fps}",
        ]
        if s.show_keyboard:
            parts.append(f"Keyboard: {s.keyboard_layout}")
        if s.show_stats:
            parts.append("Stats overlay")
        if s.watermark_text:
            parts.append(f"Watermark: \"{s.watermark_text}\"")
        return "  |  ".join(parts)

    # ─────────────────────────────────────────────────────────────────
    # Queue management
    # ─────────────────────────────────────────────────────────────────
    def _add_files(self) -> None:
        """Open a multi-select file dialog and add chosen files."""
        ext_str = " ".join(SUPPORTED_EXTENSIONS)
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Code Files for Batch", "",
            f"Code Files (*{ext_str});;All Files (*)",
        )
        if not paths:
            return
        added = 0
        for p in paths:
            # Skip duplicates already in the queue.
            if any(it.file_path == p for it in self._items):
                continue
            self._items.append(BatchItem(file_path=p))
            added += 1
        self._refresh_table()
        self._update_button_states()
        if added:
            self.status_lbl.setText(
                f"Added {added} file(s). Queue has {len(self._items)} item(s)."
            )

    def _add_current_editor(self) -> None:
        """Add the main window's current editor content as inline code.

        The actual code is passed in via :meth:`set_current_editor_code`
        before the dialog is opened. If no code was provided, this is a
        no-op.
        """
        code = getattr(self, "_current_editor_code", "")
        if not code.strip():
            QMessageBox.information(
                self, "Add Current Editor",
                "The editor is empty. Nothing to add."
            )
            return
        # Ask for a display name.
        default_name = f"snippet_{len(self._items) + 1}"
        name, ok = QInputDialog.getText(
            self, "Name Snippet", "Snippet name:", text=default_name
        )
        if not ok or not name.strip():
            return
        self._items.append(
            BatchItem(inline_code=code, display_name=name.strip())
        )
        self._refresh_table()
        self._update_button_states()
        self.status_lbl.setText(
            f"Added inline snippet '{name.strip()}'. "
            f"Queue has {len(self._items)} item(s)."
        )

    def set_current_editor_code(self, code: str) -> None:
        """Store the current editor content for 'Add Current Editor'."""
        self._current_editor_code = code

    def _remove_selected(self) -> None:
        rows = sorted(
            set(idx.row() for idx in self.table.selectedIndexes()),
            reverse=True,
        )
        if not rows:
            return
        for r in rows:
            if 0 <= r < len(self._items):
                del self._items[r]
        self._refresh_table()
        self._update_button_states()

    def _clear_all(self) -> None:
        if not self._items:
            return
        if QMessageBox.question(
            self, "Clear Queue",
            f"Remove all {len(self._items)} item(s) from the queue?"
        ) != QMessageBox.Yes:
            return
        self._items.clear()
        self._refresh_table()
        self._update_button_states()

    def _move_selected(self, delta: int) -> None:
        """Move the selected row(s) up (delta=-1) or down (delta=+1)."""
        rows = sorted(set(idx.row() for idx in self.table.selectedIndexes()))
        if not rows:
            return
        # BUG FIX: the previous implementation did ``pop(r)`` then
        # ``insert(new_r)`` for each selected row.  When moving UP
        # (delta=-1), this is WRONG because pop(r) shifts all later
        # items down by one, so a subsequent pop(r-1) removes the
        # item that was originally at r+1, not r-1.
        # The correct approach: build the target permutation and
        # reorder the entire list at once.
        n = len(self._items)
        # Build a set of row indices to move.
        move_set = set(rows)
        if delta == -1:
            # Move up: each row swaps with the one above it.
            # Process from top to bottom so we don't double-swap.
            ordered = sorted(rows)
            for r in ordered:
                if r > 0 and (r - 1) not in move_set:
                    self._items[r - 1], self._items[r] = (
                        self._items[r], self._items[r - 1]
                    )
        else:
            # Move down: each row swaps with the one below it.
            # Process from bottom to top so we don't double-swap.
            ordered = sorted(rows, reverse=True)
            for r in ordered:
                if r < n - 1 and (r + 1) not in move_set:
                    self._items[r], self._items[r + 1] = (
                        self._items[r + 1], self._items[r]
                    )
        self._refresh_table()
        # Reselect moved items.
        if rows:
            # After move, the items are now at rows + delta (clamped).
            self.table.selectRow(max(0, min(rows[0] + delta, n - 1)))

    # ─────────────────────────────────────────────────────────────────
    # Table refresh
    # ─────────────────────────────────────────────────────────────────
    def _refresh_table(self) -> None:
        self.table.setRowCount(len(self._items))
        for i, item in enumerate(self._items):
            # Status icon + text.
            status_text = item.status
            icon = _STATUS_ICONS.get(status_text, "")
            status_item = QTableWidgetItem(f"{icon}  {status_text}")
            status_item.setForeground(QColor(
                _STATUS_COLORS.get(status_text, UI_PALETTE["text"])
            ))
            self.table.setItem(i, self._COL_STATUS, status_item)

            # Name.
            name = item.resolve_display_name()
            self.table.setItem(i, self._COL_NAME, QTableWidgetItem(name))

            # Type (File / Inline).
            if item.file_path:
                type_text = "File"
            else:
                type_text = "Inline"
            self.table.setItem(i, self._COL_TYPE, QTableWidgetItem(type_text))

            # Details (output path, error, or progress).
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

    def _update_button_states(self) -> None:
        has_selection = bool(self.table.selectedIndexes())
        has_items = len(self._items) > 0
        self.remove_btn.setEnabled(has_selection and not self._is_running)
        self.clear_btn.setEnabled(has_items and not self._is_running)
        self.up_btn.setEnabled(has_selection and not self._is_running)
        self.down_btn.setEnabled(has_selection and not self._is_running)
        self.add_files_btn.setEnabled(not self._is_running)
        self.add_current_btn.setEnabled(not self._is_running)
        self.start_btn.setEnabled(has_items and not self._is_running)
        self.close_btn.setEnabled(not self._is_running)

    # ─────────────────────────────────────────────────────────────────
    # Batch execution
    # ─────────────────────────────────────────────────────────────────
    def _start_batch(self) -> None:
        if not self._items:
            return
        if self._is_running:
            return

        # Reset all items to Pending.
        for item in self._items:
            item.status = "Pending"
            item.error = None
            item.output_path = None
        self._refresh_table()

        # Reset progress bars.
        self.overall_bar.setValue(0)
        self.item_bar.setValue(0)
        self.overall_count_lbl.setText(f"0 / {len(self._items)}")
        self.item_pct_lbl.setText("")

        # Create and start the exporter.
        self._exporter = BatchExporter(
            list(self._items),  # pass a copy of the list
            self._settings,
            parent=self,
        )
        self._exporter.item_started.connect(self._on_item_started)
        self._exporter.item_progress.connect(self._on_item_progress)
        self._exporter.item_finished.connect(self._on_item_finished)
        self._exporter.item_failed.connect(self._on_item_failed)
        self._exporter.batch_progress.connect(self._on_batch_progress)
        self._exporter.status.connect(self._on_status)
        self._exporter.batch_finished.connect(self._on_batch_finished)

        self._is_running = True
        self._update_button_states()
        self.cancel_btn.setEnabled(True)
        self.start_btn.setEnabled(False)

        self._exporter.start()

    def _cancel_batch(self) -> None:
        if self._exporter is not None:
            self.status_lbl.setText("Cancelling...")
            self._exporter.cancel()

    def _on_item_started(self, index: int, name: str) -> None:
        if 0 <= index < len(self._items):
            self._items[index].status = "Rendering"
            self._refresh_table()
        self.item_bar.setValue(0)
        self.item_pct_lbl.setText("0%")
        self.overall_count_lbl.setText(
            f"{index + 1} / {len(self._items)}"
        )

    def _on_item_progress(self, pct: int) -> None:
        self.item_bar.setValue(pct)
        self.item_pct_lbl.setText(f"{pct}%")

    def _on_item_finished(self, index: int, output_path: str) -> None:
        if 0 <= index < len(self._items):
            self._items[index].status = "Done"
            self._items[index].output_path = output_path
            self._refresh_table()

    def _on_item_failed(self, index: int, error: str) -> None:
        if 0 <= index < len(self._items):
            self._items[index].status = "Failed"
            self._items[index].error = error
            self._refresh_table()

    def _on_batch_progress(self, pct: int) -> None:
        self.overall_bar.setValue(pct)

    def _on_status(self, msg: str) -> None:
        self.status_lbl.setText(msg)

    def _on_batch_finished(self, succeeded: int, total: int) -> None:
        self._is_running = False
        self._update_button_states()
        self.cancel_btn.setEnabled(False)
        self.start_btn.setEnabled(len(self._items) > 0)
        self.item_bar.setValue(0)
        self.item_pct_lbl.setText("")

        # Mark any items still "Rendering" (shouldn't happen, but just
        # in case) as Skipped.
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

    # ─────────────────────────────────────────────────────────────────
    # Close handling
    # ─────────────────────────────────────────────────────────────────
    def _on_close(self) -> None:
        if self._is_running:
            reply = QMessageBox.question(
                self, "Batch Running",
                "A batch is still running. Cancel it and close?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
            self._cancel_batch()
            # BUG FIX: must wait for the thread to finish and also
            # set _is_running to False before checking. The old code
            # called wait(5000) but then checked ``self._is_running``
            # which was still True because batch_finished hadn't
            # been emitted yet within 5s for a slow export. We now
            # use a longer wait and also handle timeout gracefully.
            if self._exporter is not None:
                self._exporter.wait(30000)
            # If still running after wait, force-terminate.
            if self._is_running:
                self._is_running = False
                self._update_button_states()
        self.accept()

    def closeEvent(self, event) -> None:
        """Intercept the window-close button too."""
        if self._is_running:
            self._on_close()
            if self._is_running:
                event.ignore()
                return
        super().closeEvent(event)

    def keyPressEvent(self, event) -> None:
        """Intercept Escape when a batch is running."""
        if event.key() == Qt.Key_Escape and self._is_running:
            self._on_close()
            if self._is_running:
                event.ignore()
                return
        super().keyPressEvent(event)
