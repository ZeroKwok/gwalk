import os
import sys
from types import SimpleNamespace

import git
import pytest

from gwalk.gwalk import CommandFilter, PathFilter, RepoHandler, RepoName, RepoStatus, RepoWalk


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


class TestRepoWalk:
    def test_repo_name_for_root_and_child(self, tmp_path):
        root = tmp_path / "root"
        child = root / "child"
        child.mkdir(parents=True)

        assert RepoName(str(root), str(root)) == "root"
        assert RepoName(str(child), str(root)) == "child"

    def test_non_recursive_walk_finds_root_and_direct_children(self, tmp_path):
        root_repo = tmp_path / "root"
        child_repo = root_repo / "child"
        nested_repo = child_repo / "nested"
        nested_repo.mkdir(parents=True)
        make_repo(root_repo)
        make_repo(child_repo)
        make_repo(nested_repo)

        walked = {
            os.path.relpath(path, tmp_path).replace("\\", "/")
            for path in RepoWalk(str(root_repo))
        }

        assert walked == {"root", "root/child"}

    def test_recursive_walk_finds_nested_repositories(self, tmp_path):
        root_repo = tmp_path / "root"
        nested_repo = root_repo / "child" / "nested"
        nested_repo.mkdir(parents=True)
        make_repo(root_repo)
        make_repo(nested_repo)

        walked = {
            os.path.relpath(path, tmp_path).replace("\\", "/")
            for path in RepoWalk(str(root_repo), recursive=True)
        }

        assert walked == {"root", "root/child/nested"}

    def test_repo_type_supports_normal_and_submodule_style_git_markers(self):
        assert RepoWalk.repoTypeByFiles([".git"], []) == 1
        assert RepoWalk.repoTypeByFiles([], [".git"]) == 2
        assert RepoWalk.repoTypeByFiles(["objects", "refs"], ["HEAD", "config"]) == 3
        assert RepoWalk.repoTypeByFiles([], []) == 0

    def test_recursive_walk_finds_bare_repository(self, tmp_path):
        bare = tmp_path / "mirror.git"
        git.Repo.init(bare, bare=True)

        walked = {
            os.path.relpath(path, tmp_path).replace("\\", "/")
            for path in RepoWalk(str(tmp_path), recursive=True)
        }

        assert "mirror.git" in walked

    def test_is_repo_detects_repo_from_child_directory(self, tmp_path):
        make_repo(tmp_path)
        child = tmp_path / "child"
        child.mkdir()

        assert RepoWalk.isRepo(str(child)) == True
        assert RepoWalk.isRepo(str(tmp_path / "missing")) == False


class TestRepoStatus:
    def test_asset_state_match(self):
        state = RepoStatus.AssetState("M", "M", "test.txt")
        assert state.match("modified") == True
        assert state.match("untracked") == False
        assert state.match("dirty") == True

        state = RepoStatus.AssetState("?", "?", "test.txt")
        assert state.match("modified") == False
        assert state.match("untracked") == True
        assert state.match("dirty") == True

        state = RepoStatus.AssetState(" ", " ", "test.txt")
        assert state.match("modified") == False
        assert state.match("untracked") == False
        assert state.match("dirty") == False

    def test_asset_state_invalid_condition(self):
        with pytest.raises(RuntimeError):
            RepoStatus.AssetState("M", " ", "test.txt").match("invalid")

    def test_repo_status_load_and_match_states(self, tmp_path):
        repo = make_repo(tmp_path)
        status = RepoStatus(str(tmp_path)).load()
        assert status.match("clean") == True
        assert status.match("all") == True

        (tmp_path / "README.md").write_text("changed\n", encoding="utf-8")
        status = RepoStatus(str(tmp_path)).load()
        assert status.match("modified") == True
        assert status.match("dirty") == True
        assert status.match("clean") == False

        repo.index.checkout(["README.md"], force=True)
        (tmp_path / "new.txt").write_text("new\n", encoding="utf-8")
        status = RepoStatus(str(tmp_path)).load()
        assert status.match("untracked") == True
        assert status.match("dirty") == True

    def test_repo_status_describe_falls_back_to_short_commit(self, tmp_path):
        repo = make_repo(tmp_path)

        assert RepoStatus(str(tmp_path)).describe() == repo.head.commit.hexsha[:7]

    @pytest.mark.parametrize(
        ("archive", "mirror", "expected"),
        [(True, True, "archive mirror"), (False, True, "mirror"), (False, False, "bare")],
    )
    def test_bare_repo_status_is_clean_and_has_type(self, tmp_path, archive, mirror, expected):
        repo = git.Repo.init(tmp_path, bare=True)
        if mirror:
            with repo.config_writer() as config:
                config.set_value('remote "origin"', "url", "https://example.com/source.git")
                config.set_value('remote "origin"', "mirror", "true")
        if archive:
            (tmp_path / "config.archive").write_text("[core]\nbare = false\n", encoding="utf-8")

        status = RepoStatus(str(tmp_path)).load()
        assert status.match("clean") is True
        assert status.match("dirty") is False
        assert status.bare_type() == expected

    def test_bare_repo_display_uses_git_directory(self, tmp_path, capsys):
        repo = git.Repo.init(tmp_path, bare=True)
        with repo.config_writer() as config:
            config.set_value('remote "origin"', "mirror", "true")

        RepoStatus(str(tmp_path)).load().display(str(tmp_path.parent), "brief")
        assert "Clean (mirror)" in capsys.readouterr().out


