#! python
# -*- coding: utf-8 -*-
#
# This file is part of the gwalk project.
# Copyright (c) 2020-2025 zero <zero.kwok@foxmail.com>
#
# For the full copyright and license information, please view the LICENSE
# file that was distributed with this source code.
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
#      列出当前目录下所有'脏'的Git仓库(不包含./gwalk.blacklist黑名单文件中匹配的项)
#   2. gwalk.py -f  all -r
#      gwalk.py -rf all
#      递归列出当前目录下所有的Git仓库(不包含./gwalk.blacklist黑名单文件中匹配的项)
#   3. gwalk.py -rf all -a run git pull origin
#      在列出的每个仓库中执行命令: git pull origin
#
# 选项
#   -h,--help       显示帮助信息
#   --version       输出程序版本
#   --debug         启用调试输出, 辅助调试过滤条件与执行的命令
#
#   -v,--verbose    启用详细输出
#   -l,--level      指定输出等级
#       'none'        仅列出仓库, 不打印仓库状态
#       'brief'       列出仓库的同时, 还会输出只有一行的简短信息(默认)
#       'normal'      列出仓库的同时, 还会输出一般的仓库的状态信息
#       'verbose'     列出仓库的同时, 还会输出尽可能详细的状态信息
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
#                        {cwd}                  将被替换为 --directory 指定的目录, 因为 . 是当前仓库的目录.

import os
import re
import sys
import argparse
import platform
import traceback
import git
from   termcolor import cprint
from . import projectName, projectHome, projectVersion, projectAuthor

def RepoName(working_dir:str, root:str):
    name = os.path.relpath(working_dir, root)
    if '.' == name:
        name = f'{os.path.basename(working_dir)}'
    return name


class RepoWalk:
    def __init__(self, directory:str, recursive:bool=False, verbose:int=0):
        self.directory = directory
        self.recursive = recursive
        self.verbose = verbose

    def __iter__(self):
        if self.recursive:
            for root, dirs, files in os.walk(self.directory):
                if RepoWalk.repoTypeByFiles(dirs, files) != 0:
                    yield root
        else:
            for root, dirs, files in os.walk(self.directory):
                if RepoWalk.isRepoRoot(root):
                    yield root
                for d in dirs:
                    if d in ['.git', '.vs', '.vscode']:
                        continue
                    path = os.path.normpath(os.path.join(root, d))
                    if RepoWalk.isRepoRoot(path):
                        yield path
                break

    def repoTypeByFiles(dirs, files) -> int:
        '''0 None, 1 Normal, 2 Submodule'''
        if '.git' in dirs:
            return 1
        if '.git' in files:
            return 2

        # TODO
        # Check the config has bare = true
        # Check the config has submodule = true
        return 0

    def isRepoRoot(directory) -> int:
        for _, dirs, files in os.walk(directory):
            return RepoWalk.repoTypeByFiles(dirs, files) != 0
        return False

    def isRepo(directory) -> int:
        try:
            repo = git.Repo(directory, search_parent_directories=True)
        except git.exc.InvalidGitRepositoryError:
            return False
        if repo.bare:
            return False
        return True

