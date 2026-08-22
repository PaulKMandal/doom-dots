import math
import unittest

from chembench.uncertainty import (
    InterventionPairObservation,
    UncertaintyObservation,
    binary_auroc,
    brier_score,
    expected_calibration_error,
    failure_detection_auroc,
    failure_labels,
    ood_detection_auroc,
    ood_labels,
    risk_coverage_curve,
    summarize_interventions,
    top_uncertain_jaccard,
)


MANIFEST_SHA256 = "a" * 64


def observation(**overrides):
    values = {
        "reaction_id": "r1",
        "task": "forward_endpoint",
        "split_id": "test",
        "shift_axis": "reaction_family",
        "shift_level": "held_out",
        "model_id": "model-1",
        "model_family": "transformer",
        "representation": "r-smiles",
        "is_correct": True,
        "is_ood": False,
        "uncertainty": 0.25,
        "confidence": 0.75,
        "score_name": "length_normalized_nll",
        "aggregation_name": "sequence_mean",
        "score_direction": "higher_is_more_uncertain",
        "correctness_definition": "equivalence_aware_top1",
        "calibration_status": "validation_fit",
        "dataset_manifest_sha256": MANIFEST_SHA256,
        "split_manifest_sha256": MANIFEST_SHA256,
        "model_manifest_sha256": MANIFEST_SHA256,
        "calibration_manifest_sha256": MANIFEST_SHA256,
        "generated_candidates": 32,
        "retained_candidates": 10,
        "model_calls": 32,
    }
    values.update(overrides)
    return UncertaintyObservation(**values)


class ObservationValidationTests(unittest.TestCase):
    def test_valid_observation(self):
        observation().validate()

    def test_nonfinite_uncertainty_is_rejected(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "finite"):
                observation(uncertainty=value).validate()

    def test_confidence_and_digest_are_strict(self):
        with self.assertRaisesRegex(ValueError, r"\[0, 1\]"):
            observation(confidence=1.01).validate()
        with self.assertRaisesRegex(ValueError, "lowercase"):
            observation(calibration_manifest_sha256="A" * 64).validate()
        with self.assertRaisesRegex(ValueError, "positive integer"):
            observation(equivalence_class_size=True).validate()

    def test_score_orientation_calibration_and_budgets_are_explicit(self):
        with self.assertRaisesRegex(ValueError, "higher_is_more_uncertain"):
            observation(score_direction="higher_is_more_confident").validate()
        with self.assertRaisesRegex(ValueError, "native or validation_fit"):
            observation(calibration_status="test_fit").validate()
        with self.assertRaisesRegex(ValueError, "cannot exceed"):
            observation(generated_candidates=4, retained_candidates=5).validate()
        with self.assertRaisesRegex(ValueError, "positive integer"):
            observation(model_calls=True).validate()


class RankingMetricTests(unittest.TestCase):
    def test_binary_auroc_is_tie_aware(self):
        self.assertEqual(binary_auroc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]), 1.0)
        self.assertEqual(binary_auroc([0, 1, 0, 1], [0.0, 0.0, 1.0, 1.0]), 0.5)

    def test_binary_auroc_returns_none_for_single_class(self):
        self.assertIsNone(binary_auroc([True, True], [0.1, 0.9]))

    def test_ood_and_failure_are_not_conflated(self):
        observations = [
            observation(reaction_id="ood-correct", is_ood=True, is_correct=True, uncertainty=0.9),
            observation(reaction_id="iid-wrong", is_ood=False, is_correct=False, uncertainty=0.1),
        ]
        self.assertEqual(ood_labels(observations), (True, False))
        self.assertEqual(failure_labels(observations), (False, True))
        self.assertEqual(ood_detection_auroc(observations), 1.0)
        self.assertEqual(failure_detection_auroc(observations), 0.0)

    def test_risk_coverage_accepts_ties_as_a_group(self):
        result = risk_coverage_curve(
            [True, False, False, True], [0.1, 0.2, 0.2, 0.8]
        )
        self.assertEqual([point.accepted for point in result.points], [1, 3, 4])
        self.assertEqual([point.tie_size for point in result.points], [1, 2, 1])
        self.assertAlmostEqual(result.points[1].risk, 2 / 3)
        self.assertAlmostEqual(result.aurc, 11 / 24)

    def test_top_uncertain_overlap_includes_boundary_ties(self):
        first = {"r1": 0.9, "r2": 0.8, "r3": 0.8, "r4": 0.1}
        second = {"r1": 0.1, "r2": 0.8, "r3": 0.7, "r4": 0.7}
        self.assertEqual(top_uncertain_jaccard(first, second, k=2), 0.5)


class CalibrationMetricTests(unittest.TestCase):
    def test_brier_and_ece(self):
        correctness = [True, False, True, False]
        confidence = [0.9, 0.8, 0.6, 0.1]
        self.assertAlmostEqual(brier_score(correctness, confidence), 0.205)
        self.assertAlmostEqual(
            expected_calibration_error(correctness, confidence, n_bins=2), 0.1
        )

    def test_invalid_probabilities_are_rejected(self):
        with self.assertRaisesRegex(ValueError, r"\[0, 1\]"):
            brier_score([True], [-0.1])
        with self.assertRaisesRegex(ValueError, "positive integer"):
            expected_calibration_error([True], [0.9], n_bins=0)


class InterventionTests(unittest.TestCase):
    def test_intervention_metrics(self):
        pairs = [
            InterventionPairObservation(
                "p1",
                "contrast-test",
                "r1-control",
                "r1-intervention",
                True,
                True,
                True,
                True,
                0.2,
                0.9,
                0.9,
            ),
            InterventionPairObservation(
                "p2",
                "contrast-test",
                "r2-control",
                "r2-intervention",
                True,
                False,
                True,
                False,
                0.3,
                0.2,
                0.95,
            ),
        ]
        metrics = summarize_interventions(pairs, confident_threshold=0.8)
        self.assertEqual(metrics.n_pairs, 2)
        self.assertEqual(metrics.n_branch_changes, 2)
        self.assertEqual(metrics.both_correct_rate, 0.5)
        self.assertEqual(metrics.correct_branch_flip_rate, 0.5)
        self.assertEqual(metrics.prediction_switch_rate, 0.5)
        self.assertAlmostEqual(metrics.mean_reference_probability_shift, 0.3)
        self.assertEqual(metrics.confident_shortcut_failure_rate, 0.5)

    def test_duplicate_reaction_membership_is_rejected(self):
        first = InterventionPairObservation(
            "p1", "test", "r1", "r2", True, True, True, True, 0.1, 0.9, 0.9
        )
        second = InterventionPairObservation(
            "p2", "test", "r2", "r3", True, True, True, True, 0.1, 0.9, 0.9
        )
        with self.assertRaisesRegex(ValueError, "multiple pairs"):
            summarize_interventions([first, second])


if __name__ == "__main__":
    unittest.main()
