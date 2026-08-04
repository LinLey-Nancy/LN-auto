import unittest

import numpy

from window_auto.diagnostics.screenshot import bgr_to_image


class ScreenshotTests(unittest.TestCase):
    def test_bgr_is_converted_to_rgb(self) -> None:
        image = numpy.array([[[10, 20, 30]]], dtype=numpy.uint8)

        converted = bgr_to_image(image)

        self.assertEqual(converted.getpixel((0, 0)), (30, 20, 10))
