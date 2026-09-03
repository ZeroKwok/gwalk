import os
import re
import shutil
import sys

import git
import pytest

from gwalk import garchive


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


def make_archive_git_dir(path):
    repo = make_repo(path)
    repo.create_remote("origin", "https://example.com/source.git")
    garchive.archive(str(path))
    return git.Repo(path / ".git")


def test_to_archive_sets_all_remotes_as_mirror_and_writes_metadata(tmp_path, capsys):
    repo = make_repo(tmp_path)
    repo.create_remote("origin", "https://example.com/source.git")

    assert garchive.archive(str(tmp_path)) == 0
    archived = git.Repo(tmp_path / ".git")

    assert archived.bare == True
    assert archived.config_reader().get_value('remote "origin"', "mirror") is True
    assert archived.config_reader().get_value('remote "origin"', "fetch") == "+refs/*:refs/*"
    assert (tmp_path / ".git" / "config.archive").is_file()
    assert (tmp_path / ".git" / "mate.archive").is_file()
    output = capsys.readouterr().out
    assert "Archive conversion done:" in output
    assert "Config archive:" in output


def test_to_archive_rejects_dirty_repository(tmp_path):
    make_repo(tmp_path)
    (tmp_path / "README.md").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="uncommitted or untracked"):
        garchive.archive(str(tmp_path))


def test_to_archive_continues_when_worktree_already_removed(tmp_path):
    repo = make_repo(tmp_path)
    repo.create_remote("origin", "https://example.com/source.git")

    for entry in os.listdir(tmp_path):
        path = tmp_path / entry
        if entry == ".git":
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()

    assert garchive.archive(str(tmp_path)) == 0
    archived = git.Repo(tmp_path / ".git")
    assert archived.bare == True
    assert archived.config_reader().get_value('remote "origin"', "mirror") is True


def test_archive_from_git_directory_leaves_worktree_metadata_empty(tmp_path):
    repo = make_repo(tmp_path)

    assert garchive.archive(str(tmp_path / ".git")) == 0

    metadata = (tmp_path / ".git" / "mate.archive").read_text(encoding="utf-8")
    assert "worktree = \n" in metadata
    assert re.search(r"^time = \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [+-]\d{4}$", metadata, re.MULTILINE)


def test_restore_moves_git_dir_to_target_and_updates_config(tmp_path):
    source = tmp_path / "SomeDir"
    target = tmp_path / "Restored"
    make_archive_git_dir(source)

    assert garchive.restore(str(source / ".git"), str(target), None) == 0
    restored = git.Repo(target / ".git")

    assert (target / ".git").is_dir()
    assert not (source / ".git").exists()
    assert restored.bare == False
    assert restored.config_reader().get_value('remote "origin"', "mirror", False) in (False, "false")
    assert restored.config_reader().get_value('remote "origin"', "fetch") == (
        "+refs/heads/*:refs/remotes/origin/*"
    )
    assert not (target / ".git" / "mate.archive").exists()


def test_restore_uses_archive_config_and_preserves_original_values(tmp_path):
    source = tmp_path / "SomeDir"
    repo = make_repo(source)
    repo.create_remote("origin", "https://example.com/source.git")
    with repo.config_writer() as config:
        config.set_value("user", "custom", "preserved-value")
    garchive.archive(str(source))

    assert garchive.restore(str(source / ".git"), str(tmp_path / "Restored"), None) == 0
    restored = git.Repo(tmp_path / "Restored" / ".git")

    assert restored.config_reader().get_value("user", "custom") == "preserved-value"
    assert restored.bare == False
    assert not (tmp_path / "Restored" / ".git" / "config.archive").exists()


def test_restore_uses_user_target_directory(tmp_path):
    source = tmp_path / "SomeDir"
    target = tmp_path / "CustomName"
    make_archive_git_dir(source)

    garchive.restore(str(source / ".git"), str(target), None)

    assert (target / ".git").exists()


def test_restore_without_branch_does_not_checkout_worktree(tmp_path):
    source = tmp_path / "SomeDir"
    target = tmp_path / "Restored"
    make_archive_git_dir(source)

    garchive.restore(str(source / ".git"), str(target), None)

    assert not (target / "README.md").exists()


def test_restore_with_branch_checks_out_worktree(tmp_path, capsys):
    source = tmp_path / "SomeDir"
    target = tmp_path / "Restored"
    make_archive_git_dir(source)

    garchive.restore(str(source / ".git"), str(target), "main")

    assert (target / "README.md").read_text(encoding="utf-8") == "test\n"
    output = capsys.readouterr().out
    assert "Checkout main" in output
    assert "Restore config.archive -> config" in output
    assert "Skip checkout because --checkout was not specified" not in output


def test_restore_checkout_without_branch_uses_head(tmp_path, capsys):
    source = tmp_path / "SomeDir"
    target = tmp_path / "Restored"
    make_archive_git_dir(source)

    garchive.restore(str(source / ".git"), str(target), "")

    assert (target / "README.md").read_text(encoding="utf-8") == "test\n"
    output = capsys.readouterr().out
    assert "Checkout main" in output


