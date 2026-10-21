import copy
import git
import pytest

from gwalk import gdeploy


def make_repo(path):
    path.mkdir(parents=True)
    repo = git.Repo.init(path)
    with repo.config_writer() as config:
        config.set_value("user", "name", "test")
        config.set_value("user", "email", "test@example.com")
    (path / "README.md").write_text("initial\n", encoding="utf-8")
    repo.index.add(["README.md"])
    repo.index.commit("initial")
    repo.git.branch("-M", "main")
    return repo


def test_upgrade_is_pure_and_preserves_repository_data():
    legacy = {"variables": [{"name": "Host", "value": "https://example.com"}], "extra": "keep",
              "repositories": [
                  {"path": "projects/FoneTool", "branch": "dev", "commit": None,
                   "remote": {"origin": "{Host}/{RepositoryName}.git"}, "post": "build", "mode": "archive"},
                  {"path": "projects/FoneTool/bin", "describe": "v1"},
                  {"path": "projects/FoneTool/bin/child", "type": "submodule", "parent": "projects/FoneTool/bin"},
                  {"path": "projects/FoneTool/child", "type": "submodule", "parent": "projects/FoneTool"},
              ]}
    original = copy.deepcopy(legacy)

    upgraded = gdeploy.upgrade_manifest(legacy)

    assert legacy == original
    assert upgraded["schema_version"] == 1
    assert upgraded["name"] == "FoneTool"
    assert [item["path"] for item in upgraded["repositories"]] == [".", "bin", "bin/child", "child"]
    assert upgraded["repositories"][2]["parent"] == "bin"
    assert upgraded["repositories"][3]["parent"] == "."
    assert upgraded["repositories"][0] == {**original["repositories"][0], "path": "."}
    assert upgraded["extra"] == "keep"
    assert gdeploy.upgrade_manifest(upgraded) == upgraded


def test_upgrade_already_relative_legacy_manifest():
    upgraded = gdeploy.upgrade_manifest({"repositories": [{"path": "."}, {"path": "bin"}]}, "Project")
    assert upgraded["name"] == "Project"
    assert [item["path"] for item in upgraded["repositories"]] == [".", "bin"]


@pytest.mark.parametrize("version", [2, -1, True, "1", None])
def test_upgrade_rejects_unsupported_schema(version):
    with pytest.raises(RuntimeError, match="schema version"):
        gdeploy.upgrade_manifest({"schema_version": version, "name": "Project", "repositories": []})


@pytest.mark.parametrize("paths", [["First", "Second"], ["Project/bin", "Project/include"]])
def test_upgrade_rejects_ambiguous_legacy_root(paths):
    with pytest.raises(RuntimeError, match="legacy manifest root"):
        gdeploy.upgrade_manifest({"repositories": [{"path": path} for path in paths]}, "Project")


@pytest.mark.parametrize("value", ["{RepositoryPath}", "echo {Workspace}"])
def test_upgrade_rejects_changed_template_meaning(value):
    legacy = {"repositories": [{"path": "Project", "post": value}]}
    original = copy.deepcopy(legacy)
    with pytest.raises(RuntimeError, match="path-dependent variables"):
        gdeploy.upgrade_manifest(legacy)
    assert legacy == original


@pytest.mark.parametrize("name", [None, "", ".", "..", "a/b", "a\\b", "C:drive", "trailing."])
def test_schema_validates_project_name(name):
    with pytest.raises(RuntimeError, match="project directory name"):
        gdeploy.upgrade_manifest({"schema_version": 1, "name": name})


@pytest.mark.parametrize("path", ["../outside", "/absolute", "C:/absolute"])
def test_schema_validates_project_relative_paths(path):
    with pytest.raises(RuntimeError, match="relative to the project"):
        gdeploy.upgrade_manifest({"schema_version": 1, "name": "Project", "repositories": [{"path": path}]})


def test_root_variables_use_project_name_and_relative_path(tmp_path):
    manifest = {"schema_version": 1, "name": "FoneTool"}
    assert gdeploy.replace_variables("{RepositoryName}|{RepositoryPath}|{Workspace}", manifest,
                                     {"path": "."}, str(tmp_path)) == f"FoneTool|.|{tmp_path}"


