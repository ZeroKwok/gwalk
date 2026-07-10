# gdeploy Manifest Deploy Rules

## Summary

`gdeploy` manages a Git workspace from a manifest file. It has two modes:

- Deploy mode: read the manifest and clone or update repositories in the workspace.
- Scan mode: walk the current workspace, merge discovered repositories into the manifest, show a diff, and write only after confirmation.

Default manifest path is:

```text
<workspace>/gdeploy.manifest
```

CLI:

```bash
gdeploy [-d WORKSPACE] [MANIFEST]
gdeploy --scan [-d WORKSPACE] [MANIFEST]
gdeploy --scan --listed [-d WORKSPACE] [MANIFEST]
gdeploy --remote NAME [-d WORKSPACE] [MANIFEST]
gdeploy --scan --remote NAME [-d WORKSPACE] [MANIFEST]
gdeploy -H [-d WORKSPACE] [MANIFEST]
gdeploy --here [-d WORKSPACE] [MANIFEST]
gdeploy --commit [-d WORKSPACE] [MANIFEST]
```

## Manifest Format

The manifest is a Python literal file parsed with `ast.literal_eval`. It supports comments outside the literal body through normal Python file comments, but the actual manifest data must be a literal `dict`.

Top-level structure:

```python
{
    'variables': [
        {
            'name': 'Host',
            'value': 'https://example.com/group',
        },
    ],
    'repositories': [
        {
            'path': 'com/uiframe',
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

Repository fields:

- `path`: repository directory relative to workspace.
- `remote`: named remote map. Values may be a string URL or a list of URL fallbacks.
- `branch`: optional target branch.
- `commit`: optional target commit ID recorded by scan.
- `describe`: optional repository description recorded by scan.
- `post`: optional command or list of commands executed after clone/update.

Disable a repository by commenting it out or removing it.

Variable replacement applies to `remote`, `branch`, and `post`.

Supported variables:

- Manifest variables: `{'name': 'Host', 'value': '...'}` can be used as `{Host}`.
- `{RepositoryName}`: basename of the repository path.
- `{RepositoryPath}`: repository path relative to workspace.
- `{Workspace}`: absolute workspace path.

## Scan Rules

Scan mode uses `gwalk.RepoWalk(workspace, recursive=True)` to discover repositories.

For each repository, scan records:

- `path`: relative path from workspace, using `/` separators.
- `remote`: Git remotes by name.
- `branch`: active branch name.
- `commit`: current `HEAD` commit ID.
- `describe`: output of `git describe --tags --dirty --always`; empty string if Git cannot describe the repository.

When the scan workspace itself is a Git repository root, the root repository path is written as the workspace directory name instead of `.`. Nested repositories are written under that name.

Example:

```text
Workspace: H:\Projects\FoneToolBackup
Root repo path: FoneToolBackup
Nested repo path: FoneToolBackup/com/uiframe
```

Detached HEAD repositories keep their `path` and `remote`, but omit `branch` and print a warning.

If `describe` ends with `-dirty`, scan prints a yellow warning:

```text
Warning: dirty repository: com/uiframe (v1.2.0-3-g7f4a9f2-dirty)
```

Git submodules are written to the manifest as visible entries, but marked as submodules. If scan encounters a repository represented by a `.git` file, it records `type: 'submodule'`, records its nearest parent repository path, and prints a yellow warning:

```text
Warning: found git submodule: FoneTool/com/library
```

Example:

```python
{
    'path': 'FoneTool/com/library',
    'type': 'submodule',
    'parent': 'FoneTool',
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

Remote handling in scan mode:

- Without `--remote`, all Git remotes are recorded.
- With `--remote NAME`, if that remote exists in a repository, only that remote is recorded for that repository.
- If `--remote NAME` does not exist in a repository, scan records all remotes for that repository.

Scan does not infer `post` commands.

Listed-only scan:

- `gdeploy --scan --listed` scans the workspace but only updates repositories already present in the manifest.
- New repositories discovered in the workspace are ignored and are not appended.
- This is useful when the manifest intentionally tracks only a subset of a workspace and you only want to refresh branch, commit, describe, and remote state for that subset.
- Existing merge behavior still applies for listed repositories, including preserving `post`.

## Manifest Update Rules

Scan mode does not replace the whole manifest blindly. It merges scanned repositories into the existing manifest by `path`.

Merge behavior:

- Existing `variables` are preserved.
- If a scanned repository already exists in the manifest, scanned fields update the manifest entry.
- Existing `post` is preserved when the same repository is updated by scan.
- Repositories already in the manifest but not found by scan are preserved.
- New scanned repositories are appended.
- Final repository list is sorted by path.

Because scan writes real Git remote URLs and branch names, a previously variable-based `remote` or `branch` may be overwritten. This is intentional. `post` is preserved because it cannot be discovered from Git state.

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
- If `--remote NAME` does not exist, use the first remote in the manifest entry.
- Without `--remote`, use `origin` if it exists.
- Without `--remote` and without `origin`, use the first remote in the manifest entry.

If the chosen remote value is a list, URLs are tried in order until clone succeeds.

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

With `--remote missing`, deploy falls back to the first remote in the manifest entry.

## Deploy Flow

For each repository entry:

1. If `type` is `submodule`, skip independent deployment and print:

   ```text
   Skip submodule: FoneTool/com/library (managed by FoneTool)
   ```

2. Resolve variables in `remote`, `branch`, and `post`.
3. Compute target path as `<workspace>/<path>`.
4. If target does not exist:
   - Require at least one selected remote URL.
   - Create the parent directory.
   - Clone from selected remote URLs in order.
   - If a clone attempt fails and leaves a partial target directory, remove it before trying the next URL.
5. If target exists and is an empty directory:
   - Clone into that empty directory.
   - This supports users who create the deployment directory before running `gdeploy`.
6. If target exists and is not empty:
   - It must be a Git repository root.
   - Non-Git directories are not overwritten and count as failures.
   - Run fetch, checkout branch, and fast-forward pull.
7. If `post` exists:
   - Run each command with the repository root as working directory.
   - Commands are executed with `shell=True`.
   - Any non-zero command marks `post_failed`, but deployment continues to following repositories.

Commit checkout:

- By default, deploy does not use the manifest `commit` field.
- With `--commit`, deploy checks out the repository to the manifest `commit` after clone/update.
- This may leave the repository in detached HEAD state, similar to pinning sub-repository revisions.
- If `commit` is missing, no commit checkout is performed for that repository.

By default, a manifest root path such as `FoneToolBackup` deploys into a subdirectory:

```text
Workspace: I:\Projects
Path:      FoneToolBackup
Target:    I:\Projects\FoneToolBackup
```

With `-H` or `--here`, the first path component is mapped to the workspace itself:

```text
Workspace: I:\Projects\FoneToolBackup
Path:      FoneToolBackup
Target:    I:\Projects\FoneToolBackup

Path:      FoneToolBackup/com/uiframe
Target:    I:\Projects\FoneToolBackup\com\uiframe
```

Branch handling:

- If no `branch` is specified, branch checkout and pull are skipped.
- If the local branch exists, checkout it.
- Otherwise, if a remote tracking branch exists, create a local tracking branch.
- Otherwise, create a new local branch.
- Pull uses `git pull --ff-only`.
- Pull failure is warned but does not immediately abort that repository.

Submodule handling:

- After clone or update, if the repository has submodules, deploy runs:

  ```bash
  git submodule update --init --recursive
  ```

- Submodules are therefore managed through their parent repository, not as separate manifest entries.

At the end, deploy prints:

```text
Done. <n> cloned, <n> updated, <n> post failed, <n> skipped, <n> failed.
```

Exit code is `0` only when both `failed` and `post_failed` are zero.
