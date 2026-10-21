import ast
import os
import shutil
import subprocess
import sys
from types import SimpleNamespace

import git
import pytest

from gwalk import gdeploy


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


def test_replace_variables_supports_manifest_and_builtin_values(tmp_path):
    manifest = {
        "variables": [
            {"name": "Host", "value": "https://example.com"},
            {"name": "{Branch}", "value": "dev"},
        ],
        "repositories": [],
    }
    repository = {"path": "libs/demo"}

    assert (
        gdeploy.replace_variables(
            "{Host}/{RepositoryName}.git:{RepositoryPath}:{Workspace}",
            manifest,
            repository,
            str(tmp_path),
        )
        == f"https://example.com/demo.git:libs/demo:{tmp_path}"
    )
    assert gdeploy.replace_variables("{Branch}", manifest, repository, str(tmp_path)) == "dev"
    assert gdeploy.replace_variables(["{Host}/a.git"], manifest, repository, str(tmp_path)) == [
        "https://example.com/a.git"
    ]
    assert gdeploy.replace_variables(
        {"origin": "{Host}/{RepositoryName}.git"},
        manifest,
        repository,
        str(tmp_path),
    ) == {"origin": "https://example.com/demo.git"}


def test_render_and_load_manifest_roundtrip(tmp_path):
    manifest = {
        "variables": [{"name": "Host", "value": "https://example.com"}],
        "repositories": [
            {
                "path": "demo",
                "remote": {"origin": "{Host}/{RepositoryName}.git"},
                "branch": "main",
                "post": ["echo done"],
            }
        ],
    }
    filename = tmp_path / "gdeploy.manifest"
    filename.write_text(gdeploy.render_manifest(manifest), encoding="utf-8")

    assert gdeploy.load_manifest(str(filename)) == manifest
    assert ast.literal_eval(filename.read_text(encoding="utf-8").split("\n", 2)[2]) == manifest


def test_render_manifest_normalizes_unnamed_remote_list():
    manifest = {
        "variables": [],
        "repositories": [
            {
                "path": ".",
                "remote": [
                    "http://example.internal/demo.git",
                    "https://example.com/demo.git",
                ],
            }
        ],
    }

    text = gdeploy.render_manifest(manifest)
    parsed = ast.literal_eval(text.split("\n", 2)[2])

    assert parsed["repositories"][0]["remote"] == {
        "origin": [
            "http://example.internal/demo.git",
            "https://example.com/demo.git",
        ]
    }
    assert "'remote': [" not in text


def test_scan_workspace_uses_repo_walk(tmp_path):
    repo_path = tmp_path / "src" / "demo"
    repo_path.mkdir(parents=True)
    repo = make_repo(repo_path, "dev")
    repo.create_remote("origin", "https://example.com/demo.git")
    repo.create_remote("public", "https://github.com/example/demo.git")

    repositories = gdeploy.scan_workspace(str(tmp_path))

    assert repositories == [
        {
            "path": "src/demo",
            "type": "repository",
            "commit": repo.head.commit.hexsha,
            "describe": repo.git.describe("--tags", "--dirty", "--always"),
            "remote": {
                "origin": "https://example.com/demo.git",
                "public": "https://github.com/example/demo.git",
            },
            "branch": "dev",
        }
    ]

    assert gdeploy.scan_workspace(str(tmp_path), ["missing", "public"])[0]["remote"] == {
        "public": "https://github.com/example/demo.git"
    }


def test_scan_git_workspace_uses_workspace_name_for_root_repo(tmp_path):
    workspace = tmp_path / "FoneToolBackup"
    workspace.mkdir()
    repo = make_repo(workspace, "dev")
    repo.create_remote("origin", "https://example.com/FoneToolBackup.git")

    repositories = gdeploy.scan_workspace(str(workspace), ["origin"])

    assert repositories == [
        {
            "path": "FoneToolBackup",
            "type": "repository",
            "commit": repo.head.commit.hexsha,
            "describe": repo.git.describe("--tags", "--dirty", "--always"),
            "remote": {"origin": "https://example.com/FoneToolBackup.git"},
            "branch": "dev",
        }
    ]


def test_scan_bare_workspace_uses_workspace_name_for_root_repo(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    make_repo(source, "main")
    workspace = tmp_path / "Backup.git"
    git.Repo.clone_from(str(source), str(workspace), bare=True)

    repositories = gdeploy.scan_workspace(str(workspace))

    assert repositories[0]["path"] == "Backup.git"
    assert repositories[0]["mode"] == "bare"


def test_scan_workspace_warns_for_dirty_repository(tmp_path, capsys):
    repo_path = tmp_path / "demo"
    repo_path.mkdir()
    make_repo(repo_path, "main")
    (repo_path / "README.md").write_text("dirty\n", encoding="utf-8")

    repositories = gdeploy.scan_workspace(str(tmp_path))
    output = capsys.readouterr()

    assert repositories[0]["describe"].endswith("-dirty")
    assert "Warning: dirty repository: demo" in output.out


def test_scan_detached_head_keeps_manifest_branch_when_commit_is_branch_tip(tmp_path, monkeypatch, capsys):
    repo_path = tmp_path / "demo"
    repo_path.mkdir()
    repo = make_repo(repo_path, "main")
    repo.create_remote("origin", "https://example.com/demo.git")
    commit = repo.head.commit.hexsha
    repo.git.switch("--detach", commit)
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest({
        "variables": [],
        "repositories": [{
            "path": "demo", "remote": {"origin": "https://example.com/demo.git"},
            "branch": "main", "commit": commit,
        }],
    }), encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda: "y")

    assert gdeploy.update_manifest(str(tmp_path), str(manifest_file)) == 0

    repository = gdeploy.load_manifest(str(manifest_file))["repositories"][0]
    assert repository["path"] == "demo"
    assert repository["commit"] == commit
    assert repository["branch"] == "main"
    output = capsys.readouterr()
    assert f"Warning: detached HEAD: demo ({commit[:12]})" in output.err
    assert "skip detached branch" not in output.err


