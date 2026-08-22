from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
import re


SHA256 = re.compile(r"[0-9a-f]{64}")


def _require_sha256(label: str, value: str) -> None:
    if SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


@dataclass(frozen=True)
class ExpertContract:
    expert_id: str
    modality: str
    semantic_version: str
    model_sha256: str
    checkpoint_sha256: str
    training_cohort_manifest_sha256: str
    target_ontology_sha256: str
    ordered_class_ids: tuple[str, ...]
    target_horizon: str
    class_prior: tuple[float, ...]
    preprocessing_manifest_sha256: str
    calibration_set_sha256: str
    calibration_method: str
    calibration_validation_manifest_sha256: str
    output_schema_version: int
    created_at: str

    def validate(self) -> None:
        if not self.expert_id or not self.modality or not self.semantic_version:
            raise ValueError("expert identity, modality, and version are required")
        if (
            len(self.ordered_class_ids) < 2
            or len(set(self.ordered_class_ids)) != len(self.ordered_class_ids)
            or any(not value for value in self.ordered_class_ids)
        ):
            raise ValueError("ordered class IDs must contain unique nonempty labels")
        if len(self.ordered_class_ids) != len(self.class_prior):
            raise ValueError("ordered class IDs and class priors must have equal length")
        if len(self.class_prior) < 2 or any(
            not math.isfinite(value) or value <= 0 for value in self.class_prior
        ):
            raise ValueError("class priors must be positive and contain at least two classes")
        if abs(sum(self.class_prior) - 1.0) > 1e-6:
            raise ValueError("class priors must sum to one")
        required = (
            self.model_sha256,
            self.checkpoint_sha256,
            self.training_cohort_manifest_sha256,
            self.target_ontology_sha256,
            self.target_horizon,
            self.preprocessing_manifest_sha256,
            self.calibration_set_sha256,
            self.calibration_method,
            self.calibration_validation_manifest_sha256,
        )
        if any(not value for value in required):
            raise ValueError("model, target, preprocessing, and calibration fields are required")
        for label, value in (
            ("model_sha256", self.model_sha256),
            ("checkpoint_sha256", self.checkpoint_sha256),
            ("training_cohort_manifest_sha256", self.training_cohort_manifest_sha256),
            ("target_ontology_sha256", self.target_ontology_sha256),
            ("preprocessing_manifest_sha256", self.preprocessing_manifest_sha256),
            ("calibration_set_sha256", self.calibration_set_sha256),
            ("calibration_validation_manifest_sha256", self.calibration_validation_manifest_sha256),
        ):
            _require_sha256(label, value)
        if (
            isinstance(self.output_schema_version, bool)
            or not isinstance(self.output_schema_version, int)
            or self.output_schema_version < 1
        ):
            raise ValueError("output schema version must be a positive integer")
        created = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        if created.tzinfo is None or created.utcoffset() is None:
            raise ValueError("created_at must include a timezone offset")


@dataclass(frozen=True)
class DeploymentPriorContract:
    ordered_class_ids: tuple[str, ...]
    target_prior: tuple[float, ...]
    estimation_cohort_manifest_sha256: str
    label_source_role: str
    cohort_disjoint_from_test: bool
    shift_policy: str

    def validate(self) -> None:
        if len(self.ordered_class_ids) != len(self.target_prior) or len(self.target_prior) < 2:
            raise ValueError("deployment prior must match the ordered class IDs")
        if any(not math.isfinite(value) or value <= 0 for value in self.target_prior) or abs(sum(self.target_prior) - 1.0) > 1e-6:
            raise ValueError("deployment prior must be positive and sum to one")
        if self.label_source_role not in {"calibration", "predeployment"}:
            raise ValueError("deployment prior cannot be estimated from validation or test labels")
        if not self.cohort_disjoint_from_test or not self.estimation_cohort_manifest_sha256:
            raise ValueError("deployment-prior cohort must be hashed and disjoint from test")
        _require_sha256(
            "estimation_cohort_manifest_sha256", self.estimation_cohort_manifest_sha256
        )
        if not self.shift_policy:
            raise ValueError("deployment-prior shift/sensitivity policy is required")


def assert_compatible(contracts: list[ExpertContract]) -> None:
    if not contracts:
        raise ValueError("at least one expert contract is required")
    for contract in contracts:
        contract.validate()
    ontology = {item.target_ontology_sha256 for item in contracts}
    classes = {item.ordered_class_ids for item in contracts}
    horizons = {item.target_horizon for item in contracts}
    schemas = {item.output_schema_version for item in contracts}
    if len(ontology) != 1 or len(classes) != 1 or len(horizons) != 1 or len(schemas) != 1:
        raise ValueError(
            "experts do not share ontology, ordered classes, target horizon, and output schema"
        )
