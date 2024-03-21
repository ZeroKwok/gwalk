#! python
# -*- coding: utf-8 -*-
#
# This file is part of the gwalk distribution.
# Copyright (c) 2020-2024 zero.kwok@foxmail.com
#
# gwalk.py
#
# 功能性需求
# - 列出指定目录下的所有的Git仓库
#   - 可指定过滤条件
#     - 存在未提交的修改
#     - 存在未跟踪的文件
#     - 脏的: 存在未提交的修改 或 未跟踪的文件 (默认)
#     - 所有
#   - 可指定黑名单, 即跳过匹配的仓库
#   - 可指定白名单, 即列出匹配的仓库
#   - 可指定是否递归搜索目录
# - 显示列出仓库的状态信息
#   - 可指定输出信息是简短还是冗长
# - 指定在每个列出的仓库中执行的任务
#   - run CMD
#     在仓库中执行命令: CMD
#   - git gui
#     在仓库中唤起: Git Gui 
#   - git bash
#     在仓库中唤起: Git Bash
#
# 语法
#   gwalk.py [--help][--version]  [--verbose | --level LEVEL]
#            [--directory PATH]   [--recursive] [--blacklist FILENAME] [--force]
#            [--filter CONDITION] [--action PROC]
# 示例
#   1. gwalk.py
#       列出当前目录下所有'脏'的Git仓库(不包含./gwalk.blacklist黑名单文件中匹配的项)
#   2. gwalk.py -f  all -r
#      gwalk.py -rf all
#       递归列出当前目录下所有的Git仓库(不包含./gwalk.blacklist黑名单文件中匹配的项)
#   3. gwalk.py -rf all -a run git pull origin
#       在列出的每个仓库中执行命令: git pull origin
#
# 选项
#   -h,--help       显示帮助信息
#   --version       输出程序版本
#
#   -v,--verbose    列出仓库的同时, 还会输出尽可能详细的状态信息
#   -l,--level      指定输出等级
#       'none'        仅列出仓库, 不打印仓库状态
#       'brief'       列出仓库的同时, 还会输出只有一行的简短信息(默认)
#       'normal'      列出仓库的同时, 还会输出一般的仓库的状态信息
#       'verbose'     同--verbose
#
#   -d,--directory  指定目录下搜索Git仓库, 默认是程序的当前目录
#   -r,--recursive  指定是否进入子文件夹, 从而列出尽可能多的仓库
#   -f,--filter     指定搜索仓库的过滤条件, 只有满足条件的仓库将被列出
#       'all'         所有仓库
#       'clean'       所有'干净'的仓库
#       'dirty'       所有'脏'的仓库(默认)
#       'modified'    所有'包含未提交的修改'的仓库
#       'untracked'   所有'包含跟踪文件的修改'的仓库
#   --blacklist     指定黑名单文件, 若黑名单文件有效, 则将忽略所有匹配的仓库, 即使指定了
#                   --condition=all.
#                   黑名单采用正则表达式匹配仓库目录的绝对路径 (分隔符统一为: '/' Unix filesystem分隔符)
#                   示例如下:
#                     ^.+/3rd$
#                     ^.+/demo$
#                   若--blacklist未指定, 则尝试在--directory指定的目录下查找 gwalk.blacklist文件.
#
#   --whitelist     指定白名单文件, 使黑名单机制失效. 若白名单文件有效, 则将忽略所有未匹配的仓库.
#   --force         使黑名单机制失效, 即使指定了--blacklist
#
#   -a,--action     指定在每个列出的仓库中执行的任务
#       'gui'         在每个列出的仓库唤出 Git Gui  来处理用户的操作
#       'bash'        在每个列出的仓库唤出 Git Bash 来处理用户的操作
#       'run CMD'     在每个列出的仓库执行 CMD 指定的命令, 可以在命令中包含下列"变量"(不区分大小写), 
#                      这将在执行前被替换为相应的内容.
#                        {ab} 或 {ActiveBranch} 将被替换为当前仓库的 活动分支名
#                        {RepositoryName}       将被替换为当前仓库的 目录名

import os
import re
import sys
import shutil
import argparse
import platform
import traceback

projectName    = 'gwalk'
projectHome    = 'https://open.7-0.cc/'
projectVersion = '0.1.3'
projectAuthor  = 'zero.kwok@foxmail.com'

try:
    import git
    from   termcolor import cprint
