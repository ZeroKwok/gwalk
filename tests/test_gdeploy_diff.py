import os
from pathlib import Path
import sys

import git
import pytest

from gwalk import garchive, gdeploy


def commit_file(repo, content):
    (Path(repo.working_dir) / "file.txt").write_text(content, encoding="utf-8")
    repo.index.add(["file.txt"])
    return repo.index.commit(content).hexsha


@pytest.fixture
def workspace(tmp_path):
    source = git.Repo.init(tmp_path / "source")
    for name, email in [("user.name", "Test"), ("user.email", "test@example.com")]:
        source.git.config(name, email)
    first = commit_file(source, "first")
    source.git.branch("-M", "main")
    commit_file(source, "second")
    tip = commit_file(source, "third")
    local = git.Repo.clone_from(source.working_dir, tmp_path / "renamed-project")
    local.git.config("user.name", "Test")
    local.git.config("user.email", "test@example.com")
    return source, local, first, tip


def write_manifest(path, *items, **fields):
    manifest = {"schema_version": 1, "name": "Project", "repositories": list(items), **fields}
    path.write_text(gdeploy.render_manifest(manifest), encoding="utf-8")
    return path


def fetch_url(repo, name="origin"):
    return repo.git.config("--get", f"remote.{name}.url")


@pytest.mark.parametrize("case,expected", [
    ("matched", "Match"),
    ("manifest ahead", "Manifest ahead (2 commits)"),
    ("local ahead", "Local ahead (2 commits)"),
    ("diverged", "Diverged (manifest only: 2, local only: 1)"),
])
def test_diff_reports_snapshot_relationship(workspace, tmp_path, capsys, case, expected):
    _, local, first, tip = workspace
    manifest_commit = tip
    if case in ("manifest ahead", "diverged"):
        local.git.switch("-C", "main", first)
    if case == "diverged":
        commit_file(local, "divergent")
    if case == "local ahead":
        manifest_commit = first
    manifest = write_manifest(tmp_path / "snapshot", {
        "path": ".", "commit": manifest_commit, "remote": {"origin": fetch_url(local)},
        "branch": "unused", "describe": "unrelated-dirty",
    })

    assert gdeploy.diff_manifest(local.working_dir, manifest) == (0 if case == "matched" else 1)
    output = capsys.readouterr().out
    assert output.startswith(f".: {expected}")
    if case == "diverged":
        assert "unpushed commits: 1 (relative to cached origin/main)" in output
    else:
        assert output == f".: {expected}\n"


@pytest.mark.parametrize("here", [None, "-H", "--here"])
def test_diff_cli_default_manifest_is_read_only_and_does_not_fetch(workspace, monkeypatch, capsys, here):
    source, local, _, tip = workspace
    root = Path(local.working_dir)
    git_dir = Path(local.git_dir)
    # The manifest lives in the workspace, but ignored files do not make it dirty.
    with (git_dir / "info" / "exclude").open("a", encoding="utf-8") as stream:
        stream.write("\ngdeploy.manifest\n")
    manifest = write_manifest(root / "gdeploy.manifest", {
        "path": ".", "commit": tip, "remote": {"origin": fetch_url(local)},
        "post": "not a real command",
    })
    git.Repo.init(root / "not-listed")
    with (git_dir / "info" / "exclude").open("a", encoding="utf-8") as stream:
        stream.write("/not-listed/\n")
    commit_file(source, "not yet fetched")
    # An ordinary status refresh could update the index's stat cache.
    os.utime(root / "file.txt", (1_600_000_000, 1_600_000_000))
    tracked_paths = [manifest, git_dir / "config", git_dir / "HEAD", git_dir / "index"]
    before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in tracked_paths]
    if here:
        monkeypatch.chdir(root)
        options = [here]
    else:
        options = ["-d", str(root)]
    monkeypatch.setattr(sys, "argv", ["gdeploy", "--diff", *options])
    monkeypatch.setattr("builtins.input", lambda *args: pytest.fail("unexpected prompt"))
    for name in ("scan_workspace", "deploy_manifest", "run_post_commands"):
        monkeypatch.setattr(gdeploy, name, lambda *args: pytest.fail("unexpected scan or deploy"))

    assert gdeploy.main() == 0
    assert capsys.readouterr().out == ".: Match\n"
    assert local.git.rev_parse("refs/remotes/origin/main") == tip
    assert not (git_dir / "FETCH_HEAD").exists()
    assert [(path.read_bytes(), path.stat().st_mtime_ns) for path in tracked_paths] == before
    assert not list(root.glob("gdeploy.manifest.backup.*"))


