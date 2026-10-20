#! python
# -*- coding: utf-8 -*-
#
# This file is part of the gwalk project.
# Copyright (c) 2020-2026 Zero Kwok.
#

import argparse
import ast
import difflib
import os
import pprint
import shutil
import signal
import subprocess
import sys
import time

import git
from termcolor import cprint

from . import garchive
from . import gwalk


DefaultManifest = "gdeploy.manifest"


def normalize_manifest(manifest):
    for repository in manifest.get("repositories", []):
        if isinstance(repository, dict) and "remote" in repository:
            remote = repository["remote"]
            if isinstance(remote, str) or isinstance(remote, list):
                repository["remote"] = {"origin": remote}
    return manifest


def bool_config(repo, section, option, default=False):
    reader = repo.config_reader()
    try:
        return reader.get_value(section, option) in (True, "true", "True", "1", 1)
    except Exception:
        return default


def is_bare_repository_path(path):
    try:
        return git.Repo(path).bare
    except Exception:
        return False


def is_mirror_repository(repo, remote_name=None):
    if not repo.bare:
        return False
    if remote_name:
        return bool_config(repo, f'remote "{remote_name}"', "mirror", False)
    for remote in repo.remotes:
        if bool_config(repo, f'remote "{remote.name}"', "mirror", False):
            return True
    return False


def archive_git_dir(path):
    return os.path.join(path, ".git")


def is_archive_directory(path, remote_name=None):
    if not os.path.isdir(path):
        return False
    if sorted(os.listdir(path)) != [".git"]:
        return False
    git_dir = archive_git_dir(path)
    if not os.path.isfile(os.path.join(git_dir, "config.archive")):
        return False
    try:
        repo = git.Repo(git_dir)
    except Exception:
        return False
    return is_mirror_repository(repo, remote_name)


def repository_mode(repo, directory, repo_type, preferred_remotes=None):
    if repo_type == 2:
        return "submodule"
    if is_archive_directory(directory, selected_remote_name(repo, preferred_remotes)):
        return "archive"
    if repo.bare:
        matched_remote = selected_remote_name(repo, preferred_remotes)
        return "mirror" if is_mirror_repository(repo, matched_remote) else "bare"
    return "worktree"


def existing_directory_mode(directory):
    """Detect the actual mode of an existing target directory.

    Returns one of ``archive``, ``mirror``, ``bare`` or ``worktree``, or
    ``None`` when the directory does not exist or is not a Git repository.
    """
    if not os.path.isdir(directory):
        return None
    try:
        repo = git.Repo(directory)
    except (git.exc.InvalidGitRepositoryError, git.exc.NoSuchPathError):
        return None

    if is_archive_directory(directory):
        return "archive"
    if repo.bare:
        return "mirror" if is_mirror_repository(repo) else "bare"
    return "worktree"


def load_manifest(filename, missing=False):
    if missing and not os.path.exists(filename):
        return {"variables": [], "repositories": []}

    with open(filename, "r", encoding="utf-8") as f:
        manifest = ast.literal_eval(f.read())

    if not isinstance(manifest, dict):
        raise RuntimeError("Incorrect manifest file: root object must be a dict")
    if "variables" not in manifest:
        manifest["variables"] = []
    if "repositories" not in manifest:
        manifest["repositories"] = []
    if not isinstance(manifest["variables"], list):
        raise RuntimeError("Incorrect manifest file: variables must be a list")
    if not isinstance(manifest["repositories"], list):
        raise RuntimeError("Incorrect manifest file: repositories must be a list")
    return normalize_manifest(manifest)


def render_manifest(manifest):
    manifest = normalize_manifest(manifest)
    body = pprint.pformat(
        manifest,
        indent=1,
        width=100,
        compact=False,
        sort_dicts=False,
    )
    return "#! gdeploy.py\n# -*- coding: utf-8 -*-\n" + body + "\n"


