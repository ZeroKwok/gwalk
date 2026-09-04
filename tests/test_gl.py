import os
import sys

import git
import pytest

from gwalk import gl


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
        gl.main()
    return exc.value.code


def test_gl_rejects_non_repository(tmp_path, monkeypatch):
    assert run_main(monkeypatch, ["gl"], tmp_path) == 1


def test_gl_fetches_all_then_pulls_origin(tmp_path, monkeypatch):
    repo = make_repo(tmp_path, "dev")
    repo.create_remote("origin", str(tmp_path / "origin.git"))
    repo.create_remote("backup", str(tmp_path / "backup.git"))
    commands = []

    monkeypatch.setattr(gl.gwalk.RepoHandler, "execute", lambda cmd: commands.append(cmd) or 0)

    assert run_main(monkeypatch, ["gl"], tmp_path) == 0
    assert commands == [
        "git fetch --all --no-auto-maintenance",
        "git maintenance run --auto --no-quiet",
        "git pull origin dev ",
    ]


def test_gl_quick_skips_fetch(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    repo.create_remote("origin", str(tmp_path / "origin.git"))
    commands = []

    monkeypatch.setattr(gl.gwalk.RepoHandler, "execute", lambda cmd: commands.append(cmd) or 0)

    assert run_main(monkeypatch, ["gl", "-q"], tmp_path) == 0
    assert commands == ["git pull origin main "]


def test_gl_fetch_option_fetches_all_without_detached_maintenance(tmp_path, monkeypatch):
    repo = make_repo(tmp_path, "dev")
    repo.create_remote("origin", str(tmp_path / "origin.git"))
    repo.create_remote("backup", str(tmp_path / "backup.git"))
    commands = []

    monkeypatch.setattr(gl.gwalk.RepoHandler, "execute", lambda cmd: commands.append(cmd) or 0)

    assert run_main(monkeypatch, ["gl", "--fetch"], tmp_path) == 0
    assert commands == [
        "git fetch --all --no-auto-maintenance",
        "git maintenance run --auto --no-quiet",
    ]


def test_gl_rebase_adds_rebase_flag(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    repo.create_remote("origin", str(tmp_path / "origin.git"))
    commands = []

    monkeypatch.setattr(gl.gwalk.RepoHandler, "execute", lambda cmd: commands.append(cmd) or 0)

    assert run_main(monkeypatch, ["gl", "--rebase"], tmp_path) == 0
    assert commands[-1] == "git pull origin main --rebase"


def test_gl_uses_first_remote_when_origin_missing(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    repo.create_remote("backup", str(tmp_path / "backup.git"))
    commands = []

    monkeypatch.setattr(gl.gwalk.RepoHandler, "execute", lambda cmd: commands.append(cmd) or 0)

    assert run_main(monkeypatch, ["gl"], tmp_path) == 0
    assert commands == [
        "git fetch --all --no-auto-maintenance",
        "git maintenance run --auto --no-quiet",
        "git pull backup main ",
    ]


def test_gl_fetch_failure_warns_but_pull_exit_code_wins(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    repo.create_remote("origin", str(tmp_path / "origin.git"))
    commands = []

    def execute(cmd):
        commands.append(cmd)
        return 1 if cmd.startswith("git fetch") else 3

    monkeypatch.setattr(gl.gwalk.RepoHandler, "execute", execute)

    assert run_main(monkeypatch, ["gl"], tmp_path) == 3
    assert commands == [
        "git fetch --all --no-auto-maintenance",
        "git maintenance run --auto --no-quiet",
        "git pull origin main ",
    ]


def test_gl_updates_bare_repository_without_pull(tmp_path, monkeypatch):
    repo = git.Repo.init(tmp_path, bare=True)
    commands = []

    monkeypatch.setattr(gl.gwalk.RepoHandler, "execute", lambda cmd: commands.append(cmd) or 0)

    assert run_main(monkeypatch, ["gl"], tmp_path) == 0
    assert commands == [
        "git fetch --all --no-auto-maintenance",
        "git maintenance run --auto --no-quiet",
    ]


def test_gl_quick_bare_repository_skips_fetch_and_maintenance(tmp_path, monkeypatch):
    git.Repo.init(tmp_path, bare=True)
    commands = []

    monkeypatch.setattr(gl.gwalk.RepoHandler, "execute", lambda cmd: commands.append(cmd) or 0)

    assert run_main(monkeypatch, ["gl", "--quick"], tmp_path) == 0
    assert commands == []
