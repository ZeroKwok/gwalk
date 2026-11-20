import os
from pathlib import Path
import sys

import git
import pytest

from gwalk import garchive, gdeploy


@pytest.fixture
def snapshot(tmp_path):
    source = git.Repo.init(tmp_path / "source")
    with source.config_writer() as config:
        config.set_value("user", "name", "test")
        config.set_value("user", "email", "test@example.com")
    readme = tmp_path / "source" / "README.md"
    readme.write_text("first\n", encoding="utf-8")
    source.index.add(["README.md"])
    first = source.index.commit("first").hexsha
    source.git.branch("-M", "main")
    readme.write_text("second\n", encoding="utf-8")
    source.index.add(["README.md"])
    source.index.commit("second")
    repo = git.Repo.clone_from(source.working_dir, tmp_path / "target")
    with repo.config_writer() as config:
        config.set_value("user", "name", "test")
        config.set_value("user", "email", "test@example.com")
    return source, repo, first


def test_snapshot_creates_branch_and_uses_selected_remote(snapshot):
    source, repo, first = snapshot
    repo.create_remote("github", source.working_dir)
    repo.git.fetch("github")
    repo.git.switch("--detach")
    repo.delete_head("main")

    gdeploy.checkout_commit(repo, first, "main", "github")

    assert repo.active_branch.name == "main"
    assert repo.head.commit.hexsha == first
    assert repo.active_branch.tracking_branch().name == "github/main"


