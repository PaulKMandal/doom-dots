# Decision log

## D-001 — Task evidence, not arbitrary latent alignment

- Date: {{CREATED_DATE}}
- Decision: Every v1 expert exposes a calibrated head for one shared endpoint/ontology. Private auxiliary representations and tasks need not align.
- Reason: heterogeneous clinical modalities have no exact coordinate conversion analogous to equivalent diffusion parameterizations.

## D-002 — Sparse bridge is explicit

- Date: {{CREATED_DATE}}
- Decision: Sweep paired bridge fractions from zero to full; never describe the nonzero-pair system as zero-shot composition.

## D-003 — Symile-MIMIC before MRI/proteomics

- Date: {{CREATED_DATE}}
- Decision: Establish E0/E1 on CXR/ECG/labs with patient-disjoint splits before paying the access and cohort-construction cost of ADNI or UK Biobank.
