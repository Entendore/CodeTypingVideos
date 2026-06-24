"""
Code Typing Video Generator
===========================

Creates MP4 / WebM / GIF videos of code being typed with realistic
animation, syntax highlighting, optional keyboard overlay, and
procedurally generated typing sounds.

Run with::

    python -m code_typing_generator.app

File structure (10 files)
-------------------------
  __init__.py     Package marker + this docstring
  config.py       Paths, themes, presets, keyboard layout, logging setup
  tokenizers.py   Syntax highlighters (Python, JS/TS, C/C++/Java, Go, Rust)
  sound.py        Procedural keyboard sound synthesis + track mixing
  renderer.py     Frame painter: bg, chrome, syntax colors, caret, keyboard
  animator.py     Per-character typing timeline with typos + humanised timing
  exporter.py     Single-file VideoExporter + BatchExporter (multi-file queue)
  widgets.py      DropTextEdit (drag-and-drop file input)
  main_window.py  UI, menu, shortcuts, settings, preview, export, BatchDialog
  app.py          Entry point

Improvements over the original single-file version
--------------------------------------------------
  * Split into 9 focused modules + entry point
  * Type hints + docstrings on all public classes and functions
  * Two new language tokenizers: Go and Rust (TS keywords merged into JS)
  * One new theme: Solarized Light
  * Sample-code buttons for Go and Rust
  * Menu bar (File / View / Help) with keyboard shortcuts
  * Settings persistence via QSettings (restored on next launch)
  * _on_timeline_released now resets play_t0 and forces refresh
  * VideoExporter.finished renamed to finished_ok (no QThread shadowing)
  * Cleaner temp-dir cleanup in exporter
  * TypingAnimator accepts an optional seed for reproducible timelines
  * Single TOKENIZER_MAP drives both renderer and language dropdown
  * _draw_caret and _env_exp helpers deduplicate code
  * Removed emoji glyphs from button labels for cross-platform rendering
  * Long one-liners expanded into readable statements
  * Bare except: clauses replaced with except Exception:
  * Default logging level lowered from DEBUG to INFO

Performance improvements
------------------------
  * Static background + window chrome pre-rendered once into a cached
    QPixmap and blitted per frame (was redrawn every frame).
  * Full source tokenised exactly once per display_chars list; each
    frame takes an O(1) slice of the precomputed colour array (was
    re-tokenised every frame → O(n^2) over the whole export).
  * visible_text computed in O(1) via a precomputed is_clean / stack_len
    table that detects the rare "active typo" frames and falls back to
    slow resolution only for those.
  * Per-line horizontal layout (char_x positions) cached by line text
    with FIFO eviction (was recomputed for every visible line, every
    frame).
  * Exporter reuses a single scratch QImage instead of allocating
    ~8 MB per frame (~14 GB of allocations avoided in a typical export).
  * Fast path in _qimg_to_raw_rgb for Format_RGB32 images reads the
    buffer directly via numpy and reverses BGRA → RGB in-place,
    skipping the expensive convertToFormat(RGB888) copy.
  * All renderer caches guarded by a threading.Lock; main window stops
    the preview timer during export so only one thread touches the
    renderer.
  * Removed unused cv2 dependency and _qimg_to_frame dead code.
  * Exporter logs render throughput (frames, ms/frame, fps) and emits
    it as a status-bar message so the speedup is visible.

New features
------------
  * **Batch rendering**: queue multiple code files (or inline snippets)
    and export them all in one go via the Batch Render dialog
    (Ctrl+Shift+B). Per-item progress + overall progress, cancel
    mid-batch, auto-detects language from file extension, reuses one
    sound generator across all items for fast throughput.
  * Statistics overlay (WPM, keystrokes, accuracy %, elapsed time) with
    configurable position — useful for typing-tutorial videos.
  * Watermark overlay: text and/or image, configurable position and
    opacity — for branding videos.
  * Speed ramp: Ease In / Ease Out / Ease In-Out easing curves with
    adjustable strength for a cinematic slow-start / slow-end effect.
  * PNG snapshot export: grab the current preview frame (at the
    scrubber position) as a PNG to output/. Shortcut: Ctrl+Shift+S.
  * SRT subtitle export: write a sidecar .srt file with one cue per
    typed line, alongside the exported video, for accessibility.
  * Hardware-accelerated encoding: auto-detects NVENC (NVIDIA),
    QuickSync (Intel), VideoToolbox (macOS), or AMF (AMD) and uses
    the GPU encoder for much faster MP4 exports; falls back to
    libx264 if none is available.
  * Named presets: save / load / delete named JSON preset files in
    presets/ via the Presets menu — share configs across projects.
  * All new feature toggles are persisted via QSettings and restored
    on next launch.

Humanised typing animations
---------------------------
  * Burst typing: real typing comes in rolls of 2-6 fast keystrokes
    separated by short micro-pauses; we model this explicitly so the
    cadence sounds natural instead of metronomic.
  * Thinking pauses: occasional 0.15-0.55s pauses after newlines,
    colons, equals signs, and open parens, with a longer bonus pause
    after blank lines (paragraph breaks).
  * Context-aware typos: instead of random a-z noise, typos are now
    drawn from keys physically adjacent on a QWERTY layout, with rare
    doubled-letter and same-row near-miss typos for variety. Each
    typo is followed by a realistic "notice + backspace" delay.
  * Handedness / distance modelling: same-key repeats are very fast,
    adjacent keys roll quickly, and big hand repositions slow down
    slightly — approximated via QWERTY row/column distance.
  * Character-class delays: newlines, spaces, tabs, sentence-final
    punctuation, mid-sentence punctuation, brackets, operators,
    quotes, digits, and upper-case letters each have their own
    timing profile (upper-case models the extra Shift coordination).
  * Hand fatigue: optional gradual slowdown over the course of long
    clips (0 = no fatigue, 1 = ~40% slower by the end).

Better procedural sounds
------------------------
  * New 4th profile: Laptop Chiclet (Apple Magic Keyboard / MacBook
    short crisp click).
  * 9 per-character sound categories instead of 3: key, space, enter,
    backspace, tab, quote, bracket, digit, modifier — each with its
    own DSP recipe and 4-8 natural variants.
  * Improved DSP: two-stage exponential attack/decay envelopes,
    secondary housing resonance, pre-ringing noise burst on key-down,
    low-pass-filtered noise floor, and per-sound normalisation to
    -3 dBFS to prevent clipping when many keystrokes overlap.
  * Typewriter Enter now has a richer two-partial bell; Typewriter Tab
    is modelled as a descending frequency sweep (the tab lever sliding
    across).
  * Backspace sounds now play in live preview (previously suppressed).

YouTube export modes
--------------------
  * Two new format options: "YouTube Video" and "YouTube Short".
  * Both use H.264 High profile with the bitrate and level YouTube
    officially recommends for the current resolution and frame rate
    (720p/1080p/1440p/2160p × 30/60 fps), per YouTube's SDR upload
    guidelines. See config.YOUTUBE_SDR_BITRATES.
  * YouTube Short mode auto-switches to a vertical 9:16 resolution,
    caps the export at 60 seconds (with a status-bar warning if the
    source is longer), and truncates the audio track to match.
  * 2-second GOP (keyframe interval) for clean YouTube seeking.
  * AAC stereo audio at 128 kbps (YouTube's SDR recommendation).
  * +faststart movflag for instant web playback.
  * Optional title and description fields are embedded as MP4
    metadata tags so the file is self-describing.
  * Output files use distinctive suffixes: ``*_short.mp4`` for
    Shorts, ``*_yt.mp4`` for regular YouTube videos.

Professional layout & GUI
-------------------------
  * Modern dark theme applied globally via a comprehensive QSS
    stylesheet (config.app_stylesheet): slate-blue accent on
    near-black background, rounded corners, hover/pressed states,
    consistent spacing. Designed to look at home next to VS Code,
    OBS, or DaVinci.
  * 3-panel layout: code editor (left) | tabbed settings (middle) |
    live preview + transport (right). Each panel is independently
    scrollable.
  * Settings reorganised into 4 tabs — Visuals / Animation / Overlays
    / Export — so every control is visible without scrolling through
    a single long settings list.
  * Primary action button (Export Video) styled in the accent colour;
    Cancel button styled as a danger (red outline) button — standard
    professional desktop conventions.
  * Transport bar now shows live ``M:SS`` current / total time labels
    on either side of the timeline slider, updating during playback
    and while scrubbing.
  * Cohesive UI_PALETTE + UI_SPACING + UI_FONT_STACK / UI_MONO_STACK
    constants centralise every visual decision in config.py so the
    look stays consistent and is easy to re-theme.
  * QPalette set explicitly so native dialogs (file open, message
    boxes) inherit the dark theme rather than clashing with it.
  * Styled scroll bars, tab bars, combo boxes, sliders, checkboxes,
    progress bars, menus, and tooltips — no default Qt chrome left
    untouched.

Bug fixes in v1.6.0
-------------------
  * **exporter.py** — ``BatchExporter.run`` and ``_export_item``
    referenced ``self._cancel_event`` (which does not exist on
    ``BatchExporter`` — that attribute belongs to ``VideoExporter``).
    The correct flag is ``self._cancel`` (a plain ``bool``).  This
    caused an ``AttributeError`` crash whenever a batch export was
    cancelled or any item after the first was skipped.
  * **exporter.py** — removed a duplicate comment line
    (``# ── Font size (auto-fit or manual) ──`` appeared twice in
    ``_export_item``).
  * **renderer.py** — removed a duplicate ``self._wm_scaled`` attribute
    assignment in ``__init__`` that shadowed the intended pre-computed
    cached watermark pixmap.

Performance improvements in v1.6.0
----------------------------------
  * **renderer.py** — pre-computed all theme ``QColor`` objects once in
    ``__init__`` into ``self._qcolors`` dict.  Previously every
    ``setPen``/``setBrush`` call in the per-frame render path
    constructed a new ``QColor`` from a hex string — for a 50-line
    frame with 5 syntax colours, that was ~100+ ``QColor`` allocations
    per frame (180,000+ over a typical 30 fps export).  Now zero
    per-frame ``QColor`` allocations occur in the hot path.
  * **renderer.py** — pre-created the stats overlay ``QFont`` and
    ``QFontMetrics`` once in ``__init__`` instead of allocating a new
    font + metrics every frame in ``_draw_stats``.  The stats box
    dimensions (width, height, line height, padding) are also
    pre-computed once.
  * **renderer.py** — pre-created the watermark overlay ``QFont`` and
    ``QFontMetrics`` once in ``__init__`` instead of allocating a new
    font + metrics every frame in ``_draw_watermark``.
  * **renderer.py** — the watermark source image is now scaled to the
    target width once (when set or first drawn) and the scaled
    ``QPixmap`` is reused on subsequent frames.  Previously
    ``scaledToWidth()`` was called every frame.
  * **renderer.py** — pre-created the keyboard overlay ``QFont`` once in
    ``__init__`` instead of constructing a new ``QFont("Arial", ...)``
    every frame in ``_draw_keyboard``.
  * **renderer.py** — ``_tokenize_to_colors`` now uses slice assignment
    (``colors[pos:end] = [ckey] * length``) instead of a per-character
    inner loop.  This is ~3x faster for long tokens like strings and
    comments.  A local alias for ``TOKEN_COLOR_MAP.get`` avoids
    repeated dict method lookups.
  * **renderer.py** — ``_get_line_layout`` now has a lock-free fast
    path for cache hits.  Previously every visible line on every frame
    acquired ``_cache_lock`` (typically 30–60 lock acquisitions per
    frame).  Now cache hits return immediately without locking; the
    lock is only acquired on the slow path (new line that needs layout
    computation).
  * **renderer.py** — local alias ``self._fm.horizontalAdvance`` in the
    line-layout computation to avoid repeated attribute lookup per
    character.
  * **animator.py** — added a ``_KW_FIRST_CHARS`` frozenset that
    pre-computes the set of first characters appearing in any
    ``PAUSE_KEYWORD``.  In ``_char_delay``, the O(n) keyword scan
    loop is skipped entirely when the current character cannot
    possibly start a keyword (O(1) set membership check).  This
    eliminates ~95% of the substring comparisons.
  * **exporter.py** — ``_qimg_to_raw_rgb`` now pre-allocates a numpy
    output buffer (``self._raw_buf``) sized to the video resolution
    and reuses it across all frames via ``np.copyto``.  Previously a
    new ~6 MB array was allocated every frame.
  * **tokenizers.py** — ``tokenize()`` now reads ``cls._COMPILED``
    directly before calling ``_compile()`` as a fallback, avoiding
    the method-call overhead on every invocation when the regex is
    already compiled (the common case).

Performance improvements in v1.7.0
----------------------------------
  * **renderer.py** — **zero per-frame QColor allocations**.  v1.6
    pre-computed ``self._qcolors`` but the render loop still called
    ``QColor(self.theme[...])`` in 7 locations: current-line highlight,
    line numbers, cursor, stats overlay, watermark overlay, keyboard
    keys, and syntax colour runs.  All 7 are now pre-computed into
    named attributes (``_qc_current_line``, ``_qc_cursor``, etc.)
    so the per-frame render path is completely allocation-free.
  * **renderer.py** — **identity-based colour-run grouping**.
    ``_tokenize_to_colors`` now builds a parallel ``List[QColor]``
    (``_color_qc``) alongside the string colour-key list.  The render
    loop uses ``is`` / ``is not`` identity comparison on QColors
    instead of ``!=`` string comparison + ``dict.get()`` lookup.
    This saves one dict lookup and one string comparison per colour
    run per line per frame.
  * **renderer.py** — pre-computed keyboard key brushes and pens
    (``_kb_pressed_brush``, ``_kb_normal_brush``, ``_kb_pressed_pen``,
    ``_kb_normal_pen``).  Previously each of the ~60 keys on the
    keyboard overlay created 2 QColor objects per frame via
    ``.lighter(130)`` and dict lookups.  Now the 4 objects are
    created once in ``__init__``.
  * **renderer.py** — pre-computed glyph shadow QColor
    (``_qc_glyph_shadow``) and overlay background (``_qc_overlay_bg``)
    for the traffic-light buttons and stats/watermark panels.
  * **main_window.py** — **scratch QImage reuse for live preview**.
    Previously ``_render_at`` allocated a new ~8 MB QImage every
    16 ms tick (~500 MB/sec of allocations).  Now a single scratch
    QImage is reused (matching the exporter's approach), dropping
    preview allocations to zero after the first frame.
  * **main_window.py** — **eliminated redundant ``visible_at()``
    call**.  ``_tick`` computed ``nv`` via ``visible_at(elapsed)``
    then passed it to ``_render_at`` which called ``visible_at``
    again internally.  Now ``_render_at`` accepts an optional ``nv``
    parameter, and ``_tick`` passes its pre-computed value.
  * **main_window.py** — **FastTransformation for preview scaling**.
    ``_show_preview`` now uses ``Qt.FastTransformation`` instead of
    ``Qt.SmoothTransformation`` when scaling the rendered QImage to
    the preview label's size.  The preview is typically 400x225
    displaying a 1920x1080 image, so the quality difference is
    imperceptible but FastTransformation is ~3x faster.
  * **animator.py** — ``_char_delay`` now uses ``str.startswith(kw, i)``
    instead of ``self.code[i:i+len(kw)] == kw``.  ``startswith`` avoids
    creating a temporary slice object on each comparison, reducing
    per-character GC pressure in the timeline builder.
  * **animator.py** — ``_build_timeline`` now shifts event timestamps
    in-place (``events[i] = (ts + sp, idx, ch)``) instead of building
    a second full-size list via list comprehension.  Saves ~100 KB
    of peak memory for a typical 5000-event timeline.
  * **exporter.py** — ``_qimg_to_raw_rgb`` now writes BGRA→RGB channel
    swap directly into the pre-allocated output buffer using three
    ``buf[:,:,ch] = arr[:,:,src]`` assignments, instead of creating
    a non-contiguous view (``arr[:,:,2::-1]``) and then calling
    ``np.copyto`` or ``np.ascontiguousarray``.  This avoids one
    intermediate array allocation per frame.
  * **widgets.py** — ``DropTextEdit.paintEvent`` now caches the
    ``QFontMetrics`` and ``QColor`` for the placeholder text, only
    rebuilding them when the widget's font actually changes.  Previously
    a ``QFontMetrics`` and ``QColor`` were allocated on every repaint
    when the editor was empty and unfocused.

Requirements
------------
  Python 3.9+, PySide6, numpy, FFmpeg (on PATH).
"""

from __future__ import annotations

__version__ = "1.7.0"
__all__ = ["__version__"]