def test_restore_here_updates_config_without_checkout(tmp_path, capsys):
    source = tmp_path / "SomeDir"
    make_archive_git_dir(source)
    (source / "README.md").write_text("changed\n", encoding="utf-8")

    assert garchive.restore(str(source / ".git"), None, None, here=True) == 0
    restored = git.Repo(source)

    assert restored.bare == False
    assert (source / "README.md").read_text(encoding="utf-8") == "changed\n"
    assert not (source / ".git" / "mate.archive").exists()
    output = capsys.readouterr().out
    assert "Checkout" not in output


def test_restore_here_with_branch_checks_out_worktree(tmp_path):
    source = tmp_path / "SomeDir"
    make_archive_git_dir(source)
    (source / "README.md").write_text("changed\n", encoding="utf-8")

    garchive.restore(str(source / ".git"), None, "main", here=True)

    assert (source / "README.md").read_text(encoding="utf-8") == "test\n"


def test_restore_here_accepts_archive_parent_path(tmp_path):
    source = tmp_path / "SomeDir.git"
    make_archive_git_dir(source)

    assert garchive.restore(str(source), None, None, here=True) == 0
    assert git.Repo(source).bare == False


def test_restore_derives_target_from_dot_git_suffix(tmp_path):
    source = tmp_path / "Project.git"
    make_archive_git_dir(source)

    garchive.restore(str(source), None, None)

    assert git.Repo(source).bare == False


def test_restore_derives_target_from_remote_url_when_source_is_dot_git(tmp_path):
    source = tmp_path / "SomeDir"
    make_archive_git_dir(source)

    garchive.restore(str(source / ".git"), None, None)

    assert git.Repo(source).bare == False


def test_restore_from_git_directory_uses_parent_even_without_metadata(tmp_path):
    source = tmp_path / "SomeDir"
    make_archive_git_dir(source)
    (source / ".git" / "mate.archive").unlink()

    assert garchive.restore(str(source / ".git"), None, None) == 0
    assert git.Repo(source).bare == False


def test_restore_rejects_non_empty_target(tmp_path):
    source = tmp_path / "SomeDir"
    target = tmp_path / "Target"
    target.mkdir()
    (target / "file.txt").write_text("exists\n", encoding="utf-8")
    make_archive_git_dir(source)

    with pytest.raises(RuntimeError, match="not empty"):
        garchive.restore(str(source / ".git"), str(target), None)


def test_restore_rejects_non_archive_source(tmp_path):
    repo = make_repo(tmp_path)
    repo.create_remote("origin", "https://example.com/source.git")

    with pytest.raises(RuntimeError, match="config.archive"):
        garchive.restore(str(tmp_path / ".git"), str(tmp_path / "target"), None)


def test_main_returns_error_for_invalid_command_target(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["garchive", "archive", "--path", str(tmp_path)])

    assert garchive.main() == 1


def test_main_restore_uses_name_option(tmp_path, monkeypatch):
    source = tmp_path / "SomeDir"
    target = tmp_path / "TargetByName"
    make_archive_git_dir(source)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "garchive",
            "restore",
            "--path",
            str(source / ".git"),
            "--name",
            str(target),
        ],
    )

    assert garchive.main() == 0
    assert (target / ".git").exists()


def test_main_restore_here(tmp_path, monkeypatch):
    source = tmp_path / "SomeDir"
    make_archive_git_dir(source)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "garchive",
            "restore",
            "--path",
            str(source / ".git"),
            "--here",
        ],
    )

    assert garchive.main() == 0
    assert git.Repo(source).bare == False


def test_main_restore_checkout_without_branch(tmp_path, monkeypatch):
    source = tmp_path / "SomeDir"
    target = tmp_path / "Restored"
    make_archive_git_dir(source)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "garchive",
            "restore",
            "--path",
            str(source / ".git"),
            "--name",
            str(target),
            "--checkout",
        ],
    )

    assert garchive.main() == 0
    assert (target / "README.md").read_text(encoding="utf-8") == "test\n"


def test_main_rejects_old_flag(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["garchive", "--archive", "--path", str(tmp_path)])

    with pytest.raises(SystemExit):
        garchive.main()

    err = capsys.readouterr().err
    assert "unrecognized arguments: --archive" in err or "required: mode" in err


def test_main_restore_here_with_name_is_rejected(tmp_path, monkeypatch, capsys):
    source = tmp_path / "SomeDir"
    target = tmp_path / "Target"
    make_archive_git_dir(source)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "garchive",
            "restore",
            "--path",
            str(source / ".git"),
            "--here",
            "--name",
            str(target),
        ],
    )

    assert garchive.main() == 1
    err = capsys.readouterr().err
    assert "--name cannot be used with --here" in err


