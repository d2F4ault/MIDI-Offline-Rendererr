"""
Unit tests for MIDI duration parsing.
"""

import tempfile
import unittest
from pathlib import Path
from pianofall.utils.midi_info import get_midi_duration


class TestMidiInfo(unittest.TestCase):
    def test_pool_midi_duration(self):
        root = Path(__file__).resolve().parent.parent
        pool_dir = root / "midis_pool"
        midis = list(pool_dir.glob("*.mid"))
        if not midis:
            pool_dir = root / "midis"
            midis = list(pool_dir.glob("*.mid"))

        self.assertTrue(len(midis) > 0, "At least one MIDI file must exist in pool")
        sample = midis[0]

        dur = get_midi_duration(sample)
        self.assertIsNotNone(dur)
        self.assertGreater(dur, 0.5)

    def test_invalid_midi_duration(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            bad_file = Path(tmp_dir) / "corrupt.mid"
            bad_file.write_bytes(b"NOT_A_MIDI_FILE_DATA_CORRUPT")

            dur = get_midi_duration(bad_file)
            self.assertIsNone(dur)


if __name__ == "__main__":
    unittest.main()