def test_scan_upgrade_writes_only_after_confirmation(tmp_path, monkeypatch, capsys):
    workspace = tmp_path / "CustomBackup"
    make_repo(workspace)
    make_repo(workspace / "bin")
    manifest_file = tmp_path / "gdeploy.manifest"
    original = "# Keep this comment in the backup\n" + gdeploy.render_manifest({
        "variables": [], "repositories": [{"path": "FoneTool"}, {"path": "FoneTool/bin"}]
    })
    manifest_file.write_text(original, encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda: "n")

    assert gdeploy.update_manifest(str(workspace), str(manifest_file), listed_only=True) == 1
    assert manifest_file.read_text(encoding="utf-8") == original
    assert not list(tmp_path.glob("*.backup.*"))
    output = capsys.readouterr().out
    assert "+{'schema_version': 1" in output
    assert "FoneTool/bin" in output

    monkeypatch.setattr("builtins.input", lambda: "y")
    assert gdeploy.update_manifest(str(workspace), str(manifest_file), listed_only=True) == 0
    upgraded = gdeploy.load_manifest(str(manifest_file))
    assert upgraded["name"] == "FoneTool"
    assert [item["path"] for item in upgraded["repositories"]] == [".", "bin"]
    backups = list(tmp_path.glob("*.backup.*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == original
    saved = manifest_file.read_bytes()
    monkeypatch.setattr("builtins.input", lambda: pytest.fail("unexpected prompt"))
    assert gdeploy.update_manifest(str(workspace), str(manifest_file), listed_only=True) == 0
    assert manifest_file.read_bytes() == saved
    assert list(tmp_path.glob("*.backup.*")) == backups


@pytest.mark.parametrize("here", [False, True])
def test_deploy_legacy_manifest_does_not_write_upgrade(tmp_path, here):
    source = tmp_path / "source"
    make_repo(source)
    workspace = tmp_path / "CustomBackup"
    manifest_file = tmp_path / "gdeploy.manifest"
    original = gdeploy.render_manifest({"repositories": [
        {"path": "FoneTool", "remote": {"origin": str(source)}, "branch": "main"}
    ]})
    manifest_file.write_text(original, encoding="utf-8")

    assert gdeploy.deploy_manifest(str(workspace), str(manifest_file), here=here) == 0
    target = workspace if here else workspace / "FoneTool"
    assert git.Repo(target).active_branch.name == "main"
    assert manifest_file.read_text(encoding="utf-8") == original
    assert not list(tmp_path.glob("*.backup.*"))


@pytest.mark.parametrize("here", [False, True])
def test_schema_round_trip_root_and_bin_in_custom_directory(tmp_path, monkeypatch, here):
    root_source = tmp_path / "sources" / "FoneTool"
    bin_source = tmp_path / "sources" / "bin"
    make_repo(root_source)
    make_repo(bin_source)
    workspace = tmp_path / "CustomBackup"
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest = {"schema_version": 1, "name": "FoneTool", "variables": [], "extra": "keep",
                "repositories": [
                    {"path": "bin", "remote": {"origin": str(bin_source)}, "branch": "main"},
                    {"path": ".", "remote": {"origin": str(root_source)}, "branch": "main",
                     "post": "{RepositoryName}|{RepositoryPath}|{Workspace}"},
                ]}
    manifest_file.write_text(gdeploy.render_manifest(manifest), encoding="utf-8")
    calls = []
    monkeypatch.setattr(gdeploy, "run_post_commands", lambda command, directory: calls.append((command, directory)) or True)

    assert gdeploy.deploy_manifest(str(workspace), str(manifest_file), here=here) == 0
    project = workspace if here else workspace / "FoneTool"
    assert calls[0] == (f"FoneTool|.|{project}", str(project))
    actor = git.Actor("test", "test@example.com")
    commits = {}
    for path in [".", "bin"]:
        directory = project / path
        repo = git.Repo(directory)
        if path == ".":
            repo.git.switch("-c", "4.2.1")
        (directory / "README.md").write_text("updated\n", encoding="utf-8")
        repo.index.add(["README.md"])
        commits[path] = repo.index.commit("updated", author=actor, committer=actor).hexsha
        if path == "bin":
            repo.git.switch("--detach", commits[path])
    monkeypatch.setattr("builtins.input", lambda: "y")

    assert gdeploy.update_manifest(str(project), str(manifest_file), listed_only=True) == 0
    updated = gdeploy.load_manifest(str(manifest_file))
    assert updated["schema_version"] == 1
    assert updated["name"] == "FoneTool"
    assert updated["extra"] == "keep"
    by_path = {item["path"]: item for item in updated["repositories"]}
    assert set(by_path) == {".", "bin"}
    assert by_path["."]["branch"] == "4.2.1"
    assert by_path["bin"]["branch"] == "main"
    assert {path: item["commit"] for path, item in by_path.items()} == commits
    assert not list(tmp_path.glob("*.backup.*"))


@pytest.mark.parametrize("mode", ["archive", "mirror", "bare"])
def test_schema_non_worktree_root_uses_dot(tmp_path, monkeypatch, mode):
    source = tmp_path / "source"
    make_repo(source)
    workspace = tmp_path / "Renamed"
    manifest_file = tmp_path / "gdeploy.manifest"
    manifest_file.write_text(gdeploy.render_manifest({
        "schema_version": 1, "name": "Project", "variables": [],
        "repositories": [{"path": ".", "mode": mode, "remote": {"origin": str(source)}}],
    }), encoding="utf-8")

    assert gdeploy.deploy_manifest(str(workspace), str(manifest_file), here=True) == 0
    monkeypatch.setattr("builtins.input", lambda: "y")
    assert gdeploy.update_manifest(str(workspace), str(manifest_file)) == 0
    entry = gdeploy.load_manifest(str(manifest_file))["repositories"][0]
    assert entry["path"] == "."
    assert entry["mode"] == mode


def test_failed_scan_write_keeps_original_manifest(tmp_path, monkeypatch):
    workspace = tmp_path / "Project"
    make_repo(workspace)
    manifest_file = tmp_path / "gdeploy.manifest"
    original = gdeploy.render_manifest({"repositories": [{"path": "Project"}]})
    manifest_file.write_text(original, encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda: "y")

    def fail_replace(*args):
        raise OSError("write failed")

    monkeypatch.setattr(gdeploy.os, "replace", fail_replace)
    assert gdeploy.update_manifest(str(workspace), str(manifest_file)) == 1
    assert manifest_file.read_text(encoding="utf-8") == original
    assert {path.name for path in tmp_path.iterdir()} == {
        workspace.name, manifest_file.name, *[path.name for path in tmp_path.glob("*.backup.*")]
    }


@pytest.mark.parametrize("kind", ["missing", "empty", "unmatched"])
def test_listed_scan_does_not_claim_latest_without_matches(tmp_path, monkeypatch, capsys, kind):
    manifest_file = tmp_path / "gdeploy.manifest"
    if kind != "missing":
        manifest_file.write_text(gdeploy.render_manifest({
            "schema_version": 1, "name": "Project", "repositories": [] if kind == "empty" else [{"path": "missing"}],
        }), encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda: pytest.fail("unexpected prompt"))
    assert gdeploy.update_manifest(str(tmp_path), str(manifest_file), listed_only=True) == 1
    assert "Manifest is up to date" not in capsys.readouterr().out


def test_scan_root_submodule_parent_is_dot(tmp_path):
    workspace = tmp_path / "Renamed"
    make_repo(workspace)
    child = workspace / "child"
    make_repo(child)
    gitdir = workspace / ".git" / "modules" / "child"
    gitdir.parent.mkdir(parents=True)
    (child / ".git").rename(gitdir)
    (child / ".git").write_text("gitdir: ../.git/modules/child\n", encoding="utf-8")

    scanned = gdeploy.scan_workspace(str(workspace))
    assert [item["path"] for item in scanned] == [".", "child"]
    assert scanned[1]["type"] == "submodule"
    assert scanned[1]["parent"] == "."


def test_listed_scan_preserves_missing_repository_and_reports_partial(tmp_path, monkeypatch, capsys):
    make_repo(tmp_path / "actual")
    entries = gdeploy.scan_workspace(str(tmp_path))
    entries.append({"path": "missing", "branch": "keep", "post": "build"})
    manifest_file = tmp_path / "gdeploy.manifest"
    original = gdeploy.render_manifest({"schema_version": 1, "name": "Project", "repositories": entries})
    manifest_file.write_text(original, encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda: pytest.fail("unexpected write prompt"))

    assert gdeploy.update_manifest(str(tmp_path), str(manifest_file), listed_only=True) == 1
    assert manifest_file.read_text(encoding="utf-8") == original
    output = capsys.readouterr()
    assert "listed repository not found: missing" in output.err
    assert "Manifest is up to date" not in output.out


def test_upgrade_backup_failure_does_not_replace_manifest(tmp_path, monkeypatch):
    workspace = tmp_path / "Project"
    make_repo(workspace)
    manifest_file = tmp_path / "gdeploy.manifest"
    original = gdeploy.render_manifest({"repositories": [{"path": "Project"}]})
    manifest_file.write_text(original, encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda: "y")

    def fail_copy(*args):
        raise OSError("backup failed")

    monkeypatch.setattr(gdeploy.shutil, "copy2", fail_copy)
    monkeypatch.setattr(gdeploy.os, "replace", lambda *args: pytest.fail("unexpected replace"))
    assert gdeploy.update_manifest(str(workspace), str(manifest_file)) == 1
    assert manifest_file.read_text(encoding="utf-8") == original
    assert not list(tmp_path.glob("*.backup.*"))


@pytest.mark.parametrize("operation", ["scan", "deploy"])
def test_future_schema_fails_before_repository_operations(tmp_path, monkeypatch, operation):
    manifest_file = tmp_path / "gdeploy.manifest"
    original = gdeploy.render_manifest({"schema_version": 2, "name": "Project", "repositories": []})
    manifest_file.write_text(original, encoding="utf-8")
    monkeypatch.setattr(gdeploy, "scan_workspace", lambda *args: pytest.fail("unexpected scan"))
    monkeypatch.setattr(gdeploy, "clone_repository", lambda *args: pytest.fail("unexpected clone"))
    function = gdeploy.update_manifest if operation == "scan" else gdeploy.deploy_manifest

    assert function(str(tmp_path), str(manifest_file)) == 1
    assert manifest_file.read_text(encoding="utf-8") == original
    assert not list(tmp_path.glob("*.backup.*"))