def test_scan_detached_head_keeps_manifest_branch_when_commit_is_ancestor(tmp_path, monkeypatch):
    repo_path = tmp_path / "demo"
    repo_path.mkdir()
    repo = make_repo(repo_path, "main")
    commit = repo.head.commit.hexsha
    (repo_path / "README.md").write_text("next\n", encoding="utf-8")
    repo.index.add(["README.md"])
    repo.index.commit("next")
    repo.git.switch("--detach", commit)
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest({
        "variables": [{"name": "TargetBranch", "value": "main"}],
        "repositories": [{"path": "demo", "branch": "{TargetBranch}", "commit": commit}],
    }), encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda: "y")

    assert gdeploy.update_manifest(str(tmp_path), str(manifest_file)) == 0
    repository = gdeploy.load_manifest(str(manifest_file))["repositories"][0]
    assert repository["branch"] == "{TargetBranch}"
    assert repository["commit"] == commit


def test_scan_detached_head_clears_manifest_branch_when_commit_is_unrelated(tmp_path, monkeypatch):
    repo_path = tmp_path / "demo"
    repo_path.mkdir()
    repo = make_repo(repo_path, "main")
    repo.git.switch("-c", "side")
    (repo_path / "README.md").write_text("side\n", encoding="utf-8")
    repo.index.add(["README.md"])
    repo.index.commit("side")
    commit = repo.head.commit.hexsha
    repo.git.switch("--detach", commit)
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest({
        "variables": [],
        "repositories": [{"path": "demo", "branch": "main", "commit": commit}],
    }), encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda: "y")

    assert gdeploy.update_manifest(str(tmp_path), str(manifest_file)) == 0
    repository = gdeploy.load_manifest(str(manifest_file))["repositories"][0]
    assert repository["branch"] is None
    assert repository["commit"] == commit


def test_scan_detached_head_checks_selected_remote_tracking_branch(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    make_repo(source, "main")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    repo = git.Repo.clone_from(str(source), str(workspace / "demo"))
    commit = repo.head.commit.hexsha
    repo.git.switch("--detach", commit)
    repo.git.branch("-D", "main")
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest({
        "variables": [],
        "repositories": [{"path": "demo", "branch": "main", "commit": commit,
                          "remote": {"origin": str(source)}}],
    }), encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda: "y")

    assert gdeploy.update_manifest(str(workspace), str(manifest_file)) == 0
    assert gdeploy.load_manifest(str(manifest_file))["repositories"][0]["branch"] == "main"


def test_scan_workspace_records_gitfile_submodule(tmp_path, capsys):
    parent = tmp_path / "parent"
    child = parent / "child"
    gitdir = parent / ".git" / "modules" / "child"
    child.mkdir(parents=True)
    make_repo(parent, "main")
    make_repo(child, "main")
    shutil.rmtree(gitdir, ignore_errors=True)
    gitdir.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(child / ".git"), str(gitdir))
    (child / ".git").write_text("gitdir: ../.git/modules/child\n", encoding="utf-8")

    repositories = gdeploy.scan_workspace(str(tmp_path))
    output = capsys.readouterr()

    assert [item["path"] for item in repositories] == ["parent", "parent/child"]
    assert repositories[0]["type"] == "repository"
    assert repositories[1]["type"] == "submodule"
    assert repositories[1]["parent"] == "parent"
    assert "Warning: found git submodule: parent/child" in output.out