def test_snapshot_already_at_commit_does_not_reset_branch(snapshot, monkeypatch):
    _, repo, first = snapshot
    repo.git.reset("--hard", first)
    original = repo.git.switch
    calls = []

    def switch(self, *args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(git.Git, "switch", switch, raising=False)
    gdeploy.checkout_commit(repo, first, "main", "origin")
    assert calls == [("main",)]


@pytest.mark.parametrize("branch,remote,reason", [
    (None, "origin", "not specified"),
    ("missing", "origin", "unavailable"),
    ("main", None, "unavailable"),
])
def test_snapshot_detaches_with_explicit_reason(snapshot, branch, remote, reason, capsys):
    _, repo, first = snapshot
    previous = repo.heads.main.commit.hexsha
    gdeploy.checkout_commit(repo, first, branch, remote)
    assert repo.head.is_detached
    assert repo.head.commit.hexsha == first
    assert repo.heads.main.commit.hexsha == previous
    assert reason in capsys.readouterr().err


@pytest.mark.parametrize("different_remote", [False, True])
def test_snapshot_attaches_and_warns_for_different_upstream(snapshot, capsys, different_remote):
    source, repo, first = snapshot
    if different_remote:
        repo.create_remote("github", source.working_dir)
        repo.git.fetch("github")
        remote, upstream = "github", "origin/main"
    else:
        source.create_head("fix4.2")
        repo.git.fetch("origin")
        repo.git.branch("--set-upstream-to=origin/fix4.2", "main")
        remote, upstream = "origin", "origin/fix4.2"

    gdeploy.checkout_commit(repo, first, "main", remote)

    assert repo.active_branch.name == "main"
    assert repo.heads.main.commit.hexsha == first
    assert repo.heads.main.tracking_branch().name == upstream
    warning = capsys.readouterr().err
    assert f"still tracks {upstream}, not {remote}/main" in warning
    assert "upstream preserved" in warning
    assert "Plain git pull/push" in warning
    assert "detached checkout" not in warning


def test_snapshot_sets_missing_upstream_without_warning(snapshot, capsys):
    _, repo, first = snapshot
    repo.git.branch("--unset-upstream", "main")

    gdeploy.checkout_commit(repo, first, "main", "origin")

    assert repo.active_branch.name == "main"
    assert repo.head.commit.hexsha == first
    assert repo.heads.main.tracking_branch().name == "origin/main"
    assert "Warning:" not in capsys.readouterr().err


@pytest.mark.parametrize("divergent", [False, True])
def test_snapshot_preserves_unpushed_target_branch(snapshot, divergent, capsys):
    source, repo, first = snapshot
    readme = os.path.join(repo.working_dir, "README.md")
    with open(readme, "w", encoding="utf-8") as stream:
        stream.write("local\n")
    repo.index.add(["README.md"])
    local = repo.index.commit("unpushed").hexsha
    if divergent:
        source.index.commit("remote", parent_commits=[source.head.commit])
        repo.git.fetch("origin")

    gdeploy.checkout_commit(repo, first, "main", "origin")

    assert repo.head.is_detached
    assert repo.head.commit.hexsha == first
    assert repo.heads.main.commit.hexsha == local
    assert "preserving its tip" in capsys.readouterr().err


@pytest.mark.parametrize("state", ["modified", "staged", "untracked"])
def test_snapshot_rejects_dirty_tree_even_without_checkout_conflicts(snapshot, state):
    _, repo, _ = snapshot
    previous = repo.head.commit.hexsha
    filename = "extra.txt" if state == "untracked" else "README.md"
    with open(os.path.join(repo.working_dir, filename), "w", encoding="utf-8") as stream:
        stream.write("local changes\n")
    if state == "staged":
        repo.index.add([filename])
    with pytest.raises(RuntimeError, match="Working tree is dirty"):
        gdeploy.checkout_commit(repo, previous, "main", "origin")
    assert repo.active_branch.name == "main"
    assert repo.head.commit.hexsha == previous


def test_snapshot_rejects_dirty_submodule(snapshot):
    source, repo, first = snapshot
    repo.git.execute([
        "git", "-c", "protocol.file.allow=always", "submodule", "add",
        source.working_dir, "module",
    ])
    repo.index.commit("add module")
    with open(os.path.join(repo.working_dir, "module", "README.md"), "w", encoding="utf-8") as stream:
        stream.write("dirty module\n")
    previous = repo.head.commit.hexsha
    with pytest.raises(RuntimeError, match="Working tree is dirty"):
        gdeploy.checkout_commit(repo, first, "main", "origin")
    assert repo.head.commit.hexsha == previous


@pytest.mark.parametrize("marker", ["MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer"])
def test_snapshot_rejects_git_operation(snapshot, marker):
    _, repo, first = snapshot
    path = os.path.join(repo.git_dir, marker)
    if marker.endswith("HEAD"):
        with open(path, "w", encoding="ascii") as stream:
            stream.write(repo.head.commit.hexsha + "\n")
    else:
        os.mkdir(path)
    previous = repo.head.commit.hexsha
    with pytest.raises(RuntimeError, match="Git operation in progress"):
        gdeploy.checkout_commit(repo, first, "main", "origin")
    assert repo.head.commit.hexsha == previous


def test_snapshot_rejects_unreferenced_detached_commit(snapshot):
    _, repo, first = snapshot
    repo.git.switch("--detach")
    detached = repo.index.commit("detached work").hexsha
    with pytest.raises(RuntimeError, match="unreferenced commits"):
        gdeploy.checkout_commit(repo, first, "main", "origin")
    assert repo.head.is_detached
    assert repo.head.commit.hexsha == detached


@pytest.mark.parametrize("reference", ["branch", "tag"])
def test_snapshot_can_leave_referenced_detached_commit(snapshot, reference):
    _, repo, first = snapshot
    repo.git.switch("--detach")
    detached = repo.index.commit("saved detached work").hexsha
    if reference == "branch":
        repo.create_head("saved", detached)
    else:
        repo.create_tag("saved", detached)
    gdeploy.checkout_commit(repo, first, "main", "origin")
    assert repo.active_branch.name == "main"
    assert repo.commit("saved").hexsha == detached


def test_snapshot_same_unreferenced_detached_commit_is_not_lost(snapshot):
    _, repo, _ = snapshot
    repo.git.switch("--detach")
    detached = repo.index.commit("detached snapshot").hexsha
    gdeploy.checkout_commit(repo, detached, "main", "origin")
    assert repo.head.is_detached
    assert repo.head.commit.hexsha == detached


def test_snapshot_worktree_conflict_does_not_fall_back_to_detached(snapshot, tmp_path):
    _, repo, first = snapshot
    previous = repo.heads.main.commit.hexsha
    repo.git.switch("--detach")
    repo.git.worktree("add", str(tmp_path / "other"), "main")
    with pytest.raises(git.exc.GitCommandError):
        gdeploy.checkout_commit(repo, first, "main", "origin")
    assert repo.heads.main.commit.hexsha == previous
    assert repo.head.commit.hexsha == previous


@pytest.mark.parametrize("branch", ["-bad", "bad..name", "@{-1}"])
def test_snapshot_invalid_branch_does_not_change_head(snapshot, branch):
    _, repo, first = snapshot
    previous = repo.head.commit.hexsha
    with pytest.raises((git.exc.GitCommandError, RuntimeError)):
        gdeploy.checkout_commit(repo, first, branch, "origin")
    assert repo.heads.main.commit.hexsha == previous
    assert not repo.head.is_detached


def test_attached_snapshot_finishes_before_submodules_and_post(snapshot, tmp_path, monkeypatch):
    source, repo, first = snapshot
    manifest = tmp_path / "gdeploy.manifest"
    manifest.write_text(gdeploy.render_manifest({
        "schema_version": 1, "name": "demo", "variables": [],
        "repositories": [{"path": ".", "remote": {"origin": source.working_dir},
                          "branch": "main", "commit": first, "post": "post"}],
    }), encoding="utf-8")
    events = []

    def submodules(current):
        events.append(("submodules", current.active_branch.name, current.head.commit.hexsha))

    def post(commands, directory):
        current = git.Repo(directory)
        events.append(("post", current.active_branch.name, current.head.commit.hexsha))
        return True

    monkeypatch.setattr(gdeploy, "update_submodules", submodules)
    monkeypatch.setattr(gdeploy, "run_post_commands", post)
    for _ in range(2):
        assert gdeploy.deploy_manifest(repo.working_dir, str(manifest), here=True, checkout_to_commit=True) == 0
    assert events == [("submodules", "main", first), ("post", "main", first)] * 2


def test_archive_snapshot_attaches_after_restore(tmp_path):
    source = git.Repo.init(tmp_path / "source")
    with source.config_writer() as config:
        config.set_value("user", "name", "test")
        config.set_value("user", "email", "test@example.com")
    (tmp_path / "source" / "file").write_text("first", encoding="utf-8")
    source.index.add(["file"])
    first = source.index.commit("first").hexsha
    source.git.branch("-M", "main")
    source.index.commit("second")
    manifest = tmp_path / "gdeploy.manifest"
    manifest.write_text(gdeploy.render_manifest({
        "schema_version": 1, "name": "backup", "variables": [],
        "repositories": [{"path": ".", "mode": "archive", "branch": "main",
                          "commit": first, "remote": {"origin": source.working_dir}}],
    }), encoding="utf-8")
    assert gdeploy.deploy_manifest(str(tmp_path), str(manifest), checkout_to_commit=True, checkout_archive=True) == 0
    restored = git.Repo(tmp_path / "backup")
    assert restored.active_branch.name == "main"
    assert restored.head.commit.hexsha == first
    assert not restored.is_dirty(untracked_files=True)
    assert gdeploy.deploy_manifest(str(tmp_path), str(manifest), checkout_to_commit=True, checkout_archive=True) == 0
    assert git.Repo(tmp_path / "backup").active_branch.name == "main"
    assert gdeploy.load_manifest(str(manifest))["repositories"][0]["mode"] == "archive"


def write_snapshot_manifest(tmp_path, source, commit, **entry):
    manifest = tmp_path / "gdeploy.manifest"
    manifest.write_text(gdeploy.render_manifest({
        "schema_version": 1, "name": "demo",
        "repositories": [{"path": ".", "remote": {"origin": source.working_dir},
                          "branch": "main", "commit": commit, "post": "post", **entry}],
    }), encoding="utf-8")
    return manifest


@pytest.mark.parametrize("state,count", [("published", 1), ("unpushed", 2), ("detached", 2)])
def test_skip_local_ahead_is_read_only_even_with_dirty_tree(snapshot, tmp_path, monkeypatch, capsys, state, count):
    source, repo, first = snapshot
    if state == "detached":
        repo.git.switch("--detach")
    if state != "published":
        repo.index.commit("additional local commit")
    previous = repo.head.commit.hexsha
    original_remote = repo.git.config("--get", "remote.origin.url")
    dirty = Path(repo.working_dir) / "README.md"
    dirty.write_text("keep my edits", encoding="utf-8")
    manifest = write_snapshot_manifest(
        tmp_path, source, first, remote={"origin": "https://example.invalid/replacement.git"},
    )
    for name in ("ensure_manifest_remote", "fetch_repository", "checkout_commit", "update_submodules", "run_post_commands"):
        monkeypatch.setattr(gdeploy, name, lambda *args: pytest.fail("skipped repository was processed"))
    monkeypatch.setattr(sys, "argv", [
        "gdeploy", "--commit", "--skip-local-ahead", "--sync-remotes", "-H", "-d", repo.working_dir, str(manifest),
    ])

    assert gdeploy.main() == 0
    assert repo.head.commit.hexsha == previous
    assert repo.head.is_detached == (state == "detached")
    assert repo.git.config("--get", "remote.origin.url") == original_remote
    assert dirty.read_text(encoding="utf-8") == "keep my edits"
    output = capsys.readouterr().out
    assert f"Skip .: local HEAD is ahead of the manifest by {count} commit" in output
    assert "0 updated, 0 post failed, 1 skipped, 0 failed" in output


@pytest.mark.parametrize("state", ["behind", "diverged", "different branch", "needs fetch"])
def test_skip_local_ahead_keeps_normal_checkout_for_other_relationships(snapshot, tmp_path, monkeypatch, capsys, state):
    source, repo, first = snapshot
    target = source.head.commit.hexsha
    if state == "behind":
        repo.git.switch("--detach", first)
    elif state == "diverged":
        repo.git.switch("-c", "feature", first)
        repo.index.commit("different history")
    elif state == "different branch":
        target = first
        repo.git.switch("-c", "feature", first)
        assert repo.heads.main.commit.hexsha != first
    elif state == "needs fetch":
        target = source.index.commit("only on the remote").hexsha
        assert not gdeploy.commit_available(repo, target)
    manifest = write_snapshot_manifest(tmp_path, source, target)
    events = []
    monkeypatch.setattr(gdeploy, "update_submodules", lambda current: events.append(current.head.commit.hexsha))
    monkeypatch.setattr(gdeploy, "run_post_commands", lambda commands, directory: commands == "post")

    assert gdeploy.deploy_manifest(repo.working_dir, manifest, here=True,
                                   checkout_to_commit=True, skip_local_ahead=True) == 0
    assert repo.active_branch.name == "main"
    assert repo.head.commit.hexsha == target
    assert events == [target]
    assert "1 updated, 0 post failed, 0 skipped, 0 failed" in capsys.readouterr().out


@pytest.mark.parametrize("branch,unpushed", [("main", False), (None, False), ("main", True)])
def test_skip_local_ahead_skips_matching_worktree(snapshot, tmp_path, monkeypatch, capsys, branch, unpushed):
    source, repo, first = snapshot
    # Neither being behind the remote tip nor having an unpublished snapshot is a mismatch.
    if unpushed:
        first = repo.index.commit("unpublished snapshot").hexsha
    elif branch:
        repo.git.switch("-C", branch, first)
    else:
        repo.git.switch("--detach", first)
    manifest = write_snapshot_manifest(tmp_path, source, first, branch=branch)
    for name in ("ensure_manifest_remote", "fetch_repository", "checkout_commit", "update_submodules", "run_post_commands"):
        monkeypatch.setattr(gdeploy, name, lambda *args: pytest.fail("matching repository was processed"))
    monkeypatch.chdir(repo.working_dir)
    monkeypatch.setattr(sys, "argv", ["gdeploy", "--commit", "--skip-local-ahead", "-H", str(manifest)])

    assert gdeploy.main() == 0
    assert repo.head.commit.hexsha == first
    assert repo.head.is_detached == (branch is None)
    output = capsys.readouterr().out
    assert "Skip .: already matches manifest" in output
    assert "0 updated, 0 post failed, 1 skipped, 0 failed" in output


@pytest.mark.parametrize("state", ["strict", "wrong branch", "remote URL", "missing remote", "dirty", "operation"])
def test_matching_head_does_not_skip_if_deployment_is_needed(snapshot, tmp_path, monkeypatch, capsys, state):
    source, repo, _ = snapshot
    tip = repo.head.commit.hexsha
    if state == "wrong branch":
        repo.git.switch("-c", "feature")
    elif state == "remote URL":
        repo.git.remote("set-url", "origin", "https://example.invalid/other.git")
    elif state == "missing remote":
        repo.delete_remote("origin")
    elif state == "dirty":
        (Path(repo.working_dir) / "file.txt").write_text("untracked", encoding="utf-8")
    elif state == "operation":
        (Path(repo.git_dir) / "MERGE_HEAD").write_text(tip + "\n", encoding="utf-8")
    manifest = write_snapshot_manifest(tmp_path, source, tip)
    events = []
    monkeypatch.setattr(gdeploy, "update_submodules", lambda *args: events.append("submodules"))
    monkeypatch.setattr(gdeploy, "run_post_commands", lambda *args: events.append("post") or True)

    result = gdeploy.deploy_manifest(repo.working_dir, manifest, here=True, checkout_to_commit=True,
                                     skip_local_ahead=state != "strict", sync_remotes=True)
    output = capsys.readouterr()
    assert "already matches manifest" not in output.out
    assert repo.active_branch.name == "main"
    assert repo.head.commit.hexsha == tip
    if state in ("remote URL", "missing remote"):
        assert repo.git.config("--get", "remote.origin.url").replace("\\", "/") == source.working_dir.replace("\\", "/")
    if state in ("dirty", "operation"):
        assert result == 1
        assert not events
        assert ("Working tree is dirty" if state == "dirty" else "Git operation in progress") in output.err
    else:
        assert result == 0
        assert events == ["submodules", "post"]
        assert "1 updated, 0 post failed, 0 skipped, 0 failed" in output.out


def test_matching_head_initializes_submodule_before_it_can_skip(snapshot, tmp_path, monkeypatch, capsys):
    source, _, _ = snapshot
    module = git.Repo.clone_from(source.working_dir, tmp_path / "module")
    source.git.execute(["git", "-c", "protocol.file.allow=always", "submodule", "add", module.working_dir, "module"])
    tip = source.index.commit("add module").hexsha
    repo = git.Repo.clone_from(source.working_dir, tmp_path / "with-submodule")
    manifest = write_snapshot_manifest(tmp_path, source, tip)
    monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "file")
    monkeypatch.setattr(gdeploy, "run_post_commands", lambda *args: True)
    assert repo.git.submodule("status", "--recursive").startswith("-")

    for expected in ("1 updated, 0 post failed, 0 skipped, 0 failed", "Skip .: already matches manifest"):
        assert gdeploy.deploy_manifest(repo.working_dir, manifest, here=True, checkout_to_commit=True,
                                       skip_local_ahead=True) == 0
        assert expected in capsys.readouterr().out
        assert git.Repo(Path(repo.working_dir) / "module").head.commit.hexsha == module.head.commit.hexsha


