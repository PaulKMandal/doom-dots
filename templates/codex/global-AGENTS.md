# General working agreement

- Inspect the repository and current Git state before editing.
- Plan before broad, architectural, or experimentally consequential changes.
- Keep changes narrowly scoped to the requested task.
- Do not commit, merge, rebase, push, switch branches, or alter hidden Git refs unless the user explicitly requests it.
- Do not modify files outside the assigned worktree.
- Do not install system packages or access unrelated repositories, SSH keys, credential files, tokens, or secrets.
- Run relevant tests after code changes and distinguish a smoke test from a complete experiment.
- Report files changed, commands run, validation performed, and remaining risks.
- Do not claim success merely because a command created a nonempty file or process.
- Use the runner-mediated job request mechanism for authorized long-running work; never improvise detached jobs with tmux, nohup, shell backgrounding, systemd, or a scheduler.