except ModuleNotFoundError as e:
    print(f'{projectName} depends on "GitPython" and "termcolor", use the following command to install them:')
    print()
    print('"python -m pip install GitPython termcolor"')
    exit(1)

class RepoWalk:
    def __init__(self, directory:str, recursive:bool=False, debug:bool=False):
        self.directory = directory
        self.recursive = recursive
        self.debug = debug

    def __iter__(self):
        if self.recursive:
            for root, dirs, files in os.walk(self.directory):
                if RepoWalk.repoType(dirs, files) != 0:
                    yield root
        else:
            for root, dirs, files in os.walk(self.directory):
                if RepoWalk.isRepo(root):
                    yield root
                for d in dirs:
                    if d in ['.git', '.vs', '.vscode']:
                        continue
                    path = os.path.normpath(os.path.join(root, d))
                    if RepoWalk.isRepo(path):
                        yield path
                break

    def repoType(dirs, files) -> int:
        '''0 None, 1 Normal, 2 Submodule'''
        if '.git' in dirs:
            return 1
        if '.git' in files:
            return 2
        return 0

    def isRepo(directory) -> int:
        for _, dirs, files in os.walk(directory):
            return RepoWalk.repoType(dirs, files) != 0
        return False

# 参考文档
# - [GitPython doc](https://gitpython.readthedocs.io/en/stable/)
# - [How to manage git repositories with Python](https://linuxconfig.org/how-to-manage-git-repositories-with-python)
class RepoStatus:
    def __init__(self, directory:str):
        self.repo = git.Repo(directory)
        self.status = []

    class AssetState:
        def __init__(self, x = '', y = '', path = ''):
            self.X = x
            self.Y = y
            self.PATH = path
            self.ORIG_PATH = None

        def match(self, condition:str='dirty') -> bool:
            '''
            condition: 
              - dirty: 存在未提交 或 未跟踪的内容
              - modified: 存在未提交的修改
              - untracked: 存在未跟踪的文件
            '''
            
            '''
            XY可能出现的值:  
              - ' ' = unmodified
              - 'M' = modified
              - 'A' = added
              - 'D' = deleted
              - 'R' = renamed
              - 'C' = copied
              - 'U' = updated but unmerged

            X          Y     Meaning
            -------------------------------------------------
                     [AMD]   not updated
            M        [ MD]   updated in index
            A        [ MD]   added to index
            D                deleted from index(git rm)
            R        [ MD]   renamed in index(git mv)
            C        [ MD]   copied in index
            [MARC]           index and work tree matches
            [ MARC]     M    work tree changed since index
            [ MARC]     D    deleted in work tree
            [ D]        R    renamed in work tree
            [ D]        C    copied in work tree
            -------------------------------------------------
            D           D    unmerged, both deleted
            A           U    unmerged, added by us
            U           D    unmerged, deleted by them
            U           A    unmerged, added by them
            D           U    unmerged, deleted by us
            A           A    unmerged, both added
            U           U    unmerged, both modified
            -------------------------------------------------
            ?           ?    untracked
            !           !    ignored
            -------------------------------------------------
            '''

            flags = 0
            if not self.X in ' ?' or self.Y in 'MD':
                flags = 1 
            elif self.X == '?' and self.Y == '?':
                flags = 2 

            if condition == 'modified':
                return flags == 1
            elif condition == 'untracked':
                return flags == 2
            elif condition == 'dirty':
                return flags != 0
            else:
                raise RuntimeError(f'Invalid parameter: condition={condition}')

    def __bool__(self):
        '''返回True, 表示仓库状态是脏的(dirty)'''
        return bool(self.status)
    
    def load(self):
        '''
        加载仓库状态
        '''

        '''
        相当于执行下面的命令: 
        git status --porcelain=1 --untracked-files=normal
    
        参考:
        https://git-scm.com/docs/git-status
        https://git-scm.com/docs/git-status#_output

        Short Format:
        - XY PATH
        - XY ORIG_PATH -> PATH

        XY 是两个字符的状态码, ORIG_PATH 只在 重命名 或 复制 时显示.

        XY 语法有三种不同模式的状态:
            - 一般模式: 即当合并成功或在合并之外的情况, X表示index的状态, Y表示工作树的状态.
            - 合并模式: 即当发生合并冲突且尚未解决时, X和Y表示相对于共同的祖先, 两个HEAD所引入的状态, PATH 表示未合并.
            - 未跟踪模式: 即当PATH是未跟踪的文件时, X与Y总是相同的, 因为它们index是未知的. 
            忽略的文件不会被列出, 除非使用--ignored; 如果是，则忽略的文件将用!!表示。
        '''
        self.status = []

        # porcelain       易于解析的简单的输出, 类似-s(Short Format)
        # untracked_files 包含详细的未跟踪文件列表
        #   - normal - Shows untracked files and directories.
        #   - all - Also shows individual files in untracked directories.
        #   - no - Show no untracked files.
        proc = self.repo.git.status(porcelain='1', untracked_files='normal', as_process=True)

        # XY PATH
        # XY ORIG_PATH -> PATH
        for line in proc.stdout:
            line = line.decode('utf-8').rstrip('\n')
            if len(line) == 0:
                continue

            asset = self.AssetState()
            asset.X = line[0:1]
            asset.Y = line[1:2]
            asset.PATH = line[3:]

            if ' -> ' in asset.PATH:
                match = re.search(r'^"?(.+?)"? -> "?(.+?)"?$', asset.PATH)
                if match is None:
                    raise RuntimeError('Unexpected format: ' + line)
                asset.PATH = match.group(2)
                asset.ORIG_PATH = match.group(1)
            elif asset.PATH[0] == '"' and asset.PATH[-1] == '"':
                asset.PATH = asset.PATH[1:-2]
            self.status.append(asset)
        proc.wait()
        return self

    def match(self, condition:str='dirty') -> bool:
        '''
        condition: 
          - modified: 存在未提交的修改
          - untracked: 存在未跟踪的文件
          - dirty: 存在modified或untracked
          - clean: 不存在modified或untracked
        '''
        if condition == 'all':
            return True
        elif condition == 'clean':
            return not self
        elif condition == 'dirty':
            return bool(self)

        for asset in self.status:
            if asset.match(condition):
                return True
        return False

    def display(self, root:str, level:str='brief'):
        dir = self.repo.working_dir
        dir = os.path.relpath(self.repo.working_dir, root)

        if level == 'none':
            cprint(dir)

        elif level == 'brief':
            modified = []
            untracked = []
            for item in self.status:
                if not item.X in ' ?' or item.Y in 'MD':
                    modified.append(item)
                elif item.X == '?' and item.Y == '?':
                    untracked.append(item)

            cprint(dir, 'green')
            if not modified and not untracked:
                cprint(f'  Clean', 'white')
            else:
                cprint(f'  Modified: {len(modified)}, Untracked: {len(untracked)}', 'red')

        else:
            lastcwd = os.getcwd()
            try:
                os.chdir(self.repo.working_dir)
                if level == 'normal':
                    os.system('git status -s --untracked-files=normal --ignore-submodules=all')
                else:
                    os.system('git status -b --show-stash --untracked-files=all --ignore-submodules=all --ignored')
            finally:
                os.chdir(lastcwd)

