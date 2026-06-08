import os
import sys
import pytest
from types import SimpleNamespace
from gwalk.gwalk import RepoStatus, PathFilter, CommandFilter

class TestRepoStatus:
    def test_asset_state_match(self):
        """测试 AssetState.match() 方法"""
        state = RepoStatus.AssetState('M', 'M', 'test.txt')
        assert state.match('modified') == True
        assert state.match('untracked') == False
        assert state.match('dirty') == True

        state = RepoStatus.AssetState('?', '?', 'test.txt')
        assert state.match('modified') == False
        assert state.match('untracked') == True
        assert state.match('dirty') == True

        state = RepoStatus.AssetState(' ', ' ', 'test.txt')
        assert state.match('modified') == False
        assert state.match('untracked') == False
        assert state.match('dirty') == False

class TestPathFilter:
    def test_path_filter_match(self, tmp_path):
        """测试 PathFilter.match() 方法"""
        # 创建临时的黑名单文件
        blacklist = tmp_path / "test.blacklist"
        blacklist.write_text("""
# 注释行
^.+/test1$
^.+/test2$
""")
        
        filter = PathFilter(str(blacklist))
        assert filter.match('path/to/test1') == True
        assert filter.match('path/to/test2') == True
        assert filter.match('path/to/test3') == False

    def test_path_filter_empty(self):
        """测试空的 PathFilter"""
        filter = PathFilter(None)
        assert bool(filter) == False

class TestCommandFilter:
    def test_command_filter_match_by_exit_code(self, tmp_path):
        repo = SimpleNamespace(working_dir=str(tmp_path))

        assert CommandFilter(f'"{sys.executable}" -c "import sys; sys.exit(0)"').match(repo) == True
        assert CommandFilter(f'"{sys.executable}" -c "import sys; sys.exit(1)"').match(repo) == False

    def test_command_filter_runs_in_repo_directory(self, tmp_path):
        (tmp_path / 'marker.txt').write_text('')
        repo = SimpleNamespace(working_dir=str(tmp_path))
        cmd = f'"{sys.executable}" -c "import os, sys; sys.exit(0 if os.path.exists(\'marker.txt\') else 1)"'

        assert CommandFilter(cmd).match(repo) == True
