import os

import git
import pytest

from gwalk import gdeploy


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


def test_snapshot_preserves_different_upstream(snapshot, capsys):
    source, repo, first = snapshot
    repo.create_remote("github", source.working_dir)
    repo.git.fetch("github")
    previous = repo.heads.main.commit.hexsha
    gdeploy.checkout_commit(repo, first, "main", "github")
    assert repo.head.is_detached
    assert repo.heads.main.commit.hexsha == previous
    assert repo.heads.main.tracking_branch().name == "origin/main"
    assert "tracks origin/main, not github/main" in capsys.readouterr().err


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
