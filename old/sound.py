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
  * ``enter``       — return key (4 variants; includes bell on Typewriter)
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
  * **Filter coefficient cache** (``_FilterCache``): LRU-style cache
    for precomputed filter coefficients, avoiding redundant bilinear
    transform calculations.
  * **NaN-safe normalisation**: ``_normalise`` sanitises input before
    processing, preventing propagation of numerical artifacts.

  *Retained from v3*: vectorised IIR filtering, FFT-based noise
    shaping, FFT convolution reverb, FM-synthesis click transients,
    multi-partial body resonance, spectral tilt, peak limiter, mid-side
    stereo enhancement, frequency-dependent panning.
"""

from __future__ import annotations

import logging
import random
import struct
import wave
from typing import Dict, List, Tuple

import numpy as np


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Advanced DSP helpers  (v3 — vectorised / FFT-accelerated)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _apply_iir(signal: np.ndarray, b: np.ndarray, a: np.ndarray) -> np.ndarray:
    """Apply an IIR filter via truncated impulse response + convolution.

    Instead of a per-sample Python loop (slow), this computes the filter's
    impulse response once (short, ~50-500 samples for typical audio
    coefficients), then delegates the heavy lifting to ``np.convolve``
    which runs in C and auto-selects direct vs FFT convolution.

    For stable filters (poles inside unit circle) the IR decays
    exponentially, so truncation introduces negligible error
    (typically < -120 dB).

    Parameters
    ----------
    signal : 1-D float64 array
    b      : feed-forward coefficients  [b0, b1, ...]
    a      : feed-back coefficients     [1.0, a1, a2, ...]  (a[0] == 1)

    Returns
    -------
    1-D float64 array, same length as *signal*.
    """
    n = len(signal)
    if n == 0:
        return signal.copy()
    nb, na = len(b), len(a)

    # --- Strategy selection ---
    # For short signals or low-order filters, use direct-form IIR (fast,
    # accurate, no truncation).  For longer signals with fast-decaying IRs,
    # use the convolution approach.
    # Threshold: if signal is short or filter order is high enough that
    # the IR would be a large fraction of the signal, use direct form.
    if n < 512 or (na - 1) >= 4:
        # Direct Form I — one-pass Python loop.  Acceptable for short signals.
        x = signal.astype(np.float64)
        out = np.zeros(n, dtype=np.float64)
        for i in range(n):
            yi = b[0] * x[i]
            for j in range(1, nb):
                if i >= j:
                    yi += b[j] * x[i - j]
            for j in range(1, na):
                if i >= j:
                    yi -= a[j] * out[i - j]
            out[i] = yi
        return out

    # --- Convolution approach: compute truncated IR, then np.convolve ---
    # The IR decays exponentially for stable filters (poles inside unit
    # circle).  We truncate at -80 dB (1e-4 of peak) — inaudible error.
    max_ir = min(n, 4096)
    ir = np.zeros(max_ir, dtype=np.float64)
    peak = 0.0
    ir[0] = b[0]
    for i in range(1, max_ir):
        x_i = b[i] if i < nb else 0.0
        fb = 0.0
        for j in range(1, na):
            fb -= a[j] * ir[i - j]
        ir[i] = x_i + fb
        a_abs = abs(ir[i])
        if a_abs > peak:
            peak = a_abs
        # Early exit once IR has decayed below -80 dB of peak.
        if i > 20 and peak > 0 and a_abs < peak * 1e-4:
            ir = ir[:i + 1]
            break
    else:
        ir = ir[:max_ir]

    return np.convolve(signal, ir, mode='full')[:n]


def _butter_lowpass(signal: np.ndarray, cutoff_ratio: float = 0.15,
                    order: int = 2) -> np.ndarray:
    """Second-order Butterworth low-pass filter (all-numpy, no scipy).

    Parameters
    ----------
    signal : 1-D array
    cutoff_ratio : float in (0, 0.5)
        Cutoff as a fraction of the Nyquist frequency.
        0.15 at 44100 Hz  ->  ~3.3 kHz cutoff.
    order : int (1 or 2)
        Filter order.  2 gives a steeper rolloff.

    Implementation: designs biquad (or first-order) coefficients, then
    delegates to :func:`_apply_iir` for convolution-based application.
    """
    wc = np.tan(np.pi * cutoff_ratio)  # pre-warped angular cutoff
    x = signal.astype(np.float64)
    if order == 1:
        b0 = wc / (1.0 + wc)
        a1 = (1.0 - wc) / (1.0 + wc)
        return _apply_iir(x, np.array([b0]), np.array([1.0, a1]))
    # Second-order Butterworth.
    k = wc * wc
    norm = 1.0 / (1.0 + np.sqrt(2) * wc + k)
    b0 = k * norm;  b1 = 2.0 * b0;  b2 = b0
    a1 = 2.0 * (k - 1.0) * norm
    a2 = (1.0 - np.sqrt(2) * wc + k) * norm
    return _apply_iir(x, np.array([b0, b1, b2]), np.array([1.0, a1, a2]))


def _highpass(signal: np.ndarray, cutoff_ratio: float = 0.02) -> np.ndarray:
    """First-order high-pass filter to remove DC and sub-bass rumble.

    Parameters
    ----------
    signal : 1-D array
    cutoff_ratio : float in (0, 0.5)
        Cutoff as fraction of Nyquist.  0.02 at 44100 Hz -> ~442 Hz.
    """
    if cutoff_ratio <= 0 or cutoff_ratio >= 0.5:
        return signal.astype(np.float64)
    wc = np.tan(np.pi * cutoff_ratio)
    b0 = 1.0 / (1.0 + wc)
    a1 = (1.0 - wc) / (1.0 + wc)
    return _apply_iir(signal.astype(np.float64),
                      np.array([b0, -b0]),
                      np.array([1.0, -a1]))


def _bandpass_noise(n: int, rng: np.random.RandomState,
                    lo_hz: float = 2000, hi_hz: float = 5000,
                    sr: int = 44100) -> np.ndarray:
    """Generate band-pass filtered white noise (keycap rattle model).

    Uses :func:`_apply_iir` for both the high-pass and low-pass stages,
    eliminating two Python-level for-loops.
    """
    noise = rng.randn(n).astype(np.float64)
    # High-pass via first-order.
    rc_hp = 1.0 / (2 * np.pi * lo_hz) * sr
    alpha_hp = rc_hp / (1 + rc_hp)
    hp = _apply_iir(noise,
                     np.array([alpha_hp, -alpha_hp]),
                     np.array([1.0, -(1 - alpha_hp)]))
    # Low-pass to set upper bound.
    return _butter_lowpass(hp, min(hi_hz / (sr * 0.5), 0.48), order=2)


def _env_adsr(t: np.ndarray, attack: float = 0.0005, decay: float = 0.02,
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
    # Attack phase: exponential ramp (more natural than linear).
    if attack > 0:
        mask_a = shifted < attack
        if np.any(mask_a):
            # Smooth exponential attack curve.
            env[mask_a] = 1.0 - np.exp(-shifted[mask_a] / (attack * 0.3))
    else:
        mask_a = np.zeros(len(t), dtype=bool)
    # Decay + sustain + release: exponential.
    mask_d = ~mask_a
    if np.any(mask_d):
        post_attack = shifted[mask_d] - attack
        decay_rate = -np.log(max(sustain_level, 0.01)) / max(decay, 0.001)
        env[mask_d] = np.exp(-post_attack * decay_rate)
    return np.clip(env, 0.0, 1.0)


def _spring_ring(t: np.ndarray, freq: float = 5200, decay: float = 800,
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


def _early_reverb(signal: np.ndarray, sr: int = 44100,
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
        delayed = np.zeros_like(out)
        delayed[d:] = out[:-d] * feedback
        out = out + delayed * wet
    return out


def _normalise(signal: np.ndarray, target_db: float = -3.0) -> np.ndarray:
    """Normalise an int16 signal to ``target_db`` below full scale."""
    # Sanitise: replace any NaN/Inf with zero before processing.
    clean = np.nan_to_num(signal.astype(np.float64), nan=0.0, posinf=0.0, neginf=0.0)
    peak = float(np.max(np.abs(clean)))
    if peak < 1e-10:
        return np.zeros_like(signal, dtype=np.int16)
    target = int(32767 * 10 ** (target_db / 20))
    scale = target / peak
    return np.clip(clean * scale, -32768, 32767).astype(np.int16)


def _soft_clip(signal: np.ndarray, threshold: float = 0.85) -> np.ndarray:
    """Tanh-based soft clipper to prevent harsh digital distortion."""
    scaled = signal.astype(np.float64) / 32768.0
    clipped = np.tanh(scaled / threshold) * threshold
    return (clipped * 32768).astype(np.int16)


def _pink_noise(n: int, sr: int = 44100, seed: int = 42) -> np.ndarray:
    """Generate pink noise (1/f spectrum) for room tone.

    Uses the Voss-McCartney IIR filter applied via Direct Form I.
    The 4th-order filter has a long impulse response, so we use the
    direct-form path in :func:`_apply_iir` (which auto-selects it for
    filters with order >= 4) to avoid IR truncation issues.
    """
    rng = np.random.RandomState(seed)
    white = rng.randn(n).astype(np.float64)
    # Voss-McCartney pink noise IIR coefficients.
    b = np.array([0.049922035, -0.095993537, 0.050612699, -0.004400824])
    a = np.array([1.0, -2.494956002, 2.017265875, -0.522189400])
    pink = _apply_iir(white, b, a)
    # Trim the first few samples (filter transient).
    transient = min(24, n)
    if transient > 0 and transient < n:
        pink[:transient] *= np.linspace(0, 1, transient) ** 2
    # Normalise to very low level.
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
         - High-frequency rolloff  (``tilt_db`` per octave)
         - Band-pass bounds        (``lo_hz`` to ``hi_hz``)
      4. IFFT back to time domain.

    This is O(n log n) regardless of the number of spectral shaping
    parameters, and produces much smoother, more natural spectral
    shapes than cascaded first-order filters.
    """
    noise = rng.randn(n).astype(np.float64)

    # FFT-based spectral shaping.
    spectrum = np.fft.rfft(noise)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)

    # Avoid division by zero at DC.
    freqs_safe = np.maximum(freqs, 1.0)

    # --- Spectral tilt (dB/octave rolloff) ---
    # Each octave doubles in frequency, so power at freq f relative to
    # a reference (e.g. 1 kHz) is:  (f / ref) ^ (tilt_db / 3.0)
    # where 3.0 converts from "dB/octave" to power-law exponent
    # (since 10^(dB/20) ≈ f^(dB/6) for voltage, and we want power).
    if abs(tilt_db) > 0.5:
        ref_hz = 1000.0
        # Voltage-level spectral envelope: amplitude ∝ f^(tilt_db/20 per octave)
        # In terms of frequency ratio: amplitude ∝ (f/ref)^(tilt_db / (20 * log2(f/ref)))
        # Simplified: amplitude ∝ f^(tilt_db / 20) * ref^(-tilt_db / 20)
        # More practically, use the standard dB/oct formula:
        # gain_dB = tilt_db * log2(f / ref)
        # gain_linear = 10^(gain_dB / 20)
        with np.errstate(divide='ignore', invalid='ignore'):
            gain_db = tilt_db * np.log2(freqs_safe / ref_hz)
            gain_db = np.where(np.isfinite(gain_db), gain_db, 0.0)
        envelope = 10.0 ** (gain_db / 20.0)
    else:
        envelope = np.ones(len(freqs), dtype=np.float64)

    # --- Band-pass: 2nd-order Linkwitz-Riley style ---
    # High-pass slope (12 dB/oct below lo_hz).
    hp_slope = 1.0 / (1.0 + (lo_hz / freqs_safe) ** 4)
    # Low-pass slope (12 dB/oct above hi_hz).
    lp_slope = 1.0 / (1.0 + (freqs_safe / hi_hz) ** 4)
    envelope *= hp_slope * lp_slope

    # Smooth the envelope slightly to avoid ringing artifacts.
    # (Apply a mild Gaussian window in frequency domain.)
    if len(envelope) > 10:
        win = np.exp(-0.5 * np.linspace(-2.5, 2.5, len(envelope)) ** 2)
        envelope = envelope ** (0.3 + 0.7 * win)

    # Apply spectral envelope and IFFT.
    spectrum *= envelope
    shaped = np.fft.irfft(spectrum, n=n)

    # Apply a soft fade-in (3 samples) to avoid FFT discontinuity click.
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
    # Modulator phase with slight AM for more realism.
    mod_phase = 2 * np.pi * fm * t
    modulator = np.sin(mod_phase) * mod_index
    # Carrier with FM.
    carrier_phase = 2 * np.pi * fc * t + modulator
    # Add a tiny amount of AM on the modulator for spectral variation.
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
        # Inharmonic partial: f_k = k * f0 * sqrt(1 + k^2 * B)
        # where B is the inharmonicity coefficient.
        f_k = k * f0 * np.sqrt(1.0 + k * k * inharmonicity)
        f_k += rng.randint(-int(f0 * 0.01), int(f0 * 0.01 + 1))
        # Decay increases with partial number (higher freqs damp faster).
        decay_k = decay_base * (1.0 + 0.4 * (k - 1))
        # Amplitude decreases with partial number.
        amp = amplitude_rolloff ** (k - 1)
        # Random phase offset for each partial (prevents constructive interference).
        phase_off = rng.uniform(0, 2 * np.pi)
        out += np.sin(2 * np.pi * f_k * t + phase_off) * np.exp(-t * decay_k) * amp
    # Apply onset delay via envelope.
    if delay > 0:
        out *= _env_adsr(t, 0.002, 0.01, 0.5, 0.04, delay=delay)
    return out


