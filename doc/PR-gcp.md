# gcp Commit And Push Rules

## Summary

`gcp` combines common Git commit and push operations for the current repository.

It can:

- Stage tracked changes or all changes.
- Commit with a message or open the Git commit editor.
- Push the selected source branch or tag to every configured remote.
- Run in push-only or dry-run mode.

CLI:

```bash
gcp [OPTIONS] [COMMIT_MESSAGE...]
```

Examples:

```bash
gcp "fix bugs"
gcp -a "add new feature"
gcp -p
gcp -p -s v1.2.0
gcp -n "preview commit"
```

## Repository Checks

`gcp` must run inside a valid Git repository.

Validation:

- If the current directory is not inside a Git repository, `gcp` prints an error and exits with code `1`.
- By default, the current directory must be the repository root.
- `-i` or `--ignore` skips the repository-root check and allows running from a subdirectory.

Repository status is loaded with `RepoStatus(os.getcwd()).load()`.

## Source Ref Selection

`--src BRANCH` selects the local branch or tag to push.

If `--src` is not provided:

- `gcp` uses the current active branch name.

Detached HEAD is not specially handled by `gcp`; requesting the active branch name may fail in that state.

## Normal Commit And Push Flow

Without `--push`, `gcp` runs the commit workflow.

Flow:

1. Load repository status.
2. If repository is clean, print:

   ```text
   The git repository is clean.
   ```

   Then exit with code `0`.

3. Print short status:

   ```bash
   git status -s --untracked-files=normal
   ```

4. Decide whether there are changes to commit:
   - Default mode commits only tracked modifications.
   - `--all` mode commits tracked modifications and untracked files.

5. Stage files:

   ```bash
   git add -u
   ```

   or with `--all`:

   ```bash
   git add -A
   ```

6. Commit:
   - If a commit message was provided:

     ```bash
     git commit -m "<message>"
     ```

   - If no message was provided:

     ```bash
     git commit
     ```

     This opens Git's normal commit editor.

7. Push to every configured remote:

   ```bash
   git push <remote-name> <src>
   ```

If there are only untracked files and `--all` is not used, status is printed but no add, commit, or push command is run.

## Push-Only Mode

`--push` skips status checks for dirty/clean state and skips add/commit.

Flow:

1. Determine `src`.
2. For every configured remote, run:

   ```bash
   git push <remote-name> <src>
   ```

3. Exit with code `0` if every push succeeds.

`--push` ignores the commit message and `--all`.

## Dry Run

`--dry-run` prints commands without executing them.

Printed command format:

```text
(dry-run) > git add -u
(dry-run) > git commit -m "message"
(dry-run) > git push origin main
```

Repository validation and status loading still occur in dry-run mode.

## Error Handling

All Git commands are executed through `RepoHandler.execute`.

For each command:

- The command is printed before execution.
- If the command returns non-zero, `gcp` raises `ResultError`.
- `main()` catches `ResultError` and exits with the failing command's exit code.

On non-Windows platforms, command exit codes are normalized by `RepoHandler.execute`.

## Remote Rules

`gcp` does not choose a single remote.

It pushes to every remote configured on the repository:

```python
for remote in repo.repo.remotes:
    git push <remote.name> <src>
```

If the repository has no remotes, no push commands are run after commit.