def test_scan_workspace_records_archive_mirror_and_bare_modes(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    make_repo(source, "main")

    archive = tmp_path / "archive"
    archive.mkdir()
    git.Repo.clone_from(str(source), str(archive / ".git"), mirror=True)
    (archive / ".git" / "config.archive").write_text("[core]\n\tbare = false\n", encoding="utf-8")
    git.Repo.clone_from(str(source), str(tmp_path / "mirror.git"), mirror=True)
    git.Repo.clone_from(str(source), str(tmp_path / "bare.git"), bare=True)

    repositories = gdeploy.scan_workspace(str(tmp_path))
    by_path = {item["path"]: item for item in repositories}

    assert by_path["archive"]["mode"] == "archive"
    assert by_path["mirror.git"]["mode"] == "mirror"
    assert by_path["bare.git"]["mode"] == "bare"


def test_merge_repositories_keeps_archive_mode_after_checkout_scan():
    old = [
        {
            "path": "demo",
            "mode": "archive",
            "remote": {"origin": "https://example.com/demo.git"},
        }
    ]
    scanned = [
        {
            "path": "demo",
            "type": "repository",
            "commit": "new",
            "describe": "new",
            "remote": {"origin": "https://example.com/demo.git"},
            "branch": "main",
        }
    ]

    merged = gdeploy.merge_repositories(old, scanned)

    assert merged[0]["mode"] == "archive"


def test_select_remotes_defaults_to_origin_then_first_remote():
    assert gdeploy.select_remotes(
        {
            "mirror": "https://example.com/mirror.git",
            "origin": "https://example.com/origin.git",
        }
    ) == ["https://example.com/origin.git"]

    assert gdeploy.select_remotes(
        {
            "mirror": "https://example.com/mirror.git",
            "public": "https://example.com/public.git",
        }
    ) == ["https://example.com/mirror.git"]

    assert gdeploy.select_remotes(
        {
            "mirror": "https://example.com/mirror.git",
            "origin": "https://example.com/origin.git",
        },
        ["missing"],
    ) == ["https://example.com/mirror.git"]

    assert gdeploy.select_remotes(
        {
            "mirror": "https://example.com/mirror.git",
            "github": "https://example.com/github.git",
            "origin": "https://example.com/origin.git",
        },
        ["missing", "github", "origin"],
    ) == ["https://example.com/github.git"]


def test_merge_repositories_preserves_post_and_unscanned_items():
    old = [
        {
            "path": "demo",
            "remote": {"origin": "{Host}/demo.git"},
            "branch": "old",
            "post": "build",
        },
        {
            "path": "manual",
            "remote": {"origin": "https://example.com/manual.git"},
            "post": "manual",
        },
    ]
    scanned = [
        {
            "path": "demo",
            "type": "repository",
            "commit": "new",
            "describe": "new",
            "remote": {"origin": "https://example.com/demo.git"},
            "branch": "main",
        }
    ]

    merged = gdeploy.merge_repositories(old, scanned)

    assert merged == [
        {
            "path": "demo",
            "type": "repository",
            "commit": "new",
            "describe": "new",
            "remote": {"origin": "https://example.com/demo.git"},
            "branch": "main",
            "post": "build",
        },
        {
            "path": "manual",
            "remote": {"origin": "https://example.com/manual.git"},
            "post": "manual",
        },
    ]


def test_update_manifest_writes_only_after_confirmation(tmp_path, monkeypatch):
    repo_path = tmp_path / "demo"
    repo_path.mkdir()
    make_repo(repo_path, "main")
    manifest_file = tmp_path / "gdeploy.manifest"

    monkeypatch.setattr("builtins.input", lambda: "n")
    assert gdeploy.update_manifest(str(tmp_path), str(manifest_file)) == 1
    assert not manifest_file.exists()

    monkeypatch.setattr("builtins.input", lambda: "y")
    assert gdeploy.update_manifest(str(tmp_path), str(manifest_file)) == 0
    manifest = gdeploy.load_manifest(str(manifest_file))
    assert manifest["repositories"][0]["path"] == "demo"


def test_update_manifest_diff_ignores_existing_formatting(tmp_path, monkeypatch, capsys):
    repo_path = tmp_path / "demo"
    repo_path.mkdir()
    repo = make_repo(repo_path, "main")
    repo.create_remote("origin", "https://example.com/demo.git")
    commit = repo.head.commit.hexsha
    describe = repo.git.describe("--tags", "--dirty", "--always")
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(
        "{'variables': [], 'repositories': [{'path': 'demo', 'remote': {'origin': "
        f"'https://example.com/demo.git'}}, 'branch': 'main', 'commit': '{commit}', "
        f"'describe': '{describe}', 'type': 'repository'}}]}}\n",
        encoding="utf-8",
    )

    def fail_input():
        raise AssertionError("input should not be called when manifest has no diff")

    monkeypatch.setattr("builtins.input", fail_input)
    assert gdeploy.update_manifest(str(tmp_path), str(manifest_file)) == 0
    output = capsys.readouterr()

    assert "Manifest is up to date" in output.out
    assert "---" not in output.out
    assert "+++" not in output.out
    assert "@@" not in output.out


def test_update_manifest_listed_only_does_not_add_new_repositories(tmp_path, monkeypatch):
    listed = tmp_path / "listed"
    extra = tmp_path / "extra"
    listed.mkdir()
    extra.mkdir()
    listed_repo = make_repo(listed, "main")
    listed_repo.create_remote("origin", "https://example.com/listed.git")
    make_repo(extra, "main")

    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(
        gdeploy.render_manifest(
            {
                "variables": [],
                "repositories": [
                    {
                        "path": "listed",
                        "type": "repository",
                        "remote": {"origin": "https://old.example.com/listed.git"},
                        "branch": "old",
                        "post": "build",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("builtins.input", lambda: "y")
    assert gdeploy.update_manifest(
        str(tmp_path), str(manifest_file), listed_only=True, sync_remotes=True,
    ) == 0
    manifest = gdeploy.load_manifest(str(manifest_file))

    assert [item["path"] for item in manifest["repositories"]] == ["listed"]
    assert manifest["repositories"][0]["branch"] == "main"
    assert manifest["repositories"][0]["commit"] == listed_repo.head.commit.hexsha
    assert manifest["repositories"][0]["remote"] == {"origin": "https://example.com/listed.git"}
    assert manifest["repositories"][0]["post"] == "build"


@pytest.mark.parametrize("answer", ["y", "n"])
def test_scan_remote_name_conflict_keeps_or_updates_manifest(tmp_path, monkeypatch, capsys, answer):
    repo_path = tmp_path / "demo"
    repo_path.mkdir()
    repo = make_repo(repo_path, "main")
    url = "https://example.com/demo.git"
    repo.create_remote("origin", url)
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest({
        "variables": [],
        "repositories": [{
            "path": "demo", "remote": {"github": url}, "branch": "old", "post": "build",
        }],
    }), encoding="utf-8")
    prompts = []
    answers = iter([answer, "y"])
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", lambda prompt="": prompts.append(prompt) or next(answers))

    assert gdeploy.update_manifest(str(tmp_path), str(manifest_file)) == 0

    updated = gdeploy.load_manifest(str(manifest_file))["repositories"][0]
    assert updated["remote"] == ({"origin": url} if answer == "y" else {"github": url})
    assert updated["branch"] == "main"
    assert updated["commit"] == repo.head.commit.hexsha
    assert updated["post"] == "build"
    assert {remote.name for remote in repo.remotes} == {"origin"}
    assert prompts == ["Update manifest remotes for demo? [y/N] ", ""]
    output = capsys.readouterr().out
    assert "Remote differs in demo" in output
    assert "github -> https://example.com/demo.git" in output
    assert "origin -> https://example.com/demo.git" in output


def test_scan_remote_conflict_requires_approval_without_tty(tmp_path, monkeypatch, capsys):
    repo_path = tmp_path / "demo"
    repo_path.mkdir()
    repo = make_repo(repo_path)
    repo.create_remote("origin", "https://example.com/local.git")
    manifest_file = tmp_path / "gdeploy.manifest"
    original = gdeploy.render_manifest({
        "variables": [],
        "repositories": [{"path": "demo", "remote": {"origin": "https://example.com/old.git"}}],
    })
    manifest_file.write_text(original, encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: False))

    assert gdeploy.update_manifest(str(tmp_path), str(manifest_file)) == 1
    assert manifest_file.read_text(encoding="utf-8") == original
    output = capsys.readouterr()
    assert "Remote differs in demo" in output.out
    assert "use --sync-remotes" in output.err


def test_scan_sync_remotes_still_confirms_manifest_write(tmp_path, monkeypatch):
    repo_path = tmp_path / "demo"
    repo_path.mkdir()
    repo = make_repo(repo_path)
    repo.create_remote("origin", "https://example.com/local.git")
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest({
        "variables": [],
        "repositories": [{"path": "demo", "remote": {"origin": "https://example.com/old.git"}}],
    }), encoding="utf-8")
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt="": prompts.append(prompt) or "n")
    monkeypatch.setattr(sys, "argv", [
        "gdeploy", "--scan", "--sync-remotes", "-d", str(tmp_path), str(manifest_file),
    ])

    assert gdeploy.main() == 1
    assert prompts == [""]
    assert gdeploy.load_manifest(str(manifest_file))["repositories"][0]["remote"] == {
        "origin": "https://example.com/old.git"
    }


def test_scan_preserves_variable_remote_when_resolved_url_matches(tmp_path, monkeypatch, capsys):
    repo_path = tmp_path / "demo"
    repo_path.mkdir()
    repo = make_repo(repo_path)
    repo.create_remote("origin", "https://example.com/demo.git")
    manifest_file = tmp_path / "gdeploy.manifest"
    scanned = gdeploy.scan_workspace(str(tmp_path))[0]
    scanned["remote"] = {"origin": ["https://backup.invalid/demo.git", "{Host}/demo.git"]}
    manifest_file.write_text(gdeploy.render_manifest({
        "variables": [{"name": "Host", "value": "https://example.com"}],
        "repositories": [scanned],
    }), encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("unexpected prompt"))

    assert gdeploy.update_manifest(str(tmp_path), str(manifest_file)) == 0
    assert gdeploy.load_manifest(str(manifest_file))["repositories"][0]["remote"] == {
        "origin": ["https://backup.invalid/demo.git", "{Host}/demo.git"]
    }
    assert "Manifest is up to date" in capsys.readouterr().out


def test_deploy_manifest_clones_missing_repository(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    make_repo(source, "main")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest = {
        "variables": [],
        "repositories": [
            {
                "path": "demo",
                "remote": {"origin": [str(tmp_path / "missing"), str(source)]},
                "branch": "main",
                "post": f'"{sys.executable}" -c "from pathlib import Path; Path(\'post.txt\').write_text(\'ok\')"',
            }
        ],
    }
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest(manifest), encoding="utf-8")

    assert gdeploy.deploy_manifest(str(workspace), str(manifest_file)) == 0
    assert (workspace / "demo" / ".git").exists()
    assert (workspace / "demo" / "post.txt").read_text() == "ok"
    assert git.Repo(workspace / "demo").active_branch.name == "main"


def test_deploy_manifest_clones_named_root_repository_by_default(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    make_repo(source, "main")

    workspace = tmp_path / "deploy"
    manifest = {
        "variables": [],
        "repositories": [
            {
                "path": "FoneToolBackup",
                "remote": {"origin": str(source)},
                "branch": "main",
            }
        ],
    }
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest(manifest), encoding="utf-8")

    assert gdeploy.deploy_manifest(str(workspace), str(manifest_file)) == 0
    assert (workspace / "FoneToolBackup" / ".git").exists()


def test_deploy_manifest_can_clone_root_repository_here(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    make_repo(source, "main")

    workspace = tmp_path / "FoneToolBackup"
    workspace.mkdir()
    manifest = {
        "variables": [],
        "repositories": [
            {
                "path": "FoneToolBackup",
                "remote": {"origin": str(source)},
                "branch": "main",
            }
        ],
    }
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest(manifest), encoding="utf-8")

    assert gdeploy.deploy_manifest(str(workspace), str(manifest_file), here=True) == 0
    assert (workspace / ".git").exists()


def test_deploy_manifest_can_checkout_manifest_commit(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    repo = make_repo(source, "main")
    first_commit = repo.head.commit.hexsha
    (source / "README.md").write_text("updated\n", encoding="utf-8")
    repo.index.add(["README.md"])
    repo.index.commit("second")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest = {
        "variables": [],
        "repositories": [
            {
                "path": "demo",
                "remote": {"origin": str(source)},
                "branch": "main",
                "commit": first_commit,
            }
        ],
    }
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest(manifest), encoding="utf-8")

    assert gdeploy.deploy_manifest(
        str(workspace),
        str(manifest_file),
        checkout_to_commit=True,
    ) == 0
    deployed = git.Repo(workspace / "demo")
    assert deployed.head.commit.hexsha == first_commit


def test_deploy_manifest_detaches_without_moving_branch(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    repo = make_repo(source, "main")
    first_commit = repo.head.commit.hexsha
    (source / "README.md").write_text("updated\n", encoding="utf-8")
    repo.index.add(["README.md"])
    repo.index.commit("second")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest = {
        "variables": [],
        "repositories": [
            {
                "path": "demo",
                "remote": {"origin": str(source)},
                "branch": "main",
                "commit": first_commit,
            }
        ],
    }
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest(manifest), encoding="utf-8")

    assert gdeploy.deploy_manifest(
        str(workspace),
        str(manifest_file),
        checkout_to_commit=True,
    ) == 0

    deployed = git.Repo(workspace / "demo")
    assert deployed.head.commit.hexsha == first_commit
    assert deployed.head.is_detached == True
    assert deployed.heads.main.commit.hexsha == repo.head.commit.hexsha


def test_deploy_manifest_detaches_when_commit_not_on_branch(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    repo = make_repo(source, "main")
    (source / "README.md").write_text("second\n", encoding="utf-8")
    repo.index.add(["README.md"])
    repo.index.commit("second")
    orphan = repo.create_head("orphan")
    orphan.checkout()
    (source / "README.md").write_text("orphan\n", encoding="utf-8")
    repo.index.add(["README.md"])
    repo.index.commit("orphan")
    orphan_commit = repo.head.commit.hexsha
    repo.git.checkout("main")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest = {
        "variables": [],
        "repositories": [
            {
                "path": "demo",
                "remote": {"origin": str(source)},
                "branch": "main",
                "commit": orphan_commit,
            }
        ],
    }
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest(manifest), encoding="utf-8")

    assert gdeploy.deploy_manifest(
        str(workspace),
        str(manifest_file),
        checkout_to_commit=True,
    ) == 0

    deployed = git.Repo(workspace / "demo")
    assert deployed.head.commit.hexsha == orphan_commit
    assert deployed.head.is_detached == True


def test_deploy_manifest_fails_when_commit_missing(tmp_path, capsys):
    source = tmp_path / "source"
    source.mkdir()
    repo = make_repo(source, "main")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest = {
        "variables": [],
        "repositories": [
            {
                "path": "demo",
                "remote": {"origin": str(source)},
                "branch": "main",
                "commit": "0" * 40,
            }
        ],
    }
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest(manifest), encoding="utf-8")

    assert gdeploy.deploy_manifest(
        str(workspace), str(manifest_file), checkout_to_commit=True
    ) == 1

    deployed = git.Repo(workspace / "demo")
    assert deployed.head.commit.hexsha == repo.head.commit.hexsha
    assert "Manifest commit not found" in capsys.readouterr().err


def test_deploy_existing_remote_requires_approval_and_can_sync(tmp_path, capsys):
    source = tmp_path / "source"
    source.mkdir()
    make_repo(source, "main")
    replacement = tmp_path / "replacement"
    replacement_repo = git.Repo.clone_from(str(source), str(replacement))
    with replacement_repo.config_writer() as config:
        config.set_value("user", "name", "test")
        config.set_value("user", "email", "test@example.com")
    (replacement / "README.md").write_text("replacement\n", encoding="utf-8")
    replacement_repo.index.add(["README.md"])
    replacement_repo.index.commit("replacement")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "demo"
    deployed = git.Repo.clone_from(str(source), str(target))
    original_commit = deployed.head.commit.hexsha
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest({
        "variables": [],
        "repositories": [{
            "path": "demo", "remote": {"origin": str(replacement)}, "branch": "main",
        }],
    }), encoding="utf-8")

    assert gdeploy.deploy_manifest(str(workspace), str(manifest_file)) == 1
    assert deployed.head.commit.hexsha == original_commit
    output = capsys.readouterr()
    assert "Remote 'origin' URL differs in demo" in output.out
    assert f"  Manifest: origin -> {replacement}" in output.out
    assert "  Existing: origin -> " in output.out
    assert "Remote differs" in output.err

    assert gdeploy.deploy_manifest(
        str(workspace), str(manifest_file), sync_remotes=True,
    ) == 0
    assert deployed.head.commit.hexsha == replacement_repo.head.commit.hexsha
    assert deployed.git.config("--get", "remote.origin.url").replace("\\", "/") == str(replacement).replace("\\", "/")


