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
import subprocess
import sys

import git
from termcolor import cprint

from . import gwalk


DefaultManifest = "gdeploy.manifest"


def normalize_manifest(manifest):
    for repository in manifest.get("repositories", []):
        if isinstance(repository, dict) and "remote" in repository:
            remote = repository["remote"]
            if isinstance(remote, str) or isinstance(remote, list):
                repository["remote"] = {"origin": remote}
    return manifest


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


def scan_workspace(workspace, preferred_remote=None):
    repositories = []
    workspace = os.path.normpath(os.path.abspath(workspace))
    root_is_repo = gwalk.RepoWalk.isRepoRoot(workspace)
    root_name = os.path.basename(workspace)
    for directory in gwalk.RepoWalk(workspace, recursive=True):
        repo = git.Repo(directory)
        path = os.path.relpath(repo.working_dir, workspace).replace("\\", "/")
        if root_is_repo:
            path = root_name if path == "." else f"{root_name}/{path}"
        cprint(f"Scan {path}", "white")

        remotes = {}
        for remote in repo.remotes:
            urls = list(remote.urls)
            if urls:
                remotes[remote.name] = urls[0] if len(urls) == 1 else urls

        item = {
            "path": path,
            "commit": repo.head.commit.hexsha,
        }

        try:
            item["describe"] = repo.git.describe("--tags", "--dirty", "--always")
            if item["describe"].endswith("-dirty"):
                cprint(f"Warning: dirty repository: {path} ({item['describe']})", "yellow")
        except git.exc.GitCommandError:
            item["describe"] = ""

        if preferred_remote and preferred_remote in remotes:
            item["remote"] = {preferred_remote: remotes[preferred_remote]}
        elif remotes:
            item["remote"] = remotes

        try:
            item["branch"] = repo.active_branch.name
        except TypeError:
            cprint(f"Warning: skip detached branch for {item['path']}", "yellow", file=sys.stderr)

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
            item.update(scanned_by_path[path])
            if post is not None:
                item["post"] = post
            merged.append(item)
            seen.add(path)
        elif path:
            merged.append(old)
            seen.add(path)

    for item in scanned_repositories:
        if item["path"] not in seen:
            merged.append(item)

    return sorted(merged, key=lambda item: item["path"].lower())


def update_manifest(workspace, manifest_file, preferred_remote=None):
    old_manifest = load_manifest(manifest_file, missing=True)
    scanned_repositories = scan_workspace(workspace, preferred_remote)
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


def checkout_branch(repo, branch):
    if not branch:
        return

    repo.git.fetch("--all", "--prune")
    if branch in [head.name for head in repo.heads]:
        repo.git.checkout(branch)
    else:
        for remote in repo.remotes:
            refname = f"{remote.name}/{branch}"
            if refname in [ref.name for ref in remote.refs]:
                repo.git.checkout("-b", branch, "--track", refname)
                break
        else:
            repo.git.checkout("-b", branch)

    try:
        repo.git.pull("--ff-only")
    except git.exc.GitCommandError as e:
        cprint(f"Warning: pull failed in {repo.working_dir}: {e}", "yellow", file=sys.stderr)


def checkout_commit(repo, commit):
    if not commit:
        return
    repo.git.checkout(commit)


def clone_repository(remotes, target, branch):
    target_existed = os.path.exists(target)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    last_error = None
    for remote in remotes:
        try:
            cprint(f"Clone {target} from {remote}", "green")
            repo = git.Repo.clone_from(remote, target)
            checkout_branch(repo, branch)
            return repo
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


def select_remotes(remote_value, preferred_remote=None):
    if isinstance(remote_value, dict):
        if preferred_remote and preferred_remote in remote_value:
            values = [remote_value[preferred_remote]]
        elif not preferred_remote and "origin" in remote_value:
            values = [remote_value["origin"]]
        else:
            values = list(remote_value.values())[:1]
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
    return remotes


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


def deploy_manifest(workspace, manifest_file, preferred_remote=None, here=False, checkout_to_commit=False):
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
        target = repository_target(workspace, path, here)
        remote_value = replace_variables(repository.get("remote"), manifest, repository, workspace)
        branch = replace_variables(repository.get("branch"), manifest, repository, workspace)
        commit = replace_variables(repository.get("commit"), manifest, repository, workspace)
        post = replace_variables(repository.get("post"), manifest, repository, workspace)
        remotes = select_remotes(remote_value, preferred_remote)

        try:
            if os.path.exists(target) and not is_empty_directory(target):
                if not gwalk.RepoWalk.isRepoRoot(target):
                    cprint(f"Skip non-git directory: {target}", "red", file=sys.stderr)
                    summary["failed"] += 1
                    continue

                cprint(f"Update {target}", "green")
                repo = git.Repo(target)
                checkout_branch(repo, branch)
                summary["updated"] += 1
            else:
                if not remotes:
                    cprint(f"No remote for missing repository: {path}", "red", file=sys.stderr)
                    summary["failed"] += 1
                    continue
                repo = clone_repository(remotes, target, branch)
                summary["cloned"] += 1

            if checkout_to_commit:
                checkout_commit(repo, commit)

            if not run_post_commands(post, target):
                summary["post_failed"] += 1

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
    parser.add_argument("--remote", help="preferred remote name")
    parser.add_argument(
        "-H",
        "--here",
        action="store_true",
        help="deploy the manifest root repository into the workspace itself",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="checkout repositories to manifest commit ids after clone/update",
    )
    parser.add_argument("--debug", action="store_true", default=False, help=argparse.SUPPRESS)

    args = parser.parse_args()

    if args.debug:
        input("Wait for debugging and press Enter to continue...")

    workspace = os.path.normpath(os.path.abspath((args.directory or os.getcwd()).strip(" '\"")))
    manifest = args.manifest.strip(" '\"") if args.manifest else os.path.join(workspace, DefaultManifest)
    manifest = os.path.normpath(os.path.abspath(manifest))

    if args.scan:
        return update_manifest(workspace, manifest, args.remote)
    if not os.path.exists(manifest):
        cprint(f"Manifest file not found: {manifest}", "red", file=sys.stderr)
        return 1
    return deploy_manifest(workspace, manifest, args.remote, args.here, args.commit)


if __name__ == "__main__":
    sys.exit(main())
