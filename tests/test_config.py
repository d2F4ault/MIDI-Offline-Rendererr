"""
Unit tests for configuration initialization and environment overrides.
"""

import os
import unittest
from pianofall.config import Config


class TestConfig(unittest.TestCase):
    def test_config_defaults(self):
        cfg = Config()
        self.assertEqual(cfg.viewport_w, 1920)
        self.assertEqual(cfg.viewport_h, 1200)
        self.assertEqual(cfg.output_fps, 60)
        self.assertEqual(cfg.capture_fps, 60)
        self.assertEqual(cfg.render_crf, 14)
        self.assertEqual(cfg.render_preset, "slow")
        self.assertEqual(cfg.midi_dir.name, "midis")
        self.assertEqual(cfg.output_dir.name, "outputs")

    def test_config_env_overrides(self):
        old_env = os.environ.copy()
        try:
            os.environ["RENDER_VIEWPORT_W"] = "1280"
            os.environ["RENDER_VIEWPORT_H"] = "720"
            os.environ["RENDER_CRF"] = "22"
            os.environ["MAX_VIDEOS_PER_RUN"] = "3"

            cfg = Config()
            self.assertEqual(cfg.viewport_w, 1280)
            self.assertEqual(cfg.viewport_h, 720)
            self.assertEqual(cfg.render_crf, 22)
            self.assertEqual(cfg.max_videos_per_run, 3)
        finally:
            os.environ.clear()
            os.environ.update(old_env)


if __name__ == "__main__":
    unittest.main()
