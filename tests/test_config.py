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
        self.assertIn(cfg.midi_pool_dir.name, ("midis_pool", "midis"))
        self.assertEqual(cfg.output_dir.name, "outputs")
        self.assertEqual(cfg.target_videos, 30)
        self.assertTrue(cfg.clean_previous_outputs)

    def test_config_env_overrides(self):
        old_env = os.environ.copy()
        try:
            os.environ["RENDER_VIEWPORT_W"] = "1280"
            os.environ["RENDER_VIEWPORT_H"] = "720"
            os.environ["RENDER_CRF"] = "22"
            os.environ["TARGET_VIDEOS"] = "15"
            os.environ["CLEAN_PREVIOUS_OUTPUTS"] = "false"

            cfg = Config()
            self.assertEqual(cfg.viewport_w, 1280)
            self.assertEqual(cfg.viewport_h, 720)
            self.assertEqual(cfg.render_crf, 22)
            self.assertEqual(cfg.target_videos, 15)
            self.assertFalse(cfg.clean_previous_outputs)
        finally:
            os.environ.clear()
            os.environ.update(old_env)


if __name__ == "__main__":
    unittest.main()
