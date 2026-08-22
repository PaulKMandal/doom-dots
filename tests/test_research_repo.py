from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
PROGRAM = REPO_ROOT / "bin" / "research-repo"


def command(*args: str | os.PathLike[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        [os.fspath(item) for item in args],
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr or completed.stdout)
    return completed


class ResearchRepoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="research-repo-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def init(self, template: str) -> tuple[Path, dict[str, object]]:
        root = self.base / template
        completed = command(
            PROGRAM,
            "init",
            "--project-root",
            root,
            "--template",
            template,
            "--remote-host",
            "rhel-test",
            "--remote-dir",
            f"/srv/research/{template}",
        )
        return root, json.loads(completed.stdout)

    def test_each_template_initializes_and_passes_doctor(self) -> None:
        for template in ("generic", "chemistry", "federated"):
            with self.subTest(template=template):
                root, result = self.init(template)
                self.assertTrue(result["ok"])
                self.assertTrue((root / "AGENTS.md").is_file())
                self.assertTrue((root / "research/PROJECT.md").is_file())
                doctor = command(PROGRAM, "doctor", "--project-root", root)
                self.assertTrue(json.loads(doctor.stdout)["ok"])

    def test_initializer_is_idempotent_for_the_same_configuration(self) -> None:
        root, first = self.init("generic")
        initialized_at = json.loads(
            (root / "research/scaffold.json").read_text(encoding="utf-8")
        )["initialized_at"]
        _same_root, second = self.init("generic")
        self.assertTrue(first["created"])
        self.assertEqual(second["created"], [])
        self.assertIn("research/scaffold.json", second["unchanged"])
        self.assertEqual(
            json.loads((root / "research/scaffold.json").read_text())["initialized_at"],
            initialized_at,
        )

    def test_initializer_rejects_dot_equivalent_remote_paths_and_symlink_ancestors(self) -> None:
        for index, remote_dir in enumerate(("/root/.", "/home/user/.", "/srv/.", "/srv//project")):
            root = self.base / f"unsafe-{index}"
            completed = subprocess.run(
                [PROGRAM, "init", "--project-root", root, "--remote-dir", remote_dir],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertNotEqual(completed.returncode, 0, remote_dir)

        root = self.base / "symlink-root"
        outside = self.base / "outside"
        root.mkdir()
        outside.mkdir()
        command("git", "init", root)
        (root / "research").symlink_to(outside, target_is_directory=True)
        completed = subprocess.run(
            [
                PROGRAM,
                "init",
                "--project-root",
                root,
                "--template",
                "generic",
                "--remote-dir",
                "/srv/research/symlink-root",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse((outside / "PROJECT.md").exists())

    def test_generated_commands_match_template_capabilities(self) -> None:
        generic, _ = self.init("generic")
        generic_locals = (generic / ".dir-locals.el").read_text(encoding="utf-8")
        self.assertIn('(my/remote-setup-cmd . "true")', generic_locals)
        self.assertIn('(my/remote-test-cmd . "")', generic_locals)
        self.assertIn('"/reports/"', generic_locals)
        generic_doctor = json.loads(
            command(PROGRAM, "doctor", "--project-root", generic).stdout
        )
        self.assertFalse(generic_doctor["launch_ready"])

        chemistry, _ = self.init("chemistry")
        chemistry_locals = (chemistry / ".dir-locals.el").read_text(encoding="utf-8")
        self.assertIn("pip install -e .", chemistry_locals)
        self.assertIn("python3 -m venv", chemistry_locals)
        self.assertIn("unittest discover -s tests", chemistry_locals)
        chemistry_doctor = json.loads(
            command(PROGRAM, "doctor", "--project-root", chemistry).stdout
        )
        self.assertTrue(chemistry_doctor["launch_ready"])

    def test_chemistry_scaffold_keeps_four_task_contracts_separate(self) -> None:
        root, _ = self.init("chemistry")
        configs = root / "configs/benchmark"
        self.assertEqual(
            {path.name for path in configs.glob("*.yaml")},
            {
                "forward_endpoint.yaml",
                "forward_elementary_step.yaml",
                "forward_pathway_search.yaml",
                "retro_single_step.yaml",
            },
        )
        project = (root / "research/PROJECT.md").read_text(encoding="utf-8")
        self.assertIn("split before augmentation", project)

    def test_federated_scaffold_has_bridge_and_staleness_kill_tests(self) -> None:
        root, _ = self.init("federated")
        project = (root / "research/PROJECT.md").read_text(encoding="utf-8")
        self.assertIn("within-label subject shuffling", project)
        self.assertTrue((root / "configs/experiments/e1_bridge_sweep.yaml").is_file())
        self.assertTrue((root / "configs/experiments/e4_staleness.yaml").is_file())
        self.assertTrue((root / "configs/datasets/second_dataset_candidates.yaml").is_file())

    def test_python_scaffold_bootstrap_and_tests_leave_git_clean(self) -> None:
        root, _ = self.init("chemistry")
        command("git", "-C", root, "config", "user.name", "Test")
        command("git", "-C", root, "config", "user.email", "test@example.invalid")
        command("git", "-C", root, "add", "-A")
        command("git", "-C", root, "commit", "-m", "scaffold")
        completed = subprocess.run(
            [
                "bash",
                "-lc",
                "python3 -m venv .venv && .venv/bin/python -m pip install -e . "
                "&& .venv/bin/python -m unittest discover -s tests -v",
            ],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(command("git", "-C", root, "status", "--porcelain").stdout, "")

    def test_code_bundle_uses_worktree_bytes_and_excludes_results_and_secrets(self) -> None:
        root, _ = self.init("generic")
        command("git", "-C", root, "config", "user.name", "Test")
        command("git", "-C", root, "config", "user.email", "test@example.invalid")
        source = root / "src/example.py"
        source.parent.mkdir()
        source.write_text("VALUE = 1\n", encoding="utf-8")
        (root / "src/leaky.py").write_text(
            'OPENAI_API_KEY = "sk-proj-ABCDEFGHIJKLMNOPQRSTUVWX"\n',
            encoding="utf-8",
        )
        (root / ".env").write_text("TOKEN=placeholder\n", encoding="utf-8")
        (root / "auth.json").write_text('{"token": "placeholder"}\n', encoding="utf-8")
        (root / "service-account.json").write_text(
            '{"type": "service_account", "private_key": "placeholder"}\n',
            encoding="utf-8",
        )
        command("git", "-C", root, "add", "-A")
        command("git", "-C", root, "add", "-f", ".env")
        command("git", "-C", root, "commit", "-m", "initial")
        source.write_text("VALUE = 2\n", encoding="utf-8")
        (root / "src/untracked.py").write_text("UNTRACKED = True\n", encoding="utf-8")
        (root / ".env").write_text("TOKEN=SUPER_SECRET\n", encoding="utf-8")
        (root / "auth.json").write_text('{"token": "SUPER_SECRET"}\n', encoding="utf-8")
        (root / "results").mkdir()
        (root / "results/metrics.json").write_text("{}\n", encoding="utf-8")
        completed = command(PROGRAM, "bundle-code", "--project-root", root)
        result = json.loads(completed.stdout)
        archive = Path(result["output"])
        with tarfile.open(archive, "r:gz") as handle:
            names = set(handle.getnames())
            prefix = f"{root.name}-code-review"
            tracked_member = handle.extractfile(f"{prefix}/files/src/example.py")
            assert tracked_member is not None
            self.assertEqual(tracked_member.read(), b"VALUE = 2\n")
            patch_member = handle.extractfile(f"{prefix}/working-tree.patch")
            assert patch_member is not None
            patch = patch_member.read()
        self.assertIn(f"{prefix}/files/src/untracked.py", names)
        self.assertNotIn(f"{prefix}/files/.env", names)
        self.assertNotIn(f"{prefix}/files/auth.json", names)
        self.assertNotIn(f"{prefix}/files/service-account.json", names)
        self.assertNotIn(f"{prefix}/files/src/leaky.py", names)
        self.assertNotIn(f"{prefix}/files/results/metrics.json", names)
        self.assertNotIn(b"SUPER_SECRET", patch)
        self.assertNotIn(b"sk-proj-", patch)
        self.assertIn(b"VALUE = 2", patch)

    def test_code_bundle_includes_staged_and_unstaged_deletions(self) -> None:
        root, _ = self.init("generic")
        command("git", "-C", root, "config", "user.name", "Test")
        command("git", "-C", root, "config", "user.email", "test@example.invalid")
        source = root / "src"
        source.mkdir()
        (source / "staged.py").write_text("STAGED_OLD = True\n", encoding="utf-8")
        (source / "unstaged.py").write_text("UNSTAGED_OLD = True\n", encoding="utf-8")
        command("git", "-C", root, "add", "-A")
        command("git", "-C", root, "commit", "-m", "sources")
        (source / "staged.py").unlink()
        command("git", "-C", root, "add", "-u", "--", "src/staged.py")
        (source / "unstaged.py").unlink()
        result = json.loads(command(PROGRAM, "bundle-code", "--project-root", root).stdout)
        with tarfile.open(result["output"], "r:gz") as handle:
            member = handle.extractfile(f"{root.name}-code-review/working-tree.patch")
            assert member is not None
            patch = member.read()
        self.assertIn(b"src/staged.py", patch)
        self.assertIn(b"STAGED_OLD", patch)
        self.assertIn(b"src/unstaged.py", patch)
        self.assertIn(b"UNSTAGED_OLD", patch)

    def test_code_bundle_rejects_removed_secrets_and_excludes_notebook_outputs(self) -> None:
        root, _ = self.init("generic")
        command("git", "-C", root, "config", "user.name", "Test")
        command("git", "-C", root, "config", "user.email", "test@example.invalid")
        source = root / "src"
        source.mkdir()
        secret = source / "rotated.py"
        secret.write_text('TOKEN = "hf_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"\n', encoding="utf-8")
        notebook = root / "analysis.ipynb"
        notebook.write_text(
            json.dumps({"cells": [{"cell_type": "code", "outputs": [{"text": "patient row"}]}]}),
            encoding="utf-8",
        )
        command("git", "-C", root, "add", "-A")
        command("git", "-C", root, "commit", "-m", "before rotation")
        secret.write_text("TOKEN = None\n", encoding="utf-8")
        completed = subprocess.run(
            [PROGRAM, "bundle-code", "--project-root", root],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("credential material", completed.stderr)

        secret.write_text('TOKEN = "hf_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"\n', encoding="utf-8")
        result = json.loads(command(PROGRAM, "bundle-code", "--project-root", root).stdout)
        with tarfile.open(result["output"], "r:gz") as handle:
            self.assertNotIn(f"{root.name}-code-review/files/analysis.ipynb", handle.getnames())


if __name__ == "__main__":
    unittest.main()
