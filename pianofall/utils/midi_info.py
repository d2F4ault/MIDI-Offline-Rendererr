"""
MIDI metadata and duration probing with mido, binary SMF parser, and persistent caching.
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import Optional

_DURATION_CACHE: dict[str, float] = {}
_CACHE_LOADED: bool = False
_CACHE_DIRTY: bool = False


def _get_cache_path() -> Path:
    repo_root = Path(__file__).resolve().parent.parent.parent
    cache_path = repo_root / "data" / "duration_cache.json"
    return cache_path


def _load_cache_if_needed() -> None:
    global _CACHE_LOADED, _DURATION_CACHE
    if _CACHE_LOADED:
        return
    _CACHE_LOADED = True
    cache_path = _get_cache_path()
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _DURATION_CACHE.update(data)
        except Exception:
            pass


def save_duration_cache() -> None:
    global _CACHE_DIRTY
    if not _CACHE_DIRTY:
        return
    cache_path = _get_cache_path()
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(_DURATION_CACHE), encoding="utf-8")
        _CACHE_DIRTY = False
    except Exception:
        pass


def get_midi_duration(path: Path) -> Optional[float]:
    """
    Return MIDI duration in seconds.
    Tries persistent cache first, then binary SMF parser, with mido fallback.
    """
    global _CACHE_DIRTY
    if not path.is_file() or path.stat().st_size < 14:
        return None

    _load_cache_if_needed()

    cache_key = None
    try:
        stat = path.stat()
        cache_key = f"{path.name}:{stat.st_size}"
        if cache_key in _DURATION_CACHE:
            return _DURATION_CACHE[cache_key]
    except Exception:
        pass

    # Fast binary SMF parser (50x faster than full mido event decoding)
    parsed = _parse_smf_duration(path)
    if parsed is not None and not math.isnan(parsed) and not math.isinf(parsed) and parsed > 0.05:
        if cache_key:
            _DURATION_CACHE[cache_key] = round(parsed, 2)
            _CACHE_DIRTY = True
        return parsed

    # Mido fallback for unusual or esoteric SMF formats
    try:
        import mido

        mid = mido.MidiFile(str(path))
        length = float(mid.length)
        if not math.isnan(length) and not math.isinf(length) and length > 0.05:
            if cache_key:
                _DURATION_CACHE[cache_key] = round(length, 2)
                _CACHE_DIRTY = True
            return length
    except Exception:
        pass

    return parsed


def _parse_smf_duration(path: Path) -> Optional[float]:
    """
    Directly parse standard MIDI file (SMF) chunks to compute total duration.
    Handles variable-length quantities and Set Tempo meta events (0xFF 0x51).
    """
    try:
        data = path.read_bytes()
        if len(data) < 14 or data[:4] != b"MThd":
            return None

        header_len = struct.unpack(">I", data[4:8])[0]
        if header_len < 6:
            return None

        fmt, num_tracks, division = struct.unpack(">HHH", data[8:14])
        if division & 0x8000:
            # SMPTE division format (rare in classical piano midis)
            return None

        ticks_per_beat = division
        if ticks_per_beat == 0:
            return None

        track_durations = []
        idx = 8 + header_len

        for _ in range(num_tracks):
            if idx + 8 > len(data):
                break
            chunk_type = data[idx : idx + 4]
            chunk_len = struct.unpack(">I", data[idx + 4 : idx + 8])[0]
            track_start = idx + 8
            track_end = min(track_start + chunk_len, len(data))
            idx = track_end

            if chunk_type != b"MTrk":
                continue

            t_idx = track_start
            current_time_s = 0.0
            tempo_us_per_beat = 500_000  # Default 120 BPM (500,000 us/beat)
            running_status = 0

            while t_idx < track_end:
                # Read delta time variable-length quantity
                delta_ticks = 0
                while t_idx < track_end:
                    b = data[t_idx]
                    t_idx += 1
                    delta_ticks = (delta_ticks << 7) | (b & 0x7F)
                    if not (b & 0x80):
                        break

                current_time_s += (delta_ticks / ticks_per_beat) * (tempo_us_per_beat / 1_000_000.0)

                if t_idx >= track_end:
                    break

                b = data[t_idx]
                if b & 0x80:
                    status = b
                    t_idx += 1
                    if status < 0xF0:
                        running_status = status
                else:
                    status = running_status

                if status == 0xFF:  # Meta Event
                    if t_idx >= track_end:
                        break
                    meta_type = data[t_idx]
                    t_idx += 1
                    meta_len = 0
                    while t_idx < track_end:
                        b = data[t_idx]
                        t_idx += 1
                        meta_len = (meta_len << 7) | (b & 0x7F)
                        if not (b & 0x80):
                            break

                    if meta_type == 0x51 and meta_len == 3 and t_idx + 3 <= track_end:
                        tempo_us_per_beat = (
                            (data[t_idx] << 16) | (data[t_idx + 1] << 8) | data[t_idx + 2]
                        )
                    t_idx += meta_len
                elif status in (0xF0, 0xF7):  # SysEx
                    sysex_len = 0
                    while t_idx < track_end:
                        b = data[t_idx]
                        t_idx += 1
                        sysex_len = (sysex_len << 7) | (b & 0x7F)
                        if not (b & 0x80):
                            break
                    t_idx += sysex_len
                elif (status & 0xF0) in (0xC0, 0xD0):
                    t_idx += 1
                elif (status & 0xF0) in (0x80, 0x90, 0xA0, 0xB0, 0xE0):
                    t_idx += 2

            track_durations.append(current_time_s)

        if not track_durations:
            return None

        total_dur = max(track_durations)
        return total_dur if total_dur > 0.05 else None

    except Exception:
        return None
