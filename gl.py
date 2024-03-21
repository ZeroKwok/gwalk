#! python
# -*- coding: utf-8 -*-
#
# This file is part of the gwalk distribution.
# Copyright (c) 2020-2024 zero.kwok@foxmail.com

import os
import gwalk     
import argparse

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--rebase', action='store_true')
    args = parser.parse_args()

    if not gwalk.RepoWalk.isRepo(os.getcwd()):
        gwalk.cprint(f'This is not an valid git repository.', 'red')
        exit(1)

    repo   = gwalk.git.Repo(os.getcwd())
    branch = repo.active_branch.name
    remote = 'origin'
    if not remote in repo.remotes:
        if len(repo.remotes) > 0:
            remote = repo.remotes[0].name

    rebase = ''
    if args.rebase:
        rebase = '--rebase'
    
    cmd = f'git pull {remote} {branch} {rebase}'
    gwalk.cprint(f'> {cmd}', 'green')
    exit(gwalk.RepoHandler.execute(cmd))