def test_matching_bare_archive_is_restored_when_requested(snapshot, tmp_path, monkeypatch, capsys):
    source, _, _ = snapshot
    directory = tmp_path / "archive"
    garchive.clone(source.working_dir, directory)
    manifest = write_snapshot_manifest(tmp_path, source, source.head.commit.hexsha, mode="archive")
    monkeypatch.setattr(gdeploy, "run_post_commands", lambda *args: True)

    assert gdeploy.deploy_manifest(directory, manifest, here=True, checkout_to_commit=True, checkout_archive=True,
                                   skip_local_ahead=True) == 0
    assert not git.Repo(directory).bare
    assert "1 updated, 0 post failed, 0 skipped, 0 failed" in capsys.readouterr().out


def test_skip_local_ahead_continues_and_pins_fresh_clones(snapshot, tmp_path, monkeypatch, capsys):
    source, repo, first = snapshot
    previous = repo.head.commit.hexsha
    entries = [{"path": path, "remote": {"origin": source.working_dir}, "branch": "main", "commit": first}
               for path in ("target", "fresh")]
    manifest = tmp_path / "gdeploy.manifest"
    manifest.write_text(gdeploy.render_manifest({
        "schema_version": 1, "name": "demo", "repositories": entries,
    }), encoding="utf-8")
    events = []
    monkeypatch.setattr(gdeploy, "update_submodules", lambda current: events.append(current.head.commit.hexsha))

    assert gdeploy.deploy_manifest(tmp_path, manifest, here=True, checkout_to_commit=True, skip_local_ahead=True) == 0
    assert repo.head.commit.hexsha == previous
    assert git.Repo(tmp_path / "fresh").head.commit.hexsha == first
    assert events == [first]
    assert "1 cloned, 0 updated, 0 post failed, 1 skipped, 0 failed" in capsys.readouterr().out


