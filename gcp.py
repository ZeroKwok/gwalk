#! python
# -*- coding: utf-8 -*-
#
# This file is part of the gwalk distribution.
# Copyright (c) 2020-2024 zero.kwok@foxmail.com
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
#   --show      仅显示执行命令，而不做任何改变
#   -a,--all    添加未跟踪的文件以及已修改的文件
#   -s,--src    要推送的本地仓库中的 分支 或 标签
#   -p,--push   仅执行推送动作, 将忽略 --all 以及 commit
#   commit      提交消息

import os
import gwalk
import argparse

class ResultError(RuntimeError):  
    def __init__(self, message, ecode):  
        super().__init__(message)  
        self.ecode = ecode  

def execute(commands:str, onlyShow:bool=False):
   gwalk.cprint(commands, 'green')
   if onlyShow:
      return
   code = gwalk.RepoHandler.execute(commands)
   if code != 0:
      raise ResultError(f'Run: {commands}', code)

if __name__ == '__main__':
   try:
      parser = argparse.ArgumentParser()
      parser.add_argument('-a', '--all', action='store_true')
      parser.add_argument('-s', '--src', action='store', default=None)
      parser.add_argument('-p', '--push', action='store_true')
      parser.add_argument('--show', action='store_true')
      parser.add_argument('commit', nargs=argparse.REMAINDER)
      args = parser.parse_args()

      args.commit = ' '.join(args.commit)

      if not gwalk.RepoWalk.isRepo(os.getcwd()):
         gwalk.cprint(f'This is not an valid git repository.', 'red')
         exit(1)

      repo = gwalk.RepoStatus(os.getcwd()).load()

      if args.src is None:
         args.src = repo.repo.active_branch.name

      if args.push:
         for r in repo.repo.remotes:
            execute(f'git push {r.name} {args.src}', args.show)
         exit(0)

      if repo.match('clean'):
         gwalk.cprint(f'The git repository is clean.', 'green')
         exit(0)
      execute('git status -s --untracked-files=normal')

      if repo.match('dirty' if args.all else 'modified'):
         execute('git add -A' if args.all else 'git add -u', args.show)
         if args.commit:
            execute(f'git commit -m "{args.commit}"', args.show)
         else:
            execute(f'git commit', args.show)
         for r in repo.repo.remotes:
            execute(f'git push {r.name} {args.src}', args.show)
      exit(0)
   except ResultError as e:
      exit(e.ecode)