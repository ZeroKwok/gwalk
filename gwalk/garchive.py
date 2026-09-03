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


def archive_config_path(config):
    return f"{config}.archive"


def mate_archive_path(git_dir):
    return os.path.join(git_dir, "mate.archive")


def save_config_archive(git_dir):
    config = os.path.join(git_dir, "config")
    if not os.path.isfile(config):
        raise RuntimeError(f"Git config not found: {config}")

    archive = archive_config_path(config)
    shutil.copy2(config, archive)
    return archive


def restore_config_archive(git_dir):
    config = os.path.join(git_dir, "config")
    archive = archive_config_path(config)
    if not os.path.isfile(archive):
        raise RuntimeError(f"Archive config not found: {archive}")

    cprint("Restore config.archive -> config", "green")
    shutil.move(archive, config)
    return config


def repo_from_worktree(path):
    repo = git.Repo(path, search_parent_directories=False)
    if repo.bare:
        raise RuntimeError(f"Expected a normal repository: {path}")
    return repo


def has_worktree_files(repo):
    working_dir = repo.working_dir
    if not working_dir or not os.path.isdir(working_dir):
        return False
    return any(
        os.path.abspath(os.path.join(working_dir, entry)) != os.path.abspath(repo.git_dir)
        for entry in os.listdir(working_dir)
    )


def repo_from_git_dir(path):
    return git.Repo(path)


def resolve_source_git_dir(source):
    source = os.path.normpath(os.path.abspath(source))

    candidate = os.path.join(source, ".git")

    if os.path.isdir(candidate):
        return candidate, True

    if os.path.isfile(candidate):
        raise RuntimeError(
            f"Git worktree is not supported, please point --path to the actual git directory: {candidate}"
        )

    return source, False


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


def head_branch(repo):
    try:
        name = repo.git.symbolic_ref("--short", "HEAD").strip()
        return name or None
    except Exception:
        return None


def resolve_checkout_branch(repo, branch):
    if branch:
        return branch
    if branch == "":
        return head_branch(repo)
    return None


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


def derive_target(source):
    source = Path(source)
    name = source.name
    if name == ".git":
        return str(source.parent)
    if name.endswith(".git"):
        return str(source.with_name(name[:-4]))
    raise RuntimeError("Cannot infer target directory, please provide TARGET")


def ensure_empty_target(target):
    if os.path.exists(target):
        if not os.path.isdir(target):
            raise RuntimeError(f"Target exists and is not a directory: {target}")
        if os.listdir(target):
            raise RuntimeError(f"Target directory is not empty: {target}")
    else:
        os.makedirs(target)


def set_archive_config(repo):
    cprint("Set all remotes as mirror", "green")
    with repo.config_writer() as writer:
        writer.set_value("core", "bare", "true")
        for remote in repo.remotes:
            section = f'remote "{remote.name}"'
            writer.set_value(section, "mirror", "true")
            writer.set_value(section, "fetch", "+refs/*:refs/*")


def is_archive_repo(repo):
    return repo.bare and os.path.isfile(archive_config_path(os.path.join(repo.git_dir, "config")))


def write_mate_archive(git_dir, worktree):
    with open(mate_archive_path(git_dir), "w", encoding="utf-8") as stream:
        worktree = os.path.abspath(worktree) if worktree else ""
        stream.write(f"worktree = {worktree}\n")
        stream.write(f"time = {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")


def read_mate_archive(git_dir):
    path = mate_archive_path(git_dir)
    if not os.path.isfile(path):
        return {}
    metadata = {}
    with open(path, "r", encoding="utf-8") as stream:
        for line in stream:
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            key, value = line.split("=", 1)
            metadata[key.strip()] = value.strip()
    return metadata


def remove_mate_archive(git_dir):
    path = mate_archive_path(git_dir)
    if os.path.isfile(path):
        os.remove(path)


def write_clone_config_archive(git_dir, repo):
    path = archive_config_path(os.path.join(git_dir, "config"))
    with open(path, "w", encoding="utf-8") as stream:
        stream.write("[core]\n\trepositoryformatversion = 0\n\tbare = false\n")
        reader = repo.config_reader()
        for remote in repo.remotes:
            section = f'remote "{remote.name}"'
            stream.write(f"\n[{section}]\n")
            try:
                url = reader.get_value(section, "url")
                stream.write(f"\turl = {url}\n")
            except Exception:
                pass
            stream.write(f"\tfetch = +refs/heads/*:refs/remotes/{remote.name}/*\n")


def archive(path, clean=False, force=False):
    path = os.path.normpath(os.path.abspath(path))
    repo = repo_from_worktree(path)
    if has_worktree_files(repo) and repo.is_dirty(untracked_files=True):
        raise RuntimeError("Repository has uncommitted or untracked changes")

    if clean:
        ignored = ignored_files(repo)
        if ignored and not force and not confirm_clean(ignored):
            raise RuntimeError("Clean cancelled by user")

    git_dir = repo.git_dir
    backup = save_config_archive(git_dir)
    metadata_worktree = "" if os.path.basename(path) == ".git" else path
    write_mate_archive(git_dir, metadata_worktree)

    if clean:
        cprint("Remove working directory files", "green")
        remove_worktree(repo.working_dir, git_dir)

    set_archive_config(repo)

    cprint(f"Archive conversion done: {git_dir}", "green")
    cprint(f"Config archive: {backup}", "green")
    return 0


