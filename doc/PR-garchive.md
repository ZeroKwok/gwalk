# garchive Archive Conversion Rules

## Summary

`garchive` converts a Git repository between a normal worktree repository and an archive-style bare mirror repository.

The goal is backup/storage:

- `to-archive` keeps only Git repository metadata as the active repository layout.
- `restore` recreates a normal repository directory from the archive repository.

CLI:

```bash
garchive --archive [--path PATH] [--remote origin]
garchive --restore [--path PATH] [--name TARGET] [--remote origin] [--branch BRANCH]
```

`--path` defaults to the current directory.

## To Archive

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

Restore creates or uses an empty target directory, moves the archive Git directory to:

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

If `--branch BRANCH` is provided, restore checks out that branch and resets the worktree to it.

If `--branch` is not provided, restore does not checkout files.

## Target Rules

If `--name TARGET` is provided, use it.

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
- `to-archive` refuses dirty repositories.
- `restore` refuses non-archive sources.
- `restore` refuses non-empty target directories.
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
- Restore without `--branch` does not checkout files.
- Restore with `--branch` checks out files.
- Target inference from `*.git` and remote URL.
- Non-empty target is rejected.
- Non-archive source is rejected.
