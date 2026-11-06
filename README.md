# git-rmbranch

Remove a local Git branch and its linked worktree in one command.

## Installation

From this repository:

```bash
mkdir -p ~/.local/bin
install -m 0755 git-rmbranch ~/.local/bin/git-rmbranch
```

Ensure `~/.local/bin` is on your `PATH`. Git discovers the executable as
`git rmbranch`; no Git alias is needed.

The script requires Bash, Git with `worktree list --porcelain -z` support, and
GNU-compatible `base64`. It is tested on Linux.

## Usage

```bash
git rmbranch topic
git rmbranch --force topic
git rmbranch -h
```

Run the command from a different worktree than the one being removed. If the
branch has no worktree, only the local branch is deleted.

By default, the command:

- Checks that the branch is fully merged into its upstream, or into the current
  `HEAD` if no existing upstream is available, matching `git branch -d`.
- Refuses worktrees containing modified, staged, or non-ignored untracked files,
  including changes in submodules.
- Removes the worktree before deleting the branch. Ignored files do not block
  removal and are discarded with the worktree.

When a dirty worktree is refused, the error includes a copyable `git -C ... status`
command to inspect the modified and non-ignored untracked files, including changes
in submodules.

`--force` (or `-f`) allows deleting unmerged branches and discarding worktree
changes, including untracked and ignored files. **This can permanently delete
work.** Git also requires this flag to remove worktrees containing submodules,
even when they are clean.

Neither mode removes the main worktree, the current worktree, or a locked
worktree. Branches checked out in multiple worktrees are refused; remove those
worktrees individually. Remote branches and remote-tracking refs are untouched.

Removal and branch deletion are separate Git operations, not an atomic
transaction. If the worktree is removed but branch deletion fails, the error is
reported and the branch remains.

Use `git rmbranch -h` for help. Git intercepts `git rmbranch --help` to look for
a manual page, which this project does not install.

## Testing

The integration tests use Python's standard library and temporary Git
repositories. They test the repository's script through `git rmbranch`, without
using an installed copy, modifying your repositories, or accessing the network.
Python 3 is required.

```bash
python3 -B -m unittest discover -s tests -v
bash -n git-rmbranch
shellcheck git-rmbranch
```

ShellCheck is optional and must be installed separately to run the last command.
