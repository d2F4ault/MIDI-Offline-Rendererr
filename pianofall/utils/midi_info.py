"""
MIDI metadata and duration probing with mido and binary SMF fallback.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path
from typing import Optional


def get_midi_duration(path: Path) -> Optional[float]:
    """
    Return MIDI duration in seconds.
    Tries mido first; if unavailable, uses a built-in SMF tempo parser.
    """
    if not path.is_file() or path.stat().st_size < 14:
        return None

    # Try mido first
    try:
        import mido

        mid = mido.MidiFile(str(path))
        length = float(mid.length)
        if not math.isnan(length) and not math.isinf(length) and length > 0.05:
            return length
    except ImportError:
        pass
    except Exception:
        pass

    # Built-in pure-Python SMF parser fallback
    return _parse_smf_duration(path)


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

        format_type, num_tracks, division = struct.unpack(">HHH", data[8:14])
        # division: if positive, ticks per quarter note; if negative, SMPTE
        if division & 0x8000:
            # SMPTE division (rare in standard piano midis)
            return None
        ticks_per_beat = division

        idx = 8 + header_len
        track_durations = []

        for _ in range(num_tracks):
            if idx + 8 > len(data):
                break
            chunk_type = data[idx : idx + 4]
            chunk_len = struct.unpack(">I", data[idx + 4 : idx + 8])[0]
            idx += 8

            if chunk_type != b"MTrk":
                idx += chunk_len
                continue

            track_end = min(idx + chunk_len, len(data))
            t_idx = idx
            idx = track_end

            current_time_s = 0.0
            tempo_us_per_beat = 500000  # Default 120 BPM = 500,000 us/beat
            running_status = 0

            while t_idx < track_end:
                # Read delta time (variable-length quantity)
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

                status = data[t_idx]
                if status >= 0x80:
                    t_idx += 1
                    running_status = status
                else:
                    status = running_status

                if status == 0xFF:  # Meta Event
                    if t_idx >= track_end:
                        break
                    meta_type = data[t_idx]
                    t_idx += 1
                    # Meta length
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