def test_remote_sync_accepts_interactive_confirmation(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    make_repo(source)
    target = tmp_path / "target"
    repo = git.Repo.clone_from(str(source), str(target))
    expected = str(tmp_path / "replacement")
    assert gdeploy.ensure_manifest_remote(repo, "origin", [expected, str(source)]) == "origin"
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or "y")

    assert gdeploy.ensure_manifest_remote(repo, "origin", [expected]) == "origin"
    assert prompts == ["Update remote 'origin'? [y/N] "]
    assert repo.git.config("--get", "remote.origin.url").replace("\\", "/") == expected.replace("\\", "/")


@pytest.mark.parametrize("mirror", [False, True])
def test_remote_sync_creates_missing_named_remote(tmp_path, mirror):
    source = tmp_path / "source"
    source.mkdir()
    make_repo(source)
    target = tmp_path / "target"
    repo = git.Repo.clone_from(str(source), str(target), mirror=mirror)
    assert gdeploy.ensure_manifest_remote(repo, "github", [str(source)], sync_remotes=True) == "github"
    assert {remote.name for remote in repo.remotes} == {"origin", "github"}
    assert repo.git.config("--get", "remote.origin.url").replace("\\", "/") == repo.git.config("--get", "remote.github.url").replace("\\", "/")
    if mirror:
        assert gdeploy.bool_config(repo, 'remote "github"', "mirror") == True


