#! python
# -*- coding: utf-8 -*-
#
# This file is part of the gwalk project.
#

import argparse
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import git
from termcolor import cprint


def config_backup_name(config):
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{config}.backup.{timestamp}"


def backup_config(git_dir):
    config = os.path.join(git_dir, "config")
    if not os.path.isfile(config):
        raise RuntimeError(f"Git config not found: {config}")

    backup = config_backup_name(config)
    shutil.copy2(config, backup)
    return backup


def repo_from_worktree(path):
    repo = git.Repo(path, search_parent_directories=False)
    if repo.bare:
        raise RuntimeError(f"Expected a normal repository: {path}")
    return repo


def repo_from_git_dir(path):
    return git.Repo(path)


def resolve_source_git_dir(source):
    source = os.path.normpath(os.path.abspath(source))

    if source.endswith(".git"):
        return source, False

    candidate = os.path.join(source, ".git")

    if os.path.isdir(candidate):
        return candidate, True

    if os.path.isfile(candidate):
        raise RuntimeError(
            f"Git worktree is not supported, please point --path to the actual git directory: {candidate}"
        )

    return source, False


def remote_url(repo, remote):
    try:
        return next(iter(repo.remotes[remote].urls))
    except Exception:
        return ""


def resolve_remote(repo, remote):
    if remote:
        return remote

    names = [r.name for r in repo.remotes]
    if len(names) == 1:
        return names[0]
    if "origin" in names:
        return "origin"
    raise RuntimeError(
        f"Cannot infer remote, please provide --remote (available: {', '.join(names)})"
    )


def ignored_files(repo):
    try:
        return repo.git.ls_files("--others", "--ignored", "--exclude-standard").splitlines()
    except Exception:
        return []


def confirm_clean(ignored):
    if not ignored:
        return True

    cprint("Ignored files exist in the working directory:", "yellow")
    for path in ignored:
        cprint(f"  - {path}", "yellow")
    answer = input("Clean working directory anyway? [y/N]: ").strip().lower()
    return answer in ("y", "yes")


def remove_worktree(working_dir, git_dir):
    if not working_dir:
        return
    for entry in os.listdir(working_dir):
        path = os.path.join(working_dir, entry)
        if os.path.abspath(path) == os.path.abspath(git_dir):
            continue
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)


def derive_target(source, repo, remote):
    source = Path(source)
    name = source.name
    if name != ".git" and name.endswith(".git"):
        return str(source.with_name(name[:-4]))

    url = remote_url(repo, remote)
    if url:
        url_path = url.rstrip("/").replace("\\", "/")
        name = url_path.rsplit("/", 1)[-1]
        if name.endswith(".git"):
            name = name[:-4]
        if name:
            parent = source.parent.parent if source.name == ".git" else source.parent
            return str(parent / name)

    raise RuntimeError("Cannot infer target directory, please provide TARGET")


def ensure_empty_target(target):
    if os.path.exists(target):
        if not os.path.isdir(target):
            raise RuntimeError(f"Target exists and is not a directory: {target}")
        if os.listdir(target):
            raise RuntimeError(f"Target directory is not empty: {target}")
    else:
        os.makedirs(target)


def bool_config(repo, section, option, default=False):
    reader = repo.config_reader()
    try:
        return reader.get_value(section, option) in (True, "true", "True", "1", 1)
    except Exception:
        return default


def set_archive_config(repo, remote):
    cprint("Set core.bare = true", "green")
    with repo.config_writer() as writer:
        writer.set_value("core", "bare", "true")
        writer.set_value(f'remote "{remote}"', "mirror", "true")
        writer.set_value(f'remote "{remote}"', "fetch", "+refs/*:refs/*")


def set_worktree_config(repo, remote):
    cprint("Set core.bare = false", "green")
    with repo.config_writer() as writer:
        writer.set_value("core", "bare", "false")
        writer.set_value(f'remote "{remote}"', "mirror", "false")
        writer.set_value(
            f'remote "{remote}"',
            "fetch",
            f"+refs/heads/*:refs/remotes/{remote}/*",
        )


def is_archive_repo(repo, remote):
    return repo.bare and bool_config(repo, f'remote "{remote}"', "mirror", False)