def test_main_archive_with_name_is_rejected(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path)
    repo.create_remote("origin", "https://example.com/source.git")
    monkeypatch.setattr(
        sys,
        "argv",
        ["garchive", "archive", "--path", str(tmp_path), "--name", str(tmp_path / "x")],
    )

    assert garchive.main() == 1
    err = capsys.readouterr().err
    assert "--name is only valid with restore mode" in err


def test_removed_remote_api():
    assert not hasattr(garchive, "resolve_remote")


def test_archive_auto_detects_single_remote(tmp_path):
    repo = make_repo(tmp_path)
    repo.create_remote("origin", "https://example.com/source.git")

    assert garchive.archive(str(tmp_path)) == 0
    archived = git.Repo(tmp_path / ".git")
    assert archived.config_reader().get_value('remote "origin"', "mirror") is True


def test_clone_creates_archive_markers_and_restores(tmp_path):
    source = tmp_path / "source"
    make_repo(source)
    target = tmp_path / "one"

    assert garchive.clone(str(source), str(target)) == 0
    archive_git = target / ".git"
    assert (archive_git / "config.archive").is_file()
    assert (archive_git / "mate.archive").is_file()
    assert git.Repo(archive_git).bare == True

    assert garchive.restore(str(archive_git), None, "main") == 0
    assert git.Repo(target).bare == False
    assert (target / "README.md").exists()
    assert not (target / ".git" / "mate.archive").exists()


def test_archive_clean_removes_working_directory(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    repo.create_remote("origin", "https://example.com/source.git")
    (tmp_path / "extra.txt").write_text("ignored\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("extra.txt\n", encoding="utf-8")
    repo.index.add([".gitignore"])
    repo.index.commit("ignore")

    monkeypatch.setattr("builtins.input", lambda prompt: "y")

    assert garchive.archive(str(tmp_path), clean=True) == 0

    assert (tmp_path / ".git").is_dir()
    assert not (tmp_path / "README.md").exists()
    assert not (tmp_path / ".gitignore").exists()
    assert not (tmp_path / "extra.txt").exists()


def test_archive_clean_prompts_when_ignored_files_exist(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path)
    repo.create_remote("origin", "https://example.com/source.git")
    (tmp_path / "extra.txt").write_text("ignored\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("extra.txt\n", encoding="utf-8")
    repo.index.add([".gitignore"])
    repo.index.commit("ignore")

    monkeypatch.setattr("builtins.input", lambda prompt: "y")

    assert garchive.archive(str(tmp_path), clean=True) == 0
    assert not (tmp_path / "README.md").exists()
    assert not (tmp_path / "extra.txt").exists()

    output = capsys.readouterr().out
    assert "Ignored files exist" in output


def test_archive_clean_cancels_when_user_declines(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    repo.create_remote("origin", "https://example.com/source.git")
    (tmp_path / "extra.txt").write_text("ignored\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("extra.txt\n", encoding="utf-8")
    repo.index.add([".gitignore"])
    repo.index.commit("ignore")

    monkeypatch.setattr("builtins.input", lambda prompt: "n")

    with pytest.raises(RuntimeError, match="cancelled"):
        garchive.archive(str(tmp_path), clean=True)

    assert (tmp_path / "README.md").exists()


def test_archive_clean_force_skips_prompt(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    repo.create_remote("origin", "https://example.com/source.git")
    (tmp_path / "extra.txt").write_text("ignored\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("extra.txt\n", encoding="utf-8")
    repo.index.add([".gitignore"])
    repo.index.commit("ignore")

    def fail(_):
        raise AssertionError("input should not be called")

    monkeypatch.setattr("builtins.input", fail)

    assert garchive.archive(str(tmp_path), clean=True, force=True) == 0
    assert not (tmp_path / "extra.txt").exists()


def test_restore_auto_detects_remote(tmp_path):
    source = tmp_path / "SomeDir"
    make_archive_git_dir(source)

    assert garchive.restore(str(source / ".git"), str(tmp_path / "Restored"), None) == 0
    assert (tmp_path / "Restored" / ".git").exists()


def test_restore_parent_dir_auto_here(tmp_path, capsys):
    source = tmp_path / "SomeDir"
    make_archive_git_dir(source)

    assert garchive.restore(str(source), None, None) == 0

    assert git.Repo(source).bare == False
    assert (source / ".git").exists()
    output = capsys.readouterr().out
    assert "Using --here" in output


def test_restore_parent_dir_with_name_moves_out(tmp_path):
    source = tmp_path / "SomeDir"
    target = tmp_path / "Restored"
    make_archive_git_dir(source)

    assert garchive.restore(str(source), str(target), None) == 0

    assert (target / ".git").exists()
    assert not (source / ".git").exists()


def test_restore_parent_dir_gitdir_file_rejected(tmp_path):
    source = tmp_path / "SomeDir"
    make_archive_git_dir(source)

    real_git = source / ".git"
    gitdir_file = source / ".git.dir"
    os.rename(real_git, gitdir_file)
    (source / ".git").write_text(f"gitdir: {gitdir_file}\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="worktree"):
        garchive.restore(str(source), None, None)
