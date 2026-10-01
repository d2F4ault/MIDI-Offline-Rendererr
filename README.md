# PianoFall 🎹

[![CI](https://github.com/d2f4ult/MIDI-Offline-Rendererr/actions/workflows/ci.yml/badge.svg)](https://github.com/d2f4ult/MIDI-Offline-Rendererr/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

> **PianoFall** is a high-performance offline rendering pipeline that transforms classical piano MIDI files into pristine, studio-quality (1920×1200 @ 60 FPS) falling-notes visualization videos.

Designed for on-demand execution on standard CPU runners, PianoFall operates headlessly without requiring external GPUs, proprietary cloud services, or paid compute tiers.

---

## ✨ Production Architecture & Features

- **100% On-Demand & Manual Execution**: No automated background schedules or standing tasks. Trigger batches whenever you choose with exact target counts (default: **30 videos**).
- **Exact Batch Quota Enforcement**: Processes precisely the requested number of videos—neither fewer nor more.
- **5-Hour Runner Safeguard & Graceful Continuation**: Standard GitHub Actions runners enforce a 6-hour execution ceiling. PianoFall monitors runtime budgets; any piece entering the 5th hour is declared the final piece of the workflow. The workflow cleanly finalizes video encoding, commits state to Git, and automatically dispatches a continuation run for the remaining quota before completely shutting down upon reaching 30 pieces.
- **Automated Storage Management**: To prevent Git repository bloat, starting a new batch automatically purges previous output videos and MIDIs while logging full audit details in `data/deletion_history.csv` and `data/cleanup_log.md`.
- **Side-by-Side MP4 and MIDI Organization**: Outputs are structured inside `outputs/run_YYYY-MM-DD_HHMMSS/` with matching `mp4/` and `midis/` folders containing identical filenames for immediate pair-matching.
- **Zero-Duplicate Protection**: When a piece finishes rendering, its source file is physically moved from `midis_pool/` to the run's `outputs/.../midis/` folder and recorded in the persistent ledger `data/processed_midis.txt`.
- **Full 88-Key Piano View (A0 – C8)**: Visualizer is programmatically zoomed to display all 88 keys edge-to-edge.
- **Zero Browser Chrome**: Runs in headless Chromium using in-page canvas compositing (`canvas_composite`), capturing strictly the rendering surface with zero tab bars, URL bars, or OS borders.
- **Deterministic 60 FPS Virtual Clock**: Virtualizes `AudioContext.currentTime` and `requestAnimationFrame`. Frames are stepped deterministically at 1/60s intervals and piped directly to FFmpeg stdin via `libx264` (CRF 14, High Profile, faststart).

---

## 📁 Repository Structure

```text
MIDI-Offline-Rendererr/
├── .github/
│   └── workflows/
│       ├── render.yml          # Manual dispatch offline rendering pipeline
│       └── ci.yml              # Test matrix and CLI verification
├── config/
│   └── default.yaml            # Configurable viewport, encoding, and timing defaults
├── data/
│   ├── processed_midis.txt     # Clean list of all converted pieces (anti-repeat check)
│   ├── render_history.csv      # Full metrics ledger (duration, render time, file size)
│   ├── RENDER_LOG.md           # Markdown table of completed renders
│   ├── deletion_history.csv    # Audit log of purged assets and reclaimed storage
│   ├── cleanup_log.md          # Human-readable maintenance and storage report
│   ├── duration_cache.json     # Fast duration lookup cache for all pool pieces
│   ├── processed.txt           # Tab-delimited persistent state log
│   └── failed_pieces.txt       # Quarantine ledger with error diagnostics
├── midis_pool/                 # Curated pool of 1,100+ classical ByteDance GiantMIDI pieces
├── outputs/                    # Output archive for finished visualizations
│   └── run_YYYY-MM-DD_HHMMSS/
│       ├── mp4/                # Rendered 1920x1200 @ 60 FPS MP4 videos
│       │     └── <piece_name>.mp4
│       └── midis/              # Matching source MIDI files
│             └── <piece_name>.mid
├── pianofall/                  # Core package
│   ├── cli.py                  # CLI entry point (render-batch, queue, inspect-system)
│   ├── config.py               # Configuration management and env overrides
│   ├── core/
│   │   ├── backend.py          # Canvas visualizer DOM automation and virtual clock
│   │   ├── browser.py          # Headless Chromium lifecycle manager
│   │   ├── recorder.py         # Direct FFmpeg image2pipe stdin streaming
│   │   └── runner.py           # Single-piece & batch pipeline orchestration
│   ├── queue/
│   │   ├── fetcher.py          # GiantMIDI dataset extractor & Google Drive handler
│   │   ├── manager.py          # Candidate selection, auto-queue, and duration filtering
│   │   └── ledger.py           # Multi-file ledger state tracking and output cleanup
│   └── utils/
│       ├── logging.py          # Clean structured console logging
│       ├── midi_info.py        # High-speed binary SMF duration parser with caching
│       └── system.py           # System hardware and dependency inspection
├── tests/                      # Unit test suite (11 passing tests)
├── ARCHITECTURE.md             # In-depth architectural specification
├── requirements.txt            # Runtime dependencies
└── pyproject.toml              # Standard Python packaging specification
```

---

## 🚀 Running via GitHub Actions

1. Navigate to **Actions** → **PianoFall Offline Render Pipeline**.
2. Click **Run workflow**.
3. Select parameters:
   - **Target video count**: `30` (or desired quota)
   - **Auto-delete previous outputs**: `true` (recommended for storage preservation)
   - **Max hours per job**: `5.0`
   - **Test seconds**: Leave blank for full pieces, or set `15` for a quick verification test.
4. Click **Run workflow**.

The runner will:
- Clean previous outputs if enabled and log the event.
- Select the next 30 shortest eligible pieces from `midis_pool/`.
- Render pristine 60 FPS MP4s and pair each with its source MIDI in `outputs/`.
- Commit and push outputs and audit ledgers.
- If the 5th hour is reached before 30 pieces complete, dispatch continuation for the remainder and cleanly shut down once finished.

---

## 💻 Local CLI Usage

### System Inspection
```bash
python -m pianofall inspect-system
```

### Queue Status
```bash
python -m pianofall queue
```

### Dry Run (Inspect Next 30 Selected Pieces)
```bash
python -m pianofall render-batch --dry-run --target-videos 30
```

### Live Batch Render
```bash
python -m pianofall render-batch --target-videos 30
```

### Run Unit Tests
```bash
python -m unittest discover tests -v
```

---

## 📄 License

Distributed under the MIT License. See `LICENSE` for details.
