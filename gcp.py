#! python
# -*- coding: utf-8 -*-
#
# This file is part of the gwalk distribution.
# Copyright (c) 2020-2024 zero.kwok@foxmail.com
#
# gcp.py (git commit and push)
#
# 语法
#   gcp.py [-h] [-a|--all] [--show] [--push] []"提交信息"]
# 
# 示例
#   1. gcp.py "fix some bugs"
#      仅推送当前分支到所有远端, 不做提交
#      相当于执行: git add -u && git commit -m "提交信息" && git push {remotes} {branch}
#   2. gcp.py --push
#      仅推送当前分支到所有远端, 不做提交
#
# 选项
#   -a,--all 添加未跟踪的文件以及已修改的文件
#   --show   仅显示执行命令，而不做任何改变
#   --push   仅执行推送动作, 将忽略 --all 以及 commit
#   commit   提交消息

import os
import gwalk
import argparse

def execute(commands:str, onlyShow:bool=False) -> int:
   gwalk.cprint(commands, 'green')
   if onlyShow:
      return 0
   return gwalk.RepoHandler.execute(commands)

if __name__ == '__main__':
   parser = argparse.ArgumentParser()
   parser.add_argument('-a', '--all', action='store_true')
   parser.add_argument('--show', action='store_true')
   parser.add_argument('--push', action='store_true')
   parser.add_argument('commit', nargs='?')
   args = parser.parse_args()

   if not gwalk.RepoWalk.isRepo(os.getcwd()):
      gwalk.cprint(f'This is not an valid git repository.', 'red')
      exit(1)

   code = 0
   repo = gwalk.RepoStatus(os.getcwd()).load()
   branch = repo.repo.active_branch.name

   if args.push:
      for r in repo.repo.remotes:
         code += execute('git push {r.name} {branch}', )
      exit(code)

   if repo.match('clean'):
      gwalk.cprint(f'The git repository is clean.', 'green')
      exit(0)
   execute('git status -s --untracked-files=normal')

   if repo.match('dirty' if args.all else 'modified'):
      code += execute('git add -A' if args.all else 'git add -u', args.show)
      if args.commit:
         code += execute(f'git commit -m "{args.commit}"', args.show)
      else:
         code += execute(f'git commit', args.show)
      for r in repo.repo.remotes:
         code += execute(f'git push {r.name} {branch}', args.show)
   exit(code)
