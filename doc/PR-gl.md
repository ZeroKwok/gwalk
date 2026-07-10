# gl Fetch And Pull Rules

## Summary

`gl` combines common Git fetch and pull operations for the current repository.

It can:

- Fetch every configured remote.
- Pull the current branch from `origin` or the first available remote.
- Skip fetch in quick mode.
- Pull with rebase.

CLI:

```bash
gl [OPTIONS]
```

Examples:

```bash
gl
gl -q
gl --rebase
```

## Repository Checks

`gl` must run inside a valid Git repository.

Validation:

- If the current directory is not inside a Git repository, `gl` prints an error and exits with code `1`.
- Unlike `gcp`, `gl` does not require the current directory to be the repository root.
- The repository is opened with `git.Repo(os.getcwd(), search_parent_directories=True)`.

The current active branch name is used as the pull target branch.

Detached HEAD is not specially handled; requesting `repo.active_branch.name` may fail in that state.

## Fetch Rules

Default behavior fetches every configured remote before pulling.

For each remote:

```bash
git fetch <remote-name>
```

If a fetch command fails:

- `gl` prints a warning for that remote.
- It continues fetching remaining remotes.
- It still proceeds to the final pull.

Quick mode:

```bash
gl -q
gl --quick
```

Quick mode skips all fetch commands and goes directly to pull.

## Pull Remote Selection

After optional fetch, `gl` chooses one remote for pull.

Selection rules:

- Prefer `origin` if it exists.
- If `origin` does not exist and at least one remote exists, use the first configured remote.
- If there are no remotes, the command still formats as `git pull origin <branch>` because `origin` is the default initial value.

The selected branch is always the current active branch name.

## Pull Rules

Default pull command:

```bash
git pull <remote> <branch>
```

With `--rebase`:

```bash
git pull <remote> <branch> --rebase
```

The pull command is printed before execution.

`gl` exits with the pull command's exit code.

## Error Handling

Fetch failures are warnings and do not stop the command.

Pull failure is terminal because its exit code is used as `gl`'s process exit code.

All commands are executed through `RepoHandler.execute`, which normalizes exit codes on non-Windows platforms.