@pytest.mark.parametrize("change", ["staged", "unstaged", "untracked"])
def test_diff_reports_uncommitted_changes_even_at_matching_commit(workspace, tmp_path, capsys, change):
    _, local, _, tip = workspace
    filename = "new.txt" if change == "untracked" else "file.txt"
    (Path(local.working_dir) / filename).write_text("changed", encoding="utf-8")
    if change == "staged":
        local.index.add([filename])
    manifest = write_manifest(tmp_path / "snapshot", {
        "path": ".", "commit": tip, "remote": {"origin": fetch_url(local)},
    })

    assert gdeploy.diff_manifest(local.working_dir, manifest) == 1
    assert capsys.readouterr().out == ".: Match: uncommitted changes\n"


def test_diff_unpushed_uses_manifest_remote_and_current_branch(workspace, tmp_path, monkeypatch, capsys):
    _, local, first, _ = workspace
    local.git.switch("-c", "topic/subtopic")
    head = commit_file(local, "local work")
    local.git.update_ref("refs/remotes/origin/topic/subtopic", head)
    local.git.branch("--set-upstream-to=origin/topic/subtopic")
    local.create_remote("public", "https://example.invalid/project.git")
    local.git.update_ref("refs/remotes/public/topic/subtopic", first)
    local.git.update_ref("refs/remotes/public/main", head)
    # A URL from a fallback list counts as a match; the manifest branch is not the active branch.
    manifest = write_manifest(tmp_path / "snapshot", {
        "path": ".", "commit": head, "branch": "main",
        "remote": {"origin": fetch_url(local), "public": ["{Primary}", fetch_url(local, "public")]},
    }, variables=[{"name": "Primary", "value": "https://example.invalid/primary.git"}])

    assert gdeploy.diff_manifest(local.working_dir, manifest) == 0
    assert capsys.readouterr().out == ".: Match\n"
    (Path(local.working_dir) / "file.txt").write_text("dirty", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "gdeploy", "--diff", "-d", local.working_dir,
        "--remote", "missing", "--remote", "public", str(manifest),
    ])
    assert gdeploy.main() == 1
    assert capsys.readouterr().out == (
        ".: Match: uncommitted changes; unpushed commits: 3 (relative to cached public/topic/subtopic)\n"
    )


@pytest.mark.parametrize("case,reason", [
    ("detached", "detached HEAD"),
    ("missing ref", "no cached tracking reference for origin/main"),
    ("missing remote", "local remote another has no fetch URL"),
    ("mismatched URL", "local remote origin URL differs from manifest"),
    ("no manifest remote", "no manifest remote selected"),
])
def test_diff_reports_unknown_unpushed_without_failing_snapshot(workspace, tmp_path, capsys, case, reason):
    _, local, _, tip = workspace
    remotes = {"origin": fetch_url(local)}
    if case == "detached":
        local.git.switch("--detach", tip)
    elif case == "missing ref":
        local.git.update_ref("-d", "refs/remotes/origin/main")
    elif case == "missing remote":
        remotes = {"another": fetch_url(local)}
    elif case == "mismatched URL":
        remotes = {"origin": "https://example.invalid/other.git"}
    elif case == "no manifest remote":
        remotes = {}
    manifest = write_manifest(tmp_path / "snapshot", {"path": ".", "commit": tip, "remote": remotes})

    assert gdeploy.diff_manifest(local.working_dir, manifest) == 0
    assert capsys.readouterr().out == f".: Match: unpushed status unknown ({reason})\n"


def test_diff_reports_incomplete_and_continues_with_other_paths(workspace, tmp_path, capsys):
    _, local, first, tip = workspace
    root = Path(local.working_dir)
    (root / "plain").mkdir()
    git.Repo.init(root / "empty")
    git.Repo.clone_from(local.working_dir, root / "snapshot-missing")
    git.Repo.clone_from(local.working_dir, root / "object-missing")
    git.Repo.clone_from(local.working_dir, root / "z-good")
    manifest = write_manifest(tmp_path / "snapshot", {"path": "missing", "commit": tip},
                              {"path": "plain", "commit": tip}, {"path": "empty", "commit": tip},
                              {"path": "snapshot-missing", "branch": "main"},
                              {"path": "object-missing", "commit": "0" * 40},
                              {"path": "z-good", "commit": first})

    assert gdeploy.diff_manifest(root, manifest) == 2
    output = capsys.readouterr().out
    assert "missing: Cannot compare (repository not found)" in output
    assert "plain: Cannot compare (not a Git repository root)" in output
    assert "empty: Cannot compare (local HEAD has no commit)" in output
    assert "snapshot-missing: Cannot compare (manifest commit is missing)" in output
    assert "object-missing: Cannot compare (manifest commit not found locally" in output
    assert "z-good: Local ahead (2 commits)" in output


