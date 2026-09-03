# gwalk Repository Walk Rules

## Summary

`gwalk` walks Git repositories under a directory, filters them, displays status, and optionally performs an action on each matched repository.

CLI:

```bash
gwalk [OPTIONS] [-- PARAMS...]
```

Common examples:

```bash
gwalk
gwalk -rf all
gwalk -rf dirty -a run git status -s
gwalk -rf all -a run gl
gwalk -rf all -j -a run git fetch --all
gwalk -a bash
```

## Repository Discovery

`RepoWalk` discovers repository roots under `--directory`.

Default behavior without `--recursive`:

- Check whether the base directory itself is a Git repository root.
- Check immediate child directories.
- Skip child directories named `.git`, `.vs`, and `.vscode`.
- Do not continue deeper than one level.

Recursive behavior with `--recursive`:

- Walk all subdirectories with `os.walk`.
- Yield every directory that looks like a Git repository root.

Repository root detection:

- A directory containing `.git` **as a directory** is treated as a normal Git repository.
- A directory containing `.git` **as a file** is treated as a submodule-style repository.
- A directory containing `objects`, `refs`, `HEAD`, and `config` is treated as a bare repository.
- Git metadata directories are not recursively scanned as separate repositories.

`RepoName(directory, root)` displays repository paths relative to the search root. If the repository is the root itself, the basename is shown.

For bare repositories, Git operations run from the repository's git directory because the parent directory has no work tree. Bare repositories are displayed as `Clean (archive mirror)`, `Clean (mirror)`, or `Clean (bare)`.

## Status Filtering

Each candidate repository is represented by `RepoStatus`.

Status is loaded with:

```bash
git status --porcelain=1 --untracked-files=normal
```

Bare repositories have no work tree, so status loading is skipped and they are treated as clean.

Filter choices:

- `all`: match every repository.
- `clean`: match repositories with no loaded status entries.
- `dirty`: match repositories with modified or untracked content.
- `modified`: match repositories with tracked file changes.
- `untracked`: match repositories with untracked files.

Default filter is `dirty`.

When `--filter all --level none` is used, status loading is skipped for speed because no status information is displayed or needed for filtering.

Detached HEAD:

- Displayed as `HEAD is detached`.
- Command placeholders requiring active branch may fail when used in actions.

## Path And Command Filters

Blacklist and whitelist files contain regular expressions, one per line.

Rules:

- Empty lines and lines starting with `#` are ignored.
- Paths are normalized to use `/` before matching.
- `--blacklist FILE` excludes matching repositories.
- If no blacklist is provided and `gwalk.blacklist` exists in the current directory, it is used by default.
- `--whitelist FILE` includes only matching repositories and disables blacklist behavior.
- `--force` disables blacklist behavior.

Command test filter:

```bash
gwalk -t "git tag | grep -q v1.0.0"
```

`--test CMD` runs `CMD` in each repository. Only repositories where the command exits with `0` match.

## Display Levels

Display level controls status output for matched repositories:

- `none`: print only repository path.
- `brief`: print path, active branch, and counts of modified/untracked entries.
- `normal`: run `git status -s --untracked-files=normal --ignore-submodules=all`.

Default level is `brief`.

`--verbose` can be repeated and is used for debug-style filtering and action output.

## Actions

Actions run only for repositories that pass all filters.

Supported actions:

- `bash`: start an interactive bash shell in the repository.
- `gui`: run `git gui` in the repository.
- `run`: execute a shell command in the repository.
- no action: only list/display matched repositories.

Run command placeholders:

- `{ab}`: active branch name.
- `{ActiveBranch}`: active branch name.
- `{RepositoryName}`: basename of the repository working directory.
- `{cwd}`: base search directory.

Example:

```bash
gwalk -rf all -a run git push origin {ab}
```

If `{ab}` or `{ActiveBranch}` is used while HEAD is detached, action formatting raises an error for that repository.

## Sequential And Parallel Execution

By default, actions run sequentially with `RepoHandler`.

`-j` enables parallel execution for `-a run` only:

- No `-j`: sequential execution.
- `-j` without a value: use automatic concurrency.
- `-j N`: run up to `N` concurrent commands.
- `-j 0`: normalized back to sequential.

If `-j` is used without `-a run`, `gwalk` prints a warning and falls back to sequential behavior.

Parallel execution uses `asyncio.create_subprocess_shell` with each repository as the working directory.

While waiting, `gwalk` prints a progress spinner and the number of pending tasks. `Ctrl+C` reports partial completed and aborted tasks.

Failure output:

- Sequential mode records success/failure code for each run action.
- Parallel mode records stdout, stderr, return code, or exception.
- Failure summaries print failed repository names.
- In parallel mode, failure output is truncated unless verbose output is requested.

## Final Summary

After walking repositories, `gwalk` prints:

```text
Walked <total> repo, matched: <matched>, ignored: <ignored>; Run result: ...
```

Definitions:

- `matched`: repositories that passed filters and were displayed/actioned.
- `ignored`: repositories skipped by blacklist/whitelist, status filter, or command test.
- `total`: matched plus ignored repositories encountered by `RepoWalk`.

If any action failed, `gwalk` prints the failed repository list.

## Version And Debug

`--version` prints project name, version, author, and homepage, then exits.

`--debug` increases verbosity and pauses at startup so a debugger can attach:

```text
Wait for debugging and press Enter to continue...
```
