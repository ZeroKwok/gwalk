# gdeploy Manifest Deploy Rules

## Summary

`gdeploy` manages a Git workspace from a manifest file. It has three modes:

- Deploy mode: read the manifest and clone or update repositories in the workspace.
- Scan mode: walk the current workspace, merge discovered repositories into the manifest, show a diff, and write only after confirmation.
- Upgrade mode: upgrade only the manifest schema, show a diff, and write after confirmation, without scanning repositories or deploying.

Default manifest path is:

```text
<directory>/gdeploy.manifest
```

`--directory` defaults to the current directory. Scan treats it as the actual project root. Deploy normally creates a project subdirectory using the manifest `name`; `--here` uses the directory itself. Manifest lookup occurs before choosing the deployment project root and does not change with `name`.

CLI:

```bash
gdeploy [-d WORKSPACE] [MANIFEST]
gdeploy --scan [-d WORKSPACE] [MANIFEST]
gdeploy --scan --listed [-d WORKSPACE] [MANIFEST]
gdeploy --upgrade [-d DIRECTORY] [MANIFEST]
gdeploy --remote NAME [--remote NAME ...] [-d WORKSPACE] [MANIFEST]
gdeploy --scan --remote NAME [--remote NAME ...] [-d WORKSPACE] [MANIFEST]
gdeploy --scan --sync-remotes [-d WORKSPACE] [MANIFEST]
gdeploy -H [-d WORKSPACE] [MANIFEST]
gdeploy --here [-d WORKSPACE] [MANIFEST]
gdeploy --commit [-d WORKSPACE] [MANIFEST]
gdeploy --sync-remotes [-d WORKSPACE] [MANIFEST]
gdeploy --checkout [-d WORKSPACE] [MANIFEST]
```

## Manifest Format

The manifest is a Python literal file parsed with `ast.literal_eval`. It supports comments outside the literal body through normal Python file comments, but the actual manifest data must be a literal `dict`.

Top-level structure:

```python
{
    'schema_version': 1,
    'name': 'FoneTool',
    'variables': [
        {
            'name': 'Host',
            'value': 'https://example.com/group',
        },
    ],
    'repositories': [
        {
            'path': '.',
            'remote': {'origin': '{Host}/{RepositoryName}.git'},
            'branch': 'dev',
        },
        {
            'path': 'com/uiframe',
            'mode': 'archive',
            'remote': {
                'origin': '{Host}/{RepositoryName}.git',
                'github': 'https://github.com/example/uiframe.git',
            },
            'branch': 'dev',
            'commit': '7f4a9f2f8d1f8f6b1b2c3d4e5f60718293a4b5c6',
            'describe': 'v1.2.0-3-g7f4a9f2',
            'post': 'npm install',
        },
    ],
}
```

`schema_version` is an integer independent of the tool version; the current schema is `1`. `name` is the project name and default deployment directory name. It must be a single nonempty directory name, not a path. Scan preserves an existing name; a newly generated manifest uses the scan directory name. A project containing multiple independent repositories uses their relative paths and does not need a `path: '.'` entry.

Repository fields:

- `path`: repository directory relative to the project root. The root repository is `.`; children are `bin`, `com/uiframe`, etc. Physical project directory names never appear as a path prefix. Absolute paths, `..` traversal, and duplicate repository paths are rejected.
- `mode`: optional repository layout. Missing means deploy detects the actual layout of an existing target before defaulting to a normal worktree repository. Supported values are `archive`, `mirror`, and `bare`.
- `remote`: named remote map. Values may be a string URL or a list of URL fallbacks.
- `branch`: optional target branch.
- `commit`: optional target commit ID recorded by scan.
- `describe`: optional repository description recorded by scan.
- `post`: optional command or list of commands executed after clone/update.

Disable a repository by commenting it out or removing it.

Variable replacement applies to `remote`, `branch`, `commit`, and `post`.

Supported variables:

- Manifest variables: `{'name': 'Host', 'value': '...'}` can be used as `{Host}`.
- `{RepositoryName}`: basename of the repository path; for `path: '.'`, the manifest `name`.
- `{RepositoryPath}`: project-relative repository path, including `.` for the root.
- `{Workspace}`: absolute actual project root, after deploy has applied `name` or `--here`.