# 参考文档
# - [GitPython doc](https://gitpython.readthedocs.io/en/stable/)
# - [How to manage git repositories with Python](https://linuxconfig.org/how-to-manage-git-repositories-with-python)
class RepoStatus:
    def __init__(self, directory:str):
        self.repo = git.Repo(directory, search_parent_directories=True)
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
        dir = RepoName(self.repo.working_dir, root)

        if level == 'none':
            cprint(dir)
            return

        cprint(dir, 'green', end=' ')
        cprint(f'({self.repo.active_branch.name})', 'cyan')

        if level == 'brief':
            modified = []
            untracked = []
            for item in self.status:
                if not item.X in ' ?' or item.Y in 'MD':
                    modified.append(item)
                elif item.X == '?' and item.Y == '?':
                    untracked.append(item)

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
    class Result:
        repo: any = None
        code: int = None

    def __init__(self):
        self.success = []
        self.failure = []

    @staticmethod
    def _format_cmd(repo, args):
        cmd = ' '.join(args.params)
        if '{ab}' in cmd:
            cmd = cmd.replace('{ab}', repo.active_branch.name)
        if '{ActiveBranch}' in cmd:
            cmd = cmd.replace('{ActiveBranch}', repo.active_branch.name)
        if '{RepositoryName}' in cmd:
            cmd = cmd.replace('{RepositoryName}', os.path.basename(repo.working_dir))
        if '{cwd}' in cmd:
            cmd = cmd.replace('{cwd}', args.directory)
        return cmd

    @staticmethod
    def execute(cmd:str) -> int:
        code = os.system(cmd)
        if platform.system().lower() != 'windows':
            code >>= 8
        return code

    def perform(self, repo, args):
        lastcwd = os.getcwd()
        try:
            if args.action == 'bash':
                cprint('')
                cprint(f'> Note that you are running in a new bash...', 'yellow')
                cprint(f'> * Press "CTRL + D" to exit the bash!', 'yellow')
                cprint(f'> * Press "CTRL + C, CTRL + D" to abort the {projectName}!', 'yellow')

                os.environ['PS1'] = rf'\[\033]0;$TITLEPREFIX:$PWD\007\]\n\[\033[32m\]\u@\h \[\033[35m\]$MSYSTEM \[\033[33m\]\w\[\033[36m\] (gwalk|{repo.active_branch.name})\[\033[0m\]\n$'
                os.chdir(repo.working_dir)
                os.system('bash --noprofile --norc')

            elif args.action == 'gui':
                os.chdir(repo.working_dir)
                os.system('git gui')

            elif args.action == 'run':
                cmd = self._format_cmd(repo, args)

                os.chdir(repo.working_dir)

                result = RepoHandler.Result()
                result.repo = repo
                result.code = self.execute(cmd)
                if args.verbose:
                    cprint(f'> Execute: "{cmd}" -> {result.code}', 'red' if result.code else 'yellow')

                if result.code == 0:
                    self.success.append(result)
                else:
                    self.failure.append(result)

        except Exception as e:
            traceback.print_exc()

        finally:
            os.chdir(lastcwd)

    def report(self, prefix:str=''):
        if self.success or self.failure:
            return prefix + f'Run result: success {len(self.success)}, failure {len(self.failure)}'
        else:
            return ''

import time
import asyncio
import threading
import itertools
import concurrent.futures
from natsort import natsorted
from typing import List, Dict, Optional, Tuple

