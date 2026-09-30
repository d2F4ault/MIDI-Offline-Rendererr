# PianoFall 🎹

[![CI](https://github.com/d2f4ult/pianofall/actions/workflows/ci.yml/badge.svg)](https://github.com/d2f4ult/pianofall/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

> **PianoFall** is a high-performance, automated offline renderer that transforms MIDI files into silent, high-definition (1920×1200 @ 60 FPS) falling-notes piano visualization videos.

Designed from the ground up for unattended execution, PianoFall operates on pure CPU infrastructure—including free GitHub Actions standard Linux runners—without requiring external GPUs, proprietary cloud services, or paid compute tiers.

---

## ✨ Features

- **Automated Scheduling**: Runs autonomously twice per day (`02:00 UTC` & `14:00 UTC`) or on-demand via `workflow_dispatch`.
- **Pure-CPU Rendering**: Highly optimized decoupled pipeline leveraging Chromium SwiftShader, Xvfb virtual displays, and multi-core `libx264` encoding.
- **High-Definition Output**: Generates crystal-clear **1920×1200** resolution videos at genuine **60 FPS** with studio-grade visual transparency (**CRF 16**, up to 35 Mbps).
- **Exact MIDI Timeline Synchronization**: Automatic duration analysis and frame retiming (`setpts`) guarantees 100% accurate 1× musical tempo without drift or jitter.
- **Silent Output**: Audio-free (`-an`) video stream ready for video editing, accompaniment syncing, or sound-font mixing.
- **GitHub Releases Storage (Up to 2 GB per file)**: Rendered videos are automatically published directly to repository **Releases** as downloadable assets. Clones remain lightweight (<10 MB) with zero repository bloat.
- **Resilient Queue & Ledgers**: Tracks completed pieces in `data/processed.txt`, quarantines edge-case failures in `data/failed_pieces.txt`, and automatically advances past errors.
- **Schedule Keepalive**: Built-in heartbeat mechanism ensures GitHub never auto-disables scheduled runs due to repository inactivity.

---

## 📁 Repository Structure

```text
pianofall/
├── .github/
│   └── workflows/
│       ├── render.yml          # Automated 2x/day scheduled rendering workflow
│       ├── keepalive.yml       # Inactivity watchdog preventing schedule suspension
│       └── ci.yml              # Test matrix and CLI interface verification
├── config/
│   └── default.yaml            # Configurable viewport, encoding, and timing defaults
├── data/
│   ├── processed.txt           # Persistent ledger of completed pieces
│   └── failed_pieces.txt       # Quarantine ledger with error diagnostics
├── midis/                      # Queue directory for input MIDI files
│   └── Handel_HWV425.mid       # Sample starter piece (Air in E major)
├── outputs/                    # Output archive for finished visualizations
│   └── README.md
├── pianofall/                  # Core package
│   ├── cli.py                  # CLI entry point (render-batch, queue, inspect)
│   ├── config.py               # Configuration management and env overrides
│   ├── core/
│   │   ├── backend.py          # Canvas visualizer DOM automation and event sync
│   │   ├── browser.py          # Xvfb and Chromium lifecycle manager
│   │   ├── recorder.py         # FFmpeg screen capture subprocess controller
│   │   └── postprocess.py      # Precise duration probing and libx264 mastering pass
│   ├── queue/
│   │   ├── manager.py          # Candidate selection and duration filtering
│   │   ├── ledger.py           # State tracking and ledger serialization
│   │   └── downloader.py       # Public domain classical piece downloader
│   └── utils/
│       ├── logging.py          # Clean structured console logging
│       ├── system.py           # CPU, memory, and binary dependency diagnostics
│       └── midi_info.py        # Robust MIDI duration probe with SMF fallback
├── tests/                      # Comprehensive unit test suite
├── ARCHITECTURE.md             # Technical architecture and design choices
├── requirements.txt            # Runtime dependencies
└── pyproject.toml              # Standard Python packaging specification
```

---

## 🚀 Quickstart & Local Usage

### 1. Prerequisites

Ensure Python 3.10+, [FFmpeg](https://ffmpeg.org/), and (on Linux) [Xvfb](https://en.wikipedia.org/wiki/Xvfb) are installed on your machine:

```bash
# Ubuntu / Debian
sudo apt-get update
sudo apt-get install -y ffmpeg xvfb

# macOS (Homebrew)
brew install ffmpeg

# Windows (Chocolatey / Scoop)
choco install ffmpeg
```

### 2. Installation

Clone this repository and install dependencies:

```bash
git clone https://github.com/d2f4ult/pianofall.git
cd pianofall
pip install -r requirements.txt
python -m playwright install --with-deps chromium
```

### 3. CLI Commands

```bash
# Inspect system capabilities, CPU cores, and FFmpeg binary
python -m pianofall inspect-system

# Inspect the queue and completion statistics
python -m pianofall queue

# Test candidate selection without rendering (dry run)
python -m pianofall render-batch --dry-run

# Render the next piece in the queue (or trial 15 seconds)
python -m pianofall render-batch --test-seconds 15

# Fetch public domain classical piano pieces if queue is empty
python -m pianofall fetch-midi
```

---

## ⚙️ Configuration

PianoFall can be customized via YAML configuration or environment variables:

| Setting | Environment Variable | Default | Description |
| :--- | :--- | :--- | :--- |
| **Viewport Width** | `RENDER_VIEWPORT_W` | `1920` | Canvas width in pixels |
| **Viewport Height** | `RENDER_VIEWPORT_H` | `1200` | Canvas height in pixels |
| **Output Framerate** | `RENDER_OUTPUT_FPS` | `60` | Target mastered video framerate |
| **Encoding Quality** | `RENDER_CRF` | `16` | libx264 Constant Rate Factor (14–20, studio quality) |
| **Encoding Preset** | `RENDER_PRESET` | `fast` | libx264 preset (`fast`, `medium`, `slow`) |
| **Max Batch Size** | `MAX_VIDEOS_PER_RUN` | `1` | Videos processed per scheduled run |
| **Max Duration** | `MAX_PIECE_DURATION` | `360.0` | Maximum piece duration cap (seconds) |

---

## 🛠️ GitHub Repository Setup Guide

To deploy PianoFall on GitHub Actions:

### Step 1: Create a New GitHub Repository
1. Navigate to [github.com/new](https://github.com/new).
2. Choose a repository name (e.g. `pianofall` or `keys-visualizer`).
3. Set the repository visibility to **Public** (public repositories have free unlimited GitHub Actions standard runners).

### Step 2: Push Code to GitHub
```bash
git init
git add .
git commit -m "feat: initial commit of PianoFall rendering pipeline"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo-name>.git
git push -u origin main
```

### Step 3: Configure Workflow Permissions
To allow the automated bot to commit finished videos and ledgers back to the repository:
1. In your GitHub repository, open **Settings** → **Actions** → **General**.
2. Scroll down to **Workflow permissions**.
3. Select **Read and write permissions**.
4. Check **Allow GitHub Actions to create and approve pull requests**.
5. Click **Save**.

### Step 4: Add Your MIDI Files
- Simply drop `.mid` or `.midi` files into the `midis/` directory and commit them.
- A sample classical piece (`Handel_HWV425.mid`) is already provided, so the pipeline is ready to run immediately.

### Step 5: Manual Trigger
1. Go to the **Actions** tab in your repository.
2. Select **PianoFall Automated Render Pipeline** from the left sidebar.
3. Click **Run workflow**. You can optionally specify a test duration (e.g., `15` seconds) for a fast trial.
4. When finished, your video will be automatically committed to `outputs/YYYY-MM-DD/`.

---

## 📜 Technical Architecture

For an in-depth explanation of the two-stage rendering strategy, `setpts` frame retiming, and CPU budget allocation, see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