def replace_variables(value, manifest, repository, workspace):
    if value is None:
        return None
    if isinstance(value, dict):
        return {
            name: replace_variables(remote, manifest, repository, workspace)
            for name, remote in value.items()
        }
    if isinstance(value, list):
        return [replace_variables(item, manifest, repository, workspace) for item in value]
    if not isinstance(value, str):
        return value

    replacements = {
        "{RepositoryName}": os.path.basename(repository["path"]),
        "{RepositoryPath}": repository["path"],
        "{Workspace}": workspace,
    }
    for item in manifest.get("variables", []):
        if not isinstance(item, dict) or "name" not in item or "value" not in item:
            raise RuntimeError("Incorrect manifest file: variables items need name and value")
        name = str(item["name"])
        key = name if name.startswith("{") and name.endswith("}") else "{" + name + "}"
        replacements[key] = str(item["value"])

    for key, replacement in replacements.items():
        value = value.replace(key, replacement)
    return value


def selected_remote_name(repo, preferred_remotes=None):
    preferred_remotes = preferred_remotes or []
    remote_names = [remote.name for remote in repo.remotes]
    matched = next((name for name in preferred_remotes if name in remote_names), None)
    if matched:
        return matched
    if not preferred_remotes and "origin" in remote_names:
        return "origin"
    return remote_names[0] if remote_names else None


def repository_relative_path(repo, directory, workspace, root_is_repo, root_name):
    if repo.bare:
        path = os.path.relpath(directory, workspace).replace("\\", "/")
    else:
        path = os.path.relpath(repo.working_dir, workspace).replace("\\", "/")
    if root_is_repo:
        path = root_name if path == "." else f"{root_name}/{path}"
    return path


def scan_bare_repository_dirs(workspace):
    for root, dirs, _ in os.walk(workspace):
        if os.path.basename(root) == ".git":
            dirs[:] = []
            continue
        if is_bare_repository_path(root):
            yield root
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in [".git", ".vs", ".vscode"]]


def describe_repository(repo):
    try:
        return repo.git.describe("--tags", "--dirty", "--always")
    except git.exc.GitCommandError:
        return ""


def active_branch_name(repo):
    try:
        return repo.active_branch.name
    except TypeError:
        return ""


def scan_workspace(workspace, preferred_remotes=None):
    preferred_remotes = preferred_remotes or []
    repositories = []
    workspace = os.path.normpath(os.path.abspath(workspace))
    root_is_repo = (
        gwalk.RepoWalk.isRepoRoot(workspace)
        or is_bare_repository_path(workspace)
        or is_archive_directory(workspace)
    )
    root_name = os.path.basename(workspace)
    normal_paths = []
    directories = []
    seen_directories = set()
    for directory in gwalk.RepoWalk(workspace, recursive=True):
        directory = os.path.normpath(os.path.abspath(directory))
        if directory not in seen_directories:
            directories.append(directory)
            seen_directories.add(directory)
    for directory in scan_bare_repository_dirs(workspace):
        directory = os.path.normpath(os.path.abspath(directory))
        if directory not in seen_directories:
            directories.append(directory)
            seen_directories.add(directory)

    for directory in directories:
        for _, dirs, files in os.walk(directory):
            repo_type = gwalk.RepoWalk.repoTypeByFiles(dirs, files)
            break
        else:
            repo_type = 0

        if is_archive_directory(directory):
            repo = git.Repo(archive_git_dir(directory))
        else:
            repo = git.Repo(directory)
        path = repository_relative_path(repo, directory, workspace, root_is_repo, root_name)
        cprint(f"Scan {path}", "white")

        remotes = {}
        for remote in repo.remotes:
            urls = list(remote.urls)
            if urls:
                remotes[remote.name] = urls[0] if len(urls) == 1 else urls

        mode = repository_mode(repo, directory, repo_type, preferred_remotes)
        item = {
            "path": path,
            "type": "submodule" if mode == "submodule" else "repository",
            "commit": repo.head.commit.hexsha,
        }
        if mode not in ["worktree", "submodule"]:
            item["mode"] = mode

        if mode == "submodule":
            parent = ""
            for candidate in reversed(normal_paths):
                if path.startswith(candidate + "/"):
                    parent = candidate
                    break
            item["parent"] = parent
            cprint(f"Warning: found git submodule: {path}", "yellow")
        else:
            normal_paths.append(path)

        item["describe"] = describe_repository(repo)
        if item["describe"].endswith("-dirty"):
            cprint(f"Warning: dirty repository: {path} ({item['describe']})", "yellow")

        matched_remote = next((name for name in preferred_remotes if name in remotes), None)
        if matched_remote:
            item["remote"] = {matched_remote: remotes[matched_remote]}
        elif remotes:
            item["remote"] = remotes

        branch = active_branch_name(repo)
        if branch:
            item["branch"] = branch
        elif not repo.bare:
            item["branch"] = None
            cprint(f"Warning: detached HEAD: {path} ({item['commit'][:12]})", "yellow", file=sys.stderr)

        repositories.append(item)

    return sorted(repositories, key=lambda item: item["path"].lower())


