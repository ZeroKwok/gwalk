#! python
# -*- coding: utf-8 -*-
#
# This file is part of the gwalk project.
# Copyright (c) 2020-2025 zero <zero.kwok@foxmail.com>
#
# For the full copyright and license information, please view the LICENSE
# file that was distributed with this source code.

import os
import argparse
from gwalk import gwalk

def main():
    parser = argparse.ArgumentParser(
        description='''A Git helper tool that combines `fetch` and `pull` operations.

This tool helps streamline common Git operations by:
- Fetching updates from all remote repositories (unless -q is used)
- Pulling changes from the default remote (origin or first available) to the current branch''',
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument('-q', '--quick', action='store_true',
                       help='quick mode: skip fetching from remote repositories\n'
                            'and only perform git pull')
    parser.add_argument('--rebase', action='store_true',
                       help='use rebase instead of merge when pulling\n'
                            '(equivalent to git pull --rebase)')
    args = parser.parse_args()

    if not gwalk.RepoWalk.isRepo(os.getcwd()):
        gwalk.cprint(f'This is not an valid git repository.', 'red')
        exit(1)

    repo   = gwalk.git.Repo(os.getcwd(), search_parent_directories=True)
    branch = repo.active_branch.name

    if not args.quick:
        for remote in repo.remotes:
            cmd = f'git fetch {remote.name}'
            gwalk.cprint(f'> {cmd}', 'green')
            if gwalk.RepoHandler.execute(cmd) != 0:
                gwalk.cprint(f'> Warning: remote "{remote.name}" fetch failed', 'yellow')

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


if __name__ == '__main__':
    main()