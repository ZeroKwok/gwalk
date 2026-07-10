


def __UnitTest_0():
    assert GitFileStatusCheck(RepoAssetState(' ', 'M'), 'modified')
    assert GitFileStatusCheck(RepoAssetState(' ', 'D'), 'modified')

    assert GitFileStatusCheck(RepoAssetState('M', ' '), 'modified')
    assert GitFileStatusCheck(RepoAssetState('A', ' '), 'modified')
    assert GitFileStatusCheck(RepoAssetState('R', ' '), 'modified')
    assert GitFileStatusCheck(RepoAssetState('C', ' '), 'modified')

    assert GitFileStatusCheck(RepoAssetState('M', 'M'), 'modified')
    assert GitFileStatusCheck(RepoAssetState('A', 'M'), 'modified')
    assert GitFileStatusCheck(RepoAssetState('R', 'M'), 'modified')
    assert GitFileStatusCheck(RepoAssetState('C', 'M'), 'modified')

    assert GitFileStatusCheck(RepoAssetState('M', 'D'), 'modified')
    assert GitFileStatusCheck(RepoAssetState('A', 'D'), 'modified')
    assert GitFileStatusCheck(RepoAssetState('R', 'D'), 'modified')
    assert GitFileStatusCheck(RepoAssetState('C', 'D'), 'modified')

    assert not GitFileStatusCheck(RepoAssetState(' ', 'M'), 'untracked')
    assert not GitFileStatusCheck(RepoAssetState(' ', 'D'), 'untracked')

    assert not GitFileStatusCheck(RepoAssetState('M', ' '), 'untracked')
    assert not GitFileStatusCheck(RepoAssetState('A', ' '), 'untracked')
    assert not GitFileStatusCheck(RepoAssetState('R', ' '), 'untracked')
    assert not GitFileStatusCheck(RepoAssetState('C', ' '), 'untracked')

    assert not GitFileStatusCheck(RepoAssetState('M', 'M'), 'untracked')
    assert not GitFileStatusCheck(RepoAssetState('A', 'M'), 'untracked')
    assert not GitFileStatusCheck(RepoAssetState('R', 'M'), 'untracked')
    assert not GitFileStatusCheck(RepoAssetState('C', 'M'), 'untracked')

    assert not GitFileStatusCheck(RepoAssetState('M', 'D'), 'untracked')
    assert not GitFileStatusCheck(RepoAssetState('A', 'D'), 'untracked')
    assert not GitFileStatusCheck(RepoAssetState('R', 'D'), 'untracked')
    assert not GitFileStatusCheck(RepoAssetState('C', 'D'), 'untracked')

    assert GitFileStatusCheck(RepoAssetState('?', '?'), 'untracked')

    assert GitFileStatusCheck(RepoAssetState('?', '?'), 'dirty')
    assert GitFileStatusCheck(RepoAssetState(' ', 'M'), 'dirty')
    assert GitFileStatusCheck(RepoAssetState('M', ' '), 'dirty')

def __UnitTest_1():
    os.system('git status --porcelain=1 --untracked-files=normal')
    print('-----------------------------------------------------')

    status = GitStatus(git.Repo(os.getcwd()))
    for node in status:
        suffix = f'PATH {node.PATH}'
        if node.ORIG_PATH:
            suffix = f'ORIG_PATH {node.ORIG_PATH} -> PATH {node.PATH}'
        print(f'X {node.X} Y {node.Y} ' + suffix)
    print('-----------------------------------------------------')

    clean = GitStatusCheck(status, 'clean')
    dirty = GitStatusCheck(status, 'dirty')
    modified = GitStatusCheck(status, 'modified')
    untracked = GitStatusCheck(status, 'untracked')
    assert clean or dirty and clean  != dirty
    assert dirty == (modified or untracked)

    print(f'GitStatusCheck() -> clean: {clean}, dirty: {dirty}, modified: {modified}, untracked: {untracked}')


    # 单元测试
    # args = parser.parse_args([])
    # args = parser.parse_args('--version'.split())
    # args = parser.parse_args('--verbose'.split())
    # args = parser.parse_args('--level none'.split())
    # args = parser.parse_args('--level normal'.split())
    # args = parser.parse_args('--level brief'.split())
    # args = parser.parse_args('--level verbose'.split())
    # args = parser.parse_args('--verbose --level brief'.split())
    # args = parser.parse_args('--verbose --level none'.split())
    # args = parser.parse_args('-v --level none'.split())
    # args = parser.parse_args('-d ..'.split())
    # args = parser.parse_args('--directory ..'.split())
    # args = parser.parse_args('-rd ..'.split())
    # args = parser.parse_args('--directory .. --recursive'.split())
    # args = parser.parse_args('-f all'.split())
    # args = parser.parse_args('-f modified'.split())
    # args = parser.parse_args('-f untracked'.split())
    # args = parser.parse_args('--filter clean'.split())
    # args = parser.parse_args('--blacklist gwalk.blacklist'.split())
    # args = parser.parse_args('--blacklist "gwalk.blacklist"'.split())
    # args = parser.parse_args('--blacklist "./gwalk.blacklist"'.split())
    # args = parser.parse_args('--blacklist "../gwalk.blacklist"'.split())
    # args = parser.parse_args('--force'.split())
    # args = parser.parse_args('-a gui'.split())
    # args = parser.parse_args('-a bash'.split())
    # args = parser.parse_args('-a run git pull origin dev'.split())
    # args = parser.parse_args('-a run "git pull origin dev"'.split())
    # args = parser.parse_args('--action run git pull origin dev'.split())
    # args = parser.parse_args('-f all -a bash'.split())
    # args = parser.parse_args('-rf all -a bash'.split())
    # args = parser.parse_args('-rf all -a bash'.split())
    # args = parser.parse_args('-f clean -a gui'.split())
    # args = parser.parse_args('-d .. -f all -a run push origin dev'.split())
    # args = parser.parse_args('-f all -a run git push origin dev'.split())
    # args = parser.parse_args('-rf all -d ./projects --blacklist ./gwalk.blacklist --force -a run git pull origin {ActiveBranch}'.split())
    # args = parser.parse_args('-rf all --directory ./projects --blacklist ./gwalk.blacklist --force --action run git pull origin {ActiveBranch}'.split())