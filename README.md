# Code Typing Video Generator

A desktop application that generates MP4, WebM, or GIF videos of source code being typed. It features real-time syntax highlighting, synthesized typing sound effects, humanized typing cadence with simulated typo correction, and an on-screen keyboard overlay.

## Prerequisites

*   Python 3.8+
*   FFmpeg (Must be installed and accessible in the system `PATH`. The application uses FFmpeg via subprocess for all video and audio muxing. Export will fail without it.)

## Installation

1.  Clone the repository or download `app.py`.
2.  Install the required Python packages:

```bash
pip install PySide6 numpy opencv-python
```

3.  Run the application:

```bash
python app.py
```

## Features and Configuration

### Source Code Input
*   **File Dropdown**: Reads files from the `input/` directory. Supports extensions including `.py`, `.js`, `.ts`, `.java`, `.c`, `.cpp`, `.go`, `.rs`, `.html`, `.css`, `.json`, `.yaml`, `.md`, `.txt`, and many others.
*   **Drag and Drop**: Files can be dragged directly into the text editor pane.
*   **Manual Entry**: Code can be pasted or typed directly into the editor.

### Syntax Highlighting
The application uses regex-based tokenizers to highlight code. Three tokenizers are included:
1.  **Python**: Handles keywords, built-ins, decorators, triple-quoted strings, and comments.
2.  **JavaScript**: Handles ES6+ keywords, template literals, and standard web/browser built-ins.
3.  **C/C++/Java (Generic)**: Handles standard C-family keywords, types, and preprocessor directives.

### Themes
Seven predefined color themes are available, defining syntax colors, UI chrome colors, and background gradients:
*   Dracula
*   One Dark
*   Monokai
*   Nord
*   GitHub Dark
*   Solarized Dark
*   Catppuccin Mocha

### Typing Animation
*   **Humanization**: Introduces random variance to typing speed. Specific delays are applied to punctuation, brackets, newlines, and spaces to mimic real typing patterns.
*   **Typo Simulation**: Configurable typo rate. When triggered, the animator inserts a random character, pauses briefly, inserts a backspace (`\b`) character, and then types the correct character.
*   **Cursor**: Renders a blinking block cursor. The blink period is approximately 0.53 seconds.

### Audio Synthesis
Typing sounds are generated procedurally using NumPy (sine waves, noise, and exponential decay). No external audio files are required. Three sound profiles are available:
*   **Mechanical**: High-frequency click, low-frequency thock, and resonant thud.
*   **Typewriter**: Sharp strike, metallic ring, and carriage return sounds.
*   **Soft Membrane**: Muted thud with low-pass filtered noise.

Audio is generated as a single WAV track synced to the typing timeline and muxed with the video during the MP4 export process. (Audio is excluded from GIF exports).

### Visual Overlays
*   **Window Chrome**: Draws a macOS-style title bar with traffic light buttons (close, minimize, maximize) and a customizable title.
*   **Line Numbers**: Toggleable line numbers with a distinct color for the active line.
*   **Active Line Highlight**: Applies a background color to the line where the cursor is currently located.
*   **On-screen Keyboard**: Renders a QWERTY keyboard layout at the bottom of the frame. Keys light up momentarily when pressed during the animation.
*   **Custom Background**: Allows setting an image file as the background, scaled to fit the frame.

### Resolution Presets
*   YouTube 1080p: 1920x1080
*   YouTube 4K: 3840x2160
*   TikTok / Reels: 1080x1920 (9:16 aspect ratio)
*   Instagram Square: 1080x1080
*   Twitter / X: 1280x720

### Export Formats
The rendering pipeline uses `QPainter` to draw frames, converts them to RGB byte arrays, and pipes them to FFmpeg.

1.  **MP4 (H.264)**:
    *   Video: `libx264`, profile `high`, level `4.2`, CRF (configurable), preset (configurable), `movflags +faststart`.
    *   Audio: `aac`, 192k bitrate (if sound is enabled).
2.  **WebM (VP9)**:
    *   Video: `libvpx-vp9`, CRF 30, `yuv420p` pixel format.
    *   Audio: Not muxed in the current WebM pipeline.
3.  **GIF**:
    *   Video: Uses FFmpeg's `palettegen` and `paletteuse` filters for high-quality color quantization. Frame rate is capped at 15 fps.
    *   Audio: Not applicable.

## How It Works

1.  **Timeline Generation**: The `TypingAnimator` reads the source code and generates a timeline of events (timestamp, display index, character). It calculates delays based on WPM and humanization rules.
2.  **Audio Generation**: The `TypingSoundGenerator` iterates through the timeline, mixes the corresponding synthesized sounds (key, space, enter) at the precise timestamps, and writes a single WAV file.
3.  **Frame Rendering**: The `VideoExporter` iterates through the timeline based on the target FPS. For each frame, it calculates how many characters should be visible, calls `CodeRenderer.render_frame()` to draw the state to a `QImage`, converts the image to a raw RGB byte array, and writes it to the FFmpeg stdin pipe.
4.  **Muxing**: FFmpeg receives the raw video pipe and (for MP4) the saved WAV file, combining them into the final output container in the `output/` directory.