class RepoAsyncHandler:
    class Result:
        repo: any = None
        code: int = None
        stdout: str = ""
        stderr: str = ""
        exception: Exception = None

    def __init__(self, jobs: int = -1):
        self.success: List[RepoAsyncHandler.Result] = []
        self.failure: List[RepoAsyncHandler.Result] = []
        self.aborted: List = []
        self.futures: List = []
        self.loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()

        def _runloop():
            asyncio.set_event_loop(self.loop)
            self.loop.run_forever()
        self.thread = threading.Thread(target=_runloop, daemon=True)
        self.thread.start()

        self.jobs = jobs if jobs > 1 else min(32, (os.cpu_count() or 1) * 2)
        self.semaphore = asyncio.Semaphore(self.jobs)

    async def execute(self, repo, cmd: str) -> Result:
        async with self.semaphore:   # 限制并发量
            try:
                process = await asyncio.create_subprocess_shell(
                    cmd,
                    cwd=repo.working_dir,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()

                code = process.returncode
                if platform.system().lower() != 'windows':
                    code >>= 8

                result = RepoAsyncHandler.Result()
                result.repo = repo
                result.code = code
                result.stdout = stdout.decode('utf-8').rstrip('\n')
                result.stderr = stderr.decode('utf-8').rstrip('\n')
                return result

            except Exception as e:
                result = RepoAsyncHandler.Result()
                result.repo = repo
                result.exception = e
                return result

    def perform(self, repo, args):
        cmd = RepoHandler._format_cmd(repo, args)
        future = asyncio.run_coroutine_threadsafe(
            self.execute(repo, cmd), self.loop
        )
        future.repo = repo
        self.futures.append(future)
        return future

    def join(self, root:str, verbose:int, timeout:int=360):
        if timeout:
            cprint('')
            cprint(f"Waiting for {len(self.futures)} tasks to complete...", 'yellow')
            cprint("Press Ctrl+C to interrupt and show partial results")
        pending = set(self.futures)

        # 动画帧
        sigstop = threading.Event()
        spinner = itertools.cycle(['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'])
        def _spinner():
            padding = ' ' * 30
            while not sigstop.is_set():
                cprint(f'\r{next(spinner)} {len(pending)} tasks ...', 'yellow', end='')
                time.sleep(0.1)
            cprint('\r' + padding, end='')
        animation = threading.Thread(target=_spinner, daemon=True)
        animation.start()

        # 异常处理
        def _handler(timeout: bool=False):
            sigstop.set()
            animation.join()

            cprint('')
            cprint("TimeoutError" if timeout else "KeyboardInterrupt", "red")
            cprint("Following tasks will be abort:", "red")

            display = []
            for future in pending:
                display.append(future.repo.working_dir)

                result = RepoAsyncHandler.Result()
                result.repo = future.repo
                result.exception = TimeoutError() if timeout else KeyboardInterrupt()
                self.aborted.append(result)
            for f in natsorted(display):
                cprint(f'- {RepoName(f, root)}', 'yellow')

        # 等待任务完成
        try:
            for future in concurrent.futures.as_completed(self.futures, timeout=timeout):
                result = future.result()
                if result.exception is not None or result.code != 0:
                    self.failure.append(result)
                else:
                    self.success.append(result)
                pending.remove(future)

        except KeyboardInterrupt:
            _handler()

        except TimeoutError:
            _handler(timeout > 0)

        finally:
            if not sigstop.is_set():
                sigstop.set()
                animation.join()

        # 失败的任务打印标准流
        self.print_failure(root, verbose)

    def print_failure(self, root:str, verbose:int):
        failure = [r for r in self.failure if 'KeyboardInterrupt' not in r.stderr]
        if not failure:
            return

        cprint('')
        cprint('Following tasks failed to execute:', 'red')

        for result in failure:
            cprint(f'- {RepoName(result.repo.working_dir, root)}', 'yellow')
            if result.exception is not None:
                cprint(f'  Exception: {result.exception}')
            else:
                cprint(f'  Code: {result.code}')

                output = lambda buf: "\n".join((
                    (verbose >= 2 and buf.splitlines())
                    or (verbose and buf.splitlines()[-20:])
                    or buf.splitlines()[-10:]
                ))

                if result.stdout:
                    cprint(f'  Stdout: {output(result.stdout)}')
                if result.stderr:
                    cprint(f'  Stderr: {output(result.stderr)}')

    def report(self, prefix:str=''):
        selector = []
        if self.success:
            selector.append(f'success {len(self.success)}')
        if self.failure:
            selector.append(f'failure {len(self.failure)}')
        if self.aborted:
            selector.append(f"aborted {len(self.aborted)}")

        if selector:
            return prefix + f'Run result: {", ".join(selector)}'
        else:
            return ''

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

def cli():
    parser = argparse.ArgumentParser(
        description='''Git Repository Walker and Batch Operation Tool

Features:
1. List and filter Git repositories:
   - By status (modified/untracked/dirty/clean)
   - Using blacklist/whitelist patterns
   - With recursive directory scanning
2. Display repository status information
3. Execute batch operations on matched repositories

Examples:
  gwalk                # List all 'dirty' repos in current directory
  gwalk -rf all        # Recursively list all repos
  gwalk -a run gl      # Run 'gl' (git fetch && git pull) in each matched repo
  gwalk -a bash        # Open bash shell in each repo for manual operations''',
        formatter_class=argparse.RawTextHelpFormatter
    )

    # Basic options
    parser.add_argument('--version', action='store_true',
                       help='show version information and exit')
    parser.add_argument('--debug', action='store_true', help='enable debug mode')

    parser.add_argument('-d', '--directory', action='store',
                        default=os.getcwd(),
                        help='base directory to search (default: current)')
    parser.add_argument('-r', '--recursive', action='store_true',
                        help='search subdirectories recursively')

    # Filter options
    group_filter = parser.add_argument_group('Filter options')
    group_filter.add_argument('-f', '--filter', action='store',
                            choices=['all', 'clean', 'dirty', 'modified', 'untracked'],
                            default='dirty',
                            help='filter repositories by status:\n'
                                'all       - match all states\n'
                                'clean     - no changes\n'
                                'dirty     - has changes (default)\n'
                                'modified  - has uncommitted changes\n'
                                'untracked - has untracked files')
    group_filter.add_argument('--blacklist', action='store', default='',
                            help='file containing paths to exclude\n'
                                 '(defaults to gwalk.blacklist if exists)')
    group_filter.add_argument('--whitelist', action='store', default='',
                            help='file containing paths to include\n'
                                 '(overrides blacklist if specified)')
    group_filter.add_argument('--force', action='store_true',
                            help='ignore blacklist filtering')

    # Display options
    group_display = parser.add_argument_group('Display Options')
    group_display.add_argument("-v", "--verbose", action="count", default=0, 
                            help="enable verbose output")
    group_display.add_argument('-l', '--level', choices=['none', 'brief', 'normal'],
                             default='brief',
                            help='set output detail level:\n'
                                 'none    - show paths only\n'
                                 'brief   - show single-line status (default)\n'
                                 'normal  - show git status output\n')

    # Action options
    group_action = parser.add_argument_group('Action options')
    group_action.add_argument('-a', '--action',
                            choices=['bash', 'gui', 'run', ''],
                            help='action to perform on matched repositories:\n'
                                 'bash - open interactive shell\n'
                                 'gui  - open Git GUI\n'
                                 'run  - execute specified command')
    group_action.add_argument('-j', '--jobs', nargs='?', const=-1, default=1, type=int,
                            help='number of parallel jobs for "run" action\n'
                                 '-j (without value): use all available cores (-1)\n'
                                 '-j N: use N parallel jobs\n'
                                 '(default: 1 - no parallel processing)')
    group_action.add_argument('params', nargs=argparse.REMAINDER,
                            help='command to execute (with -a run)\n'
                                 'supports variables:\n'
                                 '  {ab}, {ActiveBranch} - current branch name\n'
                                 '  {RepositoryName}     - repository directory name\n'
                                 '  {cwd}                - base search directory')

    args = parser.parse_args()

    if args.debug:
        args.verbose += 1
        input('Wait for debugging and press Enter to continue...')

    if args.version:
        print(f'{projectName} {projectVersion}')
        print(f'Author: {projectAuthor}')
        print(f'Github: {projectHome}')
        exit(0)

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
    if not args.blacklist and os.path.exists(f'{projectName}.blacklist'):
        args.blacklist = f'{projectName}.blacklist'

    # 如果白名单被指定, 则使黑名单失效, 类似: --force
    if args.whitelist: 
        args.force = True
    if args.force:
        args.blacklist = ''
    args.whitelist = PathFilter(args.whitelist)
    args.blacklist = PathFilter(args.blacklist)

    # 正规化参数 jobs (1 ~ -1)
    if args.jobs and args.action != 'run':
        cprint(f"WArnow: jobs option is only valid with -a run", "yellow")
        args.jobs = 1
    if args.jobs == 0:
        args.jobs = 1 

    if args.verbose:
        cprint(f'> Jobs: {args.jobs}', 'yellow')
        cprint(f'> Blacklist: ' + (f'Valid {{{args.blacklist.filename}}}' if args.blacklist else 'Invalid'), 'yellow')
        cprint(f'> Whitelist: ' + (f'Valid {{{args.whitelist.filename}}}' if args.whitelist else 'Invalid'), 'yellow')

    ignored = 0
    matched = 0
    handler = RepoHandler() if args.jobs == 1 else RepoAsyncHandler(args.jobs)
    try:
        for path in RepoWalk(args.directory, args.recursive, verbose=args.verbose):
            def filter(list, name, reverse=False):
                '''
                返回True表示被忽略, 黑名单匹配的项应该忽略, 而白名单匹配的项则反之, 名单未初始化则不参与过滤.
                matched : reverse 的组合结果如下: 
                    1 : 0 = 1
                    0 : 0 = 0
                    1 : 1 = 0
                    0 : 1 = 1
                '''

                if not list:
                    return False
                matched = list.match(path)
                if args.verbose:
                    cprint(f'> {name}.match({path}): {matched}', 'yellow' if matched else 'white')
                    if matched ^ reverse:
                        cprint(f'> ignored repo that {"not in" if reverse else "in"} {name}: {RepoName(path, args.directory)}', 'yellow')
                return matched ^ reverse

            if filter(args.blacklist, 'blacklist') or filter(args.whitelist, 'whitelist', True):
                ignored += 1
                continue

            repstat = RepoStatus(path)
            if not (args.filter == 'all' and args.level == 'none'):
                repstat.load()
            if not repstat.match(args.filter):
                ignored += 1
                if args.verbose:
                    cprint(f'> ignored repo that not match filter "{args.filter}": {RepoName(path, args.directory)}', 'yellow')
                continue

            matched += 1
            repstat.display(args.directory, args.level)
            handler.perform(repstat.repo, args)
    except KeyboardInterrupt:
        if args.jobs == 1:
            raise

        # 并发执行时, 需要汇报以完成的任务
        handler.join(args.directory, args.verbose, timeout=0)
        cprint('')
        cprint("Following tasks has ben completed:", 'yellow')
        for result in handler.success:
            cprint(f' - {RepoName(result.repo.working_dir, args.directory)}')
        else:
            cprint("  nothing", end='')
        exit(1)

    if args.jobs != 1:
        handler.join(args.directory, args.verbose)

    cprint('')
    cprint(f'Walked {matched + ignored} repo, matched: {matched}, ignored: {ignored}{handler.report("; ")}', 
            'red' if handler.failure else 'white')

    if handler.failure:
        cprint('The failed projects are as follows:', 'red')
        for result in handler.failure:
            cprint(' - ' + RepoName(result.repo.working_dir, args.directory), 'red')


def main():
    try:
        cli()
    except KeyboardInterrupt:
        cprint('\nKeyboardInterrupt', 'red')


if __name__ == '__main__':
    main()
