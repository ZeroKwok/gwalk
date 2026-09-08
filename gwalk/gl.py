#! python
# -*- coding: utf-8 -*-
#
# This file is part of the gwalk project.
# Copyright (c) 2020-2025 zero <zero.kwok@foxmail.com>
#
# For the full copyright and license information, please view the LICENSE
# file that was distributed with this source code.

import os
import sys
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
                       help='quick mode: skip maintenance; with -f fetch only without maintenance, otherwise only pull')
    parser.add_argument('-f', '--fetch', action='store_true',
                       help='fetch all remotes, without pull')
    parser.add_argument('--rebase', action='store_true',
                       help='use rebase instead of merge when pulling\n'
                            '(equivalent to git pull --rebase)')
    args = parser.parse_args()

    try:
        repo = gwalk.git.Repo(os.getcwd(), search_parent_directories=True)
    except (gwalk.git.exc.InvalidGitRepositoryError, gwalk.git.exc.NoSuchPathError):
        gwalk.cprint(f'This is not an valid git repository.', 'red')
        sys.exit(1)

    if args.quick and not args.fetch:
        if repo.bare:
            sys.exit(0)
    else:
        fetch_code = fetch(quick=args.quick)
        if args.fetch or repo.bare:
            sys.exit(fetch_code)

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
    sys.exit(gwalk.RepoHandler.execute(cmd))


def fetch(quick=False):
    """Fetch all remotes, then optionally run maintenance synchronously."""
    # Fetch can otherwise start detached maintenance/repack in the background.
    # Keep both operations in the foreground to avoid Windows pack-file races.
    commands = ['git fetch --all --no-auto-maintenance']
    if not quick:
        # Quick mode skips maintenance. Maintenance runs a full cruft gc that
        # can fail on Windows when deleting still-mapped pack files.
        commands.append('git maintenance run --auto --no-quiet')
    code = 0
    for cmd in commands:
        gwalk.cprint(f'> {cmd}', 'green')
        result = gwalk.RepoHandler.execute(cmd)
        if result != 0:
            code = code or result
            gwalk.cprint(f'> Warning: {cmd} failed', 'yellow')
    return code


if __name__ == '__main__':
    main()
