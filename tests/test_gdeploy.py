import ast
import os
import shutil
import sys
from types import SimpleNamespace

import git

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
    assert gdeploy.update_manifest(str(tmp_path), str(manifest_file), listed_only=True) == 0
    manifest = gdeploy.load_manifest(str(manifest_file))

    assert [item["path"] for item in manifest["repositories"]] == ["listed"]
    assert manifest["repositories"][0]["branch"] == "main"
    assert manifest["repositories"][0]["commit"] == listed_repo.head.commit.hexsha
    assert manifest["repositories"][0]["remote"] == {"origin": "https://example.com/listed.git"}
    assert manifest["repositories"][0]["post"] == "build"


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


def test_deploy_manifest_checkouts_archive_and_runs_post(tmp_path):
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
