from __future__ import annotations

from collections.abc import Iterable
import re


ATOM_MAP = re.compile(r":\d+\]")


def assert_group_disjoint(train: Iterable[str], test: Iterable[str], label: str) -> None:
    overlap = set(train) & set(test)
    if overlap:
        examples = ", ".join(sorted(overlap)[:5])
        raise ValueError(f"{label} leakage ({len(overlap)} groups): {examples}")


def assert_pairwise_group_disjoint(
    train: Iterable[str], validation: Iterable[str], test: Iterable[str], label: str
) -> None:
    assert_group_disjoint(train, validation, f"{label} train/validation")
    assert_group_disjoint(train, test, f"{label} train/test")
    assert_group_disjoint(validation, test, f"{label} validation/test")


def assert_no_retro_target_metadata(product_inputs: Iterable[str]) -> None:
    bad = [value for value in product_inputs if ATOM_MAP.search(value)]
    if bad:
        raise ValueError("retro product inputs appear to contain atom-map metadata")
