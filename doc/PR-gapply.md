# gapply Patch Apply Rules

## Summary

`gapply` is a small helper around `git apply`, staging, and commit creation.

It accepts one or more patch files, extracts metadata from each patch, applies the patch, stages changed files, creates a commit, and optionally deletes the patch file.

CLI:

```bash
gapply [OPTIONS] PATCH_FILE [PATCH_FILE ...]
```

Common examples:

```bash
gapply patchs/0001-feature.patch
gapply -n patchs/0001-feature.patch
gapply -d patchs/0001-feature.patch
gapply -D patchs/0001-feature.patch
gapply -j 3-8 patchs/*.patch
```

## Patch Metadata Extraction

`gapply` reads each patch as UTF-8 text and extracts:

- `subject`: used as the commit message.
- `newfiles`: files that need explicit `git add`.

Subject parsing:

- Finds the first `Subject:` header.
- Removes leading `[PATCH] `.
- Removes leading `[PATCH N/M] `.
- Joins folded email subject continuation lines that start with space or tab.
- Decodes MIME-encoded subject fragments when possible.

New file parsing:

- When a patch contains `new file mode`, the previous `diff --git a/... b/...` line is used to identify the new file path.
- When a patch contains `rename to ...`, the renamed target path is recorded.

The parsed `newfiles` list is used after `git add -u`, because newly created or renamed paths may need explicit staging.

## Apply Flow

For each patch file, `gapply` executes these steps in order:

1. Validate the patch path exists as a file.
2. Print the patch path.
3. Extract metadata from the patch.
4. If `--verbose` or `--dry-run` is enabled, print parsed metadata.
5. Run:

   ```bash
   git apply -v "<patch_file>"
   ```

6. Stage changed tracked files:

   ```bash
   git add -u
   ```

7. Stage extracted new or renamed files:

   ```bash
   git add "<newfile>"
   ```

8. Create the commit:

   ```bash
   git commit -m "<subject>"
   ```

If any Git command fails, `gapply` prints a manual recovery message and exits with that command's status code.

## Dry Run

`--dry-run` does not execute Git commands or delete patch files.

Instead it prints the commands that would run:

```text
(dry-run) > git apply -v "patch.patch"
(dry-run) > git add -u
(dry-run) > git add "new_file.py"
(dry-run) > git commit -m "subject"
```

Dry run also prints extracted metadata, the same as verbose mode.

## Delete Rules

`--delete` asks before deleting each patch after a successful apply and commit:

```text
Delete patch file 'patch.patch'? [y/N]:
```

Accepted answers:

- `y` or `yes`: delete the patch file.
- empty input, `n`, or `no`: keep the patch file.

`--force-delete` deletes without confirmation.

In dry-run mode, delete options only print what would be deleted.

## Jitter Rules

`--jitter MIN-MAX` adds a random delay between patch files after each successful patch except the last one.

Example:

```bash
gapply -j 3-8 patch1.patch patch2.patch
```

The delay is randomly selected with `random.uniform(MIN, MAX)`.

If the jitter value cannot be parsed as `MIN-MAX`, `gapply` prints a warning and continues without jitter.

## Limitations And Edge Cases

- Patch files are read as UTF-8.
- Commit subject comes only from the patch `Subject:` header.
- If no subject is found, `git commit -m "None"` is currently attempted.
- Commands run in the current working directory, so the caller should run `gapply` from the target Git repository.
- The tool expects Git format-patch style input; other patch formats may not provide enough metadata for commit creation.
