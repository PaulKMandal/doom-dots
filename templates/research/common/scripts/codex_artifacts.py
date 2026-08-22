#!/usr/bin/env python3
"""Write experiment evidence only through the sealed Codex job directories."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from typing import Mapping


def _safe_child(root: Path, relative: str) -> Path:
    value = PurePosixPath(relative)
    if value.is_absolute() or ".." in value.parts or not value.parts:
        raise ValueError("artifact path must remain below its managed directory")
    if root.is_symlink():
        raise ValueError("managed artifact directory cannot be a symlink")
    root.mkdir(parents=True, exist_ok=True)
    resolved_root = root.resolve()
    if resolved_root != root.absolute():
        raise ValueError("managed artifact directory cannot have symlink ancestors")
    current = root
    for part in value.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("artifact path cannot contain a symlink")
        if not current.resolve(strict=False).is_relative_to(resolved_root):
            raise ValueError("artifact path escapes its managed directory")
    return current


def write_result_json(relative: str, value: object) -> Path:
    root_value = os.environ.get("CODEX_RESULTS_DIR")
    if not root_value:
        raise RuntimeError("CODEX_RESULTS_DIR is required for managed experiments")
    target = _safe_child(Path(root_value), relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def write_evidence_manifest(
    *,
    dataset_manifest_sha256: str,
    split_manifest_sha256: str,
    membership_evidence_sha256: str,
    expected_counts: Mapping[str, int],
    observed_counts: Mapping[str, int],
    relative: str = "evidence-manifest.json",
) -> Path:
    """Write the identity/count contract required by the read-only run auditor."""
    hashes = {
        "dataset_manifest_sha256": dataset_manifest_sha256,
        "split_manifest_sha256": split_manifest_sha256,
        "membership_evidence_sha256": membership_evidence_sha256,
    }
    if any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in hashes.values()):
        raise ValueError("evidence identities must be lowercase SHA-256 values")
    expected = dict(expected_counts)
    observed = dict(observed_counts)
    for label, counts in (("expected_counts", expected), ("observed_counts", observed)):
        if (
            not counts
            or any(
                not isinstance(key, str)
                or not key
                or isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                for key, value in counts.items()
            )
        ):
            raise ValueError(f"{label} must contain nonnegative integer counts")
    if set(expected) != set(observed):
        raise ValueError("expected and observed count keys must match")
    return write_result_json(relative, {**hashes, "expected_counts": expected, "observed_counts": observed})


def mark_complete() -> Path:
    marker_value = os.environ.get("CODEX_COMPLETION_MARKER")
    if not marker_value:
        raise RuntimeError("CODEX_COMPLETION_MARKER is required")
    marker = Path(marker_value)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("complete\n", encoding="utf-8")
    return marker


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if not args.smoke:
        parser.error("only --smoke is supported; import the helpers in real launchers")
    write_result_json("contract-smoke.json", {"output_contract": "sealed-results-v1"})
    identities = {
        label: hashlib.sha256(label.encode("utf-8")).hexdigest()
        for label in ("dataset", "split", "membership")
    }
    write_evidence_manifest(
        dataset_manifest_sha256=identities["dataset"],
        split_manifest_sha256=identities["split"],
        membership_evidence_sha256=identities["membership"],
        expected_counts={"smoke_rows": 1},
        observed_counts={"smoke_rows": 1},
    )
    mark_complete()


if __name__ == "__main__":
    main()