def test_diff_uses_legacy_paths_and_expands_commit_without_rewriting(workspace, tmp_path, capsys):
    _, local, _, tip = workspace
    manifest = tmp_path / "legacy"
    original = "# keep\n" + repr({
        "variables": [{"name": "Snapshot", "value": tip}],
        "repositories": [{"path": "OldName", "commit": "{Snapshot}", "remote": fetch_url(local)}],
    })
    manifest.write_text(original, encoding="utf-8")

    assert gdeploy.diff_manifest(local.working_dir, manifest) == 0
    assert capsys.readouterr().out == ".: Match\n"
    assert manifest.read_text(encoding="utf-8") == original
    assert not list(tmp_path.glob("legacy.backup.*"))


@pytest.mark.parametrize("mode", ["bare", "mirror", "archive"])
def test_diff_compares_actual_non_worktree_layouts(workspace, tmp_path, capsys, mode):
    source, _, first, _ = workspace
    directory = tmp_path / mode
    if mode == "archive":
        garchive.clone(source.working_dir, directory)
        repo = git.Repo(directory / ".git")
    else:
        repo = git.Repo.clone_from(source.working_dir, directory, **{mode: True})
    if mode != "bare":
        # A mirror can contain old refs/remotes entries; they are not its tracking baseline.
        repo.git.update_ref("refs/remotes/origin/main", first)
    manifest = write_manifest(tmp_path / "snapshot", {
        "path": ".", "commit": first, "remote": {"origin": fetch_url(repo)},
    })
    capsys.readouterr()

    assert gdeploy.diff_manifest(directory, manifest) == 1
    output = capsys.readouterr().out
    assert output.startswith(".: Local ahead (2 commits): unpushed status unknown")
    assert "uncommitted" not in output
    assert repo.bare


def test_diff_checks_listed_gitfile_submodule(workspace, tmp_path, capsys):
    source, local, first, _ = workspace
    local.git.execute(["git", "-c", "protocol.file.allow=always", "submodule", "add", source.working_dir, "module"])
    submodule = git.Repo(Path(local.working_dir) / "module")
    submodule.git.switch("--detach")
    manifest = write_manifest(tmp_path / "snapshot", {
        "path": "module", "type": "submodule", "parent": ".", "commit": first,
        "remote": {"origin": fetch_url(submodule)},
    })

    assert gdeploy.diff_manifest(local.working_dir, manifest) == 1
    assert capsys.readouterr().out == "module: Local ahead (2 commits): unpushed status unknown (detached HEAD)\n"


def test_diff_does_not_claim_exact_counts_for_shallow_history(workspace, tmp_path, capsys):
    source, _, _, tip = workspace
    directory = tmp_path / "shallow"
    repo = git.Repo.clone_from(Path(source.working_dir).as_uri(), directory, depth=2)
    assert repo.git.rev_parse("--is-shallow-repository") == "true"
    manifest = write_manifest(tmp_path / "snapshot", {
        "path": ".", "commit": tip, "remote": {"origin": fetch_url(repo)},
    })
    assert gdeploy.diff_manifest(directory, manifest) == 0
    assert capsys.readouterr().out == ".: Match\n"

    write_manifest(manifest, {"path": ".", "commit": repo.git.rev_parse("HEAD^"),
                              "remote": {"origin": fetch_url(repo)}})
    assert gdeploy.diff_manifest(directory, manifest) == 2
    assert capsys.readouterr().out == ".: Cannot compare (shallow history cannot reliably compare different commits)\n"


@pytest.mark.parametrize("contents,reason", [
    (None, "Manifest file not found"),
    ("{", "Cannot read manifest"),
    ("{'schema_version': 99}", "Unsupported manifest schema version"),
    ("{'schema_version': 1, 'name': 'Test'}", "No repositories listed in manifest"),
])
def test_diff_rejects_missing_or_invalid_manifest(tmp_path, capsys, contents, reason):
    manifest = tmp_path / "snapshot"
    if contents is not None:
        manifest.write_text(contents, encoding="utf-8")

    assert gdeploy.diff_manifest(tmp_path, manifest) == 2
    assert reason in capsys.readouterr().err


@pytest.mark.parametrize("option", ["--scan", "--upgrade", "--listed", "--commit", "--sync-remotes", "--checkout"])
def test_diff_rejects_other_mode_options(monkeypatch, option):
    monkeypatch.setattr(sys, "argv", ["gdeploy", "--diff", option])
    with pytest.raises(SystemExit) as error:
        gdeploy.main()
    assert error.value.code == 2
