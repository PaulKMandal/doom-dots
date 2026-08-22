# {{PROJECT_NAME}}

Benchmark for **versioned decentralized multimodal inference**: independently and asynchronously trained modality experts expose calibrated evidence for one shared endpoint; evidence is composed for the same subject/event at inference without global training rounds, parameter exchange, or activation synchronization. A low-capacity residual/router may use a sparse paired bridge cohort to model conditional dependence.

This is deliberately not framed as discovering an arbitrary shared latent. Unlike heterogeneous decentralized diffusion, MRI, ECG, labs, and proteomics do not have an exact algebraic conversion into a common generative coordinate. The defensible common object is calibrated task evidence under a shared endpoint and label ontology.

The first milestone is Symile-MIMIC E0–E1: calibrated baselines and a paired-bridge sweep. Raw MRI/proteomics should not begin unless the proposed composition recovers meaningful multimodal gain with at most 5% paired bridge data.

The primary recovery fraction has a preregistered denominator guard: the paired centralized oracle must improve on the strongest unimodal expert by at least 0.01 AUROC. Below that threshold, the dataset is non-informative for the fraction claim rather than a pass or failure. Absolute AUROC gain over the strongest unimodal expert is always reported.

Symile-MIMIC is a feasibility dataset here. Its official test CSV is retrieval-expanded, so adapters must deduplicate to one admission, preserve patient-disjoint membership, use an explicit feature allowlist, and condition the mortality estimand on survival/admission through the 72-hour CXR landmark. A second dataset is still an explicit scaffold gap: `configs/datasets/second_dataset_candidates.yaml` recommends eICU-CRD for low-cost external feasibility and UK Biobank for high-cost confirmation, but neither is selected or executable yet. The preregistered two-dataset go/kill rule cannot be applied until that decision is recorded and its manifest is pinned.

## Boundaries

- Zero paired training data cannot identify arbitrary cross-modal synergy without explicit structural assumptions.
- Vertical modality ownership for the same patient is not ordinary horizontal federated learning.
- “Data-local” is not a privacy guarantee; logits/evidence can leak unless DP, secure aggregation, or cryptography is implemented and measured.
- A model version is compatible only when its evidence contract, ontology, priors, and calibration validation pass.

## Frozen-run output contract

Write all predictions, cohort flow, split/membership hashes, expert contracts, metrics, uncertainty, figures, and run cards under `$CODEX_RESULTS_DIR`; write resumable states only under `$CODEX_CHECKPOINTS_DIR`. The worktree completion marker is a sentinel only. Evidence beside the marker is not sealed or exported and therefore does not count.