def merge_repositories(old_repositories, scanned_repositories):
    scanned_by_path = {item["path"]: item for item in scanned_repositories}
    merged = []
    seen = set()

    for old in old_repositories:
        path = old.get("path") if isinstance(old, dict) else None
        if path in scanned_by_path:
            item = dict(old)
            post = item.get("post")
            mode = item.get("mode")
            item.update(scanned_by_path[path])
            if post is not None:
                item["post"] = post
            if mode == "archive" and scanned_by_path[path].get("mode") in [None, "worktree"]:
                item["mode"] = mode
            merged.append(item)
            seen.add(path)
        elif path:
            merged.append(old)
            seen.add(path)

    for item in scanned_repositories:
        if item["path"] not in seen:
            merged.append(item)

    return sorted(merged, key=lambda item: item["path"].lower())


def update_manifest(workspace, manifest_file, preferred_remotes=None, listed_only=False, sync_remotes=False):
    old_manifest = load_manifest(manifest_file, missing=True)
    scanned_repositories = scan_workspace(workspace, preferred_remotes)
    if listed_only:
        listed = {
            item.get("path")
            for item in old_manifest.get("repositories", [])
            if isinstance(item, dict) and item.get("path")
        }
        scanned_repositories = [
            item for item in scanned_repositories
            if item.get("path") in listed
        ]
    old_by_path = {
        item["path"]: item
        for item in old_manifest["repositories"]
        if isinstance(item, dict) and item.get("path")
    }
    for scanned in scanned_repositories:
        old_item = old_by_path.get(scanned["path"])
        if not old_item or not old_item.get("remote"):
            continue

        manifest_remote = replace_variables(old_item["remote"], old_manifest, old_item, workspace)
        local_remote = scanned.get("remote") or {}
        matches = set(manifest_remote) == set(local_remote)
        if matches:
            for name, value in local_remote.items():
                local_urls = value if isinstance(value, list) else [value]
                allowed = manifest_remote[name]
                allowed_urls = allowed if isinstance(allowed, list) else [allowed]
                if not local_urls or local_urls[0].replace("\\", "/") not in {
                    url.replace("\\", "/") for url in allowed_urls
                }:
                    matches = False
                    break
        if matches:
            scanned["remote"] = old_item["remote"]
            continue

        cprint(f"Remote differs in {scanned['path']}", "yellow")
        cprint("  Manifest:", "yellow")
        for name, value in manifest_remote.items():
            cprint(f"    {name} -> {value}", "yellow")
        cprint("  Local:", "yellow")
        for name, value in local_remote.items():
            cprint(f"    {name} -> {value}", "yellow")
        if not local_remote:
            cprint("    <none>", "yellow")

        if not sync_remotes:
            if not sys.stdin.isatty():
                cprint("Remote differs; use --sync-remotes to update the manifest", "red", file=sys.stderr)
                return 1
            try:
                answer = input(f"Update manifest remotes for {scanned['path']}? [y/N] ").strip().lower()
            except EOFError:
                answer = ""
            if answer != "y":
                scanned["remote"] = old_item["remote"]
                continue
        scanned["remote"] = local_remote

    new_manifest = {
        "variables": old_manifest.get("variables", []),
        "repositories": merge_repositories(old_manifest.get("repositories", []), scanned_repositories),
    }

    old = []
    if os.path.exists(manifest_file):
        old = render_manifest(old_manifest).splitlines()
    new = render_manifest(new_manifest).splitlines()

    diff = list(difflib.unified_diff(
        old,
        new,
        fromfile=manifest_file + " (old)",
        tofile=manifest_file + " (new)",
        lineterm="",
    ))

    if not diff:
        cprint(f"Manifest is up to date: {manifest_file}", "green")
        return 0

    print("")
    for line in diff:
        if line.startswith("+"):
            cprint(line, "green")
        elif line.startswith("-"):
            cprint(line, "red")
        elif line.startswith("@@"):
            cprint(line, "cyan")
        else:
            cprint(line)

    cprint(f"\nUpdate {manifest_file} with these changes? [y/N]", end=" ")
    if input().strip().lower() != "y":
        cprint("Error: User Cancelled", "red", file=sys.stderr)
        return 1

    with open(manifest_file, "w", encoding="utf-8", newline="\n") as f:
        f.write(render_manifest(new_manifest))
    return 0