## Manifest Upgrade

`upgrade_manifest(manifest, default_name=None)` returns a validated schema-1 copy in memory. It never writes a file or mutates its argument. Deploy and scan call it before processing repositories. Unsupported, non-integer, or future schema versions fail before any Git operations. No version field (or explicit `0`) means the unversioned Python-literal manifest; old `.conf` formats are not supported.

For an unversioned manifest with a unique root repository entry, upgrade derives `name` from that entry's basename, converts its `path` to `.`, and removes that full root prefix from descendant `path` and submodule `parent` values. An existing explicit `name` is preserved. For an already-relative root `.` or an empty manifest, the fallback name is the scan directory name, or the manifest's parent directory name during deployment or standalone upgrade. Other fields, including variables, `post`, mode, and extra metadata, are preserved.

If the old root cannot be identified reliably (for example, multiple roots or sibling paths whose root entry is absent), automatic upgrade fails with instructions to specify schema 1, a project name, and project-relative paths explicitly. Upgrade also compares expanded `remote`, `branch`, `commit`, and `post` values under the old and new path rules. A change caused by path-dependent variables such as `{RepositoryPath}` or `{Workspace}` requires manual review and stops automatic upgrade rather than silently changing a URL or command.

Deployment only uses the upgraded data and leaves the source file untouched. Scan compares the original manifest data with the upgraded, scanned result, so schema changes appear in the same diff as repository changes. A confirmed scan or standalone `--upgrade` persists the upgrade; canceling either leaves the original file untouched and creates no backup.

`gdeploy --upgrade [MANIFEST]` performs only format conversion. It does not inspect Git state, fetch remotes, run commands, or refresh branches, commits, and descriptions. It can operate even when the repositories are not present. The file must exist; `-d` selects the directory for the default `gdeploy.manifest` when no explicit file is given. It cannot be combined with `--scan`, `--listed`, `--remote`, `--here`, `--commit`, `--sync-remotes`, or `--checkout`. An already-current manifest returns successfully without a prompt or rewrite.

When a confirmed scan or standalone upgrade converts an existing unversioned file, it first saves the original bytes as `<manifest>.backup.<timestamp>`, then writes a same-directory temporary file and atomically replaces the manifest. The original comments are preserved in the backup; serialization does not retain comments in the new file. Backup or write failure stops the operation without replacing the original. Current-schema scans do not create upgrade backups, and an unchanged current-schema manifest is not rewritten.

## Scan Rules

Scan mode uses `gwalk.RepoWalk(workspace, recursive=True)` to discover repositories.

For each repository, scan records:

- `path`: relative path from the actual project root, using `/` separators.
- `mode`: omitted for normal worktree repositories; recorded as `archive`, `mirror`, or `bare` for non-worktree layouts.
- `remote`: Git remotes by name.
- `branch`: active branch name.
- `commit`: current `HEAD` commit ID.
- `describe`: output of `git describe --tags --dirty --always`; empty string if Git cannot describe the repository.

The root repository is always recorded as `.`, independent of the physical project directory name. Scan uses the directory itself as the project root; `--scan --here` is equivalent to ordinary scan.

Example:

```text
Project directory: H:\Projects\FoneToolBackup
Manifest name: FoneTool
Root repo path: .
Nested repo path: com/uiframe
```

Detached HEAD repositories are still scanned and record their current `commit`. If an existing manifest names a branch containing that commit, scan preserves the original `branch` value (including variables). It checks the local branch, then the selected remote's locally available tracking branch, without fetching. Otherwise it writes `branch: None`, replacing any stale branch name. A detached HEAD warning is printed in either case. Deploy with `--commit` to restore the exact snapshot; without it, deployment does not use the recorded commit and may advance the recorded branch to its tip.

If `describe` ends with `-dirty`, scan prints a yellow warning:

```text
Warning: dirty repository: com/uiframe (v1.2.0-3-g7f4a9f2-dirty)
```

Git submodules are written to the manifest as visible entries, but marked as submodules. If scan encounters a repository represented by a `.git` file, it records `type: 'submodule'`, records its nearest parent repository path, and prints a yellow warning:

```text
Warning: found git submodule: com/library
```

Example:

