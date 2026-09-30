# PianoFall Outputs Archive

This directory stores finished, silent 1920x1200 MP4 falling-notes piano visualizations rendered by the pipeline.

## Storage Architecture (GitHub Releases)

In automated GitHub Actions runs, rendered videos are published directly to **GitHub Releases** as downloadable release assets:
- **Maximum file size limit**: Up to **2 GB per video** (surpassing GitHub's standard 100 MB git commit ceiling).
- **Lightweight Repository**: Git repository clones remain fast and lightweight (<10 MB) without bloating the `.git` database with binary video blobs.
- **Direct Downloads**: Videos are immediately accessible, streamable, and downloadable directly from the repository's **Releases** tab.

For local runs (`python -m pianofall render-batch`), videos are stored locally under:

```text
outputs/
  └── YYYY-MM-DD/
        └── <original-midi-stem>.mp4
```

## Video Specifications

- **Resolution**: 1920 × 1200
- **Framerate**: 60 FPS
- **Video Codec**: H.264 / AVC (`libx264`, High Profile, CRF 16, `yuv420p`)
- **Visual Quality**: Studio-grade visually transparent (CRF 16, max bitrate 35 Mbps)
- **Audio**: Silent (no audio track embedded)
- **Container**: MP4 (`+faststart` web-optimized header)
