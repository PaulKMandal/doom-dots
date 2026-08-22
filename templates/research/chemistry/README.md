# {{PROJECT_NAME}}

Controlled benchmark of reaction representations, graph methods, and mechanistic constraints across four distinct tasks:

1. forward endpoint prediction: reactants/reagents to product multiset;
2. forward elementary-step prediction: one atom-mapped mechanistic state to the next state;
3. forward pathway search: unmapped initial reactants to a recorded endpoint through recursive steps;
4. single-step retrosynthesis: product to precursor multiset.

Multistep retrosynthetic route planning is deliberately deferred from phase 1. The current retro lane does not evaluate search trees, route diversity, route cost, solved-route rate, or termination at a pinned purchasable-building-block catalog; do not label its single-step results as a route-planning benchmark.

FlowER belongs in the forward-mechanism lane. R-SMILES (root-aligned SMILES) is a representation evaluated with a matched Transformer in forward and retro lanes. It is not treated as an independent architecture.

The first milestone is an evaluator contract on 100–500 reactions, not a full leaderboard. A method cannot enter the full matrix until its adapter passes canonicalization, split-leakage, candidate-deduplication, inference-budget, and artifact-completeness tests.

## Initial matrix

- Mechanism: FlowER publication code tag `2.0.0`, plus the study's recursively applied G2S and G2S+H comparators. G2S+H is Graph2SMILES trained on Kekulé structures with explicit hydrogens, not a separate architecture or upstream.
- Forward endpoint: matched canonical/R-SMILES Transformers and Graph2SMILES; add WLDN/MEGAN after phase 1.
- Retrosynthesis: matched canonical/R-SMILES Transformers, GLN, Graph2Edits; add MEGAN after phase 1.

Use isolated environments behind one prediction-record contract. Do not force legacy TensorFlow/Python stacks and current FlowER into one environment.

Primary sources and unresolved revisions live in `manifests/`. No dataset or model is runnable until its revision, checksum, provenance, and license fields are complete.

All tables keep scratch-trained, released-checkpoint reproduction, and local-adaptation lanes separate. Published Graph2SMILES tasks are endpoint prediction and single-step retro; its mechanism benchmark is a FlowER-study adaptation. Published R-SMILES tasks are forward endpoint and retro; any mechanism use must be labeled a new local adaptation.

## Frozen-run output contract

- Write tables, predictions, figures, machine-readable dataset/split identity, expected/observed counts, and the run card under `$CODEX_RESULTS_DIR`.
- Write resumable model state only under `$CODEX_CHECKPOINTS_DIR`.
- The configured worktree completion marker is marker-only; never place evidence beside it.
- An audit is incomplete unless the sealed results include dataset and split hashes, reaction IDs or sufficient nonidentifying membership evidence, counts, adapter/model identity, and inference-budget totals.