```python
{
    'path': 'com/library',
    'type': 'submodule',
    'parent': '.',
    'commit': '...',
    'describe': '...',
    'remote': {'origin': '...'},
    'branch': 'main',
}
```

Scan prints each walked repository:

```text
Scan com/uiframe
```

This keeps long scans visibly active when a workspace has many nested repositories.

Non-worktree mode detection:

- `mode: 'archive'`: the repository path is a directory containing only `.git`, that `.git` directory carries a `config.archive` marker, and it is a bare mirror repository.
- `mode: 'mirror'`: the repository path itself is a bare repository and the selected remote has `mirror = true`.
- `mode: 'bare'`: the repository path itself is a bare repository without mirror mode.

When `mode` is omitted and the target already exists, deploy detects the actual layout (`archive`, `mirror`, `bare`, or `worktree`) and applies the matching handling instead of forcing a worktree checkout.

If an existing manifest entry has `mode: 'archive'` and the local repository is currently a normal worktree, scan keeps `mode: 'archive'`. This prevents a temporary checkout from changing the user's backup/deploy strategy.

Remote handling in scan mode:

- Without `--remote`, all Git remotes are recorded.
- With one or more `--remote NAME` options, the names form a priority list.
- Scan records only the first preferred remote that exists in each repository.
- If none of the preferred remote names exist in a repository, scan records all remotes for that repository.

Scan does not infer `post` commands.

Listed-only scan:

- `gdeploy --scan --listed` scans the workspace but only updates repositories already present in the manifest.
- New repositories discovered in the workspace are ignored and are not appended.
- This is useful when the manifest intentionally tracks only a subset of a workspace and you only want to refresh branch, commit, describe, and remote state for that subset.
- Existing merge behavior still applies for listed repositories, including preserving `post`.
- Remote conflicts are checked only for listed repositories after the scan is filtered.
- The manifest must exist and list at least one repository. Missing or empty manifests fail before scanning; zero matches fail with path examples and do not offer a write.
- Missing listed repositories are named and their entries preserved. Matched repositories can still be updated after confirmation, but an incomplete scan returns `1`. It does not claim the manifest is up to date while listed repositories are missing.

## Manifest Update Rules

Scan mode does not replace the whole manifest blindly. It merges scanned repositories into the existing manifest by `path`.

Merge behavior:

- Existing `name`, `schema_version`, `variables`, and extra top-level metadata are preserved in the upgraded structure.
- If a scanned repository already exists in the manifest, scanned fields update the manifest entry. Its `remote` field follows the conflict rules below.
- Existing `post` is preserved when the same repository is updated by scan.
- Repositories already in the manifest but not found by scan are preserved.
- New scanned repositories are appended.
- Final repository list is sorted by path.

Scan treats local Git configuration as the source for remote updates, but never changes that configuration. For each repository already in the manifest, it compares remote names and the local first fetch URL against the manifest's allowed URLs after variable expansion. A URL match under a different name is a conflict. If all selected remotes match, scan preserves the original manifest `remote` value, including variables and URL fallback lists. If the manifest has no remote value, a discovered local remote is added without a conflict prompt. New repositories are also added without a conflict prompt.

On a conflict, scan shows the manifest and local name/URL pairs. Interactive `y` uses the scanned local remotes in the manifest; any other answer preserves the manifest `remote` while still updating other scanned fields such as `branch`, `commit`, and `describe`. Without an interactive terminal, a conflict stops the scan before any manifest write. `--scan --sync-remotes` approves all such replacements without individual prompts, but the final manifest diff and write confirmation still apply. It never updates local Git remotes. When `--remote NAME` filters scan results, approving a conflict replaces the old remote map with the filtered scanned map; unselected names are not retained.

Scan may still overwrite variable-based fields such as `branch` when their current values differ. `post` is preserved because it cannot be discovered from Git state.

Before writing, scan mode renders both the old manifest and the new manifest with the same formatter, then prints a unified diff:

```text
--- gdeploy.manifest (old)
+++ gdeploy.manifest (new)
@@ ...
```

Only input `y` writes the file. Any other input cancels and returns non-zero.

This means pure formatting differences in the existing manifest, such as indentation, wrapping, or extra spaces, are ignored by the diff. The diff is intended to show manifest data changes, not formatting churn.

## Remote Selection During Deploy

