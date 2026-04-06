"""Tests for build lifecycle Makefile targets."""

import os
import shutil
import subprocess
import tempfile
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MAKEFILE = os.path.join(_REPO_ROOT, "Makefile")


def _build_state_root():
    """Return the main working tree root (resolves correctly in worktrees)."""
    result = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=_REPO_ROOT, capture_output=True, text=True
    )
    git_common_dir = result.stdout.strip()
    if not os.path.isabs(git_common_dir):
        git_common_dir = os.path.join(_REPO_ROOT, git_common_dir)
    return os.path.normpath(os.path.join(git_common_dir, ".."))


_STATE_ROOT = _build_state_root()


class TestBuildMakefileTargetStructure(unittest.TestCase):
    """Verifies build lifecycle targets exist in Makefile text."""

    @classmethod
    def setUpClass(cls):
        with open(_MAKEFILE) as f:
            cls.content = f.read()

    def test_build_init_target_exists(self):
        self.assertIn("build-init:", self.content)

    def test_build_checkpoint_target_exists(self):
        self.assertIn("build-checkpoint:", self.content)

    def test_build_checkpoint_get_target_exists(self):
        self.assertIn("build-checkpoint-get:", self.content)

    def test_build_checkpoint_require_target_exists(self):
        self.assertIn("build-checkpoint-require:", self.content)

    def test_build_evidence_target_exists(self):
        self.assertIn("build-evidence:", self.content)

    def test_build_evidence_check_target_exists(self):
        self.assertIn("build-evidence-check:", self.content)

    def test_build_clear_target_exists(self):
        self.assertIn("build-clear:", self.content)

    def test_help_lists_build_targets(self):
        for target in ("build-init", "build-checkpoint", "build-evidence", "build-clear"):
            self.assertIn(target, self.content, f"Expected '{target}' to appear in Makefile help")

    def test_phony_includes_build_targets(self):
        for target in ("build-init", "build-checkpoint", "build-checkpoint-get",
                       "build-checkpoint-require", "build-evidence", "build-evidence-check",
                       "build-clear"):
            self.assertIn(target, self.content, f"Expected '{target}' to appear in .PHONY")


class TestPublishMakefileTargets(unittest.TestCase):
    """Verify publish-related Makefile targets exist."""

    @classmethod
    def setUpClass(cls):
        with open(_MAKEFILE) as f:
            cls.content = f.read()

    def test_publish_setup_target_exists(self):
        self.assertIn("publish-setup:", self.content)

    def test_publish_dry_run_target_exists(self):
        self.assertIn("publish-dry-run:", self.content)

    def test_publish_public_target_exists(self):
        self.assertIn("publish-public:", self.content)

    def test_phony_includes_publish_targets(self):
        for target in ("publish-setup", "publish-dry-run", "publish-public"):
            self.assertIn(target, self.content, f"Expected '{target}' in .PHONY")


class TestBuildMakefileTargetBehavior(unittest.TestCase):
    """Invokes build lifecycle targets via subprocess.

    Uses BUILD_STATE_FILE and BUILD_EVIDENCE_DIR env var overrides to isolate
    tests from any active build state (fixes rpw-agent-assets-be5).
    """

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="build-test-")
        self._state_file = os.path.join(self._tmpdir, "build-state.json")
        self._evidence_dir = os.path.join(self._tmpdir, "build-evidence")
        # Save originals
        self._orig_state = os.environ.get("BUILD_STATE_FILE")
        self._orig_evidence = os.environ.get("BUILD_EVIDENCE_DIR")
        # Set isolated paths
        os.environ["BUILD_STATE_FILE"] = self._state_file
        os.environ["BUILD_EVIDENCE_DIR"] = self._evidence_dir
        # Clear any leftover state in the isolated path
        subprocess.run(["make", "build-clear"], cwd=_REPO_ROOT, capture_output=True)

    def tearDown(self):
        # Clean up temp dir
        shutil.rmtree(self._tmpdir, ignore_errors=True)
        # Restore originals
        if self._orig_state is not None:
            os.environ["BUILD_STATE_FILE"] = self._orig_state
        else:
            os.environ.pop("BUILD_STATE_FILE", None)
        if self._orig_evidence is not None:
            os.environ["BUILD_EVIDENCE_DIR"] = self._orig_evidence
        else:
            os.environ.pop("BUILD_EVIDENCE_DIR", None)

    def test_build_init_creates_state_file(self):
        result = subprocess.run(
            ["make", "build-init", "BEAD=test-behavioral-123"],
            cwd=_REPO_ROOT, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, f"make build-init failed: {result.stderr}")
        self.assertTrue(os.path.exists(self._state_file), "build-state.json should exist after build-init")

    def test_build_checkpoint_sets_checkpoint(self):
        subprocess.run(
            ["make", "build-init", "BEAD=test-behavioral-123"],
            cwd=_REPO_ROOT, capture_output=True
        )
        result = subprocess.run(
            ["make", "build-checkpoint", "CP=verify_passed"],
            cwd=_REPO_ROOT, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, f"make build-checkpoint failed: {result.stderr}")
        get_result = subprocess.run(
            ["make", "build-checkpoint-get", "CP=verify_passed"],
            cwd=_REPO_ROOT, capture_output=True, text=True
        )
        self.assertEqual(get_result.returncode, 0, f"make build-checkpoint-get failed: {get_result.stderr}")

    def test_build_evidence_saves_artifact(self):
        result = subprocess.run(
            ["make", "build-evidence", "PHASE=verify", "DATA={\"ok\":true}"],
            cwd=_REPO_ROOT, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, f"make build-evidence failed: {result.stderr}")
        evidence_file = os.path.join(self._evidence_dir, "verify.json")
        self.assertTrue(os.path.exists(evidence_file), "verify.json should exist after build-evidence")

    def test_build_clear_removes_state(self):
        subprocess.run(
            ["make", "build-init", "BEAD=test-behavioral-123"],
            cwd=_REPO_ROOT, capture_output=True
        )
        self.assertTrue(os.path.exists(self._state_file), "Precondition: state file should exist")
        result = subprocess.run(
            ["make", "build-clear"],
            cwd=_REPO_ROOT, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, f"make build-clear failed: {result.stderr}")
        self.assertFalse(os.path.exists(self._state_file), "build-state.json should be gone after build-clear")
