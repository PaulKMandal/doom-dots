"""Dependency-free uncertainty and shift-evaluation utilities.

The module deliberately keeps distribution-shift membership and prediction
failure as separate labels.  An out-of-distribution reaction can be predicted
correctly, and an in-distribution reaction can be predicted incorrectly; callers
must therefore provide both labels rather than asking the evaluator to infer one
from the other.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Mapping, Sequence


SHA256 = re.compile(r"[0-9a-f]{64}")
CALIBRATION_STATUSES = {"native", "validation_fit"}


def _require_nonempty_string(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_bool(value: object, name: str) -> None:
    if type(value) is not bool:
        raise ValueError(f"{name} must be a bool")


def _require_finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite real number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite real number")
    return result


def _require_probability(value: object, name: str) -> float:
    result = _require_finite(value, name)
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"{name} must be in [0, 1]")
    return result


def _require_sha256(value: object, name: str) -> None:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase 64-character hex digest")


@dataclass(frozen=True)
class UncertaintyObservation:
    """One prediction and the provenance needed to interpret its uncertainty."""

    reaction_id: str
    task: str
    split_id: str
    shift_axis: str
    shift_level: str
    model_id: str
    model_family: str
    representation: str
    is_correct: bool
    is_ood: bool
    uncertainty: float
    confidence: float
    score_name: str
    aggregation_name: str
    score_direction: str
    correctness_definition: str
    calibration_status: str
    dataset_manifest_sha256: str
    split_manifest_sha256: str
    model_manifest_sha256: str
    calibration_manifest_sha256: str
    generated_candidates: int
    retained_candidates: int
    model_calls: int
    equivalence_class_size: int = 1

    def validate(self) -> None:
        for name in (
            "reaction_id",
            "task",
            "split_id",
            "shift_axis",
            "shift_level",
            "model_id",
            "model_family",
            "representation",
            "score_name",
            "aggregation_name",
            "correctness_definition",
        ):
            _require_nonempty_string(getattr(self, name), name)
        _require_bool(self.is_correct, "is_correct")
        _require_bool(self.is_ood, "is_ood")
        _require_finite(self.uncertainty, "uncertainty")
        _require_probability(self.confidence, "confidence")
        if self.score_direction != "higher_is_more_uncertain":
            raise ValueError("score_direction must be higher_is_more_uncertain")
        if self.calibration_status not in CALIBRATION_STATUSES:
            raise ValueError("calibration_status must be native or validation_fit")
        for name in (
            "dataset_manifest_sha256",
            "split_manifest_sha256",
            "model_manifest_sha256",
            "calibration_manifest_sha256",
        ):
            _require_sha256(getattr(self, name), name)
        for name in ("generated_candidates", "retained_candidates", "model_calls"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.retained_candidates > self.generated_candidates:
            raise ValueError("retained_candidates cannot exceed generated_candidates")
        if type(self.equivalence_class_size) is not int or self.equivalence_class_size < 1:
            raise ValueError("equivalence_class_size must be a positive integer")


def _validate_labels_and_scores(
    labels: Sequence[bool | int], scores: Sequence[float]
) -> tuple[list[int], list[float]]:
    if len(labels) != len(scores):
        raise ValueError("labels and scores must have the same length")
    if not labels:
        raise ValueError("at least one observation is required")

    checked_labels: list[int] = []
    checked_scores: list[float] = []
    for index, (label, score) in enumerate(zip(labels, scores)):
        if type(label) is bool:
            checked_labels.append(int(label))
        elif type(label) is int and label in (0, 1):
            checked_labels.append(label)
        else:
            raise ValueError(f"label at index {index} must be bool, 0, or 1")
        checked_scores.append(_require_finite(score, f"score at index {index}"))
    return checked_labels, checked_scores


def binary_auroc(labels: Sequence[bool | int], scores: Sequence[float]) -> float | None:
    """Return tie-aware binary AUROC, or ``None`` when only one class is present.

    Larger scores are interpreted as stronger evidence for the positive class.
    The implementation is the probability that a randomly chosen positive has
    a larger score than a randomly chosen negative, with score ties worth 0.5.
    """

    checked_labels, checked_scores = _validate_labels_and_scores(labels, scores)
    positives = sum(checked_labels)
    negatives = len(checked_labels) - positives
    if positives == 0 or negatives == 0:
        return None

    ordered = sorted(zip(checked_scores, checked_labels), key=lambda item: item[0])
    negatives_below = 0
    favorable_pairs = 0.0
    cursor = 0
    while cursor < len(ordered):
        score = ordered[cursor][0]
        end = cursor
        group_positives = 0
        group_negatives = 0
        while end < len(ordered) and ordered[end][0] == score:
            if ordered[end][1] == 1:
                group_positives += 1
            else:
                group_negatives += 1
            end += 1
        favorable_pairs += group_positives * (
            negatives_below + 0.5 * group_negatives
        )
        negatives_below += group_negatives
        cursor = end
    return favorable_pairs / (positives * negatives)


def failure_labels(observations: Sequence[UncertaintyObservation]) -> tuple[bool, ...]:
    """Extract explicit failure labels without using distribution membership."""

    for observation in observations:
        observation.validate()
    return tuple(not observation.is_correct for observation in observations)


def ood_labels(observations: Sequence[UncertaintyObservation]) -> tuple[bool, ...]:
    """Extract explicit OOD labels without using prediction correctness."""

    for observation in observations:
        observation.validate()
    return tuple(observation.is_ood for observation in observations)


def failure_detection_auroc(
    observations: Sequence[UncertaintyObservation],
) -> float | None:
    """Measure how well uncertainty ranks incorrect predictions."""

    return binary_auroc(
        failure_labels(observations),
        [observation.uncertainty for observation in observations],
    )


def ood_detection_auroc(observations: Sequence[UncertaintyObservation]) -> float | None:
    """Measure how well uncertainty ranks explicitly labeled OOD examples."""

    return binary_auroc(
        ood_labels(observations),
        [observation.uncertainty for observation in observations],
    )


@dataclass(frozen=True)
class RiskCoveragePoint:
    coverage: float
    risk: float
    threshold: float
    accepted: int
    tie_size: int


@dataclass(frozen=True)
class RiskCoverageResult:
    points: tuple[RiskCoveragePoint, ...]
    aurc: float


def risk_coverage_curve(
    is_correct: Sequence[bool], uncertainty: Sequence[float]
) -> RiskCoverageResult:
    """Build a selective-prediction curve while accepting score ties together.

    Lower-uncertainty predictions are accepted first.  A point is emitted only
    after a complete tie group has been accepted, so input order cannot provide
    an artificial advantage.  ``aurc`` is the right-continuous step integral of
    risk over coverage across those attainable operating points.
    """

    if len(is_correct) != len(uncertainty):
        raise ValueError("is_correct and uncertainty must have the same length")
    if not is_correct:
        raise ValueError("at least one observation is required")

    checked: list[tuple[float, bool]] = []
    for index, (correct, score) in enumerate(zip(is_correct, uncertainty)):
        _require_bool(correct, f"is_correct at index {index}")
        checked.append((_require_finite(score, f"uncertainty at index {index}"), correct))
    checked.sort(key=lambda item: item[0])

    total = len(checked)
    accepted = 0
    failures = 0
    previous_coverage = 0.0
    aurc = 0.0
    points: list[RiskCoveragePoint] = []
    cursor = 0
    while cursor < total:
        threshold = checked[cursor][0]
        end = cursor
        group_failures = 0
        while end < total and checked[end][0] == threshold:
            group_failures += int(not checked[end][1])
            end += 1
        tie_size = end - cursor
        accepted += tie_size
        failures += group_failures
        coverage = accepted / total
        risk = failures / accepted
        aurc += (coverage - previous_coverage) * risk
        points.append(RiskCoveragePoint(coverage, risk, threshold, accepted, tie_size))
        previous_coverage = coverage
        cursor = end
    return RiskCoverageResult(tuple(points), aurc)


def brier_score(is_correct: Sequence[bool], confidence: Sequence[float]) -> float:
    """Return mean squared error for confidence interpreted as P(correct)."""

    if len(is_correct) != len(confidence):
        raise ValueError("is_correct and confidence must have the same length")
    if not is_correct:
        raise ValueError("at least one observation is required")

    total = 0.0
    for index, (correct, probability) in enumerate(zip(is_correct, confidence)):
        _require_bool(correct, f"is_correct at index {index}")
        checked_probability = _require_probability(
            probability, f"confidence at index {index}"
        )
        total += (checked_probability - float(correct)) ** 2
    return total / len(is_correct)


def expected_calibration_error(
    is_correct: Sequence[bool], confidence: Sequence[float], *, n_bins: int = 10
) -> float:
    """Return equal-width expected calibration error for P(correct).

    Bins are ``[lower, upper)`` except that confidence 1.0 is included in the
    final bin.  Empty bins contribute zero.
    """

    if type(n_bins) is not int or n_bins < 1:
        raise ValueError("n_bins must be a positive integer")
    if len(is_correct) != len(confidence):
        raise ValueError("is_correct and confidence must have the same length")
    if not is_correct:
        raise ValueError("at least one observation is required")

    counts = [0] * n_bins
    confidence_sums = [0.0] * n_bins
    correct_sums = [0] * n_bins
    for index, (correct, probability) in enumerate(zip(is_correct, confidence)):
        _require_bool(correct, f"is_correct at index {index}")
        checked_probability = _require_probability(
            probability, f"confidence at index {index}"
        )
        bin_index = min(int(checked_probability * n_bins), n_bins - 1)
        counts[bin_index] += 1
        confidence_sums[bin_index] += checked_probability
        correct_sums[bin_index] += int(correct)

    total = len(is_correct)
    ece = 0.0
    for count, confidence_sum, correct_sum in zip(
        counts, confidence_sums, correct_sums
    ):
        if count:
            mean_confidence = confidence_sum / count
            accuracy = correct_sum / count
            ece += (count / total) * abs(mean_confidence - accuracy)
    return ece


@dataclass(frozen=True)
class InterventionPairObservation:
    """Outcome of changing conditions while holding the chemical pair fixed."""

    pair_id: str
    split_id: str
    control_reaction_id: str
    intervention_reaction_id: str
    reference_branch_changed: bool
    prediction_changed: bool
    control_correct: bool
    intervention_correct: bool
    intervened_reference_probability_before: float
    intervened_reference_probability_after: float
    intervention_confidence: float

    def validate(self) -> None:
        for name in (
            "pair_id",
            "split_id",
            "control_reaction_id",
            "intervention_reaction_id",
        ):
            _require_nonempty_string(getattr(self, name), name)
        if self.control_reaction_id == self.intervention_reaction_id:
            raise ValueError("control and intervention reaction IDs must differ")
        for name in (
            "reference_branch_changed",
            "prediction_changed",
            "control_correct",
            "intervention_correct",
        ):
            _require_bool(getattr(self, name), name)
        _require_probability(
            self.intervened_reference_probability_before,
            "intervened_reference_probability_before",
        )
        _require_probability(
            self.intervened_reference_probability_after,
            "intervened_reference_probability_after",
        )
        _require_probability(self.intervention_confidence, "intervention_confidence")


@dataclass(frozen=True)
class InterventionMetrics:
    n_pairs: int
    n_branch_changes: int
    both_correct_rate: float
    correct_branch_flip_rate: float | None
    prediction_switch_rate: float | None
    mean_reference_probability_shift: float | None
    confident_shortcut_failure_rate: float | None


def summarize_interventions(
    pairs: Sequence[InterventionPairObservation], *, confident_threshold: float = 0.8
) -> InterventionMetrics:
    """Summarize paired condition interventions.

    Branch-flip, switch, probability-shift, and confident-shortcut rates use
    only pairs whose reference branch actually changes.  A confident shortcut
    failure is an unchanged, wrong intervention prediction at or above the
    supplied confidence threshold.
    """

    if not pairs:
        raise ValueError("at least one intervention pair is required")
    checked_threshold = _require_probability(confident_threshold, "confident_threshold")
    pair_ids: set[str] = set()
    reaction_ids: set[str] = set()
    for pair in pairs:
        pair.validate()
        if pair.pair_id in pair_ids:
            raise ValueError(f"duplicate pair_id: {pair.pair_id}")
        pair_ids.add(pair.pair_id)
        for reaction_id in (pair.control_reaction_id, pair.intervention_reaction_id):
            if reaction_id in reaction_ids:
                raise ValueError(f"reaction_id appears in multiple pairs: {reaction_id}")
            reaction_ids.add(reaction_id)

    both_correct = sum(pair.control_correct and pair.intervention_correct for pair in pairs)
    changed = [pair for pair in pairs if pair.reference_branch_changed]
    n_changed = len(changed)
    if not changed:
        return InterventionMetrics(
            len(pairs),
            0,
            both_correct / len(pairs),
            None,
            None,
            None,
            None,
        )

    correct_flips = sum(
        pair.control_correct and pair.intervention_correct and pair.prediction_changed
        for pair in changed
    )
    switches = sum(pair.prediction_changed for pair in changed)
    probability_shift = sum(
        pair.intervened_reference_probability_after
        - pair.intervened_reference_probability_before
        for pair in changed
    )
    confident_shortcut_failures = sum(
        not pair.prediction_changed
        and not pair.intervention_correct
        and pair.intervention_confidence >= checked_threshold
        for pair in changed
    )
    return InterventionMetrics(
        len(pairs),
        n_changed,
        both_correct / len(pairs),
        correct_flips / n_changed,
        switches / n_changed,
        probability_shift / n_changed,
        confident_shortcut_failures / n_changed,
    )


def top_uncertain_jaccard(
    first: Mapping[str, float], second: Mapping[str, float], *, k: int
) -> float:
    """Compare tie-inclusive top-k uncertain sets with Jaccard overlap."""

    if set(first) != set(second):
        raise ValueError("score mappings must contain identical observation IDs")
    if not first:
        raise ValueError("at least one observation is required")
    if type(k) is not int or not 1 <= k <= len(first):
        raise ValueError("k must be an integer in [1, number of observations]")

    def tie_inclusive_top(scores: Mapping[str, float]) -> set[str]:
        checked = {
            observation_id: _require_finite(score, f"score for {observation_id}")
            for observation_id, score in scores.items()
        }
        threshold = sorted(checked.values(), reverse=True)[k - 1]
        return {
            observation_id
            for observation_id, score in checked.items()
            if score >= threshold
        }

    first_top = tie_inclusive_top(first)
    second_top = tie_inclusive_top(second)
    return len(first_top & second_top) / len(first_top | second_top)