class RepoHandler:
    def __init__(self):
        self.success = []
        self.failure = []
    
    def perform(self, repo, args):
        lastcwd = os.getcwd()
        try:
            if args.action == 'bash':
                cprint('')
                cprint(f'> Note that you are running in a new bash...', 'yellow')
                cprint(f'> * Press "CTRL + D" to exit the bash!', 'yellow')
                cprint(f'> * Press "CTRL + C, CTRL + D" to abort the {projectName}!', 'yellow')
                os.chdir(repo.repo.working_dir)
                os.system('bash')

            elif args.action == 'gui':
                os.chdir(repo.repo.working_dir)
                os.system('git gui')

            elif args.action == 'run':
                cmd = ' '.join(args.params)
                if '{ab}' in cmd:
                    cmd = cmd.replace('{ab}', repo.repo.active_branch.name)
                if '{ActiveBranch}' in cmd:
                    cmd = cmd.replace('{ActiveBranch}', repo.repo.active_branch.name)
                if '{RepositoryName}' in cmd:
                    cmd = cmd.replace('{RepositoryName}', os.path.basename(repo.repo.working_dir))

                os.chdir(repo.repo.working_dir)
                repo.code = os.system(cmd)
                if platform.system().lower() != 'windows':
                    repo.code >>= 8
                    
                if repo.code == 0:
                    self.success.append(repo)
                else:
                    self.failure.append(repo)
                    
        except Exception as e:
            traceback.print_exc()

        finally:
            os.chdir(lastcwd)
            
    def report(self):
        pass