Deploy mode chooses a concrete URL from the repository `remote` map.

Rules:

- With `--remote NAME`, use `remote[NAME]` if it exists.
- With multiple `--remote NAME` options, use the first matching remote in that priority order.
- If none of the preferred remote names exist, use the first remote in the manifest entry.
- Without `--remote`, use `origin` if it exists.
- Without `--remote` and without `origin`, use the first remote in the manifest entry.

If the chosen remote value is a list, URLs are tried in order until clone succeeds.

For an existing repository, the selected remote name is part of the manifest contract. Deploy compares that named remote's first fetch URL with the manifest's allowed URLs. A match needs no action. If the name is missing, deploy shows the repository path relative to the workspace, then the manifest name and URL, followed by existing remote names and URLs. An existing remote with an allowed URL is marked `(same fetch URL)`. One existing remote is shown on a single `Existing:` line; multiple remotes are listed below `Existing:`. Even when `origin` has the same URL as manifest `github`, it does not silently substitute `origin`: confirmation creates `github` and leaves `origin` unchanged. If the name exists with a different URL, deploy shows the same relative path, then the manifest and existing name/URL pairs before asking whether to update it. Declining fails that repository without changing its remotes. Without an interactive terminal, a missing or mismatched remote fails. `--sync-remotes` explicitly approves creation or update for unattended deployment. Other named remotes are left alone. Newly cloned repositories use the selected remote name instead of always creating `origin`.

For example, if manifest `github` is missing while local `origin` has the same URL:

```text
Manifest remote 'github' is missing in com/pyembed
  Manifest: github -> https://github.com/ZeroKwok/pyembed.git
  Existing: origin -> https://github.com/ZeroKwok/pyembed.git (same fetch URL)
Add remote 'github'? [y/N]
```

Example:

```python
'remote': {
    'origin': [
        'http://internal/example.git',
        'https://public/example.git',
    ],
    'github': 'https://github.com/example/example.git',
}
```

Without `--remote`, deploy uses `origin` and tries the internal URL first, then the public URL.

With `--remote github`, deploy uses only the `github` URL.

With `--remote github --remote origin`, deploy uses `github` when available, otherwise `origin` when available.

With `--remote missing`, deploy falls back to the first remote in the manifest entry.

## Deploy Flow

Parent repositories are processed before nested repositories, even if entries appear in the opposite order. For each repository entry:

1. If `type` is `submodule`, skip independent deployment and print:

   ```text
   Skip submodule: com/library (managed by .)
   ```

2. Resolve variables in `remote`, `branch`, and `post`.
3. Compute target path as `<project root>/<path>`.
4. If target does not exist:
   - Require at least one selected remote URL.
   - Create the parent directory.
   - Clone from selected remote URLs in order.
   - If a clone attempt fails and leaves a partial target directory, remove it before trying the next URL.
   - Finish the requested branch or commit checkout, then update submodules and run `post`.
5. If target exists and is an empty directory:
   - Clone into that empty directory.
   - This supports users who create the deployment directory before running `gdeploy`.
6. If target exists and is not empty:
   - It must be a Git repository root.
   - Non-Git directories are not overwritten and count as failures.
   - Verify the selected remote URL, fetch that remote, then apply either the branch or commit flow below.
7. If `post` exists:
   - Run it only after the final checkout and submodule update succeed.
   - Run each command with the repository root as working directory.
   - Commands are executed with `shell=True`.
   - Any non-zero command marks `post_failed`, but deployment continues to following repositories.

Repository modes:

- Missing `mode` deploys a normal worktree repository using the rules above.
- `mode: 'archive'` creates or updates `<target>/.git` with `garchive clone` archive storage, including `config.archive` and `mate.archive`. By default it only fetches the selected remote and does not checkout files or run `post`.
- `mode: 'mirror'` creates or updates `<target>` as a bare mirror repository. It fetches the selected remote and does not checkout files or run `post`.
- `mode: 'bare'` creates or updates `<target>` as a bare non-mirror repository. It fetches the selected remote and does not checkout files or run `post`.

Archive checkout:

