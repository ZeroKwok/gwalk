#! python
# -*- coding: utf-8 -*-
#
# This file is part of the gwalk project.
# Copyright (c) 2020-2024 zero <zero.kwok@foxmail.com>
#
# For the full copyright and license information, please view the LICENSE
# file that was distributed with this source code.
#
# gapply.py (git apply patch and create commit)
#
# Syntax:
#   gapply.py [-h] <patch_file ...>
#

import os
import re
import sys
import argparse
from gwalk import gwalk
from email.header import decode_header

def decoded_subject(line):
    if line.startswith('=?'):
        try:
            decoded_parts = decode_header(line)
            return ''.join(
                part[0].decode(part[1] or 'utf8') if isinstance(part[0], bytes) 
                else str(part[0])
                for part in decoded_parts)
        except:
            return line
    return line

def extract_subject_from_patch(patch_file):
    subject_lines = []
    with open(patch_file, "r", encoding="utf-8") as file:
        is_join = False
        for line in file:
            if line.startswith("Subject:"):
                is_join = True
                line = line[len("Subject:") :].strip()               # Remove "Subject:"
                line = re.sub(r'\[PATCH [0-9]+/[0-9]+\] ', '', line) # Remove [PATCH X/Y]
                subject_lines.append(decoded_subject(line))
            elif is_join:
                if line.startswith((' ', '\t')):
                    subject_lines.append(decoded_subject(line.strip()))
                else:
                    is_join = False
                    break
        return ''.join(subject_lines)
    return None

def extract_subject_from_filename(patch_file):
    filename = os.path.splitext(os.path.basename(patch_file))[0]
    subject = re.sub(r'^[0-9]+-', '', filename)
    subject = re.sub(r'\.patch$', '', subject)
    subject = subject.replace('-', ' ')
    return subject

def apply_patch(patch_file, dry_run=False):
    cmd = f'git apply -v "{patch_file}"'
    if dry_run:
        gwalk.cprint(f'(dry-run) > {cmd}', 'cyan')
        return

    gwalk.cprint(f'> {cmd}', 'green')
    result = gwalk.RepoHandler.execute(cmd)
    if result != 0:
        gwalk.cprint(f"Failed to apply patch: {patch_file}", 'red')
        sys.exit(result)

def stage_changes(dry_run=False):
    cmd = f'git add -A'
    if dry_run:
        gwalk.cprint(f'(dry-run) > {cmd}', 'cyan')
        return

    gwalk.cprint(f'> {cmd}', 'green')
    result = gwalk.RepoHandler.execute(cmd)
    if result != 0:
        gwalk.cprint(f"Failed to stage changes.", 'red')
        sys.exit(result)

def commit_changes(subject, dry_run=False):
    cmd = f'git commit -m "{subject}"'
    if dry_run:
        gwalk.cprint(f'(dry-run) > {cmd}', 'cyan')
        return

    gwalk.cprint(f'> {cmd}', 'green')
    result = gwalk.RepoHandler.execute(cmd)
    if result != 0:
        gwalk.cprint(f"Failed to create commit.", 'red')
        sys.exit(result)

def main():
    parser = argparse.ArgumentParser(
        description='A Git helper tool that combines `git apply` and `git commit` operations.',
        formatter_class=argparse.RawTextHelpFormatter,
        epilog='Note: Patches should be in git format-patch style'
    )
    parser.add_argument('patch_files', nargs='+', metavar='patch_file',
                       help='one or more patch files to apply\n')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='show detailed progress information')
    parser.add_argument('-n', '--dry-run', action='store_true',
                       help='show what would be done without actually doing it')
    args = parser.parse_args()

    for patch_file in args.patch_files:
        if not os.path.isfile(patch_file):
            gwalk.cprint(f"Patch file not found: {patch_file}", 'red')
            sys.exit(1)
        gwalk.cprint(f"Patch: {patch_file}", 'magenta')

        subject = extract_subject_from_patch(patch_file)
        if not subject:
            subject = extract_subject_from_filename(patch_file)
            if args.verbose or args.dry_run:
                gwalk.cprint(f"Using filename-based subject: {subject}", 'yellow')

        apply_patch(patch_file, args.dry_run)
        stage_changes(args.dry_run)
        commit_changes(subject, args.dry_run)

if __name__ == "__main__":
    main()