def test_deploy_requires_selected_remote_name_even_when_url_matches(tmp_path, monkeypatch, capsys):
    source = tmp_path / "source"
    source.mkdir()
    source_repo = make_repo(source, "dev")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "demo"
    deployed = git.Repo.clone_from(str(source), str(target))
    (source / "README.md").write_text("next\n", encoding="utf-8")
    source_repo.index.add(["README.md"])
    source_repo.index.commit("next")
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest({
        "variables": [],
        "repositories": [{
            "path": "demo", "remote": {"github": str(source)}, "branch": "dev",
        }],
    }), encoding="utf-8")

    original_commit = deployed.head.commit.hexsha
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: False))
    assert gdeploy.deploy_manifest(str(workspace), str(manifest_file)) == 1
    output = capsys.readouterr()
    source_url = str(source).replace("\\", "/")
    assert "Manifest remote 'github' is missing in demo" in output.out
    assert f"  Manifest: github -> {source}" in output.out
    assert f"  Existing: origin -> {source_url} (same fetch URL)" in output.out
    assert "Remote github is missing" in output.err
    assert deployed.head.commit.hexsha == original_commit
    assert [remote.name for remote in deployed.remotes] == ["origin"]

    assert gdeploy.deploy_manifest(str(workspace), str(manifest_file), sync_remotes=True) == 0
    assert deployed.head.commit.hexsha == source_repo.head.commit.hexsha
    assert {remote.name for remote in deployed.remotes} == {"origin", "github"}
    assert deployed.git.config("--get", "remote.origin.url").replace("\\", "/") == deployed.git.config("--get", "remote.github.url").replace("\\", "/")


