import unittest

from fedcompose.contracts import DeploymentPriorContract, ExpertContract, assert_compatible
from fedcompose.evidence import (
    centralized_gain_recovery,
    fuse_evidence,
    prior_corrected_evidence,
)


class EvidenceTests(unittest.TestCase):
    digest = "a" * 64

    def test_uninformative_expert_returns_target_prior(self):
        evidence = prior_corrected_evidence((0.25, 0.75), (0.25, 0.75))
        fused = fuse_evidence([evidence], (0.4, 0.6))
        self.assertAlmostEqual(fused[0], 0.4)
        self.assertAlmostEqual(fused[1], 0.6)

    def test_recovery_fraction_requires_a_positive_oracle_gap(self):
        informative = centralized_gain_recovery(0.76, 0.72, 0.80)
        self.assertTrue(informative.informative_for_recovery_fraction)
        self.assertAlmostEqual(informative.absolute_gain_over_best_unimodal, 0.04)
        self.assertAlmostEqual(informative.recovery_fraction, 0.5)

        tied_oracle = centralized_gain_recovery(0.73, 0.72, 0.725)
        self.assertFalse(tied_oracle.informative_for_recovery_fraction)
        self.assertIsNone(tied_oracle.recovery_fraction)
        self.assertAlmostEqual(tied_oracle.absolute_gain_over_best_unimodal, 0.01)

    def test_incompatible_ontology_is_rejected(self):
        common = dict(
            modality="ecg", semantic_version="1.0.0", model_sha256=self.digest,
            checkpoint_sha256=self.digest, training_cohort_manifest_sha256=self.digest,
            ordered_class_ids=("survives", "dies"), target_horizon="after_72h",
            class_prior=(0.5, 0.5), preprocessing_manifest_sha256=self.digest,
            calibration_set_sha256=self.digest, calibration_method="temperature",
            calibration_validation_manifest_sha256=self.digest, output_schema_version=1,
            created_at="2026-01-01T00:00:00+00:00",
        )
        first = ExpertContract(expert_id="a", target_ontology_sha256="1" * 64, **common)
        second = ExpertContract(expert_id="b", target_ontology_sha256="2" * 64, **common)
        with self.assertRaisesRegex(ValueError, "do not share ontology"):
            assert_compatible([first, second])

    def test_reversed_class_semantics_and_invalid_priors_are_rejected(self):
        common = dict(
            modality="ecg", semantic_version="1.0.0", model_sha256=self.digest,
            checkpoint_sha256=self.digest, training_cohort_manifest_sha256=self.digest,
            target_ontology_sha256=self.digest, target_horizon="after_72h",
            preprocessing_manifest_sha256=self.digest, calibration_set_sha256=self.digest,
            calibration_method="temperature", calibration_validation_manifest_sha256=self.digest,
            output_schema_version=1, created_at="2026-01-01T00:00:00+00:00",
        )
        first = ExpertContract(
            expert_id="a", ordered_class_ids=("survives", "dies"),
            class_prior=(0.5, 0.5), **common
        )
        reversed_labels = ExpertContract(
            expert_id="b", ordered_class_ids=("dies", "survives"),
            class_prior=(0.5, 0.5), **common
        )
        with self.assertRaisesRegex(ValueError, "ordered classes"):
            assert_compatible([first, reversed_labels])
        invalid_prior = ExpertContract(
            expert_id="c", ordered_class_ids=("survives", "dies"),
            class_prior=(1.1, -0.1), **common
        )
        with self.assertRaisesRegex(ValueError, "class priors"):
            assert_compatible([invalid_prior])
        nan_prior = ExpertContract(
            expert_id="d", ordered_class_ids=("survives", "dies"),
            class_prior=(float("nan"), 0.5), **common
        )
        with self.assertRaisesRegex(ValueError, "class priors"):
            assert_compatible([nan_prior])

    def test_deployment_prior_cannot_use_test_labels(self):
        contract = DeploymentPriorContract(
            ordered_class_ids=("survives", "dies"),
            target_prior=(0.9, 0.1),
            estimation_cohort_manifest_sha256=self.digest,
            label_source_role="test",
            cohort_disjoint_from_test=False,
            shift_policy="sensitivity grid",
        )
        with self.assertRaisesRegex(ValueError, "test labels"):
            contract.validate()

    def test_digest_schema_and_timestamp_are_enforced(self):
        common = dict(
            expert_id="a", modality="ecg", semantic_version="1.0.0",
            model_sha256="not-a-hash", checkpoint_sha256=self.digest,
            training_cohort_manifest_sha256=self.digest,
            target_ontology_sha256=self.digest,
            ordered_class_ids=("survives", "dies"), target_horizon="after_72h",
            class_prior=(0.5, 0.5), preprocessing_manifest_sha256=self.digest,
            calibration_set_sha256=self.digest, calibration_method="temperature",
            calibration_validation_manifest_sha256=self.digest, output_schema_version=1,
            created_at="2026-01-01T00:00:00+00:00",
        )
        with self.assertRaisesRegex(ValueError, "lowercase SHA-256"):
            ExpertContract(**common).validate()
        common["model_sha256"] = self.digest
        common["created_at"] = "2026-01-01T00:00:00"
        with self.assertRaisesRegex(ValueError, "timezone"):
            ExpertContract(**common).validate()


if __name__ == "__main__":
    unittest.main()
