#! python
# -*- coding: utf-8 -*-
#
# This file is part of the gwalk project.
# Copyright (c) 2020-2025 zero <zero.kwok@foxmail.com>
#
# For the full copyright and license information, please view the LICENSE
# file that was distributed with this source code.
#
# gcp.py (git commit and push)
#
# 语法
#   gcp.py [-h] [-a|--all] [--show] [-p|--push] [-s|--src <SRC>] ["提交信息"]
# 
# 示例
#   1. gcp.py "fix some bugs"
#      仅推送当前分支到所有远端, 不做提交
#      相当于执行: git add -u && git commit -m "提交信息" && git push {remotes} {branch}
#   2. gcp.py --push
#      仅推送当前分支到所有远端, 不做提交
#
# 选项
#   commit       提交消息
#   -a,--all     添加未跟踪的文件以及已修改的文件
#   -s,--src     要推送的本地仓库中的 分支 或 标签
#   -p,--push    仅执行推送动作, 将忽略 --all 以及 commit
#   -n,--dry-run 仅显示执行命令，而不做任何改变

import os
import argparse
from gwalk import gwalk

class ResultError(RuntimeError):  
    def __init__(self, message, ecode):  
        super().__init__(message)  
        self.ecode = ecode  

def execute(cmd:str, dry_run:bool=False):
   if dry_run:
      gwalk.cprint(f'(dry-run) > {cmd}', 'cyan')
      return

   gwalk.cprint(f'> {cmd}', 'green')
   code = gwalk.RepoHandler.execute(cmd)
   if code != 0:
      raise ResultError(f'Run: {cmd}', code)

def main():
   try:
      parser = argparse.ArgumentParser(
         description='''A Git helper tool that combines `commit` and `push` operations.

This tool streamlines git workflow by combining multiple operations:
1. Automatically adds modified files (git add -u)
   - With -a option: adds all files including untracked (git add -A)
2. Commits changes with message or opens editor
3. Pushes to all configured remote repositories

Examples:
  gcp "fix bugs"    # Add modified files, commit, and push to all remotes
  gcp -a "new feat" # Add all files (including untracked), commit, and push
  gcp -p            # Push only mode, skips add/commit steps
  gcp -n            # Show commands without executing (dry-run)''',
         formatter_class=argparse.RawTextHelpFormatter,
         epilog='Note: By default, this tool must be run from repository root.'
      )
      parser.add_argument('commit', nargs=argparse.REMAINDER, 
                         help='commit message (optional)\n'
                              'if not provided, opens the git commit editor')
      parser.add_argument('-a', '--all', action='store_true',
                         help='stage all changes including untracked files\n'
                              '(equivalent to git add -A instead of git add -u)')
      parser.add_argument('-p', '--push', action='store_true',
                         help='push-only mode: skip add and commit steps\n'
                              'pushes current or specified branch to all remotes')
      parser.add_argument('-s', '--src', metavar='BRANCH',
                         help='source branch/tag to push (optional)\n'
                              'defaults to current branch if not specified')
      parser.add_argument('-i', '--ignore', action='store_true',
                         help='ignore repository root check\n'
                              'allows running from any subdirectory')
      parser.add_argument('-n', '--dry-run', action='store_true',
                         help='show what would be done without actually doing it')
      args = parser.parse_args()

      args.commit = ' '.join(args.commit)

      if not gwalk.RepoWalk.isRepo(os.getcwd()):
         gwalk.cprint(f'This is not an valid git repository.', 'red')
         exit(1)

      if not args.ignore and not gwalk.RepoWalk.isRepoRoot(os.getcwd()):
         gwalk.cprint(f'This directory is not the root of the git repository; ignore this with the -i option.', 'yellow')
         exit(1)

      repo = gwalk.RepoStatus(os.getcwd()).load()

      if args.src is None:
         args.src = repo.repo.active_branch.name

      if args.push:
         for r in repo.repo.remotes:
            execute(f'git push {r.name} {args.src}', args.dry_run)
         exit(0)

      if repo.match('clean'):
         gwalk.cprint(f'The git repository is clean.', 'green')
         exit(0)
      execute('git status -s --untracked-files=normal')

      if repo.match('dirty' if args.all else 'modified'):
         execute('git add -A' if args.all else 'git add -u', args.dry_run)
         if args.commit:
            execute(f'git commit -m "{args.commit}"', args.dry_run)
         else:
            execute(f'git commit', args.dry_run)
         for r in repo.repo.remotes:
            execute(f'git push {r.name} {args.src}', args.dry_run)
      exit(0)
   except ResultError as e:
      exit(e.ecode)


if __name__ == '__main__':
   main()