- `--checkout` applies only to `mode: 'archive'`.
- When an archive repository is still in `<target>/.git` layout, `gdeploy` calls `garchive` to restore it in place, then checks out the requested branch or commit. Snapshot checkout verifies the commit exists before converting the archive.
- If `--checkout` is used with `mode: 'mirror'` or `mode: 'bare'`, gdeploy prints a warning and keeps the repository unchanged.
- `post` commands for archive repositories run only after `--checkout` has produced a normal worktree.

Commit checkout:

- By default, deploy does not use the manifest `commit` field.
- With `--commit`, deploy fetches the selected remote and verifies that the manifest `commit` is available in the local object database. A missing field or unavailable commit fails that repository.
- The worktree must be clean, including the index, untracked files, and submodules. A merge, rebase, cherry-pick, or revert in progress also fails the checkout. Git's own checkout protection is not a substitute: nonconflicting edits could otherwise survive the switch.
- A manifest branch must be a valid literal local branch name. Attachment uses only the selected remote's freshly fetched `refs/remotes/<remote>/<branch>`, not an arbitrary existing upstream.
- When that remote branch contains the manifest commit, and the existing local target branch has no commits outside it, deploy runs `git switch -C <branch> <commit>`. A missing local branch is created; a branch already at the commit uses plain `git switch <branch>`. A published local tip may move backwards to the snapshot, which is reported in the checkout output.
- A missing upstream is set to the selected remote branch after attachment. An existing different upstream is never overwritten.
- If the manifest has no branch, the selected remote branch is unavailable or does not contain the commit, the local target branch has unpushed/divergent commits, or its upstream differs, deploy prints a yellow explanation and runs `git switch --detach <commit>`, preserving the local branch and its configuration.
- Before leaving a different detached HEAD, deploy checks whether it is reachable from any local branch, remote-tracking branch, or tag. If not, checkout fails and asks the user to save a branch first. Reflog entries alone do not count as saved references. Keeping the same detached commit is allowed.
- Git handles switch-level restrictions, such as a branch being checked out in another worktree. A failed switch fails deployment; it does not trigger a forced checkout or a detached retry. No `pull`, `reset --hard`, push, or automatic backup branch is used by the snapshot checkout policy.
- The final HEAD always equals the manifest commit on success. Attached snapshots may be behind the remote; another `--commit` deployment keeps that snapshot, while normal branch deployment may fast-forward it. Submodules and `post` run only after checkout succeeds.
- Archive repositories apply the commit only when `--checkout` is also specified; bare and mirror repositories remain bare.
- Archive snapshot restore performs commit, operation, and detached-HEAD safety checks before conversion, materializes the commit without moving a branch, fetches with the restored configuration, and then applies the same attachment policy as normal worktrees. Its manifest `mode` is unchanged.

By default, the manifest `name` determines the project subdirectory:

```text
Directory: H:\Projects
Name:      FoneTool
Path:      .
Target:    H:\Projects\FoneTool
```

With `-H` or `--here`, the actual project root is the specified directory. The name remains project metadata and repository paths do not change:

```text
Directory: H:\Projects\FoneToolBackup
Name:      FoneTool
Path:      .
Target:    H:\Projects\FoneToolBackup

Path:      com/uiframe
Target:    H:\Projects\FoneToolBackup\com\uiframe
```

This rule also applies to a project with several independent repositories and no root Git repository. No unique-root inference or prefix mapping is needed for schema 1. Worktree, archive, mirror, and bare modes all use the same project-root-relative layout. Nonempty non-Git clone targets remain unsupported.

Branch handling:

- Normal deployment fetches the selected remote before switching branches. A clone already includes this fetch.
- If no `branch` is specified, branch checkout and merge are skipped.
- If the local branch exists, switch to it. Otherwise, create it from `<remote>/<branch>` with tracking.
- The selected remote branch must exist. Deploy runs `git merge --ff-only <remote>/<branch>` after switching, so a local upstream is not required.
- A divergent branch or dirty worktree fails that repository. Deploy never automatically runs `reset --hard`.

Submodule handling:

- After the parent repository reaches its final branch or commit, if it has submodules, deploy runs:

  ```bash
  git submodule update --init --recursive
  ```

- Submodules are therefore managed through their parent repository, not as separate manifest entries.

At the end, deploy prints:

```text
Done. <n> cloned, <n> updated, <n> post failed, <n> skipped, <n> failed.
```

Exit code is `0` only when both `failed` and `post_failed` are zero.
