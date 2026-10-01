"""
Unit tests for queue discovery, ledger management, and output cleanup.
"""

import tempfile
import unittest
from pathlib import Path
from pianofall.queue.ledger import (
    append_failed_entry,
    append_processed_entry,
    load_failed_map,
    load_processed_set,
    perform_output_cleanup,
)
from pianofall.queue.manager import select_candidates


class TestQueue(unittest.TestCase):
    def test_ledger_append_and_load(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proc_log = Path(tmp_dir) / "processed.txt"
            fail_log = Path(tmp_dir) / "failed.txt"

            append_processed_entry(
                log_path=proc_log,
                midi_filename="test_song.mid",
                duration_s=120.5,
                frames=7230,
                file_size_bytes=5000000,
                rel_output_path="outputs/run_01/mp4/test_song.mp4",
            )

            proc_set = load_processed_set(proc_log)
            self.assertIn("test_song.mid", proc_set)
            self.assertIn("test_song", proc_set)

            append_failed_entry(
                log_path=fail_log,
                midi_filename="broken_song.mid",
                error_msg="Test timeout error",
            )

            quarantined, attempts = load_failed_map(fail_log)
            self.assertIn("broken_song.mid", quarantined)
            self.assertEqual(attempts.get("broken_song.mid"), 1)

    def test_select_candidates_filters_processed(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proc_log = Path(tmp_dir) / "processed.txt"
            fail_log = Path(tmp_dir) / "failed.txt"
            midi_dir = Path(tmp_dir) / "midis"
            midi_dir.mkdir()

            root = Path(__file__).resolve().parent.parent
            pool_dir = root / "midis_pool"
            midis = list(pool_dir.glob("*.mid"))
            self.assertTrue(len(midis) > 0, "Pool MIDIs must exist")
            sample = midis[0]

            target = midi_dir / sample.name
            target.write_bytes(sample.read_bytes())

            cand = select_candidates(
                midi_dir=midi_dir,
                processed_log=proc_log,
                failed_log=fail_log,
                max_duration_seconds=3600.0,
                limit=1,
                auto_fetch_preview=False,
            )
            self.assertEqual(len(cand), 1)
            self.assertEqual(cand[0][0].name, sample.name)

            # Mark as processed
            append_processed_entry(
                log_path=proc_log,
                midi_filename=sample.name,
                duration_s=120.0,
                frames=7200,
                file_size_bytes=5000000,
                rel_output_path=f"outputs/run_01/mp4/{sample.stem}.mp4",
            )

            # Now candidate should be filtered out
            cand_after = select_candidates(
                midi_dir=midi_dir,
                processed_log=proc_log,
                failed_log=fail_log,
                max_duration_seconds=3600.0,
                limit=1,
                auto_fetch_preview=False,
            )
            self.assertEqual(len(cand_after), 0)

    def test_perform_output_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir) / "outputs"
            data_dir = Path(tmp_dir) / "data"
            out_dir.mkdir()
            data_dir.mkdir()

            # Create dummy previous run
            run_dir = out_dir / "run_2026-09-30_120000"
            mp4_dir = run_dir / "mp4"
            mid_dir = run_dir / "midis"
            mp4_dir.mkdir(parents=True)
            mid_dir.mkdir(parents=True)

            dummy_video = mp4_dir / "piece.mp4"
            dummy_video.write_bytes(b"X" * 1024 * 100)  # 100 KB
            dummy_midi = mid_dir / "piece.mid"
            dummy_midi.write_bytes(b"MThd" + b"\x00" * 20)

            # Run cleanup
            n_removed, bytes_freed = perform_output_cleanup(out_dir, data_dir)
            self.assertEqual(n_removed, 2)
            self.assertGreater(bytes_freed, 100000)

            # Verify files and folder are purged
            self.assertFalse(run_dir.exists())

            # Verify deletion logs are written
            del_csv = data_dir / "deletion_history.csv"
            clean_md = data_dir / "cleanup_log.md"
            self.assertTrue(del_csv.exists())
            self.assertTrue(clean_md.exists())
            self.assertIn("piece.mp4", del_csv.read_text(encoding="utf-8"))
            self.assertIn("piece.mp4", clean_md.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
