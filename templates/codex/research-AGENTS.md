# Research repository instructions

## Experimental integrity

- Existing result directories, checkpoints, frozen panels, candidate lists, splits, and reported artifacts are immutable unless the task explicitly authorizes replacing them.
- Do not retrain models or regenerate established artifacts merely to obtain a missing statistic.
- Preserve established random seeds, validation slices, thresholds, model identities, preprocessing, and control definitions.
- Never silently substitute a model, dataset, checkpoint, control, metric, or evaluation panel.
- Separate implementation changes, smoke validation, full experiment launch, and result interpretation.

## Validation and jobs

- Run the configured bounded test or smoke command before requesting a long job.
- For an explicitly authorized long job, use `"$CODEX_JOBCTL" request`; do not launch detached work directly.
- Include a descriptive job name, exact argv command, GPU selection when applicable, a completion marker when the repository provides one, and useful metadata such as experiment tag, model panel, seeds, or dataset split.
- Make runs resumable and idempotent where practical. Never overwrite a completed run directory.
- Treat the source snapshot, command, environment, GPUs, seeds, data split, and output location as part of the result.

## Interpretation

- Verify exit status, completion markers, expected rows/groups/shards, duplicate or malformed records, and zero-byte artifacts before interpreting metrics.
- State what the run supports and what it does not support.
- Do not launch, rerun, repair, delete, or mutate experiments during a read-only interpretation task.