class PathFilter:
    def __init__(self, filename:str=None) -> None:
        self.patterns = None
        self.filename = filename
        self.load(filename)

    def __bool__(self):
        return self.patterns is not None

    def load(self, filename:str) -> bool:
        if not filename:
            return
        self.patterns = []
        with open(filename, 'r') as f:
            for line in f:
                line = line.lstrip(' ').rstrip('\n')
                if not line or line.startswith('#'):
                    continue
                self.patterns.append(re.compile(line.rstrip('\n')))

    def match(self, path) -> bool:
        path = path.replace('\\', '/')
        for item in self.patterns:
            if item.match(path):
                return True
        return False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', action='store_true')
    parser.add_argument('--debug',  action='store', nargs='?', default='disable')

    parser.add_argument('-v', '--verbose', action='store_true', default=False)
    parser.add_argument('-l', '--level', action='store', choices=['none', 'brief', 'normal', 'verbose'], default='brief')

    parser.add_argument('-d', '--directory', action='store', default=os.getcwd())
    parser.add_argument('-r', '--recursive', action='store_true', default=False)

    parser.add_argument('-f', '--filter', action='store', choices=['all', 'clean', 'dirty', 'modified', 'untracked'], default='dirty')
    parser.add_argument('--blacklist', action='store', default='')
    parser.add_argument('--whitelist', action='store', default='')
    parser.add_argument('--force', action='store_true')

    parser.add_argument('-a', '--action', action='store', choices=['bash', 'gui', 'run'], default=None)
    parser.add_argument('params', nargs=argparse.REMAINDER)

    args = parser.parse_args()
    if args.debug == 'disable':
        args.debug = False
    else:
        if args.debug == 'wait':
            input('Wait for debugging and press Enter to continue...')
        else:
            args.debug = True
        print(f'> {projectName} args={args}')

    if args.version:
        print(f'{projectName} version {projectVersion} powered by {projectAuthor}')
        print(f'Home: {projectHome}')
        exit(0)

    # --verbose 优先
    if args.verbose:
        args.level = 'verbose'

    # 观察
    args.untracked_files = 'normal'
    if args.level == 'verbose':
        args.untracked_files = 'all'

    args.directory = args.directory.strip(' \'"')
    args.blacklist = args.blacklist.strip(' \'"')
    args.whitelist = args.whitelist.strip(' \'"')

    if args.blacklist and not os.path.exists(args.blacklist):
        raise RuntimeError(f'Invalid blacklist: {args.blacklist}')
    if args.whitelist and not os.path.exists(args.whitelist):
        raise RuntimeError(f'Invalid whitelist: {args.whitelist}')
    if os.path.exists(f'{projectName}.blacklist'):
        args.blacklist = f'{projectName}.blacklist'

    # 如果白名单被指定, 则使黑名单失效, 类似: --force
    if args.whitelist: 
        args.force = True
    if args.force:
        args.blacklist = ''
    args.whitelist = PathFilter(args.whitelist)
    args.blacklist = PathFilter(args.blacklist)
    if args.debug:
        print(f'> Blacklist: ' + (f'Valid {{{args.blacklist.filename}}}' if args.blacklist else 'Invalid'))
        print(f'> Whitelist: ' + (f'Valid {{{args.whitelist.filename}}}' if args.whitelist else 'Invalid'))

    ignored = 0
    matched = 0
    handler = RepoHandler()
    for path in RepoWalk(args.directory, args.recursive, debug=args.debug):
        def filter(list, name):
            if list and list.match(path):
                if args.debug:
                    print(f'> ignored repo that in {name}: {os.path.relpath(path, args.directory)}')
                return True
            return False
        if filter(args.blacklist, 'blacklist') or filter(args.whitelist, 'whitelist'):
            ignored += 1
            continue
         
        repo = RepoStatus(path)
        if not (args.filter == 'all' and args.level == 'none'):
            repo.load()
        if not repo.match(args.filter):
            ignored += 1
            if args.debug:
                print(f'> ignored repo that not match filter "{args.filter}": {os.path.relpath(path, args.directory)}')
            continue
        
        matched += 1
        repo.display(args.directory, args.level)
        handler.perform(repo, args)
        
    cprint('')
    cprint(f'Walked {matched+ignored} repo, matched: {matched}, ignored: {ignored}')

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass