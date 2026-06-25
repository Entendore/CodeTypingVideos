```markdown
# Simple Code Typing Video Generator

PySide6 GUI that scans folders for code files and renders typing-animation MP4 videos with procedural audio via FFmpeg.

## Requirements

- Python 3.9+
- PySide6 — `pip install PySide6`
- NumPy — `pip install numpy`
- FFmpeg (on PATH)

## Installation

```bash
pip install PySide6 numpy
```

## Usage

```bash
python simple_code_typing.py
```

1. Add code files via *Scan input/*, *Choose Folder...*, or *Add files...*
2. Check the files you want to export
3. **Preview** tab — view live render, scrub frames, or click *Animate* to play
4. **Settings** tab — configure theme, resolution, WPM, audio, keyboard overlay
5. Click *Export Checked* to render MP4s into `output/`

## Features

- Syntax highlighting for Python, JS, TS, Go, Rust, HTML, CSS, Java, C/C++, Ruby, Bash
- 9 color themes (Dracula, One Dark, GitHub Dark, Monokai, Solarized Dark, VS Code Dark+, Nord, Tokyo Night, Gruvbox Dark)
- 4 resolutions: 1920x1080, 1280x720, 3840x2160, 1080x1920 (vertical)
- Procedural audio presets: Mechanical, Typewriter, Cash Register
- Keyboard overlay with 8 layouts: QWERTY, AZERTY, QWERTZ, Dvorak, Colemak, JIS, Pinyin, Turkish Q
- Batch export with progress tracking