def clone(url, directory=None):
    url_path = url.rstrip("/").replace("\\", "/")
    name = url_path.rsplit("/", 1)[-1]
    if name.endswith(".git"):
        name = name[:-4]
    if not name and not directory:
        raise RuntimeError(f"Cannot infer target directory from URL: {url}")

    target = os.path.abspath(directory or os.path.join(os.getcwd(), name))
    if os.path.exists(target) and os.listdir(target):
        raise RuntimeError(f"Target directory is not empty: {target}")
    os.makedirs(target, exist_ok=True)
    git_dir = os.path.join(target, ".git")
    cprint(f"Clone archive {url} -> {git_dir}", "green")
    repo = git.Repo.clone_from(url, git_dir, mirror=True)
    write_clone_config_archive(git_dir, repo)
    write_mate_archive(git_dir, target)
    cprint(f"Archive clone done: {git_dir}", "green")
    return 0


def restore_here(source, branch):
    source = os.path.normpath(os.path.abspath(source))
    repo = repo_from_git_dir(source)
    if not is_archive_repo(repo):
        raise RuntimeError(f"Expected an archive repository with config.archive: {source}")
    if os.path.basename(source) != ".git":
        raise RuntimeError("--here restore requires --path to point to a .git directory")

    restore_config_archive(repo.git_dir)
    remove_mate_archive(repo.git_dir)

    worktree = os.path.dirname(repo.git_dir)
    branch = resolve_checkout_branch(repo, branch)
    if branch:
        cprint(f"Checkout {branch}", "green")
        git.Repo(worktree).git.checkout("-f", branch)
        git.Repo(worktree).git.reset("--hard", branch)

    cprint(f"Restore done: {worktree}", "green")
    return 0


def restore(source, target, branch, here=False):
    source = os.path.normpath(os.path.abspath(source))
    source, is_parent_dir = resolve_source_git_dir(source)

    if here or (is_parent_dir and not target):
        if is_parent_dir and not here:
            cprint(f"Using --here: in-place restore of {source}", "yellow")
        return restore_here(source, branch)

    repo = repo_from_git_dir(source)
    if not is_archive_repo(repo):
        raise RuntimeError(f"Expected an archive repository with config.archive: {source}")

    if not target and not here and not is_parent_dir and os.path.basename(source) == ".git":
        return restore_here(source, branch)

    target = os.path.normpath(os.path.abspath(target or derive_target(source)))
    ensure_empty_target(target)

    target_git = os.path.join(target, ".git")
    if os.path.exists(target_git):
        raise RuntimeError(f"Target git directory already exists: {target_git}")

    cprint(f"Move {repo.git_dir} -> {target_git}", "green")
    shutil.move(repo.git_dir, target_git)

    restored = git.Repo(target_git)
    restore_config_archive(target_git)
    remove_mate_archive(target_git)

    branch = resolve_checkout_branch(restored, branch)
    if branch:
        cprint(f"Checkout {branch}", "green")
        worktree = git.Repo(target)
        worktree.git.checkout("-f", branch)
        worktree.git.reset("--hard", branch)

    cprint(f"Restore done: {target}", "green")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Convert Git repositories between normal and archive mirror layouts.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("mode", choices=["archive", "clone", "restore"], help="operation mode")
    parser.add_argument("url", nargs="?", help="repository URL for clone mode")
    parser.add_argument("directory", nargs="?", help="target directory for clone mode")
    parser.add_argument("--path", default=os.getcwd(), help="repository path")
    parser.add_argument("--name", help="target normal repository directory for --restore")
    parser.add_argument(
        "--checkout",
        nargs="?",
        const="",
        default=None,
        metavar="BRANCH",
        help="checkout after restore; omit BRANCH to use the current HEAD branch",
    )
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
            if args.name:
                raise RuntimeError("--name is only valid with restore mode")
            if args.checkout is not None:
                raise RuntimeError("--checkout is only valid with restore mode")
            if args.here:
                raise RuntimeError("--here is only valid with restore mode")
            if not args.clean and args.force:
                cprint("Warning: --force is only valid with --clean", "yellow")
            if args.url or args.directory:
                raise RuntimeError("URL and directory are only valid with clone mode")
            return archive(args.path, clean=args.clean, force=args.force)
        
        if args.mode == "clone":
            if not args.url:
                raise RuntimeError("clone requires a repository URL")
            if args.path != os.getcwd() or args.name or args.checkout is not None or args.here or args.clean or args.force:
                raise RuntimeError("clone accepts only URL and optional directory")
            return clone(args.url, args.directory)
        
        if args.mode == "restore":
            if args.url or args.directory:
                raise RuntimeError("URL and directory are only valid with clone mode")
            if args.clean:
                raise RuntimeError("--clean is only valid with archive mode")
            if args.force:
                cprint("Warning: --force is only valid with archive --clean", "yellow")
            if args.here and args.name:
                raise RuntimeError("--name cannot be used with --here")
            return restore(args.path, args.name, args.checkout, args.here)
    except Exception as e:
        cprint(f"Error: {e}", "red", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