def test_skip_local_ahead_fails_closed_in_shallow_repository(snapshot, tmp_path, monkeypatch, capsys):
    source, _, first = snapshot
    repo = git.Repo.clone_from(Path(source.working_dir).as_uri(), tmp_path / "shallow", depth=2)
    previous = repo.head.commit.hexsha
    assert gdeploy.commit_available(repo, first)
    manifest = write_snapshot_manifest(tmp_path, source, first)
    monkeypatch.setattr(gdeploy, "fetch_repository", lambda *args: pytest.fail("unexpected fetch"))

    assert gdeploy.deploy_manifest(repo.working_dir, manifest, here=True,
                                   checkout_to_commit=True, skip_local_ahead=True) == 1
    assert repo.head.commit.hexsha == previous
    assert "shallow history cannot reliably compare different commits" in capsys.readouterr().err


def test_skip_local_ahead_fails_if_snapshot_is_unavailable_after_fetch(snapshot, tmp_path, capsys):
    source, repo, _ = snapshot
    previous = repo.head.commit.hexsha
    new_remote_tip = source.index.commit("new remote commit").hexsha
    manifest = write_snapshot_manifest(tmp_path, source, "0" * 40)

    assert gdeploy.deploy_manifest(repo.working_dir, manifest, here=True,
                                   checkout_to_commit=True, skip_local_ahead=True) == 1
    assert repo.git.rev_parse("refs/remotes/origin/main") == new_remote_tip
    assert repo.head.commit.hexsha == previous
    assert "Manifest commit not found" in capsys.readouterr().err


