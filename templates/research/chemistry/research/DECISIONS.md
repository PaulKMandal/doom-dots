# Decision log

## D-001 — Separate task contracts

- Date: {{CREATED_DATE}}
- Decision: Forward endpoint, atom-mapped elementary-step prediction, unmapped pathway search, and single-step retrosynthesis have separate inputs, targets, metrics, and tables.
- Reason: FlowER is a forward mechanism/outcome model; putting it in a retro table without an inverse model would be a category error.

## D-002 — Controlled R-SMILES comparison

- Date: {{CREATED_DATE}}
- Decision: Treat R-SMILES as a representation and hold architecture, updates, data, seeds, and inference calls fixed against canonical/randomized SMILES.
- Revisit when: a method contribution beyond root alignment is explicitly implemented.

## D-003 — Dataset identity

- Date: {{CREATED_DATE}}
- Decision: “USPTO-50K” or “USPTO-Full” is never a sufficient identifier. Record source URL, processing revision, checksums, counts, mapper, and split checksum.

## D-004 — Uncertainty is a component-wise overlay

- Date: {{CREATED_DATE}}
- Decision: Record model/representation, predictive mechanism, score, and aggregation separately. Evaluate failure detection, OOD detection, selective prediction, calibration, and ambiguity in separate panels rather than creating one uncertainty leaderboard.
- Reason: a score that recognizes unfamiliar inputs need not recognize incorrect predictions, and aggregation can reverse rankings.

## D-005 — Validation-only calibration and input-only deployable OOD

- Date: {{CREATED_DATE}}
- Decision: Fit calibrators, score orientation, and thresholds on validation only. Transformation/mechanism novelty derived from products or annotations is analysis-only and cannot enter a deployable OOD detector.
- Reason: test/OOD label tuning would leak the answer and inflate shift performance.

## D-006 — Paired condition-intervention panel

- Date: {{CREATED_DATE}}
- Decision: Build 100 source-grounded pairs: approximately 40 endpoint-changing, 30 same-endpoint/different-mechanism, and 30 outcome-preserving controls. Hold out whole pairs and their scaffold/source/reaction-family groups. Use two blinded expert annotations plus adjudication.
- Reason: matched causal contrasts separate condition sensitivity from substrate memorization and serialization instability.
