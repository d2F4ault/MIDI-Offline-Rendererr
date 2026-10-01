# PianoFall Outputs Archive

This directory stores finished, silent 1920x1200 @ 60 FPS falling-notes piano visualizations rendered by the offline pipeline.

## Directory Layout

Each execution batch creates a dedicated run folder with matching MP4 videos and source MIDIs organized side-by-side:

```text
outputs/
  └── run_YYYY-MM-DD_HHMMSS/
        ├── mp4/
        │     ├── Piece_Name_1.mp4
        │     └── Piece_Name_2.mp4
        └── midis/
              ├── Piece_Name_1.mid
              └── Piece_Name_2.mid
```

- **Matching Filenames**: Every piece produces an identical basename in both `mp4/` and `midis/`.
- **Zero-Duplicate Protection**: When a piece finishes rendering, its source MIDI is physically moved from `midis_pool/` to `outputs/<run>/midis/` and recorded in `data/processed_midis.txt`.
- **Automatic Storage Management**: When starting a new batch, previous run assets can be automatically purged to conserve repository storage, with full audit records preserved in `data/deletion_history.csv` and `data/cleanup_log.md`.

## Video Specifications

- **Resolution**: 1920 × 1200 (full-bleed, zero browser UI)
- **Keyboard View**: Full 88-key piano keyboard (A0 – C8)
- **Framerate**: Genuine 60 FPS (deterministic virtual clock stepping)
- **Video Codec**: H.264 / AVC (`libx264`, High Profile, CRF 14, `yuv420p`, preset `faster`)
- **Visual Quality**: Studio-grade visually transparent (CRF 14, max bitrate 50 Mbps)
- **Audio**: Silent (`-an`, no audio track embedded)
- **Container**: MP4 (`+faststart` web-optimized header)