@pytest.mark.parametrize("restored", [False, True])
def test_skip_local_ahead_protects_archive_snapshots(snapshot, tmp_path, monkeypatch, capsys, restored):
    source, repo, first = snapshot
    directory = Path(repo.working_dir)
    if not restored:
        directory = tmp_path / "archive"
        garchive.clone(source.working_dir, directory)
    manifest = write_snapshot_manifest(tmp_path, source, first, mode="archive")
    for module, name in ((gdeploy, "fetch_repository"), (garchive, "restore")):
        monkeypatch.setattr(module, name, lambda *args: pytest.fail("skipped archive was processed"))

    assert gdeploy.deploy_manifest(directory, manifest, here=True, checkout_to_commit=True,
                                   checkout_archive=not restored, skip_local_ahead=True) == 0
    current = git.Repo(directory)
    assert current.bare == (not restored)
    assert current.head.commit.hexsha == source.head.commit.hexsha
    assert "Skip .: local HEAD is ahead" in capsys.readouterr().out


@pytest.mark.parametrize("layout", ["bare", "mirror", "archive"])
def test_skip_local_ahead_does_not_skip_fetch_only_repositories(snapshot, tmp_path, monkeypatch, capsys, layout):
    source, _, first = snapshot
    directory = tmp_path / layout
    if layout == "archive":
        garchive.clone(source.working_dir, directory)
    else:
        git.Repo.clone_from(source.working_dir, directory, **{layout: True})
    manifest = write_snapshot_manifest(tmp_path, source, first, mode=layout)
    fetched = []
    monkeypatch.setattr(gdeploy, "fetch_repository", lambda current, remote: fetched.append(remote))

    assert gdeploy.deploy_manifest(directory, manifest, here=True, checkout_to_commit=True, skip_local_ahead=True) == 0
    assert fetched == ["origin"]
    assert git.Repo(directory).bare
    assert "1 updated, 0 post failed, 0 skipped, 0 failed" in capsys.readouterr().out


@pytest.mark.parametrize("other_options", [[], ["--scan", "--commit"], ["--upgrade"], ["--diff"]])
def test_skip_local_ahead_requires_commit_in_deploy_mode(monkeypatch, capsys, other_options):
    monkeypatch.setattr(sys, "argv", ["gdeploy", "--skip-local-ahead", *other_options])
    with pytest.raises(SystemExit) as error:
        gdeploy.main()
    assert error.value.code == 2
    assert "--skip-local-ahead requires --commit in deploy mode" in capsys.readouterr().err