def test_missing_named_remote_accepts_interactive_confirmation(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    make_repo(source)
    repo = git.Repo.clone_from(str(source), str(tmp_path / "target"))
    prompts = []
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or "y")

    assert gdeploy.ensure_manifest_remote(repo, "github", [str(source)]) == "github"
    assert prompts == ["Add remote 'github'? [y/N] "]
    assert {remote.name for remote in repo.remotes} == {"origin", "github"}


def test_missing_named_remote_lists_all_existing_remotes(tmp_path, monkeypatch, capsys):
    source = tmp_path / "source"
    source.mkdir()
    make_repo(source)
    repo = git.Repo.clone_from(str(source), str(tmp_path / "target"))
    repo.create_remote("backup", "https://example.invalid/backup.git")
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: False))

    with pytest.raises(RuntimeError, match="Remote github is missing"):
        gdeploy.ensure_manifest_remote(repo, "github", [str(source)], display_path="com/pyembed")

    output = capsys.readouterr().out
    source_url = str(source).replace("\\", "/")
    assert "Manifest remote 'github' is missing in com/pyembed" in output
    assert f"  Manifest: github -> {source}" in output
    assert "  Existing:\n" in output
    assert f"    origin -> {source_url} (same fetch URL)" in output
    assert "    backup -> https://example.invalid/backup.git" in output


def test_named_remote_mismatch_still_requires_confirmation(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    make_repo(source)
    repo = git.Repo.clone_from(str(source), str(tmp_path / "target"))
    repo.create_remote("github", "https://example.invalid/other.git")
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: False))

    with pytest.raises(RuntimeError, match="Remote differs"):
        gdeploy.ensure_manifest_remote(repo, "github", [str(source)])
    assert {remote.name for remote in repo.remotes} == {"origin", "github"}


def test_deploy_fast_forwards_branch_without_upstream(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    source_repo = make_repo(source, "ft")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "demo"
    deployed = git.Repo.clone_from(str(source), str(target))
    deployed.git.branch("--unset-upstream", "ft")

    (source / "README.md").write_text("next\n", encoding="utf-8")
    source_repo.index.add(["README.md"])
    source_repo.index.commit("next")
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest({
        "variables": [],
        "repositories": [{
            "path": "demo", "remote": {"origin": str(source)}, "branch": "ft",
        }],
    }), encoding="utf-8")

    assert gdeploy.deploy_manifest(str(workspace), str(manifest_file)) == 0
    assert deployed.head.commit.hexsha == source_repo.head.commit.hexsha
    assert deployed.active_branch.name == "ft"


def test_deploy_divergent_branch_preserves_local_commits(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    source_repo = make_repo(source, "main")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "demo"
    deployed = git.Repo.clone_from(str(source), str(target))
    with deployed.config_writer() as config:
        config.set_value("user", "name", "test")
        config.set_value("user", "email", "test@example.com")

    (target / "README.md").write_text("local\n", encoding="utf-8")
    deployed.index.add(["README.md"])
    local_commit = deployed.index.commit("local").hexsha
    (source / "README.md").write_text("remote\n", encoding="utf-8")
    source_repo.index.add(["README.md"])
    source_repo.index.commit("remote")
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest({
        "variables": [],
        "repositories": [{
            "path": "demo", "remote": {"origin": str(source)}, "branch": "main",
            "commit": source_repo.head.commit.hexsha,
        }],
    }), encoding="utf-8")

    assert gdeploy.deploy_manifest(str(workspace), str(manifest_file)) == 1
    assert deployed.head.commit.hexsha == local_commit
    assert deployed.head.is_detached == False