def checkout_branch(repo, branch, remote_name):
    if not branch:
        return

    if repo.is_dirty(untracked_files=True, submodules=True):
        raise RuntimeError(f"Working tree is dirty: {repo.working_dir}")

    remote_branch = f"{remote_name}/{branch}" if remote_name else None
    if remote_branch:
        try:
            repo.git.show_ref("--verify", f"refs/remotes/{remote_branch}")
        except git.exc.GitCommandError:
            raise RuntimeError(f"Remote branch not found: {remote_branch}")

    if branch in [head.name for head in repo.heads]:
        repo.git.switch(branch)
    elif remote_branch:
        repo.git.switch("--track", "-c", branch, remote_branch)
    else:
        raise RuntimeError(f"Branch not found: {branch}")

    if remote_branch:
        repo.git.merge("--ff-only", remote_branch)


def commit_available(repo, commit):
    try:
        repo.git.cat_file("-e", f"{commit}^{{commit}}")
        return True
    except git.exc.GitCommandError:
        return False


def checkout_commit(repo, commit):
    if not commit:
        raise RuntimeError(f"Manifest commit is missing: {repo.working_dir}")

    if not commit_available(repo, commit):
        raise RuntimeError(f"Manifest commit not found: {commit}")
    if repo.is_dirty(untracked_files=True, submodules=True):
        raise RuntimeError(f"Working tree is dirty: {repo.working_dir}")
    repo.git.switch("--detach", commit)


def update_submodules(repo):
    try:
        modules = repo.submodules
    except Exception:
        modules = []
    if not modules:
        return

    cprint(f"Update submodules in {repo.working_dir}", "green")
    repo.git.submodule("update", "--init", "--recursive")


def terminate_process(process):
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.terminate()
        process.wait(timeout=3)
    except Exception:
        if process.poll() is None:
            process.kill()
            process.wait()


def run_git_command(args, cwd=None):
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        ["git", *args],
        cwd=cwd,
        creationflags=flags,
    )
    try:
        while process.poll() is None:
            time.sleep(0.1)
    except KeyboardInterrupt:
        terminate_process(process)
        raise
    if process.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {process.returncode}")


def clone_repository(remotes, target, remote_name):
    target_existed = os.path.exists(target)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    last_error = None
    for remote in remotes:
        try:
            cprint(f"Clone {target} from {remote}", "green")
            args = ["clone"]
            if remote_name:
                args.extend(["--origin", remote_name])
            run_git_command(args + [remote, target])
            return git.Repo(target)
        except Exception as e:
            last_error = e
            cprint(f"Clone failed from {remote}: {e}", "red", file=sys.stderr)
            if not target_existed and os.path.exists(target):
                shutil.rmtree(target)
    raise last_error


def is_empty_directory(path):
    return os.path.isdir(path) and not os.listdir(path)


def repository_target(workspace, path, here=False):
    if not here:
        return os.path.normpath(os.path.join(workspace, path))

    parts = path.replace("\\", "/").split("/")
    if len(parts) <= 1:
        return workspace
    return os.path.normpath(os.path.join(workspace, *parts[1:]))


def select_remotes(remote_value, preferred_remotes=None):
    _, remotes = select_remote_entry(remote_value, preferred_remotes)
    return remotes


