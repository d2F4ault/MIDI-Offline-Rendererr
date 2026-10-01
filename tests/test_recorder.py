"""
Unit tests for recorder utilities and frame pipeline structures.
"""

import unittest
from pathlib import Path
from pianofall.core.recorder import get_png_dimensions, FrameWriter


class TestRecorder(unittest.TestCase):
    def test_get_png_dimensions_valid(self):
        # Construct minimal 24-byte PNG header: 8 bytes magic + 4 bytes IHDR len + 4 bytes IHDR type + 4 bytes width + 4 bytes height
        # Width: 1920 (0x0780), Height: 1200 (0x04B0)
        png_header = (
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\x0d"
            b"IHDR"
            b"\x00\x00\x07\x80"
            b"\x00\x00\x04\xb0"
        )
        w, h = get_png_dimensions(png_header)
        self.assertEqual(w, 1920)
        self.assertEqual(h, 1200)

    def test_get_png_dimensions_invalid(self):
        w, h = get_png_dimensions(b"NOT_A_PNG_FILE_DATA")
        self.assertEqual(w, 0)
        self.assertEqual(h, 0)


if __name__ == "__main__":
    unittest.main()
