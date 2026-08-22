# Uncertainty and OOD variation study

## Research question

Does a reaction model know when the chemistry, rather than merely its serialization, is unfamiliar? The study tests whether uncertainty rankings and error-detection performance change across task, representation, model family, aggregation rule, and distribution shift.

This is an overlay on the four task contracts, not a fifth task and not a single pooled leaderboard. Forward endpoint, elementary-step, pathway, and single-step retro results stay in separate panels.

## ValUES-to-chemistry decomposition

The study adapts the component-wise design of ValUES instead of treating an uncertainty method as one indivisible label.

| Component | Chemistry factor | Required comparisons |
|---|---|---|
| C0 | task, representation, and backbone | canonical/randomized/R-SMILES Transformer; graph endpoint model; FlowER and its graph comparators in mechanism panels |
| C1 | predictive mechanism | deterministic decoder, deep ensemble, randomized-SMILES test-time augmentation, and stochastic candidate generation |
| C2 | score | calibrated probability of correctness, sequence NLL, beam margin, candidate-set entropy, ensemble disagreement, and structured validity signals |
| C3 | aggregation | sum, length-normalized mean, maximum, top-quantile mean, and pathway step aggregation |

Aleatoric and epistemic labels are hypotheses to test, not ground truth attached to a method. Randomized-SMILES augmentation must not be called aleatoric or epistemic merely by convention.

## Separate applications

1. **Failure detection:** can uncertainty rank chemically incorrect predictions above correct predictions?
2. **OOD detection:** can an input-only score identify a predeclared shift without using products, atom maps, reaction classes, or test labels?
3. **Selective prediction:** does abstention lower chemical error at useful coverage?
4. **Calibration:** does a confidence value predict equivalence-aware correctness on held-out reactions?
5. **Ambiguity modeling:** does candidate mass cover multiple expert-accepted products or mechanisms rather than penalizing all alternatives to the recorded answer?

Active learning is a later extension. It enters only with a fixed labeling and training-compute budget; uncertainty-only pool ranking is not an active-learning result.

OOD detection and failure detection are intentionally distinct. An unfamiliar reaction may still be predicted correctly, and an in-distribution reaction may be confidently wrong.

## Shift panels

Each score is evaluated on IID plus individually named shifts. Near and far shifts are not pooled.

- patent-temporal and patent-family/source shifts;
- transformation/edit-pattern-disjoint shifts;
- product-core or reactant-scaffold-disjoint shifts;
- held-out reaction-family shifts;
- condition/reagent novelty and mechanism-branch shifts;
- atom-map or serialization perturbations as robustness diagnostics, never as chemical OOD.

Deployable OOD scores may use only information available at prediction time. Target-derived transformation and mechanism novelty are analysis strata, not input features.

## Score and aggregation registry

Every reported score records its direction, raw units, calibration split, calibration artifact hash, candidate-deduplication rule, and aggregation. Required score families are:

- native and length-normalized sequence log likelihood;
- top-1/top-2 margin;
- token or graph-action mean, maximum, and top-quantile NLL;
- entropy over canonicalized, deduplicated retained candidates;
- ensemble predictive entropy and disagreement;
- disagreement across 16 semantically equivalent SMILES encodings;
- pathway mean, maximum, and accumulated step uncertainty;
- conservation, valence, sanitization, and mechanism-validity flags as auxiliary signals.

A distribution normalized only over a retained beam is named `retained_candidate_entropy`; it is not called full predictive entropy. Generated and retained candidate counts and model-forward counts accompany it.

Summed uncertainty is always paired with length-normalized and maximum/top-quantile variants. Otherwise SMILES length, number of atoms, or pathway length can determine the apparent uncertainty ranking. Raw token entropy is never compared directly across different tokenizers or output spaces.

## Calibration and budgets

- Fit all temperatures, calibrators, score orientations, and operating thresholds on a held-out validation split only.
- Keep native and post-hoc calibrated results separate.
- Use the same training split for every member of a deep ensemble. Cross-validation disagreement is not an epistemic score because members saw different data.
- Deduplicate chemically equivalent candidates before confidence and top-k calculations.
- Match 32 generated proposals and the declared model-forward/state-expansion budget for the primary comparison; add budget curves rather than silently granting one method more calls.

## Condition-intervention contrast set

Construct 100 expert-audited matched pairs (200 reactions). Pair members share the intended substrate/scaffold context but differ in a condition or reagent intervention. Entire pairs, patent/source families, and scaffold groups remain in one held-out partition.

Target composition:

- about 40 endpoint-changing pairs;
- about 30 same-endpoint, different-mechanism pairs;
- about 30 outcome-preserving controls.

Cover several families rather than making a one-reaction-family benchmark: substitution/elimination competition, regio- and chemoselectivity, stereochemical branch choice, redox state, protecting-group behavior, and catalyst/solvent/base effects where source evidence supports the contrast. Two blinded chemistry annotations plus adjudication record accepted products/mechanism classes and whether the intervention is genuinely decisive.

Primary pair metrics are both-members correct, correct endpoint or mechanism switch, probability shift toward the intervened reference, confident shortcut failure, and an outcome-preserving invariance control. Compare chemical sensitivity with variation across the 16 equivalent SMILES encodings. Retro receives only the serialization/calibration overlay; a forward-condition intervention is not forced into the retro task.

## Metrics and inference

Report per task and per shift:

- Brier score, NLL, calibration slope/intercept, and reliability tables;
- failure- and OOD-detection AUROC/AUPRC;
- AURC, excess AURC, risk at 80% and 90% coverage, and confident-wrong rate at a validation-fixed threshold;
- Spearman/Kendall rank agreement and top-1/5/10% uncertain-set Jaccard overlap across scores, representations, models, and seeds;
- equivalence-aware top-k coverage and ambiguity-set mass;
- the paired intervention metrics above.

The statistical unit is a reaction connected component, overall mechanism sequence, or intervention pair—not a beam, token, sampled candidate, elementary step from the same pathway, or seed. Use 10,000 paired or hierarchical bootstrap replicates clustered by patent family/reaction family as applicable. Treat seeds as repeated measurements. Report effect sizes and confidence intervals; control false discovery within each task/application family and test method-by-shift interactions and rank reversals explicitly.

Use Holm correction for the small preregistered hypothesis family and Benjamini-Hochberg within clearly labeled exploratory task/application families.

## Required artifacts

- exact dataset, split, intervention-set, and calibrator hashes;
- one row per reaction/model/score/aggregation with correctness and shift labels;
- deduplicated candidate records plus generation/model-call budgets;
- reliability, risk-coverage, ranking-overlap, interaction, and paired-intervention tables;
- failure slices retaining correct-OOD, wrong-ID, invalid, ambiguous, and confident-shortcut cases separately.

The first useful result is the phase-U0 audit on a 100-500 reaction slice plus the 100 intervention pairs. It should reveal where uncertainty rankings agree, reverse, or merely track sequence/pathway length before scaling the full model matrix.
