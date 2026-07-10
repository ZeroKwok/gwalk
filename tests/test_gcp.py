import os
import sys

import git
import pytest

from gwalk import gcp


def make_repo(path, branch="main"):
    repo = git.Repo.init(path)
    with repo.config_writer() as config:
        config.set_value("user", "name", "test")
        config.set_value("user", "email", "test@example.com")
    (path / "README.md").write_text("test\n", encoding="utf-8")
    repo.index.add(["README.md"])
    repo.index.commit("init")
    repo.git.branch("-M", branch)
    return repo


def run_main(monkeypatch, argv, cwd):
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.chdir(cwd)
    with pytest.raises(SystemExit) as exc:
        gcp.main()
    return exc.value.code


def test_gcp_rejects_non_repository(tmp_path, monkeypatch):
    assert run_main(monkeypatch, ["gcp"], tmp_path) == 1


def test_gcp_requires_repo_root_by_default(tmp_path, monkeypatch):
    make_repo(tmp_path)
    child = tmp_path / "child"
    child.mkdir()

    assert run_main(monkeypatch, ["gcp"], child) == 1


def test_gcp_ignore_allows_subdirectory(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    repo.create_remote("origin", str(tmp_path / "remote.git"))
    child = tmp_path / "child"
    child.mkdir()
    (tmp_path / "README.md").write_text("changed\n", encoding="utf-8")
    commands = []

    monkeypatch.setattr(gcp, "execute", lambda cmd, dry_run=False: commands.append((cmd, dry_run)))

    assert run_main(monkeypatch, ["gcp", "-i", "msg"], child) == 0
    assert commands == [
        ("git status -s --untracked-files=normal", False),
        ("git add -u", False),
        ('git commit -m "msg"', False),
        ("git push origin main", False),
    ]


def test_gcp_all_stages_untracked_files(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    repo.create_remote("origin", str(tmp_path / "remote.git"))
    (tmp_path / "new.txt").write_text("new\n", encoding="utf-8")
    commands = []

    monkeypatch.setattr(gcp, "execute", lambda cmd, dry_run=False: commands.append((cmd, dry_run)))

    assert run_main(monkeypatch, ["gcp", "-a", "new file"], tmp_path) == 0
    assert ("git add -A", False) in commands
    assert ('git commit -m "new file"', False) in commands
    assert ("git push origin main", False) in commands


def test_gcp_without_all_ignores_untracked_only_repo(tmp_path, monkeypatch):
    make_repo(tmp_path)
    (tmp_path / "new.txt").write_text("new\n", encoding="utf-8")
    commands = []

    monkeypatch.setattr(gcp, "execute", lambda cmd, dry_run=False: commands.append((cmd, dry_run)))

    assert run_main(monkeypatch, ["gcp", "msg"], tmp_path) == 0
    assert commands == [("git status -s --untracked-files=normal", False)]


def test_gcp_push_only_pushes_src_to_all_remotes(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    repo.create_remote("origin", str(tmp_path / "origin.git"))
    repo.create_remote("backup", str(tmp_path / "backup.git"))
    commands = []

    monkeypatch.setattr(gcp, "execute", lambda cmd, dry_run=False: commands.append((cmd, dry_run)))

    assert run_main(monkeypatch, ["gcp", "-p", "-s", "v1.0.0"], tmp_path) == 0
    assert commands == [
        ("git push origin v1.0.0", False),
        ("git push backup v1.0.0", False),
    ]


def test_gcp_dry_run_passes_dry_run_to_mutating_commands(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    repo.create_remote("origin", str(tmp_path / "remote.git"))
    (tmp_path / "README.md").write_text("changed\n", encoding="utf-8")
    commands = []

    monkeypatch.setattr(gcp, "execute", lambda cmd, dry_run=False: commands.append((cmd, dry_run)))

    assert run_main(monkeypatch, ["gcp", "-n", "msg"], tmp_path) == 0
    assert commands == [
        ("git status -s --untracked-files=normal", False),
        ("git add -u", True),
        ('git commit -m "msg"', True),
        ("git push origin main", True),
    ]


def test_gcp_execute_raises_result_error_on_failure(monkeypatch):
    monkeypatch.setattr(gcp.gwalk.RepoHandler, "execute", lambda cmd: 7)

    with pytest.raises(gcp.ResultError) as exc:
        gcp.execute("git push origin main")

    assert exc.value.ecode == 7