class TestRepoHandler:
    def test_format_cmd_replaces_placeholders(self, tmp_path):
        repo = make_repo(tmp_path, "dev")
        args = SimpleNamespace(
            params=["git", "push", "origin", "{ab}", "{RepositoryName}", "{cwd}"],
            directory=str(tmp_path.parent),
        )

        assert RepoHandler._format_cmd(repo, args) == (
            f"git push origin dev {tmp_path.name} {tmp_path.parent}"
        )

    def test_format_cmd_replaces_active_branch_alias(self, tmp_path):
        repo = make_repo(tmp_path, "dev")
        args = SimpleNamespace(params=["echo", "{ActiveBranch}"], directory=str(tmp_path))

        assert RepoHandler._format_cmd(repo, args) == "echo dev"

    def test_report_includes_success_and_failure_counts(self):
        handler = RepoHandler()
        handler.success = [object(), object()]
        handler.failure = [object()]

        assert handler.report("; ") == "; Run result: success 2, failure 1"

    def test_report_is_empty_without_results(self):
        assert RepoHandler().report("; ") == ""


class TestPathFilter:
    def test_path_filter_match(self, tmp_path):
        blacklist = tmp_path / "test.blacklist"
        blacklist.write_text(
            """
# comment
^.+/test1$
^.+/test2$
"""
        )

        filter = PathFilter(str(blacklist))
        assert filter.match("path/to/test1") == True
        assert filter.match("path/to/test2") == True
        assert filter.match("path/to/test3") == False

    def test_path_filter_empty(self):
        filter = PathFilter(None)
        assert bool(filter) == False

    def test_path_filter_normalizes_windows_separators(self, tmp_path):
        whitelist = tmp_path / "test.whitelist"
        whitelist.write_text(r"^path/to/repo$" + "\n")

        filter = PathFilter(str(whitelist))

        assert filter.match(r"path\to\repo") == True


class TestCommandFilter:
    def test_command_filter_empty_matches(self, tmp_path):
        repo = SimpleNamespace(working_dir=str(tmp_path))

        assert bool(CommandFilter(None)) == False
        assert CommandFilter(None).match(repo) == True

    def test_command_filter_match_by_exit_code(self, tmp_path):
        repo = SimpleNamespace(working_dir=str(tmp_path))

        assert CommandFilter(f'"{sys.executable}" -c "import sys; sys.exit(0)"').match(repo) == True
        assert CommandFilter(f'"{sys.executable}" -c "import sys; sys.exit(1)"').match(repo) == False

    def test_command_filter_runs_in_repo_directory(self, tmp_path):
        (tmp_path / "marker.txt").write_text("")
        repo = SimpleNamespace(working_dir=str(tmp_path))
        cmd = (
            f'"{sys.executable}" -c '
            '"import os, sys; sys.exit(0 if os.path.exists(\'marker.txt\') else 1)"'
        )

        assert CommandFilter(cmd).match(repo) == True
