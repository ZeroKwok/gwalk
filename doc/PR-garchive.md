# garchive Archive Conversion Rules

## Summary

`garchive` converts a Git repository between a normal worktree repository and an archive-style bare mirror repository.

The goal is backup/storage:

- `archive` keeps only Git repository metadata as the active repository layout.
- `restore` recreates a normal repository directory from the archive repository.

CLI:

```bash
garchive archive [--path PATH] [--remote REMOTE] [--clean] [--force]
garchive restore [--path PATH] [--remote REMOTE] [--checkout BRANCH] [--name TARGET]
garchive restore [--path PATH] [--remote REMOTE] [--checkout BRANCH] --here
```

- `archive` / `restore` is a required positional argument.
- `--path` defaults to the current directory.
- `--name` only applies to non-in-place restore.

## Restore Source Resolution

`restore --path` accepts either the archive Git directory or a parent directory that contains a real `.git` directory:

```text
SomeDir/.git     # archive Git directory
SomeDir          # parent directory containing SomeDir/.git
```

If `--path` is a parent directory with a real `.git` directory (not a `gitdir` file) and no `--name` is given, `restore` auto-enables in-place restore (equivalent to `--here`).

- `--name TARGET` takes precedence: it forces the move-out restore even for a parent directory path.
- If the parent directory's `.git` is a file (a `gitdir` link, i.e. a linked worktree or submodule), `restore` rejects it and asks for the actual Git directory, because worktrees are not supported.

## Remote Selection

If `--remote` is omitted:

- If the repository has exactly one remote, use it.
- If the repository has multiple remotes and one is named `origin`, use `origin`.
- Otherwise, fail and ask the user to pass `--remote`.

## Archive

Input is a normal repository directory:

```text
SomeDir/.git
```

Before conversion:

- The repository must be non-bare.
- The repository must be clean, including untracked files.
- `.git/config` is backed up:

  ```text
  .git/config -> .git/config.backup.<YYYYmmddHHMMSS>
  ```

Conversion updates config:

```ini
[core]
    bare = true

[remote "origin"]
    mirror = true
    fetch = +refs/*:refs/*
```

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

The source must be:

- `core.bare = true`
- `remote.<remote>.mirror = true`

Before restore modifies config, it backs up the source config:

```text
config -> config.backup.<YYYYmmddHHMMSS>
```

Default restore creates or uses an empty target directory, moves the archive Git directory to:

```text
TARGET/.git
```

Then it updates config:

```ini
[core]
    bare = false

[remote "origin"]
    mirror = false
    fetch = +refs/heads/*:refs/remotes/origin/*
```

If `--checkout BRANCH` is provided, restore checks out that branch and resets the worktree to it.

If `--checkout` is not provided, restore does not checkout files.

`--here` is the in-place restore mode:

- `--path` must point to an archive `.git` directory, such as `SomeDir/.git`.
- The Git directory is not moved.
- The same config backup and config mutation rules apply.
- If `--checkout BRANCH` is provided, the parent directory of `.git` is checked out and reset to that branch.
- If `--checkout` is omitted, existing worktree files are left as-is.

When `--path` is a parent directory (e.g. `SomeDir`) containing a real `.git` directory and `--name` is omitted, `restore` automatically applies in-place restore and prints a notice.

## Target Rules

If `--name TARGET` is provided, use it.

`--name` is ignored by `--here`; in-place restore always uses the parent directory of the `.git` path.

If `--name` is omitted:

- For source paths ending in `.git`, strip that suffix:

  ```text
  FoneTool.git -> FoneTool
  ```

- For source paths named `.git`, derive the target from `remote.<remote>.url` and place it next to the parent worktree directory.

- If no target can be inferred, fail and ask the user to pass `TARGET`.

Target must not exist or must be empty.

## Safety Rules

- Config is backed up before every conversion direction.
- `archive` refuses dirty repositories.
- `restore` refuses non-archive sources.
- `restore` refuses non-empty target directories.
- `archive --clean` asks for confirmation when ignored files exist, unless `--force`.
- `restore` rejects parent directory paths whose `.git` is a `gitdir` file (worktree unsupported).
- The tool prints each important operation before executing it:
  - config backup
  - config mutation
  - git directory move
  - optional checkout

## Tests

Covered scenarios:

- Normal clean repository converts to archive config.
- Dirty repository refuses archive conversion.
- Archive repository restores to normal config.
- Restore honors explicit target directory.
- Restore without `--checkout` does not checkout files.
- Restore with `--checkout` checks out files.
- Target inference from `*.git` and remote URL.
- Non-empty target is rejected.
- Non-archive source is rejected.
- Remote auto-detection: single remote, `origin` among multiple, and failure without `origin`.
- `--clean` removes working directory files.
- `--clean` prompts when ignored files exist; `--force` skips the prompt.
- `restore` auto-enables in-place restore for a parent directory with a real `.git` directory.
- `restore` honors `--name` (move-out) even for a parent directory path.
- `restore` rejects a parent directory whose `.git` is a `gitdir` file.