def test_deploy_snapshot_skips_merge_and_updates_submodules_after_checkout(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    source_repo = make_repo(source, "main")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "demo"
    deployed = git.Repo.clone_from(str(source), str(target))
    with deployed.config_writer() as config:
        config.set_value("user", "name", "test")
        config.set_value("user", "email", "test@example.com")

    (target / "README.md").write_text("local\n", encoding="utf-8")
    deployed.index.add(["README.md"])
    local_commit = deployed.index.commit("local").hexsha
    (source / "README.md").write_text("remote\n", encoding="utf-8")
    source_repo.index.add(["README.md"])
    source_repo.index.commit("remote")
    wanted = source_repo.head.commit.hexsha
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest({
        "variables": [],
        "repositories": [{
            "path": "demo", "remote": {"origin": str(source)},
            "branch": "main", "commit": wanted,
        }],
    }), encoding="utf-8")
    submodule_heads = []
    monkeypatch.setattr(gdeploy, "update_submodules", lambda repo: submodule_heads.append(repo.head.commit.hexsha))

    assert gdeploy.deploy_manifest(
        str(workspace), str(manifest_file), checkout_to_commit=True,
    ) == 0
    assert deployed.head.is_detached == True
    assert deployed.head.commit.hexsha == wanted
    assert deployed.heads.main.commit.hexsha == local_commit
    assert submodule_heads == [wanted]


def test_deploy_snapshot_requires_manifest_commit(tmp_path, capsys):
    source = tmp_path / "source"
    source.mkdir()
    make_repo(source)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "demo"
    deployed = git.Repo.clone_from(str(source), str(target))
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest({
        "variables": [],
        "repositories": [{"path": "demo", "remote": {"origin": str(source)}}],
    }), encoding="utf-8")

    assert gdeploy.deploy_manifest(
        str(workspace), str(manifest_file), checkout_to_commit=True,
    ) == 1
    assert deployed.head.is_detached == False
    assert "Manifest commit is missing" in capsys.readouterr().err


def test_clone_uses_selected_remote_name_on_later_updates(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    make_repo(source, "main")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest({
        "variables": [],
        "repositories": [{
            "path": "demo", "remote": {"github": str(source)}, "branch": "main",
        }],
    }), encoding="utf-8")

    assert gdeploy.deploy_manifest(str(workspace), str(manifest_file)) == 0
    assert [remote.name for remote in git.Repo(workspace / "demo").remotes] == ["github"]
    assert gdeploy.deploy_manifest(str(workspace), str(manifest_file)) == 0


def test_deploy_manifest_handles_existing_mirror_without_mode(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    make_repo(source, "main")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "demo"
    target.mkdir()
    git.Repo.clone_from(str(source), str(target / ".git"), mirror=True)

    manifest = {
        "variables": [],
        "repositories": [
            {"path": "demo", "remote": {"origin": str(source)}, "branch": "main"}
        ],
    }
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest(manifest), encoding="utf-8")

    assert gdeploy.deploy_manifest(str(workspace), str(manifest_file)) == 0
    assert git.Repo(target / ".git").bare == True


def test_deploy_manifest_clones_archive_without_checkout_or_post(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    make_repo(source, "main")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest = {
        "variables": [],
        "repositories": [
            {
                "path": "backup",
                "mode": "archive",
                "remote": {"origin": str(source)},
                "branch": "main",
                "post": f'"{sys.executable}" -c "from pathlib import Path; Path(\'post.txt\').write_text(\'ok\')"',
            }
        ],
    }
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest(manifest), encoding="utf-8")

    assert gdeploy.deploy_manifest(str(workspace), str(manifest_file)) == 0
    repo = git.Repo(workspace / "backup" / ".git")

    assert repo.bare == True
    assert gdeploy.bool_config(repo, 'remote "origin"', "mirror") == True
    assert not (workspace / "backup" / "README.md").exists()
    assert not (workspace / "backup" / "post.txt").exists()


def test_deploy_manifest_checkouts_archive_and_runs_post(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    make_repo(source, "main")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest = {
        "variables": [],
        "repositories": [
            {
                "path": "backup",
                "mode": "archive",
                "remote": {"origin": str(source)},
                "branch": "main",
                "post": f'"{sys.executable}" -c "from pathlib import Path; Path(\'post.txt\').write_text(\'ok\')"',
            }
        ],
    }
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest(manifest), encoding="utf-8")

    assert gdeploy.deploy_manifest(
        str(workspace),
        str(manifest_file),
        checkout_archive=True,
    ) == 0

    assert git.Repo(workspace / "backup").bare == False
    assert (workspace / "backup" / "README.md").read_text(encoding="utf-8") == "test\n"
    assert (workspace / "backup" / "post.txt").read_text() == "ok"

    (workspace / "backup" / "post.txt").unlink()
    calls = []
    monkeypatch.setattr(gdeploy, "run_post_commands", lambda commands, directory: calls.append(directory) or True)
    assert gdeploy.deploy_manifest(
        str(workspace), str(manifest_file), checkout_archive=True,
    ) == 0
    assert calls == [str(workspace / "backup")]


def test_deploy_manifest_checkouts_archive_to_commit(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    repo = make_repo(source, "main")
    first_commit = repo.head.commit.hexsha
    (source / "README.md").write_text("updated\n", encoding="utf-8")
    repo.index.add(["README.md"])
    repo.index.commit("second")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest = {
        "variables": [],
        "repositories": [
            {
                "path": "backup",
                "mode": "archive",
                "remote": {"origin": str(source)},
                "commit": first_commit,
            }
        ],
    }
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest(manifest), encoding="utf-8")

    assert gdeploy.deploy_manifest(
        str(workspace),
        str(manifest_file),
        checkout_to_commit=True,
        checkout_archive=True,
    ) == 0

    assert git.Repo(workspace / "backup").head.commit.hexsha == first_commit


