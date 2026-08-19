# General working agreement

- Inspect the repository and current Git state before editing.
- Plan before broad, architectural, or experimentally consequential changes.
- Keep changes narrowly scoped to the requested task.
- In a codex-remote managed interactive worktree, create small coherent commits after each validated logical unit so the laptop can pull live checkpoints. Do not amend, rebase, reset, or otherwise rewrite commits created in that session; the laptop may publish them at any time.
- Outside that managed interactive mode, do not commit unless the user explicitly requests it. Never merge, push, switch branches, or alter hidden Git refs.
- Do not modify files outside the assigned worktree.
- Do not install system packages or access unrelated repositories, SSH keys, credential files, tokens, or secrets.
- Run relevant tests after code changes and distinguish a smoke test from a complete experiment.
- Report files changed, commands run, validation performed, and remaining risks.
- Do not claim success merely because a command created a nonempty file or process.
- Use the runner-mediated job request mechanism for authorized long-running work; never improvise detached jobs with tmux, nohup, shell backgrounding, systemd, or a scheduler. Commit the exact source first; the trusted broker freezes it and launches the job while the interactive session remains available.
