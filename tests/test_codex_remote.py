from __future__ import annotations

import argparse
import importlib.util
from importlib.machinery import SourceFileLoader
import io
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import tarfile
import tempfile
import threading
import time
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "bin" / "codex-remote"
loader = SourceFileLoader("codex_remote_backend", str(BACKEND))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec is not None
cr = importlib.util.module_from_spec(spec)
loader.exec_module(cr)


def command(*args: str | os.PathLike[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [os.fspath(arg) for arg in args],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"command failed ({result.returncode}): {' '.join(map(os.fspath, args))}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return command("git", "-C", root, *args, check=check)


def configure_repo(root: Path) -> None:
    git(root, "config", "user.name", "Codex Remote Test")
    git(root, "config", "user.email", "codex-remote-test@example.invalid")
    git(root, "config", "commit.gpgsign", "false")


def init_repo(root: Path, files: dict[str, str] | None = None) -> None:
    root.mkdir(parents=True)
    initial = command("git", "init", "-b", "main", root, check=False)
    if initial.returncode != 0:
        command("git", "init", root)
        git(root, "checkout", "-b", "main")
    configure_repo(root)
    for relative, content in (files or {"tracked.txt": "one\ntwo\nthree\nfour\n"}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-m", "initial")


def commit_all(root: Path, message: str) -> str:
    git(root, "add", "-A")
    git(root, "commit", "-m", message)
    return git(root, "rev-parse", "HEAD").stdout.strip()


def visible_state(root: Path) -> dict[str, str]:
    return {
        "head": git(root, "rev-parse", "HEAD").stdout,
        "branch": git(root, "symbolic-ref", "--quiet", "--short", "HEAD").stdout,
        "index": git(root, "write-tree").stdout,
        "status": git(root, "status", "--porcelain=v1", "--untracked-files=all").stdout,
        "staged": git(root, "diff", "--cached", "--binary").stdout,
    }


class RepositoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="codex-remote-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "repo"
        init_repo(self.root)

    def add_detached_worktree(self, commit: str, name: str) -> Path:
        path = self.base / name
        git(self.root, "worktree", "add", "--detach", str(path), commit)
        configure_repo(path)
        self.addCleanup(lambda: cr.remove_worktree(self.root, path) if path.exists() else None)
        return path


class SnapshotTests(RepositoryTestCase):
    def test_hidden_snapshot_preserves_visible_git_state_and_file_modes(self) -> None:
        tracked = self.root / "tracked.txt"
        tracked.write_text("staged\ntwo\nthree\nfour\n", encoding="utf-8")
        git(self.root, "add", "tracked.txt")
        tracked.write_text("staged\nunstaged\nthree\nfour\n", encoding="utf-8")

        script = self.root / "script.sh"
        script.write_text("#!/bin/sh\necho remote\n", encoding="utf-8")
        script.chmod(0o755)
        (self.root / "script-link").symlink_to("script.sh")

        cr.ensure_safe_untracked(self.root, 1024 * 1024)
        before = visible_state(self.root)
        snapshot = cr.create_hidden_snapshot(
            self.root,
            "refs/codex/test/input/snapshot",
            "test hidden snapshot",
        )
        self.assertEqual(before, visible_state(self.root))

        materialized = self.add_detached_worktree(snapshot["commit"], "snapshot-worktree")
        self.assertEqual(
            (materialized / "tracked.txt").read_text(encoding="utf-8"),
            "staged\nunstaged\nthree\nfour\n",
        )
        self.assertTrue((materialized / "script.sh").stat().st_mode & stat.S_IXUSR)
        self.assertTrue((materialized / "script-link").is_symlink())
        self.assertEqual(os.readlink(materialized / "script-link"), "script.sh")

    def test_tracked_only_hidden_snapshot_excludes_all_untracked_paths(self) -> None:
        tracked = self.root / "tracked.txt"
        tracked.write_text("one\nstaged\nthree\nfour\n", encoding="utf-8")
        git(self.root, "add", "tracked.txt")
        tracked.write_text("one\nstaged\nunstaged\nfour\n", encoding="utf-8")

        untracked = {
            ".env": "TOKEN=local-only\n",
            "codex_remote_smoke_test.txt": "local smoke output\n",
            "reports/bootstrap-summary.md": "generated locally\n",
        }
        for relative, content in untracked.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        before = visible_state(self.root)
        snapshot = cr.create_hidden_snapshot(
            self.root,
            "refs/codex/test/input/tracked-only",
            "tracked-only interactive snapshot",
            include_untracked=False,
        )
        self.assertEqual(before, visible_state(self.root))

        materialized = self.add_detached_worktree(
            snapshot["commit"], "tracked-only-snapshot"
        )
        self.assertEqual(
            (materialized / "tracked.txt").read_text(encoding="utf-8"),
            "one\nstaged\nunstaged\nfour\n",
        )
        for relative in untracked:
            self.assertFalse((materialized / relative).exists(), relative)

    def test_untracked_safety_detects_secrets_generated_files_large_files_and_escaping_links(self) -> None:
        (self.root / ".env").write_text("TOKEN=x\n", encoding="utf-8")
        (self.root / ".cache").mkdir()
        (self.root / ".cache" / "artifact").write_text("x", encoding="utf-8")
        (self.root / "large.bin").write_bytes(b"x" * 32)
        (self.root / "escape-link").symlink_to("../outside")

        unsafe = cr.inspect_untracked(self.root, 16)
        reasons = {item["path"]: item["reason"] for item in unsafe}
        self.assertIn(".env", reasons)
        self.assertIn(".cache/artifact", reasons)
        self.assertIn("large.bin", reasons)
        self.assertIn("escape-link", reasons)
        self.assertTrue(cr.path_is_generated(".pytest_cache/data"))
        self.assertTrue(cr.path_is_generated("src/__pycache__/module.pyc"))
        self.assertTrue(cr.path_is_generated("result-server"))
        self.assertTrue(cr.path_is_secret(".env.staging"))
        self.assertTrue(cr.path_is_secret("config/credentials.yaml"))
        self.assertTrue(cr.safe_relative_symlink("docs/current", "../README.md"))
        self.assertFalse(cr.safe_relative_symlink("current", "../outside"))
        with self.assertRaises(cr.CodexRemoteError) as caught:
            cr.ensure_safe_untracked(self.root, 16)
        self.assertEqual(caught.exception.code, "UNSAFE_UNTRACKED")


class ResultSafetyTests(RepositoryTestCase):
    def test_committed_codex_result_is_inspected_not_only_dirty_files(self) -> None:
        input_sha = git(self.root, "rev-parse", "HEAD").stdout.strip()
        result_tree = self.add_detached_worktree(input_sha, "unsafe-result")
        (result_tree / ".env").write_text("SECRET=x\n", encoding="utf-8")
        (result_tree / "outputs").mkdir()
        (result_tree / "outputs" / "run.txt").write_text("generated\n", encoding="utf-8")
        (result_tree / "large.bin").write_bytes(b"x" * 64)
        result_sha = commit_all(result_tree, "unsafe committed result")

        unsafe = cr.inspect_result_delta(result_tree, input_sha, result_sha, 32)
        reasons = {item["path"]: item["reason"] for item in unsafe}
        self.assertIn(".env", reasons)
        self.assertIn("outputs/run.txt", reasons)
        self.assertIn("large.bin", reasons)
        with self.assertRaises(cr.CodexRemoteError) as caught:
            cr.ensure_safe_result_delta(result_tree, input_sha, result_sha, 32)
        self.assertEqual(caught.exception.code, "UNSAFE_RESULT")

    def test_unsafe_file_committed_then_deleted_is_still_blocked(self) -> None:
        input_sha = git(self.root, "rev-parse", "HEAD").stdout.strip()
        result_tree = self.add_detached_worktree(input_sha, "unsafe-history")
        (result_tree / ".env").write_text("SECRET=x\n", encoding="utf-8")
        commit_all(result_tree, "temporarily commit secret")
        (result_tree / ".env").unlink()
        (result_tree / "tracked.txt").write_text(
            "one\ntwo\nlegitimate\nfour\n",
            encoding="utf-8",
        )
        result_sha = commit_all(result_tree, "remove secret and keep source change")

        final_paths = cr.result_changed_paths(result_tree, input_sha, result_sha)
        self.assertNotIn(".env", final_paths)
        unsafe = cr.inspect_result_delta(result_tree, input_sha, result_sha, 1024)
        self.assertIn(".env", {item["path"] for item in unsafe})
        with self.assertRaises(cr.CodexRemoteError) as caught:
            cr.ensure_safe_result_delta(result_tree, input_sha, result_sha, 1024)
        self.assertEqual(caught.exception.code, "UNSAFE_RESULT")


class IntegrationTests(RepositoryTestCase):
    def make_result(self, input_sha: str, mutate, name: str = "remote-result") -> str:
        tree = self.add_detached_worktree(input_sha, name)
        mutate(tree)
        return commit_all(tree, "Codex result")

    def test_nonoverlapping_result_applies_unstaged_without_changing_head_or_index(self) -> None:
        tracked = self.root / "tracked.txt"
        lines = [f"line-{index}" for index in range(1, 21)]
        tracked.write_text("\n".join(lines) + "\n", encoding="utf-8")
        git(self.root, "add", "tracked.txt")
        lines[0] = "staged"
        tracked.write_text("\n".join(lines) + "\n", encoding="utf-8")
        git(self.root, "add", "tracked.txt")
        lines[2] = "unstaged"
        tracked.write_text("\n".join(lines) + "\n", encoding="utf-8")
        input_snapshot = cr.create_hidden_snapshot(
            self.root, "refs/codex/test/input/nonoverlap", "input"
        )

        def codex_changes(tree: Path) -> None:
            codex_lines = (tree / "tracked.txt").read_text(encoding="utf-8").splitlines()
            codex_lines[9] = "codex"
            (tree / "tracked.txt").write_text("\n".join(codex_lines) + "\n", encoding="utf-8")
            (tree / "new-code.py").write_text("print('codex')\n", encoding="utf-8")

        result_sha = self.make_result(input_snapshot["commit"], codex_changes)
        lines[17] = "local-after"
        tracked.write_text("\n".join(lines) + "\n", encoding="utf-8")
        before = visible_state(self.root)
        state_dir = self.base / "state"

        result = cr.integrate_result_into_worktree(
            self.root,
            "test-project",
            "task-nonoverlap",
            input_snapshot["commit"],
            result_sha,
            state_dir=state_dir,
        )

        after = visible_state(self.root)
        self.assertEqual(before["head"], after["head"])
        self.assertEqual(before["branch"], after["branch"])
        self.assertEqual(before["index"], after["index"])
        self.assertEqual(before["staged"], after["staged"])
        expected_lines = list(lines)
        expected_lines[9] = "codex"
        self.assertEqual(
            tracked.read_text(encoding="utf-8"),
            "\n".join(expected_lines) + "\n",
        )
        self.assertEqual((self.root / "new-code.py").read_text(encoding="utf-8"), "print('codex')\n")
        self.assertIn("codex", git(self.root, "diff", "--", "tracked.txt").stdout)
        self.assertFalse(Path(result["integration_path"]).exists())
        changed = {item["path"] for item in result["changed_files"]}
        self.assertEqual(changed, {"tracked.txt", "new-code.py"})

    def test_same_line_conflict_preserves_canonical_checkout(self) -> None:
        input_snapshot = cr.create_hidden_snapshot(
            self.root, "refs/codex/test/input/conflict", "input"
        )

        def codex_changes(tree: Path) -> None:
            (tree / "tracked.txt").write_text("one\nCODEX\nthree\nfour\n", encoding="utf-8")

        result_sha = self.make_result(input_snapshot["commit"], codex_changes, "conflict-result")
        (self.root / "tracked.txt").write_text("one\nLOCAL\nthree\nfour\n", encoding="utf-8")
        before = visible_state(self.root)
        before_content = (self.root / "tracked.txt").read_bytes()
        state_dir = self.base / "conflict-state"

        with self.assertRaises(cr.CodexRemoteError) as caught:
            cr.integrate_result_into_worktree(
                self.root,
                "test-project",
                "task-conflict",
                input_snapshot["commit"],
                result_sha,
                state_dir=state_dir,
            )
        self.assertEqual(caught.exception.code, "INTEGRATION_CONFLICT")
        self.assertEqual(before, visible_state(self.root))
        self.assertEqual(before_content, (self.root / "tracked.txt").read_bytes())
        conflict_path = Path(caught.exception.details["conflict_path"])
        self.assertTrue(conflict_path.exists())
        self.assertTrue(git(conflict_path, "ls-files", "-u").stdout.strip())
        cr.remove_worktree(self.root, conflict_path)


    def test_resolved_conflict_imports_when_apply_is_retried(self) -> None:
        input_snapshot = cr.create_hidden_snapshot(
            self.root, "refs/codex/test/input/resolved-conflict", "input"
        )

        def codex_changes(tree: Path) -> None:
            (tree / "tracked.txt").write_text(
                "one\nCODEX\nthree\nfour\n", encoding="utf-8"
            )

        result_sha = self.make_result(
            input_snapshot["commit"], codex_changes, "resolved-conflict-result"
        )
        (self.root / "tracked.txt").write_text(
            "one\nLOCAL\nthree\nfour\n", encoding="utf-8"
        )
        before = visible_state(self.root)
        state_dir = self.base / "resolved-conflict-state"

        with self.assertRaises(cr.CodexRemoteError) as caught:
            cr.integrate_result_into_worktree(
                self.root,
                "test-project",
                "task-resolved-conflict",
                input_snapshot["commit"],
                result_sha,
                state_dir=state_dir,
            )
        self.assertEqual(caught.exception.code, "INTEGRATION_CONFLICT")
        conflict_path = Path(caught.exception.details["conflict_path"])
        (conflict_path / "tracked.txt").write_text(
            "one\nLOCAL+CODEX\nthree\nfour\n", encoding="utf-8"
        )
        git(conflict_path, "add", "tracked.txt")
        git(conflict_path, "-c", "core.editor=true", "rebase", "--continue")

        result = cr.integrate_result_into_worktree(
            self.root,
            "test-project",
            "task-resolved-conflict",
            input_snapshot["commit"],
            result_sha,
            state_dir=state_dir,
        )

        after = visible_state(self.root)
        self.assertEqual(before["head"], after["head"])
        self.assertEqual(before["branch"], after["branch"])
        self.assertEqual(before["index"], after["index"])
        self.assertEqual(
            (self.root / "tracked.txt").read_text(encoding="utf-8"),
            "one\nLOCAL+CODEX\nthree\nfour\n",
        )
        self.assertFalse(conflict_path.exists())
        self.assertFalse((state_dir / "integration-conflict.json").exists())
        self.assertEqual({item["path"] for item in result["changed_files"]}, {"tracked.txt"})

    def test_local_backup_branch_preserves_later_work_and_restores_task_input(self) -> None:
        tracked = self.root / "tracked.txt"
        tracked.write_text("STAGED\ntwo\nthree\nfour\n", encoding="utf-8")
        git(self.root, "add", "tracked.txt")
        tracked.write_text("STAGED\nUNSTAGED\nthree\nfour\n", encoding="utf-8")
        (self.root / "input-untracked.txt").write_text("input\n", encoding="utf-8")
        input_snapshot = cr.create_hidden_snapshot(
            self.root, "refs/codex/test/input/backup", "input"
        )
        task = {
            "task_id": "task-backup",
            "local_branch": "main",
            "local_head": input_snapshot["head"],
            "input_tree": input_snapshot["tree"],
            "input_index_tree": input_snapshot["index_tree"],
        }
        local = dict(task)

        git(self.root, "add", "-A")
        git(self.root, "commit", "-m", "local commits after task start")
        (self.root / "tracked.txt").write_text(
            "LOCAL-COMMIT\nLOCAL-WIP\nthree\nfour\n", encoding="utf-8"
        )
        (self.root / "later-untracked.txt").write_text("later wip\n", encoding="utf-8")
        before_head = git(self.root, "rev-parse", "HEAD").stdout.strip()
        before_tree = cr.snapshot_tree_only(self.root)
        state_dir = self.base / "backup-state"

        recovery = cr.preserve_local_state_on_branch(
            self.root,
            "test-project",
            task,
            local,
            input_snapshot["commit"],
            max_untracked_bytes=1024 * 1024,
            state_dir=state_dir,
        )

        branch = recovery["backup_branch"]
        self.assertRegex(branch, r"^main-local-\d{8}T\d{6}Z")
        self.assertEqual(
            git(self.root, "rev-parse", f"{branch}^{{tree}}").stdout.strip(),
            before_tree,
        )
        self.assertEqual(
            git(self.root, "rev-parse", f"{branch}^").stdout.strip(),
            before_head,
        )
        self.assertEqual(
            git(self.root, "show", f"{branch}:later-untracked.txt").stdout,
            "later wip\n",
        )
        self.assertEqual(current := cr.current_head(self.root), input_snapshot["head"])
        self.assertEqual(cr.index_tree(self.root), input_snapshot["index_tree"])
        self.assertEqual(cr.snapshot_tree_only(self.root), input_snapshot["tree"])
        self.assertEqual(current, task["local_head"])
        self.assertTrue((state_dir / "local-backup.json").is_file())

    def test_requested_backup_push_failure_leaves_canonical_checkout_unchanged(self) -> None:
        input_snapshot = cr.create_hidden_snapshot(
            self.root, "refs/codex/test/input/push-failure", "input"
        )
        task = {
            "task_id": "task-push-failure",
            "local_branch": "main",
            "local_head": input_snapshot["head"],
            "input_tree": input_snapshot["tree"],
            "input_index_tree": input_snapshot["index_tree"],
        }
        (self.root / "tracked.txt").write_text(
            "one\nLOCAL\nthree\nfour\n", encoding="utf-8"
        )
        before = visible_state(self.root)
        state_dir = self.base / "push-failure-state"

        with self.assertRaises(cr.CodexRemoteError) as caught:
            cr.preserve_local_state_on_branch(
                self.root,
                "test-project",
                task,
                task,
                input_snapshot["commit"],
                max_untracked_bytes=1024 * 1024,
                push_backup=True,
                backup_remote="missing-remote",
                state_dir=state_dir,
            )

        self.assertEqual(caught.exception.code, "BACKUP_PUSH_FAILED")
        self.assertEqual(before, visible_state(self.root))
        branches = git(
            self.root,
            "for-each-ref",
            "--format=%(refname:short)",
            "refs/heads/main-local-*",
        ).stdout.splitlines()
        self.assertEqual(len(branches), 1)


class LiveCheckpointTests(RepositoryTestCase):
    def make_interactive_server_task(
        self, home: Path, *, project_id: str = "checkpoint-project", task_id: str = "task-live"
    ) -> tuple[dict[str, Path], dict[str, object], Path]:
        paths = cr.ensure_server_layout(project_id)
        input_sha = git(self.root, "rev-parse", "HEAD").stdout.strip()
        input_ref = f"refs/codex/{project_id}/input/{task_id}"
        git(self.root, "push", str(paths["broker"]), f"HEAD:{input_ref}")
        worktree = paths["worktrees"] / task_id
        command(
            "git",
            "--git-dir",
            paths["broker"],
            "worktree",
            "add",
            "--detach",
            worktree,
            input_sha,
        )
        configure_repo(worktree)
        state_dir = paths["project_state"] / task_id
        state_dir.mkdir(parents=True, exist_ok=True)
        task: dict[str, object] = {
            "schema_version": cr.SCHEMA_VERSION,
            "project_id": project_id,
            "project_name": "checkpoint",
            "task_id": task_id,
            "state": "RUNNING",
            "execution_mode": "interactive",
            "input_ref": input_ref,
            "input_sha": input_sha,
            "local_head": input_sha,
            "local_branch": "main",
            "broker": str(paths["broker"]),
            "worktree": str(worktree),
            "state_dir": str(state_dir),
            "max_untracked_bytes": 1024 * 1024,
            "job_policy": "launch",
            "test_cmd": "python -m unittest",
            "tools": {
                "bash": shutil.which("bash"),
                "git": shutil.which("git"),
                "tmux": shutil.which("true"),
                "python3": shutil.which("python3"),
            },
        }
        cr.save_server_task(paths, task)
        return paths, task, worktree

    def test_live_checkpoint_publishes_commits_and_rejects_history_rewrite(self) -> None:
        home = self.base / "checkpoint-home"
        home.mkdir()
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            paths, task, worktree = self.make_interactive_server_task(home)
            (worktree / "tracked.txt").write_text(
                "one\ncheckpoint-one\nthree\nfour\n", encoding="utf-8"
            )
            first = commit_all(worktree, "checkpoint one")
            (worktree / "checkpoint.py").write_text("VALUE = 2\n", encoding="utf-8")
            second = commit_all(worktree, "checkpoint two")

            checkpoint = cr.publish_task_checkpoint(paths, task)
            self.assertEqual(checkpoint["sha"], second)
            self.assertEqual(checkpoint["commit_count"], 2)
            self.assertFalse(checkpoint["dirty"])
            self.assertEqual(
                command(
                    "git",
                    "--git-dir",
                    paths["broker"],
                    "rev-parse",
                    checkpoint["ref"],
                ).stdout.strip(),
                second,
            )

            git(worktree, "reset", "--hard", first)
            (worktree / "checkpoint.py").write_text("VALUE = 3\n", encoding="utf-8")
            commit_all(worktree, "rewritten checkpoint two")
            with self.assertRaises(cr.CodexRemoteError) as caught:
                cr.publish_task_checkpoint(paths, task)
            self.assertEqual(caught.exception.code, "CHECKPOINT_HISTORY_REWRITTEN")

    def test_interactive_result_preserves_codex_commit_chain(self) -> None:
        home = self.base / "result-home"
        home.mkdir()
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            paths, task, worktree = self.make_interactive_server_task(home)
            (worktree / "tracked.txt").write_text(
                "one\nfirst\nthree\nfour\n", encoding="utf-8"
            )
            first = commit_all(worktree, "first logical unit")
            (worktree / "second.py").write_text("SECOND = True\n", encoding="utf-8")
            second = commit_all(worktree, "second logical unit")

            result_sha, changed = cr.commit_dirty_result(task, paths)
            self.assertTrue(changed)
            self.assertEqual(result_sha, second)
            self.assertEqual(task["result_sha"], second)
            self.assertEqual(task["codex_head_sha"], second)
            self.assertFalse(task["result_squashed"])
            self.assertTrue(task["result_preserves_commits"])
            self.assertEqual(git(worktree, "rev-parse", f"{second}^").stdout.strip(), first)
            self.assertEqual(
                command(
                    "git",
                    "--git-dir",
                    paths["broker"],
                    "rev-parse",
                    task["result_ref"],
                ).stdout.strip(),
                second,
            )

    def test_incremental_checkpoint_pull_preserves_commit_boundaries(self) -> None:
        input_sha = git(self.root, "rev-parse", "HEAD").stdout.strip()
        remote = self.add_detached_worktree(input_sha, "live-remote")
        (remote / "tracked.txt").write_text(
            "one\nremote-one\nthree\nfour\n", encoding="utf-8"
        )
        first_remote = commit_all(remote, "remote logical unit one")
        (remote / "remote.py").write_text("VALUE = 2\n", encoding="utf-8")
        second_remote = commit_all(remote, "remote logical unit two")
        state_dir = self.base / "live-pull-state"

        first_pull = cr.integrate_committed_checkpoint(
            self.root,
            "live-project",
            "task-live",
            input_sha,
            second_remote,
            state_dir=state_dir,
        )
        first_local_tip = cr.current_head(self.root)
        self.assertEqual(first_pull["changed_commit_count"], 2)
        self.assertEqual(
            [item["subject"] for item in first_pull["commits"]],
            ["remote logical unit one", "remote logical unit two"],
        )
        self.assertEqual(
            git(self.root, "log", "--format=%s", "-2").stdout.splitlines(),
            ["remote logical unit two", "remote logical unit one"],
        )
        self.assertFalse(git(self.root, "status", "--porcelain").stdout.strip())

        (remote / "third.py").write_text("THIRD = 3\n", encoding="utf-8")
        third_remote = commit_all(remote, "remote logical unit three")
        second_pull = cr.integrate_committed_checkpoint(
            self.root,
            "live-project",
            "task-live",
            second_remote,
            third_remote,
            prior_local_tip=first_local_tip,
            state_dir=state_dir,
        )
        self.assertEqual(second_pull["changed_commit_count"], 1)
        self.assertEqual(
            [item["subject"] for item in second_pull["commits"]],
            ["remote logical unit three"],
        )
        self.assertEqual(git(self.root, "log", "-1", "--format=%s").stdout.strip(),
                         "remote logical unit three")
        self.assertTrue((self.root / "third.py").is_file())

    def test_checkpoint_pull_from_dirty_tracked_input_preserves_codex_commit(self) -> None:
        tracked = self.root / "tracked.txt"
        tracked.write_text("one\nlocal-baseline\nthree\nfour\n", encoding="utf-8")
        snapshot = cr.create_hidden_snapshot(
            self.root,
            "refs/codex/live/input/dirty-tracked",
            "interactive tracked input",
            include_untracked=False,
        )
        local_baseline = commit_all(self.root, "commit local starting state")

        remote = self.add_detached_worktree(snapshot["commit"], "dirty-input-remote")
        remote_lines = (remote / "tracked.txt").read_text(encoding="utf-8").splitlines()
        remote_lines[3] = "codex-change"
        (remote / "tracked.txt").write_text(
            "\n".join(remote_lines) + "\n", encoding="utf-8"
        )
        remote_tip = commit_all(remote, "Codex logical unit")

        result = cr.integrate_committed_checkpoint(
            self.root,
            "live-project",
            "task-dirty-input",
            snapshot["commit"],
            remote_tip,
            state_dir=self.base / "dirty-input-state",
        )

        self.assertEqual(result["changed_commit_count"], 1)
        self.assertEqual(
            git(self.root, "log", "-1", "--format=%s").stdout.strip(),
            "Codex logical unit",
        )
        self.assertEqual(
            git(self.root, "rev-parse", "HEAD^").stdout.strip(), local_baseline
        )
        self.assertEqual(
            tracked.read_text(encoding="utf-8"),
            "one\nlocal-baseline\nthree\ncodex-change\n",
        )

    def test_checkpoint_pull_preserves_unrelated_untracked_files(self) -> None:
        input_sha = git(self.root, "rev-parse", "HEAD").stdout.strip()
        remote = self.add_detached_worktree(input_sha, "untracked-live-remote")
        (remote / "tracked.txt").write_text(
            "one\nremote-update\nthree\nfour\n", encoding="utf-8"
        )
        remote_tip = commit_all(remote, "remote update with local untracked file")
        untracked = self.root / "local-notes.txt"
        untracked.write_text("keep this local\n", encoding="utf-8")

        result = cr.integrate_committed_checkpoint(
            self.root,
            "live-project",
            "task-untracked",
            input_sha,
            remote_tip,
            state_dir=self.base / "live-untracked-state",
        )

        self.assertEqual(result["changed_commit_count"], 1)
        self.assertEqual(untracked.read_text(encoding="utf-8"), "keep this local\n")
        self.assertIn("?? local-notes.txt", git(self.root, "status", "--porcelain").stdout)
        self.assertEqual(
            git(self.root, "log", "-1", "--format=%s").stdout.strip(),
            "remote update with local untracked file",
        )

    def test_checkpoint_pull_blocks_untracked_path_overwrite(self) -> None:
        input_sha = git(self.root, "rev-parse", "HEAD").stdout.strip()
        remote = self.add_detached_worktree(input_sha, "untracked-collision-remote")
        (remote / "collision.txt").write_text("from Codex\n", encoding="utf-8")
        remote_tip = commit_all(remote, "add collision path")
        collision = self.root / "collision.txt"
        collision.write_text("local untracked content\n", encoding="utf-8")
        before_head = cr.current_head(self.root)
        before_status = cr.git_status_porcelain(self.root)

        with self.assertRaises(cr.CodexRemoteError) as caught:
            cr.integrate_committed_checkpoint(
                self.root,
                "live-project",
                "task-untracked-collision",
                input_sha,
                remote_tip,
                state_dir=self.base / "live-untracked-collision-state",
            )

        self.assertEqual(caught.exception.code, "LOCAL_CHECKOUT_BLOCKED")
        self.assertEqual(cr.current_head(self.root), before_head)
        self.assertEqual(cr.git_status_porcelain(self.root), before_status)
        self.assertEqual(
            collision.read_text(encoding="utf-8"), "local untracked content\n"
        )

    def test_checkpoint_conflict_keeps_canonical_checkout_untouched(self) -> None:
        input_sha = git(self.root, "rev-parse", "HEAD").stdout.strip()
        remote = self.add_detached_worktree(input_sha, "conflicting-live-remote")
        (remote / "tracked.txt").write_text(
            "one\nREMOTE\nthree\nfour\n", encoding="utf-8"
        )
        remote_tip = commit_all(remote, "remote conflicting change")
        (self.root / "tracked.txt").write_text(
            "one\nLOCAL\nthree\nfour\n", encoding="utf-8"
        )
        commit_all(self.root, "local conflicting change")
        before = visible_state(self.root)
        content = (self.root / "tracked.txt").read_bytes()
        state_dir = self.base / "live-conflict-state"

        with self.assertRaises(cr.CodexRemoteError) as caught:
            cr.integrate_committed_checkpoint(
                self.root,
                "live-project",
                "task-conflict",
                input_sha,
                remote_tip,
                state_dir=state_dir,
            )
        self.assertEqual(caught.exception.code, "INTEGRATION_CONFLICT")
        self.assertEqual(before, visible_state(self.root))
        self.assertEqual(content, (self.root / "tracked.txt").read_bytes())
        conflict_path = Path(caught.exception.details["conflict_path"])
        self.assertTrue(conflict_path.is_dir())
        self.assertTrue(git(conflict_path, "ls-files", "-u").stdout.strip())
        cr.remove_worktree(self.root, conflict_path)

    def test_job_request_waits_for_trusted_broker_response(self) -> None:
        request_file = self.root / cr.JOB_REQUEST_RELATIVE
        response_file = self.root / cr.JOB_RESPONSE_RELATIVE

        def broker() -> None:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and not request_file.exists():
                time.sleep(0.01)
            self.assertTrue(request_file.exists())
            cr.atomic_write_json(
                response_file,
                {"ok": True, "message": "launched", "job": {"run_id": "run-1"}},
            )

        worker = threading.Thread(target=broker)
        worker.start()
        try:
            result = cr.request_job_file(
                request_file,
                name="live experiment",
                command=["python", "train.py"],
                response_file=response_file,
                wait_seconds=3,
            )
        finally:
            worker.join(timeout=3)
        self.assertEqual(result["job"]["run_id"], "run-1")
        self.assertFalse(response_file.exists())

    def test_environment_request_waits_for_trusted_broker_response(self) -> None:
        request_file = self.root / cr.ENV_REQUEST_RELATIVE
        response_file = self.root / cr.ENV_RESPONSE_RELATIVE

        def broker() -> None:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and not request_file.exists():
                time.sleep(0.01)
            self.assertTrue(request_file.exists())
            cr.atomic_write_json(
                response_file,
                {"ok": True, "action": "refresh", "finished_at": cr.utc_now()},
            )

        worker = threading.Thread(target=broker)
        worker.start()
        try:
            with mock.patch.dict(
                os.environ,
                {"CODEX_ENV_REQUEST_PATH": str(request_file)},
            ):
                result = cr.request_env_action_file(
                    request_file,
                    response_file,
                    action="refresh",
                    wait_seconds=3,
                )
        finally:
            worker.join(timeout=3)
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "refresh")
        self.assertFalse(response_file.exists())

    def test_job_control_request_waits_for_trusted_broker_response(self) -> None:
        request_file = self.root / cr.JOB_CONTROL_REQUEST_RELATIVE
        response_file = self.base / "trusted-state" / cr.JOB_CONTROL_RESPONSE_RELATIVE

        def broker() -> None:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and not request_file.exists():
                time.sleep(0.01)
            self.assertTrue(request_file.exists())
            request = cr.read_json(request_file)
            assert request is not None
            self.assertEqual(request["action"], "status")
            self.assertEqual(request["run_id"], "run-1")
            request_file.unlink()
            response_for_nonce = response_file.with_name(
                f"{response_file.name}.{request['request_nonce']}"
            )
            cr.atomic_write_json(
                response_for_nonce,
                {
                    "ok": True,
                    "request_nonce": request["request_nonce"],
                    "job": {"run_id": "run-1", "state": "SUCCEEDED"},
                },
            )

        worker = threading.Thread(target=broker)
        worker.start()
        try:
            with mock.patch.dict(
                os.environ,
                {
                    "CODEX_JOB_CONTROL_REQUEST_PATH": str(request_file),
                    "CODEX_JOB_CONTROL_RESPONSE_PATH": str(response_file),
                },
            ):
                result = cr.request_job_control_file(
                    request_file,
                    response_file,
                    action="status",
                    run_id="run-1",
                    wait_seconds=3,
                )
        finally:
            worker.join(timeout=3)
        self.assertEqual(result["job"]["state"], "SUCCEEDED")
        self.assertEqual(list(response_file.parent.glob(f"{response_file.name}.*")), [])
        self.assertEqual(cr.git_status_porcelain(self.root), "")

    def test_commit_request_waits_for_trusted_broker_response(self) -> None:
        request_file = self.root / cr.COMMIT_REQUEST_RELATIVE
        response_file = self.root / cr.COMMIT_RESPONSE_RELATIVE

        def broker() -> None:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and not request_file.exists():
                time.sleep(0.01)
            self.assertTrue(request_file.exists())
            request = cr.read_json(request_file)
            assert request is not None
            self.assertEqual(request["message"], "logical checkpoint")
            self.assertEqual(request["paths"], ["tracked.txt"])
            cr.atomic_write_json(
                response_file,
                {
                    "ok": True,
                    "commit": {"sha": "deadbeef", "message": request["message"]},
                },
            )

        worker = threading.Thread(target=broker)
        worker.start()
        try:
            with mock.patch.dict(
                os.environ,
                {"CODEX_COMMIT_REQUEST_PATH": str(request_file)},
            ):
                result = cr.request_commit_file(
                    request_file,
                    response_file,
                    message="logical checkpoint",
                    paths=["tracked.txt"],
                    wait_seconds=3,
                )
        finally:
            worker.join(timeout=3)
        self.assertEqual(result["commit"]["sha"], "deadbeef")
        self.assertFalse(response_file.exists())

    def test_trusted_commit_broker_preserves_selected_commit_boundary(self) -> None:
        home = self.base / "commit-broker-home"
        home.mkdir()
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            paths, task, worktree = self.make_interactive_server_task(home)
            (worktree / "tracked.txt").write_text(
                "one\ncommitted-unit\nthree\nfour\n", encoding="utf-8"
            )
            (worktree / "later.py").write_text("LATER = True\n", encoding="utf-8")

            result = cr.server_interactive_commit_action(
                str(task["project_id"]),
                str(task["task_id"]),
                {
                    "message": "implement first logical unit",
                    "paths": ["tracked.txt"],
                },
            )

            commit_sha = result["commit"]["sha"]
            self.assertEqual(cr.current_head(worktree), commit_sha)
            self.assertEqual(
                git(worktree, "log", "-1", "--format=%s").stdout.strip(),
                "implement first logical unit",
            )
            self.assertEqual(result["commit"]["paths"], ["tracked.txt"])
            self.assertEqual(result["checkpoint"]["sha"], commit_sha)
            self.assertTrue((worktree / "later.py").is_file())
            self.assertIn("?? later.py", git(worktree, "status", "--short").stdout)
            self.assertNotIn(
                "later.py",
                git(worktree, "show", "--format=", "--name-only", commit_sha).stdout,
            )

    def test_trusted_commit_broker_rejects_paths_outside_worktree(self) -> None:
        with self.assertRaises(cr.CodexRemoteError) as caught:
            cr.normalized_commit_request(
                {"message": "bad path", "paths": ["../outside.txt"]}
            )
        self.assertEqual(caught.exception.code, "INVALID_COMMIT_REQUEST")

    def test_trusted_environment_control_refreshes_and_tests_clean_checkpoint(self) -> None:
        home = self.base / "environment-control-home"
        home.mkdir()
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            paths, task, worktree = self.make_interactive_server_task(home)
            task["bootstrap_cmd"] = (
                'test "$UV_PROJECT_ENVIRONMENT" = "$PWD/.venv" && '
                'test -n "$UV_CACHE_DIR" && '
                "mkdir -p .venv/bin && printf ready > .venv/bin/environment-ready"
            )
            task["test_cmd"] = (
                'test "$VIRTUAL_ENV" = "$PWD/.venv" && '
                "test -f .venv/bin/environment-ready"
            )
            task["tools"]["nix"] = None
            task["tools"]["uv"] = None
            cr.save_server_task(paths, task)

            result = cr.server_interactive_env_action(
                str(task["project_id"]),
                str(task["task_id"]),
                {"action": "check"},
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["refresh"]["exit_code"], 0)
            self.assertEqual(result["test"]["exit_code"], 0)
            self.assertTrue((worktree / ".venv/bin/environment-ready").is_file())
            self.assertTrue(Path(task["state_dir"], "codex-dev").is_file())

    def test_trusted_environment_control_requires_committed_tracked_work(self) -> None:
        home = self.base / "environment-dirty-home"
        home.mkdir()
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            _paths, task, worktree = self.make_interactive_server_task(home)
            task["bootstrap_cmd"] = "true"
            (worktree / "tracked.txt").write_text("dirty\n", encoding="utf-8")
            with self.assertRaises(cr.CodexRemoteError) as caught:
                cr.server_interactive_env_action(
                    str(task["project_id"]),
                    str(task["task_id"]),
                    {"action": "refresh"},
                )
            self.assertEqual(
                caught.exception.code,
                "ENV_REQUIRES_COMMITTED_CHECKPOINT",
            )

    def test_interactive_job_can_launch_from_unchanged_committed_input(self) -> None:
        home = self.base / "job-home"
        home.mkdir()
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            paths, task, _worktree = self.make_interactive_server_task(home)
            expected_job = {
                "run_id": "run-baseline",
                "name": "baseline job",
                "state": "STARTING",
                "tmux_session": "job-baseline",
            }
            with mock.patch.object(cr, "start_frozen_job", return_value=expected_job) as launch:
                result = cr.server_request_job(
                    str(task["project_id"]),
                    str(task["task_id"]),
                    {
                        "name": "baseline job",
                        "command": ["python", "train.py"],
                    },
                )
            self.assertEqual(result["job"], expected_job)
            self.assertEqual(result["checkpoint"]["sha"], task["input_sha"])
            source_task = launch.call_args.args[1]
            self.assertEqual(source_task["result_sha"], task["input_sha"])
            self.assertEqual(
                launch.call_args.kwargs["preflight_test_cmd"], task["test_cmd"]
            )
            record = cr.load_task_live_job(task)
            assert record is not None
            self.assertEqual(record["run_id"], "run-baseline")

    def test_interactive_job_launch_requires_configured_preflight_test(self) -> None:
        home = self.base / "job-no-test-home"
        home.mkdir()
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            paths, task, _worktree = self.make_interactive_server_task(home)
            task["test_cmd"] = ""
            cr.save_server_task(paths, task)
            with mock.patch.object(cr, "start_frozen_job") as launch, \
                 self.assertRaises(cr.CodexRemoteError) as caught:
                cr.server_request_job(
                    str(task["project_id"]),
                    str(task["task_id"]),
                    {"name": "unsafe", "command": ["python", "train.py"]},
                )
        self.assertEqual(caught.exception.code, "JOB_PREFLIGHT_REQUIRED")
        launch.assert_not_called()



class ServerStartTests(RepositoryTestCase):
    def test_server_start_is_idempotent_and_freezes_the_runner_helper(self) -> None:
        home = self.base / "server-home"
        home.mkdir()
        fake_codex = home / "bin" / "codex"
        fake_codex.parent.mkdir(parents=True)
        fake_codex.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_codex.chmod(0o755)
        project_id = "start-project"
        task_id = "task-start"

        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            paths = cr.ensure_server_layout(project_id)
            input_sha = git(self.root, "rev-parse", "HEAD").stdout.strip()
            input_ref = f"refs/codex/{project_id}/input/{task_id}"
            git(self.root, "push", str(paths["broker"]), f"HEAD:{input_ref}")
            prompt = "change the implementation"
            payload = {
                "schema_version": cr.SCHEMA_VERSION,
                "project_id": project_id,
                "project_name": "start",
                "task_id": task_id,
                "input_ref": input_ref,
                "input_sha": input_sha,
                "local_head": input_sha,
                "local_branch": "main",
                "normal_remote_dir": "/srv/normal-project",
                "prompt": prompt,
                "prompt_sha256": cr.hashlib.sha256(prompt.encode()).hexdigest(),
                "bootstrap_cmd": None,
                "test_cmd": None,
                "data_links": [],
                "max_untracked_bytes": 1024 * 1024,
                "model": None,
                "profile": None,
                "reasoning_effort": None,
                "enable_search": False,
                "lock_hashes": cr.file_hashes(self.root),
                "created_at": cr.utc_now(),
            }
            tools = {
                "bash": shutil.which("bash"),
                "git": shutil.which("git"),
                "tmux": shutil.which("true"),
                "flock": shutil.which("flock"),
                "codex": str(fake_codex),
            }

            with mock.patch.object(cr, "login_which", side_effect=lambda name: tools.get(name)):
                first = cr.server_start(project_id, task_id, payload)
                second = cr.server_start(project_id, task_id, payload)

            self.assertFalse(first["idempotent"])
            self.assertTrue(second["idempotent"])
            task = first["task"]
            runner = Path(task["runner_helper"])
            self.assertTrue(runner.is_file())
            self.assertEqual(runner.read_bytes(), BACKEND.read_bytes())
            self.assertEqual(task["runner_helper_sha256"], cr.sha256_file(runner))
            self.assertEqual(task["tools"]["python3"], str(Path(cr.sys.executable).resolve()))
            self.assertIn("bash -lc", task["runner_command"])
            self.assertIn("flock", task["runner_command"])
            self.assertEqual(task["state"], "STARTING")
            self.assertEqual(task["execution_mode"], "exec")
            jobctl = Path(task["jobctl_path"]).read_text(encoding="utf-8")
            self.assertIn("_job-request", jobctl)
            self.assertNotIn("--response-file", jobctl)
            self.assertNotIn("--wait-seconds", jobctl)

    def test_server_start_accepts_interactive_task_without_prompt(self) -> None:
        home = self.base / "interactive-server-home"
        home.mkdir()
        fake_codex = home / "bin" / "codex"
        fake_codex.parent.mkdir(parents=True)
        fake_codex.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_codex.chmod(0o755)
        project_id = "interactive-project"
        task_id = "task-interactive"

        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            paths = cr.ensure_server_layout(project_id)
            input_sha = git(self.root, "rev-parse", "HEAD").stdout.strip()
            input_ref = f"refs/codex/{project_id}/input/{task_id}"
            git(self.root, "push", str(paths["broker"]), f"HEAD:{input_ref}")
            payload = {
                "schema_version": cr.SCHEMA_VERSION,
                "project_id": project_id,
                "project_name": "interactive",
                "task_id": task_id,
                "execution_mode": "interactive",
                "input_ref": input_ref,
                "input_sha": input_sha,
                "local_head": input_sha,
                "local_branch": "main",
                "normal_remote_dir": "/srv/normal-project",
                "prompt": None,
                "prompt_sha256": None,
                "bootstrap_cmd": None,
                "test_cmd": None,
                "data_links": [],
                "max_untracked_bytes": 1024 * 1024,
                "model": None,
                "profile": None,
                # A project-local lower setting must not reduce managed
                # interactive sessions below Extra High.
                "reasoning_effort": "high",
                "enable_search": False,
                "lock_hashes": cr.file_hashes(self.root),
                "created_at": cr.utc_now(),
            }
            tools = {
                "bash": shutil.which("bash"),
                "git": shutil.which("git"),
                "tmux": shutil.which("true"),
                "flock": shutil.which("flock"),
                "codex": str(fake_codex),
            }

            with mock.patch.object(cr, "login_which", side_effect=lambda name: tools.get(name)):
                started = cr.server_start(project_id, task_id, payload)

            task = started["task"]
            self.assertEqual(task["execution_mode"], "interactive")
            self.assertIsNone(task["prompt_path"])
            self.assertTrue(task["tmux_session"].startswith("codexi-"))
            self.assertEqual(task["model"], cr.DEFAULT_INTERACTIVE_MODEL)
            self.assertEqual(
                task["reasoning_effort"], cr.DEFAULT_INTERACTIVE_REASONING
            )
            self.assertEqual(
                task["approval_policy"], cr.DEFAULT_INTERACTIVE_APPROVAL_POLICY
            )
            self.assertTrue(task["network_access"])
            jobctl = Path(task["jobctl_path"]).read_text(encoding="utf-8")
            self.assertIn("--response-file", jobctl)
            self.assertIn("--wait-seconds 900", jobctl)
            self.assertIn("_job-control", jobctl)
            self.assertNotIn("_server-job", jobctl)
            self.assertIn(cr.JOB_CONTROL_REQUEST_RELATIVE, jobctl)
            self.assertIn(cr.JOB_CONTROL_RESPONSE_RELATIVE, jobctl)
            command("sh", "-n", task["jobctl_path"])
            commitctl = Path(task["commitctl_path"]).read_text(encoding="utf-8")
            self.assertIn("_commit-request", commitctl)
            self.assertIn("--wait-seconds 900", commitctl)
            self.assertIn('"$@"', commitctl)


class ServerCleanupTests(RepositoryTestCase):
    def test_discard_kills_retained_tmux_session(self) -> None:
        home = self.base / "home"
        home.mkdir()
        session_exists = True
        tmux_calls: list[list[str]] = []
        original_run = cr.run

        def fake_run(argv, **kwargs):
            nonlocal session_exists
            args = [os.fspath(item) for item in argv]
            if args[0] == "/fake/tmux":
                tmux_calls.append(args)
                if args[1] == "has-session":
                    return subprocess.CompletedProcess(
                        args=args,
                        returncode=0 if session_exists else 1,
                        stdout="",
                        stderr="",
                    )
                if args[1] == "kill-session":
                    session_exists = False
                    return subprocess.CompletedProcess(
                        args=args,
                        returncode=0,
                        stdout="",
                        stderr="",
                    )
                if args[1] == "list-panes":
                    return subprocess.CompletedProcess(
                        args=args,
                        returncode=0 if session_exists else 1,
                        stdout="0\t\t123\n" if session_exists else "",
                        stderr="",
                    )
                raise AssertionError(f"unexpected fake tmux command: {args}")
            return original_run(argv, **kwargs)

        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            paths = cr.ensure_server_layout("cleanup-project")
            task = cr.save_server_task(
                paths,
                {
                    "schema_version": cr.SCHEMA_VERSION,
                    "project_id": "cleanup-project",
                    "project_name": "cleanup",
                    "task_id": "task-cleanup",
                    "state": "FAILED",
                    "tmux_session": "codex-cleanup",
                    "tools": {"tmux": "/fake/tmux"},
                    "worktree": str(paths["worktrees"] / "task-cleanup"),
                },
            )
            with mock.patch.object(cr, "run", side_effect=fake_run):
                cleaned = cr.cleanup_server_task_artifacts(paths, task, "discard")
                status = cr.server_status("cleanup-project")["task"]

        self.assertEqual(cleaned["state"], "DISCARDED")
        self.assertIn("tmux_cleaned_at", cleaned)
        self.assertFalse(session_exists)
        self.assertEqual(
            tmux_calls,
            [
                ["/fake/tmux", "has-session", "-t", "codex-cleanup"],
                ["/fake/tmux", "kill-session", "-t", "codex-cleanup"],
                ["/fake/tmux", "has-session", "-t", "codex-cleanup"],
                [
                    "/fake/tmux",
                    "list-panes",
                    "-t",
                    "codex-cleanup",
                    "-F",
                    "#{pane_dead}\t#{pane_dead_status}\t#{pane_pid}",
                ],
            ],
        )
        self.assertFalse(status["tmux"]["exists"])
        self.assertFalse(status["tmux"]["running"])
        self.assertFalse(status["worktree_exists"])


    def test_orphaned_worktree_can_be_published_without_rerunning_codex(self) -> None:
        home = self.base / "recover-home"
        home.mkdir()
        project_id = "recover-project"
        task_id = "task-recover"
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            paths = cr.ensure_server_layout(project_id)
            input_sha = git(self.root, "rev-parse", "HEAD").stdout.strip()
            input_ref = f"refs/codex/{project_id}/input/{task_id}"
            git(self.root, "push", str(paths["broker"]), f"HEAD:{input_ref}")
            worktree = paths["worktrees"] / task_id
            command(
                "git",
                "--git-dir",
                paths["broker"],
                "worktree",
                "add",
                "--detach",
                worktree,
                input_sha,
            )
            (worktree / "tracked.txt").write_text(
                "one\nRECOVERED\nthree\nfour\n", encoding="utf-8"
            )
            task = {
                "schema_version": cr.SCHEMA_VERSION,
                "project_id": project_id,
                "project_name": "recover",
                "task_id": task_id,
                "state": "ORPHANED",
                "execution_mode": "interactive",
                "input_ref": input_ref,
                "input_sha": input_sha,
                "worktree": str(worktree),
                "state_dir": str(paths["project_state"] / task_id),
                "max_untracked_bytes": 1024 * 1024,
                "tools": {"tmux": "/bin/false"},
                "error": "runner disappeared",
            }
            cr.save_server_task(paths, task)
            result = cr.server_recover(project_id)

            recovered = result["task"]
            self.assertEqual(recovered["state"], "READY_RECOVERED_UNVERIFIED")
            self.assertTrue(recovered["has_changes"])
            self.assertFalse(recovered["recovery"]["codex_rerun"])
            self.assertFalse(recovered["recovery"]["tests_rerun"])
            self.assertIsNone(recovered.get("error"))
            self.assertEqual(
                command(
                    "git",
                    "--git-dir",
                    paths["broker"],
                    "rev-parse",
                    recovered["result_ref"],
                ).stdout.strip(),
                recovered["result_sha"],
            )


class ServerRunnerTests(RepositoryTestCase):
    def prepare_server_task(
        self,
        home: Path,
        *,
        unsafe: bool = False,
        lock_change: bool = False,
    ) -> tuple[str, str, dict[str, Path]]:
        project_id = "runner-project"
        task_id = "task-runner"
        paths = cr.ensure_server_layout(project_id)
        if lock_change:
            (self.root / ".gitignore").write_text(".venv/\n", encoding="utf-8")
            (self.root / "uv.lock").write_text("old-lock\n", encoding="utf-8")
            commit_all(self.root, "add lock file for refresh test")
        input_sha = git(self.root, "rev-parse", "HEAD").stdout.strip()
        input_ref = f"refs/codex/{project_id}/input/{task_id}"
        git(self.root, "push", str(paths["broker"]), f"HEAD:{input_ref}")
        worktree = paths["worktrees"] / task_id
        command("git", "--git-dir", paths["broker"], "worktree", "add", "--detach", worktree, input_sha)
        state_dir = paths["project_state"] / task_id
        state_dir.mkdir(parents=True)
        prompt = state_dir / "prompt.txt"
        prompt.write_text("make the requested change", encoding="utf-8")

        fake_codex = home / "bin" / "codex"
        fake_codex.parent.mkdir(parents=True)
        fake_codex.write_text(
            "#!/usr/bin/env python3\n"
            "import json, pathlib, sys\n"
            "sys.stdin.read()\n"
            "root = pathlib.Path.cwd()\n"
            + (
                "(root / '.env').write_text('SECRET=x\\n')\n"
                "import subprocess\n"
                "subprocess.run(['git', 'add', '.env'], check=True)\n"
                "subprocess.run(['git', '-c', 'user.name=Fake Codex', '-c', "
                "'user.email=fake@example.invalid', 'commit', '-m', 'commit secret'], check=True)\n"
                if unsafe
                else (
                    "(root / 'tracked.txt').write_text('one\\ntwo\\nINTERMEDIATE\\nfour\\n')\n"
                    "import subprocess\n"
                    "subprocess.run(['git', 'add', 'tracked.txt'], check=True)\n"
                    "subprocess.run(['git', '-c', 'user.name=Fake Codex', '-c', "
                    "'user.email=fake@example.invalid', 'commit', '-m', 'intermediate source change'], check=True)\n"
                    "(root / 'tracked.txt').write_text('one\\ntwo\\nCODEX\\nfour\\n')\n"
                    + ("(root / 'uv.lock').write_text('new-lock\\n')\n" if lock_change else "")
                )
            )
            + "print(json.dumps({'type': 'thread.started', 'thread_id': 'thread-test'}), flush=True)\n"
            "print(json.dumps({'type': 'turn.completed'}), flush=True)\n",
            encoding="utf-8",
        )
        fake_codex.chmod(0o755)
        task = {
            "schema_version": cr.SCHEMA_VERSION,
            "project_id": project_id,
            "project_name": "runner",
            "task_id": task_id,
            "state": "STARTING",
            "created_at": cr.utc_now(),
            "input_ref": input_ref,
            "input_sha": input_sha,
            "local_head": input_sha,
            "local_branch": "main",
            "broker": str(paths["broker"]),
            "worktree": str(worktree),
            "state_dir": str(state_dir),
            "prompt_path": str(prompt),
            "tmux_session": "unused-test-session",
            "lock_path": str(paths["lock"]),
            "bootstrap_cmd": (
                "mkdir -p .venv && printf '%s\\n' refresh >> .venv/refresh-count"
                if lock_change
                else None
            ),
            "test_cmd": (
                None
                if unsafe
                else (
                    "test $(wc -l < .venv/refresh-count) -eq 2 && grep -q CODEX tracked.txt"
                    if lock_change
                    else "grep -q CODEX tracked.txt"
                )
            ),
            "data_links": [],
            "max_untracked_bytes": 1024 * 1024,
            "model": None,
            "profile": None,
            "reasoning_effort": None,
            "enable_search": False,
            "lock_hashes": {},
            "tools": {
                "bash": shutil.which("bash"),
                "git": shutil.which("git"),
                "tmux": shutil.which("true"),
                "flock": shutil.which("flock"),
                "python3": shutil.which("python3"),
                "codex": str(fake_codex),
            },
        }
        cr.save_server_task(paths, task)
        return project_id, task_id, paths

    def run_server_task(self, *, unsafe: bool = False, lock_change: bool = False) -> dict:
        home = self.base / "home"
        home.mkdir()
        old_term = signal.getsignal(signal.SIGTERM)
        old_int = signal.getsignal(signal.SIGINT)
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            project_id, task_id, paths = self.prepare_server_task(
                home,
                unsafe=unsafe,
                lock_change=lock_change,
            )
            try:
                cr.server_run(project_id, task_id)
            finally:
                signal.signal(signal.SIGTERM, old_term)
                signal.signal(signal.SIGINT, old_int)
            task = cr.load_server_task(paths, task_id)
            assert task is not None
            return task

    def test_cancellation_during_bootstrap_finishes_as_cancelled_noop(self) -> None:
        home = self.base / "home"
        home.mkdir()
        old_term = signal.getsignal(signal.SIGTERM)
        old_int = signal.getsignal(signal.SIGINT)
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            project_id, task_id, paths = self.prepare_server_task(home, lock_change=True)

            def cancel_bootstrap(_shell, _command, _cwd, _log_path, active, **_kwargs):
                active["cancelled"] = True
                return 143

            try:
                with mock.patch.object(cr, "run_shell_logged", side_effect=cancel_bootstrap):
                    cr.server_run(project_id, task_id)
            finally:
                signal.signal(signal.SIGTERM, old_term)
                signal.signal(signal.SIGINT, old_int)

            task = cr.load_server_task(paths, task_id)
            assert task is not None
            self.assertEqual(task["state"], "CANCELLED_NOOP")
            self.assertTrue(task["cancel_requested"])
            self.assertNotIn("codex_started_at", task)

    def test_server_runner_publishes_result_and_test_status(self) -> None:
        task = self.run_server_task()
        self.assertEqual(task["state"], "READY")
        self.assertEqual(task["codex_thread_id"], "thread-test")
        self.assertEqual(task["tests"]["exit_code"], 0)
        self.assertTrue(task["result_sha"])
        self.assertNotEqual(task["input_sha"], task["result_sha"])
        self.assertTrue(task["result_squashed"])
        self.assertNotEqual(task["codex_head_sha"], task["result_sha"])
        parent = command(
            "git",
            "--git-dir",
            task["broker"],
            "rev-parse",
            f"{task['result_sha']}^",
        ).stdout.strip()
        self.assertEqual(parent, task["input_sha"])

    def test_interactive_runner_inherits_terminal_and_finalizes_result(self) -> None:
        home = self.base / "interactive-home"
        home.mkdir()
        old_term = signal.getsignal(signal.SIGTERM)
        old_int = signal.getsignal(signal.SIGINT)
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            project_id, task_id, paths = self.prepare_server_task(home)
            task = cr.load_server_task(paths, task_id)
            assert task is not None
            task["execution_mode"] = "interactive"
            task["prompt_path"] = None
            task["model"] = cr.DEFAULT_INTERACTIVE_MODEL
            task["reasoning_effort"] = cr.DEFAULT_INTERACTIVE_REASONING
            task["approval_policy"] = cr.DEFAULT_INTERACTIVE_APPROVAL_POLICY
            task["network_access"] = True
            task["test_cmd"] = "grep -q INTERACTIVE interactive.txt"
            fake_codex = Path(task["tools"]["codex"])
            fake_codex.write_text(
                "#!/usr/bin/env python3\n"
                "from pathlib import Path\n"
                "Path('interactive.txt').write_text('INTERACTIVE\\n')\n",
                encoding="utf-8",
            )
            cr.save_server_task(paths, task)
            try:
                cr.server_run(project_id, task_id)
            finally:
                signal.signal(signal.SIGTERM, old_term)
                signal.signal(signal.SIGINT, old_int)

            finished = cr.load_server_task(paths, task_id)
            assert finished is not None
            self.assertEqual(finished["state"], "READY")
            self.assertEqual(finished["execution_mode"], "interactive")
            self.assertEqual(finished["codex_exit_code"], 0)
            self.assertTrue(finished["has_changes"])
            self.assertEqual(finished["tests"]["exit_code"], 0)
            self.assertFalse((Path(finished["state_dir"]) / "codex.jsonl").exists())

    def test_interactive_runner_enters_nix_shell_and_bootstraps_uv_project(self) -> None:
        (self.root / ".gitignore").write_text(".venv/\n", encoding="utf-8")
        (self.root / "flake.nix").write_text("{}\n", encoding="utf-8")
        (self.root / "pyproject.toml").write_text(
            "[project]\nname='runner-env'\nversion='0.1.0'\n",
            encoding="utf-8",
        )
        (self.root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
        commit_all(self.root, "add locked project environment")

        home = self.base / "interactive-env-home"
        home.mkdir()
        old_term = signal.getsignal(signal.SIGTERM)
        old_int = signal.getsignal(signal.SIGINT)
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            project_id, task_id, paths = self.prepare_server_task(home)
            task = cr.load_server_task(paths, task_id)
            assert task is not None
            task["execution_mode"] = "interactive"
            task["prompt_path"] = None
            task["model"] = cr.DEFAULT_INTERACTIVE_MODEL
            task["reasoning_effort"] = cr.DEFAULT_INTERACTIVE_REASONING
            task["approval_policy"] = cr.DEFAULT_INTERACTIVE_APPROVAL_POLICY
            task["network_access"] = True
            task["bootstrap_cmd"] = None
            task["test_cmd"] = (
                "test -x .venv/bin/uv && grep -q PROJECT_ENV interactive.txt"
            )

            fake_nix = home / "bin" / "nix"
            python = str(Path(cr.sys.executable).resolve())
            fake_nix.write_text(
                f"#!{python}\n"
                "import os, pathlib, subprocess, sys\n"
                "args = sys.argv[1:]\n"
                "root = pathlib.Path.cwd()\n"
                "# Real Nix writes a missing flake.lock by default.  Managed\n"
                "# startup must explicitly suppress that side effect.\n"
                "assert '--no-write-lock-file' in args, args\n"
                "marker = '--command' if '--command' in args else '-c'\n"
                "index = args.index(marker)\n"
                "command = args[index + 1:]\n"
                "if command[:3] == ['uv', 'sync', '--frozen']:\n"
                "    assert os.environ.get('UV_PROJECT_ENVIRONMENT') == str(root / '.venv')\n"
                "    assert 'tool-cache' in os.environ.get('UV_CACHE_DIR', '')\n"
                "    binary = root / '.venv' / 'bin' / 'uv'\n"
                "    binary.parent.mkdir(parents=True, exist_ok=True)\n"
                "    binary.write_text('#!/bin/sh\\nexit 0\\n')\n"
                "    binary.chmod(0o755)\n"
                "    raise SystemExit(0)\n"
                "raise SystemExit(subprocess.call(command, env=os.environ.copy()))\n",
                encoding="utf-8",
            )
            fake_nix.chmod(0o755)
            task["tools"]["nix"] = str(fake_nix)
            task["tools"]["uv"] = None

            fake_codex = Path(task["tools"]["codex"] )
            fake_codex.write_text(
                f"#!{python}\n"
                "import os, pathlib, shutil\n"
                "root = pathlib.Path.cwd()\n"
                "assert os.environ.get('VIRTUAL_ENV') == str(root / '.venv')\n"
                "assert shutil.which('uv') == str(root / '.venv' / 'bin' / 'uv')\n"
                "(root / 'interactive.txt').write_text('PROJECT_ENV\\n')\n",
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)
            cr.save_server_task(paths, task)
            try:
                cr.server_run(project_id, task_id)
            finally:
                signal.signal(signal.SIGTERM, old_term)
                signal.signal(signal.SIGINT, old_int)

            finished = cr.load_server_task(paths, task_id)
            assert finished is not None
            self.assertEqual(finished["state"], "READY")
            self.assertTrue(finished["bootstrap_inferred"])
            self.assertIn("nix develop", finished["interactive_environment"])
            self.assertEqual(finished["tests"]["exit_code"], 0)
            self.assertFalse((Path(finished["worktree"]) / "flake.lock").exists())

    def test_nix_develop_environment_probe_never_writes_lock_files(self) -> None:
        (self.root / "flake.nix").write_text("{}\n", encoding="utf-8")
        task = {"tools": {"nix": "/nix/bin/nix"}, "bootstrap_cmd": None, "test_cmd": None}

        without_lock = cr.interactive_nix_develop_candidates(task, self.root)
        self.assertTrue(without_lock)
        for candidate in without_lock:
            self.assertIn("--no-write-lock-file", candidate)
            self.assertNotIn("--no-update-lock-file", candidate)

        (self.root / "flake.lock").write_text("{}\n", encoding="utf-8")
        with_lock = cr.interactive_nix_develop_candidates(task, self.root)
        self.assertTrue(with_lock)
        for candidate in with_lock:
            self.assertIn("--no-write-lock-file", candidate)
            self.assertIn("--no-update-lock-file", candidate)

    def test_configured_nix_bootstrap_is_guarded_against_lock_writes(self) -> None:
        (self.root / "flake.nix").write_text("{}\n", encoding="utf-8")
        task = {
            "tools": {"nix": "/nix/bin/nix"},
            "bootstrap_cmd": "nix develop .#server --command uv sync --frozen",
        }
        command, inferred = cr.inferred_interactive_bootstrap(task, self.root)
        self.assertFalse(inferred)
        assert command is not None
        tokens = cr.shlex.split(command)
        self.assertEqual(tokens[0], "/nix/bin/nix")
        self.assertIn("--no-write-lock-file", tokens)
        self.assertNotIn("--no-update-lock-file", tokens)

    def test_lockfile_change_refreshes_environment_before_tests(self) -> None:
        task = self.run_server_task(lock_change=True)
        self.assertEqual(task["state"], "READY")
        self.assertEqual(task["lock_files_changed"], ["uv.lock"])
        self.assertEqual(task["environment_refresh"]["exit_code"], 0)
        self.assertFalse(task["environment_refresh"]["dirty_after_refresh"])
        count = Path(task["worktree"]) / ".venv" / "refresh-count"
        self.assertEqual(count.read_text(encoding="utf-8").splitlines(), ["refresh", "refresh"])
        self.assertEqual(task["tests"]["exit_code"], 0)

    def test_server_runner_blocks_secret_committed_by_codex(self) -> None:
        task = self.run_server_task(unsafe=True)
        self.assertEqual(task["state"], "BLOCKED_UNSAFE_RESULT")
        self.assertEqual(task["error_code"], "UNSAFE_RESULT")
        self.assertIn(".env", task["error"])


class ExperimentJobTests(RepositoryTestCase):
    def test_job_request_helper_validates_and_runner_consumes_file(self) -> None:
        state_dir = self.base / "state"
        state_dir.mkdir()
        request_path = self.root / cr.JOB_REQUEST_RELATIVE
        response = cr.request_job_file(
            request_path,
            name="heldout transfer",
            command=["python", "run.py", "--tag", "heldout"],
            gpus="0,1",
            completion_marker="outputs/COMPLETE",
            resume_command="python run.py --resume",
            metadata_values=["panel=confirmation", "seed=17"],
        )
        self.assertTrue(response["ok"])
        task = {
            "worktree": str(self.root),
            "state_dir": str(state_dir),
            "job_policy": "launch",
        }
        request = cr.consume_job_request(task)
        assert request is not None
        self.assertEqual(request["gpus"], "0,1")
        self.assertEqual(request["metadata"]["panel"], "confirmation")
        self.assertFalse(request_path.exists())
        self.assertEqual(
            json.loads((state_dir / "job-request.json").read_text(encoding="utf-8"))["name"],
            "heldout transfer",
        )

    def test_unauthorized_manual_job_request_is_blocked_and_removed(self) -> None:
        state_dir = self.base / "state-deny"
        state_dir.mkdir()
        request_path = self.root / cr.JOB_REQUEST_RELATIVE
        cr.atomic_write_json(
            request_path,
            {"name": "bad", "command": ["sleep", "10"]},
        )
        with self.assertRaises(cr.CodexRemoteError) as caught:
            cr.consume_job_request(
                {
                    "worktree": str(self.root),
                    "state_dir": str(state_dir),
                    "job_policy": "deny",
                }
            )
        self.assertEqual(caught.exception.code, "JOB_NOT_AUTHORIZED")
        self.assertFalse(request_path.exists())

    def test_orphaned_job_is_cleaned_and_sealed(self) -> None:
        home = self.base / "orphan-job-home"
        home.mkdir()
        project_id = "orphan-job-project"
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            paths = cr.ensure_server_layout(project_id)
            state_dir = paths["jobs_state"] / "run-orphan"
            (state_dir / "results").mkdir(parents=True)
            (state_dir / "checkpoints").mkdir()
            (state_dir / "results/partial.json").write_text("{}\n", encoding="utf-8")
            job = {
                "schema_version": cr.SCHEMA_VERSION,
                "project_id": project_id,
                "run_id": "run-orphan",
                "name": "orphan",
                "state": "RUNNING",
                "created_at": cr.utc_now(),
                "state_dir": str(state_dir),
                "worktree": str(self.root),
                "results_dir": str(state_dir / "results"),
                "checkpoints_dir": str(state_dir / "checkpoints"),
                "source_sha": git(self.root, "rev-parse", "HEAD").stdout.strip(),
                "tools": {"tmux": "/bin/false"},
                "data_links": [],
                "data_links_active": False,
            }
            cr.save_server_job(paths, job)
            status = cr.server_job_status(project_id, "run-orphan")["job"]
        self.assertEqual(status["state"], "ORPHANED")
        self.assertTrue((state_dir / "artifacts.manifest.json").is_file())
        self.assertIn("results/partial.json", status["artifact_evidence"])

    def test_stop_before_child_process_is_cleaned_and_sealed(self) -> None:
        home = self.base / "early-stop-home"
        home.mkdir()
        project_id = "early-stop-project"
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            paths = cr.ensure_server_layout(project_id)
            state_dir = paths["jobs_state"] / "run-stop"
            (state_dir / "results").mkdir(parents=True)
            (state_dir / "checkpoints").mkdir()
            job = {
                "schema_version": cr.SCHEMA_VERSION,
                "project_id": project_id,
                "run_id": "run-stop",
                "name": "stop",
                "state": "STARTING",
                "created_at": cr.utc_now(),
                "state_dir": str(state_dir),
                "worktree": str(self.root),
                "results_dir": str(state_dir / "results"),
                "checkpoints_dir": str(state_dir / "checkpoints"),
                "source_sha": git(self.root, "rev-parse", "HEAD").stdout.strip(),
                "tmux_session": "run-stop",
                "tools": {"tmux": "/bin/true"},
                "data_links": [],
                "data_links_active": False,
            }
            cr.save_server_job(paths, job)
            with mock.patch.object(cr, "job_with_runtime_status", return_value=job):
                stopped = cr.server_job_stop(project_id, "run-stop")["job"]
        self.assertEqual(stopped["state"], "STOPPED")
        self.assertTrue((state_dir / "artifacts.manifest.json").is_file())

    def test_stop_escalates_for_sigterm_ignoring_process(self) -> None:
        home = self.base / "term-ignore-home"
        home.mkdir()
        process = subprocess.Popen(
            [
                cr.sys.executable,
                "-c",
                "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "print('ready', flush=True); time.sleep(60)",
            ],
            start_new_session=True,
            stdout=subprocess.PIPE,
            text=True,
        )
        assert process.stdout is not None
        self.assertEqual(process.stdout.readline().strip(), "ready")
        project_id = "term-ignore-project"
        try:
            with mock.patch.dict(os.environ, {"HOME": str(home)}):
                paths = cr.ensure_server_layout(project_id)
                state_dir = paths["jobs_state"] / "run-term-ignore"
                (state_dir / "results").mkdir(parents=True)
                (state_dir / "checkpoints").mkdir()
                job = {
                    "schema_version": cr.SCHEMA_VERSION,
                    "project_id": project_id,
                    "run_id": "run-term-ignore",
                    "name": "term ignore",
                    "state": "RUNNING",
                    "created_at": cr.utc_now(),
                    "state_dir": str(state_dir),
                    "worktree": str(self.root),
                    "results_dir": str(state_dir / "results"),
                    "checkpoints_dir": str(state_dir / "checkpoints"),
                    "source_sha": git(self.root, "rev-parse", "HEAD").stdout.strip(),
                    "process_pid": process.pid,
                    "process_start_ticks": cr.process_start_ticks(process.pid),
                    "server_boot_id": cr.linux_boot_id(),
                    "tools": {"tmux": "/bin/true"},
                    "data_links": [],
                    "data_links_active": False,
                }
                cr.save_server_job(paths, job)
                with mock.patch.object(cr, "job_with_runtime_status", return_value=job):
                    stopped = cr.server_job_stop(project_id, "run-term-ignore")["job"]
            self.assertTrue(stopped["stop_requested"])
            self.assertTrue(stopped["stop_escalated"])
            self.assertEqual(stopped["stop_signal"], "SIGKILL")
            self.assertEqual(process.wait(timeout=3), -signal.SIGKILL)
        finally:
            process.stdout.close()
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)

    def test_managed_state_file_helpers_reject_symlinks(self) -> None:
        target = self.base / "state-target"
        target.write_text("do not overwrite\n", encoding="utf-8")
        link = self.base / "managed.log"
        link.symlink_to(target)
        with self.assertRaises(cr.CodexRemoteError) as caught:
            cr.open_regular_nofollow(link, append=True)
        self.assertEqual(caught.exception.code, "UNSAFE_STATE_FILE")
        with self.assertRaises(cr.CodexRemoteError):
            cr.tail_file(link, 20)
        self.assertEqual(target.read_text(encoding="utf-8"), "do not overwrite\n")

        hardlink = self.base / "managed-hardlink.log"
        os.link(target, hardlink)
        with self.assertRaises(cr.CodexRemoteError) as caught:
            cr.open_regular_nofollow(hardlink, truncate=True)
        self.assertEqual(caught.exception.code, "UNSAFE_STATE_FILE")
        self.assertEqual(target.read_text(encoding="utf-8"), "do not overwrite\n")

    def test_frozen_job_records_manifest_and_runs_independently(self) -> None:
        home = self.base / "job-home"
        home.mkdir()
        project_id = "experiment-project"
        old_term = signal.getsignal(signal.SIGTERM)
        old_int = signal.getsignal(signal.SIGINT)
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            paths = cr.ensure_server_layout(project_id)
            source_sha = git(self.root, "rev-parse", "HEAD").stdout.strip()
            git(self.root, "push", str(paths["broker"]), f"HEAD:refs/source/{source_sha}")
            task = {
                "project_id": project_id,
                "project_name": "experiment",
                "task_id": "task-source",
                "input_sha": source_sha,
                "result_sha": source_sha,
                "result_lock_hashes": {"uv.lock": "deadbeef"},
                "data_links": [],
                "model": None,
                "profile": None,
                "reasoning_effort": "high",
                "tools": {
                    "bash": shutil.which("bash"),
                    "git": shutil.which("git"),
                    "tmux": shutil.which("true"),
                    "codex": shutil.which("true"),
                },
            }
            script = (
                "from pathlib import Path; import json, os; "
                "Path('done.marker').write_text('done\\n'); "
                "Path(os.environ['CODEX_RESULTS_DIR'], 'result.json').write_text("
                "json.dumps({'run': os.environ['CODEX_RUN_ID'], "
                "'source': os.environ['CODEX_SOURCE_SHA']})); "
                "Path(os.environ['CODEX_CHECKPOINTS_DIR'], 'checkpoint.txt').write_text('checkpoint\\n')"
            )
            request = {
                "name": "smoke experiment",
                "command": [cr.sys.executable, "-c", script],
                "gpus": "0,1",
                "completion_marker": "done.marker",
                "resume_command": "python run.py --resume",
                "metadata": {"panel": "confirmation", "seed": "17"},
            }
            job = cr.start_frozen_job(paths, task, request)
            try:
                returncode = cr.server_job_run(project_id, job["run_id"])
            finally:
                signal.signal(signal.SIGTERM, old_term)
                signal.signal(signal.SIGINT, old_int)

            self.assertEqual(returncode, 0)
            finished = cr.load_server_job(paths, job["run_id"])
            assert finished is not None
            self.assertEqual(finished["state"], "SUCCEEDED")
            self.assertEqual(finished["source_sha"], source_sha)
            self.assertTrue(finished["completion_marker_present"])
            state_dir = Path(finished["state_dir"])
            self.assertTrue((state_dir / "run.json").is_file())
            self.assertTrue((state_dir / "status.json").is_file())
            self.assertTrue((state_dir / "command.txt").is_file())
            self.assertTrue((state_dir / "environment.txt").is_file())
            self.assertIn(
                "lock_sha256[uv.lock]=deadbeef",
                (state_dir / "environment.txt").read_text(encoding="utf-8"),
            )
            self.assertTrue((state_dir / "results" / "result.json").is_file())
            self.assertTrue((state_dir / "checkpoints" / "checkpoint.txt").is_file())
            worktree = Path(finished["worktree"])
            self.assertEqual(git(worktree, "rev-parse", "HEAD").stdout.strip(), source_sha)
            result = json.loads(
                (state_dir / "results" / "result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(result["run"], finished["run_id"])
            self.assertEqual(result["source"], source_sha)
            artifact_manifest = cr.read_json(state_dir / "artifacts.manifest.json")
            assert artifact_manifest is not None
            self.assertEqual(
                {item["path"] for item in artifact_manifest["artifacts"]},
                {"results/result.json", "checkpoints/checkpoint.txt"},
            )
            report_export = cr.server_job_export(project_id, job["run_id"], "report")
            full_export = cr.server_job_export(project_id, job["run_id"], "full")
            with tarfile.open(report_export["archive"], "r:gz") as archive:
                report_names = set(archive.getnames())
            with tarfile.open(full_export["archive"], "r:gz") as archive:
                full_names = set(archive.getnames())
            prefix = finished["run_id"]
            self.assertIn(f"{prefix}/results/result.json", report_names)
            self.assertNotIn(f"{prefix}/checkpoints/checkpoint.txt", report_names)
            self.assertIn(f"{prefix}/checkpoints/checkpoint.txt", full_names)

            (state_dir / "results/result.json").write_text("tampered\n", encoding="utf-8")
            with self.assertRaises(cr.CodexRemoteError) as caught:
                cr.server_job_export(project_id, job["run_id"], "report")
            self.assertEqual(caught.exception.code, "ARTIFACT_MANIFEST_MISMATCH")
            summarized = cr.server_job_summarize(project_id, job["run_id"])
            self.assertEqual(summarized["analysis"]["state"], "STARTING")

    def test_zero_exit_without_marker_or_artifact_is_incomplete(self) -> None:
        home = self.base / "no-evidence-home"
        home.mkdir()
        project_id = "no-evidence-project"
        old_term = signal.getsignal(signal.SIGTERM)
        old_int = signal.getsignal(signal.SIGINT)
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            paths = cr.ensure_server_layout(project_id)
            source_sha = git(self.root, "rev-parse", "HEAD").stdout.strip()
            git(self.root, "push", str(paths["broker"]), f"HEAD:refs/source/{source_sha}")
            task = {
                "project_id": project_id,
                "project_name": "no-evidence",
                "task_id": "task-source",
                "input_sha": source_sha,
                "result_sha": source_sha,
                "data_links": [],
                "tools": {
                    "bash": shutil.which("bash"),
                    "git": shutil.which("git"),
                    "tmux": shutil.which("true"),
                    "codex": shutil.which("true"),
                },
            }
            job = cr.start_frozen_job(
                paths,
                task,
                {"name": "no evidence", "command": [cr.sys.executable, "-c", "pass"]},
            )
            try:
                returncode = cr.server_job_run(project_id, job["run_id"])
            finally:
                signal.signal(signal.SIGTERM, old_term)
                signal.signal(signal.SIGINT, old_int)
            finished = cr.load_server_job(paths, job["run_id"])
            assert finished is not None
        self.assertEqual(returncode, 1)
        self.assertEqual(finished["state"], "INCOMPLETE")
        self.assertFalse(finished["completion_marker_present"])
        self.assertFalse(finished["artifact_evidence_present"])
        self.assertTrue(Path(finished["state_dir"], "artifacts.manifest.json").is_file())

    def test_missing_configured_marker_and_background_children_cannot_succeed(self) -> None:
        def run_case(label: str, script: str) -> tuple[int, dict[str, object]]:
            home = self.base / f"{label}-home"
            home.mkdir()
            project_id = f"{label}-project"
            old_term = signal.getsignal(signal.SIGTERM)
            old_int = signal.getsignal(signal.SIGINT)
            with mock.patch.dict(os.environ, {"HOME": str(home)}):
                paths = cr.ensure_server_layout(project_id)
                source_sha = git(self.root, "rev-parse", "HEAD").stdout.strip()
                git(self.root, "push", str(paths["broker"]), f"HEAD:refs/source/{source_sha}")
                task = {
                    "project_id": project_id,
                    "project_name": label,
                    "task_id": "task-source",
                    "input_sha": source_sha,
                    "result_sha": source_sha,
                    "data_links": [],
                    "tools": {
                        "bash": shutil.which("bash"),
                        "git": shutil.which("git"),
                        "tmux": shutil.which("true"),
                        "codex": shutil.which("true"),
                    },
                }
                job = cr.start_frozen_job(
                    paths,
                    task,
                    {
                        "name": label,
                        "command": [cr.sys.executable, "-c", script],
                        "completion_marker": "COMPLETE",
                    },
                )
                try:
                    returncode = cr.server_job_run(project_id, job["run_id"])
                finally:
                    signal.signal(signal.SIGTERM, old_term)
                    signal.signal(signal.SIGINT, old_int)
                finished = cr.load_server_job(paths, job["run_id"])
                assert finished is not None
                return returncode, finished

        missing_rc, missing = run_case(
            "partial-without-marker",
            "from pathlib import Path; import os; "
            "Path(os.environ['CODEX_RESULTS_DIR'], 'partial.json').write_text('{}')",
        )
        self.assertEqual(missing_rc, 1)
        self.assertEqual(missing["state"], "INCOMPLETE")
        self.assertTrue(missing["artifact_evidence_present"])

        background_rc, background = run_case(
            "background-writer",
            "from pathlib import Path; import subprocess, sys; "
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
            "Path('COMPLETE').write_text('done')",
        )
        self.assertEqual(background_rc, 1)
        self.assertEqual(background["state"], "FAILED")
        self.assertTrue(background["background_process_detected"])

    def test_frozen_job_bootstraps_its_fresh_worktree_before_command(self) -> None:
        home = self.base / "bootstrap-job-home"
        home.mkdir()
        project_id = "bootstrap-experiment-project"
        (self.root / ".gitignore").write_text(".venv/\n", encoding="utf-8")
        source_sha = commit_all(self.root, "ignore local virtual environment")
        old_term = signal.getsignal(signal.SIGTERM)
        old_int = signal.getsignal(signal.SIGINT)
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            paths = cr.ensure_server_layout(project_id)
            git(self.root, "push", str(paths["broker"]), f"HEAD:refs/source/{source_sha}")
            task = {
                "project_id": project_id,
                "project_name": "bootstrap-experiment",
                "task_id": "task-source",
                "input_sha": source_sha,
                "result_sha": source_sha,
                "bootstrap_cmd": "mkdir -p .venv && printf ready > .venv/ready",
                "data_links": [],
                "tools": {
                    "bash": shutil.which("bash"),
                    "git": shutil.which("git"),
                    "tmux": shutil.which("true"),
                    "codex": shutil.which("true"),
                },
            }
            script = (
                "from pathlib import Path; "
                "assert Path('.venv/ready').read_text() == 'ready'; "
                "Path('BOOTSTRAP_COMPLETE').write_text('done\\n')"
            )
            job = cr.start_frozen_job(
                paths,
                task,
                {
                    "name": "bootstrapped frozen job",
                    "command": [cr.sys.executable, "-c", script],
                    "completion_marker": "BOOTSTRAP_COMPLETE",
                },
            )
            try:
                returncode = cr.server_job_run(project_id, job["run_id"])
            finally:
                signal.signal(signal.SIGTERM, old_term)
                signal.signal(signal.SIGINT, old_int)

            finished = cr.load_server_job(paths, job["run_id"])
            assert finished is not None
            self.assertEqual(returncode, 0)
            self.assertEqual(finished["state"], "SUCCEEDED")
            self.assertEqual(finished["bootstrap"]["exit_code"], 0)
            self.assertFalse(finished["bootstrap"]["dirty_after_bootstrap"])
            self.assertTrue(finished["bootstrap"]["source_integrity"]["tracked_clean"])
            self.assertTrue((Path(finished["worktree"]) / ".venv" / "ready").is_file())
            state_dir = Path(finished["state_dir"])
            self.assertEqual(
                (state_dir / "bootstrap-command.txt").read_text(encoding="utf-8").strip(),
                task["bootstrap_cmd"],
            )
            self.assertIn(
                "bootstrap_command=" + task["bootstrap_cmd"],
                (state_dir / "environment.txt").read_text(encoding="utf-8"),
            )

    def test_fast_job_cannot_be_reset_to_stale_starting_state(self) -> None:
        home = self.base / "fast-job-home"
        home.mkdir()
        project_id = "fast-experiment-project"
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            paths = cr.ensure_server_layout(project_id)
            source_sha = git(self.root, "rev-parse", "HEAD").stdout.strip()
            git(self.root, "push", str(paths["broker"]), f"HEAD:refs/source/{source_sha}")
            fake_tmux = home / "tmux"
            bash_path = shutil.which("bash")
            if bash_path is None:
                self.fail("bash is required for the fake tmux fixture")
            fake_tmux.write_text(
                f"#!{bash_path}\n"
                "set -e\n"
                "if [ \"${1:-}\" = new-session ]; then\n"
                "  command=${!#}\n"
                "  command=${command/ -lc / -c }\n"
                "  exec bash -c \"$command\"\n"
                "fi\n"
                "exit 0\n",
                encoding="utf-8",
            )
            fake_tmux.chmod(0o755)
            task = {
                "project_id": project_id,
                "project_name": "fast-experiment",
                "task_id": "task-source",
                "input_sha": source_sha,
                "result_sha": source_sha,
                "bootstrap_cmd": "",
                "data_links": [],
                "tools": {
                    "bash": shutil.which("bash"),
                    "git": shutil.which("git"),
                    "tmux": str(fake_tmux),
                    "codex": shutil.which("true"),
                },
            }
            script = "from pathlib import Path; Path('FAST_COMPLETE').write_text('done\\n')"
            returned = cr.start_frozen_job(
                paths,
                task,
                {
                    "name": "fast completion",
                    "command": [cr.sys.executable, "-c", script],
                    "completion_marker": "FAST_COMPLETE",
                },
            )
            stored = cr.load_server_job(paths, returned["run_id"])
            assert stored is not None

        self.assertEqual(returned["state"], "SUCCEEDED")
        self.assertEqual(stored["state"], "SUCCEEDED")
        self.assertTrue(stored["completion_marker_present"])

    def test_completion_marker_cannot_resolve_inside_data_link(self) -> None:
        with self.assertRaises(cr.CodexRemoteError) as caught:
            cr.validate_job_completion_marker(
                {"data_links": [{"source": "/srv/data", "target": "data"}]},
                "data/already-complete.marker",
            )
        self.assertEqual(caught.exception.code, "INVALID_JOB_REQUEST")

    def test_frozen_job_rejects_completion_marker_already_in_source(self) -> None:
        home = self.base / "existing-marker-home"
        home.mkdir()
        project_id = "existing-marker-project"
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            paths = cr.ensure_server_layout(project_id)
            source_sha = git(self.root, "rev-parse", "HEAD").stdout.strip()
            git(self.root, "push", str(paths["broker"]), f"HEAD:refs/source/{source_sha}")
            task = {
                "project_id": project_id,
                "project_name": "existing-marker",
                "task_id": "task-source",
                "input_sha": source_sha,
                "result_sha": source_sha,
                "data_links": [],
                "tools": {
                    "bash": shutil.which("bash"),
                    "git": shutil.which("git"),
                    "tmux": shutil.which("true"),
                    "codex": shutil.which("true"),
                },
            }
            with self.assertRaises(cr.CodexRemoteError) as caught:
                cr.start_frozen_job(
                    paths,
                    task,
                    {
                        "name": "stale marker run",
                        "command": [cr.sys.executable, "-c", "print('not launched')"],
                        "completion_marker": "tracked.txt",
                    },
                )
        self.assertEqual(caught.exception.code, "COMPLETION_MARKER_EXISTS")

    def test_frozen_job_detects_tracked_source_mutation(self) -> None:
        home = self.base / "dirty-job-home"
        home.mkdir()
        project_id = "dirty-experiment-project"
        old_term = signal.getsignal(signal.SIGTERM)
        old_int = signal.getsignal(signal.SIGINT)
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            paths = cr.ensure_server_layout(project_id)
            source_sha = git(self.root, "rev-parse", "HEAD").stdout.strip()
            git(self.root, "push", str(paths["broker"]), f"HEAD:refs/source/{source_sha}")
            task = {
                "project_id": project_id,
                "project_name": "dirty-experiment",
                "task_id": "task-source",
                "input_sha": source_sha,
                "result_sha": source_sha,
                "data_links": [],
                "tools": {
                    "bash": shutil.which("bash"),
                    "git": shutil.which("git"),
                    "tmux": shutil.which("true"),
                    "codex": shutil.which("true"),
                },
            }
            script = (
                "from pathlib import Path; import subprocess; "
                "Path('tracked.txt').write_text('changed during run\\n'); "
                "subprocess.run(['git', 'add', 'tracked.txt'], check=True); "
                "subprocess.run(['git', '-c', 'user.name=Experiment', "
                "'-c', 'user.email=experiment@example.invalid', 'commit', "
                "'-m', 'mutate frozen source'], check=True); "
                "Path('COMPLETE').write_text('done\\n')"
            )
            job = cr.start_frozen_job(
                paths,
                task,
                {
                    "name": "dirty source run",
                    "command": [cr.sys.executable, "-c", script],
                    "completion_marker": "COMPLETE",
                },
            )
            try:
                returncode = cr.server_job_run(project_id, job["run_id"])
            finally:
                signal.signal(signal.SIGTERM, old_term)
                signal.signal(signal.SIGINT, old_int)

            finished = cr.load_server_job(paths, job["run_id"])
            assert finished is not None
            self.assertEqual(returncode, 1)
            self.assertEqual(finished["state"], "SOURCE_DIRTY")
            self.assertEqual(finished["exit_code"], 0)
            self.assertTrue(finished["completion_marker_present"])
            self.assertFalse(finished["source_integrity"]["tracked_clean"])
            self.assertFalse(finished["source_integrity"]["head_matches_source"])
            self.assertIn("tracked.txt", finished["source_integrity"]["tracked_changes"])

    def test_server_runner_launches_only_after_test_from_squashed_result(self) -> None:
        home = self.base / "mediated-home"
        home.mkdir()
        old_term = signal.getsignal(signal.SIGTERM)
        old_int = signal.getsignal(signal.SIGINT)
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            project_id, task_id, paths = ServerRunnerTests.prepare_server_task(self, home)
            task = cr.load_server_task(paths, task_id)
            assert task is not None
            task["job_policy"] = "launch"
            task["test_cmd"] = "grep -q CODEX tracked.txt"
            fake_codex = Path(task["tools"]["codex"])
            request = {
                "schema_version": cr.SCHEMA_VERSION,
                "name": "mediated launch",
                "command": [cr.sys.executable, "-c", "print('job')"],
                "gpus": "0,1",
                "completion_marker": "",
                "resume_command": "",
                "metadata": {"panel": "heldout"},
                "requested_at": cr.utc_now(),
            }
            fake_codex.write_text(
                "#!/usr/bin/env python3\n"
                "import json, pathlib, sys\n"
                "sys.stdin.read()\n"
                "root = pathlib.Path.cwd()\n"
                "(root / 'tracked.txt').write_text('one\\ntwo\\nCODEX\\nfour\\n')\n"
                f"(root / {cr.JOB_REQUEST_RELATIVE!r}).write_text(json.dumps({request!r}))\n"
                "print(json.dumps({'type': 'thread.started', 'thread_id': 'thread-job'}), flush=True)\n"
                "print(json.dumps({'type': 'turn.completed'}), flush=True)\n",
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)
            cr.save_server_task(paths, task)
            try:
                returncode = cr.server_run(project_id, task_id)
            finally:
                signal.signal(signal.SIGTERM, old_term)
                signal.signal(signal.SIGINT, old_int)

            finished = cr.load_server_task(paths, task_id)
            assert finished is not None
            self.assertEqual(returncode, 0)
            self.assertEqual(finished["state"], "READY")
            self.assertEqual(finished["tests"]["exit_code"], 0)
            self.assertIn("launched_job", finished)
            run_id = finished["launched_job"]["run_id"]
            job = cr.load_server_job(paths, run_id)
            assert job is not None
            self.assertEqual(job["source_sha"], finished["result_sha"])
            self.assertEqual(job["source_task_id"], task_id)
            self.assertEqual(job["metadata"]["panel"], "heldout")
            tree_paths = command(
                "git", "--git-dir", paths["broker"], "ls-tree", "-r", "--name-only", finished["result_sha"]
            ).stdout.splitlines()
            self.assertNotIn(cr.JOB_REQUEST_RELATIVE, tree_paths)

    def test_runner_refuses_job_launch_without_configured_test(self) -> None:
        home = self.base / "no-test-home"
        home.mkdir()
        old_term = signal.getsignal(signal.SIGTERM)
        old_int = signal.getsignal(signal.SIGINT)
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            project_id, task_id, paths = ServerRunnerTests.prepare_server_task(self, home)
            task = cr.load_server_task(paths, task_id)
            assert task is not None
            task["job_policy"] = "launch"
            task["test_cmd"] = None
            fake_codex = Path(task["tools"]["codex"])
            request = {
                "schema_version": cr.SCHEMA_VERSION,
                "name": "must not launch",
                "command": [cr.sys.executable, "-c", "print('unsafe launch')"],
                "gpus": "0,1",
                "completion_marker": "",
                "resume_command": "",
                "metadata": {},
                "requested_at": cr.utc_now(),
            }
            fake_codex.write_text(
                "#!/usr/bin/env python3\n"
                "import json, pathlib, sys\n"
                "sys.stdin.read()\n"
                "root = pathlib.Path.cwd()\n"
                "(root / 'tracked.txt').write_text('one\\ntwo\\nCODEX\\nfour\\n')\n"
                f"(root / {cr.JOB_REQUEST_RELATIVE!r}).write_text(json.dumps({request!r}))\n"
                "print(json.dumps({'type': 'turn.completed'}), flush=True)\n",
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)
            cr.save_server_task(paths, task)
            try:
                returncode = cr.server_run(project_id, task_id)
            finally:
                signal.signal(signal.SIGTERM, old_term)
                signal.signal(signal.SIGINT, old_int)

            finished = cr.load_server_task(paths, task_id)
            assert finished is not None
            self.assertEqual(returncode, 0)
            self.assertEqual(finished["state"], "READY_JOB_NOT_LAUNCHED")
            self.assertIn("No test command is configured", finished["job_launch_error"])
            self.assertNotIn("launched_job", finished)
            self.assertEqual(list(paths["jobs_state"].glob("*/run.json")), [])

    def test_analysis_command_is_noninteractive_and_read_only(self) -> None:
        job = {
            "tools": {"codex": "/opt/codex"},
            "state_dir": "/tmp/run-state",
            "model": "gpt-test",
            "profile": "server",
            "reasoning_effort": "high",
        }
        command_value = cr.job_analysis_command(job)
        self.assertEqual(command_value[:4], ["/opt/codex", "--ask-for-approval", "never", "exec"])
        self.assertEqual(command_value[command_value.index("--sandbox") + 1], "read-only")
        self.assertIn("--output-schema", command_value)
        self.assertIn("--output-last-message", command_value)
        self.assertEqual(command_value[-1], "-")
        audit_command = cr.job_audit_command(job)
        self.assertEqual(audit_command[audit_command.index("--sandbox") + 1], "read-only")
        self.assertTrue(any(value.endswith("audit-schema.json") for value in audit_command))

    def test_blocking_audit_cannot_be_overruled_by_positive_analysis(self) -> None:
        audit = {
            "run_integrity": "invalid",
            "implementation_matches_claim": "no",
            "blocking_defects": ["the configured model was never invoked"],
        }
        analysis = {"run_complete": True, "evidence_status": "positive"}
        with self.assertRaises(cr.CodexRemoteError) as caught:
            cr.validate_job_review_consistency(audit, analysis)
        self.assertEqual(caught.exception.code, "JOB_REVIEW_INCONSISTENT")

        incomplete = {
            "run_integrity": "incomplete",
            "implementation_matches_claim": "uncertain",
            "blocking_defects": [],
        }
        cr.validate_job_review_consistency(
            incomplete,
            {"run_complete": False, "evidence_status": "incomplete"},
        )

    def test_weak_analysis_requires_actionable_continuation_or_justified_stop(self) -> None:
        base = {
            "evidence_status": "valid_negative",
            "stopping_assessment": "One run does not meet a scientific kill criterion.",
            "stop_recommended": False,
            "stopping_criterion_met": False,
            "alternative_explanations": ["The representation may be mismatched."],
            "decisive_followups": [],
            "future_directions": [],
            "salvageable_contributions": [],
        }
        with self.assertRaises(cr.CodexRemoteError) as caught:
            cr.validate_job_analysis_actionability(base)
        self.assertEqual(caught.exception.code, "JOB_ANALYSIS_NOT_ACTIONABLE")

        bounded = dict(base)
        bounded["decisive_followups"] = ["Run the predeclared 100-example control."]
        cr.validate_job_analysis_actionability(bounded)

        stopped = dict(base)
        stopped["stop_recommended"] = True
        stopped["stopping_criterion_met"] = True
        stopped["stopping_assessment"] = (
            "The preregistered kill criterion was met on both datasets; stop because "
            "the calibrated baseline is within the declared equivalence margin."
        )
        cr.validate_job_analysis_actionability(stopped)

        for misleading in (
            "The stopping criterion was not met, so this run alone cannot end the direction.",
            "Do not stop because the evidence is incomplete and no kill criterion was tested.",
        ):
            negated = dict(base)
            negated["stopping_assessment"] = misleading
            with self.assertRaises(cr.CodexRemoteError):
                cr.validate_job_analysis_actionability(negated)

    def test_negative_analysis_requires_alternative_explanation(self) -> None:
        with self.assertRaises(cr.CodexRemoteError) as caught:
            cr.validate_job_analysis_actionability(
                {
                    "evidence_status": "mixed",
                    "stopping_assessment": "Continue until the kill criterion is evaluated.",
                    "stop_recommended": False,
                    "stopping_criterion_met": False,
                    "alternative_explanations": [],
                    "decisive_followups": ["Run the leakage control."],
                    "future_directions": [],
                    "salvageable_contributions": [],
                }
            )
        self.assertEqual(caught.exception.code, "JOB_ANALYSIS_NOT_ACTIONABLE")

    def test_invalid_analysis_cannot_recommend_scientific_stop(self) -> None:
        with self.assertRaises(cr.CodexRemoteError) as caught:
            cr.validate_job_analysis_actionability(
                {
                    "evidence_status": "invalid",
                    "stopping_assessment": "A named criterion appears met in invalid output.",
                    "stop_recommended": True,
                    "stopping_criterion_met": True,
                    "alternative_explanations": [],
                    "decisive_followups": [],
                    "future_directions": [],
                    "salvageable_contributions": [],
                }
            )
        self.assertEqual(caught.exception.code, "JOB_ANALYSIS_NOT_ACTIONABLE")

    def test_analysis_launcher_refuses_planted_runner_helper_symlink(self) -> None:
        home = self.base / "helper-symlink-home"
        home.mkdir()
        project_id = "helper-symlink-project"
        target = home / "important-user-file"
        target.write_text("preserve me\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            paths = cr.ensure_server_layout(project_id)
            state_dir = paths["jobs_state"] / "run-helper-link"
            (state_dir / "results").mkdir(parents=True)
            (state_dir / "checkpoints").mkdir()
            (state_dir / "codex-job-runner.py").symlink_to(target)
            job = {
                "schema_version": cr.SCHEMA_VERSION,
                "project_id": project_id,
                "run_id": "run-helper-link",
                "name": "helper link",
                "state": "SUCCEEDED",
                "created_at": cr.utc_now(),
                "finished_at": cr.utc_now(),
                "state_dir": str(state_dir),
                "worktree": str(self.root),
                "results_dir": str(state_dir / "results"),
                "checkpoints_dir": str(state_dir / "checkpoints"),
                "source_sha": git(self.root, "rev-parse", "HEAD").stdout.strip(),
                "tools": {"tmux": "/bin/true", "bash": "/bin/sh"},
                "data_links": [],
            }
            cr.seal_job_artifacts(job)
            cr.save_server_job(paths, job)
            with self.assertRaises(cr.CodexRemoteError) as caught:
                cr.server_job_summarize(project_id, "run-helper-link")
        self.assertEqual(caught.exception.code, "UNSAFE_STATE_FILE")
        self.assertEqual(target.read_text(encoding="utf-8"), "preserve me\n")

    def test_local_export_extraction_rejects_links_and_traversal(self) -> None:
        safe_archive = self.base / "safe-export.tar.gz"
        payload = b"report\n"
        with tarfile.open(safe_archive, "w:gz") as archive:
            info = tarfile.TarInfo("run-safe/analysis.md")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
        destination = self.base / "pulled" / "run-safe"
        count = cr.extract_job_export(
            safe_archive, destination, "run-safe", max_unpacked_bytes=1024
        )
        self.assertEqual(count, 1)
        self.assertEqual((destination / "analysis.md").read_bytes(), payload)

        unsafe_archive = self.base / "unsafe-export.tar.gz"
        with tarfile.open(unsafe_archive, "w:gz") as archive:
            info = tarfile.TarInfo("run-safe/link")
            info.type = tarfile.SYMTYPE
            info.linkname = "../../outside"
            archive.addfile(info)
        with self.assertRaises(cr.CodexRemoteError) as caught:
            cr.extract_job_export(
                unsafe_archive,
                self.base / "pulled" / "unsafe",
                "run-safe",
                max_unpacked_bytes=1024,
            )
        self.assertEqual(caught.exception.code, "UNSAFE_EXPORT_ARCHIVE")

    def test_pulled_export_validates_selection_and_detects_local_edits(self) -> None:
        destination = self.base / "validated-pull"
        destination.mkdir()
        (destination / "analysis.md").write_text("analysis\n", encoding="utf-8")
        selection_base = {
            "schema_version": 1,
            "project_id": "project",
            "run_id": "run-safe",
            "profile": "report",
            "created_at": "2026-01-01T00:00:00+00:00",
            "source_sha": "a" * 40,
            "files": [
                {
                    "path": "analysis.md",
                    "size": (destination / "analysis.md").stat().st_size,
                    "sha256": cr.sha256_file(destination / "analysis.md"),
                }
            ],
            "omitted": [],
            "selected_artifacts_verified": True,
            "complete_artifact_set_verified": False,
            "sealed_post_hoc": False,
            "provenance_warning": "",
        }
        snapshot = cr.hashlib.sha256(
            cr.json.dumps(selection_base, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        cr.atomic_write_json(
            destination / "export-selection.json",
            {**selection_base, "snapshot_sha256": snapshot},
        )
        cr.validate_pulled_export(
            destination, "run-safe", "report", snapshot, allow_pull_marker=False
        )
        (destination / "analysis.md").write_text("edited\n", encoding="utf-8")
        with self.assertRaises(cr.CodexRemoteError) as caught:
            cr.validate_pulled_export(
                destination, "run-safe", "report", snapshot, allow_pull_marker=False
            )
        self.assertEqual(caught.exception.code, "EXPORT_HASH_MISMATCH")

    def test_legacy_report_is_metadata_only_and_full_export_is_post_hoc(self) -> None:
        home = self.base / "legacy-export-home"
        home.mkdir()
        project_id = "legacy-export-project"
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            paths = cr.ensure_server_layout(project_id)
            state_dir = paths["jobs_state"] / "run-legacy"
            (state_dir / "results").mkdir(parents=True)
            (state_dir / "checkpoints").mkdir()
            (state_dir / "results/legacy.json").write_text("{}\n", encoding="utf-8")
            job = {
                "schema_version": cr.SCHEMA_VERSION,
                "project_id": project_id,
                "run_id": "run-legacy",
                "name": "legacy",
                "state": "SUCCEEDED",
                "created_at": cr.utc_now(),
                "finished_at": cr.utc_now(),
                "state_dir": str(state_dir),
                "worktree": str(self.root),
                "results_dir": str(state_dir / "results"),
                "checkpoints_dir": str(state_dir / "checkpoints"),
                "source_sha": git(self.root, "rev-parse", "HEAD").stdout.strip(),
                "tools": {},
            }
            cr.save_server_job(paths, job)
            report = cr.server_job_export(project_id, "run-legacy", "report")
            with tarfile.open(report["archive"], "r:gz") as handle:
                report_names = set(handle.getnames())
            self.assertNotIn("run-legacy/results/legacy.json", report_names)
            self.assertFalse(report["selected_artifacts_verified"])
            self.assertIn("metadata-only", report["provenance_warning"])

            full = cr.server_job_export(project_id, "run-legacy", "full")
            with tarfile.open(full["archive"], "r:gz") as handle:
                full_names = set(handle.getnames())
            self.assertIn("run-legacy/results/legacy.json", full_names)
            self.assertTrue(full["complete_artifact_set_verified"])
            self.assertTrue(full["sealed_post_hoc"])

    def test_job_artifact_manifest_rejects_symlinks(self) -> None:
        state_dir = self.base / "symlink-artifact"
        results = state_dir / "results"
        checkpoints = state_dir / "checkpoints"
        results.mkdir(parents=True)
        checkpoints.mkdir()
        (results / "outside").symlink_to(self.base)
        with self.assertRaises(cr.CodexRemoteError) as caught:
            cr.build_job_artifact_manifest(
                {
                    "state_dir": str(state_dir),
                    "results_dir": str(results),
                    "checkpoints_dir": str(checkpoints),
                }
            )
        self.assertEqual(caught.exception.code, "UNSAFE_JOB_ARTIFACT")
        (results / "outside").unlink()
        results.rmdir()
        results.symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(cr.CodexRemoteError) as caught:
            cr.build_job_artifact_manifest(
                {
                    "state_dir": str(state_dir),
                    "results_dir": str(results),
                    "checkpoints_dir": str(checkpoints),
                }
            )
        self.assertEqual(caught.exception.code, "UNSAFE_JOB_ARTIFACT")

    def test_analysis_runs_independent_audit_before_interpretation(self) -> None:
        home = self.base / "two-pass-analysis-home"
        home.mkdir()
        project_id = "two-pass-analysis-project"
        audit = {
            "run_integrity": "auditable",
            "implementation_matches_claim": "yes",
            "summary": "The invoked implementation and artifacts match the contract.",
            "evidence_manifest_path": "results/evidence-manifest.json",
            "identity_and_split_evidence_verified": True,
            "audited_paths": ["train.py", "results/metrics.json"],
            "manifest_checks": ["source and command verified"],
            "data_and_split_checks": ["patient groups are disjoint"],
            "implementation_checks": ["configured model is invoked"],
            "metric_and_statistics_checks": ["patient is the resampling unit"],
            "leakage_or_contamination_risks": [],
            "anomalies": [],
            "blocking_defects": [],
            "repair_actions": [],
            "residual_risks": ["external dataset provenance was not re-downloaded"],
        }
        analysis = {
            "run_complete": True,
            "evidence_status": "valid_negative",
            "claim_tested": "The proposed method beats calibrated late fusion.",
            "summary": "The run is a valid negative result for this configuration.",
            "source_and_command": "source abc; python train.py",
            "audit_disposition": "Auditable with one residual provenance risk.",
            "coverage_checks": ["all planned seeds present"],
            "headline_results": ["difference from baseline is near zero"],
            "effect_and_uncertainty": ["paired interval includes zero"],
            "anomalies": [],
            "supported_conclusions": ["no advantage in this setting"],
            "unsupported_conclusions": ["the entire direction is nonviable"],
            "alternative_explanations": ["conditional independence already holds"],
            "decisive_followups": ["run the preregistered dependence stress test"],
            "future_directions": ["retain the version-staleness benchmark"],
            "salvageable_contributions": ["calibrated negative-result benchmark"],
            "stop_recommended": False,
            "stopping_criterion_met": False,
            "stopping_assessment": "The global kill criterion is not yet met.",
            "recommended_actions": ["perform one bounded decisive follow-up"],
        }
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            paths = cr.ensure_server_layout(project_id)
            state_dir = paths["jobs_state"] / "run-two-pass"
            state_dir.mkdir(parents=True)
            (state_dir / "results").mkdir()
            (state_dir / "checkpoints").mkdir()
            fake_codex = home / "codex"
            payloads = {"audit.json": audit, "analysis.json": analysis}
            fake_codex.write_text(
                "#!/usr/bin/env python3\n"
                "import json, pathlib, sys\n"
                "sys.stdin.read()\n"
                f"payloads = {payloads!r}\n"
                "output = pathlib.Path(sys.argv[sys.argv.index('--output-last-message') + 1])\n"
                "output.write_text(json.dumps(payloads[output.name]), encoding='utf-8')\n"
                "print(json.dumps({'type': 'turn.completed'}), flush=True)\n",
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)
            job = {
                "schema_version": cr.SCHEMA_VERSION,
                "project_id": project_id,
                "run_id": "run-two-pass",
                "name": "two-pass",
                "state": "SUCCEEDED",
                "created_at": cr.utc_now(),
                "state_dir": str(state_dir),
                "worktree": str(self.root),
                "results_dir": str(state_dir / "results"),
                "checkpoints_dir": str(state_dir / "checkpoints"),
                "source_sha": git(self.root, "rev-parse", "HEAD").stdout.strip(),
                "command": ["true"],
                "tools": {"codex": str(fake_codex)},
            }
            cr.atomic_write_json(
                state_dir / "results/evidence-manifest.json",
                {
                    "dataset_manifest_sha256": "d" * 64,
                    "split_manifest_sha256": "5" * 64,
                    "membership_evidence_sha256": "e" * 64,
                    "expected_counts": {"test": 10},
                    "observed_counts": {"test": 10},
                },
            )
            cr.seal_job_artifacts(job)
            cr.save_server_job(paths, job)
            returncode = cr.server_job_analyze(project_id, "run-two-pass")
            finished = cr.load_server_job(paths, "run-two-pass")
            assert finished is not None
        self.assertEqual(returncode, 0)
        self.assertEqual(finished["analysis"]["state"], "SUCCEEDED")
        self.assertIn("Implementation matches claim:** yes", (state_dir / "audit.md").read_text())
        rendered = (state_dir / "analysis.md").read_text()
        self.assertIn("Evidence status:** valid_negative", rendered)
        self.assertIn("Future directions", rendered)

    def test_missing_identity_evidence_is_downgraded_but_still_interpreted(self) -> None:
        home = self.base / "incomplete-analysis-home"
        home.mkdir()
        project_id = "incomplete-analysis-project"
        audit = {
            "run_integrity": "auditable",
            "implementation_matches_claim": "yes",
            "summary": "The implementation appears to match.",
            "evidence_manifest_path": "results/evidence-manifest.json",
            "identity_and_split_evidence_verified": True,
            "audited_paths": [],
            "manifest_checks": [],
            "data_and_split_checks": [],
            "implementation_checks": [],
            "metric_and_statistics_checks": [],
            "leakage_or_contamination_risks": [],
            "anomalies": [],
            "blocking_defects": [],
            "repair_actions": [],
            "residual_risks": [],
        }
        analysis = {
            "run_complete": False,
            "evidence_status": "incomplete",
            "claim_tested": "candidate claim",
            "summary": "Identity evidence is missing; the direction is not rejected.",
            "source_and_command": "sealed source",
            "audit_disposition": "incomplete",
            "coverage_checks": [],
            "headline_results": [],
            "effect_and_uncertainty": [],
            "anomalies": [],
            "supported_conclusions": [],
            "unsupported_conclusions": ["the direction is nonviable"],
            "alternative_explanations": ["the output contract was miswritten"],
            "decisive_followups": ["repair and smoke-test the evidence writer"],
            "future_directions": ["retain the scientific hypothesis"],
            "salvageable_contributions": ["the evaluator implementation"],
            "stop_recommended": False,
            "stopping_criterion_met": False,
            "stopping_assessment": "No scientific kill criterion was evaluated.",
            "recommended_actions": ["run one bounded repaired experiment"],
        }
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            paths = cr.ensure_server_layout(project_id)
            state_dir = paths["jobs_state"] / "run-incomplete"
            (state_dir / "results").mkdir(parents=True)
            (state_dir / "checkpoints").mkdir()
            fake_codex = home / "codex"
            payloads = {"audit.json": audit, "analysis.json": analysis}
            fake_codex.write_text(
                "#!/usr/bin/env python3\n"
                "import json, pathlib, sys\n"
                "sys.stdin.read()\n"
                f"payloads = {payloads!r}\n"
                "output = pathlib.Path(sys.argv[sys.argv.index('--output-last-message') + 1])\n"
                "output.write_text(json.dumps(payloads[output.name]), encoding='utf-8')\n",
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)
            job = {
                "schema_version": cr.SCHEMA_VERSION,
                "project_id": project_id,
                "run_id": "run-incomplete",
                "name": "incomplete",
                "state": "SUCCEEDED",
                "created_at": cr.utc_now(),
                "state_dir": str(state_dir),
                "worktree": str(self.root),
                "results_dir": str(state_dir / "results"),
                "checkpoints_dir": str(state_dir / "checkpoints"),
                "source_sha": git(self.root, "rev-parse", "HEAD").stdout.strip(),
                "command": ["true"],
                "tools": {"codex": str(fake_codex)},
            }
            cr.seal_job_artifacts(job)
            cr.save_server_job(paths, job)
            returncode = cr.server_job_analyze(project_id, "run-incomplete")
            finished_audit = cr.read_json(state_dir / "audit.json")
        self.assertEqual(returncode, 0)
        assert finished_audit is not None
        self.assertEqual(finished_audit["run_integrity"], "incomplete")
        self.assertEqual(finished_audit["blocking_defects"], [])
        self.assertTrue(
            any(
                "Mechanical identity-evidence gate failed" in item
                for item in finished_audit["manifest_checks"]
            )
        )
        self.assertIn("Future directions", (state_dir / "analysis.md").read_text())

    def test_failed_analysis_cannot_reuse_stale_structured_output(self) -> None:
        home = self.base / "analysis-home"
        home.mkdir()
        project_id = "analysis-project"
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            paths = cr.ensure_server_layout(project_id)
            state_dir = paths["jobs_state"] / "run-analysis"
            state_dir.mkdir(parents=True)
            (state_dir / "results").mkdir()
            (state_dir / "checkpoints").mkdir()
            fake_codex = home / "codex"
            fake_codex.write_text(
                "#!/bin/sh\ncat >/dev/null\nexit 0\n",
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)
            stale = {
                "run_complete": True,
                "summary": "stale",
                "source_and_command": "stale",
                "coverage_checks": [],
                "headline_results": [],
                "anomalies": [],
                "supported_conclusions": [],
                "unsupported_conclusions": [],
                "recommended_actions": [],
            }
            cr.atomic_write_json(state_dir / "analysis.json", stale)
            (state_dir / "analysis.md").write_text("stale\n", encoding="utf-8")
            job = {
                "schema_version": cr.SCHEMA_VERSION,
                "project_id": project_id,
                "run_id": "run-analysis",
                "name": "analysis",
                "state": "SUCCEEDED",
                "created_at": cr.utc_now(),
                "state_dir": str(state_dir),
                "worktree": str(self.root),
                "results_dir": str(state_dir / "results"),
                "checkpoints_dir": str(state_dir / "checkpoints"),
                "source_sha": git(self.root, "rev-parse", "HEAD").stdout.strip(),
                "command": ["true"],
                "tools": {"codex": str(fake_codex)},
            }
            cr.seal_job_artifacts(job)
            cr.save_server_job(paths, job)
            returncode = cr.server_job_analyze(project_id, "run-analysis")
            finished = cr.load_server_job(paths, "run-analysis")
            assert finished is not None

        self.assertEqual(returncode, 1)
        self.assertEqual(finished["analysis"]["state"], "FAILED")
        self.assertFalse((state_dir / "analysis.json").exists())
        self.assertFalse((state_dir / "analysis.md").exists())

    def test_global_agents_install_preserves_user_content_and_replaces_managed_block(self) -> None:
        home = self.base / "agents-home"
        home.mkdir()
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            target = home / ".codex" / "AGENTS.md"
            target.parent.mkdir()
            target.write_text("# My existing instructions\n\nKeep this.\n", encoding="utf-8")
            content = "# Managed\n\n- First version.\n"
            payload = {
                "content": content,
                "sha256": cr.hashlib.sha256(content.encode("utf-8")).hexdigest(),
            }
            cr.server_install_agents("agents-project", payload)
            replacement = "# Managed\n\n- Replacement.\n"
            payload = {
                "content": replacement,
                "sha256": cr.hashlib.sha256(replacement.encode("utf-8")).hexdigest(),
            }
            cr.server_install_agents("agents-project", payload)
            value = target.read_text(encoding="utf-8")

        self.assertIn("# My existing instructions", value)
        self.assertIn("Keep this.", value)
        self.assertIn("- Replacement.", value)
        self.assertNotIn("- First version.", value)
        self.assertEqual(value.count(cr.GLOBAL_AGENTS_BEGIN), 1)
        self.assertEqual(value.count(cr.GLOBAL_AGENTS_END), 1)


    def test_global_agents_install_rejects_duplicate_managed_markers(self) -> None:
        home = self.base / "duplicate-agents-home"
        home.mkdir()
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            target = home / ".codex" / "AGENTS.md"
            target.parent.mkdir()
            target.write_text(
                f"{cr.GLOBAL_AGENTS_BEGIN}\nfirst\n{cr.GLOBAL_AGENTS_END}\n"
                f"{cr.GLOBAL_AGENTS_BEGIN}\nsecond\n{cr.GLOBAL_AGENTS_END}\n",
                encoding="utf-8",
            )
            content = "# Managed\n"
            payload = {
                "content": content,
                "sha256": cr.hashlib.sha256(content.encode("utf-8")).hexdigest(),
            }
            with self.assertRaises(cr.CodexRemoteError) as caught:
                cr.server_install_agents("agents-project", payload)
        self.assertEqual(caught.exception.code, "MALFORMED_MANAGED_BLOCK")


class PromptInputTests(RepositoryTestCase):
    def test_subprocess_without_explicit_input_cannot_consume_parent_stdin(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["true"], returncode=0, stdout="", stderr=""
        )
        with mock.patch.object(cr.subprocess, "run", return_value=completed) as run_mock:
            cr.run(["true"])

        self.assertIs(run_mock.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def test_start_captures_stdin_prompt_before_remote_preflight(self) -> None:
        args = argparse.Namespace(prompt_file="-", max_untracked_bytes=1024)
        observed_stdin = []

        def stop_at_remote_probe(host: str, timeout: int):
            observed_stdin.append(cr.sys.stdin.read())
            raise RuntimeError("stop after prompt capture")

        with (
            mock.patch.object(cr.sys, "stdin", io.StringIO("remote prompt\n")),
            mock.patch.object(
                cr,
                "common_local_args",
                return_value=(self.root, "rhel-test", "/srv/repo", 5, "repo-test", "repo"),
            ),
            mock.patch.object(cr, "check_startable_local"),
            mock.patch.object(cr, "ensure_remote_helper", side_effect=stop_at_remote_probe),
        ):
            with self.assertRaisesRegex(RuntimeError, "stop after prompt capture"):
                cr.cmd_start(args)

        self.assertEqual(observed_stdin, [""])


class MiscellaneousTests(RepositoryTestCase):
    def interactive_start_args(self) -> argparse.Namespace:
        return argparse.Namespace(
            project_root=str(self.root),
            host="rhel-test",
            remote_dir="/srv/repo",
            timeout=5,
            max_untracked_bytes=1024 * 1024,
            bootstrap_cmd="",
            test_cmd="",
            data_link=[],
            model="",
            profile="",
            reasoning_effort="",
            enable_search=False,
            job_policy="launch",
        )

    def test_interactive_start_accepts_dirty_tracked_named_local_branch(self) -> None:
        args = self.interactive_start_args()
        tracked = self.root / "tracked.txt"
        tracked.write_text("one\nSTAGED\nthree\nfour\n", encoding="utf-8")
        git(self.root, "add", "tracked.txt")
        tracked.write_text("one\nSTAGED\nUNSTAGED\nfour\n", encoding="utf-8")

        with (
            mock.patch.object(
                cr, "ensure_remote_helper", return_value={"helper": "/helper"}
            ),
            mock.patch.object(
                cr,
                "remote_invoke",
                return_value={"remote": {"broker": "/tmp/broker"}},
            ),
            mock.patch.object(
                cr, "remote_status", return_value={"task": {"state": "NONE"}}
            ),
            mock.patch.object(
                cr, "local_current_path", return_value=self.base / "current.json"
            ),
            mock.patch.object(
                cr,
                "create_hidden_snapshot",
                side_effect=RuntimeError("tracked-only snapshot requested"),
            ) as snapshot,
        ):
            with self.assertRaisesRegex(
                RuntimeError, "tracked-only snapshot requested"
            ):
                cr.start_new_task(args, execution_mode="interactive", prompt=None)

        self.assertTrue(snapshot.call_args.kwargs["include_untracked"] is False)
        tracked_status = cr.tracked_status_porcelain(self.root)
        self.assertIn("tracked.txt", tracked_status)
        self.assertNotIn("??", tracked_status)

    def test_interactive_start_requires_named_local_branch(self) -> None:
        args = self.interactive_start_args()
        git(self.root, "checkout", "--detach")
        with (
            mock.patch.object(cr, "ensure_remote_helper", return_value={"helper": "/helper"}),
            mock.patch.object(
                cr,
                "remote_invoke",
                return_value={"remote": {"broker": "/tmp/broker"}},
            ),
            mock.patch.object(
                cr, "remote_status", return_value={"task": {"state": "NONE"}}
            ),
            mock.patch.object(cr, "local_current_path", return_value=self.base / "current.json"),
        ):
            with self.assertRaises(cr.CodexRemoteError) as caught:
                cr.start_new_task(args, execution_mode="interactive", prompt=None)
        self.assertEqual(caught.exception.code, "INTERACTIVE_REQUIRES_BRANCH")

    def test_interactive_start_ignores_untracked_files_entirely(self) -> None:
        args = self.interactive_start_args()
        untracked = {
            ".env": "LOCAL_ONLY=1\n",
            "codex_remote_smoke_test.txt": "local smoke output\n",
            "reports/bootstrap-summary.md": "generated locally\n",
        }
        for relative, content in untracked.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        with mock.patch.object(
            cr,
            "ensure_remote_helper",
            side_effect=RuntimeError("stop after local interactive preflight"),
        ):
            with self.assertRaisesRegex(
                RuntimeError, "stop after local interactive preflight"
            ):
                cr.start_new_task(args, execution_mode="interactive", prompt=None)

        self.assertEqual(cr.tracked_status_porcelain(self.root), "")
        status = cr.git_status_porcelain(self.root)
        for relative in untracked:
            self.assertIn(f"?? {relative}", status)
        head = cr.current_head(self.root)
        for relative in untracked:
            self.assertNotEqual(
                git(self.root, "cat-file", "-e", f"{head}:{relative}", check=False).returncode,
                0,
            )

    def remote_probe(self, helper_hash: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                "__CODEX_REMOTE_PY__/opt/python3.12\n"
                "__CODEX_REMOTE_PYVER__3.12.8\n"
                "__CODEX_REMOTE_HOME__/home/remote\n"
                f"__CODEX_REMOTE_HELPER_SHA__{helper_hash}\n"
            ),
            stderr="",
        )

    def test_remote_helper_probe_reuses_matching_copy(self) -> None:
        source_hash = cr.sha256_file(BACKEND)
        with mock.patch.object(
            cr,
            "ssh_login_shell",
            return_value=self.remote_probe(source_hash),
        ) as ssh:
            context = cr.ensure_remote_helper("rhel-test", 5)

        ssh.assert_called_once()
        self.assertEqual(context["python"], "/opt/python3.12")
        self.assertEqual(context["python_version"], "3.12.8")
        self.assertEqual(
            context["helper"],
            "/home/remote/.local/libexec/codex-remote",
        )
        self.assertEqual(context["helper_sha256"], source_hash)

    def test_remote_helper_probe_updates_stale_copy_atomically(self) -> None:
        responses = [
            self.remote_probe("old-hash"),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        ]
        with mock.patch.object(
            cr,
            "ssh_login_shell",
            side_effect=responses,
        ) as ssh:
            context = cr.ensure_remote_helper("rhel-test", 5)

        self.assertEqual(ssh.call_count, 2)
        install_call = ssh.call_args_list[1]
        self.assertEqual(install_call.kwargs["input_data"], BACKEND.read_bytes())
        self.assertIn("mv -f", install_call.args[1])
        self.assertEqual(context["python"], "/opt/python3.12")

    def test_data_link_rejects_symlink_parent_escape(self) -> None:
        source = self.base / "dataset"
        source.mkdir()
        outside = self.base / "outside"
        outside.mkdir()
        (self.root / "linked-parent").symlink_to(outside, target_is_directory=True)
        task = {
            "worktree": str(self.root),
            "data_links": [
                {"source": str(source), "target": "linked-parent/data"},
            ],
        }

        with self.assertRaises(cr.CodexRemoteError) as caught:
            cr.create_data_links(task)
        self.assertEqual(caught.exception.code, "DATA_LINK_TAMPERED")
        self.assertFalse((outside / "data").exists())

    def test_secret_template_names_are_allowed_but_live_secret_names_are_blocked(self) -> None:
        self.assertFalse(cr.path_is_secret(".env.example"))
        self.assertFalse(cr.path_is_secret("config/credentials.template"))
        self.assertTrue(cr.path_is_secret(".env"))
        self.assertTrue(cr.path_is_secret(".env.production"))
        self.assertTrue(cr.path_is_secret("credentials.json"))
        self.assertTrue(cr.path_is_secret(".ssh/id_rsa.example"))

    def test_project_identity_uses_host_and_remote_directory(self) -> None:
        one = cr.project_identity(self.root, "rhel-test", "/srv/a")[0]
        two = cr.project_identity(self.root, "rhel-test", "/srv/b")[0]
        three = cr.project_identity(self.root, "other-host", "/srv/a")[0]
        self.assertNotEqual(one, two)
        self.assertNotEqual(one, three)
        self.assertRegex(one, r"^repo-[0-9a-f]{12}$")

    def test_status_reconciles_matching_local_task_state(self) -> None:
        local = {"task_id": "task-1", "state": "STARTING", "local_branch": "main"}
        task = {"task_id": "task-1", "state": "FAILED", "error": "codex failed"}
        with mock.patch.object(cr, "LOCAL_STATE_ROOT", self.base / "local-state"), \
             mock.patch.object(cr, "atomic_write_json") as write:
            updated = cr.reconcile_local_status("project-1", task, local)

        assert updated is not None
        self.assertEqual(updated["state"], "FAILED")
        self.assertEqual(updated["remote"], task)
        self.assertEqual(updated["local_branch"], "main")
        write.assert_called_once()

    def test_status_does_not_overwrite_pending_remote_ack(self) -> None:
        local = {"task_id": "task-1", "state": "APPLIED_PENDING_REMOTE_ACK"}
        task = {"task_id": "task-1", "state": "READY"}
        with mock.patch.object(cr, "atomic_write_json") as write:
            updated = cr.reconcile_local_status("project-1", task, local)

        self.assertIs(updated, local)
        write.assert_not_called()

    def test_tmux_pane_state_distinguishes_dead_session_from_running_process(self) -> None:
        dead = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1\t2\t123\n", stderr=""
        )
        with mock.patch.object(cr, "run", return_value=dead):
            state = cr.tmux_pane_state(
                {"tools": {"tmux": "/fake/tmux"}, "tmux_session": "session"}
            )
        self.assertTrue(state["exists"])
        self.assertFalse(state["running"])
        self.assertTrue(state["pane_dead"])
        self.assertEqual(state["pane_dead_status"], 2)

    def test_codex_command_uses_noninteractive_workspace_write_mode(self) -> None:
        task = {
            "tools": {"codex": "/opt/codex"},
            "state_dir": "/tmp/state",
            "model": "gpt-test",
            "profile": "server",
            "reasoning_effort": "high",
            "enable_search": True,
        }
        value = cr.codex_command(task)
        self.assertEqual(
            value[:5],
            ["/opt/codex", "--ask-for-approval", "never", "--search", "exec"],
        )
        self.assertLess(value.index("--ask-for-approval"), value.index("exec"))
        self.assertLess(value.index("--search"), value.index("exec"))
        self.assertIn("--json", value)
        self.assertEqual(value[value.index("--sandbox") + 1], "workspace-write")
        self.assertIn("model_reasoning_effort=high", value)
        self.assertTrue(any("developer_instructions=" in item for item in value))
        self.assertEqual(value[-1], "-")

    def test_interactive_codex_command_is_autonomous_inside_workspace(self) -> None:
        state_dir = self.base / "interactive-command-state"
        task = {
            "tools": {"codex": "/opt/codex"},
            "state_dir": str(state_dir),
            "model": "gpt-test",
            "profile": "server",
            "reasoning_effort": "high",
            "approval_policy": "never",
            "network_access": True,
            "enable_search": True,
        }
        value = cr.interactive_codex_command(task)
        self.assertEqual(value[0], "/opt/codex")
        self.assertNotIn("exec", value)
        self.assertEqual(value[value.index("--sandbox") + 1], "workspace-write")
        self.assertEqual(value[value.index("--ask-for-approval") + 1], "never")
        cache = state_dir / "tool-cache"
        self.assertEqual(value[value.index("--add-dir") + 1], str(cache))
        self.assertTrue(cache.is_dir())
        self.assertIn("sandbox_workspace_write.network_access=true", value)
        self.assertIn("features.network_proxy.enabled=true", value)
        self.assertIn('features.network_proxy.domains={ "*" = "allow" }', value)
        self.assertFalse(any("network_proxy.unix_sockets" in item for item in value))
        self.assertIn("--search", value)
        self.assertIn("gpt-test", value)
        self.assertIn("server", value)
        self.assertIn('model_reasoning_effort="high"', value)
        self.assertTrue(any("developer_instructions=" in item for item in value))

    def test_codex_commands_grant_data_link_directories_write_access(self) -> None:
        persistent = self.base / "persistent-data"
        persistent.mkdir()
        file_link = self.base / "manifest.json"
        file_link.write_text("{}\n", encoding="utf-8")
        task = {
            "tools": {"codex": "/opt/codex"},
            "state_dir": str(self.base / "persistent-data-state"),
            "execution_mode": "interactive",
            "approval_policy": "never",
            "network_access": True,
            "enable_search": False,
            "data_links": [
                {"source": str(persistent), "target": "data"},
                {"source": str(file_link), "target": "metadata/manifest.json"},
            ],
        }

        interactive = cr.interactive_codex_command(task)
        noninteractive = cr.codex_command(task)

        self.assertIn(str(persistent), interactive)
        self.assertIn(str(persistent), noninteractive)
        self.assertEqual(
            interactive[interactive.index(str(persistent)) - 1],
            "--add-dir",
        )
        self.assertEqual(
            noninteractive[noninteractive.index(str(persistent)) - 1],
            "--add-dir",
        )
        self.assertNotIn(str(file_link.parent), cr.codex_data_write_directories(task))
        self.assertNotIn(str(file_link), interactive)
        self.assertLess(noninteractive.index(str(persistent)), noninteractive.index("exec"))

    def test_interactive_codex_command_defaults_to_sol_and_xhigh(self) -> None:
        task = {
            "tools": {"codex": "/opt/codex"},
            "state_dir": str(self.base / "interactive-default-state"),
            "model": None,
            "profile": None,
            "reasoning_effort": None,
            "network_access": True,
            "enable_search": False,
        }
        value = cr.interactive_codex_command(task)
        self.assertEqual(value[value.index("--model") + 1], "gpt-5.6-sol")
        self.assertIn('model_reasoning_effort="xhigh"', value)
        self.assertEqual(value[value.index("--ask-for-approval") + 1], "never")

    def test_interactive_codex_environment_uses_task_private_tool_cache(self) -> None:
        state_dir = self.base / "interactive-environment-state"
        task = {
            "execution_mode": "interactive",
            "state_dir": str(state_dir),
            "worktree": str(self.root),
            "job_policy": "deny",
            "commitctl_path": str(state_dir / "codex-commit"),
        }
        env = cr.codex_process_environment(task)
        cache = state_dir / "tool-cache"
        self.assertEqual(env["XDG_CACHE_HOME"], str(cache))
        self.assertEqual(env["UV_CACHE_DIR"], str(cache / "uv"))
        self.assertEqual(env["PIP_CACHE_DIR"], str(cache / "pip"))
        self.assertEqual(env["UV_PROJECT_ENVIRONMENT"], str(self.root / ".venv"))
        self.assertEqual(env["PYTHONNOUSERSITE"], "1")
        self.assertEqual(env["GIT_AUTHOR_NAME"], "Codex Remote")
        self.assertEqual(env["GIT_AUTHOR_EMAIL"], "codex-remote@localhost")
        self.assertEqual(env["GIT_COMMITTER_NAME"], "Codex Remote")
        self.assertEqual(env["GIT_COMMITTER_EMAIL"], "codex-remote@localhost")
        self.assertEqual(env["CODEX_COMMIT"], str(state_dir / "codex-commit"))
        self.assertEqual(
            env["CODEX_COMMIT_REQUEST_PATH"],
            str(self.root / cr.COMMIT_REQUEST_RELATIVE),
        )
        self.assertTrue(cache.is_dir())

    def test_filtered_dev_environment_excludes_credential_variables(self) -> None:
        value = cr.filtered_dev_environment(
            {
                "PATH": "/nix/store/tools/bin",
                "NIX_CFLAGS_COMPILE": "-isystem /nix/store/include",
                "CARGO_HOME": "/tmp/cargo",
                "RUSTFLAGS": "-C target-cpu=native",
                "CARGO_REGISTRIES_PRIVATE_TOKEN": "do-not-copy",
                "NIX_CONFIG": "access-tokens = github.com=do-not-copy",
                "NIX_SSHOPTS": "-i /home/user/.ssh/id_ed25519",
                "AWS_SECRET_ACCESS_KEY": "not-in-scope",
            }
        )
        self.assertEqual(value["PATH"], "/nix/store/tools/bin")
        self.assertIn("NIX_CFLAGS_COMPILE", value)
        self.assertIn("CARGO_HOME", value)
        self.assertIn("RUSTFLAGS", value)
        self.assertNotIn("CARGO_REGISTRIES_PRIVATE_TOKEN", value)
        self.assertNotIn("NIX_CONFIG", value)
        self.assertNotIn("NIX_SSHOPTS", value)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", value)

    def test_codex_instructions_authorize_project_dependencies_not_host_activation(self) -> None:
        instructions = cr.codex_job_instructions(
            {"execution_mode": "interactive", "job_policy": "deny"}
        )
        self.assertIn("uv add", instructions)
        self.assertIn("$CODEX_DEV", instructions)
        self.assertIn("$CODEX_ENVCTL refresh", instructions)
        self.assertIn("$CODEX_COMMIT", instructions)
        self.assertIn("do not run git add", instructions)
        self.assertIn("cannot contact the Nix daemon directly", instructions)
        self.assertIn("do not stop after merely proposing a plan", instructions)
        self.assertIn("Do not use sudo", instructions)
        self.assertIn("nixos-rebuild", instructions)
        self.assertIn("systemctl", instructions)

    def test_codex_instructions_route_durable_downloads_to_data_links(self) -> None:
        persistent = self.base / "persistent-data-instructions"
        persistent.mkdir()
        instructions = cr.codex_job_instructions(
            {
                "execution_mode": "interactive",
                "job_policy": "deny",
                "data_links": [
                    {"source": str(persistent), "target": "data"},
                ],
            }
        )
        self.assertIn(f"data -> {persistent}", instructions)
        self.assertIn("persistent server storage", instructions)
        self.assertIn("download", instructions)
        self.assertIn("survive task cleanup", instructions)
        self.assertIn("Do not unlink, replace, rename, or repoint", instructions)

    def test_interactive_command_reuses_active_interactive_task(self) -> None:
        args = argparse.Namespace(max_untracked_bytes=1024)
        existing = {
            "task_id": "task-1",
            "state": "RUNNING",
            "execution_mode": "interactive",
            "tmux": {"exists": True, "running": True},
        }
        with (
            mock.patch.object(
                cr,
                "common_local_args",
                return_value=(self.root, "rhel-test", "/srv/repo", 5, "repo-test", "repo"),
            ),
            mock.patch.object(cr, "ensure_remote_helper", return_value={"helper": "/helper"}),
            mock.patch.object(cr, "remote_invoke", return_value={"ok": True}),
            mock.patch.object(cr, "remote_status", return_value={"ok": True, "task": existing}),
            mock.patch.object(cr, "local_current_path", return_value=self.base / "current.json"),
            mock.patch.object(cr, "read_json", return_value=None),
            mock.patch.object(cr, "start_new_task") as start_new,
        ):
            result = cr.cmd_interactive(args)

        self.assertTrue(result["reused"])
        self.assertEqual(result["task"], existing)
        start_new.assert_not_called()

    def test_interactive_command_starts_managed_task_when_project_is_resolved(self) -> None:
        args = argparse.Namespace(max_untracked_bytes=1024)
        expected = {"ok": True, "task": {"state": "STARTING"}}
        with (
            mock.patch.object(
                cr,
                "common_local_args",
                return_value=(self.root, "rhel-test", "/srv/repo", 5, "repo-test", "repo"),
            ),
            mock.patch.object(cr, "ensure_remote_helper", return_value={"helper": "/helper"}),
            mock.patch.object(cr, "remote_invoke", return_value={"ok": True}),
            mock.patch.object(
                cr,
                "remote_status",
                return_value={"ok": True, "task": {"state": "NONE"}},
            ),
            mock.patch.object(cr, "start_new_task", return_value=expected) as start_new,
        ):
            result = cr.cmd_interactive(args)

        self.assertEqual(result, expected)
        start_new.assert_called_once_with(
            args, execution_mode="interactive", prompt=None
        )

    def test_interactive_command_does_not_reattach_during_finalization(self) -> None:
        args = argparse.Namespace(max_untracked_bytes=1024)
        existing = {
            "task_id": "task-finalizing",
            "state": "FINALIZING",
            "execution_mode": "interactive",
        }
        with (
            mock.patch.object(
                cr,
                "common_local_args",
                return_value=(self.root, "rhel-test", "/srv/repo", 5, "repo-test", "repo"),
            ),
            mock.patch.object(cr, "ensure_remote_helper", return_value={"helper": "/helper"}),
            mock.patch.object(cr, "remote_invoke", return_value={"ok": True}),
            mock.patch.object(cr, "remote_status", return_value={"ok": True, "task": existing}),
        ):
            with self.assertRaises(cr.CodexRemoteError) as caught:
                cr.cmd_interactive(args)

        self.assertEqual(caught.exception.code, "OUTSTANDING_TASK")
        self.assertIs(caught.exception.details, existing)

    def test_interactive_command_blocks_active_noninteractive_task(self) -> None:
        args = argparse.Namespace(max_untracked_bytes=1024)
        existing = {
            "task_id": "task-exec",
            "state": "RUNNING",
            "execution_mode": "exec",
        }
        with (
            mock.patch.object(
                cr,
                "common_local_args",
                return_value=(self.root, "rhel-test", "/srv/repo", 5, "repo-test", "repo"),
            ),
            mock.patch.object(cr, "ensure_remote_helper", return_value={"helper": "/helper"}),
            mock.patch.object(cr, "remote_invoke", return_value={"ok": True}),
            mock.patch.object(
                cr,
                "remote_status",
                return_value={"ok": True, "task": existing},
            ),
        ):
            with self.assertRaises(cr.CodexRemoteError) as caught:
                cr.cmd_interactive(args)

        self.assertEqual(caught.exception.code, "OUTSTANDING_TASK")
        self.assertIs(caught.exception.details, existing)


    def test_apply_routes_live_interactive_session_through_commit_pull(self) -> None:
        args = argparse.Namespace(max_untracked_bytes=1024)
        task = {
            "task_id": "task-interactive",
            "state": "RUNNING",
            "execution_mode": "interactive",
        }
        expected = {"ok": True, "command": "pull", "changed_commit_count": 2}
        with (
            mock.patch.object(
                cr,
                "common_local_args",
                return_value=(self.root, "rhel-test", "/srv/repo", 5, "repo-test", "repo"),
            ),
            mock.patch.object(cr, "ensure_remote_helper", return_value={"helper": "/helper"}),
            mock.patch.object(cr, "remote_status", return_value={"task": task}),
            mock.patch.object(cr, "local_current_path", return_value=self.base / "current.json"),
            mock.patch.object(cr, "read_json", return_value=None),
            mock.patch.object(cr, "cmd_pull", return_value=expected) as pull,
        ):
            result = cr.cmd_apply(args)

        self.assertEqual(result, expected)
        pull.assert_called_once_with(args)

    def test_project_configuration_is_persisted_for_terminal_frontend(self) -> None:
        args = argparse.Namespace(
            project_root=str(self.root),
            host="rhel-test",
            remote_dir="/srv/repo",
            timeout=7,
            max_untracked_bytes=4096,
            bootstrap_cmd="nix develop --command uv sync --frozen",
            test_cmd="nix develop --command pytest -q",
            data_link=["/srv/data=data"],
            model="gpt-test",
            profile="server",
            reasoning_effort="high",
            enable_search=True,
        )
        root, host, remote_dir, timeout, _project_id, _project_name = cr.common_local_args(args)
        self.assertEqual(root, self.root.resolve())
        self.assertEqual(host, "rhel-test")
        self.assertEqual(remote_dir, "/srv/repo")
        self.assertEqual(timeout, 7)
        path = cr.local_project_config_path(self.root)
        value = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(value["host"], "rhel-test")
        self.assertEqual(value["remote_dir"], "/srv/repo")
        self.assertEqual(value["bootstrap_cmd"], args.bootstrap_cmd)
        self.assertEqual(value["test_cmd"], args.test_cmd)
        self.assertEqual(value["data_links"], args.data_link)
        self.assertEqual(value["reasoning_effort"], "high")
        self.assertTrue(value["enable_search"])
        self.assertEqual(value["job_policy"], "deny")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
