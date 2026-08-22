import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ArtifactContractTests(unittest.TestCase):
    def test_smoke_launcher_separates_evidence_from_marker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            results = root / "sealed-results"
            marker = root / "worktree" / "artifacts" / "COMPLETE"
            env = os.environ.copy()
            env["CODEX_RESULTS_DIR"] = str(results)
            env["CODEX_COMPLETION_MARKER"] = str(marker)
            subprocess.run(
                [sys.executable, "scripts/codex_artifacts.py", "--smoke"],
                check=True,
                env=env,
            )
            self.assertTrue((results / "contract-smoke.json").is_file())
            evidence = json.loads((results / "evidence-manifest.json").read_text())
            self.assertEqual(evidence["expected_counts"], {"smoke_rows": 1})
            self.assertEqual(evidence["observed_counts"], {"smoke_rows": 1})
            self.assertEqual(len(evidence["dataset_manifest_sha256"]), 64)
            self.assertTrue(marker.is_file())
            self.assertEqual(list(marker.parent.glob("*.json")), [])

    def test_result_writer_rejects_existing_and_dangling_symlink_parents(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            results = root / "results"
            results.mkdir()
            outside = root / "outside"
            outside.mkdir()
            env = os.environ.copy()
            env["CODEX_RESULTS_DIR"] = str(results)
            command = [
                sys.executable,
                "-c",
                "from scripts.codex_artifacts import write_result_json; "
                "write_result_json('linked/value.json', {'unsafe': True})",
            ]
            (results / "linked").symlink_to(outside, target_is_directory=True)
            completed = subprocess.run(command, env=env, check=False)
            self.assertNotEqual(completed.returncode, 0)
            self.assertFalse((outside / "value.json").exists())
            (results / "linked").unlink()
            dangling = root / "does-not-exist"
            (results / "linked").symlink_to(dangling, target_is_directory=True)
            completed = subprocess.run(command, env=env, check=False)
            self.assertNotEqual(completed.returncode, 0)
            self.assertFalse((dangling / "value.json").exists())


if __name__ == "__main__":
    unittest.main()
