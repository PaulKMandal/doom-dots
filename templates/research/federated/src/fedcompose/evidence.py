from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class RecoveryOutcome:
    absolute_gain_over_best_unimodal: float
    centralized_oracle_gap: float
    recovery_fraction: float | None
    informative_for_recovery_fraction: bool


def centralized_gain_recovery(
    proposal_auroc: float,
    best_unimodal_auroc: float,
    centralized_oracle_auroc: float,
    *,
    minimum_positive_oracle_gap: float = 0.01,
) -> RecoveryOutcome:
    """Compute recovery only when its oracle-gap denominator is informative."""
    values = (proposal_auroc, best_unimodal_auroc, centralized_oracle_auroc)
    if any(not math.isfinite(value) or value < 0 or value > 1 for value in values):
        raise ValueError("AUROC values must be finite and lie in [0, 1]")
    if not math.isfinite(minimum_positive_oracle_gap) or minimum_positive_oracle_gap <= 0:
        raise ValueError("minimum oracle gap must be finite and positive")
    absolute_gain = proposal_auroc - best_unimodal_auroc
    oracle_gap = centralized_oracle_auroc - best_unimodal_auroc
    informative = oracle_gap >= minimum_positive_oracle_gap
    return RecoveryOutcome(
        absolute_gain_over_best_unimodal=absolute_gain,
        centralized_oracle_gap=oracle_gap,
        recovery_fraction=(absolute_gain / oracle_gap) if informative else None,
        informative_for_recovery_fraction=informative,
    )


def _validate_probabilities(values: Sequence[float], label: str) -> None:
    if len(values) < 2 or any(not math.isfinite(value) or value <= 0 for value in values):
        raise ValueError(f"{label} probabilities must be finite and positive")
    if abs(sum(values) - 1.0) > 1e-6:
        raise ValueError(f"{label} probabilities must sum to one")


def prior_corrected_evidence(
    calibrated_posterior: Sequence[float], training_prior: Sequence[float]
) -> tuple[float, ...]:
    if len(calibrated_posterior) != len(training_prior) or len(training_prior) < 2:
        raise ValueError("posterior and prior must have the same class count")
    _validate_probabilities(calibrated_posterior, "posterior")
    _validate_probabilities(training_prior, "prior")
    return tuple(math.log(posterior) - math.log(prior) for posterior, prior in zip(calibrated_posterior, training_prior))


def fuse_evidence(
    evidence_vectors: Sequence[Sequence[float]], target_prior: Sequence[float]
) -> tuple[float, ...]:
    if not evidence_vectors:
        raise ValueError("at least one available expert is required")
    class_count = len(target_prior)
    _validate_probabilities(target_prior, "target prior")
    if class_count < 2 or any(len(vector) != class_count for vector in evidence_vectors):
        raise ValueError("all evidence vectors must match the target class count")
    if any(not math.isfinite(value) for vector in evidence_vectors for value in vector):
        raise ValueError("evidence values must be finite")
    logits = [math.log(value) for value in target_prior]
    for vector in evidence_vectors:
        logits = [left + right for left, right in zip(logits, vector)]
    maximum = max(logits)
    weights = [math.exp(value - maximum) for value in logits]
    denominator = sum(weights)
    return tuple(value / denominator for value in weights)
