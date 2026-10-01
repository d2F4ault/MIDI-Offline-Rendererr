"""
Tests for GiantMIDI dataset fetcher and ledger multi-file tracking.
"""

import tempfile
import unittest
from pathlib import Path
from pianofall.queue.ledger import append_processed_entry, load_processed_set
from pianofall.queue.fetcher import _clean_stem


class TestGiantMidiAndLedger(unittest.TestCase):
    def test_clean_stem(self):
        stem = _clean_stem("Chopin, Frédéric, Études, Op.10, g0hoN6_HDVU.mid")
        self.assertIn("Chopin", stem)
        self.assertIn("Op.10", stem)

    def test_multi_ledger_tracking(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            processed_txt = data_dir / "processed.txt"

            append_processed_entry(
                log_path=processed_txt,
                midi_filename="TestPiece",
                duration_s=120.5,
                frames=7230,
                file_size_bytes=10485760,
                rel_output_path="outputs/2026-09-30/run_01/TestPiece.mp4",
                render_time_s=45.2,
            )

            # Check processed.txt
            self.assertTrue(processed_txt.exists())
            processed_set = load_processed_set(processed_txt)
            self.assertIn("TestPiece", processed_set)

            # Check processed_midis.txt
            clean_list = data_dir / "processed_midis.txt"
            self.assertTrue(clean_list.exists())
            self.assertIn("TestPiece", clean_list.read_text(encoding="utf-8"))

            # Check render_history.csv
            history_csv = data_dir / "render_history.csv"
            self.assertTrue(history_csv.exists())
            csv_content = history_csv.read_text(encoding="utf-8")
            self.assertIn("TestPiece", csv_content)
            self.assertIn("120.50", csv_content)
            self.assertIn("45.20", csv_content)

            # Check RENDER_LOG.md
            render_md = data_dir / "RENDER_LOG.md"
            self.assertTrue(render_md.exists())
            md_content = render_md.read_text(encoding="utf-8")
            self.assertIn("`TestPiece`", md_content)
            self.assertIn("120.5s", md_content)


if __name__ == "__main__":
    unittest.main()
