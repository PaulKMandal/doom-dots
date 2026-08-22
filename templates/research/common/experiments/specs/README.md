# Experiment specifications

Copy `research/EXPERIMENT_TEMPLATE.md` for each consequential experiment. The spec should be committed before launching the frozen job and referenced from its metadata. Use `scripts/codex_artifacts.py` as the output-contract example: evidence belongs in `$CODEX_RESULTS_DIR`, resumable state in `$CODEX_CHECKPOINTS_DIR`, and only a sentinel at `$CODEX_COMPLETION_MARKER`.

Every invoked experiment entry point must write `$CODEX_RESULTS_DIR/evidence-manifest.json` before marking completion. `evidence-manifest.schema.json` records the exact field names. The three identity fields are lowercase 64-character SHA-256 values; `expected_counts` and `observed_counts` must be nonempty, use identical keys, and contain nonnegative integers. Run `python scripts/codex_artifacts.py --smoke` under temporary managed paths to exercise the contract. A missing manifest makes the read-only post-run audit incomplete by design.
