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

from __future__ import annotations

import bisect
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time as _time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from .config import (
    TMP_DIR, OUTPUT_DIR, RESOLUTION_PRESETS, EXT_TO_LANGUAGE,
    is_short_resolution, youtube_bitrate_for, YOUTUBE_SHORT_MAX_DURATION,
    GPU_VRAM_TIERS, GPU_VRAM_SAFETY_MARGIN, GPU_VRAM_POLL_INTERVAL,
    GPU_VRAM_LOW_WATERMARK, gpu_tier_for_vram,
)
from .animator import TypingAnimator
from .renderer import CodeRenderer
from .sound import TypingSoundGenerator


class VideoExporter(QThread):
    """Background thread that exports the animation to a video file."""

    progress = Signal(int)
    status = Signal(str)
    finished_ok = Signal(str)   # emits output path on success
    error = Signal(str)
    gpu_info = Signal(str)     # emits "GPU Name | 8192 MB | Tier: RTX 2070-class"

    def __init__(
        self,
        code: str,
        output: str,
        renderer: CodeRenderer,
        animator: TypingAnimator,
        fps: int = 30,
        sound_gen: Optional[TypingSoundGenerator] = None,
        volume: float = 0.5,
        codec_profile: str = "MP4 (H.264)",
        crf: int = 18,
        preset: str = "medium",
        subtitle_path: Optional[str] = None,
        use_hw_accel: bool = False,
        metadata_title: str = "",
        metadata_description: str = "",
        max_duration: Optional[float] = None,
    ) -> None:
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
        self.subtitle_path = subtitle_path
        self.use_hw_accel = use_hw_accel
        self.metadata_title = metadata_title.strip()
        self.metadata_description = metadata_description.strip()
        # When set (e.g. for YouTube Shorts), the export is truncated to
        # at most this many seconds of content.
        self.max_duration = max_duration
        self.logger = logging.getLogger("VideoExporter")
        self._cancel_event = threading.Event()
        # Make sure the renderer can ask the animator for live stats.
        self.renderer.animator_ref = animator
        # PERF (v1.6): pre-allocate a numpy buffer for the BGRA→RGB
        # conversion in _qimg_to_raw_rgb.  Sized once to w*h*3 bytes
        # and reused every frame, avoiding ~6 MB of allocations/frame.
        self._raw_buf: Optional[np.ndarray] = np.empty(
            (self.renderer.height, self.renderer.width, 3), dtype=np.uint8
        )

    def cancel(self) -> None:
        self._cancel_event.set()

    # ── helpers ───────────────────────────────────────────────────────
    @staticmethod
    def _check_ffmpeg() -> bool:
        try:
            r = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
            return r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def _detect_gpu_info() -> Tuple[str, int, int]:
        """Query nvidia-smi for GPU name, total VRAM, and free VRAM (MiB).

        Returns ``(gpu_name, total_vram_mb, free_vram_mb)``.  On non-NVIDIA
        systems or when nvidia-smi is unavailable, returns ``("", 0, 0)``.
        The query runs in ~30ms and should only be called once at export
        start (or periodically during export for monitoring).
        """
        try:
            r = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,memory.total,memory.free",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True, timeout=5,
            )
            if r.returncode != 0:
                return ("", 0, 0)
            line = r.stdout.decode("utf-8", errors="ignore").strip()
            # Format: "NVIDIA GeForce GTX 1080, 8111, 6023"
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                name = parts[0]
                total = int(parts[1])
                free = int(parts[2])
                return (name, total, free)
        except Exception:
            pass
        return ("", 0, 0)

    @staticmethod
    def _poll_gpu_free_vram() -> int:
        """Quick poll of free VRAM (MiB).  Returns 0 on failure."""
        try:
            r = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.free",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True, timeout=5,
            )
            if r.returncode == 0:
                return int(r.stdout.decode("utf-8", errors="ignore").strip())
        except Exception:
            pass
        return 0

    @staticmethod
    def _detect_hw_encoder() -> Optional[Tuple[str, str]]:
        """Detect an available hardware H.264 encoder.

        Probes FFmpeg's encoder list for known GPU encoders and returns
        ``(encoder_name, preset)`` if one is available, otherwise None.

        Detection order (most common first):
          - h264_nvenc      (NVIDIA)
          - h264_qsv        (Intel QuickSync)
          - h264_videotoolbox (macOS)
          - h264_amf        (AMD)
        """
        try:
            r = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"],
                capture_output=True, timeout=5,
            )
            text = (r.stdout + r.stderr).decode("utf-8", errors="ignore")
        except Exception:
            return None
        candidates = [
            ("h264_nvenc", "p4"),
            ("h264_qsv", "veryfast"),
            ("h264_videotoolbox", ""),
            ("h264_amf", "speed"),
        ]
        for enc, preset in candidates:
            if enc in text:
                return (enc, preset)
        return None

    @staticmethod
    def _smart_gpu_tier(total_vram_mb: int) -> dict:
        """Return the best GPU_VRAM_TIERS entry for the given VRAM.

        This is a thin wrapper around :func:`gpu_tier_for_vram` that
        also logs the selection for debugging.  The returned dict
        contains all NVENC tuning parameters for the detected tier.
        """
        tier = gpu_tier_for_vram(total_vram_mb)
        return tier

    @staticmethod
    def _build_nvenc_args(tier: dict, w: int, h: int, bitrate_kbps: int = 0) -> list:
        """Build NVENC-specific FFmpeg arguments from a GPU tier config.

        Parameters
        ----------
        tier : dict
            A ``GPU_VRAM_TIERS`` entry with keys like ``nvenc_preset``,
            ``nvenc_rc``, ``nvenc_surfaces``, etc.
        w, h : int
            Frame resolution.  Used to estimate surface memory and
            clamp the surface count if the resolution exceeds the
            tier's recommended max.
        bitrate_kbps : int
            Target bitrate in kbps.  If 0, quality-based mode (``-cq``)
            is used instead.

        Returns
        -------
        list[str]
            FFmpeg command-line arguments to append after ``-c:v h264_nvenc``.
        """
        args: list[str] = []

        # Preset — controls the encoder's speed/quality tradeoff.
        args += ["-preset", tier["nvenc_preset"]]

        # Rate control.
        args += ["-rc", tier["nvenc_rc"]]
        if bitrate_kbps > 0:
            args += ["-b:v", f"{bitrate_kbps}k"]
            args += ["-maxrate", f"{bitrate_kbps}k"]
            args += ["-bufsize", f"{bitrate_kbps * 2}k"]
        else:
            # Quality-based: CQ mode with a default quality target.
            args += ["-b:v", "0", "-cq", "20"]

        # Adaptive quantization — spatial AQ improves perceptual quality
        # at no extra memory cost.
        args += ["-aq", tier["nvenc_aq"]]

        # Multipass — higher tiers use multi-pass encoding for better
        # quality at the cost of some GPU memory.
        if tier["nvenc_multipass"] != "disabled":
            args += ["-multipass", tier["nvenc_multipass"]]

        # Lookahead — allows the encoder to analyse future frames for
        # better bit allocation.  Uses extra VRAM proportional to the
        # surface count × frame size.
        if tier["nvenc_lookahead"]:
            args += ["-lookahead_level", "auto"]

        # Surface count — clamp if the resolution exceeds the tier's
        # recommended max, since each 4K surface uses ~48 MB.
        surfaces = tier["nvenc_surfaces"]
        if w > tier["max_res_width"] or h > tier["max_res_height"]:
            # Each surface at this resolution is larger than the tier
            # assumed; halve the surface count to stay within VRAM.
            surfaces = max(4, surfaces // 2)
            logging.getLogger("VideoExporter").info(
                "Resolution %dx%d exceeds tier max %dx%d; "
                "clamping NVENC surfaces to %d.",
                w, h, tier["max_res_width"], tier["max_res_height"], surfaces,
            )
        args += ["-surfaces", str(surfaces)]

        # Force yuv420p for maximum compatibility.
        args += ["-pix_fmt", "yuv420p"]

        return args

    def _write_srt(self, path: str, max_time: Optional[float] = None) -> None:
        """Write a .srt subtitle file with one cue per typed line.

        Each cue shows the source line currently being typed (resolved
        of backspaces) and stays on screen until the next line starts.
        """
        # Group timeline events by the resolved line they belong to.
        # We walk the display_chars and track the current line + column,
        # recording (start_time, end_time, line_number, line_text) for
        # each line transition.
        # NOTE (v1.5.1): removed a dead `resolved = ...` line whose
        # result was never used — the loop below re-resolves inline
        # because each cue needs the *partial* line state at each
        # transition, not the fully-resolved end-state text.
        line_starts: dict[int, float] = {}
        line_texts: dict[int, str] = {}
        cur_line = 0
        cur_chars: list[str] = []
        line_starts[0] = self.animator.start_pause
        for ts, _, ch in self.animator.timeline:
            if ch == "\b":
                if cur_chars:
                    cur_chars.pop()
            elif ch == "\n":
                line_texts[cur_line] = "".join(cur_chars)
                cur_line += 1
                cur_chars = []
                if cur_line not in line_starts:
                    line_starts[cur_line] = ts
            else:
                cur_chars.append(ch)
            line_texts[cur_line] = "".join(cur_chars)

        # Sort lines by start time.
        ordered = sorted(line_starts.items())
        cues = []
        for i, (ln, start) in enumerate(ordered):
            end = ordered[i + 1][1] if i + 1 < len(ordered) else self.animator.duration()
            if max_time is not None:
                end = min(end, max_time)
            text = line_texts.get(ln, "").rstrip()
            if not text:
                continue
            # Show the line number + text. Escape newlines for SRT.
            cues.append((start, end, f"[{ln + 1}] {text}"))

        if not cues:
            return

        def _fmt(t: float) -> str:
            ms = int(t * 1000)
            h, ms = divmod(ms, 3600_000)
            m, ms = divmod(ms, 60_000)
            s, ms = divmod(ms, 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        with open(path, "w", encoding="utf-8") as f:
            for i, (start, end, text) in enumerate(cues, 1):
                f.write(f"{i}\n{_fmt(start)} --> {_fmt(end)}\n{text}\n\n")

    def _qimg_to_raw_rgb(self, qimg: QImage) -> bytes:
        """Convert a QImage to raw RGB24 bytes for FFmpeg.

        Fast path: when the image is already Format_RGB32 with no
        scanline padding (the common case produced by CodeRenderer),
        we read the buffer directly and rearrange BGRA → RGB via numpy
        slicing, avoiding the expensive ``convertToFormat`` call.

        PERF (v1.6): pre-allocate a reusable output numpy array
        (``_raw_buf``) so we avoid allocating a new ~6 MB array
        every frame.  The buffer is sized to the renderer's
        width × height × 3 and reused via ``np.copyto``.
        """
        w, h = qimg.width(), qimg.height()
        bpl = qimg.bytesPerLine()

        if qimg.format() == QImage.Format_RGB32 and bpl == w * 4:
            ptr = qimg.constBits()
            if hasattr(ptr, "setsize"):
                ptr.setsize(h * bpl)
                # RGB32 on little-endian is stored as B, G, R, A.
                arr = np.array(ptr, dtype=np.uint8).reshape((h, w, 4))
                # PERF (v1.7): copy BGRA data into the pre-allocated output
                # buffer and reverse channels in a single pass, instead of
                # creating a non-contiguous slice view (arr[:, :, 2::-1])
                # and then copying it.  The old approach created a view with
                # negative stride, which required an extra copy when writing
                # to the pre-allocated buffer or calling tobytes().  The new
                # approach writes directly into the output buffer in one pass.
                buf = self._raw_buf
                if buf is not None and buf.shape == (h, w, 3):
                    # Direct channel swap into the pre-allocated buffer.
                    buf[:, :, 0] = arr[:, :, 2]  # R
                    buf[:, :, 1] = arr[:, :, 1]  # G
                    buf[:, :, 2] = arr[:, :, 0]  # B
                    return buf.tobytes()
                # Fallback: no pre-allocated buffer (wrong size).
                out = np.empty((h, w, 3), dtype=np.uint8)
                out[:, :, 0] = arr[:, :, 2]  # R
                out[:, :, 1] = arr[:, :, 1]  # G
                out[:, :, 2] = arr[:, :, 0]  # B
                return out.tobytes()

        # Fallback: explicit conversion to RGB888.
        qimg = qimg.convertToFormat(QImage.Format_RGB888)
        w, h = qimg.width(), qimg.height()
        bpl = qimg.bytesPerLine()
        ptr = qimg.constBits()

        if isinstance(ptr, memoryview):
            raw = ptr.tobytes()
            if len(raw) < h * bpl:
                return self._qimg_to_raw_rgb_scanline(qimg, w, h, bpl)
        elif hasattr(ptr, "setsize"):
            ptr.setsize(h * bpl)
            arr = np.array(ptr, dtype=np.uint8).reshape((h, bpl))
            if bpl != w * 3:
                arr = arr[:, : w * 3]
            return np.ascontiguousarray(arr).tobytes()
        else:
            raw = ptr.tobytes() if hasattr(ptr, "tobytes") else bytes(ptr)

        raw = raw[: h * bpl]
        if bpl == w * 3:
            return raw
        arr = np.frombuffer(raw, dtype=np.uint8).reshape((h, bpl))
        return np.ascontiguousarray(arr[:, : w * 3]).tobytes()

    @staticmethod
    def _qimg_to_raw_rgb_scanline(qimg: QImage, w: int, h: int, bpl: int) -> bytes:
        rows = []
        for y in range(h):
            scan = qimg.scanLine(y)
            if isinstance(scan, memoryview):
                rows.append(scan.tobytes()[: w * 3])
            elif hasattr(scan, "setsize"):
                scan.setsize(bpl)
                rows.append(bytes(scan)[: w * 3])
            else:
                rows.append(bytes(scan)[: w * 3])
        return b"".join(rows)

    def _render_frame_at(
        self, t: float, blink_period: float = 0.53,
        scratch: Optional[QImage] = None,
    ) -> QImage:
        nv = self.animator.visible_at(t)
        cur_vis = True
        # Find the timestamp of the last visible event.
        # BUG FIX: the previous v1.5.1 optimisation assumed
        # ``timeline[k] == (t_k, k, ch_k)`` — i.e. the event at index
        # k always has display_index == k.  This is FALSE: the timeline
        # includes typo + backspace events that push display_index ahead
        # of the timeline index.  Indexing ``timeline[nv - 1]`` would
        # return a WRONG event whose timestamp has nothing to do with
        # when the nv-th character appeared.  The correct O(log n)
        # approach is to bisect the precomputed _timestamps array,
        # which the main window's _render_at already does correctly.
        last_ts = 0.0
        if nv > 0:
            idx = bisect.bisect_right(self.animator._timestamps, t)
            if idx > 0:
                last_ts = self.animator.timeline[idx - 1][0]
        since = t - last_ts
        if since > 0.25:
            cur_vis = (int(since / blink_period) % 2) == 0

        pressed_key: Optional[str] = None
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
        # Let the renderer compute live stats for the overlay.
        self.renderer.current_time = t
        return self.renderer.render_frame(
            self.animator.display_chars, nv, cur_vis, target=scratch
        )

    # ── main run ──────────────────────────────────────────────────────
    def run(self) -> None:  # noqa: D401  (QThread override)
        tmp = None
        try:
            self.logger.info(
                "╔══ Export started ════════════════════════════════════════════════"
            )
            self.logger.info("  Codec profile : %s", self.codec_profile)
            self.logger.info("  Output file  : %s", self.output)
            self.logger.info("  Resolution   : %dx%d", self.renderer.width, self.renderer.height)
            self.logger.info("  FPS          : %d", self.fps)
            self.logger.info("  Sound profile: %s", self.sound_gen.profile if self.sound_gen else "(none)")
            self.logger.info("  Volume       : %.0f%%", self.volume * 100)
            self.logger.info(
                "╚═══════════════════════════════════════════════════════════════"
            )

            os.makedirs(TMP_DIR, exist_ok=True)
            tmp = tempfile.mkdtemp(dir=TMP_DIR, prefix="export_")
            self.logger.debug("Temporary directory: %s", tmp)
            aud_path = os.path.join(tmp, "audio.wav")

            total = self.animator.duration()
            self.logger.info("Animation duration: %.2f seconds (%d characters)",
                             total, len(self.animator.display_chars))

            # ── YouTube Shorts duration cap ────────────────────────────
            # If a max_duration is set (e.g. 60s for Shorts), truncate
            # the export to that length. We emit a warning so the user
            # knows content was cut.
            is_short = "Short" in self.codec_profile
            effective_max = self.max_duration
            if is_short and effective_max is None:
                effective_max = YOUTUBE_SHORT_MAX_DURATION
            if effective_max is not None and total > effective_max:
                self.logger.warning(
                    "Source duration %.1fs exceeds limit %.0fs; truncating.",
                    total, effective_max,
                )
                self.status.emit(
                    f"Note: source is {total:.1f}s; truncating to "
                    f"{effective_max:.0f}s (YouTube Shorts limit)."
                )
                total = effective_max

            n_frames = max(1, int(total * self.fps))
            self.logger.info("Total frames to render: %d (%.2fs × %d fps)", n_frames, total, self.fps)

            blink_period = self.renderer.CURSOR_BLINK_PERIOD
            w, h = self.renderer.width, self.renderer.height

            # ── YouTube Shorts aspect-ratio warning ───────────────────
            if is_short and not is_short_resolution(w, h):
                self.logger.warning(
                    "YouTube Short selected but resolution %dx%d is not vertical 9:16.", w, h
                )
                self.status.emit(
                    f"Warning: YouTube Short selected but resolution is "
                    f"{w}x{h} (not vertical 9:16). Consider switching to "
                    f"'YouTube Short (9:16)' in the Resolution dropdown."
                )

            is_gif = "GIF" in self.codec_profile
            has_audio = (self.sound_gen is not None and not is_gif)

            # Check FFmpeg BEFORE expensive audio generation.
            if not self._check_ffmpeg():
                self.logger.critical("FFmpeg not found on PATH — cannot export.")
                self.error.emit("FFmpeg is required for exports but was not found on PATH.")
                shutil.rmtree(tmp, ignore_errors=True)
                return

            if has_audio:
                self.logger.info(
                    "Generating audio track (%s, volume %.0f%%)...",
                    self.sound_gen.profile, self.volume * 100,
                )
                # v1.9: Estimate audio RAM usage so users can anticipate
                # memory pressure on long exports.
                est_duration = self.animator.duration()
                est_samples = int(est_duration * 44100)
                # float32 mix buffers (L+R) + limiter envelope + stereo int16
                est_audio_mb = (est_samples * 4 * 2 + est_samples * 2) / (1024 * 1024)
                self.logger.info(
                    "Estimated audio memory: ~%.0f MB (%.1f s, %d samples, float32 mix)",
                    est_audio_mb, est_duration, est_samples,
                )
                t0 = _time.perf_counter()
                # When truncating for Shorts, only include audio up to
                # the truncated duration.
                if effective_max is not None and effective_max < self.animator.duration():
                    char_ts = [
                        (ts, ch) for ts, ch in self.animator.char_timestamps()
                        if ts <= effective_max
                    ]
                    self.logger.debug("Audio: using %d/%d timestamps (truncated)",
                                     len(char_ts), len(self.animator.char_timestamps()))
                    self.sound_gen.generate_audio_track(char_ts, aud_path, self.volume)
                else:
                    self.sound_gen.generate_audio_track(
                        self.animator.char_timestamps(), aud_path, self.volume
                    )
                has_audio = os.path.exists(aud_path) and os.path.getsize(aud_path) > 0
                if has_audio:
                    aud_size_mb = os.path.getsize(aud_path) / (1024 * 1024)
                    self.logger.info(
                        "Audio track generated in %.2fs (%.2f MB)",
                        _time.perf_counter() - t0, aud_size_mb,
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
                shutil.rmtree(tmp, ignore_errors=True)
                return

            # Write the sidecar .srt subtitle file if requested.
            if self.subtitle_path:
                try:
                    self.logger.info("Writing subtitle file: %s", self.subtitle_path)
                    self._write_srt(self.subtitle_path, max_time=total)
                    self.status.emit(f"Subtitles: {self.subtitle_path}")
                    self.logger.info("Subtitles written successfully.")
                except Exception as e:
                    self.logger.warning("Failed to write subtitles: %s", e)

            self.logger.info("Export complete → %s", self.output)
            self.finished_ok.emit(self.output)
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception as e:
            self.logger.error("Export failed: %s", e, exc_info=True)
            self.error.emit(str(e))
            # Remove corrupt partial output
            if os.path.exists(self.output):
                try:
                    os.remove(self.output)
                except OSError:
                    pass
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)

    # ── ffmpeg piping ─────────────────────────────────────────────────
    def _export_ffmpeg_pipe(
        self,
        tmp: str,
        aud_path: str,
        n_frames: int,
        w: int,
        h: int,
        has_audio: bool,
        blink_period: float,
    ) -> None:
        self.logger.debug("Building FFmpeg command for %s...", self.codec_profile)

        # ── Smart GPU detection (once per export) ────────────────────
        gpu_name, gpu_total_mb, gpu_free_mb = self._detect_gpu_info()
        gpu_tier = None
        frame_chunk = 1  # default: write every frame (software path)
        if gpu_total_mb > 0:
            gpu_tier = self._smart_gpu_tier(gpu_total_mb)
            frame_chunk = gpu_tier["frame_chunk"]
            self.logger.info(
                "GPU detected: %s (%d MB total, %d MB free) → tier: %s",
                gpu_name, gpu_total_mb, gpu_free_mb, gpu_tier["name"],
            )
            self.gpu_info.emit(
                f"{gpu_name} | {gpu_total_mb} MB | Tier: {gpu_tier['name']}"
            )
        else:
            self.logger.debug("No NVIDIA GPU detected (or nvidia-smi unavailable).")

        cmd = [
            "ffmpeg", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{w}x{h}", "-r", str(self.fps),
            "-i", "pipe:0",
        ]

        is_nvenc = False  # track whether we're using NVENC for chunking

        if "GIF" in self.codec_profile:
            self.logger.info("Codec: GIF (fps capped at %d, palette-based dithering)", min(self.fps, 15))
            cmd += [
                "-vf",
                f"fps={min(self.fps, 15)},scale={w}:-1:flags=lanczos,"
                f"split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
            ]
        elif "WebM" in self.codec_profile:
            # BUG FIX (v1.5.1): the WebM branch previously ignored the
            # generated audio track entirely — ``has_audio`` was True,
            # ``generate_audio_track`` wrote a WAV, but no ``-i aud_path``
            # or ``-c:a`` flags were ever added to the ffmpeg command,
            # so the audio was generated and silently discarded. We now
            # wire the audio input and use libopus (the modern WebM
            # audio codec) at 128 kbps stereo.
            if has_audio:
                cmd += ["-i", aud_path]
            self.logger.info("Codec: WebM (VP9 video, CRF 30; Opus audio)")
            cmd += ["-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0",
                    "-pix_fmt", "yuv420p"]
            if has_audio:
                cmd += ["-c:a", "libopus", "-b:a", "128k", "-ac", "2"]
        elif "YouTube" in self.codec_profile:
            # ── YouTube-recommended SDR encoding ──────────────────────
            # Uses H.264 High profile with the bitrate and level that
            # YouTube officially recommends for the current resolution
            # and frame rate. See config.YOUTUBE_SDR_BITRATES.
            if has_audio:
                cmd += ["-i", aud_path]

            video_bitrate, level_x10 = youtube_bitrate_for(w, h, self.fps)
            level_str = f"{level_x10 // 10}.{level_x10 % 10}"
            bitrate_kbps = video_bitrate // 1000

            is_short = "Short" in self.codec_profile
            profile_label = "YouTube Short" if is_short else "YouTube Video"
            self.logger.info(
                "%s: %dx%d @ %dfps → %d kbps video, H.264 level %s",
                profile_label, w, h, self.fps, bitrate_kbps, level_str,
            )
            self.status.emit(
                f"{profile_label}: {w}x{h} @ {self.fps}fps, "
                f"{bitrate_kbps} kbps H.264 (level {level_str})"
            )

            # Pick the encoder: hardware-accelerated if requested and
            # available, otherwise the software libx264 default.
            hw = self._detect_hw_encoder() if self.use_hw_accel else None
            if hw is not None:
                enc_name, _hw_preset = hw
                if "nvenc" in enc_name and gpu_tier is not None:
                    # ── Smart NVENC path: use tier-tuned parameters ───
                    is_nvenc = True
                    self.logger.info(
                        "Smart NVENC: tier=%s, preset=%s, surfaces=%d, "
                        "multipass=%s, lookahead=%s, chunk=%d frames",
                        gpu_tier["name"], gpu_tier["nvenc_preset"],
                        gpu_tier["nvenc_surfaces"],
                        gpu_tier["nvenc_multipass"],
                        gpu_tier["nvenc_lookahead"],
                        frame_chunk,
                    )
                    self.status.emit(
                        f"NVENC ({gpu_tier['name']}): {gpu_tier['nvenc_preset']} preset, "
                        f"{gpu_tier['nvenc_surfaces']} surfaces, chunk={frame_chunk}"
                    )
                    cmd += ["-c:v", enc_name]
                    cmd += ["-profile:v", "high", "-level", level_str]
                    cmd += self._build_nvenc_args(gpu_tier, w, h, bitrate_kbps)
                    cmd += ["-movflags", "+faststart"]
                else:
                    # Non-NVENC hardware (QSV, AMF, VideoToolbox): use
                    # the original generic hardware path.
                    self.logger.info("Hardware encoder detected: %s (non-NVENC, using generic hw path)", enc_name)
                    cmd += [
                        "-c:v", enc_name,
                        "-profile:v", "high",
                        "-level", level_str,
                        "-pix_fmt", "yuv420p",
                        "-b:v", f"{bitrate_kbps}k",
                        "-maxrate", f"{bitrate_kbps}k",
                        "-bufsize", f"{bitrate_kbps * 2}k",
                    ]
                    if "qsv" in enc_name:
                        cmd += ["-rc_mode", "vbr"]
                    elif "amf" in enc_name:
                        cmd += ["-rc_mode", "VBR_PEAK"]
                    cmd += ["-movflags", "+faststart"]
                    if _hw_preset:
                        cmd += ["-preset", _hw_preset]
            else:
                if self.use_hw_accel:
                    self.logger.info(
                        "Hardware acceleration requested but no GPU encoder "
                        "found; falling back to libx264."
                    )
                # For YouTube we use a target bitrate (two-pass-ish VBR)
                # rather than pure CRF, so the upload meets YouTube's
                # recommended quality floor without bloating file size.
                cmd += [
                    "-c:v", "libx264",
                    "-profile:v", "high",
                    "-level", level_str,
                    "-preset", self.preset,
                    "-b:v", f"{bitrate_kbps}k",
                    "-maxrate", f"{bitrate_kbps}k",
                    "-bufsize", f"{bitrate_kbps * 2}k",
                    "-pix_fmt", "yuv420p",
                    "-bf", "2",
                    "-refs", "4",
                    "-g", str(self.fps * 2),  # GOP = 2s (keyframe every 2s)
                    "-movflags", "+faststart",
                ]

            # Audio: YouTube recommends AAC stereo at 128 kbps for SDR.
            if has_audio:
                self.logger.debug("Audio codec: AAC 128kbps stereo (YouTube SDR)")
                cmd += ["-c:a", "aac", "-b:a", "128k", "-ac", "2"]

            # ── Metadata tags (embedded in the MP4) ──────────────────
            # YouTube reads the title and description from the file's
            # metadata on upload (though most of the visible metadata
            # is set in the YouTube upload form). We still embed them
            # so the file is self-describing.
            if self.metadata_title:
                cmd += ["-metadata", f"title={self.metadata_title}"]
            if self.metadata_description:
                cmd += ["-metadata", f"description={self.metadata_description}"]
            # Tag the encoder so the file is identifiable as a YouTube-
            # optimised export.
            cmd += ["-metadata", f"encoder=CodeTypingVideoGenerator ({profile_label})"]
        else:  # MP4 (H.264)
            if has_audio:
                cmd += ["-i", aud_path]

            # Pick the encoder: hardware-accelerated if requested and
            # available, otherwise the software libx264 default.
            hw = self._detect_hw_encoder() if self.use_hw_accel else None
            if hw is not None:
                enc_name, _hw_preset = hw
                if "nvenc" in enc_name and gpu_tier is not None:
                    # ── Smart NVENC path: use tier-tuned parameters ───
                    is_nvenc = True
                    self.logger.info(
                        "Smart NVENC: tier=%s, preset=%s, surfaces=%d, "
                        "multipass=%s, lookahead=%s, chunk=%d frames",
                        gpu_tier["name"], gpu_tier["nvenc_preset"],
                        gpu_tier["nvenc_surfaces"],
                        gpu_tier["nvenc_multipass"],
                        gpu_tier["nvenc_lookahead"],
                        frame_chunk,
                    )
                    self.status.emit(
                        f"NVENC ({gpu_tier['name']}): {gpu_tier['nvenc_preset']} preset, "
                        f"{gpu_tier['nvenc_surfaces']} surfaces, chunk={frame_chunk}"
                    )
                    cmd += ["-c:v", enc_name]
                    # Use CRF-based quality for standard MP4 (no target bitrate).
                    nvenc_args = self._build_nvenc_args(gpu_tier, w, h)
                    # Replace the default cq=20 from _build_nvenc_args with
                    # the user's chosen CRF for standard MP4 exports.
                    nvenc_args = [a for a in nvenc_args if a != "20"]
                    # Insert the user's CRF value after the "-cq" flag.
                    for idx_a in range(len(nvenc_args)):
                        if nvenc_args[idx_a] == "-cq":
                            nvenc_args[idx_a + 1] = str(self.crf)
                            break
                    cmd += nvenc_args
                    cmd += ["-movflags", "+faststart"]
                else:
                    # Non-NVENC hardware: generic path.
                    self.logger.info("Hardware encoder detected: %s (non-NVENC, using generic hw path)", enc_name)
                    self.status.emit(f"Using hardware encoder: {enc_name}")
                    cmd += [
                        "-c:v", enc_name,
                        "-pix_fmt", "yuv420p",
                    ]
                    if "qsv" in enc_name:
                        cmd += ["-rc_mode", "vbr", "-global_quality", str(self.crf * 5)]
                    elif "amf" in enc_name:
                        cmd += ["-rc_mode", "VBR_PEAK", "-quality", str(self.crf)]
                    elif "videotoolbox" in enc_name:
                        cmd += ["-q:v", str(self.crf)]
                    else:
                        cmd += ["-b:v", "0", "-cq", str(self.crf)]
                    cmd += ["-movflags", "+faststart"]
                    if _hw_preset:
                        cmd += ["-preset", _hw_preset]
            else:
                if self.use_hw_accel:
                    self.logger.info(
                        "Hardware acceleration requested but no GPU encoder "
                        "found; falling back to libx264."
                    )
                self.logger.info("Software encoder: libx264 (preset=%s, CRF=%d)", self.preset, self.crf)
                cmd += [
                    "-c:v", "libx264", "-profile:v", "high", "-level", "4.2",
                    "-preset", self.preset, "-crf", str(self.crf),
                    "-pix_fmt", "yuv420p", "-bf", "2", "-refs", "4",
                    "-movflags", "+faststart",
                ]
            if has_audio:
                self.logger.debug("Audio codec: AAC 192kbps stereo")
                cmd += ["-c:a", "aac", "-b:a", "192k"]

        cmd.append(self.output)

        self.logger.debug("FFmpeg command: %s", " ".join(cmd))

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        stderr_chunks: list[bytes] = []

        def _drain() -> None:
            while True:
                chunk = proc.stderr.read(8192)  # type: ignore[union-attr]
                if not chunk:
                    break
                stderr_chunks.append(chunk)

        drain_t = threading.Thread(target=_drain, daemon=True)
        drain_t.start()

        # Reusable scratch image — avoids ~8 MB allocation per frame.
        scratch = QImage(w, h, QImage.Format_RGB32)

        export_start = _time.time()
        frame_size = w * h * 3
        frame_render_total = 0.0

        # ── Frame chunking buffer ───────────────────────────────────
        # Instead of writing each frame individually (one syscall per
        # frame), we buffer N frames and flush them in one write.  This
        # reduces syscall overhead and lets NVENC batch-encode more
        # efficiently.  The chunk size is determined by the GPU tier
        # (4 frames on GTX 1080-class, up to 12 on RTX 4090-class).
        # For non-NVENC paths, chunk=1 (write every frame immediately).
        chunk_buf = bytearray(frame_size * frame_chunk) if frame_chunk > 1 else None
        chunk_fill = 0  # number of frames currently in the buffer
        effective_chunk = frame_chunk  # may be reduced under VRAM pressure

        # ── VRAM monitoring state ───────────────────────────────────
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

                t = fi / self.fps
                rt0 = _time.perf_counter()
                qimg = self._render_frame_at(t, blink_period, scratch=scratch)
                raw = self._qimg_to_raw_rgb(qimg)
                frame_render_total += _time.perf_counter() - rt0

                if len(raw) != frame_size:
                    raise RuntimeError(
                        f"Frame {fi}: size {len(raw)} != expected {frame_size}"
                    )

                # ── Write frame (chunked or immediate) ───────────────
                if chunk_buf is not None:
                    # Buffer the frame data.
                    chunk_buf[chunk_fill * frame_size : (chunk_fill + 1) * frame_size] = raw
                    chunk_fill += 1
                    if chunk_fill >= effective_chunk or fi == n_frames - 1:
                        # Flush the buffer to FFmpeg.
                        try:
                            proc.stdin.write(
                                bytes(chunk_buf[: chunk_fill * frame_size])
                            )  # type: ignore[union-attr]
                        except BrokenPipeError:
                            self.logger.warning(
                                "Broken pipe from FFmpeg at frame %d — FFmpeg may have exited early.",
                                fi,
                            )
                            break
                        chunk_fill = 0
                else:
                    # Non-chunked path (software encoding or non-NVENC).
                    try:
                        proc.stdin.write(raw)  # type: ignore[union-attr]
                    except BrokenPipeError:
                        self.logger.warning(
                            "Broken pipe from FFmpeg at frame %d — FFmpeg may have exited early.",
                            fi,
                        )
                        break

                # ── VRAM monitoring (NVENC only) ─────────────────────
                if (
                    is_nvenc
                    and total_vram_for_monitor > 0
                    and fi > 0
                    and fi % GPU_VRAM_POLL_INTERVAL == 0
                ):
                    free_mb = self._poll_gpu_free_vram()
                    if free_mb > 0:
                        free_frac = free_mb / total_vram_for_monitor
                        if free_frac < 0.05 and not critical_vram_warned:
                            self.logger.warning(
                                "CRITICAL: GPU VRAM critically low (%d MB free / %d MB total, %.1f%%). "
                                "Close other GPU applications to avoid encoding failures.",
                                free_mb, total_vram_for_monitor, free_frac * 100,
                            )
                            self.status.emit(
                                "WARNING: GPU VRAM critically low! Close other GPU apps."
                            )
                            critical_vram_warned = True
                            # Emergency: reduce chunk size to minimum.
                            if effective_chunk > 1:
                                effective_chunk = 1
                                chunk_buf = None  # disable chunking
                                self.logger.info(
                                    "VRAM critical — disabled frame chunking to reduce GPU pressure."
                                )
                        elif free_frac < GPU_VRAM_LOW_WATERMARK and not low_vram_warned:
                            self.logger.warning(
                                "GPU VRAM running low (%d MB free / %d MB total, %.1f%%). "
                                "Consider closing other GPU applications for best performance.",
                                free_mb, total_vram_for_monitor, free_frac * 100,
                            )
                            self.status.emit(
                                f"GPU VRAM low ({free_mb} MB free). Closing other GPU apps is recommended."
                            )
                            low_vram_warned = True
                            # Reduce chunk size by half to ease GPU memory pressure.
                            if effective_chunk > 1:
                                effective_chunk = max(1, effective_chunk // 2)
                                self.logger.info(
                                    "VRAM low — reduced frame chunk to %d.", effective_chunk
                                )
                                if effective_chunk == 1:
                                    chunk_buf = None

                pct = int((fi + 1) / n_frames * 100)
                self.progress.emit(pct)
                if fi % max(1, n_frames // 20) == 0 and fi > 0:
                    elapsed = _time.time() - export_start
                    eta = elapsed / (fi + 1) * (n_frames - fi - 1)
                    self.logger.debug(
                        "Progress: %d%% (%d/%d frames, %.1fs elapsed, ETA %ds)",
                        pct, fi + 1, n_frames, elapsed, int(eta),
                    )
                    self.status.emit(f"Encoding... {pct}% (ETA: {int(eta)}s)")

            # Flush any remaining buffered frames.
            if chunk_buf is not None and chunk_fill > 0:
                try:
                    proc.stdin.write(
                        bytes(chunk_buf[: chunk_fill * frame_size])
                    )  # type: ignore[union-attr]
                except BrokenPipeError:
                    pass

            try:
                proc.stdin.close()  # type: ignore[union-attr]
            except Exception:
                pass
            proc.wait(timeout=600)
            drain_t.join(timeout=5)
            if proc.returncode != 0:
                err = b"".join(stderr_chunks).decode("utf-8", errors="ignore")[-800:]
                self.logger.error("FFmpeg exited with code %d.\n%s", proc.returncode, err)
                raise RuntimeError(f"FFmpeg encoding failed: {err}")

            # Report render throughput.
            total_export_time = _time.time() - export_start
            if n_frames > 0 and frame_render_total > 0:
                avg_ms = frame_render_total / n_frames * 1000
                avg_fps = n_frames / frame_render_total
                self.logger.info(
                    "Render stats: %d frames in %.2fs (%.1f ms/frame, %.1f fps render throughput)",
                    n_frames, frame_render_total, avg_ms, avg_fps,
                )
                self.status.emit(
                    f"Rendered {n_frames} frames at {avg_fps:.1f} fps ({avg_ms:.1f} ms/frame)"
                )

            # Report total export wall-clock time + output size.
            out_size = os.path.getsize(self.output) if os.path.exists(self.output) else 0
            out_size_mb = out_size / (1024 * 1024)
            self.logger.info(
                "Export finished in %.1fs total → %s (%.2f MB)",
                total_export_time, self.output, out_size_mb,
            )
        except Exception:
            self.logger.exception("Error during frame encoding loop")
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
            raise


# ═══════════════════════════════════════════════════════════════════════════
# BATCH RENDERING
# ═══════════════════════════════════════════════════════════════════════════
# The classes below implement the batch rendering engine: a queue of code
# files (or inline snippets) exported sequentially, reusing one sound
# generator across all items and building a fresh CodeRenderer +
# TypingAnimator per item (since each file has different content and thus
# different cache state).
#
# The BatchExporter runs in its own QThread and constructs a VideoExporter
# per item, calling .run() directly (synchronous, in the batch thread).
# The VideoExporter's signals fire from the batch thread and are relayed
# to the main thread via Qt's queued connections.
# ═══════════════════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class BatchItem:
    """One item in the batch queue.

    Either ``file_path`` (read code from disk) or ``inline_code`` (use
    the provided string) must be set. ``file_path`` takes precedence.
    """

    file_path: Optional[str] = None
    inline_code: Optional[str] = None
    display_name: str = ""
    # Optional per-item overrides (None = use batch defaults).
    language_override: Optional[str] = None
    title_override: Optional[str] = None
    output_name: Optional[str] = None

    # Runtime state (filled in during export).
    status: str = "Pending"  # Pending / Rendering / Done / Failed / Skipped
    error: Optional[str] = None
    output_path: Optional[str] = None

    def resolve_display_name(self) -> str:
        """Return a human-friendly name for list display."""
        if self.display_name:
            return self.display_name
        if self.file_path:
            return os.path.basename(self.file_path)
        return "(inline snippet)"


@dataclass
class BatchSettings:
    """Snapshot of all export-relevant settings from the main window.

    Captured once when the batch dialog opens, so changing the main
    window's settings during a batch does not affect in-flight items.
    """

    # ── Renderer ────────────────────────────────────────────────────
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
    watermark_text: str = ""
    watermark_image: Optional[str] = None
    watermark_position: str = "Bottom-Right"
    watermark_opacity: float = 0.4
    bg_image: Optional[str] = None
    resolution: str = "YouTube 1080p"

    # ── Animator ────────────────────────────────────────────────────
    wpm: int = 100
    typo_rate: float = 0.01
    start_pause: float = 1.0
    end_pause: float = 2.0
    speed_ramp: str = "None"
    ramp_strength: float = 0.5
    burst_typing: bool = True
    thinking_pauses: bool = True
    fatigue: float = 0.0

    # ── Export ──────────────────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────────────────
# Batch exporter thread
# ─────────────────────────────────────────────────────────────────────────

class BatchExporter(QThread):
    """Sequentially export a queue of code files to video.

    Signals
    -------
    item_started(index, name)
        Emitted when an item begins rendering.
    item_progress(pct)
        0-100 progress for the *current* item.
    item_finished(index, output_path)
        Emitted when an item completes successfully.
    item_failed(index, error_message)
        Emitted when an item fails.
    batch_progress(pct)
        0-100 overall progress across all items.
    status(msg)
        Human-readable status text for the status bar.
    batch_finished(succeeded, total)
        Emitted when the entire batch is done (or cancelled).
    """

    item_started = Signal(int, str)
    item_progress = Signal(int)
    item_finished = Signal(int, str)
    item_failed = Signal(int, str)
    batch_progress = Signal(int)
    status = Signal(str)
    batch_finished = Signal(int, int)

    def __init__(
        self,
        items: List[BatchItem],
        settings: BatchSettings,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.items = items
        self.settings = settings
        self.logger = logging.getLogger("BatchExporter")
        self._cancel = False
        self._current_exporter: Optional[VideoExporter] = None
        self._sound_gen: Optional[TypingSoundGenerator] = None

    def cancel(self) -> None:
        """Cancel the batch: stops the current item and skips the rest."""
        self._cancel = True
        if self._current_exporter is not None:
            self._current_exporter.cancel()

    # ── main run loop ───────────────────────────────────────────────
    def run(self) -> None:
        total = len(self.items)
        if total == 0:
            self.batch_finished.emit(0, 0)
            return

        succeeded = 0
        failed = 0
        skipped = 0

        # Build the sound generator once (it's expensive to construct
        # and is read-only after init, so safe to reuse across items).
        try:
            self._sound_gen = TypingSoundGenerator(
                profile=self.settings.sound_profile
            )
        except Exception as e:
            self.logger.error("Failed to init sound generator: %s", e)
            self._sound_gen = None

        for i, item in enumerate(self.items):
            if self._cancel:
                item.status = "Skipped"
                skipped += 1
                continue

            self.item_started.emit(i, item.resolve_display_name())
            self.status.emit(
                f"[{i + 1}/{total}] Rendering: {item.resolve_display_name()}"
            )
            item.status = "Rendering"

            try:
                output_path = self._export_item(item, i, total)
                if output_path is not None:
                    item.status = "Done"
                    item.output_path = output_path
                    succeeded += 1
                    self.item_finished.emit(i, output_path)
                else:
                    # Cancelled mid-item.
                    item.status = "Skipped"
                    skipped += 1
            except Exception as e:
                self.logger.error(
                    "Item %d (%s) failed: %s",
                    i, item.resolve_display_name(), e, exc_info=True,
                )
                item.status = "Failed"
                item.error = str(e)
                failed += 1
                self.item_failed.emit(i, str(e))

            # Update overall progress (count completed items).
            pct = int((i + 1) / total * 100)
            self.batch_progress.emit(pct)

        self._sound_gen = None
        self._current_exporter = None

        summary = f"Batch complete: {succeeded}/{total} succeeded"
        if failed:
            summary += f", {failed} failed"
        if skipped:
            summary += f", {skipped} skipped"
        self.status.emit(summary)
        self.batch_finished.emit(succeeded, total)

    # ── per-item export ─────────────────────────────────────────────
    def _export_item(
        self, item: BatchItem, index: int, total: int
    ) -> Optional[str]:
        """Export one item. Returns the output path on success, or
        ``None`` if the batch was cancelled mid-item."""
        s = self.settings

        # ── Read source code ──────────────────────────────────────────
        if item.file_path is not None:
            with open(item.file_path, "r", encoding="utf-8", errors="replace") as f:
                code = f.read()
        elif item.inline_code is not None:
            code = item.inline_code
        else:
            raise ValueError("BatchItem has neither file_path nor inline_code")

        if not code.strip():
            raise ValueError("Source code is empty")

        # ── Determine language ────────────────────────────────────────
        if item.language_override:
            language = item.language_override
        elif item.file_path:
            ext = os.path.splitext(item.file_path)[1].lower()
            language = EXT_TO_LANGUAGE.get(ext, s.language)
        else:
            language = s.language

        # ── Determine title ───────────────────────────────────────────
        if item.title_override:
            title = item.title_override
        elif item.file_path:
            title = f"{os.path.basename(item.file_path)} \u2014 Code Editor"
        else:
            title = s.title_text

        # ── Determine output path ─────────────────────────────────────
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        if item.output_name:
            base = item.output_name
        elif item.file_path:
            base = os.path.splitext(os.path.basename(item.file_path))[0]
        else:
            base = f"snippet_{index + 1:03d}"

        fmt = s.codec_profile
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
        # Avoid overwriting existing files: append _2, _3, etc.
        if os.path.exists(output_path):
            counter = 2
            while os.path.exists(
                os.path.join(OUTPUT_DIR, f"{base}_{counter}{ext}")
            ):
                counter += 1
            output_path = os.path.join(OUTPUT_DIR, f"{base}_{counter}{ext}")

        # ── Resolution ────────────────────────────────────────────────
        w, h = RESOLUTION_PRESETS.get(s.resolution, (1920, 1080))

        # ── Font size (auto-fit or manual) ────────────────────────────
        if s.autofit:
            code_lines = code.count("\n") + 1
            target = s.max_lines or None
            font_size = CodeRenderer.auto_font_size(
                code_lines=code_lines,
                width=w, height=h,
                padding=s.padding,
                show_window_chrome=s.show_window_chrome,
                show_line_numbers=s.show_line_numbers,
                show_keyboard=s.show_keyboard,
                tab_size=s.tab_size,
                target_lines=target,
                keyboard_position=s.keyboard_position,
                keyboard_scale=s.keyboard_scale,  
                keyboard_gap=s.keyboard_gap,      
                code=code,                        
                font_family=s.font_family,        
            )
        else:
            font_size = s.font_size

        # ── Build renderer ────────────────────────────────────────────
        renderer = CodeRenderer(
            width=w, height=h,
            theme_name=s.theme_name,
            font_family=s.font_family,
            font_size=font_size,
            show_line_numbers=s.show_line_numbers,
            show_window_chrome=s.show_window_chrome,
            padding=s.padding,
            tab_size=s.tab_size,
            title_text=title,
            language=language,
            show_keyboard=s.show_keyboard,
            keyboard_gap=s.keyboard_gap,
            keyboard_scale=s.keyboard_scale,
            keyboard_layout=s.keyboard_layout,
            keyboard_position=s.keyboard_position,
            keyboard_opacity=s.keyboard_opacity,
            keyboard_radius=s.keyboard_radius,
            show_stats=s.show_stats,
            stats_position=s.stats_position,
            watermark_text=s.watermark_text,
            watermark_image=s.watermark_image,
            watermark_position=s.watermark_position,
            watermark_opacity=s.watermark_opacity,
        )
        if s.bg_image:
            renderer.set_background_image(s.bg_image)

        # ── Build animator ────────────────────────────────────────────
        animator = TypingAnimator(
            code,
            base_wpm=s.wpm,
            humanize=True,
            typo_rate=s.typo_rate,
            start_pause=s.start_pause,
            end_pause=s.end_pause,
            speed_ramp=s.speed_ramp,
            ramp_strength=s.ramp_strength,
            burst_typing=s.burst_typing,
            thinking_pauses=s.thinking_pauses,
            fatigue=s.fatigue,
        )
        renderer.animator_ref = animator

        # ── Subtitle path ─────────────────────────────────────────────
        subtitle_path: Optional[str] = None
        if s.export_srt and "GIF" not in fmt:
            sub_base, _ = os.path.splitext(output_path)
            subtitle_path = sub_base + ".srt"

        # ── Build and run the VideoExporter ───────────────────────────
        # We construct a VideoExporter but call .run() directly instead
        # of .start(). This runs the export synchronously in the batch
        # thread. The exporter's signals fire from here; lambda
        # connections are direct, so result dict is updated before run()
        # returns. BatchExporter's own signals are emitted from this
        # thread and delivered to the main thread via queued connections.
        exporter = VideoExporter(
            code=code,
            output=output_path,
            renderer=renderer,
            animator=animator,
            fps=s.fps,
            sound_gen=self._sound_gen,
            volume=s.sound_volume,
            codec_profile=s.codec_profile,
            crf=s.crf,
            preset=s.preset,
            subtitle_path=subtitle_path,
            use_hw_accel=s.use_hw_accel,
            metadata_title=s.metadata_title,
            metadata_description=s.metadata_description,
        )
        self._current_exporter = exporter

        # Collect results via direct-connected lambdas.
        result = {"ok": False, "error": None, "path": None}

        def _on_progress(pct: int) -> None:
            self.item_progress.emit(pct)

        def _on_status(msg: str) -> None:
            self.status.emit(
                f"[{index + 1}/{total}] {item.resolve_display_name()}: {msg}"
            )

        def _on_done(path: str) -> None:
            result["ok"] = True
            result["path"] = path

        def _on_error(msg: str) -> None:
            result["error"] = msg

        exporter.progress.connect(_on_progress)
        exporter.status.connect(_on_status)
        exporter.finished_ok.connect(_on_done)
        exporter.error.connect(_on_error)

        # Synchronous export (runs in this batch thread).
        exporter.run()

        self._current_exporter = None

        # Check results.
        if self._cancel:
            return None  # batch was cancelled mid-item
        if result["ok"]:
            return result["path"]
        if result["error"]:
            raise RuntimeError(result["error"])
        raise RuntimeError(
            "Export finished without emitting success or error signal"
        )
