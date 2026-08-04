from types import SimpleNamespace
import unittest

import numpy

from window_auto.diagnostics.template_match import (
    TemplateMatchDiagnosticError,
    best_template_candidate,
    crop_template,
    match_box_from_raw,
)


class TemplateMatchDiagnosticTests(unittest.TestCase):
    def test_template_crop_uses_requested_roi(self) -> None:
        image = numpy.zeros((20, 30, 3), dtype=numpy.uint8)
        image[4:10, 5:13] = (10, 20, 30)

        template = crop_template(image, (5, 4, 8, 6))

        self.assertEqual(template.shape, (6, 8, 3))
        self.assertEqual(tuple(template[0, 0]), (10, 20, 30))

    def test_out_of_bounds_roi_is_rejected(self) -> None:
        image = numpy.zeros((20, 30, 3), dtype=numpy.uint8)
        with self.assertRaises(TemplateMatchDiagnosticError):
            crop_template(image, (25, 10, 10, 10))

    def test_list_match_box_from_binding_is_supported(self) -> None:
        box = match_box_from_raw([1, 2, 3, 4])
        self.assertEqual((box.x, box.y, box.w, box.h), (1, 2, 3, 4))

    def test_best_candidate_includes_below_threshold_miss(self) -> None:
        results = [
            SimpleNamespace(score=0.41, box=[1, 2, 3, 4]),
            SimpleNamespace(score=0.67, box=[5, 6, 7, 8]),
        ]

        score, box = best_template_candidate(results)

        self.assertEqual(score, 0.67)
        self.assertEqual((box.x, box.y, box.w, box.h), (5, 6, 7, 8))