def select_remote_entry(remote_value, preferred_remotes=None):
    preferred_remotes = preferred_remotes or []
    name = None
    if isinstance(remote_value, dict):
        matched_remote = next((name for name in preferred_remotes if name in remote_value), None)
        if matched_remote:
            name = matched_remote
            values = [remote_value[matched_remote]]
        elif not preferred_remotes and "origin" in remote_value:
            name = "origin"
            values = [remote_value["origin"]]
        else:
            items = list(remote_value.items())[:1]
            name = items[0][0] if items else None
            values = [items[0][1]] if items else []
    elif isinstance(remote_value, list):
        values = remote_value
    elif remote_value:
        values = [remote_value]
    else:
        values = []

    remotes = []
    for value in values:
        if isinstance(value, list):
            remotes.extend(value)
        elif value:
            remotes.append(value)
    return name, remotes


def ensure_manifest_remote(repo, name, urls, sync_remotes=False, display_path=None):
    if not urls:
        return selected_remote_name(repo)

    if not name:
        raise RuntimeError(f"Manifest remote has no name: {repo.git_dir}")

    allowed_urls = {url.replace("\\", "/") for url in urls}
    existing = next((remote for remote in repo.remotes if remote.name == name), None)
    current_urls = repo.git.config("--get-all", f"remote.{name}.url").splitlines() if existing else []
    if current_urls and current_urls[0].replace("\\", "/") in allowed_urls:
        return name

    display_path = display_path or repo.working_tree_dir or repo.git_dir
    if existing:
        cprint(f"Remote '{name}' URL differs in {display_path}", "yellow")
    else:
        cprint(f"Manifest remote '{name}' is missing in {display_path}", "yellow")
    cprint(f"  Manifest: {name} -> {urls[0]}", "yellow")
    if existing:
        cprint(f"  Existing: {name} -> {current_urls[0] if current_urls else '<missing>'}", "yellow")
    else:
        remotes = list(repo.remotes)
        if len(remotes) != 1:
            cprint("  Existing:", "yellow")
        for remote in remotes:
            remote_urls = repo.git.config("--get-all", f"remote.{remote.name}.url").splitlines()
            remote_url = remote_urls[0] if remote_urls else "<missing>"
            same_url = remote_urls and remote_url.replace("\\", "/") in allowed_urls
            prefix = "  Existing: " if len(remotes) == 1 else "    "
            cprint(f"{prefix}{remote.name} -> {remote_url}{' (same fetch URL)' if same_url else ''}", "yellow")
        if not remotes:
            cprint("    <none>", "yellow")
    if not sync_remotes:
        if not sys.stdin.isatty():
            reason = "Remote differs" if existing else f"Remote {name} is missing"
            raise RuntimeError(f"{reason}; use --sync-remotes to approve synchronization")
        try:
            action = "Update" if existing else "Add"
            answer = input(f"{action} remote '{name}'? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer != "y":
            raise RuntimeError(f"Remote synchronization declined: {name}")

    if existing:
        repo.git.remote("set-url", name, urls[0])
    elif is_mirror_repository(repo):
        repo.git.remote("add", "--mirror=fetch", name, urls[0])
        repo.git.config(f"remote.{name}.mirror", "true")
    else:
        repo.create_remote(name, urls[0])
    return name


def fetch_repository(repo, remote_name):
    if remote_name:
        repo.git.fetch(remote_name, "--prune")


def run_post_commands(commands, directory):
    if not commands:
        return True
    if isinstance(commands, str):
        commands = [commands]

    ok = True
    for command in commands:
        cprint(f"> {command}", "green")
        code = subprocess.call(command, cwd=directory, shell=True)
        if code != 0:
            cprint(f"Post command failed ({code}): {command}", "red", file=sys.stderr)
            ok = False
    return ok


def clone_mode_repository(mode, remotes, target, remote_name):
    target_existed = os.path.exists(target)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if mode == "archive":
        os.makedirs(target, exist_ok=True)
        clone_target = archive_git_dir(target)
    elif mode == "mirror":
        clone_target = target
    elif mode == "bare":
        clone_target = target
    else:
        raise RuntimeError(f"Unsupported repository mode: {mode}")

    last_error = None
    for remote in remotes:
        try:
            cprint(f"Clone {target} from {remote} ({mode})", "green")
            if mode == "archive":
                garchive.clone(remote, target)
                repo = git.Repo(archive_git_dir(target))
                if remote_name and remote_name != "origin":
                    repo.git.remote("rename", "origin", remote_name)
                return repo
            args = ["clone"]
            if remote_name:
                args.extend(["--origin", remote_name])
            if mode == "mirror":
                args.append("--mirror")
            elif mode == "bare":
                args.append("--bare")
            args.extend([remote, clone_target])
            run_git_command(args)
            return git.Repo(clone_target)
        except Exception as e:
            last_error = e
            cprint(f"Clone failed from {remote}: {e}", "red", file=sys.stderr)
            if not target_existed and os.path.exists(target):
                shutil.rmtree(target)
            if mode == "archive":
                os.makedirs(target, exist_ok=True)
    raise last_error


def update_bare_like_repository(repo, target, remote_name):
    cprint(f"Update {target}", "green")
    fetch_repository(repo, remote_name)


def ensure_checkout_target(repository, branch, commit, checkout_to_commit):
    if branch or (checkout_to_commit and commit):
        return
    raise RuntimeError(
        f"Archive repository needs branch or --commit with commit to checkout: {repository['path']}"
    )


def deploy_manifest(
    workspace,
    manifest_file,
    preferred_remotes=None,
    here=False,
    checkout_to_commit=False,
    checkout_archive=False,
    sync_remotes=False,
):
    manifest = load_manifest(manifest_file)
    summary = {
        "cloned": 0,
        "updated": 0,
        "post_failed": 0,
        "skipped": 0,
        "failed": 0,
    }

    for repository in manifest["repositories"]:
        if not isinstance(repository, dict) or "path" not in repository:
            cprint(f"Invalid repository item: {repository}", "red", file=sys.stderr)
            summary["failed"] += 1
            continue

        path = repository["path"]
        if repository.get("type") == "submodule":
            parent = repository.get("parent") or "<unknown>"
            cprint(f"Skip submodule: {path} (managed by {parent})", "yellow")
            summary["skipped"] += 1
            continue

        target = repository_target(workspace, path, here)
        display_path = os.path.relpath(target, workspace).replace("\\", "/")
        remote_value = replace_variables(repository.get("remote"), manifest, repository, workspace)
        branch = replace_variables(repository.get("branch"), manifest, repository, workspace)
        commit = replace_variables(repository.get("commit"), manifest, repository, workspace)
        post = replace_variables(repository.get("post"), manifest, repository, workspace)
        remote_name, remotes = select_remote_entry(remote_value, preferred_remotes)
        mode = repository.get("mode") or existing_directory_mode(target) or "worktree"
        should_run_post = mode == "worktree"

        try:
            if mode in ["archive", "mirror", "bare"]:
                if checkout_archive and mode != "archive":
                    cprint(f"Skip checkout for {mode} repository: {path}", "yellow")

                existed = os.path.exists(target) and not is_empty_directory(target)
                if existed:
                    if mode == "archive" and is_archive_directory(target):
                        repo = git.Repo(archive_git_dir(target))
                    elif mode in ["mirror", "bare"] and is_bare_repository_path(target):
                        repo = git.Repo(target)
                        if mode == "mirror" and not is_mirror_repository(repo):
                            raise RuntimeError(f"Expected a mirror repository: {target}")
                        if mode == "bare" and is_mirror_repository(repo):
                            raise RuntimeError(f"Expected a bare non-mirror repository: {target}")
                    elif mode == "archive" and gwalk.RepoWalk.isRepoRoot(target):
                        repo = git.Repo(target)
                    else:
                        raise RuntimeError(f"Expected a {mode} repository: {target}")

                    remote_name = ensure_manifest_remote(repo, remote_name, remotes, sync_remotes, display_path)
                    if repo.bare:
                        update_bare_like_repository(repo, target, remote_name)
                    else:
                        cprint(f"Update {target}", "green")
                        fetch_repository(repo, remote_name)
                else:
                    if not remotes:
                        raise RuntimeError(f"No remote for missing repository: {path}")
                    repo = clone_mode_repository(mode, remotes, target, remote_name)

                if mode == "archive" and checkout_archive:
                    ensure_checkout_target(repository, branch, commit, checkout_to_commit)
                    if repo.bare:
                        if checkout_to_commit and not commit_available(repo, commit):
                            raise RuntimeError(f"Manifest commit not found: {commit}")
                        garchive.restore(
                            archive_git_dir(target), None,
                            commit if checkout_to_commit else branch, here=True,
                        )
                        repo = git.Repo(target)
                    if checkout_to_commit:
                        checkout_commit(repo, commit)
                    else:
                        fetch_repository(repo, remote_name)
                        checkout_branch(repo, branch, remote_name)
                    update_submodules(repo)
                    should_run_post = True
                elif mode == "archive" and not repo.bare:
                    if checkout_to_commit:
                        checkout_commit(repo, commit)
                    else:
                        checkout_branch(repo, branch, remote_name)
                    update_submodules(repo)
                    should_run_post = checkout_archive

                if should_run_post and not run_post_commands(post, target):
                    summary["post_failed"] += 1
                summary["updated" if existed else "cloned"] += 1
                continue

            if mode != "worktree":
                raise RuntimeError(f"Unsupported repository mode: {mode}")

            existed = os.path.exists(target) and not is_empty_directory(target)
            if existed:
                if not gwalk.RepoWalk.isRepoRoot(target):
                    raise RuntimeError(f"Expected a Git repository: {target}")

                cprint(f"Update {target}", "green")
                repo = git.Repo(target)
                remote_name = ensure_manifest_remote(repo, remote_name, remotes, sync_remotes, display_path)
                fetch_repository(repo, remote_name)
            else:
                if not remotes:
                    raise RuntimeError(f"No remote for missing repository: {path}")
                repo = clone_repository(remotes, target, remote_name)

            if checkout_to_commit:
                checkout_commit(repo, commit)
            else:
                checkout_branch(repo, branch, remote_name)

            update_submodules(repo)

            if should_run_post and not run_post_commands(post, target):
                summary["post_failed"] += 1
            summary["updated" if existed else "cloned"] += 1

        except Exception as e:
            cprint(f"Failed {path}: {e}", "red", file=sys.stderr)
            summary["failed"] += 1

    cprint(
        "Done. "
        f"{summary['cloned']} cloned, "
        f"{summary['updated']} updated, "
        f"{summary['post_failed']} post failed, "
        f"{summary['skipped']} skipped, "
        f"{summary['failed']} failed.",
        "green" if summary["failed"] == 0 and summary["post_failed"] == 0 else "yellow",
    )
    return 0 if summary["failed"] == 0 and summary["post_failed"] == 0 else 1


def main():
    parser = argparse.ArgumentParser(
        description="Deploy or update a Git workspace from a manifest.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("manifest", nargs="?", help="manifest file")
    parser.add_argument("-d", "--directory", help="workspace directory")
    parser.add_argument(
        "--scan",
        action="store_true",
        help="scan workspace and update manifest after confirmation",
    )
    parser.add_argument(
        "--listed",
        action="store_true",
        help="with --scan, update only repositories already listed in the manifest",
    )
    parser.add_argument(
        "--remote",
        action="append",
        default=[],
        help="preferred remote name; repeat to define priority",
    )
    parser.add_argument(
        "-H",
        "--here",
        action="store_true",
        help="deploy the manifest root repository into the workspace itself",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="checkout repositories to manifest commits with detached HEAD",
    )
    parser.add_argument(
        "--sync-remotes",
        action="store_true",
        help="approve remote synchronization without prompting (scan: local to manifest; deploy: manifest to local)",
    )
    parser.add_argument(
        "--checkout",
        action="store_true",
        help="checkout archive repositories into normal worktrees",
    )
    parser.add_argument("--debug", action="store_true", default=False, help=argparse.SUPPRESS)

    args = parser.parse_args()

    if args.debug:
        input("Wait for debugging and press Enter to continue...")

    workspace = os.path.normpath(os.path.abspath((args.directory or os.getcwd()).strip(" '\"")))
    manifest = args.manifest.strip(" '\"") if args.manifest else os.path.join(workspace, DefaultManifest)
    manifest = os.path.normpath(os.path.abspath(manifest))

    try:
        if args.scan:
            return update_manifest(workspace, manifest, args.remote, args.listed, args.sync_remotes)
        if not os.path.exists(manifest):
            cprint(f"Manifest file not found: {manifest}", "red", file=sys.stderr)
            return 1
        return deploy_manifest(
            workspace, manifest, args.remote, args.here, args.commit,
            args.checkout, args.sync_remotes,
        )
    except KeyboardInterrupt:
        cprint("\nInterrupted", "red", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