def archive(path, remote, clean=False, force=False):
    path = os.path.normpath(os.path.abspath(path))
    repo = repo_from_worktree(path)
    if repo.is_dirty(untracked_files=True):
        raise RuntimeError("Repository has uncommitted or untracked changes")

    remote = resolve_remote(repo, remote)

    if clean:
        ignored = ignored_files(repo)
        if ignored and not force and not confirm_clean(ignored):
            raise RuntimeError("Clean cancelled by user")

    git_dir = repo.git_dir
    backup = backup_config(git_dir)

    if clean:
        cprint("Remove working directory files", "green")
        remove_worktree(repo.working_dir, git_dir)

    set_archive_config(repo, remote)

    cprint(f"Archive conversion done: {git_dir}", "green")
    cprint(f"Config backup: {backup}", "green")
    return 0


def restore_here(source, remote, branch):
    source = os.path.normpath(os.path.abspath(source))
    repo = repo_from_git_dir(source)
    remote = resolve_remote(repo, remote)
    if not is_archive_repo(repo, remote):
        raise RuntimeError(f"Expected a bare mirror repository: {source}")
    if os.path.basename(source) != ".git":
        raise RuntimeError("--here restore requires --path to point to a .git directory")

    backup = backup_config(repo.git_dir)
    set_worktree_config(repo, remote)

    worktree = os.path.dirname(repo.git_dir)
    if branch:
        cprint(f"Checkout {branch}", "green")
        git.Repo(worktree).git.checkout("-f", branch)
        git.Repo(worktree).git.reset("--hard", branch)

    cprint(f"Restore done: {worktree}", "green")
    cprint(f"Config backup: {backup}", "green")
    return 0


def restore(source, target, remote, branch, here=False):
    source = os.path.normpath(os.path.abspath(source))
    source, is_parent_dir = resolve_source_git_dir(source)

    if here or (is_parent_dir and not target):
        if is_parent_dir and not here:
            cprint(f"Using --here: in-place restore of {source}", "yellow")
        return restore_here(source, remote, branch)

    repo = repo_from_git_dir(source)
    remote = resolve_remote(repo, remote)
    if not is_archive_repo(repo, remote):
        raise RuntimeError(f"Expected a bare mirror repository: {source}")

    target = os.path.normpath(os.path.abspath(target or derive_target(source, repo, remote)))
    ensure_empty_target(target)

    target_git = os.path.join(target, ".git")
    if os.path.exists(target_git):
        raise RuntimeError(f"Target git directory already exists: {target_git}")

    backup = backup_config(repo.git_dir)
    cprint(f"Move {repo.git_dir} -> {target_git}", "green")
    shutil.move(repo.git_dir, target_git)

    restored = git.Repo(target_git)
    set_worktree_config(restored, remote)

    if branch:
        cprint(f"Checkout {branch}", "green")
        worktree = git.Repo(target)
        worktree.git.checkout("-f", branch)
        worktree.git.reset("--hard", branch)

    cprint(f"Restore done: {target}", "green")
    cprint(f"Config backup: {os.path.join(target_git, os.path.basename(backup))}", "green")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Convert Git repositories between normal and archive mirror layouts.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("mode", choices=["archive", "restore"], help="operation mode")
    parser.add_argument("--path", default=os.getcwd(), help="repository path")
    parser.add_argument("--name", help="target normal repository directory for --restore")
    parser.add_argument("--remote", default=None, help="remote name")
    parser.add_argument("--branch", help="branch to checkout after restore")
    parser.add_argument(
        "-H",
        "--here",
        action="store_true",
        help="restore archive .git directory in place",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="remove working directory files after archive",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="skip confirmation when cleaning a working directory with ignored files",
    )

    args = parser.parse_args()

    try:
        if args.mode == "archive":
            if not args.clean and args.force:
                cprint("Warning: --force is only valid with --clean", "yellow")
            return archive(args.path, args.remote, clean=args.clean, force=args.force)
        if args.mode == "restore":
            if args.clean:
                raise RuntimeError("--clean is only valid with archive mode")
            return restore(args.path, args.name, args.remote, args.branch, args.here)
    except Exception as e:
        cprint(f"Error: {e}", "red", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
