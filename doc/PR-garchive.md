# garchive Archive Conversion Rules

## Summary

`garchive` converts a Git repository between a normal worktree repository and an archive-style bare mirror repository.

The goal is backup/storage:

- `archive` keeps only Git repository metadata as the active repository layout.
- `restore` recreates a normal repository directory from the archive repository.

CLI:

```bash
garchive archive [--path PATH] [--clean] [--force]
garchive restore [--path PATH] [--checkout [BRANCH]] [--name TARGET]
garchive restore [--path PATH] [--checkout [BRANCH]] --here
garchive clone URL [DIR]
```

- `archive` / `restore` is a required positional argument.
- `--path` defaults to the current directory.
- `--name` only applies to `restore`; it forces the move-out restore.
- `--here` only applies to `restore`; it cannot be combined with `--name`.
- `--clean` / `--force` only apply to `archive`.

## Restore Source Resolution

`restore --path` accepts either the archive Git directory or a parent directory that contains a real `.git` directory:

```text
SomeDir/.git     # archive Git directory
SomeDir          # parent directory containing SomeDir/.git
```

If `--path` is a parent directory with a real `.git` directory (not a `gitdir` file) and no `--name` is given, `restore` auto-enables in-place restore (equivalent to `--here`).

- `--name TARGET` takes precedence: it forces the move-out restore even for a parent directory path.
- If the parent directory's `.git` is a file (a `gitdir` link, i.e. a linked worktree or submodule), `restore` rejects it and asks for the actual Git directory, because worktrees are not supported.

## Archive

Input is a normal repository directory:

```text
SomeDir/.git
```

Before conversion:

- The repository must be non-bare.
- The repository must be clean, including untracked files.
- `.git/config` is archived as a fixed-name marker:

  ```text
  .git/config -> .git/config.archive
  ```

Conversion updates config:

```ini
[core]
    bare = true

[remote "origin"]
    mirror = true
    fetch = +refs/*:refs/*
```

All configured remotes are marked as mirrors. `mate.archive` records the worktree path and archive timestamp.

The worktree files are not deleted or moved.

### Clean Working Directory

By default `archive` keeps the working directory files. With `--clean`, `archive` removes the working directory contents (everything except `.git`) after converting the config.

- If ignored files exist in the working directory, `archive` lists them and asks for confirmation before deleting.
- `--force` skips that confirmation.
- `--clean` is only valid for `archive` mode.

## Restore

Input is an archive Git directory, such as:

```text
SomeDir/.git
SomeDir.git
```

`garchive clone URL [DIR]` creates this archive layout directly. If DIR is omitted, the directory name is derived from the URL.

The source must be:

- `core.bare = true`
- `config.archive` exists

Before restore modifies config, it restores the original config from the archive marker:

```text
config.archive -> config
```

If `config.archive` is absent, restore is rejected. Historical archive layouts are not supported.

`mate.archive` records the original worktree path and archive timestamp. When restoring from a `.git` directory without `--name`, the recorded worktree path allows in-place restore. `mate.archive` is removed after restore.

Default restore creates or uses an empty target directory, moves the archive Git directory to:

```text
TARGET/.git
```

The restored `config.archive` already contains the worktree configuration:

```ini
[core]
    bare = false

[remote "origin"]
    mirror = false
    fetch = +refs/heads/*:refs/remotes/origin/*
```

If `--checkout BRANCH` is provided, restore checks out that branch and resets the worktree to it.

If `--checkout` is provided without a branch, restore checks out the current `HEAD` branch.

If `--checkout` is not provided, restore does not checkout files.

`--here` is the in-place restore mode:

- `--path` must point to an archive `.git` directory, such as `SomeDir/.git`.
- The Git directory is not moved.
- Restore always moves `config.archive` to `config`; there is no configuration rewrite fallback.
- If `--checkout BRANCH` is provided, the parent directory of `.git` is checked out and reset to that branch.
- If `--checkout` is provided without a branch, the current `HEAD` branch is checked out.
- If `--checkout` is omitted, existing worktree files are left as-is.
- `--name` cannot be combined with `--here`.

When `--path` is a parent directory (e.g. `SomeDir`) containing a real `.git` directory and `--name` is omitted, `restore` automatically applies in-place restore and prints a notice.

## Target Rules

If `--name TARGET` is provided, use it.

`--name` is rejected when combined with `--here`; in-place restore always uses the parent directory of the `.git` path.

If `--name` is omitted:

- For source paths ending in `.git`, strip that suffix when no metadata is available:

  ```text
  FoneTool.git -> FoneTool
  ```

- For source paths named `.git`, use the worktree path recorded in `mate.archive` when available.

- If no target can be inferred, fail and ask the user to pass `TARGET`.

Target must not exist or must be empty.

## Safety Rules

- `archive` saves the original config as `config.archive`.
- `archive` refuses dirty repositories.
- `restore` refuses non-archive sources.
- `restore` refuses non-empty target directories.
- `archive --clean` asks for confirmation when ignored files exist, unless `--force`.
- `restore` rejects parent directory paths whose `.git` is a `gitdir` file (worktree unsupported).
- `restore` requires `config.archive` and removes `mate.archive` after restoring it.
- The tool prints each important operation before executing it:
  - config archive
  - config restoration
  - git directory move
  - optional checkout

## Tests

Covered scenarios:

- Normal clean repository converts to archive config.
- Dirty repository refuses archive conversion.
- Archive repository restores to normal config.
- Restore honors explicit target directory.
- Restore without `--checkout` does not checkout files.
- Restore with `--checkout BRANCH` checks out files.
- Restore with `--checkout` (no branch) checks out the current `HEAD` branch.
- Target inference from `mate.archive` and `*.git` paths.
- Non-empty target is rejected.
- Non-archive source is rejected.
- Archive clone creates `config.archive` and `mate.archive` metadata.
- `--clean` removes working directory files.
- `--clean` prompts when ignored files exist; `--force` skips the prompt.
- `restore` auto-enables in-place restore for a parent directory with a real `.git` directory.
- `restore` honors `--name` (move-out) even for a parent directory path.
- `restore` rejects a parent directory whose `.git` is a `gitdir` file.
- `archive` writes a fixed `config.archive` marker; `restore` restores it and preserves original config values.
- `clone` creates a mirror archive with worktree-style `config.archive` and `mate.archive` metadata.
