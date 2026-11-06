import os
from pathlib import Path
import subprocess
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RmbranchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="git-rmbranch-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.env = {
            key: value for key, value in os.environ.items()
            if not key.startswith("GIT_")
        }
        self.env.update({
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
            "PATH": str(PROJECT_ROOT) + os.pathsep + self.env.get("PATH", ""),
        })
        self.git("init", "-b", "main", str(self.repo), cwd=self.root)
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("commit", "--allow-empty", "-m", "Initial")

    def git(self, *args, cwd=None, check=True):
        return subprocess.run(
            ["git", *args], cwd=cwd or self.repo, env=self.env,
            text=True, capture_output=True, check=check,
        )

    def run_command(self, *args, cwd=None, success=True):
        result = self.git("rmbranch", *args, cwd=cwd, check=False)
        self.assertEqual(
            result.returncode == 0, success, result.stdout + result.stderr,
        )
        return result

    def worktree(self, name="topic", path="linked worktree"):
        target = self.root / path
        self.git("worktree", "add", "-b", name, str(target))
        return target

    def assert_branch(self, name, exists=True):
        result = self.git(
            "show-ref", "--verify", "--quiet", f"refs/heads/{name}", check=False,
        )
        self.assertEqual(result.returncode == 0, exists)

    def submodule_worktree(self):
        subrepo = self.root / "subrepo"
        self.git("init", "-b", "main", str(subrepo))
        self.git("config", "user.name", "Test", cwd=subrepo)
        self.git("config", "user.email", "test@example.invalid", cwd=subrepo)
        (subrepo / "tracked").write_text("original")
        self.git("add", "tracked", cwd=subrepo)
        self.git("commit", "-m", "Initial", cwd=subrepo)
        self.git(
            "-c", "protocol.file.allow=always", "submodule", "add",
            str(subrepo), "sub",
        )
        self.git("commit", "-m", "Submodule")
        target = self.worktree()
        self.git(
            "-c", "protocol.file.allow=always", "submodule", "update",
            "--init", cwd=target,
        )
        return target

    def test_merged_worktree_removed(self):
        target = self.worktree()
        self.run_command("topic")
        self.assertFalse(target.exists())
        self.assert_branch("topic", False)
        self.assertNotIn(str(target), self.git("worktree", "list").stdout)

    def test_branch_without_worktree(self):
        self.git("branch", "topic")
        self.run_command("topic")
        self.assert_branch("topic", False)

    def test_unmerged_refused_before_removal(self):
        target = self.worktree()
        self.git("commit", "--allow-empty", "-m", "Unmerged", cwd=target)
        self.assertIn(
            "not fully merged", self.run_command("topic", success=False).stderr,
        )
        self.assertTrue(target.exists())
        self.assert_branch("topic")

    def test_unmerged_branch_without_worktree_refused(self):
        self.git("switch", "-c", "topic")
        self.git("commit", "--allow-empty", "-m", "Unmerged")
        self.git("switch", "main")
        self.run_command("topic", success=False)
        self.assert_branch("topic")
        self.run_command("-f", "topic")
        self.assert_branch("topic", False)

    def test_force_removes_dirty_unmerged_worktree(self):
        target = self.worktree()
        self.git("commit", "--allow-empty", "-m", "Unmerged", cwd=target)
        (target / "untracked").write_text("keep unless forced")
        self.run_command("--force", "topic")
        self.assertFalse(target.exists())
        self.assert_branch("topic", False)

    def test_untracked_files_refused(self):
        target = self.worktree()
        (target / "untracked").write_text("keep")
        self.run_command("topic", success=False)
        self.assertTrue((target / "untracked").exists())
        self.assert_branch("topic")

    def test_dirty_worktree_logs_copyable_status_command(self):
        for path in ["linked worktree 'quoted' $literal;", "linked\nworktree"]:
            with self.subTest(path=path):
                target = self.worktree(path=path)
                (target / "untracked").write_text("keep")
                exclude = self.repo / ".git/info/exclude"
                with exclude.open("a") as stream:
                    stream.write("\nignored\n")
                (target / "ignored").write_text("keep")
                result = self.run_command("topic", success=False)
                prefix, separator, command = result.stderr.partition(
                    "View changes with:\n  ",
                )
                self.assertTrue(separator, result.stderr)
                self.assertIn(
                    f"Worktree has modified or untracked files: {target}",
                    prefix,
                )
                command = command.rstrip("\n")
                self.assertTrue(command.startswith("git -C "), command)
                inspected = subprocess.run(
                    ["bash", "--noprofile", "--norc", "-c", command],
                    cwd=self.repo, env=self.env, text=True,
                    capture_output=True, check=True,
                )
                expected = self.git(
                    "-C", str(target), "status", "--short",
                    "--untracked-files=all", "--ignore-submodules=none",
                )
                self.assertEqual(inspected.stdout, expected.stdout)
                self.assertIn("?? untracked", inspected.stdout)
                self.assertNotIn("--ignored", command)
                self.assertNotIn("ignored", inspected.stdout)
                self.assertTrue(target.exists())
                self.assert_branch("topic")
                self.git("worktree", "remove", "--force", str(target))
                self.git("branch", "-d", "topic")

    def test_tracked_changes_refused(self):
        (self.repo / "tracked").write_text("original")
        self.git("add", "tracked")
        self.git("commit", "-m", "Tracked file")
        target = self.worktree()
        (target / "tracked").write_text("modified")
        self.run_command("topic", success=False)
        self.assertEqual((target / "tracked").read_text(), "modified")
        self.assert_branch("topic")

    def test_staged_changes_refused(self):
        target = self.worktree()
        (target / "staged").write_text("keep")
        self.git("add", "staged", cwd=target)
        self.run_command("topic", success=False)
        self.assertTrue((target / "staged").exists())
        self.assert_branch("topic")

    def test_ignored_files_do_not_block_removal(self):
        target = self.worktree()
        exclude = self.repo / ".git/info/exclude"
        with exclude.open("a") as stream:
            stream.write("\nignored\n")
        (target / "ignored").write_text("discard with worktree")
        self.run_command("topic")
        self.assertFalse(target.exists())
        self.assert_branch("topic", False)

    def test_current_worktree_never_removed(self):
        target = self.worktree()
        self.run_command("--force", "topic", cwd=target, success=False)
        self.assertTrue(target.exists())
        self.assert_branch("topic")

    def test_main_worktree_never_removed(self):
        target = self.worktree()
        self.run_command("--force", "main", cwd=target, success=False)
        self.assertTrue(self.repo.exists())
        self.assert_branch("main")

    def test_locked_worktree_never_removed(self):
        target = self.worktree()
        self.git("worktree", "lock", "--reason", "Do not delete", str(target))
        self.run_command("--force", "topic", success=False)
        self.assertTrue(target.exists())
        self.assert_branch("topic")

    def test_unrelated_locked_worktree(self):
        target = self.worktree("other")
        self.git("worktree", "lock", str(target))
        self.git("branch", "topic")
        self.run_command("topic")
        self.assertTrue(target.exists())
        self.assert_branch("topic", False)

    def test_path_with_newline(self):
        target = self.worktree(path="linked\nworktree")
        self.run_command("--", "topic")
        self.assertFalse(target.exists())
        self.assert_branch("topic", False)

    def test_branch_with_slash(self):
        target = self.worktree(name="user/topic")
        self.run_command("user/topic")
        self.assertFalse(target.exists())
        self.assert_branch("user/topic", False)

    def test_upstream_used_instead_of_head(self):
        target = self.worktree()
        self.git("commit", "--allow-empty", "-m", "Topic", cwd=target)
        self.git("branch", "upstream", "topic")
        self.git("branch", "--set-upstream-to=upstream", "topic")
        self.run_command("topic")
        self.assertFalse(target.exists())
        self.assert_branch("topic", False)
        self.assert_branch("upstream")

    def test_divergent_upstream_refused_before_removal(self):
        target = self.worktree()
        self.git("branch", "upstream")
        self.git("branch", "--set-upstream-to=upstream", "topic")
        self.git("commit", "--allow-empty", "-m", "Topic", cwd=target)
        self.git("merge", "--ff-only", "topic")
        self.run_command("topic", success=False)
        self.assertTrue(target.exists())
        self.assert_branch("topic")

    def test_missing_upstream_falls_back_to_head(self):
        target = self.worktree()
        self.git("branch", "upstream")
        self.git("branch", "--set-upstream-to=upstream", "topic")
        self.git("branch", "-d", "upstream")
        self.run_command("topic")
        self.assertFalse(target.exists())
        self.assert_branch("topic", False)

    def test_remote_tracking_branch_preserved(self):
        target = self.worktree()
        self.git("remote", "add", "origin", "https://example.invalid/repo.git")
        self.git("update-ref", "refs/remotes/origin/topic", "HEAD")
        self.git("branch", "--set-upstream-to=origin/topic", "topic")
        self.run_command("topic")
        self.assertFalse(target.exists())
        self.assert_branch("topic", False)
        self.git("show-ref", "--verify", "refs/remotes/origin/topic")

    def test_submodule_requires_explicit_force(self):
        target = self.submodule_worktree()
        self.run_command("topic", success=False)
        self.assertTrue(target.exists())
        self.assert_branch("topic")
        self.run_command("-f", "topic")
        self.assertFalse(target.exists())
        self.assert_branch("topic", False)

    def test_dirty_submodule_refused(self):
        target = self.submodule_worktree()
        (target / "sub/tracked").write_text("modified")
        result = self.run_command("topic", success=False)
        self.assertIn("modified or untracked", result.stderr)
        self.assertEqual((target / "sub/tracked").read_text(), "modified")
        self.assert_branch("topic")

    def test_multiple_worktrees_refused(self):
        first = self.worktree()
        second = self.root / "second worktree"
        self.git("worktree", "add", "--force", str(second), "topic")
        self.run_command("--force", "topic", success=False)
        self.assertTrue(first.exists())
        self.assertTrue(second.exists())
        self.assert_branch("topic")

    def test_bare_repository(self):
        self.git("branch", "topic")
        bare = self.root / "bare.git"
        self.git("clone", "--bare", str(self.repo), str(bare))
        self.run_command("topic", cwd=bare)
        result = self.git(
            "show-ref", "--verify", "--quiet", "refs/heads/topic",
            cwd=bare, check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assert_branch("topic")

    def test_invalid_arguments_do_not_modify_repo(self):
        target = self.worktree()
        for args in [
            (), ("missing",), ("--invalid",), ("topic", "extra"), ("../topic",),
        ]:
            with self.subTest(args=args):
                self.run_command(*args, success=False)
        self.assertTrue(target.exists())
        self.assert_branch("topic")

    def test_outside_repository(self):
        self.run_command("topic", cwd=self.root, success=False)

    def test_help(self):
        result = self.run_command("-h", cwd=self.root)
        self.assertIn("Usage: git rmbranch", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