def test_deploy_manifest_clones_mirror_and_bare_modes(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    make_repo(source, "main")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest = {
        "variables": [],
        "repositories": [
            {
                "path": "mirror.git",
                "mode": "mirror",
                "remote": {"origin": str(source)},
            },
            {
                "path": "bare.git",
                "mode": "bare",
                "remote": {"origin": str(source)},
            },
        ],
    }
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest(manifest), encoding="utf-8")

    assert gdeploy.deploy_manifest(str(workspace), str(manifest_file)) == 0
    mirror = git.Repo(workspace / "mirror.git")
    bare = git.Repo(workspace / "bare.git")

    assert mirror.bare == True
    assert bare.bare == True
    assert gdeploy.bool_config(mirror, 'remote "origin"', "mirror") == True
    assert gdeploy.bool_config(bare, 'remote "origin"', "mirror") == False


@pytest.mark.parametrize("mode", ["archive", "mirror", "bare"])
def test_non_worktree_modes_keep_selected_remote_name(tmp_path, mode):
    source = tmp_path / "source"
    source.mkdir()
    make_repo(source, "main")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest({
        "variables": [],
        "repositories": [{
            "path": "demo", "mode": mode, "remote": {"github": str(source)},
        }],
    }), encoding="utf-8")

    assert gdeploy.deploy_manifest(str(workspace), str(manifest_file)) == 0
    repo_path = workspace / "demo" / ".git" if mode == "archive" else workspace / "demo"
    assert [remote.name for remote in git.Repo(repo_path).remotes] == ["github"]
    assert gdeploy.deploy_manifest(str(workspace), str(manifest_file)) == 0


def test_deploy_manifest_skips_checkout_for_mirror_and_bare(tmp_path, capsys):
    source = tmp_path / "source"
    source.mkdir()
    make_repo(source, "main")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest = {
        "variables": [],
        "repositories": [
            {
                "path": "mirror.git",
                "mode": "mirror",
                "remote": {"origin": str(source)},
            }
        ],
    }
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest(manifest), encoding="utf-8")

    assert gdeploy.deploy_manifest(
        str(workspace),
        str(manifest_file),
        checkout_archive=True,
    ) == 0
    output = capsys.readouterr()

    assert "Skip checkout for mirror repository: mirror.git" in output.out
    assert git.Repo(workspace / "mirror.git").bare == True


def test_deploy_manifest_skips_submodule_entries(tmp_path, capsys):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest = {
        "variables": [],
        "repositories": [
            {
                "path": "parent/child",
                "type": "submodule",
                "parent": "parent",
                "remote": {"origin": "https://example.com/child.git"},
            }
        ],
    }
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest(manifest), encoding="utf-8")

    assert gdeploy.deploy_manifest(str(workspace), str(manifest_file)) == 0
    output = capsys.readouterr()

    assert "Skip submodule: parent/child (managed by parent)" in output.out
    assert not (workspace / "parent").exists()


def test_update_submodules_runs_when_repository_has_submodules(tmp_path):
    calls = []
    repo = SimpleNamespace(
        submodules=[object()],
        working_dir=str(tmp_path),
        git=SimpleNamespace(submodule=lambda *args: calls.append(args)),
    )

    gdeploy.update_submodules(repo)

    assert calls == [("update", "--init", "--recursive")]


def test_update_submodules_skips_when_repository_has_no_submodules(tmp_path):
    calls = []
    repo = SimpleNamespace(
        submodules=[],
        working_dir=str(tmp_path),
        git=SimpleNamespace(submodule=lambda *args: calls.append(args)),
    )

    gdeploy.update_submodules(repo)

    assert calls == []


def test_deploy_manifest_fails_for_existing_non_git_directory(tmp_path):
    workspace = tmp_path / "workspace"
    target = workspace / "demo"
    target.mkdir(parents=True)
    manifest = {
        "variables": [],
        "repositories": [
            {
                "path": "demo",
                "remote": {"origin": "https://example.com/demo.git"},
            }
        ],
    }
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest(manifest), encoding="utf-8")

    assert gdeploy.deploy_manifest(str(workspace), str(manifest_file)) == 1


def test_run_git_command_terminates_child_on_keyboard_interrupt(monkeypatch):
    calls = []

    class Process:
        returncode = None

        def poll(self):
            return None

        def send_signal(self, value):
            calls.append(("signal", value))
            self.returncode = 130

        def terminate(self):
            calls.append(("terminate",))
            self.returncode = 130

        def wait(self, timeout=None):
            calls.append(("wait", timeout))
            return self.returncode

        def kill(self):
            calls.append(("kill",))
            self.returncode = 130

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(gdeploy.time, "sleep", lambda seconds: (_ for _ in ()).throw(KeyboardInterrupt()))

    with pytest.raises(KeyboardInterrupt):
        gdeploy.run_git_command(["clone", "remote", "target"])

    assert ("wait", 3) in calls
    assert ("kill",) not in calls


def test_main_returns_130_on_keyboard_interrupt(tmp_path, monkeypatch, capsys):
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest({"variables": [], "repositories": []}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["gdeploy", str(manifest_file)])
    monkeypatch.setattr(gdeploy, "deploy_manifest", lambda *args, **kwargs: (_ for _ in ()).throw(KeyboardInterrupt()))

    assert gdeploy.main() == 130
    output = capsys.readouterr()

    assert "Interrupted" in output.err