def _spring_model_v2(t: np.ndarray, freq: float = 5200, decay: float = 800,
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
        # Each mode has a different frequency ratio.
        ratio = 1.0 + k * 0.31 + k * k * 0.02  # inharmonic spacing
        f_k = freq * ratio
        if rng:
            f_k += rng.randint(-int(detune), int(detune + 1))
        # Higher modes decay faster.
        d_k = decay * (1.0 + k * 0.6)
        # Amplitude decreases for higher modes.
        amp = 0.6 ** k
        phase_off = rng.uniform(0, 2 * np.pi) if rng else 0
        out += np.sin(2 * np.pi * f_k * t + phase_off) * np.exp(-t * d_k) * amp
    return out * 0.18


def _spectral_tilt(signal: np.ndarray, sr: int = 44100,
                    tilt_db_oct: float = -3.0) -> np.ndarray:
    """Apply a spectral tilt (dB/octave) to a signal.

    Positive tilt boosts treble, negative tilt boosts bass.
    Uses :func:`_apply_iir` with first-order shelving coefficients,
    replacing the old per-sample Python loops.
    """
    if abs(tilt_db_oct) < 0.1:
        return signal.astype(np.float64)

    out = signal.astype(np.float64)
    # Each first-order stage gives approximately -6 dB/octave.
    n_stages = max(1, round(abs(tilt_db_oct) / 6.0))
    for _ in range(n_stages):
        if tilt_db_oct < 0:
            # Low-shelf boost: gentle one-pole lowpass mixed with dry.
            alpha = 0.12
            lp = _apply_iir(out, np.array([alpha]),
                            np.array([1.0, -(1 - alpha)]))
            out = out * 0.7 + lp * 0.3
        else:
            # High-shelf boost: gentle one-pole highpass mixed with dry.
            alpha = 0.12
            hp = _apply_iir(out, np.array([alpha, -alpha]),
                            np.array([1.0, -(1 - alpha)]))
            out = out * 0.7 + hp * 0.3
    return out


def _generate_ir(sr: int = 44100, duration: float = 0.06,
                   room_size: float = 0.5, damping: float = 0.6) -> np.ndarray:
    """Generate a synthetic impulse response for convolution reverb.

    Creates a physically-plausible short IR using:
      - Early reflections: exponentially-spaced delay taps modelling
        first- and second-order wall bounces with proper inverse-square
        amplitude decay and frequency-dependent absorption.
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

    # Early reflections: discrete taps at exponentially-spaced delays.
    n_taps = 8
    base_delay_ms = 3.0 + room_size * 5.0  # 3-8ms first reflection
    for i in range(n_taps):
        delay_ms = base_delay_ms * (1.8 ** i)
        delay_samps = int(delay_ms * sr / 1000)
        if delay_samps >= n:
            break
        # Amplitude: inverse-distance + damping.
        amp = (0.5 ** i) * (0.3 + 0.7 * damping) * rng.uniform(0.6, 1.0)
        # Higher-order reflections are spectrally darker (absorb highs).
        brightness = 0.7 ** i  # 1.0 = full bright, decreasing for later taps
        ir[delay_samps] += amp * rng.choice([-1, 1]) * brightness
        # Micro-spread (1-2 samples) for less metallic sound.
        if delay_samps + 1 < n:
            ir[delay_samps + 1] += amp * 0.3 * rng.choice([-1, 1]) * brightness
        if delay_samps + 2 < n:
            ir[delay_samps + 2] += amp * 0.1 * rng.choice([-1, 1]) * brightness * 0.5

    # Diffuse tail: filtered noise that decays.
    tail_start = min(int(base_delay_ms * (1.8 ** n_taps) * sr / 1000), n - 1)
    tail_len = n - tail_start
    if tail_len > 10:
        tail = rng.randn(tail_len).astype(np.float64)
        tail = _butter_lowpass(tail, 0.15, order=1)  # dark tail
        t_tail = np.arange(tail_len) / sr
        # Exponential decay with proper room-dependent rate.
        tail *= np.exp(-t_tail * (15.0 / max(room_size, 0.1)) * (1.2 - damping * 0.8))
        ir[tail_start:] += tail * 0.15

    # Normalise IR to unit peak.
    peak = np.max(np.abs(ir))
    if peak > 0:
        ir /= peak
    return ir


def _fft_convolve(signal: np.ndarray, ir: np.ndarray) -> np.ndarray:
    """Fast FFT-based convolution (much faster than direct for long signals).

    Uses overlap-add method for efficiency with moderate-length IRs.
    Falls back to direct convolution for very short signals.
    """
    n_sig = len(signal)
    n_ir = len(ir)
    if n_sig < 256 or n_ir < 16:
        return np.convolve(signal, ir, mode='full')[:n_sig]
    # Overlap-add with block size = next power of 2 >= 2 * n_ir.
    block_size = 1
    while block_size < 2 * n_ir:
        block_size *= 2
    # Process in blocks (proper overlap-add).
    out = np.zeros(n_sig + n_ir - 1, dtype=np.float64)
    # Pre-compute IR FFT.
    ir_padded = np.zeros(block_size, dtype=np.float64)
    ir_padded[:n_ir] = ir
    ir_fft = np.fft.rfft(ir_padded)
    # Process in blocks.
    pos = 0
    while pos < n_sig:
        block_end = min(pos + block_size // 2, n_sig)
        block = np.zeros(block_size, dtype=np.float64)
        block[:block_end - pos] = signal[pos:block_end]
        conv = np.fft.irfft(np.fft.rfft(block) * ir_fft, n=block_size)
        # Accumulate the full convolution result (including the overlap/tail).
        end = min(pos + block_size, len(out))
        out[pos:end] += conv[:end - pos]
        pos = block_end
    # Trim to input length (caller expects same-length output).
    return out[:n_sig]


def _peak_limiter(signal: np.ndarray, sr: int = 44100,
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

    # Block size: ~1 ms.  At 44100 Hz that's 44 samples.
    block_size = max(1, int(sr * 0.001))
    n_blocks = (n + block_size - 1) // block_size

    # Find peak of each block (small loop — blocks are ~44 samples).
    block_peaks = np.empty(n_blocks, dtype=np.float64)
    for i in range(n_blocks):
        s = i * block_size
        e = min(s + block_size, n)
        block_peaks[i] = np.max(x[s:e])

    # Smooth block peaks: instant attack, exponential release.
    release_per_sample = np.exp(-1.0 / (release_ms * 0.001 * sr))
    release_per_block = release_per_sample ** block_size
    smoothed = np.empty(n_blocks, dtype=np.float64)
    smoothed[0] = block_peaks[0]
    for i in range(1, n_blocks):
        smoothed[i] = max(block_peaks[i], smoothed[i - 1] * release_per_block)

    # Expand block envelope to sample level (vectorised).
    envelope = np.repeat(smoothed, block_size)[:n]

    # Apply gain reduction only where needed (vectorised).
    over = envelope > ceiling
    if np.any(over):
        out = signal.copy()
        out[over] *= ceiling / envelope[over]
        return out
    return signal


def _mid_side_enhance(stereo: np.ndarray, width: float = 1.3) -> np.ndarray:
    """Mid-side stereo width enhancement (memory-efficient chunked version).

    ``width > 1.0`` makes the stereo image wider (more spacious).
    ``width < 1.0`` makes it narrower (more mono, more focused).
    Operates on interleaved stereo data (L R L R ...).

    v1.9: Uses float32 and processes in chunks to avoid _ArrayMemoryError
    on long audio tracks (>30 min).  Peak memory per chunk is ~120 MB
    instead of ~7+ GB for the entire track at float64.
    """
    CHUNK_SAMPLES = 4_000_000  # ~90s of stereo at 44.1 kHz per chunk
    total = len(stereo)
    result = np.empty_like(stereo)

    for start in range(0, total, CHUNK_SAMPLES):
        end = min(start + CHUNK_SAMPLES, total)
        chunk = stereo[start:end]
        n = len(chunk) // 2
        if n == 0:
            continue
        # float32 is sufficient for int16 audio — halves memory vs float64
        left = chunk[0::2].astype(np.float32)
        right = chunk[1::2].astype(np.float32)
        # In-place operations to minimise temporary arrays
        mid = (left + right) * 0.5
        left -= right
        side = left
        side *= width
        result[start:end:2] = np.clip(mid + side, -32768, 32767).astype(np.int16)
        result[start + 1:end:2] = np.clip(mid - side, -32768, 32767).astype(np.int16)

    return result


def _shape_attack(signal: np.ndarray, attack_ms: float = 0.5,
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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Advanced DSP primitives  (v4 — physical modelling / modal / KS / SVF)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class _FilterCache:
    """LRU-style cache for precomputed filter coefficients.

    Avoids recomputing bilinear-transform coefficients when the same
    cutoff/Q combination is requested repeatedly (common when many
    variants share the same filter settings).

    The cache is intentionally kept small (max 256 entries) and uses
    a simple dict with manual eviction to avoid import overhead.
    """

    __slots__ = ('_store', '_max')

    def __init__(self, max_size: int = 256):
        self._store: Dict[Tuple, Tuple] = {}
        self._max = max_size

    def get_svf(self, freq: float, q: float, sr: int) -> Tuple[float, ...]:
        """Return SVF coefficients (f, g, r) for the given parameters.

        Returns (f, g, r) where:
            f = 1 - resonance damping
            g = gain (bandwidth)
            r = 1/(2*Q) feedback factor
        """
        key = ('svf', freq, q, sr)
        entry = self._store.get(key)
        if entry is not None:
            return entry
        # Bilinear transform pre-warp.
        wc = 2.0 * np.pi * freq / sr
        g = np.sin(wc) / (2.0 * q + np.sin(wc))  # simplified g
        f = 2.0 * np.sin(wc)
        r = 1.0 / (2.0 * q)
        result = (f, g, r)
        self._put(key, result)
        return result

    def _put(self, key, value):
        if len(self._store) >= self._max:
            # Evict oldest 25% (simple strategy).
            keys = list(self._store.keys())
            for k in keys[:len(keys) // 4 + 1]:
                del self._store[k]
        self._store[key] = value


# Module-level shared cache instance.
_SVF_CACHE = _FilterCache()


def _svf_filter(signal: np.ndarray, freq: float, q: float = 0.707,
                sr: int = 44100, mode: str = 'lp') -> np.ndarray:
    """State Variable Filter — the musically superior alternative to Butterworth.

    Unlike Butterworth (which only gives LP), the SVF simultaneously
    computes LP, HP, BP, and Notch outputs from a single 2-state
    recursive filter.  Key advantages:

    * **Resonance (Q) control** — can boost frequencies near cutoff,
      producing the "ringing" characteristic of real acoustic resonances.
    * **Simultaneous outputs** — can mix LP+HP for a band-reject, or
      LP+BP for a more natural rolloff, without running the filter twice.
    * **Numerically stable** at all parameter settings (no bilinear
      transform pole-zero flipping issues that plague direct-form IIR).
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

    # Pre-warp and compute coefficients.
    # Clamp cutoff to 90% of Nyquist to prevent TPT SVF overflow.
    freq_clamped = min(freq, sr * 0.45)
    wc = np.tan(np.pi * freq_clamped / sr)
    g = wc  # integrator gain
    k = 1.0 / (2.0 * max(q, 0.01))  # standard TPT SVF feedback coefficient
    # TPT SVF coefficients.
    denom = 1.0 + g * (g + k)
    a1 = 1.0 / denom
    a2 = g * a1
    a3 = g * g * a1
    a4 = k * a1

    # State variables (zero initial conditions).
    lp = 0.0
    bp = 0.0

    out = np.empty(n, dtype=np.float64)
    for i in range(n):
        # Zero-delay feedback: compute input to integrators.
        hp = (x[i] - lp * g * (g + k) - bp * k) * a1

        # Two-integrator loop (bilinear integrators).
        bp_new = bp + g * hp
        lp_new = lp + g * bp_new

        # Soft-clamp state variables to prevent runaway oscillation.
        bp_new = max(-10.0, min(10.0, bp_new))
        lp_new = max(-10.0, min(10.0, lp_new))

        lp, bp = lp_new, bp_new

        # Select output.
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
    # Sharp attack envelope on the excitation.
    exc_len = min(int(0.001 * sr), n)  # 1ms excitation burst
    if exc_len > 0:
        noise[exc_len:] *= 0.0
        noise[:exc_len] *= np.linspace(1.0, 0.5, exc_len)

    filtered = _svf_filter(noise, freq, q, sr, mode='bp')

    # Apply exponential decay.
    t = np.arange(n, dtype=np.float64) / sr
    filtered *= np.exp(-t * decay)
    return filtered


def _karplus_strong(freq: float, duration: float, sr: int = 44100,
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

    # Delay line length = period of the fundamental.
    period = max(2, int(sr / freq))
    # Extend to fill the output buffer.
    buf_len = n + period
    buf = np.zeros(buf_len, dtype=np.float64)

    # Initial excitation: band-limited noise burst (not white noise).
    # Real plucks have energy mostly in the first 10-20 harmonics.
    n_excite = min(period * 2, n)
    raw_noise = rng.randn(n_excite)
    # Shape the excitation spectrum with a gentle rolloff.
    excite_spectrum = np.fft.rfft(raw_noise)
    freqs_excite = np.fft.rfftfreq(n_excite, 1.0 / sr)
    # Roll off above 8x fundamental for a natural pluck.
    rolloff = 1.0 / (1.0 + (freqs_excite / (freq * 8.0)) ** 4)
    excite_spectrum *= rolloff
    excitation = np.fft.irfft(excite_spectrum, n=n_excite)
    # Normalise excitation energy.
    peak = np.max(np.abs(excitation))
    if peak > 0:
        excitation /= peak

    # Fill initial delay line.
    buf[:n_excite] = excitation

    # Karplus-Strong loop: average filter + damping.
    # blend controls how much of the averaged vs. original sample is used.
    blend = 0.5 * damping + 0.3  # 0.3-0.8 range
    # stretch adds slight inharmonicity (pitch droop over time).
    stretch = 1.0 + 0.0002 * (1.0 - brightness)

    # Average filter probability: controls brightness.
    # Lower probability = brighter (less filtering per pass).
    avg_prob = 0.3 + 0.6 * brightness  # 0.3 (bright) to 0.9 (muffled)

    write_pos = 0
    read_pos = period

    for i in range(n_excite, buf_len):
        # Read from delay line (with fractional delay for inharmonicity).
        rp = read_pos
        rp_int = int(rp)
        rp_frac = rp - rp_int
        if rp_int + 1 < buf_len:
            delayed = buf[rp_int] * (1.0 - rp_frac) + buf[min(rp_int + 1, buf_len - 1)] * rp_frac
        else:
            delayed = buf[min(rp_int, buf_len - 1)]

        # Low-pass average filter (the core KS operation).
        if rp_int > 0:
            prev = buf[rp_int - 1]
            averaged = 0.5 * (delayed + prev)
        else:
            averaged = delayed

        # Stochastic brightness: randomly skip averaging for brightness.
        if rng.rand() > avg_prob:
            filtered = delayed  # no filtering = brighter
        else:
            filtered = averaged

        # Blend between filtered and unfiltered based on damping.
        buf[i] = blend * filtered + (1.0 - blend) * delayed

        # Slight inharmonicity: the delay line "stretches" over time,
        # causing higher harmonics to decay faster (like a real string).
        read_pos += stretch
        write_pos += 1

    return buf[:n]


def _karplus_strong_v2(freq: float, duration: float, sr: int = 44100,
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
        # Each string has a slightly different frequency.
        f_var = freq + (rng.randint(-int(detune_hz * 10), int(detune_hz * 10 + 1)) / 10.0 if rng else 0)
        # Inharmonicity: higher strings get stretched.
        f_var *= (1.0 + s * freq_spread)
        # Each string has slightly different timbre.
        b_var = np.clip(brightness + (rng.uniform(-0.1, 0.1) if rng else 0), 0.0, 1.0)
        d_var = np.clip(damping + (rng.uniform(-0.1, 0.1) if rng else 0), 0.0, 1.0)
        out += _karplus_strong(f_var, duration, sr, b_var, d_var, rng)

    # Normalise.
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
        # Add small random detuning for natural variation.
        f = freq + rng.randint(-int(freq * 0.005), int(freq * 0.005) + 1)
        d = decay + rng.uniform(-decay * 0.05, decay * 0.05)
        out += np.sin(2 * np.pi * f * t + phase) * np.exp(-t * d) * amp

    # Add a noise burst component (real impacts have a noisy transient).
    if noise_mix > 0.01:
        noise = rng.randn(n).astype(np.float64)
        # Shape the noise: sharp attack, fast decay.
        noise *= np.exp(-t * noise_decay)
        # Soften the noise with a gentle LP to avoid harshness.
        if n > 20:
            noise = _svf_filter(noise, min(freq * 3 if modes else 4000, sr * 0.48),
                               0.707, sr, mode='lp')
        out += noise * noise_mix

    return out


def _metal_plate_modes(f0: float, n_modes: int = 6,
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

    # Approximate Bessel-zero ratios for clamped circular plate.
    # These are j(m,n)^2 / j(0,1)^2 for the first few modes.
    bessel_ratios = [1.0, 2.14, 3.59, 5.27, 7.20, 9.37, 11.8, 14.5]
    # Amplitude rolloff: higher modes are quieter (energy distribution).
    amp_rolloff = 0.55
    # Decay increases with mode number (higher freqs damp faster).
    base_decay = 800.0  # 1/s for fundamental

    modes = []
    for k in range(min(n_modes, len(bessel_ratios))):
        ratio = bessel_ratios[k]
        f_k = f0 * ratio
        # Random detuning (real plates aren't perfectly circular).
        f_k += rng.randint(-int(f0 * 0.008), int(f0 * 0.008) + 1)
        amp = amp_rolloff ** k
        decay = base_decay * (1.0 + 0.8 * k)
        phase = rng.uniform(0, 2 * np.pi)
        modes.append((f_k, amp, decay, phase))

    return modes


def _wood_bar_modes(f0: float, n_modes: int = 5,
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

    # Free-free bar ratios: (2n+1)^2 / 9
    bar_ratios = [1.0, 2.78, 5.41, 8.93, 13.3, 18.4]
    amp_rolloff = 0.50
    base_decay = 500.0

    modes = []
    for k in range(min(n_modes, len(bar_ratios))):
        ratio = bar_ratios[k]
        f_k = f0 * ratio
        f_k += rng.randint(-int(f0 * 0.005), int(f0 * 0.005) + 1)
        amp = amp_rolloff ** k
        decay = base_decay * (1.0 + 0.5 * k)
        phase = rng.uniform(0, 2 * np.pi)
        modes.append((f_k, amp, decay, phase))

    return modes


def _bell_modes(f0: float, n_modes: int = 7,
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

    # Bell partial ratios (approximate, based on church bell acoustics).
    bell_ratios = [0.5, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 3.8]
    # Amplitudes: prime is loudest, hum is sub-dominant.
    bell_amps = [0.35, 0.60, 0.25, 0.20, 0.40, 0.15, 0.10, 0.06]
    base_decay = 4.0  # bells ring for a LONG time

    modes = []
    for k in range(min(n_modes, len(bell_ratios))):
        f_k = f0 * bell_ratios[k]
        f_k += rng.randint(-int(f0 * 0.003), int(f0 * 0.003) + 1)
        amp = bell_amps[k] if k < len(bell_amps) else 0.05
        # Higher partials decay faster.
        decay = base_decay * (1.0 + 1.5 * k)
        phase = rng.uniform(0, 2 * np.pi)
        modes.append((f_k, amp, decay, phase))

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

    # Generate excitation noise with controlled bandwidth.
    if bandwidth > 0:
        noise = rng.randn(n).astype(np.float64)
        # Shape excitation spectrum via FFT (broad energy around center).
        spectrum = np.fft.rfft(noise)
        freqs = np.fft.rfftfreq(n, 1.0 / sr)
        # Gaussian-shaped excitation centered on the resonant frequency.
        sigma = max(bandwidth, 100.0)
        excitation_envelope = np.exp(-0.5 * ((freqs - center_freq) / sigma) ** 2)
        # Also include some low-frequency energy (impact thud).
        excitation_envelope += 0.3 * np.exp(-0.5 * (freqs / (center_freq * 0.5)) ** 2)
        spectrum *= excitation_envelope
        noise = np.fft.irfft(spectrum, n=n)
    else:
        noise = rng.randn(n).astype(np.float64)

    # Apply sharp attack envelope to the excitation.
    attack_samples = min(int(0.0005 * sr), n)
    if attack_samples > 1:
        noise[:attack_samples] *= np.linspace(0, 1, attack_samples) ** 0.5

    # Apply excitation decay.
    noise *= np.exp(-t * excitation_decay)

    # Pass through resonant SVF (the "body").
    # Use BP for the resonant ring + LP for the body thud.
    resonant = _svf_filter(noise, center_freq, q, sr, mode='bp')
    body_thud = _svf_filter(noise, center_freq * 0.25, 0.707, sr, mode='lp') * 0.3

    return resonant + body_thud


def _comb_filter(signal: np.ndarray, delay_ms: float, feedback: float = 0.5,
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
        delayed = x[i - delay_samples] if i >= delay_samples else 0.0
        y[i] = x[i] + feedback * delayed

    return y


def _allpass_diffusion(signal: np.ndarray, delay_ms: float = 5.0,
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
        # Read from delay line.
        delayed = buffer[buf_pos]
        # Allpass equation: output = -g * input + input_delayed + g * output_delayed
        y[i] = -feedback * x[i] + delayed
        buffer[buf_pos] = x[i] + feedback * delayed
        buf_pos = (buf_pos + 1) % delay_samples

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
    # Linear frequency ramp.
    freq = np.linspace(f_start, f_end, n)
    # Cumulative phase: integral of 2*pi*f(t) dt
    phase = phase_offset + 2 * np.pi * np.cumsum(freq) / sr
    return np.sin(phase)


# QWERTY position model for stereo panning.
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
        # Normalise column to [-1, 1] for panning (left to right).
        # BUG FIX (v1.5.1): for single-key rows (the space row), the
        # formula produced -1.0 (hard-left pan) because
        # `_col_idx / max(len(_row) - 1, 1)` was `0 / 1 = 0`. Now we
        # special-case single-key rows to centre them (pan = 0.0).
        if len(_row) <= 1:
            _KEY_POSITIONS[_ch] = 0.0
        else:
            _KEY_POSITIONS[_ch] = -1.0 + 2.0 * _col_idx / (len(_row) - 1)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TypingSoundGenerator
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TypingSoundGenerator:
    """Generate and mix procedural keyboard typing sounds."""

    PROFILES = ("Mechanical", "Typewriter", "Soft Membrane",
                "Laptop Chiclet", "Topre Electrostatic", "Custom Linear",
                "Cash Register", "Pinball", "Telegraph",
                "Arcade Button", "Gunshot", "Gunshot Silenced",
                "Crystal Singing Bowl", "Synth Bubble", "Tibetan Bowl")

    SOUND_CATEGORIES = ("key", "space", "enter", "backspace", "tab",
                        "quote", "bracket", "digit", "modifier",
                        "punctuation", "escape")

    # Per-profile category remapping.  Non-keyboard presets map
    # characters to thematic categories instead of standard key classes.
    _CATEGORY_MAPS: Dict[str, Dict[str, str]] = {
        "Mechanical": {},
        "Typewriter": {},
        "Soft Membrane": {},
        "Laptop Chiclet": {},
        "Topre Electrostatic": {},
        "Custom Linear": {},
        "Cash Register": {
            "\n": "jackpot", " ": "coin", "\t": "coin_tray",
            "\x1b": "drawer_slam", "\b": "receipt_tear",
            "'\"`": "small_item", "()[]{}": "med_item",
            "digit": "beep", ".;:,!?": "scanner",
        },
        "Pinball": {
            "\n": "multiplier", " ": "plunger", "\t": "tilt",
            "\x1b": "drain", "\b": "flipper",
            "'\"`": "bumper_a", "()[]{}": "bumper_b",
            "digit": "bumper_c", ".;:,!?": "target",
        },
        "Telegraph": {
            "\n": "dash", " ": "long_gap", "\t": "repeater_click",
            "\x1b": "end_transmission", "\b": "correction",
            "'\"`": "dot", "()[]{}": "dash",
            "digit": "dot", ".;:,!?": "dot",
        },
        "Arcade Button": {
            "\n": "start_coin", " ": "punch", "\t": "macro",
            "\x1b": "insert_coin", "\b": "delete_buzz",
            "'\"`": "a_btn", "()[]{}": "b_btn",
            "digit": "a_btn", ".;:,!?": "b_btn",
        },
        "Gunshot": {
            "\n": "shotgun", " ": "rifle", "\t": "burst",
            "\x1b": "cannon", "\b": "silenced_hit",
            "'\"`": "pistol", "()[]{}": "revolver",
            "digit": "pistol", ".;:,!?": "revolver",
        },
        "Gunshot Silenced": {
            "\n": "heavy_thump", " ": "medium_thump", "\t": "triple_tap",
            "\x1b": "deep_boom", "\b": "gas_leak",
            "'\"`": "soft_pfft", "()[]{}": "low_pop",
            "digit": "soft_pfft", ".;:,!?": "low_pop",
        },
        "Crystal Singing Bowl": {
            "\n": "full_bowl", " ": "deep_ring", "\t": "shimmer_sweep",
            "\x1b": "dissonant", "\b": "fade_out",
            "'\"`": "harmonic_a", "()[]{}": "harmonic_b",
            "digit": "chime", ".;:,!?": "sparkle",
        },
        "Synth Bubble": {
            "\n": "whoosh", " ": "deep_bubble", "\t": "squelch_sweep",
            "\x1b": "glitch", "\b": "deflate",
            "'\"`": "bubble_a", "()[]{}": "bubble_b",
            "digit": "blip", ".;:,!?": "squelch",
        },
        "Tibetan Bowl": {
            "\n": "large_bowl", " ": "bass_bowl", "\t": "harmonic_tap",
            "\x1b": "deep_gong", "\b": "mallet_damp",
            "'\"`": "overtone_a", "()[]{}": "overtone_b",
            "digit": "small_bell", ".;:,!?": "rim_tap",
        },
    }

    # Profiles that use thematic categories (keys in _CATEGORY_MAPS with
    # non-empty dicts) need extended SOUND_CATEGORIES at build time.
    _EXTRA_CATEGORIES: Dict[str, Tuple[str, ...]] = {
        "Cash Register": ("jackpot", "coin", "coin_tray", "drawer_slam",
                           "receipt_tear", "small_item", "med_item", "beep", "scanner"),
        "Pinball": ("multiplier", "plunger", "tilt", "drain", "flipper",
                     "bumper_a", "bumper_b", "bumper_c", "target"),
        "Telegraph": ("dash", "long_gap", "repeater_click", "end_transmission",
                       "correction", "dot"),
        "Arcade Button": ("start_coin", "punch", "macro", "insert_coin",
                           "delete_buzz", "a_btn", "b_btn"),
        "Gunshot": ("shotgun", "rifle", "burst", "cannon", "silenced_hit",
                      "pistol", "revolver"),
        "Gunshot Silenced": ("heavy_thump", "medium_thump", "triple_tap",
                               "deep_boom", "gas_leak", "soft_pfft", "low_pop"),
        "Crystal Singing Bowl": ("full_bowl", "deep_ring", "shimmer_sweep",
                                   "dissonant", "fade_out", "harmonic_a",
                                   "harmonic_b", "chime", "sparkle"),
        "Synth Bubble": ("whoosh", "deep_bubble", "squelch_sweep",
                          "glitch", "deflate", "bubble_a",
                          "bubble_b", "blip", "squelch"),
        "Tibetan Bowl": ("large_bowl", "bass_bowl", "harmonic_tap",
                          "deep_gong", "mallet_damp", "overtone_a",
                          "overtone_b", "small_bell", "rim_tap"),
    }

    def __init__(self, sample_rate: int = 44100,
                 profile: str = "Mechanical") -> None:
        self.logger = logging.getLogger("TypingSoundGenerator")
        if profile not in self.PROFILES:
            self.logger.warning("Unknown profile %r; falling back to 'Mechanical'",
                                profile)
            profile = "Mechanical"
        self.sample_rate = sample_rate
        self.profile = profile
        self.sounds: Dict[str, List[np.ndarray]] = {}
        self._generate_all()

    # ── profile dispatch ──────────────────────────────────────────────
    def _generate_all(self) -> None:
        """Build the full per-category sound bank for the active profile."""
        builders = self._profile_builders()
        self.sounds = {}
        for category, (fn, n_variants) in builders.items():
            self.sounds[category] = [fn(i) for i in range(n_variants)]

    def _profile_builders(self) -> Dict[str, Tuple, int]:
        """Return a dict of {category: (builder_fn, n_variants)}."""
        p = self.profile
        if p == "Mechanical":
            return self._mech_builders()
        if p == "Typewriter":
            return self._typewriter_builders()
        if p == "Soft Membrane":
            return self._membrane_builders()
        if p == "Laptop Chiclet":
            return self._chiclet_builders()
        if p == "Topre Electrostatic":
            return self._topre_builders()
        if p == "Custom Linear":
            return self._linear_builders()
        if p == "Cash Register":
            return self._cashreg_builders()
        if p == "Pinball":
            return self._pinball_builders()
        if p == "Telegraph":
            return self._telegraph_builders()
        if p == "Arcade Button":
            return self._arcade_builders()
        if p == "Gunshot":
            return self._gunshot_builders()
        if p == "Crystal Singing Bowl":
            return self._crystal_bowl_builders()
        if p == "Synth Bubble":
            return self._synth_bubble_builders()
        if p == "Tibetan Bowl":
            return self._tibetan_bowl_builders()
        # Gunshot Silenced
        return self._silenced_builders()

    # ══════════════════════════════════════════════════════════════════
    # MECHANICAL profile — Cherry MX Blue/Brown hybrid thock
    # ══════════════════════════════════════════════════════════════════
    def _mech_builders(self) -> Dict[str, Tuple]:
        return {
            "key":         (self._mech_click, 8),
            "space":       (self._mech_space, 4),
            "enter":       (self._mech_enter, 4),
            "backspace":   (self._mech_backspace, 4),
            "tab":         (self._mech_tab, 4),
            "quote":       (self._mech_quote, 4),
            "bracket":     (self._mech_bracket, 4),
            "digit":       (self._mech_digit, 4),
            "modifier":    (self._mech_modifier, 4),
            "punctuation": (self._mech_punctuation, 4),
            "escape":      (self._mech_escape, 4),
        }

    def _mech_click(self, v: int = 0, dur: float = 0.08) -> np.ndarray:
        sr, n = self.sample_rate, int(self.sample_rate * 0.08)
        t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v)
        pitch = 1.0 + (v - 3.5) * 0.05

        # --- Impact transient: noise-excited resonator (physical model) ---
        # Instead of separate noise + sine, model the keycap as a
        # resonant body excited by the impact.
        impact = _noise_excited_resonator(n, rng,
                                           center_freq=4500 * pitch,
                                           bandwidth=8000, q=3.0, sr=sr,
                                           excitation_decay=1500) * 0.10
        impact = _shape_attack(impact, attack_ms=0.3, hardness=3.0)

        # --- Click transient: FM synthesis for rich metallic character ---
        click = _fm_click(t, f_carrier=3400 * pitch, f_mod=1800 * pitch,
                          mod_index=2.5, rng=rng, decay=450, detune=250)
        click *= _env_adsr(t, 0.0003, 0.015, 0.1, 0.03) * 0.32

        # --- Spring resonance: Karplus-Strong (physically modelled) ---
        # The metal spring in MX switches vibrates like a plucked string.
        # KS models this naturally with the correct harmonic decay.
        ks_spring = _karplus_strong(5400 * pitch, dur * 0.7, sr,
                                     brightness=0.25, damping=0.7, rng=rng)
        # Trim or pad to match buffer length.
        ks_len = min(len(ks_spring), n)
        spring = np.zeros(n, dtype=np.float64)
        spring[:ks_len] = ks_spring[:ks_len]
        spring *= _env_adsr(t, 0.001, 0.01, 0.05, 0.02) * 0.14
        # Add slight comb filter resonance for metallic tube quality.
        spring = _comb_filter(spring, delay_ms=0.18, feedback=0.35, sr=sr) * 0.12

        # --- Housing body: modal impact (physically correct mode frequencies) ---
        # Use wood bar modes for the plastic/PCB case resonance.
        body_modes = _wood_bar_modes(360 * pitch, n_modes=5, rng=rng)
        thock = _modal_impact(n, rng, body_modes, sr,
                               noise_mix=0.08, noise_decay=600) * 0.45

        # --- Secondary resonance: modal impact ---
        res_modes = _wood_bar_modes(700 * pitch, n_modes=3, rng=rng)
        res2 = _modal_impact(n, rng, res_modes, sr,
                              noise_mix=0.05, noise_decay=500) * 0.10

        # --- Keycap rattle: SVF resonant noise (more natural than shaped noise) ---
        rattle = _svf_resonant_noise(n, rng, freq=3500 * pitch, q=4.0,
                                      sr=sr, decay=350) * 0.08

        # --- Sub-bass cavity: noise-excited resonator at very low freq ---
        thud = _noise_excited_resonator(n, rng,
                                         center_freq=130 * pitch,
                                         bandwidth=300, q=2.0, sr=sr,
                                         excitation_decay=500) * 0.20
        # Delay the thud slightly (cavity resonance builds up).
        thud *= _env_adsr(t, 0.010, 0.02, 0.08, 0.04, delay=0.012)

        out = impact + click + spring + thock + res2 + rattle + thud
        # SVF highpass for cleaner sub-bass removal (more musical than Butterworth).
        out = _svf_filter(out, 330, 0.707, sr, mode='hp')
        # Gentle spectral tilt for natural warmth.
        out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        # SVF lowpass for HF rolloff (with slight resonance for air).
        out = _svf_filter(out, 9200, 1.0, sr, mode='lp')
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _mech_space(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.11
        n = int(sr * dur)
        t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 100)

        # Wider rattle (stabilizer wires) — shaped noise.
        rattle = _noise_shaped(n, rng, 1800, 4500, sr, tilt_db=-3.0)
        rattle *= np.exp(-t * 200) * 0.18

        # Deeper housing resonance (longer key) — resonant body.
        res = _resonant_body(t, f0=200, rng=rng, n_partials=5,
                             decay_base=120, inharmonicity=0.003,
                             delay=0.015, amplitude_rolloff=0.50) * 0.60

        # Stabilizer thud — resonant body.
        thud = _resonant_body(t, f0=85, rng=rng, n_partials=3,
                              decay_base=100, inharmonicity=0.002,
                              delay=0.018, amplitude_rolloff=0.45) * 0.45

        # Click — FM click.
        click = _fm_click(t, f_carrier=2200, f_mod=1100,
                          mod_index=2.0, rng=rng, decay=300, detune=200)
        click *= _env_adsr(t, 0.0003, 0.015, 0.08, 0.03) * 0.20

        out = rattle + res + thud + click
        out = _highpass(out, 0.015)
        out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _mech_enter(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.10
        n = int(sr * dur)
        t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 200)

        # FM click for richer metallic character.
        click = _fm_click(t, f_carrier=2000, f_mod=1000,
                          mod_index=2.5, rng=rng, decay=400, detune=180)
        click *= _env_adsr(t, 0.0003, 0.012, 0.08, 0.03) * 0.40

        # Resonant body for housing resonance.
        res = _resonant_body(t, f0=160, rng=rng, n_partials=5,
                             decay_base=130, inharmonicity=0.003,
                             delay=0.010, amplitude_rolloff=0.50) * 0.65

        # Sub-bass thud — resonant body.
        thud = _resonant_body(t, f0=70, rng=rng, n_partials=3,
                              decay_base=110, inharmonicity=0.002,
                              delay=0.016, amplitude_rolloff=0.45) * 0.50

        # Shaped noise rattle.
        rattle = _noise_shaped(n, rng, 2000, 5000, sr, tilt_db=-3.0)
        rattle *= np.exp(-t * 280) * 0.12
        out = click + res + thud + rattle
        out = _highpass(out, 0.015)
        out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _mech_backspace(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.065
        n = int(sr * dur)
        t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 300)
        pitch = 1.12 + (v - 1.5) * 0.04

        # FM click with higher carrier for sharper backspace.
        click = _fm_click(t, f_carrier=3800 * pitch, f_mod=1900 * pitch,
                          mod_index=2.8, rng=rng, decay=480, detune=250)
        click *= _env_adsr(t, 0.0003, 0.012, 0.08, 0.02) * 0.38

        # Resonant body thock.
        thock = _resonant_body(t, f0=440 * pitch, rng=rng, n_partials=5,
                               decay_base=150, inharmonicity=0.003,
                               delay=0.005, amplitude_rolloff=0.50) * 0.35

        # Spring model v2.
        spring = _spring_model_v2(t, 5600 * pitch, 900, rng, 150, n_partials=4, sr=sr) * 0.10

        # Shaped noise rattle.
        rattle = _noise_shaped(n, rng, 2800, 5500, sr, tilt_db=-3.0)
        rattle *= np.exp(-t * 400) * 0.08
        out = click + thock + spring + rattle
        out = _highpass(out, 0.015)
        out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _mech_tab(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.07
        n = int(sr * dur)
        t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 400)

        # FM click.
        click = _fm_click(t, f_carrier=2600, f_mod=1300,
                          mod_index=2.2, rng=rng, decay=420, detune=200)
        click *= _env_adsr(t, 0.0003, 0.015, 0.08, 0.03) * 0.35

        # Resonant body thock.
        thock = _resonant_body(t, f0=340, rng=rng, n_partials=5,
                               decay_base=140, inharmonicity=0.003,
                               delay=0.008, amplitude_rolloff=0.50) * 0.42

        # Shaped noise rattle.
        rattle = _noise_shaped(n, rng, 2200, 4800, sr, tilt_db=-3.0)
        rattle *= np.exp(-t * 350) * 0.09
        out = click + thock + rattle
        out = _highpass(out, 0.015)
        out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _mech_quote(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.065
        n = int(sr * dur)
        t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 500)

        # FM click.
        click = _fm_click(t, f_carrier=2800, f_mod=1400,
                          mod_index=2.0, rng=rng, decay=450, detune=200)
        click *= _env_adsr(t, 0.0004, 0.018, 0.08, 0.03) * 0.28

        # Resonant body thock.
        thock = _resonant_body(t, f0=360, rng=rng, n_partials=5,
                               decay_base=145, inharmonicity=0.003,
                               delay=0.008, amplitude_rolloff=0.50) * 0.40

        # Shaped noise rattle.
        rattle = _noise_shaped(n, rng, 2000, 4500, sr, tilt_db=-3.0)
        rattle *= np.exp(-t * 320) * 0.07
        out = click + thock + rattle
        out = _highpass(out, 0.015)
        out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _mech_bracket(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.065
        n = int(sr * dur)
        t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 600)

        # FM click.
        click = _fm_click(t, f_carrier=3400, f_mod=1700,
                          mod_index=2.5, rng=rng, decay=380, detune=200)
        click *= _env_adsr(t, 0.0003, 0.012, 0.06, 0.02) * 0.30

        # Spring: Karplus-Strong + comb filter for metallic ring.
        ks_ring = _karplus_strong(5200, dur * 0.6, sr,
                                   brightness=0.2, damping=0.65, rng=rng)
        ks_len = min(len(ks_ring), n)
        ring = np.zeros(n, dtype=np.float64)
        ring[:ks_len] = ks_ring[:ks_len]
        ring = _comb_filter(ring, delay_ms=0.15, feedback=0.40, sr=sr) * 0.16

        # Resonant body thock.
        thock = _resonant_body(t, f0=400, rng=rng, n_partials=5,
                               decay_base=145, inharmonicity=0.003,
                               delay=0.006, amplitude_rolloff=0.50) * 0.42
        out = click + ring + thock
        out = _highpass(out, 0.015)
        out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _mech_digit(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.065
        n = int(sr * dur)
        t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 700)
        pitch = 1.08 + (v - 1.5) * 0.03

        # FM click with pitched carrier.
        click = _fm_click(t, f_carrier=3500 * pitch, f_mod=1750 * pitch,
                          mod_index=2.4, rng=rng, decay=440, detune=220)
        click *= _env_adsr(t, 0.0003, 0.014, 0.08, 0.03) * 0.32

        # Resonant body thock.
        thock = _resonant_body(t, f0=420 * pitch, rng=rng, n_partials=5,
                               decay_base=145, inharmonicity=0.003,
                               delay=0.008, amplitude_rolloff=0.50) * 0.44

        # Shaped noise rattle.
        rattle = _noise_shaped(n, rng, 2200, 5000, sr, tilt_db=-3.0)
        rattle *= np.exp(-t * 320) * 0.08
        out = click + thock + rattle
        out = _highpass(out, 0.015)
        out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _mech_modifier(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.04
        n = int(sr * dur)
        t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 800)

        # Short FM click.
        click = _fm_click(t, f_carrier=2400, f_mod=1200,
                          mod_index=2.0, rng=rng, decay=550, detune=180)
        click *= _env_adsr(t, 0.0002, 0.010, 0.06, 0.02) * 0.22

        # Shaped noise rattle.
        rattle = _noise_shaped(n, rng, 2500, 5000, sr, tilt_db=-3.0)
        rattle *= np.exp(-t * 500) * 0.06
        out = click + rattle
        out = _highpass(out, 0.015)
        out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _mech_punctuation(self, v: int = 0) -> np.ndarray:
        """Period, comma, colon, semicolon — slightly softer than letters."""
        sr, dur = self.sample_rate, 0.065
        n = int(sr * dur)
        t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 900)

        # FM click.
        click = _fm_click(t, f_carrier=3000, f_mod=1500,
                          mod_index=2.2, rng=rng, decay=460, detune=200)
        click *= _env_adsr(t, 0.0004, 0.016, 0.08, 0.03) * 0.28

        # Resonant body thock.
        thock = _resonant_body(t, f0=370, rng=rng, n_partials=5,
                               decay_base=140, inharmonicity=0.003,
                               delay=0.008, amplitude_rolloff=0.50) * 0.42

        # Shaped noise rattle.
        rattle = _noise_shaped(n, rng, 2200, 4800, sr, tilt_db=-3.0)
        rattle *= np.exp(-t * 340) * 0.07
        out = click + thock + rattle
        out = _highpass(out, 0.015)
        out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _mech_escape(self, v: int = 0) -> np.ndarray:
        """Escape key — top-left position, slightly different resonance."""
        sr, dur = self.sample_rate, 0.07
        n = int(sr * dur)
        t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 950)

        # FM click.
        click = _fm_click(t, f_carrier=3200, f_mod=1600,
                          mod_index=2.3, rng=rng, decay=430, detune=200)
        click *= _env_adsr(t, 0.0003, 0.014, 0.06, 0.03) * 0.30

        # Higher cavity resonance (smaller key, less mass) — resonant body.
        res = _resonant_body(t, f0=480, rng=rng, n_partials=4,
                             decay_base=160, inharmonicity=0.002,
                             delay=0.006, amplitude_rolloff=0.50) * 0.45

        # Spring model v2.
        spring = _spring_model_v2(t, 5800, 800, rng, 200, n_partials=4, sr=sr) * 0.12
        out = click + res + spring
        out = _highpass(out, 0.015)
        out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    # ══════════════════════════════════════════════════════════════════
    # TYPEWRITER profile — sharp strike + bell on Enter
    # ══════════════════════════════════════════════════════════════════
    def _typewriter_builders(self) -> Dict[str, Tuple]:
        return {
            "key":         (self._typewriter_click, 8),
            "space":       (self._typewriter_space, 4),
            "enter":       (self._typewriter_enter, 4),
            "backspace":   (self._typewriter_backspace, 4),
            "tab":         (self._typewriter_tab, 4),
            "quote":       (self._typewriter_quote, 4),
            "bracket":     (self._typewriter_bracket, 4),
            "digit":       (self._typewriter_digit, 4),
            "modifier":    (self._typewriter_modifier, 4),
            "punctuation": (self._typewriter_punctuation, 4),
            "escape":      (self._typewriter_modifier, 4),  # alias
        }

    def _typewriter_click(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.10
        n = int(sr * dur)
        t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v)
        pitch = 1.0 + (v - 3.5) * 0.04

        # Typebar strike: Karplus-Strong (metal arm vibrating like a plucked string).
        ks_strike = _karplus_strong(4800 * pitch, dur * 0.8, sr,
                                     brightness=0.3, damping=0.55, rng=rng)
        ks_len = min(len(ks_strike), n)
        strike = np.zeros(n, dtype=np.float64)
        strike[:ks_len] = ks_strike[:ks_len]
        # Add FM click transient for the initial impact crack.
        fm_crack = _fm_click(t, f_carrier=4800 * pitch, f_mod=2400 * pitch,
                              mod_index=2.0, rng=rng, decay=800, detune=300)
        strike += fm_crack * _env_adsr(t, 0.0002, 0.005, 0.05, 0.02) * 0.25
        strike *= _env_adsr(t, 0.0002, 0.008, 0.15, 0.04) * 0.50

        # Typebar arm ringing — wood bar modal modes (the arm is a metal bar).
        bar_modes = _wood_bar_modes(1100 * pitch, n_modes=4, rng=rng)
        ring = _modal_impact(n, rng, bar_modes, sr,
                              noise_mix=0.06, noise_decay=400) * 0.35
        # Delay the ring slightly (arm vibrates after initial strike).
        ring *= _env_adsr(t, 0.002, 0.01, 0.15, 0.04, delay=0.002)

        # Clack as bar hits the platen — noise-excited resonator.
        clack = _noise_excited_resonator(n, rng,
                                          center_freq=780, bandwidth=2000,
                                          q=3.5, sr=sr,
                                          excitation_decay=350) * 0.20

        # Mechanical noise — shaped noise.
        noise = _noise_shaped(n, rng, 400, 7000, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 220) * 0.15
        out = strike + ring + clack + noise
        out = _svf_filter(out, 330, 0.707, sr, mode='hp')
        out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _typewriter_space(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.12
        n = int(sr * dur)
        t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 100)

        # Typebar strike: Karplus-Strong for metallic arm + FM crack.
        ks_s = _karplus_strong(3200, dur * 0.7, sr,
                                brightness=0.35, damping=0.6, rng=rng)
        ks_l = min(len(ks_s), n)
        strike = np.zeros(n, dtype=np.float64)
        strike[:ks_l] = ks_s[:ks_l]
        fm_c = _fm_click(t, f_carrier=3200, f_mod=1600,
                          mod_index=2.0, rng=rng, decay=600, detune=200)
        strike += fm_c * _env_adsr(t, 0.0003, 0.005, 0.05, 0.02) * 0.20
        strike *= _env_adsr(t, 0.0003, 0.01, 0.15, 0.04) * 0.40

        # Resonant ring body.
        ring = _resonant_body(t, f0=780, rng=rng, n_partials=4,
                              decay_base=90, inharmonicity=0.002,
                              delay=0.005, amplitude_rolloff=0.45) * 0.55

        # Shaped noise.
        noise = _noise_shaped(n, rng, 300, 6000, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 130) * 0.18
        out = strike + ring + noise
        out = _highpass(out, 0.015)
        out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _typewriter_enter(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.20
        n = int(sr * dur)
        t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 200)

        # Carriage-return slide (frequency sweep) — proper phase integration.
        sweep = _frequency_sweep(dur, 1400 + rng.randint(-100, 100), 500, sr) * np.exp(-t * 28) * 0.30

        # Bell — physically-modelled bell partials (hum, prime, minor third, etc.).
        bell = _bell_modes(2400 + rng.randint(-80, 80), n_modes=7, rng=rng)
        ding = _modal_impact(n, rng, bell, sr,
                              noise_mix=0.03, noise_decay=50) * 0.6
        ding *= _env_adsr(t, 0.001, 0.01, 0.6, 0.12, delay=0.05)

        # Shaped noise (was butter_lowpass(randn)).
        noise = _noise_shaped(n, rng, 200, 5000, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 45) * 0.12
        out = sweep + ding + noise
        out = _highpass(out, 0.015)
        out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _typewriter_backspace(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.08
        n = int(sr * dur)
        t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 300)

        # FM strike.
        strike = _fm_click(t, f_carrier=4400, f_mod=2200,
                           mod_index=3.0, rng=rng, decay=600, detune=300)
        strike *= _env_adsr(t, 0.0002, 0.008, 0.12, 0.03) * 0.45

        # Resonant ring body.
        ring = _resonant_body(t, f0=1050, rng=rng, n_partials=4,
                              decay_base=110, inharmonicity=0.002,
                              delay=0.002, amplitude_rolloff=0.45) * 0.35

        # Shaped noise.
        noise = _noise_shaped(n, rng, 400, 7000, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 260) * 0.12
        out = strike + ring + noise
        out = _highpass(out, 0.015)
        out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _typewriter_tab(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.10
        n = int(sr * dur)
        t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 400)

        # FM strike for the tab mechanism.
        strike = _fm_click(t, f_carrier=1500, f_mod=750,
                           mod_index=2.5, rng=rng, decay=55, detune=150)
        strike *= np.exp(-t * 55) * 0.38

        # Shaped noise.
        noise = _noise_shaped(n, rng, 300, 6000, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 100) * 0.12
        out = strike + noise
        out = _highpass(out, 0.015)
        out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _typewriter_quote(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.09
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 500)

        # FM strike.
        strike = _fm_click(t, f_carrier=4500, f_mod=2250,
                           mod_index=3.0, rng=rng, decay=580, detune=300)
        strike *= _env_adsr(t, 0.0002, 0.010, 0.12, 0.03) * 0.42

        # Resonant body ring.
        ring = _resonant_body(t, f0=1100, rng=rng, n_partials=4,
                              decay_base=110, inharmonicity=0.002,
                              amplitude_rolloff=0.45) * 0.30

        # Shaped noise.
        noise = _noise_shaped(n, rng, 400, 7000, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 250) * 0.10
        out = strike + ring + noise
        out = _highpass(out, 0.015)
        out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _typewriter_bracket(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.09
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 600)

        # FM strike.
        strike = _fm_click(t, f_carrier=4700, f_mod=2350,
                           mod_index=3.2, rng=rng, decay=560, detune=300)
        strike *= _env_adsr(t, 0.0002, 0.009, 0.10, 0.03) * 0.45

        # Resonant body ring.
        ring = _resonant_body(t, f0=1250, rng=rng, n_partials=4,
                              decay_base=105, inharmonicity=0.002,
                              amplitude_rolloff=0.45) * 0.35

        # Shaped noise.
        noise = _noise_shaped(n, rng, 400, 7000, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 240) * 0.12
        out = strike + ring + noise
        out = _highpass(out, 0.015)
        out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _typewriter_digit(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.09
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 700)

        # FM strike.
        strike = _fm_click(t, f_carrier=4500, f_mod=2250,
                           mod_index=3.0, rng=rng, decay=580, detune=300)
        strike *= _env_adsr(t, 0.0002, 0.009, 0.12, 0.03) * 0.48

        # Resonant body ring.
        ring = _resonant_body(t, f0=1200, rng=rng, n_partials=4,
                              decay_base=100, inharmonicity=0.002,
                              amplitude_rolloff=0.45) * 0.38

        # Shaped noise.
        noise = _noise_shaped(n, rng, 400, 7000, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 230) * 0.13
        out = strike + ring + noise
        out = _highpass(out, 0.015)
        out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _typewriter_modifier(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.05
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 800)

        # FM strike.
        strike = _fm_click(t, f_carrier=4000, f_mod=2000,
                           mod_index=2.5, rng=rng, decay=600, detune=250)
        strike *= np.exp(-t * 600) * 0.30

        # Shaped noise.
        noise = _noise_shaped(n, rng, 400, 7000, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 280) * 0.08
        out = strike + noise
        out = _highpass(out, 0.015)
        out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _typewriter_punctuation(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.09
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 900)

        # FM strike.
        strike = _fm_click(t, f_carrier=4600, f_mod=2300,
                           mod_index=3.0, rng=rng, decay=580, detune=300)
        strike *= _env_adsr(t, 0.0002, 0.010, 0.10, 0.03) * 0.40

        # Resonant body ring.
        ring = _resonant_body(t, f0=1150, rng=rng, n_partials=4,
                              decay_base=110, inharmonicity=0.002,
                              amplitude_rolloff=0.45) * 0.32

        # Shaped noise.
        noise = _noise_shaped(n, rng, 400, 7000, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 250) * 0.10
        out = strike + ring + noise
        out = _highpass(out, 0.015)
        out = _spectral_tilt(out, sr, tilt_db_oct=-2.0)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    # ══════════════════════════════════════════════════════════════════
    # SOFT MEMBRANE profile — quiet rubber-dome thud
    # ══════════════════════════════════════════════════════════════════
    def _membrane_builders(self) -> Dict[str, Tuple]:
        b = self
        return {
            "key":         (b._membrane_click, 8),
            "space":       (b._membrane_space, 4),
            "enter":       (b._membrane_enter, 4),
            "backspace":   (b._membrane_backspace, 4),
            "tab":         (b._membrane_tab, 4),
            "quote":       (b._membrane_quote, 4),
            "bracket":     (b._membrane_bracket, 4),
            "digit":       (b._membrane_digit, 4),
            "modifier":    (b._membrane_modifier, 4),
            "punctuation": (b._membrane_punctuation, 4),
            "escape":      (b._membrane_modifier, 4),
        }

    def _membrane_click(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.065
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v)
        pitch = 1.0 + (v - 3.5) * 0.03

        # Thud — resonant body with rubber-like inharmonicity.
        thud = _resonant_body(t, f0=200 * pitch, rng=rng, n_partials=3,
                              decay_base=180, inharmonicity=0.005,
                              amplitude_rolloff=0.45) * 0.60

        # Click.
        f_click = 1400 + rng.randint(-100, 100)
        click = np.sin(2 * np.pi * f_click * t) * np.exp(-t * 420) * 0.15

        # Shaped noise (was butter_lowpass(randn)).
        noise = _noise_shaped(n, rng, 100, 4000, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 180) * 0.22
        out = thud + click + noise
        out = _highpass(out, 0.015)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _membrane_space(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.075
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 100)

        # Thud — resonant body.
        thud = _resonant_body(t, f0=120, rng=rng, n_partials=2,
                              decay_base=140, inharmonicity=0.005,
                              delay=0.008, amplitude_rolloff=0.40) * 0.70

        # Shaped noise.
        noise = _noise_shaped(n, rng, 80, 3000, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 90) * 0.25
        out = thud + noise
        out = _highpass(out, 0.015)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _membrane_enter(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.085
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 200)

        # Thud — resonant body.
        thud = _resonant_body(t, f0=100, rng=rng, n_partials=2,
                              decay_base=130, inharmonicity=0.005,
                              delay=0.010, amplitude_rolloff=0.40) * 0.80

        # Shaped noise.
        noise = _noise_shaped(n, rng, 60, 2500, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 80) * 0.25
        out = thud + noise
        out = _highpass(out, 0.015)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _membrane_backspace(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.055
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 300)

        # Thud — resonant body.
        thud = _resonant_body(t, f0=240, rng=rng, n_partials=3,
                              decay_base=190, inharmonicity=0.005,
                              amplitude_rolloff=0.45) * 0.55

        # Shaped noise.
        noise = _noise_shaped(n, rng, 120, 4500, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 240) * 0.18
        out = thud + noise
        out = _highpass(out, 0.015)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _membrane_tab(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.06
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 400)

        # Thud — resonant body.
        thud = _resonant_body(t, f0=180, rng=rng, n_partials=3,
                              decay_base=170, inharmonicity=0.005,
                              amplitude_rolloff=0.45) * 0.55

        # Shaped noise.
        noise = _noise_shaped(n, rng, 100, 4000, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 200) * 0.18
        out = thud + noise
        out = _highpass(out, 0.015)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _membrane_quote(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.055
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 500)

        # Thud — resonant body.
        thud = _resonant_body(t, f0=220, rng=rng, n_partials=3,
                              decay_base=200, inharmonicity=0.005,
                              amplitude_rolloff=0.45) * 0.45

        # Shaped noise.
        noise = _noise_shaped(n, rng, 100, 4000, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 220) * 0.15
        out = thud + noise
        out = _highpass(out, 0.015)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _membrane_bracket(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.06
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 600)

        # Thud — resonant body.
        thud = _resonant_body(t, f0=210, rng=rng, n_partials=3,
                              decay_base=170, inharmonicity=0.005,
                              amplitude_rolloff=0.45) * 0.50

        # Click.
        f_click = 1600 + rng.randint(-100, 100)
        click = np.sin(2 * np.pi * f_click * t) * np.exp(-t * 400) * 0.10

        # Shaped noise.
        noise = _noise_shaped(n, rng, 100, 4000, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 210) * 0.16
        out = thud + click + noise
        out = _highpass(out, 0.015)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _membrane_digit(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.055
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 700)

        # Thud — resonant body.
        thud = _resonant_body(t, f0=230, rng=rng, n_partials=3,
                              decay_base=190, inharmonicity=0.005,
                              amplitude_rolloff=0.45) * 0.55

        # Shaped noise.
        noise = _noise_shaped(n, rng, 100, 4000, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 190) * 0.18
        out = thud + noise
        out = _highpass(out, 0.015)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _membrane_modifier(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.04
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 800)

        # Thud — resonant body.
        thud = _resonant_body(t, f0=260, rng=rng, n_partials=2,
                              decay_base=200, inharmonicity=0.005,
                              amplitude_rolloff=0.40) * 0.35

        # Shaped noise.
        noise = _noise_shaped(n, rng, 120, 4500, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 280) * 0.12
        out = thud + noise
        out = _highpass(out, 0.015)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _membrane_punctuation(self, v: int = 0) -> np.ndarray:
        return self._membrane_quote(v + 950)

    # ══════════════════════════════════════════════════════════════════
    # LAPTOP CHICLET profile — Apple Magic Keyboard / MacBook
    # ══════════════════════════════════════════════════════════════════
    def _chiclet_builders(self) -> Dict[str, Tuple]:
        b = self
        return {
            "key":         (b._chiclet_click, 8),
            "space":       (b._chiclet_space, 4),
            "enter":       (b._chiclet_enter, 4),
            "backspace":   (b._chiclet_backspace, 4),
            "tab":         (b._chiclet_tab, 4),
            "quote":       (b._chiclet_quote, 4),
            "bracket":     (b._chiclet_bracket, 4),
            "digit":       (b._chiclet_digit, 4),
            "modifier":    (b._chiclet_modifier, 4),
            "punctuation": (b._chiclet_punctuation, 4),
            "escape":      (b._chiclet_modifier, 4),
        }

    def _chiclet_click(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.05
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v)
        pitch = 1.0 + (v - 3.5) * 0.025

        # FM click — low mod_index for crisp, not metallic.
        click = _fm_click(t, f_carrier=2600 * pitch, f_mod=1300 * pitch,
                          mod_index=1.5, rng=rng, decay=520, detune=150)
        click *= _env_adsr(t, 0.0002, 0.008, 0.08, 0.02) * 0.40

        # Thock — resonant body (3 partials).
        thock = _resonant_body(t, f0=520 * pitch, rng=rng, n_partials=3,
                               decay_base=200, inharmonicity=0.003,
                               delay=0.005, amplitude_rolloff=0.50) * 0.30

        # Shaped noise rattle.
        rattle = _noise_shaped(n, rng, 2500, 5500, sr, tilt_db=-3.0)
        rattle *= np.exp(-t * 500) * 0.10
        out = click + thock + rattle
        out = _highpass(out, 0.015)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _chiclet_space(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.065
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 100)

        # Thud — resonant body.
        thud = _resonant_body(t, f0=180, rng=rng, n_partials=3,
                              decay_base=160, inharmonicity=0.003,
                              delay=0.008, amplitude_rolloff=0.50) * 0.55

        # FM click.
        click = _fm_click(t, f_carrier=2200, f_mod=1100,
                          mod_index=1.5, rng=rng, decay=520, detune=150)
        click *= np.exp(-t * 520) * 0.22

        # Shaped noise rattle.
        rattle = _noise_shaped(n, rng, 2000, 4500, sr, tilt_db=-3.0)
        rattle *= np.exp(-t * 350) * 0.10
        out = thud + click + rattle
        out = _highpass(out, 0.015)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _chiclet_enter(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.065
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 200)

        # Thud — resonant body.
        thud = _resonant_body(t, f0=160, rng=rng, n_partials=3,
                              decay_base=150, inharmonicity=0.003,
                              delay=0.010, amplitude_rolloff=0.50) * 0.60

        # FM click.
        click = _fm_click(t, f_carrier=2400, f_mod=1200,
                          mod_index=1.5, rng=rng, decay=500, detune=150)
        click *= np.exp(-t * 500) * 0.25

        # Shaped noise rattle.
        rattle = _noise_shaped(n, rng, 2200, 4800, sr, tilt_db=-3.0)
        rattle *= np.exp(-t * 320) * 0.12
        out = thud + click + rattle
        out = _highpass(out, 0.015)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _chiclet_backspace(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.042
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 300)

        # FM click.
        click = _fm_click(t, f_carrier=2900, f_mod=1450,
                          mod_index=1.5, rng=rng, decay=680, detune=150)
        click *= np.exp(-t * 680) * 0.36

        # Thock — resonant body.
        thock = _resonant_body(t, f0=560, rng=rng, n_partials=3,
                               decay_base=220, inharmonicity=0.003,
                               amplitude_rolloff=0.50) * 0.24
        out = click + thock
        out = _highpass(out, 0.015)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _chiclet_tab(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.048
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 400)

        # FM click.
        click = _fm_click(t, f_carrier=2500, f_mod=1250,
                          mod_index=1.5, rng=rng, decay=620, detune=150)
        click *= np.exp(-t * 620) * 0.34

        # Thock — resonant body.
        thock = _resonant_body(t, f0=480, rng=rng, n_partials=3,
                               decay_base=220, inharmonicity=0.003,
                               amplitude_rolloff=0.50) * 0.26
        out = click + thock
        out = _highpass(out, 0.015)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _chiclet_quote(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.042
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 500)

        # FM click.
        click = _fm_click(t, f_carrier=2400, f_mod=1200,
                          mod_index=1.5, rng=rng, decay=650, detune=150)
        click *= np.exp(-t * 650) * 0.30

        # Thock — resonant body.
        thock = _resonant_body(t, f0=500, rng=rng, n_partials=3,
                               decay_base=230, inharmonicity=0.003,
                               amplitude_rolloff=0.50) * 0.24
        out = click + thock
        out = _highpass(out, 0.015)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _chiclet_bracket(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.045
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 600)

        # FM click.
        click = _fm_click(t, f_carrier=2800, f_mod=1400,
                          mod_index=1.5, rng=rng, decay=630, detune=150)
        click *= np.exp(-t * 630) * 0.32

        # Spring model v2.
        ring = _spring_model_v2(t, 4800, 400, rng, 100, n_partials=4, sr=sr) * 0.08

        # Thock — resonant body.
        thock = _resonant_body(t, f0=540, rng=rng, n_partials=3,
                               decay_base=220, inharmonicity=0.003,
                               amplitude_rolloff=0.50) * 0.26
        out = click + ring + thock
        out = _highpass(out, 0.015)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _chiclet_digit(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.048
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 700)
        pitch = 1.06 + (v - 1.5) * 0.02

        # FM click.
        click = _fm_click(t, f_carrier=2700 * pitch, f_mod=1350 * pitch,
                          mod_index=1.5, rng=rng, decay=640, detune=150)
        click *= np.exp(-t * 640) * 0.34

        # Thock — resonant body.
        thock = _resonant_body(t, f0=560 * pitch, rng=rng, n_partials=3,
                               decay_base=210, inharmonicity=0.003,
                               amplitude_rolloff=0.50) * 0.28
        out = click + thock
        out = _highpass(out, 0.015)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _chiclet_modifier(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.032
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 800)

        # FM click — short.
        click = _fm_click(t, f_carrier=2200, f_mod=1100,
                          mod_index=1.5, rng=rng, decay=850, detune=150)
        click *= np.exp(-t * 850) * 0.24
        out = click
        out = _highpass(out, 0.015)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _chiclet_punctuation(self, v: int = 0) -> np.ndarray:
        return self._chiclet_click(v + 950)

    # ══════════════════════════════════════════════════════════════════
    # TOPRE ELECTROSTATIC profile — HHKB / Realforce thock
    # ══════════════════════════════════════════════════════════════════
    def _topre_builders(self) -> Dict[str, Tuple]:
        b = self
        return {
            "key":         (b._topre_click, 8),
            "space":       (b._topre_space, 4),
            "enter":       (b._topre_enter, 4),
            "backspace":   (b._topre_backspace, 4),
            "tab":         (b._topre_tab, 4),
            "quote":       (b._topre_quote, 4),
            "bracket":     (b._topre_bracket, 4),
            "digit":       (b._topre_digit, 4),
            "modifier":    (b._topre_modifier, 4),
            "punctuation": (b._topre_punctuation, 4),
            "escape":      (b._topre_escape, 4),
        }

    def _topre_click(self, v: int = 0) -> np.ndarray:
        """Topre signature: deep, satisfying thock with rubber dome.
        The electrostatic capacitive trigger gives a smooth, dampened
        bottom-out with no metallic click — just a warm, rounded thud."""
        sr, dur = self.sample_rate, 0.09
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v)
        pitch = 1.0 + (v - 3.5) * 0.03

        # Rubber dome bottom-out: resonant body (4 partials, low inharmonicity).
        dome = _resonant_body(t, f0=280 * pitch, rng=rng, n_partials=4,
                              decay_base=120, inharmonicity=0.001,
                              delay=0.010, amplitude_rolloff=0.50) * 0.55

        # Dome compression (higher harmonic) — resonant body.
        comp = _resonant_body(t, f0=580 * pitch, rng=rng, n_partials=3,
                              decay_base=150, inharmonicity=0.001,
                              delay=0.008, amplitude_rolloff=0.40) * 0.25

        # Very subtle spring sheet ring (Topre has a conical spring).
        f_spring = 1800 + rng.randint(-100, 100)
        spring = np.sin(2 * np.pi * f_spring * t) * np.exp(-t * 300) * 0.08

        # Housing resonance — resonant body.
        housing = _resonant_body(t, f0=160, rng=rng, n_partials=3,
                                 decay_base=110, inharmonicity=0.001,
                                 delay=0.015, amplitude_rolloff=0.45) * 0.30

        # Shaped noise for texture.
        noise = _noise_shaped(n, rng, 80, 3500, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 120) * 0.20

        out = dome + comp + spring + housing + noise
        out = _highpass(out, 0.010)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _topre_space(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.12
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 100)

        # Dome — resonant body.
        dome = _resonant_body(t, f0=160, rng=rng, n_partials=4,
                              decay_base=100, inharmonicity=0.001,
                              delay=0.015, amplitude_rolloff=0.50) * 0.65

        # Housing — resonant body.
        housing = _resonant_body(t, f0=100, rng=rng, n_partials=3,
                                 decay_base=90, inharmonicity=0.001,
                                 delay=0.020, amplitude_rolloff=0.45) * 0.35

        # Shaped noise.
        noise = _noise_shaped(n, rng, 60, 2500, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 80) * 0.25
        out = dome + housing + noise
        out = _highpass(out, 0.010)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _topre_enter(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.10
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 200)

        # Dome — resonant body.
        dome = _resonant_body(t, f0=140, rng=rng, n_partials=4,
                              decay_base=95, inharmonicity=0.001,
                              delay=0.015, amplitude_rolloff=0.50) * 0.70

        # Housing — resonant body.
        housing = _resonant_body(t, f0=90, rng=rng, n_partials=3,
                                 decay_base=85, inharmonicity=0.001,
                                 delay=0.018, amplitude_rolloff=0.45) * 0.35

        # Shaped noise.
        noise = _noise_shaped(n, rng, 50, 2200, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 70) * 0.22
        out = dome + housing + noise
        out = _highpass(out, 0.010)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _topre_backspace(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.07
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 300)

        # Dome — resonant body.
        dome = _resonant_body(t, f0=300, rng=rng, n_partials=4,
                              decay_base=120, inharmonicity=0.001,
                              delay=0.008, amplitude_rolloff=0.50) * 0.55

        # Comp — resonant body.
        comp = _resonant_body(t, f0=600, rng=rng, n_partials=3,
                              decay_base=200, inharmonicity=0.001,
                              amplitude_rolloff=0.45) * 0.18

        # Shaped noise.
        noise = _noise_shaped(n, rng, 80, 4000, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 140) * 0.15
        out = dome + comp + noise
        out = _highpass(out, 0.010)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _topre_tab(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.08
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 400)

        # Dome — resonant body.
        dome = _resonant_body(t, f0=260, rng=rng, n_partials=4,
                              decay_base=115, inharmonicity=0.001,
                              delay=0.010, amplitude_rolloff=0.50) * 0.55

        # Housing — resonant body.
        housing = _resonant_body(t, f0=170, rng=rng, n_partials=3,
                                 decay_base=105, inharmonicity=0.001,
                                 delay=0.012, amplitude_rolloff=0.45) * 0.30

        # Shaped noise.
        noise = _noise_shaped(n, rng, 80, 3500, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 130) * 0.18
        out = dome + housing + noise
        out = _highpass(out, 0.010)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _topre_quote(self, v: int = 0) -> np.ndarray:
        return self._topre_click(v + 500)

    def _topre_bracket(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.085
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 600)

        # Dome — resonant body.
        dome = _resonant_body(t, f0=270, rng=rng, n_partials=4,
                              decay_base=115, inharmonicity=0.001,
                              delay=0.010, amplitude_rolloff=0.50) * 0.52

        # Spring sheet ring (kept as single sine — subtle).
        f_spring = 1600 + rng.randint(-100, 100)
        spring = np.sin(2 * np.pi * f_spring * t) * np.exp(-t * 280) * 0.10

        # Shaped noise.
        noise = _noise_shaped(n, rng, 80, 3500, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 120) * 0.18
        out = dome + spring + noise
        out = _highpass(out, 0.010)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _topre_digit(self, v: int = 0) -> np.ndarray:
        return self._topre_click(v + 700)

    def _topre_modifier(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.05
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 800)

        # Dome — resonant body.
        dome = _resonant_body(t, f0=320, rng=rng, n_partials=4,
                              decay_base=140, inharmonicity=0.001,
                              delay=0.006, amplitude_rolloff=0.50) * 0.40

        # Shaped noise.
        noise = _noise_shaped(n, rng, 80, 4500, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 200) * 0.12
        out = dome + noise
        out = _highpass(out, 0.010)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _topre_punctuation(self, v: int = 0) -> np.ndarray:
        return self._topre_click(v + 900)

    def _topre_escape(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.07
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 950)

        # Dome — resonant body.
        dome = _resonant_body(t, f0=290, rng=rng, n_partials=4,
                              decay_base=120, inharmonicity=0.001,
                              delay=0.008, amplitude_rolloff=0.50) * 0.50

        # Comp — resonant body.
        comp = _resonant_body(t, f0=580, rng=rng, n_partials=3,
                              decay_base=220, inharmonicity=0.001,
                              amplitude_rolloff=0.45) * 0.15

        # Shaped noise.
        noise = _noise_shaped(n, rng, 80, 4000, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 150) * 0.14
        out = dome + comp + noise
        out = _highpass(out, 0.010)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    # ══════════════════════════════════════════════════════════════════
    # CUSTOM LINEAR profile — Holy Panda / Gateron smooth linear
    # ══════════════════════════════════════════════════════════════════
    def _linear_builders(self) -> Dict[str, Tuple]:
        b = self
        return {
            "key":         (b._linear_click, 8),
            "space":       (b._linear_space, 4),
            "enter":       (b._linear_enter, 4),
            "backspace":   (b._linear_backspace, 4),
            "tab":         (b._linear_tab, 4),
            "quote":       (b._linear_quote, 4),
            "bracket":     (b._linear_bracket, 4),
            "digit":       (b._linear_digit, 4),
            "modifier":    (b._linear_modifier, 4),
            "punctuation": (b._linear_punctuation, 4),
            "escape":      (b._linear_escape, 4),
        }

    def _linear_click(self, v: int = 0) -> np.ndarray:
        """Smooth linear switch: no click, just a soft bottom-out thud
        with a subtle spring return."""
        sr, dur = self.sample_rate, 0.075
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v)
        pitch = 1.0 + (v - 3.5) * 0.03

        # Bottom-out: resonant body (3 partials).
        bottom = _resonant_body(t, f0=220 * pitch, rng=rng, n_partials=3,
                                decay_base=130, inharmonicity=0.002,
                                delay=0.008, amplitude_rolloff=0.50) * 0.55

        # Stem friction — shaped noise (high freq).
        friction = _noise_shaped(n, rng, 2000, 6000, sr, tilt_db=-6.0)
        friction *= np.exp(-t * 500) * 0.06

        # Spring return (slightly delayed) — resonant body.
        spring = _resonant_body(t, f0=400 * pitch, rng=rng, n_partials=3,
                                decay_base=160, inharmonicity=0.002,
                                delay=0.025, amplitude_rolloff=0.50) * 0.20

        # Housing resonance — resonant body.
        housing = _resonant_body(t, f0=150, rng=rng, n_partials=3,
                                 decay_base=120, inharmonicity=0.002,
                                 delay=0.012, amplitude_rolloff=0.45) * 0.28

        # Shaped noise.
        noise = _noise_shaped(n, rng, 60, 3000, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 140) * 0.15
        out = bottom + friction + spring + housing + noise
        out = _highpass(out, 0.015)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _linear_space(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.09
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 100)

        # Bottom — resonant body.
        bottom = _resonant_body(t, f0=130, rng=rng, n_partials=3,
                                decay_base=100, inharmonicity=0.002,
                                delay=0.015, amplitude_rolloff=0.50) * 0.65

        # Housing — resonant body.
        housing = _resonant_body(t, f0=95, rng=rng, n_partials=3,
                                 decay_base=90, inharmonicity=0.002,
                                 delay=0.020, amplitude_rolloff=0.45) * 0.30

        # Shaped noise.
        noise = _noise_shaped(n, rng, 50, 2500, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 80) * 0.20
        out = bottom + housing + noise
        out = _highpass(out, 0.015)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _linear_enter(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.085
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 200)

        # Bottom — resonant body.
        bottom = _resonant_body(t, f0=120, rng=rng, n_partials=3,
                                decay_base=100, inharmonicity=0.002,
                                delay=0.015, amplitude_rolloff=0.50) * 0.68

        # Housing — resonant body.
        housing = _resonant_body(t, f0=85, rng=rng, n_partials=3,
                                 decay_base=85, inharmonicity=0.002,
                                 delay=0.018, amplitude_rolloff=0.45) * 0.30

        # Shaped noise.
        noise = _noise_shaped(n, rng, 50, 2500, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 75) * 0.18
        out = bottom + housing + noise
        out = _highpass(out, 0.015)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _linear_backspace(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.06
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 300)

        # Bottom — resonant body.
        bottom = _resonant_body(t, f0=250, rng=rng, n_partials=3,
                                decay_base=140, inharmonicity=0.002,
                                delay=0.006, amplitude_rolloff=0.50) * 0.50

        # Shaped noise.
        noise = _noise_shaped(n, rng, 80, 3500, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 160) * 0.15
        out = bottom + noise
        out = _highpass(out, 0.015)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _linear_tab(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.07
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 400)

        # Bottom — resonant body.
        bottom = _resonant_body(t, f0=200, rng=rng, n_partials=3,
                                decay_base=125, inharmonicity=0.002,
                                delay=0.010, amplitude_rolloff=0.50) * 0.52

        # Spring — resonant body.
        spring = _resonant_body(t, f0=420, rng=rng, n_partials=3,
                                decay_base=160, inharmonicity=0.002,
                                delay=0.020, amplitude_rolloff=0.50) * 0.18

        # Shaped noise.
        noise = _noise_shaped(n, rng, 80, 3500, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 140) * 0.15
        out = bottom + spring + noise
        out = _highpass(out, 0.015)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _linear_quote(self, v: int = 0) -> np.ndarray:
        return self._linear_click(v + 500)

    def _linear_bracket(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.075
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 600)

        # Bottom — resonant body.
        bottom = _resonant_body(t, f0=230, rng=rng, n_partials=3,
                                decay_base=125, inharmonicity=0.002,
                                delay=0.010, amplitude_rolloff=0.50) * 0.50

        # Spring — resonant body.
        spring = _resonant_body(t, f0=440, rng=rng, n_partials=3,
                                decay_base=200, inharmonicity=0.002,
                                amplitude_rolloff=0.50) * 0.12

        # Shaped noise.
        noise = _noise_shaped(n, rng, 80, 3500, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 140) * 0.14
        out = bottom + spring + noise
        out = _highpass(out, 0.015)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _linear_digit(self, v: int = 0) -> np.ndarray:
        return self._linear_click(v + 700)

    def _linear_modifier(self, v: int = 0) -> np.ndarray:
        sr, dur = self.sample_rate, 0.045
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 800)

        # Bottom — resonant body.
        bottom = _resonant_body(t, f0=280, rng=rng, n_partials=3,
                                decay_base=150, inharmonicity=0.002,
                                delay=0.005, amplitude_rolloff=0.50) * 0.38

        # Shaped noise.
        noise = _noise_shaped(n, rng, 80, 4000, sr, tilt_db=-9.0)
        noise *= np.exp(-t * 220) * 0.10
        out = bottom + noise
        out = _highpass(out, 0.015)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _linear_punctuation(self, v: int = 0) -> np.ndarray:
        return self._linear_click(v + 900)

    def _linear_escape(self, v: int = 0) -> np.ndarray:
        return self._linear_click(v + 950)

    # ══════════════════════════════════════════════════════════════════
    # CASH REGISTER profile — cha-ching / coins / scanner / drawer
    # ══════════════════════════════════════════════════════════════════
    def _cashreg_builders(self) -> Dict[str, Tuple]:
        b = self
        return {
            "key":           (b._cashreg_key, 6),
            "jackpot":       (b._cashreg_jackpot, 3),
            "coin":          (b._cashreg_coin, 4),
            "coin_tray":     (b._cashreg_coin_tray, 3),
            "drawer_slam":   (b._cashreg_drawer_slam, 3),
            "receipt_tear":  (b._cashreg_receipt_tear, 3),
            "small_item":    (b._cashreg_small_item, 4),
            "med_item":      (b._cashreg_med_item, 4),
            "beep":          (b._cashreg_beep, 4),
            "scanner":       (b._cashreg_scanner, 4),
        }

    def _cashreg_key(self, v: int = 0) -> np.ndarray:
        """Quick register keypress — short mechanical click + tiny ding."""
        sr, dur = self.sample_rate, 0.055
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v)
        pitch = 1.0 + (v - 2.5) * 0.04
        # Plastic key click.
        f_click = 3000 * pitch + rng.randint(-200, 200)
        click = np.sin(2 * np.pi * f_click * t) * _env_adsr(t, 0.0002, 0.008, 0.05, 0.02) * 0.30
        # Tiny metallic register ding.
        f_ding = 4200 * pitch + rng.randint(-150, 150)
        ding = np.sin(2 * np.pi * f_ding * t) * _env_adsr(t, 0.001, 0.006, 0.08, 0.015, delay=0.008) * 0.20
        # Plastic body thud.
        f_thud = 450 + rng.randint(-30, 30)
        thud = np.sin(2 * np.pi * f_thud * t) * _env_adsr(t, 0.003, 0.012, 0.08, 0.02, delay=0.004) * 0.25
        out = click + ding + thud
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _cashreg_jackpot(self, v: int = 0) -> np.ndarray:
        """Cash register jackpot — rising arpeggio 'cha-ching!'."""
        sr, dur = self.sample_rate, 0.35
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 10)
        # Rising two-note arpeggio (cha → ching).
        f1 = 1800 + rng.randint(-100, 100)
        f2 = 3200 + rng.randint(-100, 100)
        # First note (cha) — 0-100ms.
        mask1 = (t < 0.10).astype(np.float64)
        t1 = np.clip(t, 0, 0.10)
        note1 = np.sin(2 * np.pi * f1 * t) * np.exp(-t * 18) * 0.40 * mask1
        # Second note (ching) — 100-300ms, higher.
        mask2 = (t >= 0.10).astype(np.float64)
        t2 = np.clip(t - 0.10, 0, None)
        note2 = np.sin(2 * np.pi * f2 * t) * np.exp(-t2 * 10) * 0.55 * mask2
        # Shimmering overtones on ching — metal plate modal modes.
        shim_modes = _metal_plate_modes(f2 * 2.5, n_modes=5, rng=rng)
        shim = _modal_impact(n, rng, shim_modes, sr,
                              noise_mix=0.02, noise_decay=30) * 0.18 * mask2
        # Coin-like metallic ring — Karplus-Strong for realistic coin timbre.
        ring_ks = _karplus_strong(5500 + rng.randint(-300, 300), dur * 0.9, sr,
                                    brightness=0.2, damping=0.3, rng=rng)
        ring_ks_len = min(len(ring_ks), n)
        ring = np.zeros(n, dtype=np.float64)
        ring[:ring_ks_len] = ring_ks[:ring_ks_len]
        ring *= np.exp(-t * 12) * 0.14
        out = note1 + note2 + shim + ring
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _cashreg_coin(self, v: int = 0) -> np.ndarray:
        """Single coin dropping into tray — bright metallic ping."""
        sr, dur = self.sample_rate, 0.18
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 100)
        pitch = 1.0 + v * 0.06
        # Coin impact: Karplus-Strong models the coin as a vibrating membrane.
        coin_ks = _karplus_strong_v2(6200 * pitch, dur * 0.85, sr,
                                       brightness=0.15, damping=0.4, rng=rng,
                                       n_strings=2, detune_hz=80,
                                       freq_spread=0.003)
        ks_len = min(len(coin_ks), n)
        ping = np.zeros(n, dtype=np.float64)
        ping[:ks_len] = coin_ks[:ks_len]
        ping *= np.exp(-t * 20) * 0.45
        # Secondary ring (coin wobble) — metal plate modal modes.
        coin_modes = _metal_plate_modes(3800 * pitch, n_modes=4, rng=rng)
        wobble = _modal_impact(n, rng, coin_modes, sr,
                                noise_mix=0.05, noise_decay=60) * 0.22
        # Tray rattle.
        rattle = _bandpass_noise(n, rng, 3000, 7000, sr) * np.exp(-t * 35) * 0.12
        # Delayed bounce (coin settling).
        bounce_delay = int(0.06 * sr)
        if bounce_delay < n - 100:
            t_b = t[bounce_delay:] - t[bounce_delay]
            f_b = 5500 * pitch + rng.randint(-300, 300)
            bounce = np.sin(2 * np.pi * f_b * t_b) * np.exp(-t_b * 45) * 0.25
            buf = np.zeros(n, dtype=np.float64)
            buf[bounce_delay:bounce_delay + len(bounce)] = bounce
        else:
            buf = np.zeros(n, dtype=np.float64)
        out = ping + wobble + rattle + buf
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _cashreg_coin_tray(self, v: int = 0) -> np.ndarray:
        """Handful of coins scattered into tray — cascading pings."""
        sr, dur = self.sample_rate, 0.30
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 200)
        out = np.zeros(n, dtype=np.float64)
        for i in range(5 + v):
            delay = int(rng.uniform(0, 0.15) * sr)
            f = rng.uniform(4000, 7000)
            length = int(rng.uniform(0.04, 0.10) * sr)
            end = min(delay + length, n)
            t_seg = np.arange(end - delay) / sr
            seg = np.sin(2 * np.pi * f * t_seg) * np.exp(-t_seg * rng.uniform(20, 50)) * rng.uniform(0.15, 0.35)
            out[delay:end] += seg
        # Tray body thud.
        f_thud = 200 + rng.randint(-20, 20)
        thud = np.sin(2 * np.pi * f_thud * t) * _env_adsr(t, 0.005, 0.02, 0.12, 0.05, delay=0.01) * 0.30
        out += thud
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _cashreg_drawer_slam(self, v: int = 0) -> np.ndarray:
        """Cash drawer sliding open and slamming shut."""
        sr, dur = self.sample_rate, 0.40
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 300)
        # Drawer slide (friction sweep).
        f_start = 800 + rng.randint(-50, 50)
        f_end = 200
        freq = f_start + (f_end - f_start) * (t / dur)
        phase = 2 * np.pi * np.cumsum(freq) / sr
        slide = np.sin(phase) * np.exp(-t * 8) * 0.25
        # Metal-on-metal slide noise.
        slide_noise = _butter_lowpass(rng.randn(n), 0.25, 1) * np.exp(-t * 6) * 0.20
        # Slam impact (at ~60% through).
        slam_t = 0.24
        slam_env = np.exp(-np.maximum(0, t - slam_t) * 60) * (t >= slam_t).astype(float)
        f_slam = 150 + rng.randint(-15, 15)
        slam = np.sin(2 * np.pi * f_slam * t) * slam_env * 0.50
        # Metal latch click after slam.
        latch_t = 0.30
        latch_env = np.exp(-np.maximum(0, t - latch_t) * 120) * (t >= latch_t).astype(float)
        f_latch = 3500 + rng.randint(-200, 200)
        latch = np.sin(2 * np.pi * f_latch * t) * latch_env * 0.30
        out = slide + slide_noise + slam + latch
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _cashreg_receipt_tear(self, v: int = 0) -> np.ndarray:
        """Receipt paper tearing — textured noise burst."""
        sr, dur = self.sample_rate, 0.12
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 400)
        # Tearing noise — bandpass filtered.
        tear = _bandpass_noise(n, rng, 1500, 6000, sr) * np.exp(-t * 25) * 0.45
        # Paper crinkle (lower freq noise).
        crinkle = _butter_lowpass(rng.randn(n), 0.18, 1) * np.exp(-t * 30) * 0.25
        # Sharp initial rip transient.
        rip = rng.randn(min(60, n)) * np.exp(-np.linspace(0, 2000, min(60, n))) * 0.20
        rip = np.pad(rip, (0, n - len(rip)))
        out = tear + crinkle + rip
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _cashreg_small_item(self, v: int = 0) -> np.ndarray:
        """Small item scanned — quick double beep."""
        sr, dur = self.sample_rate, 0.10
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 500)
        pitch = 1.0 + v * 0.05
        # First beep.
        f1 = 2800 * pitch + rng.randint(-100, 100)
        beep1 = np.sin(2 * np.pi * f1 * t) * np.exp(-np.maximum(0, t - 0.03) * 80) * (t < 0.06).astype(float) * 0.35
        # Second beep (slightly higher).
        f2 = 3200 * pitch + rng.randint(-100, 100)
        t2 = np.clip(t - 0.05, 0, None)
        beep2 = np.sin(2 * np.pi * f2 * t) * np.exp(-t2 * 80) * (t >= 0.05).astype(float) * 0.40
        out = beep1 + beep2
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _cashreg_med_item(self, v: int = 0) -> np.ndarray:
        """Medium item — barcode scanner beep + thud."""
        sr, dur = self.sample_rate, 0.12
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 600)
        pitch = 1.0 + v * 0.04
        # Scanner beam — bright sine sweep down (proper phase integration).
        scan = _frequency_sweep(0.08, 3500 * pitch + rng.randint(-100, 100),
                                 2000 * pitch + rng.randint(-50, 50), sr)
        scan = np.pad(scan, (0, n - len(scan)))[:n]
        scan *= np.exp(-t * 22) * 0.35
        # Confirmation beep.
        f_conf = 2600 * pitch + rng.randint(-80, 80)
        conf = np.sin(2 * np.pi * f_conf * t) * np.exp(-np.maximum(0, t - 0.06) * 60) * (t >= 0.06).astype(float) * 0.30
        # Item placed on counter.
        f_thud = 180 + rng.randint(-15, 15)
        thud = np.sin(2 * np.pi * f_thud * t) * _env_adsr(t, 0.005, 0.02, 0.10, 0.04, delay=0.01) * 0.30
        out = scan + conf + thud
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _cashreg_beep(self, v: int = 0) -> np.ndarray:
        """Numeric keypad beep — clean electronic tone."""
        sr, dur = self.sample_rate, 0.06
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 700)
        pitch = 0.85 + v * 0.08  # different pitch per digit variant
        f = 2200 * pitch + rng.randint(-80, 80)
        beep = np.sin(2 * np.pi * f * t) * _env_adsr(t, 0.001, 0.005, 0.15, 0.02) * 0.40
        # Square-wave overtone for electronic feel.
        sq = np.sign(np.sin(2 * np.pi * f * 0.5 * t)) * _env_adsr(t, 0.001, 0.005, 0.08, 0.015) * 0.10
        out = beep + sq
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _cashreg_scanner(self, v: int = 0) -> np.ndarray:
        """Barcode scanner — laser sweep + confirmation chirp."""
        sr, dur = self.sample_rate, 0.15
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 900)
        # Laser sweep (rapid freq sweep — proper phase integration).
        sweep_dur = 0.07
        sweep_raw = _frequency_sweep(sweep_dur, 4000 + rng.randint(-200, 200),
                                       1500 + rng.randint(-100, 100), sr)
        mask_sweep = (t < sweep_dur).astype(float)
        sweep_raw = np.pad(sweep_raw, (0, n - len(sweep_raw)))[:n]
        sweep = sweep_raw * 0.35 * mask_sweep
        # Confirmation chirp (two quick tones).
        f_c1 = 2400 + rng.randint(-80, 80)
        f_c2 = 3000 + rng.randint(-80, 80)
        mask_chirp = (t >= 0.08).astype(float)
        t_c = np.clip(t - 0.08, 0, None)
        chirp = (np.sin(2 * np.pi * f_c1 * t) * np.exp(-t_c * 50) * 0.35
                 + np.sin(2 * np.pi * f_c2 * t) * np.exp(-t_c * 55) * 0.20) * mask_chirp
        out = sweep + chirp
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    # ══════════════════════════════════════════════════════════════════
    # PINBALL profile — coil plunger, bumpers, flippers, targets
    # ══════════════════════════════════════════════════════════════════
    def _pinball_builders(self) -> Dict[str, Tuple]:
        b = self
        return {
            "key":         (b._pinball_key, 6),
            "multiplier":  (b._pinball_multiplier, 3),
            "plunger":     (b._pinball_plunger, 4),
            "tilt":        (b._pinball_tilt, 3),
            "drain":       (b._pinball_drain, 3),
            "flipper":     (b._pinball_flipper, 4),
            "bumper_a":    (b._pinball_bumper_a, 4),
            "bumper_b":    (b._pinball_bumper_b, 4),
            "bumper_c":    (b._pinball_bumper_c, 4),
            "target":      (b._pinball_target, 4),
        }

    def _pinball_key(self, v: int = 0) -> np.ndarray:
        """Generic playfield sound — plastic ball hitting a rail."""
        sr, dur = self.sample_rate, 0.07
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v)
        pitch = 1.0 + (v - 2.5) * 0.05
        # Ball hit — bright transient.
        f_hit = 4000 * pitch + rng.randint(-250, 250)
        hit = np.sin(2 * np.pi * f_hit * t) * np.exp(-t * 500) * 0.35
        # Plastic ring.
        f_ring = 1800 * pitch + rng.randint(-100, 100)
        ring = np.sin(2 * np.pi * f_ring * t) * np.exp(-t * 120) * 0.25
        # Playfield body resonance.
        f_body = 300 + rng.randint(-25, 25)
        body = np.sin(2 * np.pi * f_body * t) * _env_adsr(t, 0.004, 0.015, 0.10, 0.025, delay=0.006) * 0.30
        out = hit + ring + body
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _pinball_multiplier(self, v: int = 0) -> np.ndarray:
        """Multiplier activated — rising electronic arpeggio."""
        sr, dur = self.sample_rate, 0.30
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 10)
        out = np.zeros(n, dtype=np.float64)
        # Three rising notes.
        base_freqs = [800, 1200, 1800]
        for i, f_base in enumerate(base_freqs):
            f = f_base + rng.randint(-50, 50)
            delay = i * 0.06
            t_seg = np.clip(t - delay, 0, None)
            seg = np.sin(2 * np.pi * f * t) * np.exp(-t_seg * 12) * 0.35 * (t >= delay).astype(float)
            out += seg
        # Final high ping.
        f_hi = 3500 + rng.randint(-200, 200)
        t_seg = np.clip(t - 0.18, 0, None)
        hi = np.sin(2 * np.pi * f_hi * t) * np.exp(-t_seg * 10) * 0.30 * (t >= 0.18).astype(float)
        out += hi
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _pinball_plunger(self, v: int = 0) -> np.ndarray:
        """Spring plunger launch — rising coil whine + thwack."""
        sr, dur = self.sample_rate, 0.25
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 100)
        # Coil compression whine (rising frequency).
        f_start = 200 + rng.randint(-20, 20)
        f_end = 1200 + rng.randint(-80, 80)
        freq = f_start + (f_end - f_start) * np.clip(t / 0.15, 0, 1)
        phase = 2 * np.pi * np.cumsum(freq) / sr
        whine = np.sin(phase) * (t < 0.15).astype(float) * 0.30
        # Release thwack at 150ms.
        thwack_env = np.exp(-np.maximum(0, t - 0.15) * 80) * (t >= 0.15).astype(float)
        f_thwack = 600 + rng.randint(-40, 40)
        thwack = np.sin(2 * np.pi * f_thwack * t) * thwack_env * 0.45
        # Ball launch echo.
        f_echo = 2000 + rng.randint(-150, 150)
        echo = np.sin(2 * np.pi * f_echo * t) * np.exp(-np.maximum(0, t - 0.18) * 40) * (t >= 0.18).astype(float) * 0.20
        out = whine + thwack + echo
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _pinball_tilt(self, v: int = 0) -> np.ndarray:
        """Tilt warning — harsh buzzer."""
        sr, dur = self.sample_rate, 0.25
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 200)
        # Buzzer — square wave.
        f_buzz = 280 + rng.randint(-20, 20)
        buzzer = np.sign(np.sin(2 * np.pi * f_buzz * t)) * _env_adsr(t, 0.002, 0.02, 0.5, 0.08) * 0.30
        # Warning tone overlay.
        f_warn = 880 + rng.randint(-40, 40)
        warn = np.sin(2 * np.pi * f_warn * t) * _env_adsr(t, 0.002, 0.01, 0.3, 0.06) * 0.25
        # Mechanical rattle.
        rattle = _bandpass_noise(n, rng, 200, 2000, sr) * _env_adsr(t, 0.005, 0.03, 0.3, 0.06) * 0.15
        out = buzzer + warn + rattle
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _pinball_drain(self, v: int = 0) -> np.ndarray:
        """Ball drain — descending tone + sad thud."""
        sr, dur = self.sample_rate, 0.35
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 300)
        # Descending tone.
        f_start = 600 + rng.randint(-40, 40)
        f_end = 150
        freq = f_start + (f_end - f_start) * (t / dur)
        phase = 2 * np.pi * np.cumsum(freq) / sr
        desc = np.sin(phase) * np.exp(-t * 8) * 0.35
        # Drain hole thud.
        f_thud = 100 + rng.randint(-10, 10)
        thud = np.sin(2 * np.pi * f_thud * t) * _env_adsr(t, 0.01, 0.04, 0.25, 0.08, delay=0.05) * 0.45
        # Mechanical noise.
        noise = _butter_lowpass(rng.randn(n), 0.15, 2) * np.exp(-t * 12) * 0.15
        out = desc + thud + noise
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _pinball_flipper(self, v: int = 0) -> np.ndarray:
        """Flipper activation — solenoid slap + return spring."""
        sr, dur = self.sample_rate, 0.09
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 400)
        # Solenoid thwack.
        f_sol = 500 + rng.randint(-30, 30)
        sol = np.sin(2 * np.pi * f_sol * t) * _env_adsr(t, 0.001, 0.008, 0.12, 0.025) * 0.50
        # Impact noise.
        impact = _bandpass_noise(n, rng, 500, 3000, sr) * np.exp(-t * 200) * 0.20
        # Return spring (delayed).
        t_ret = np.clip(t - 0.03, 0, None)
        f_ret = 350 + rng.randint(-25, 25)
        ret = np.sin(2 * np.pi * f_ret * t) * np.exp(-t_ret * 120) * (t >= 0.03).astype(float) * 0.20
        out = sol + impact + ret
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _pinball_bumper_a(self, v: int = 0) -> np.ndarray:
        """Pop bumper A — high ping + thud."""
        sr, dur = self.sample_rate, 0.08
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 500)
        # Bumper cap: modal impact with metal plate modes (realistic metallic ping).
        cap_modes = _metal_plate_modes(4500 + rng.randint(-300, 300), n_modes=5, rng=rng)
        ping = _modal_impact(n, rng, cap_modes, sr,
                              noise_mix=0.12, noise_decay=500) * 0.42
        # Body thud: noise-excited resonator (the bumper housing).
        thud = _noise_excited_resonator(n, rng,
                                          center_freq=350 + rng.randint(-25, 25),
                                          bandwidth=1000, q=2.5, sr=sr,
                                          excitation_decay=400) * 0.30
        thud *= _env_adsr(t, 0.003, 0.012, 0.10, 0.02, delay=0.004)
        # Cap ring: Karplus-Strong for metallic ring quality.
        ring_ks = _karplus_strong(2200 + rng.randint(-150, 150), dur * 0.7, sr,
                                    brightness=0.2, damping=0.6, rng=rng)
        ring_ks_len = min(len(ring_ks), n)
        ring = np.zeros(n, dtype=np.float64)
        ring[:ring_ks_len] = ring_ks[:ring_ks_len]
        ring = _comb_filter(ring, delay_ms=0.22, feedback=0.30, sr=sr) * 0.14
        out = ping + thud + ring
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _pinball_bumper_b(self, v: int = 0) -> np.ndarray:
        """Pop bumper B — different pitch range."""
        sr, dur = self.sample_rate, 0.08
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 600)
        cap_modes = _metal_plate_modes(5200 + rng.randint(-300, 300), n_modes=5, rng=rng)
        ping = _modal_impact(n, rng, cap_modes, sr,
                              noise_mix=0.12, noise_decay=550) * 0.40
        thud = _noise_excited_resonator(n, rng,
                                          center_freq=380 + rng.randint(-25, 25),
                                          bandwidth=1000, q=2.5, sr=sr,
                                          excitation_decay=400) * 0.28
        thud *= _env_adsr(t, 0.003, 0.012, 0.10, 0.02, delay=0.004)
        ring_ks = _karplus_strong(2800 + rng.randint(-150, 150), dur * 0.7, sr,
                                    brightness=0.2, damping=0.6, rng=rng)
        ring_ks_len = min(len(ring_ks), n)
        ring = np.zeros(n, dtype=np.float64)
        ring[:ring_ks_len] = ring_ks[:ring_ks_len]
        ring = _comb_filter(ring, delay_ms=0.20, feedback=0.30, sr=sr) * 0.14
        out = ping + thud + ring
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _pinball_bumper_c(self, v: int = 0) -> np.ndarray:
        """Pop bumper C — lowest pitch bumper."""
        sr, dur = self.sample_rate, 0.085
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 700)
        cap_modes = _metal_plate_modes(3800 + rng.randint(-250, 250), n_modes=5, rng=rng)
        ping = _modal_impact(n, rng, cap_modes, sr,
                              noise_mix=0.12, noise_decay=450) * 0.44
        thud = _noise_excited_resonator(n, rng,
                                          center_freq=300 + rng.randint(-25, 25),
                                          bandwidth=1000, q=2.5, sr=sr,
                                          excitation_decay=400) * 0.34
        thud *= _env_adsr(t, 0.004, 0.012, 0.12, 0.02, delay=0.005)
        out = ping + thud
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _pinball_target(self, v: int = 0) -> np.ndarray:
        """Drop target / standup target — metallic clang."""
        sr, dur = self.sample_rate, 0.065
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 900)
        # Target clang: metal plate modal modes (physically correct for struck metal).
        target_modes = _metal_plate_modes(3000 + rng.randint(-200, 200), n_modes=5, rng=rng)
        clang = _modal_impact(n, rng, target_modes, sr,
                                noise_mix=0.10, noise_decay=600) * 0.42
        # Target body: noise-excited resonator.
        body = _noise_excited_resonator(n, rng,
                                          center_freq=250 + rng.randint(-20, 20),
                                          bandwidth=800, q=2.0, sr=sr,
                                          excitation_decay=450) * 0.28
        body *= _env_adsr(t, 0.003, 0.010, 0.08, 0.02, delay=0.004)
        out = clang + body
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    # ══════════════════════════════════════════════════════════════════
    # TELEGRAPH profile — morse-code dots, dashes, relay clicks
    # ══════════════════════════════════════════════════════════════════
    def _telegraph_builders(self) -> Dict[str, Tuple]:
        b = self
        return {
            "key":               (b._telegraph_key, 6),
            "dash":              (b._telegraph_dash, 4),
            "long_gap":          (b._telegraph_long_gap, 3),
            "repeater_click":    (b._telegraph_repeater, 3),
            "end_transmission":  (b._telegraph_end, 3),
            "correction":        (b._telegraph_correction, 3),
            "dot":               (b._telegraph_dot, 4),
        }

    def _telegraph_key(self, v: int = 0) -> np.ndarray:
        """Standard telegraph key tap — electromagnetic relay click."""
        sr, dur = self.sample_rate, 0.06
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v)
        pitch = 1.0 + (v - 2.5) * 0.04
        # Relay arm: Karplus-Strong (metal arm vibrates like a plucked string).
        ks_relay = _karplus_strong(2800 * pitch + rng.randint(-200, 200), dur * 0.6, sr,
                                     brightness=0.3, damping=0.65, rng=rng)
        ks_len = min(len(ks_relay), n)
        strike = np.zeros(n, dtype=np.float64)
        strike[:ks_len] = ks_relay[:ks_len]
        strike *= _env_adsr(t, 0.0002, 0.008, 0.10, 0.025) * 0.40
        # Electromagnetic buzz: SVF resonant noise at 120Hz.
        em = _svf_resonant_noise(n, rng, freq=120 * pitch + rng.randint(-10, 10),
                                   q=8.0, sr=sr, decay=180) * 0.15
        # Contact click: metal plate modal modes.
        contact_modes = _metal_plate_modes(5000 + rng.randint(-300, 300), n_modes=3, rng=rng)
        click = _modal_impact(n, rng, contact_modes, sr,
                                noise_mix=0.05, noise_decay=1200) * 0.18
        # Wood base: wood bar modal modes.
        wood_modes = _wood_bar_modes(180 + rng.randint(-15, 15), n_modes=3, rng=rng)
        wood = _modal_impact(n, rng, wood_modes, sr,
                              noise_mix=0.04, noise_decay=300) * 0.20
        wood *= _env_adsr(t, 0.005, 0.015, 0.08, 0.03, delay=0.006)
        out = strike + em + click + wood
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _telegraph_dot(self, v: int = 0) -> np.ndarray:
        """Short dot — quick tap (on/off)."""
        sr, dur = self.sample_rate, 0.05
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 100)
        f_tap = 3200 + rng.randint(-200, 200)
        tap = np.sin(2 * np.pi * f_tap * t) * np.exp(-t * 500) * 0.40
        f_base = 160 + rng.randint(-12, 12)
        base = np.sin(2 * np.pi * f_base * t) * np.exp(-t * 150) * 0.20
        out = tap + base
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _telegraph_dash(self, v: int = 0) -> np.ndarray:
        """Long dash — sustained tone (3x dot length)."""
        sr, dur = self.sample_rate, 0.15
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 200)
        f_tone = 800 + rng.randint(-40, 40)
        # Sustained tone with gentle decay.
        tone = np.sin(2 * np.pi * f_tone * t) * _env_adsr(t, 0.0005, 0.01, 0.6, 0.04) * 0.35
        # Relay buzz underneath.
        f_buzz = 120 + rng.randint(-10, 10)
        buzz = np.sin(2 * np.pi * f_buzz * t) * _env_adsr(t, 0.001, 0.01, 0.4, 0.03) * 0.15
        # Contact close/open clicks.
        close_click = rng.randn(min(30, n)) * 0.15 * np.exp(-np.linspace(0, 3000, min(30, n)))
        close_click = np.pad(close_click, (0, n - len(close_click)))
        open_click = np.zeros(n, dtype=np.float64)
        open_idx = int(0.13 * sr)
        if open_idx + 30 < n:
            open_click[open_idx:open_idx + 30] = rng.randn(30) * 0.10 * np.exp(-np.linspace(0, 2500, 30))
        out = tone + buzz + close_click + open_click
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _telegraph_long_gap(self, v: int = 0) -> np.ndarray:
        """Long gap — quiet pause with subtle room ambience."""
        sr, dur = self.sample_rate, 0.20
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 300)
        # Very subtle ambient hum.
        f_hum = 60
        hum = np.sin(2 * np.pi * f_hum * t) * 0.02
        # Tiny random tick.
        tick_idx = rng.randint(n // 3, 2 * n // 3)
        tick = np.zeros(n, dtype=np.float64)
        tick_len = min(40, n - tick_idx)
        if tick_len > 0:
            tick[tick_idx:tick_idx + tick_len] = rng.randn(tick_len) * np.exp(-np.linspace(0, 1000, tick_len)) * 0.08
        out = hum + tick
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _telegraph_repeater(self, v: int = 0) -> np.ndarray:
        """Repeater click — rapid double-tap mechanical sound."""
        sr, dur = self.sample_rate, 0.10
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 400)
        f_click = 3500 + rng.randint(-200, 200)
        # First tap.
        tap1 = np.sin(2 * np.pi * f_click * t) * np.exp(-t * 400) * 0.35
        # Second tap (40ms later).
        tap2_env = np.exp(-np.maximum(0, t - 0.04) * 400) * (t >= 0.04).astype(float)
        f_click2 = 3600 + rng.randint(-200, 200)
        tap2 = np.sin(2 * np.pi * f_click2 * t) * tap2_env * 0.35
        # Electromagnetic snap.
        snap = _bandpass_noise(n, rng, 500, 3000, sr) * np.exp(-t * 200) * 0.12
        out = tap1 + tap2 + snap
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _telegraph_end(self, v: int = 0) -> np.ndarray:
        """End of transmission — three dots + long dash (sign-off)."""
        sr, dur = self.sample_rate, 0.60
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 500)
        out = np.zeros(n, dtype=np.float64)
        f_base = 800 + rng.randint(-40, 40)
        # Three quick dots.
        for i in range(3):
            delay = i * 0.08
            t_seg = np.clip(t - delay, 0, None)
            seg = np.sin(2 * np.pi * f_base * t) * np.exp(-t_seg * 300) * 0.35 * (t >= delay).astype(float)
            out += seg
        # Long closing dash.
        dash_delay = 0.28
        t_seg = np.clip(t - dash_delay, 0, None)
        dash = np.sin(2 * np.pi * f_base * t) * np.exp(-t_seg * 8) * 0.40 * (t >= dash_delay).astype(float)
        out += dash
        # Final relay click.
        final_delay = 0.50
        t_f = np.clip(t - final_delay, 0, None)
        final = np.sin(2 * np.pi * 4000 * t) * np.exp(-t_f * 600) * 0.20 * (t >= final_delay).astype(float)
        out += final
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _telegraph_correction(self, v: int = 0) -> np.ndarray:
        """Correction signal — rapid buzz (error indication)."""
        sr, dur = self.sample_rate, 0.12
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 600)
        # Rapid buzzing tone.
        f_buzz = 600 + rng.randint(-30, 30)
        buzz = np.sign(np.sin(2 * np.pi * f_buzz * t)) * _env_adsr(t, 0.001, 0.01, 0.4, 0.04) * 0.25
        # Error tone (dissonant).
        f_err = 930 + rng.randint(-40, 40)
        err = np.sin(2 * np.pi * f_err * t) * _env_adsr(t, 0.001, 0.01, 0.3, 0.03) * 0.25
        # Mechanical rattle.
        rattle = _butter_lowpass(rng.randn(n), 0.25, 1) * np.exp(-t * 100) * 0.12
        out = buzz + err + rattle
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    # ══════════════════════════════════════════════════════════════════
    # ARCADE BUTTON profile — microswitch clicks + cabinet resonance
    # ══════════════════════════════════════════════════════════════════
    def _arcade_builders(self) -> Dict[str, Tuple]:
        b = self
        return {
            "key":           (b._arcade_key, 6),
            "start_coin":    (b._arcade_start_coin, 3),
            "punch":         (b._arcade_punch, 4),
            "macro":         (b._arcade_macro, 3),
            "insert_coin":   (b._arcade_insert_coin, 3),
            "delete_buzz":   (b._arcade_delete_buzz, 3),
            "a_btn":         (b._arcade_a_btn, 4),
            "b_btn":         (b._arcade_b_btn, 4),
        }

    def _arcade_key(self, v: int = 0) -> np.ndarray:
        """Standard arcade button press — microswitch click + cabinet."""
        sr, dur = self.sample_rate, 0.06
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v)
        pitch = 1.0 + (v - 2.5) * 0.04
        # Microswitch click: metal plate modal modes (tiny metal contact).
        sw_modes = _metal_plate_modes(3200 * pitch + rng.randint(-200, 200), n_modes=4, rng=rng)
        click = _modal_impact(n, rng, sw_modes, sr,
                                noise_mix=0.08, noise_decay=800) * 0.35
        click *= _env_adsr(t, 0.0002, 0.006, 0.06, 0.02)
        # Switch spring return: Karplus-Strong.
        ks_sw = _karplus_strong(4800 * pitch + rng.randint(-300, 300), dur * 0.5, sr,
                                  brightness=0.2, damping=0.7, rng=rng)
        ks_len = min(len(ks_sw), n)
        spring = np.zeros(n, dtype=np.float64)
        spring[:ks_len] = ks_sw[:ks_len]
        spring *= np.exp(-t * 400) * 0.15
        # Button dome (plastic).
        f_dome = 600 + rng.randint(-40, 40)
        dome = np.sin(2 * np.pi * f_dome * t) * _env_adsr(t, 0.002, 0.010, 0.08, 0.02, delay=0.003) * 0.25
        # Cabinet resonance.
        f_cab = 120 + rng.randint(-10, 10)
        cab = np.sin(2 * np.pi * f_cab * t) * np.exp(-t * 80) * 0.15
        out = click + spring + dome + cab
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _arcade_a_btn(self, v: int = 0) -> np.ndarray:
        """A button — bright, punchy microswitch."""
        sr, dur = self.sample_rate, 0.055
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 100)
        pitch = 1.0 + v * 0.05
        f_click = 3500 * pitch + rng.randint(-200, 200)
        click = np.sin(2 * np.pi * f_click * t) * _env_adsr(t, 0.0002, 0.006, 0.05, 0.015) * 0.38
        f_spring = 5200 * pitch + rng.randint(-300, 300)
        spring = np.sin(2 * np.pi * f_spring * t) * np.exp(-t * 450) * 0.12
        f_cab = 130 + rng.randint(-10, 10)
        cab = np.sin(2 * np.pi * f_cab * t) * np.exp(-t * 90) * 0.18
        out = click + spring + cab
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _arcade_b_btn(self, v: int = 0) -> np.ndarray:
        """B button — slightly deeper than A."""
        sr, dur = self.sample_rate, 0.058
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 200)
        pitch = 0.92 + v * 0.04
        f_click = 3000 * pitch + rng.randint(-200, 200)
        click = np.sin(2 * np.pi * f_click * t) * _env_adsr(t, 0.0002, 0.007, 0.06, 0.018) * 0.36
        f_spring = 4600 * pitch + rng.randint(-250, 250)
        spring = np.sin(2 * np.pi * f_spring * t) * np.exp(-t * 400) * 0.12
        f_cab = 110 + rng.randint(-10, 10)
        cab = np.sin(2 * np.pi * f_cab * t) * np.exp(-t * 85) * 0.20
        out = click + spring + cab
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _arcade_punch(self, v: int = 0) -> np.ndarray:
        """Punch button (fighting game) — heavy thwack."""
        sr, dur = self.sample_rate, 0.07
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 300)
        # Impact thwack.
        f_impact = 800 + rng.randint(-50, 50)
        impact = np.sin(2 * np.pi * f_impact * t) * _env_adsr(t, 0.0005, 0.008, 0.12, 0.02) * 0.45
        # Microswitch click.
        f_click = 3000 + rng.randint(-200, 200)
        click = np.sin(2 * np.pi * f_click * t) * np.exp(-t * 500) * 0.25
        # Cabinet punch.
        f_cab = 100 + rng.randint(-8, 8)
        cab = np.sin(2 * np.pi * f_cab * t) * _env_adsr(t, 0.004, 0.015, 0.12, 0.03, delay=0.006) * 0.30
        out = impact + click + cab
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _arcade_macro(self, v: int = 0) -> np.ndarray:
        """Macro button — rapid triple click."""
        sr, dur = self.sample_rate, 0.12
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 400)
        out = np.zeros(n, dtype=np.float64)
        for i in range(3):
            delay = i * 0.03
            t_seg = np.clip(t - delay, 0, None)
            f = 3200 + rng.randint(-200, 200) + i * 200
            seg = np.sin(2 * np.pi * f * t) * np.exp(-t_seg * 350) * 0.30 * (t >= delay).astype(float)
            out += seg
        # Cabinet resonance.
        f_cab = 110 + rng.randint(-8, 8)
        cab = np.sin(2 * np.pi * f_cab * t) * np.exp(-t * 60) * 0.15
        out += cab
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _arcade_start_coin(self, v: int = 0) -> np.ndarray:
        """Start button / coin credit — classic ascending chime."""
        sr = self.sample_rate
        dur = 0.25
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 500)
        out = np.zeros(n, dtype=np.float64)
        # Two ascending tones using bell modes for chime quality.
        for i, f_base in enumerate([1200, 1800]):
            f = f_base + rng.randint(-60, 60)
            delay = i * 0.08
            t_seg = np.clip(t - delay, 0, None)
            chime_modes = _bell_modes(f, n_modes=5, rng=rng)
            # Generate modal impact for the bell.
            seg_n = n - int(delay * sr)
            if seg_n > 0:
                seg_raw = _modal_impact(seg_n, rng, chime_modes, sr,
                                          noise_mix=0.02, noise_decay=30)
                seg = np.zeros(n, dtype=np.float64)
                seg_start = int(delay * sr)
                seg_end = min(seg_start + seg_n, n)
                seg[seg_start:seg_end] = seg_raw[:seg_end - seg_start]
                seg *= np.exp(-t_seg * 12) * 0.35
            else:
                seg = np.zeros(n, dtype=np.float64)
            out += seg
        # High sparkle — metal plate modes for bright metallic shimmer.
        t_seg = np.clip(t - 0.16, 0, None)
        hi_modes = _metal_plate_modes(3600 + rng.randint(-200, 200), n_modes=3, rng=rng)
        hi_n = n - int(0.16 * sr)
        if hi_n > 0:
            hi_raw = _modal_impact(hi_n, rng, hi_modes, sr,
                                     noise_mix=0.03, noise_decay=40)
            hi = np.zeros(n, dtype=np.float64)
            hi_start = int(0.16 * sr)
            hi_end = min(hi_start + hi_n, n)
            hi[hi_start:hi_end] = hi_raw[:hi_end - hi_start]
            hi *= np.exp(-t_seg * 15) * 0.22
        else:
            hi = np.zeros(n, dtype=np.float64)
        out += hi
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _arcade_insert_coin(self, v: int = 0) -> np.ndarray:
        """Insert coin — coin sliding in + credit ding."""
        sr, dur = self.sample_rate, 0.30
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 600)
        # Coin slide (metal friction).
        slide = _butter_lowpass(rng.randn(n), 0.30, 1) * np.exp(-t * 12) * 0.20
        # Coin drop thud.
        f_thud = 250 + rng.randint(-20, 20)
        thud = np.sin(2 * np.pi * f_thud * t) * _env_adsr(t, 0.005, 0.02, 0.10, 0.04, delay=0.08) * 0.35
        # Credit ding.
        f_ding = 2800 + rng.randint(-150, 150)
        t_seg = np.clip(t - 0.15, 0, None)
        ding = np.sin(2 * np.pi * f_ding * t) * np.exp(-t_seg * 18) * 0.35 * (t >= 0.15).astype(float)
        out = slide + thud + ding
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _arcade_delete_buzz(self, v: int = 0) -> np.ndarray:
        """Delete/back buzz — error buzzer."""
        sr, dur = self.sample_rate, 0.15
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 700)
        f_buzz = 200 + rng.randint(-15, 15)
        buzz = np.sign(np.sin(2 * np.pi * f_buzz * t)) * _env_adsr(t, 0.002, 0.01, 0.3, 0.04) * 0.30
        # Dissonant overtone.
        f_dis = 265 + rng.randint(-15, 15)
        dis = np.sign(np.sin(2 * np.pi * f_dis * t)) * _env_adsr(t, 0.002, 0.01, 0.2, 0.03) * 0.15
        out = buzz + dis
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    # ══════════════════════════════════════════════════════════════════
    # GUNSHOT profile — punchy percussive booms per keystroke
    # ══════════════════════════════════════════════════════════════════
    def _gunshot_builders(self) -> Dict[str, Tuple]:
        b = self
        return {
            "key":           (b._gunshot_key, 6),
            "shotgun":       (b._gunshot_shotgun, 3),
            "rifle":         (b._gunshot_rifle, 4),
            "burst":         (b._gunshot_burst, 3),
            "cannon":        (b._gunshot_cannon, 3),
            "silenced_hit":  (b._gunshot_silenced_hit, 3),
            "pistol":        (b._gunshot_pistol, 4),
            "revolver":      (b._gunshot_revolver, 4),
        }

    def _gunshot_key(self, v: int = 0) -> np.ndarray:
        """Generic shot — short percussive boom."""
        sr, dur = self.sample_rate, 0.10
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v)
        pitch = 1.0 + (v - 2.5) * 0.06
        # Initial crack (explosion transient).
        crack_len = min(120, n)
        crack = rng.randn(crack_len) * np.exp(-np.linspace(0, 1500, crack_len)) * 0.30
        crack = np.pad(crack, (0, n - len(crack)))
        # Boom body: noise-excited resonator (explosion excites the room).
        boom = _noise_excited_resonator(n, rng,
                                          center_freq=80 * pitch + rng.randint(-8, 8),
                                          bandwidth=500, q=3.0, sr=sr,
                                          excitation_decay=250) * 0.50
        boom *= _env_adsr(t, 0.002, 0.02, 0.25, 0.05, delay=0.005)
        # Mid-range punch: SVF resonant noise.
        mid = _svf_resonant_noise(n, rng, freq=400 * pitch + rng.randint(-30, 30),
                                   q=4.0, sr=sr, decay=120) * 0.22
        # Echo/reverb tail: comb filter for room reflections.
        echo_base = _svf_resonant_noise(n, rng, freq=120 * pitch + rng.randint(-10, 10),
                                          q=6.0, sr=sr, decay=30) * 0.20
        echo = _comb_filter(echo_base, delay_ms=12.0, feedback=0.45, sr=sr)
        echo *= _env_adsr(t, 0.015, 0.03, 0.15, 0.06, delay=0.03)
        out = crack + boom + mid + echo
        out = _svf_filter(out, 8800, 0.707, sr, mode='lp')
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _gunshot_pistol(self, v: int = 0) -> np.ndarray:
        """Pistol shot — sharp crack + quick decay."""
        sr, dur = self.sample_rate, 0.12
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 100)
        pitch = 1.0 + v * 0.06
        # Muzzle crack.
        crack_len = min(150, n)
        crack = rng.randn(crack_len) * np.exp(-np.linspace(0, 1200, crack_len)) * 0.35
        crack = np.pad(crack, (0, n - len(crack)))
        # Gunshot body: noise-excited resonator (barrel resonance).
        body = _noise_excited_resonator(n, rng,
                                          center_freq=120 * pitch + rng.randint(-10, 10),
                                          bandwidth=600, q=3.5, sr=sr,
                                          excitation_decay=300) * 0.45
        body *= _env_adsr(t, 0.001, 0.015, 0.20, 0.04, delay=0.003)
        # Mechanical slide action.
        slide_delay = int(0.06 * sr)
        if slide_delay + 60 < n:
            f_slide = 2500 + rng.randint(-200, 200)
            t_s = np.arange(60) / sr
            slide = np.sin(2 * np.pi * f_slide * t_s) * np.exp(-t_s * 200) * 0.15
            buf = np.zeros(n, dtype=np.float64)
            buf[slide_delay:slide_delay + 60] = slide
        else:
            buf = np.zeros(n, dtype=np.float64)
        out = crack + body + buf
        out = _svf_filter(out, 8400, 0.707, sr, mode='lp')
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _gunshot_revolver(self, v: int = 0) -> np.ndarray:
        """Revolver — deeper boom + cylinder rotation click."""
        sr, dur = self.sample_rate, 0.14
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 200)
        pitch = 1.0 + v * 0.05
        # Muzzle blast (deeper than pistol).
        crack_len = min(180, n)
        crack = rng.randn(crack_len) * np.exp(-np.linspace(0, 900, crack_len)) * 0.30
        crack = np.pad(crack, (0, n - len(crack)))
        # Deep boom: noise-excited resonator (larger caliber = lower, longer).
        boom = _noise_excited_resonator(n, rng,
                                          center_freq=70 * pitch + rng.randint(-6, 6),
                                          bandwidth=400, q=3.0, sr=sr,
                                          excitation_decay=200) * 0.50
        boom *= _env_adsr(t, 0.003, 0.025, 0.28, 0.05, delay=0.005)
        # Cylinder click (delayed).
        cyl_delay = int(0.08 * sr)
        if cyl_delay + 50 < n:
            f_cyl = 4000 + rng.randint(-300, 300)
            t_c = np.arange(50) / sr
            cyl = np.sin(2 * np.pi * f_cyl * t_c) * np.exp(-t_c * 300) * 0.15
            buf = np.zeros(n, dtype=np.float64)
            buf[cyl_delay:cyl_delay + 50] = cyl
        else:
            buf = np.zeros(n, dtype=np.float64)
        out = crack + boom + buf
        out = _svf_filter(out, 7700, 0.707, sr, mode='lp')
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _gunshot_shotgun(self, v: int = 0) -> np.ndarray:
        """Shotgun blast — long, powerful boom with chamber echo."""
        sr, dur = self.sample_rate, 0.25
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 300)
        # Massive initial crack.
        crack_len = min(300, n)
        crack = rng.randn(crack_len) * np.exp(-np.linspace(0, 500, crack_len)) * 0.30
        crack = np.pad(crack, (0, n - len(crack)))
        # Deep boom.
        f_boom = 55 + rng.randint(-5, 5)
        boom = np.sin(2 * np.pi * f_boom * t) * _env_adsr(t, 0.003, 0.03, 0.35, 0.08, delay=0.005) * 0.60
        # Racking sound (pump action, delayed).
        rack_delay = int(0.12 * sr)
        rack_len = min(120, n - rack_delay)
        if rack_len > 0:
            f_rack = 300 + rng.randint(-25, 25)
            t_r = np.arange(rack_len) / sr
            rack = np.sin(2 * np.pi * f_rack * t_r) * np.exp(-t_r * 60) * 0.25
            # Click at end of rack.
            click = rng.randn(min(40, rack_len)) * np.exp(-np.linspace(0, 800, min(40, rack_len))) * 0.20
            click = np.pad(click, (0, max(0, rack_len - len(click))))
            buf = np.zeros(n, dtype=np.float64)
            buf[rack_delay:rack_delay + rack_len] = rack + click
        else:
            buf = np.zeros(n, dtype=np.float64)
        out = crack + boom + buf
        out = _butter_lowpass(out, 0.32, 1)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _gunshot_rifle(self, v: int = 0) -> np.ndarray:
        """Rifle shot — sharp crack + long echo."""
        sr, dur = self.sample_rate, 0.20
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 400)
        pitch = 1.0 + v * 0.04
        # Supersonic crack.
        crack_len = min(200, n)
        crack = rng.randn(crack_len) * np.exp(-np.linspace(0, 800, crack_len)) * 0.35
        crack = np.pad(crack, (0, n - len(crack)))
        # Rifle boom.
        f_boom = 90 * pitch + rng.randint(-8, 8)
        boom = np.sin(2 * np.pi * f_boom * t) * _env_adsr(t, 0.002, 0.02, 0.22, 0.06, delay=0.004) * 0.50
        # Long echo tail.
        f_echo = 100 * pitch + rng.randint(-8, 8)
        echo = np.sin(2 * np.pi * f_echo * t) * _env_adsr(t, 0.02, 0.04, 0.15, 0.08, delay=0.04) * 0.25
        # Bolt action click.
        bolt_delay = int(0.10 * sr)
        if bolt_delay + 40 < n:
            f_bolt = 3500 + rng.randint(-200, 200)
            t_b = np.arange(40) / sr
            bolt = np.sin(2 * np.pi * f_bolt * t_b) * np.exp(-t_b * 250) * 0.15
            buf = np.zeros(n, dtype=np.float64)
            buf[bolt_delay:bolt_delay + 40] = bolt
        else:
            buf = np.zeros(n, dtype=np.float64)
        out = crack + boom + echo + buf
        out = _butter_lowpass(out, 0.36, 1)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _gunshot_burst(self, v: int = 0) -> np.ndarray:
        """Burst fire — 3 rapid shots."""
        sr, dur = self.sample_rate, 0.25
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 500)
        out = np.zeros(n, dtype=np.float64)
        for i in range(3):
            delay = int(i * 0.06 * sr)
            seg_len = min(int(0.08 * sr), n - delay)
            if seg_len <= 0:
                continue
            t_seg = np.arange(seg_len) / sr
            # Mini shot.
            crack = rng.randn(min(80, seg_len)) * np.exp(-np.linspace(0, 1500, min(80, seg_len))) * 0.30
            crack = np.pad(crack, (0, max(0, seg_len - len(crack))))
            f_boom = 90 + rng.randint(-8, 8)
            boom = np.sin(2 * np.pi * f_boom * t_seg) * _env_adsr(t_seg, 0.002, 0.015, 0.15, 0.03, delay=0.003) * 0.45
            seg = crack + boom
            buf = np.zeros(n, dtype=np.float64)
            buf[delay:delay + seg_len] = seg
            out += buf
        out = _butter_lowpass(out, 0.36, 1)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _gunshot_cannon(self, v: int = 0) -> np.ndarray:
        """Cannon — massive deep boom with long decay."""
        sr, dur = self.sample_rate, 0.40
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 600)
        # Huge initial blast noise.
        crack_len = min(400, n)
        crack = rng.randn(crack_len) * np.exp(-np.linspace(0, 300, crack_len)) * 0.35
        crack = np.pad(crack, (0, n - len(crack)))
        # Massive sub-bass boom.
        f_boom = 40 + rng.randint(-4, 4)
        boom = np.sin(2 * np.pi * f_boom * t) * _env_adsr(t, 0.005, 0.04, 0.40, 0.12, delay=0.008) * 0.65
        # Shockwave mid.
        f_shock = 200 + rng.randint(-15, 15)
        shock = np.sin(2 * np.pi * f_shock * t) * _env_adsr(t, 0.003, 0.02, 0.18, 0.06, delay=0.005) * 0.30
        # Rumble tail.
        rumble = _butter_lowpass(rng.randn(n), 0.08, 2) * _env_adsr(t, 0.01, 0.05, 0.30, 0.12, delay=0.02) * 0.20
        out = crack + boom + shock + rumble
        out = _butter_lowpass(out, 0.30, 1)
        out = np.nan_to_num(out, 0.0)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _gunshot_silenced_hit(self, v: int = 0) -> np.ndarray:
        """Silenced pistol — quiet mechanical action (used in Gunshot profile for backspace)."""
        sr, dur = self.sample_rate, 0.06
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 700)
        # Suppressed pop.
        f_pop = 300 + rng.randint(-25, 25)
        pop = np.sin(2 * np.pi * f_pop * t) * _env_adsr(t, 0.001, 0.008, 0.10, 0.02) * 0.35
        # Mechanical action.
        f_mech = 2000 + rng.randint(-150, 150)
        mech = np.sin(2 * np.pi * f_mech * t) * np.exp(-t * 300) * 0.15
        # Gas escape.
        gas = _butter_lowpass(rng.randn(n), 0.12, 2) * np.exp(-t * 120) * 0.20
        out = pop + mech + gas
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    # ══════════════════════════════════════════════════════════════════
    # GUNSHOT SILENCED profile — suppressed, low and subtle
    # ══════════════════════════════════════════════════════════════════
    def _silenced_builders(self) -> Dict[str, Tuple]:
        b = self
        return {
            "key":           (b._silenced_key, 6),
            "heavy_thump":   (b._silenced_heavy, 3),
            "medium_thump":  (b._silenced_medium, 4),
            "triple_tap":    (b._silenced_triple, 3),
            "deep_boom":     (b._silenced_deep, 3),
            "gas_leak":      (b._silenced_gas_leak, 3),
            "soft_pfft":     (b._silenced_soft, 4),
            "low_pop":       (b._silenced_pop, 4),
        }

    def _silenced_key(self, v: int = 0) -> np.ndarray:
        """Suppressed shot — quiet pop + gas hiss."""
        sr, dur = self.sample_rate, 0.08
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v)
        pitch = 1.0 + (v - 2.5) * 0.05
        # Suppressed pop.
        f_pop = 200 * pitch + rng.randint(-15, 15)
        pop = np.sin(2 * np.pi * f_pop * t) * _env_adsr(t, 0.001, 0.008, 0.10, 0.02) * 0.40
        # Gas escape: SVF resonant noise for more natural hiss.
        gas = _svf_resonant_noise(n, rng, freq=800, q=1.5, sr=sr, decay=100) * 0.25
        # Mechanical action.
        f_mech = 1800 + rng.randint(-150, 150)
        mech = np.sin(2 * np.pi * f_mech * t) * np.exp(-t * 250) * 0.10
        out = pop + gas + mech
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _silenced_soft(self, v: int = 0) -> np.ndarray:
        """Soft pfft — very quiet, subtle."""
        sr, dur = self.sample_rate, 0.06
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 100)
        f_pop = 250 + rng.randint(-20, 20)
        pop = np.sin(2 * np.pi * f_pop * t) * np.exp(-t * 150) * 0.35
        gas = _butter_lowpass(rng.randn(n), 0.12, 2) * np.exp(-t * 130) * 0.22
        out = pop + gas
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _silenced_pop(self, v: int = 0) -> np.ndarray:
        """Low pop — slightly louder suppressed shot."""
        sr, dur = self.sample_rate, 0.07
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 200)
        f_pop = 180 + rng.randint(-15, 15)
        pop = np.sin(2 * np.pi * f_pop * t) * _env_adsr(t, 0.001, 0.010, 0.12, 0.02) * 0.42
        gas = _butter_lowpass(rng.randn(n), 0.13, 2) * np.exp(-t * 110) * 0.25
        f_mech = 1500 + rng.randint(-120, 120)
        mech = np.sin(2 * np.pi * f_mech * t) * np.exp(-t * 280) * 0.08
        out = pop + gas + mech
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _silenced_medium(self, v: int = 0) -> np.ndarray:
        """Medium thump — suppressed but noticeable."""
        sr, dur = self.sample_rate, 0.09
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 300)
        f_thump = 150 + rng.randint(-12, 12)
        thump = np.sin(2 * np.pi * f_thump * t) * _env_adsr(t, 0.002, 0.012, 0.15, 0.03, delay=0.004) * 0.50
        gas = _butter_lowpass(rng.randn(n), 0.14, 2) * np.exp(-t * 90) * 0.28
        f_mech = 1600 + rng.randint(-120, 120)
        mech = np.sin(2 * np.pi * f_mech * t) * np.exp(-t * 220) * 0.10
        out = thump + gas + mech
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _silenced_heavy(self, v: int = 0) -> np.ndarray:
        """Heavy thump — suppressed large caliber."""
        sr, dur = self.sample_rate, 0.12
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 400)
        f_thump = 100 + rng.randint(-8, 8)
        thump = np.sin(2 * np.pi * f_thump * t) * _env_adsr(t, 0.003, 0.018, 0.20, 0.04, delay=0.006) * 0.55
        # Sub-bass rumble.
        f_sub = 50 + rng.randint(-4, 4)
        sub = np.sin(2 * np.pi * f_sub * t) * _env_adsr(t, 0.005, 0.025, 0.18, 0.05, delay=0.010) * 0.35
        gas = _svf_resonant_noise(n, rng, freq=600, q=1.2, sr=sr, decay=70) * 0.22
        out = thump + sub + gas
        out = np.nan_to_num(out, 0.0)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _silenced_deep(self, v: int = 0) -> np.ndarray:
        """Deep boom — suppressed but powerful."""
        sr, dur = self.sample_rate, 0.18
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 500)
        f_boom = 65 + rng.randint(-5, 5)
        boom = np.sin(2 * np.pi * f_boom * t) * _env_adsr(t, 0.004, 0.02, 0.25, 0.06, delay=0.008) * 0.60
        # Gas expansion: SVF resonant noise (deeper, slower).
        gas = _svf_resonant_noise(n, rng, freq=500, q=1.0, sr=sr, decay=40) * 0.25
        gas *= _env_adsr(t, 0.006, 0.03, 0.20, 0.06, delay=0.008)
        # Mechanical slide.
        f_slide = 1200 + rng.randint(-100, 100)
        slide = np.sin(2 * np.pi * f_slide * t) * np.exp(-np.maximum(0, t - 0.06) * 150) * (t >= 0.06).astype(float) * 0.12
        out = boom + gas + slide
        out = np.nan_to_num(out, 0.0)
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _silenced_triple(self, v: int = 0) -> np.ndarray:
        """Triple tap — three quick suppressed pops."""
        sr, dur = self.sample_rate, 0.18
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 600)
        out = np.zeros(n, dtype=np.float64)
        for i in range(3):
            delay = int(i * 0.045 * sr)
            seg_len = min(int(0.06 * sr), n - delay)
            if seg_len <= 0:
                continue
            t_seg = np.arange(seg_len) / sr
            f = 200 + rng.randint(-15, 15)
            pop = np.sin(2 * np.pi * f * t_seg) * _env_adsr(t_seg, 0.001, 0.008, 0.10, 0.02) * 0.38
            gas = _butter_lowpass(rng.randn(seg_len), 0.14, 2) * np.exp(-t_seg * 120) * 0.18
            seg = pop + gas
            buf = np.zeros(n, dtype=np.float64)
            buf[delay:delay + seg_len] = seg
            out += buf
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _silenced_gas_leak(self, v: int = 0) -> np.ndarray:
        """Gas leak — long, slow hiss (for Escape/backspace)."""
        sr, dur = self.sample_rate, 0.15
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 700)
        # Slow gas hiss.
        gas = _butter_lowpass(rng.randn(n), 0.10, 2) * _env_adsr(t, 0.01, 0.04, 0.3, 0.05) * 0.30
        # Subtle low tone.
        f_tone = 80 + rng.randint(-6, 6)
        tone = np.sin(2 * np.pi * f_tone * t) * np.exp(-t * 50) * 0.15
        out = gas + tone
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    # ══════════════════════════════════════════════════════════════════
    # CRYSTAL SINGING BOWL profile — ethereal glass/harmonic shimmer
    # ══════════════════════════════════════════════════════════════════
    def _crystal_bowl_builders(self) -> Dict[str, Tuple]:
        b = self
        return {
            "key":            (b._crystal_bowl_key, 8),
            "full_bowl":      (b._crystal_bowl_full, 3),
            "deep_ring":      (b._crystal_bowl_deep_ring, 4),
            "shimmer_sweep":  (b._crystal_bowl_shimmer_sweep, 3),
            "dissonant":      (b._crystal_bowl_dissonant, 3),
            "fade_out":       (b._crystal_bowl_fade_out, 3),
            "harmonic_a":     (b._crystal_bowl_harmonic_a, 4),
            "harmonic_b":     (b._crystal_bowl_harmonic_b, 4),
            "chime":          (b._crystal_bowl_chime, 4),
            "sparkle":        (b._crystal_bowl_sparkle, 4),
        }

    def _crystal_bowl_key(self, v: int = 0) -> np.ndarray:
        """Crystal bowl tap — glass-like harmonic ring with shimmer."""
        sr, dur = self.sample_rate, 0.22
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v)
        pitch = 1.0 + (v - 3.5) * 0.08

        # Fundamental: bell modes for crystalline harmonic series.
        f0 = 880 * pitch + rng.randint(-20, 20)
        modes = _bell_modes(f0, n_modes=6, rng=rng)
        # Shift amplitudes toward upper partials for glass-like brightness.
        modes = [(f, a * 0.7, d, p) for f, a, d, p in modes]
        modes[0] = (modes[0][0], modes[0][1] * 0.5, modes[0][2], modes[0][3])
        bowl = _modal_impact(n, rng, modes, sr,
                              noise_mix=0.03, noise_decay=800) * 0.50

        # Shimmer: very high-frequency SVF resonant noise (glass "sizzle").
        shimmer = _svf_resonant_noise(n, rng, freq=6800 * pitch + rng.randint(-200, 200),
                                       q=6.0, sr=sr, decay=50) * 0.15
        shimmer *= _env_adsr(t, 0.002, 0.04, 0.15, 0.06, delay=0.008)

        # High harmonic overtone — pure sine with very slow decay.
        f_hi = f0 * 3.17  # inharmonic partial for crystal character
        overtone = np.sin(2 * np.pi * f_hi * t) * np.exp(-t * 6.0) * 0.18

        # Subtle beating between two close frequencies (psychedelic wobble).
        beat1 = np.sin(2 * np.pi * f0 * 2.003 * t) * np.exp(-t * 5.5) * 0.08
        beat2 = np.sin(2 * np.pi * f0 * 1.997 * t) * np.exp(-t * 5.5) * 0.08

        out = bowl + shimmer + overtone + beat1 + beat2
        # Gentle highpass to remove any sub-bass, then LP for air.
        out = _svf_filter(out, 200, 0.707, sr, mode='hp')
        out = _svf_filter(out, 11000, 0.707, sr, mode='lp')
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _crystal_bowl_full(self, v: int = 0) -> np.ndarray:
        """Full bowl strike — rich harmonic bloom (for Enter)."""
        sr, dur = self.sample_rate, 0.50
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 100)
        pitch = 0.85 + v * 0.10

        # Large bowl: lower fundamental, many modes.
        f0 = 520 * pitch + rng.randint(-15, 15)
        modes = _bell_modes(f0, n_modes=8, rng=rng)
        bowl = _modal_impact(n, rng, modes, sr,
                              noise_mix=0.02, noise_decay=600) * 0.55

        # Wobble: slow frequency modulation on a sine for vibrato.
        vibrato = np.sin(2 * np.pi * (f0 * 2.0) * t * (1 + 0.003 * np.sin(2 * np.pi * 5.5 * t)))
        vibrato *= np.exp(-t * 3.0) * 0.22

        # Shimmer tail — comb filter for metallic reverb quality.
        shimmer = _svf_resonant_noise(n, rng, freq=5500 + rng.randint(-200, 200),
                                       q=5.0, sr=sr, decay=35) * 0.12
        shimmer = _comb_filter(shimmer, delay_ms=5.2, feedback=0.55, sr=sr)

        # Beating partials (psychedelic effect).
        b1 = np.sin(2 * np.pi * f0 * 3.01 * t) * np.exp(-t * 3.5) * 0.10
        b2 = np.sin(2 * np.pi * f0 * 2.99 * t) * np.exp(-t * 3.5) * 0.10

        out = bowl + vibrato + shimmer + b1 + b2
        out = _svf_filter(out, 180, 0.707, sr, mode='hp')
        out = _svf_filter(out, 10500, 0.8, sr, mode='lp')
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _crystal_bowl_deep_ring(self, v: int = 0) -> np.ndarray:
        """Deep resonant ring (for Space)."""
        sr, dur = self.sample_rate, 0.35
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 200)
        pitch = 0.7 + v * 0.08

        f0 = 380 * pitch + rng.randint(-10, 10)
        modes = _bell_modes(f0, n_modes=5, rng=rng)
        ring = _modal_impact(n, rng, modes, sr,
                              noise_mix=0.02, noise_decay=500) * 0.55

        # Sub-harmonic drone.
        sub = np.sin(2 * np.pi * f0 * 0.5 * t) * np.exp(-t * 2.5) * 0.20
        # Slow frequency wobble (psychedelic).
        wobble = np.sin(2 * np.pi * f0 * t * (1 + 0.002 * np.sin(2 * np.pi * 3.0 * t)))
        wobble *= np.exp(-t * 3.0) * 0.15

        out = ring + sub + wobble
        out = _svf_filter(out, 120, 0.707, sr, mode='hp')
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _crystal_bowl_shimmer_sweep(self, v: int = 0) -> np.ndarray:
        """Frequency sweep shimmer (for Tab)."""
        sr, dur = self.sample_rate, 0.30
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 300)

        # Rising sweep through harmonic series.
        f_start = 1200 + v * 200
        f_end = 4000 + v * 300
        sweep = _frequency_sweep(dur, f_start, f_end, sr) * 0.30
        sweep *= _env_adsr(t, 0.002, 0.05, 0.18, 0.08, delay=0.005)

        # Bell tap at the end frequency.
        modes = _bell_modes(f_end, n_modes=4, rng=rng)
        ring = _modal_impact(n, rng, modes, sr,
                              noise_mix=0.01, noise_decay=400) * 0.30
        ring *= _env_adsr(t, 0.02, 0.04, 0.15, 0.06, delay=0.04)

        # High shimmer.
        shimmer = _svf_resonant_noise(n, rng, freq=7500, q=5.0, sr=sr, decay=40) * 0.10

        out = sweep + ring + shimmer
        out = _svf_filter(out, 600, 0.707, sr, mode='hp')
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _crystal_bowl_dissonant(self, v: int = 0) -> np.ndarray:
        """Dissonant cluster — trippy minor-second clash (for Escape)."""
        sr, dur = self.sample_rate, 0.40
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 400)

        # Two bell modes very close together for beating / dissonance.
        f1 = 660 + rng.randint(-15, 15)
        f2 = f1 * 1.0595  # semitone above — maximum tension
        modes1 = _bell_modes(f1, n_modes=4, rng=rng)
        modes2 = _bell_modes(f2, n_modes=4, rng=rng)
        d1 = _modal_impact(n, rng, modes1, sr, noise_mix=0.01, noise_decay=500) * 0.35
        d2 = _modal_impact(n, rng, modes2, sr, noise_mix=0.01, noise_decay=500) * 0.35

        # Tritone shimmer for extra unease.
        tri = np.sin(2 * np.pi * f1 * 1.414 * t) * np.exp(-t * 4.0) * 0.12

        out = d1 + d2 + tri
        out = _svf_filter(out, 200, 0.707, sr, mode='hp')
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _crystal_bowl_fade_out(self, v: int = 0) -> np.ndarray:
        """Reverse fade — sound that decays from nothing (for Backspace)."""
        sr, dur = self.sample_rate, 0.18
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 500)
        pitch = 1.0 + v * 0.06

        f0 = 1100 * pitch + rng.randint(-20, 20)
        # Quick tap then rapid exponential fade.
        modes = _bell_modes(f0, n_modes=4, rng=rng)
        ring = _modal_impact(n, rng, modes, sr,
                              noise_mix=0.02, noise_decay=1200) * 0.45

        # Reverse envelope impression: fast attack, faster decay.
        ring *= np.exp(-t * 18.0)

        out = ring
        out = _svf_filter(out, 400, 0.707, sr, mode='hp')
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _crystal_bowl_harmonic_a(self, v: int = 0) -> np.ndarray:
        """Pure harmonic overtone A — clean 5th above fundamental."""
        sr, dur = self.sample_rate, 0.25
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 600)
        f0 = 1320 + v * 80

        # Perfect fifth + octave shimmer.
        tone = np.sin(2 * np.pi * f0 * t) * np.exp(-t * 5.0) * 0.30
        fifth = np.sin(2 * np.pi * f0 * 1.5 * t) * np.exp(-t * 6.5) * 0.20
        # Beating for psychedelic texture.
        beat = np.sin(2 * np.pi * f0 * 2.002 * t) * np.exp(-t * 7.0) * 0.10
        out = tone + fifth + beat
        out = _svf_filter(out, 300, 0.707, sr, mode='hp')
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _crystal_bowl_harmonic_b(self, v: int = 0) -> np.ndarray:
        """Harmonic overtone B — major third with warble."""
        sr, dur = self.sample_rate, 0.28
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 700)
        f0 = 990 + v * 70

        # Warbling major third.
        tone = np.sin(2 * np.pi * f0 * t * (1 + 0.004 * np.sin(2 * np.pi * 6.0 * t)))
        tone *= np.exp(-t * 4.5) * 0.30
        third = np.sin(2 * np.pi * f0 * 1.25 * t) * np.exp(-t * 6.0) * 0.18
        out = tone + third
        out = _svf_filter(out, 250, 0.707, sr, mode='hp')
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _crystal_bowl_chime(self, v: int = 0) -> np.ndarray:
        """Small crystal chime — bright, short (for digits)."""
        sr, dur = self.sample_rate, 0.15
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 800)
        f0 = 2200 + v * 150 + rng.randint(-50, 50)

        modes = _bell_modes(f0, n_modes=3, rng=rng)
        chime = _modal_impact(n, rng, modes, sr,
                               noise_mix=0.02, noise_decay=700) * 0.55
        # Tiny high sparkle.
        sp = np.sin(2 * np.pi * f0 * 3.0 * t) * np.exp(-t * 12.0) * 0.10
        out = chime + sp
        out = _svf_filter(out, 1000, 0.707, sr, mode='hp')
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _crystal_bowl_sparkle(self, v: int = 0) -> np.ndarray:
        """Sparkle — tiny high-pitched crystalline ping (for punctuation)."""
        sr, dur = self.sample_rate, 0.12
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 900)
        f0 = 3500 + v * 200 + rng.randint(-100, 100)

        # Pure sine + inharmonic overtone for "crystalline" quality.
        ping = np.sin(2 * np.pi * f0 * t) * np.exp(-t * 10.0) * 0.35
        # Inharmonic partial (glass "crack").
        crack = np.sin(2 * np.pi * f0 * 2.37 * t) * np.exp(-t * 14.0) * 0.15
        # Noise transient.
        noise = rng.randn(min(30, n)) * np.exp(-np.linspace(0, 200, min(30, n))) * 0.12
        noise = np.pad(noise, (0, max(0, n - len(noise))))
        out = ping + crack + noise
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    # ══════════════════════════════════════════════════════════════════
    # SYNTH BUBBLE profile — squelchy resonant synth bubbles
    # ══════════════════════════════════════════════════════════════════
    def _synth_bubble_builders(self) -> Dict[str, Tuple]:
        b = self
        return {
            "key":            (b._synth_bubble_key, 8),
            "whoosh":         (b._synth_bubble_whoosh, 3),
            "deep_bubble":    (b._synth_bubble_deep, 4),
            "squelch_sweep":  (b._synth_bubble_squelch_sweep, 3),
            "glitch":         (b._synth_bubble_glitch, 3),
            "deflate":        (b._synth_bubble_deflate, 3),
            "bubble_a":       (b._synth_bubble_a, 4),
            "bubble_b":       (b._synth_bubble_b, 4),
            "blip":           (b._synth_bubble_blip, 4),
            "squelch":        (b._synth_bubble_squelch, 4),
        }

    def _synth_bubble_key(self, v: int = 0) -> np.ndarray:
        """Resonant synth bubble — squelchy filtered noise sweep."""
        sr, dur = self.sample_rate, 0.14
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v)
        pitch = 1.0 + (v - 3.5) * 0.07

        # Resonant noise burst — the "bubble" body.
        # SVF bandpass gives that classic squelch character.
        f_center = 600 * pitch + rng.randint(-30, 30)
        bubble = _svf_resonant_noise(n, rng, freq=f_center, q=8.0,
                                      sr=sr, decay=80) * 0.45
        bubble *= _env_adsr(t, 0.002, 0.015, 0.06, 0.04, delay=0.003)

        # Pitched "pop" at the end of the bubble.
        pop_delay = int(0.025 * sr)
        if pop_delay < n:
            f_pop = 1200 * pitch + rng.randint(-60, 60)
            t_pop = np.arange(n - pop_delay) / sr
            pop = np.sin(2 * np.pi * f_pop * t_pop) * np.exp(-t_pop * 200) * 0.20
            buf = np.zeros(n, dtype=np.float64)
            buf[pop_delay:] = pop
        else:
            buf = np.zeros(n, dtype=np.float64)

        # Sub-bass "thud" of the bubble forming.
        thud = _noise_excited_resonator(n, rng,
                                          center_freq=80 * pitch,
                                          bandwidth=200, q=2.0, sr=sr,
                                          excitation_decay=600) * 0.15
        thud *= _env_adsr(t, 0.005, 0.02, 0.08, 0.03, delay=0.002)

        # Filtered "air" release.
        air = _svf_resonant_noise(n, rng, freq=2800 * pitch, q=2.0,
                                   sr=sr, decay=45) * 0.08

        out = bubble + buf + thud + air
        # Bandpass to keep it focused and squelchy.
        out = _svf_filter(out, 250, 0.707, sr, mode='hp')
        out = _svf_filter(out, 6000, 0.707, sr, mode='lp')
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _synth_bubble_whoosh(self, v: int = 0) -> np.ndarray:
        """Whoosh — sweeping filtered noise (for Enter)."""
        sr, dur = self.sample_rate, 0.30
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 100)

        # Frequency sweep: low to high whoosh.
        f_start = 200 + v * 50
        f_end = 3000 + v * 200
        sweep = _frequency_sweep(dur, f_start, f_end, sr) * 0.25
        sweep *= _env_adsr(t, 0.005, 0.06, 0.18, 0.08, delay=0.005)

        # Noise body — shaped noise with sweep-like envelope.
        noise = _noise_shaped(n, rng, 400, 4000, sr, tilt_db=4.0) * 0.15
        noise *= _env_adsr(t, 0.005, 0.06, 0.18, 0.08, delay=0.005)

        # Bubbly resonant tail.
        bubble = _svf_resonant_noise(n, rng, freq=1800 + v * 100, q=6.0,
                                      sr=sr, decay=40) * 0.15
        bubble *= _env_adsr(t, 0.03, 0.06, 0.15, 0.06, delay=0.06)

        out = sweep + noise + bubble
        out = _svf_filter(out, 180, 0.707, sr, mode='hp')
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _synth_bubble_deep(self, v: int = 0) -> np.ndarray:
        """Deep bubble — lower pitched, larger (for Space)."""
        sr, dur = self.sample_rate, 0.22
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 200)
        pitch = 0.6 + v * 0.08

        # Low resonant bubble.
        bubble = _svf_resonant_noise(n, rng, freq=320 * pitch + rng.randint(-15, 15),
                                      q=10.0, sr=sr, decay=60) * 0.50
        bubble *= _env_adsr(t, 0.003, 0.02, 0.10, 0.05, delay=0.004)

        # Pop at end.
        pop_delay = int(0.04 * sr)
        if pop_delay < n:
            f_pop = 600 * pitch + rng.randint(-30, 30)
            t_pop = np.arange(n - pop_delay) / sr
            pop = np.sin(2 * np.pi * f_pop * t_pop) * np.exp(-t_pop * 120) * 0.25
            buf = np.zeros(n, dtype=np.float64)
            buf[pop_delay:] = pop
        else:
            buf = np.zeros(n, dtype=np.float64)

        # Sub rumble.
        sub = _noise_excited_resonator(n, rng,
                                         center_freq=55 * pitch,
                                         bandwidth=120, q=2.5, sr=sr,
                                         excitation_decay=500) * 0.18
        sub *= _env_adsr(t, 0.008, 0.025, 0.12, 0.04, delay=0.005)

        out = bubble + buf + sub
        out = _svf_filter(out, 40, 0.707, sr, mode='hp')
        out = _svf_filter(out, 5000, 0.707, sr, mode='lp')
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _synth_bubble_squelch_sweep(self, v: int = 0) -> np.ndarray:
        """Squelch with frequency sweep (for Tab)."""
        sr, dur = self.sample_rate, 0.25
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 300)

        # Descending squelch — classic acid synth character.
        f_start = 2000 + v * 200
        f_end = 300 + v * 50
        sweep = _frequency_sweep(dur, f_start, f_end, sr) * 0.30
        sweep *= _env_adsr(t, 0.001, 0.03, 0.12, 0.06)

        # Resonant squelch body.
        squelch = _svf_resonant_noise(n, rng, freq=f_end + 200, q=12.0,
                                       sr=sr, decay=55) * 0.30
        squelch *= _env_adsr(t, 0.003, 0.04, 0.14, 0.06, delay=0.01)

        out = sweep + squelch
        out = _svf_filter(out, 200, 0.707, sr, mode='hp')
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _synth_bubble_glitch(self, v: int = 0) -> np.ndarray:
        """Digital glitch — stuttering micro-slices (for Escape)."""
        sr, dur = self.sample_rate, 0.20
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 400)
        out = np.zeros(n, dtype=np.float64)

        # 4 rapid micro-bubbles with random pitch.
        for i in range(4):
            delay = int(i * 0.035 * sr)
            seg_len = min(int(0.04 * sr), n - delay)
            if seg_len <= 0:
                continue
            t_seg = np.arange(seg_len) / sr
            f = 400 + rng.randint(0, 2000)
            bub = _svf_resonant_noise(seg_len, rng, freq=f, q=8.0,
                                       sr=sr, decay=30) * 0.35
            bub *= _env_adsr(t_seg, 0.001, 0.008, 0.02, 0.01)
            buf = np.zeros(n, dtype=np.float64)
            buf[delay:delay + seg_len] = bub
            out += buf

        # Add a digital "crash" noise tail.
        crash = rng.randn(min(60, n)) * np.exp(-np.linspace(0, 400, min(60, n))) * 0.15
        crash = np.pad(crash, (0, max(0, n - len(crash))))
        out += crash
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _synth_bubble_deflate(self, v: int = 0) -> np.ndarray:
        """Deflating bubble — pitch drops rapidly (for Backspace)."""
        sr, dur = self.sample_rate, 0.16
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 500)

        # Rapidly descending pitch (deflating balloon).
        f_start = 1500 + v * 100
        f_end = 80 + v * 10
        deflation = _frequency_sweep(dur, f_start, f_end, sr) * 0.35
        deflation *= _env_adsr(t, 0.001, 0.02, 0.10, 0.05)

        # Sputtering noise.
        noise = _svf_resonant_noise(n, rng, freq=900, q=3.0,
                                     sr=sr, decay=60) * 0.15
        noise *= _env_adsr(t, 0.005, 0.03, 0.10, 0.04, delay=0.02)

        out = deflation + noise
        out = _svf_filter(out, 60, 0.707, sr, mode='hp')
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _synth_bubble_a(self, v: int = 0) -> np.ndarray:
        """Small bubble A — higher pitch, quicker (for quotes)."""
        sr, dur = self.sample_rate, 0.10
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 600)
        f = 1200 + v * 100 + rng.randint(-50, 50)

        bub = _svf_resonant_noise(n, rng, freq=f, q=9.0,
                                   sr=sr, decay=70) * 0.50
        bub *= _env_adsr(t, 0.001, 0.012, 0.05, 0.03)
        # Tiny pop.
        pop_d = int(0.02 * sr)
        if pop_d < n:
            t_p = np.arange(n - pop_d) / sr
            pop = np.sin(2 * np.pi * f * 2.5 * t_p) * np.exp(-t_p * 250) * 0.18
            buf = np.zeros(n, dtype=np.float64)
            buf[pop_d:] = pop
        else:
            buf = np.zeros(n, dtype=np.float64)
        out = bub + buf
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _synth_bubble_b(self, v: int = 0) -> np.ndarray:
        """Bubble B — medium pitch, fatter (for brackets)."""
        sr, dur = self.sample_rate, 0.12
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 700)
        f = 800 + v * 80 + rng.randint(-40, 40)

        bub = _svf_resonant_noise(n, rng, freq=f, q=10.0,
                                   sr=sr, decay=55) * 0.50
        bub *= _env_adsr(t, 0.002, 0.015, 0.06, 0.03, delay=0.002)
        # Poppier tail.
        pop_d = int(0.025 * sr)
        if pop_d < n:
            t_p = np.arange(n - pop_d) / sr
            pop = np.sin(2 * np.pi * f * 2.0 * t_p) * np.exp(-t_p * 180) * 0.20
            buf = np.zeros(n, dtype=np.float64)
            buf[pop_d:] = pop
        else:
            buf = np.zeros(n, dtype=np.float64)
        out = bub + buf
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _synth_bubble_blip(self, v: int = 0) -> np.ndarray:
        """Blip — very short synth beep (for digits)."""
        sr, dur = self.sample_rate, 0.06
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 800)
        f = 1800 + v * 120 + rng.randint(-60, 60)

        blip = np.sin(2 * np.pi * f * t) * np.exp(-t * 60) * 0.40
        # Slight detune for width.
        blip2 = np.sin(2 * np.pi * f * 1.005 * t) * np.exp(-t * 55) * 0.15
        out = blip + blip2
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _synth_bubble_squelch(self, v: int = 0) -> np.ndarray:
        """Squelch — wet, resonant pop (for punctuation)."""
        sr, dur = self.sample_rate, 0.09
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 900)
        f = 700 + v * 60 + rng.randint(-30, 30)

        squelch = _svf_resonant_noise(n, rng, freq=f, q=12.0,
                                       sr=sr, decay=55) * 0.50
        squelch *= _env_adsr(t, 0.001, 0.010, 0.04, 0.02)
        # Sub click.
        sub = _noise_excited_resonator(n, rng,
                                         center_freq=120, bandwidth=200,
                                         q=2.0, sr=sr,
                                         excitation_decay=800) * 0.12
        out = squelch + sub
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    # ══════════════════════════════════════════════════════════════════
    # TIBETAN BOWL profile — deep meditative singing bowl
    # ══════════════════════════════════════════════════════════════════
    def _tibetan_bowl_builders(self) -> Dict[str, Tuple]:
        b = self
        return {
            "key":            (b._tibetan_bowl_key, 8),
            "large_bowl":     (b._tibetan_bowl_large, 3),
            "bass_bowl":      (b._tibetan_bowl_bass, 4),
            "harmonic_tap":   (b._tibetan_bowl_harmonic_tap, 3),
            "deep_gong":      (b._tibetan_bowl_gong, 3),
            "mallet_damp":    (b._tibetan_bowl_mallet_damp, 3),
            "overtone_a":     (b._tibetan_bowl_overtone_a, 4),
            "overtone_b":     (b._tibetan_bowl_overtone_b, 4),
            "small_bell":     (b._tibetan_bowl_small_bell, 4),
            "rim_tap":        (b._tibetan_bowl_rim_tap, 4),
        }

    def _tibetan_bowl_key(self, v: int = 0) -> np.ndarray:
        """Tibetan bowl tap — deep harmonic ring with slow decay."""
        sr, dur = self.sample_rate, 0.35
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v)
        pitch = 1.0 + (v - 3.5) * 0.06

        # Fundamental — bell modes give the correct harmonic series for a bowl.
        f0 = 290 * pitch + rng.randint(-8, 8)
        modes = _bell_modes(f0, n_modes=7, rng=rng)
        # Enhance the fundamental and second partial for warmth.
        modes = [(f, a * (1.3 if i < 2 else 0.8), d, p) for i, (f, a, d, p) in enumerate(modes)]
        bowl = _modal_impact(n, rng, modes, sr,
                              noise_mix=0.02, noise_decay=400) * 0.55

        # Mallet "thock" transient — short noise burst at impact.
        thock = _noise_excited_resonator(n, rng,
                                          center_freq=1800 * pitch,
                                          bandwidth=3000, q=2.0, sr=sr,
                                          excitation_decay=2000) * 0.12
        thock *= _env_adsr(t, 0.0005, 0.005, 0.01, 0.005)

        # Sub-harmonic warmth — adds "body" to the bowl.
        sub = np.sin(2 * np.pi * f0 * 0.5 * t) * np.exp(-t * 2.0) * 0.15

        # Slow vibrato (bowl "breathing" — common in real singing bowls).
        vibrato_depth = 0.002 + v * 0.0003
        vibrato_rate = 4.5 + v * 0.2
        vib = np.sin(2 * np.pi * f0 * t * (1 + vibrato_depth * np.sin(2 * np.pi * vibrato_rate * t)))
        vib *= np.exp(-t * 2.5) * 0.12

        out = bowl + thock + sub + vib
        out = _svf_filter(out, 80, 0.707, sr, mode='hp')
        out = _svf_filter(out, 8000, 0.707, sr, mode='lp')
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _tibetan_bowl_large(self, v: int = 0) -> np.ndarray:
        """Large bowl strike — long, deep, meditative (for Enter)."""
        sr, dur = self.sample_rate, 0.70
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 100)
        pitch = 0.8 + v * 0.08

        f0 = 180 * pitch + rng.randint(-5, 5)
        modes = _bell_modes(f0, n_modes=8, rng=rng)
        modes = [(f, a * (1.4 if i < 2 else 0.7), d, p) for i, (f, a, d, p) in enumerate(modes)]
        bowl = _modal_impact(n, rng, modes, sr,
                              noise_mix=0.01, noise_decay=350) * 0.60

        # Mallet thud.
        thud = _noise_excited_resonator(n, rng,
                                         center_freq=1200,
                                         bandwidth=2500, q=1.5, sr=sr,
                                         excitation_decay=2500) * 0.10
        thud *= _env_adsr(t, 0.001, 0.008, 0.015, 0.008)

        # Deep sub drone — felt in the chest.
        drone = np.sin(2 * np.pi * f0 * 0.5 * t) * np.exp(-t * 1.2) * 0.22

        # Slow vibrato.
        vib = np.sin(2 * np.pi * f0 * t * (1 + 0.003 * np.sin(2 * np.pi * 3.5 * t)))
        vib *= np.exp(-t * 1.5) * 0.15

        # Beating upper partials for "shimmering" quality.
        b1 = np.sin(2 * np.pi * f0 * 2.005 * t) * np.exp(-t * 2.0) * 0.08
        b2 = np.sin(2 * np.pi * f0 * 1.995 * t) * np.exp(-t * 2.0) * 0.08

        out = bowl + thud + drone + vib + b1 + b2
        out = _svf_filter(out, 50, 0.707, sr, mode='hp')
        out = _svf_filter(out, 7500, 0.707, sr, mode='lp')
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _tibetan_bowl_bass(self, v: int = 0) -> np.ndarray:
        """Bass bowl — deep and warm (for Space)."""
        sr, dur = self.sample_rate, 0.50
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 200)
        pitch = 0.65 + v * 0.06

        f0 = 140 * pitch + rng.randint(-4, 4)
        modes = _bell_modes(f0, n_modes=5, rng=rng)
        bowl = _modal_impact(n, rng, modes, sr,
                              noise_mix=0.01, noise_decay=300) * 0.55

        # Warm sub.
        sub = np.sin(2 * np.pi * f0 * 0.5 * t) * np.exp(-t * 1.5) * 0.25
        # Vibrato.
        vib = np.sin(2 * np.pi * f0 * t * (1 + 0.003 * np.sin(2 * np.pi * 4.0 * t)))
        vib *= np.exp(-t * 2.0) * 0.12

        out = bowl + sub + vib
        out = _svf_filter(out, 40, 0.707, sr, mode='hp')
        out = _svf_filter(out, 6000, 0.707, sr, mode='lp')
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _tibetan_bowl_harmonic_tap(self, v: int = 0) -> np.ndarray:
        """Harmonic tap — emphasises upper partials (for Tab)."""
        sr, dur = self.sample_rate, 0.30
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 300)
        f0 = 350 + v * 30 + rng.randint(-10, 10)

        # Bell modes but emphasise partials 3-6 for harmonic ring.
        modes = _bell_modes(f0, n_modes=6, rng=rng)
        modes = [(f, a * (0.4 if i < 2 else 1.2), d, p) for i, (f, a, d, p) in enumerate(modes)]
        ring = _modal_impact(n, rng, modes, sr,
                              noise_mix=0.01, noise_decay=350) * 0.50

        # Bright tap transient.
        tap = _fm_click(t, f_carrier=2800, f_mod=1400,
                         mod_index=1.5, rng=rng, decay=600, detune=100)
        tap *= _env_adsr(t, 0.0005, 0.005, 0.01, 0.005) * 0.20

        out = ring + tap
        out = _svf_filter(out, 150, 0.707, sr, mode='hp')
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _tibetan_bowl_gong(self, v: int = 0) -> np.ndarray:
        """Deep gong — massive, long decay (for Escape)."""
        sr, dur = self.sample_rate, 0.90
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 400)
        f0 = 100 + rng.randint(-3, 3)

        # Very deep fundamental with many modes.
        modes = _bell_modes(f0, n_modes=9, rng=rng)
        gong = _modal_impact(n, rng, modes, sr,
                              noise_mix=0.01, noise_decay=250) * 0.55

        # Impact thud.
        thud = _noise_excited_resonator(n, rng,
                                         center_freq=80,
                                         bandwidth=300, q=2.0, sr=sr,
                                         excitation_decay=400) * 0.25
        thud *= _env_adsr(t, 0.003, 0.02, 0.20, 0.10, delay=0.005)

        # Long sub drone.
        drone = np.sin(2 * np.pi * f0 * 0.5 * t) * np.exp(-t * 0.8) * 0.20

        out = gong + thud + drone
        out = _svf_filter(out, 35, 0.707, sr, mode='hp')
        out = _svf_filter(out, 6000, 0.707, sr, mode='lp')
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _tibetan_bowl_mallet_damp(self, v: int = 0) -> np.ndarray:
        """Mallet damp — quick thud, short decay (for Backspace)."""
        sr, dur = self.sample_rate, 0.12
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 500)
        f0 = 300 + v * 20 + rng.randint(-10, 10)

        # Short modal impact — quickly damped.
        modes = _bell_modes(f0, n_modes=3, rng=rng)
        tap = _modal_impact(n, rng, modes, sr,
                             noise_mix=0.03, noise_decay=1500) * 0.50
        tap *= np.exp(-t * 15.0)  # rapid damping

        # Mallet felt thud.
        thud = _noise_excited_resonator(n, rng,
                                         center_freq=200,
                                         bandwidth=800, q=1.5, sr=sr,
                                         excitation_decay=2000) * 0.20
        thud *= _env_adsr(t, 0.001, 0.008, 0.03, 0.02)

        out = tap + thud
        out = _svf_filter(out, 100, 0.707, sr, mode='hp')
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _tibetan_bowl_overtone_a(self, v: int = 0) -> np.ndarray:
        """Overtone A — singing bowl's upper harmonic (for quotes)."""
        sr, dur = self.sample_rate, 0.30
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 600)
        f0 = 580 + v * 40 + rng.randint(-15, 15)

        # Emphasise the 2nd and 3rd partials.
        modes = _bell_modes(f0, n_modes=5, rng=rng)
        modes = [(f, a * (0.3 if i == 0 else 1.0), d, p) for i, (f, a, d, p) in enumerate(modes)]
        ring = _modal_impact(n, rng, modes, sr,
                              noise_mix=0.01, noise_decay=350) * 0.45

        # Pure overtone sine with vibrato.
        vib = np.sin(2 * np.pi * f0 * 2.0 * t * (1 + 0.002 * np.sin(2 * np.pi * 5.0 * t)))
        vib *= np.exp(-t * 3.5) * 0.15

        out = ring + vib
        out = _svf_filter(out, 200, 0.707, sr, mode='hp')
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _tibetan_bowl_overtone_b(self, v: int = 0) -> np.ndarray:
        """Overtone B — another harmonic, slightly different character (for brackets)."""
        sr, dur = self.sample_rate, 0.28
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 700)
        f0 = 440 + v * 35 + rng.randint(-12, 12)

        modes = _bell_modes(f0, n_modes=5, rng=rng)
        ring = _modal_impact(n, rng, modes, sr,
                              noise_mix=0.01, noise_decay=300) * 0.45

        # Beating partials for warmth.
        b1 = np.sin(2 * np.pi * f0 * 3.003 * t) * np.exp(-t * 3.0) * 0.10
        b2 = np.sin(2 * np.pi * f0 * 2.997 * t) * np.exp(-t * 3.0) * 0.10

        out = ring + b1 + b2
        out = _svf_filter(out, 150, 0.707, sr, mode='hp')
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _tibetan_bowl_small_bell(self, v: int = 0) -> np.ndarray:
        """Small bell — bright, clear (for digits)."""
        sr, dur = self.sample_rate, 0.18
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 800)
        f0 = 1100 + v * 80 + rng.randint(-30, 30)

        modes = _bell_modes(f0, n_modes=4, rng=rng)
        bell = _modal_impact(n, rng, modes, sr,
                              noise_mix=0.02, noise_decay=500) * 0.55

        # Bright transient.
        transient = _fm_click(t, f_carrier=3000, f_mod=1500,
                               mod_index=1.2, rng=rng, decay=800, detune=80)
        transient *= _env_adsr(t, 0.0005, 0.005, 0.01, 0.005) * 0.15

        out = bell + transient
        out = _svf_filter(out, 400, 0.707, sr, mode='hp')
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    def _tibetan_bowl_rim_tap(self, v: int = 0) -> np.ndarray:
        """Rim tap — metallic, bright (for punctuation)."""
        sr, dur = self.sample_rate, 0.15
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        rng = np.random.RandomState(v + 900)
        f0 = 2200 + v * 100 + rng.randint(-80, 80)

        # Metal plate modes for the rim (higher, more metallic).
        modes = _metal_plate_modes(f0, n_modes=5, rng=rng)
        rim = _modal_impact(n, rng, modes, sr,
                             noise_mix=0.03, noise_decay=600) * 0.45

        # Sharp attack transient.
        crack_len = min(40, n)
        crack = rng.randn(crack_len) * np.exp(-np.linspace(0, 1500, crack_len)) * 0.15
        crack = np.pad(crack, (0, max(0, n - len(crack))))

        # Bowl body resonance underneath.
        body_modes = _bell_modes(f0 * 0.25, n_modes=3, rng=rng)
        body = _modal_impact(n, rng, body_modes, sr,
                              noise_mix=0.01, noise_decay=300) * 0.15

        out = rim + crack + body
        out = _svf_filter(out, 300, 0.707, sr, mode='hp')
        return _normalise((np.clip(out, -1, 1) * 32767).astype(np.int16))

    # ── public API ──────────────────────────────────────────────────────
    def _category_for(self, char: str) -> str:
        """Dispatch a character to the right sound category.

        For keyboard profiles this uses the standard 11-category mapping.
        For non-keyboard (thematic) profiles it uses the per-profile
        ``_CATEGORY_MAPS`` to remap characters to themed categories.
        """
        cmap = self._CATEGORY_MAPS.get(self.profile, {})
        if cmap:
            # Non-keyboard profile — use thematic mapping.
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
            # Letters fall through to the profile's default "key" equivalent.
            return "key"
        # Standard keyboard profiles.
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

    def get_sound(self, char: str) -> np.ndarray:
        """Pick a random variant of the sound matching the given character."""
        category = self._category_for(char)
        sounds = self.sounds.get(category) or self.sounds["key"]
        return random.choice(sounds)

    @staticmethod
    def save_wav(path: str, signal: np.ndarray, sr: int = 44100,
                 volume: float = 0.5, channels: int = 1) -> None:
        """Write an int16 signal to a WAV file (mono or stereo)."""
        scaled = np.clip(signal.astype(np.float64) * volume, -32768, 32767).astype(np.int16)
        with wave.open(path, "w") as w:
            w.setnchannels(channels)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(scaled.tobytes())

    def generate_audio_track(
        self,
        char_timestamps: List[Tuple[float, str]],
        filepath: str,
        volume: float = 0.5,
    ) -> None:
        """Mix a full stereo audio track aligned to ``char_timestamps``.

        v3 mix bus improvements:
          - Convolution reverb (synthetic IR) replaces simple delay-line
            reverb for much more realistic spatial depth.
          - Per-sound micro-convolution: each keystroke gets a tiny room
            imprint before hitting the mix bus, so even rapid typing
            sounds like it's in a real room.
          - Frequency-dependent panning: low frequencies are panned
            less aggressively than highs (bass is omnidirectional).
          - Mid-side stereo enhancement for a wider, more immersive image.
          - Peak limiter with envelope follower replaces simple tanh
            clipping — preserves transient punch while preventing
            digital overs.
          - Stereo room tone with subtle cross-delay for depth.
          - Per-channel spectral tilt for natural warmth.
        """
        if not char_timestamps:
            return
        sr = self.sample_rate
        total = max(ts for ts, _ in char_timestamps) + 0.5
        n = int(sr * total)

        # Generate convolution IR once (shared across all sounds).
        ir = _generate_ir(sr, duration=0.08, room_size=0.45, damping=0.65)

        # Stereo mix buffers (L, R) — float32 for memory efficiency.
        # v1.9: Changed from float64 to float32.  At 235M samples this saves
        # ~1.75 GB per channel (3.5 GB total) with no audible quality loss
        # since the final output is int16 anyway.
        # BUG FIX (v1.5.1): previously audio_r was np.int32, which caused
        # the right channel to be silently truncated to zero because the
        # float mix_r values (typically in [-0.5, 0.5]) were cast to int32
        # before accumulation. The result was a mono-on-left output.
        # Both channels now accumulate in float32 and are clipped to int16
        # range only at the final interleaving step.
        mix_mem_mb = n * 4 * 2 / (1024 * 1024)  # float32, 2 channels
        self.logger.info(
            "Audio mix buffers: %d samples (%.1f s), %.1f MB (float32)",
            n, total, mix_mem_mb,
        )
        audio_l = np.zeros(n, dtype=np.float32)
        audio_r = np.zeros(n, dtype=np.float32)

        for ts, ch in char_timestamps:
            snd = self.get_sound(ch)
            s = int(ts * sr)
            e = min(s + len(snd), n)
            if s >= n:
                continue
            chunk = snd[:e - s].astype(np.float32)

            # Pan based on key position (QWERTY model).
            pan = _KEY_POSITIONS.get(ch.lower(), 0.0)
            pan = max(-1.0, min(1.0, pan))

            # Frequency-dependent panning: reduce panning at low frequencies
            # (bass is omnidirectional in real rooms).
            # Apply mild convolution reverb per sound for room imprint.
            chunk_rev = _fft_convolve(chunk, ir * 0.35)  # wet signal
            # Reverb is slightly less panned (more centered/diffuse).
            pan_rev = pan * 0.5  # reverb is more omnidirectional
            gain_l_rev = np.cos((pan_rev + 1) * np.pi / 4)
            gain_r_rev = np.sin((pan_rev + 1) * np.pi / 4)

            # Dry signal: equal-power pan.
            gain_l = np.cos((pan + 1) * np.pi / 4)
            gain_r = np.sin((pan + 1) * np.pi / 4)

            chunk_scaled = chunk * volume
            chunk_rev_scaled = chunk_rev * volume * 0.3  # reverb level

            sl = slice(s, e)

            # Mix dry (fully panned) + wet (less panned, lower level).
            mix_l = chunk_scaled * gain_l + chunk_rev_scaled * gain_l_rev
            mix_r = chunk_scaled * gain_r + chunk_rev_scaled * gain_r_rev

            # Accumulate into float64 buffers (no clipping yet — let the
            # peak limiter handle overshoots transparently at the end).
            audio_l[sl] += mix_l
            audio_r[sl] += mix_r

        # Apply transparent peak limiter to float64 buffers BEFORE int16 clip.
        audio_l = _peak_limiter(audio_l, sr, ceiling_db=-1.5, release_ms=40.0)
        audio_r = _peak_limiter(audio_r, sr, ceiling_db=-1.5, release_ms=40.0)

        # Clip both channels to int16 range and interleave L/R for stereo.
        stereo = np.empty(n * 2, dtype=np.int16)
        stereo[0::2] = np.clip(audio_l, -32768, 32767).astype(np.int16)
        stereo[1::2] = np.clip(audio_r, -32768, 32767).astype(np.int16)

        # Mid-side stereo width enhancement for spaciousness.
        stereo = _mid_side_enhance(stereo, width=1.25)

        # Add subtle stereo room tone with cross-delay for depth.
        # v1.9: generate and mix room tone in chunks to avoid
        # allocating 3+ full-length float64 arrays simultaneously.
        ROOM_CHUNK = 4_000_000  # ~90s per chunk
        room_l_full = np.zeros(n, dtype=np.float32)
        room_r_full = np.zeros(n, dtype=np.float32)
        cross_delay = int(0.004 * sr)  # 4ms cross-delay
        for cs in range(0, n, ROOM_CHUNK):
            ce = min(cs + ROOM_CHUNK, n)
            cn = ce - cs
            rl = _pink_noise(cn, sr, seed=42 + cs).astype(np.float32)
            rr = _pink_noise(cn, sr, seed=12345 + cs).astype(np.float32)
            # Cross-delay within chunk (simplified — skip boundary for first chunk)
            if cs > 0 and cross_delay < cn:
                rr[cross_delay:] += rr[:-cross_delay] * 0.5
            room_l_full[cs:ce] += rl * 0.35
            room_r_full[cs:ce] += rr * 0.65
        # Mix room tone at very low level (directly into stereo int16).
        room_contrib = np.empty(n * 2, dtype=np.int16)
        room_contrib[0::2] = np.clip(room_l_full * volume * 0.12 * 32767, -32768, 32767).astype(np.int16)
        room_contrib[1::2] = np.clip(room_r_full * volume * 0.12 * 32767, -32768, 32767).astype(np.int16)
        del room_l_full, room_r_full  # free ~3.6 GB (was float64)
        stereo = np.clip(stereo.astype(np.int32) + room_contrib.astype(np.int32),
                        -32768, 32767).astype(np.int16)

        self.save_wav(filepath, stereo, sr, 1.0, channels=2)