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
gl -f
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

Normal mode uses one aggregate fetch:

```bash
git fetch --all --no-auto-maintenance
git maintenance run --auto --no-quiet
```

If fetch or maintenance fails:

- `gl` prints a warning.
- It still proceeds to the final pull unless `--fetch` was specified.

Safe aggregate fetch mode:

```bash
gl -f
gl --fetch
```

This runs `git fetch --all --no-auto-maintenance`, followed by
`git maintenance run --auto --no-quiet` in the foreground. Git may otherwise
start detached background maintenance after fetch. On Windows, that process
can compete with later Git commands for `.pack` and `.idx` files.

Quick mode:

```bash
gl -q
gl --quick
```

Quick mode skips all fetch commands and goes directly to pull.

`--fetch` is fetch-only: it performs the aggregate fetch and foreground
maintenance, then exits without pulling.

For bare repositories, pull is unsupported because there is no work tree. In
non-quick mode, `gl` performs the safe aggregate fetch and foreground
maintenance, then exits without pulling. In quick mode, it performs no update.

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

For bare repositories, `gl` exits with the fetch or maintenance failure status,
or `0` when both complete successfully.

## Error Handling

Fetch failures are warnings and do not stop the command.

Pull failure is terminal because its exit code is used as `gl`'s process exit code.

All commands are executed through `RepoHandler.execute`, which normalizes exit codes on non-Windows platforms.
