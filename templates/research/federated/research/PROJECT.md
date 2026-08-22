# {{PROJECT_NAME}} research charter

- Initialized: {{CREATED_DATE}}
- Primary question: Can independently versioned unimodal experts recover robust multimodal predictive gain through calibrated task-evidence composition with little paired data and no coordinated training rounds?
- Primary contribution: a no-round interoperability contract plus a model-evolution benchmark for missing, stale, and architecture-swapped experts.
- Initial dataset: Symile-MIMIC with CXR, ECG, and labs; fully paired patient-disjoint test subjects, disjoint unimodal training pools, and a controlled paired bridge sweep.
- Initial endpoint: mortality after a 72-hour admission landmark among patients alive and still admitted at that landmark; this prevents the 24–72-hour CXR window from using post-outcome information.
- Primary unit: patient admission/event, with patient-level resampling.
- Privacy claim: data locality only until leakage/privacy mechanisms are implemented and audited.
- Symile role: feasibility with patient-bootstrap uncertainty. Its retrieval-expanded test table must be deduplicated to unique admissions and is too small to establish the two-dataset claim alone.
- Go criterion: with at most 5% paired bridge subjects, recover at least half the gap between the strongest unimodal expert and paired centralized oracle on two informative datasets, while retaining at least 90% of static performance at four-version staleness.
- Oracle-gap guard: always report absolute AUROC gain over the best unimodal expert. Compute the recovery fraction only when the paired centralized oracle exceeds that expert by at least 0.01 AUROC; otherwise classify that dataset as non-informative for the recovery-fraction claim, never as a pass or failure.
- Primary kill criterion: tuned calibrated late fusion/evidence averaging matches the proposal within one absolute AUROC point with similar calibration across at least two datasets.

## Core evidence contract

For expert `c`, version `v`, class `k`, calibrated posterior `p`, and local training prior `pi_c`:

`e[c,v,k](x) = log p_tilde(Y=k | x) - log pi_c[k]`.

Target inference adds the target log prior, available expert evidence, and an optional residual regularized toward zero. The plain sum is justified only under calibrated posteriors, label shift, a shared ontology, and conditional independence given the endpoint. E1 measures how little paired bridge data is needed when those assumptions fail.

## Required negative controls

- shuffle modalities across subjects;
- shuffle within label, preserving class marginals but destroying subject-specific synergy;
- availability-mask-only predictor;
- uncalibrated versus calibrated and prior-corrected evidence;
- random/untrained router;
- frozen experts while changing only fusion;
- paired versus unpaired bridge cohorts at equal sample counts.

If within-label subject shuffling leaves the claimed gain unchanged, the system has not shown subject-level multimodal synergy.

All run evidence belongs under `$CODEX_RESULTS_DIR`, resumable states under `$CODEX_CHECKPOINTS_DIR`, and only a sentinel at the configured worktree completion-marker path. The sealed evidence manifest must include the unique-admission cohort flow, input allowlist hash, split/membership hashes, expert contracts, expected/observed counts, and missingness pattern counts.
