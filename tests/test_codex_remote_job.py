from __future__ import annotations

import argparse
import importlib.util
from importlib.machinery import SourceFileLoader
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
PROGRAM = REPO_ROOT / "bin" / "codex-remote-job"
loader = SourceFileLoader("codex_remote_job", str(PROGRAM))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec is not None
job = importlib.util.module_from_spec(spec)
loader.exec_module(job)


def command(*args: str | os.PathLike[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [os.fspath(value) for value in args],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result


class TerminalJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="codex-remote-job-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        command("git", "init", "-b", "main", self.root)
        command("git", "-C", self.root, "config", "user.name", "Test")
        command("git", "-C", self.root, "config", "user.email", "test@example.invalid")
        (self.root / "README.md").write_text("test\n", encoding="utf-8")
        command("git", "-C", self.root, "add", "README.md")
        command("git", "-C", self.root, "commit", "-m", "initial")

    def namespace(self, **overrides):
        values = dict(
            project_root=str(self.root),
            backend=None,
            host=None,
            remote_dir=None,
            timeout=None,
            max_untracked_bytes=None,
            bootstrap_cmd=None,
            test_cmd=None,
            data_link=None,
            model=None,
            profile=None,
            reasoning_effort=None,
            enable_search=None,
            ignore_config=False,
            prompt_file=None,
            watch=False,
            poll_interval=1.0,
            tail=800,
            pause_at_end=False,
        )
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_config_and_explicit_overrides_build_backend_arguments(self) -> None:
        config = {
            "host": "rhel-test",
            "remote_dir": "/srv/configured",
            "timeout": 5,
            "max_untracked_bytes": 4096,
            "bootstrap_cmd": "nix develop --command true",
            "test_cmd": "pytest -q",
            "data_links": ["/srv/data=data"],
            "model": "configured-model",
            "profile": "server",
            "reasoning_effort": "high",
            "enable_search": True,
        }
        args = self.namespace(remote_dir="/srv/override", model="override-model")
        values = job.resolved_options(args, config)
        self.assertEqual(values["host"], "rhel-test")
        self.assertEqual(values["remote_dir"], "/srv/override")
        self.assertEqual(values["model"], "override-model")
        command_args = job.task_backend_args(self.root, values, "start")
        self.assertEqual(command_args[0], "start")
        self.assertIn("--bootstrap-cmd", command_args)
        self.assertIn("/srv/data=data", command_args)
        self.assertIn("--enable-search", command_args)
        self.assertIn("override-model", command_args)

    def test_incremental_text_handles_append_and_tail_overlap(self) -> None:
        addition, baseline = job.incremental_text("one\ntwo\n", "one\ntwo\nthree\n")
        self.assertEqual(addition, "three\n")
        self.assertEqual(baseline, "one\ntwo\nthree\n")
        addition, baseline = job.incremental_text(
            "old\nshared\n", "shared\nnew\n"
        )
        self.assertEqual(addition, "new\n")
        self.assertEqual(baseline, "shared\nnew\n")

    def test_program_is_executable(self) -> None:
        self.assertEqual(stat.S_IMODE(PROGRAM.stat().st_mode) & 0o111, 0o111)


if __name__ == "__main__":
    unittest.main()
