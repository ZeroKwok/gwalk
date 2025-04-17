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

def apply_patch(patch_file):
    cmd = f'git apply -v "{patch_file}"'
    gwalk.cprint(f'> {cmd}', 'green')
    result = gwalk.RepoHandler.execute(cmd)
    if result != 0:
        gwalk.cprint(f"Failed to apply patch: {patch_file}", 'red')
        sys.exit(result)

def stage_changes():
    cmd = f'git add -u'
    gwalk.cprint(f'> {cmd}', 'green')
    result = gwalk.RepoHandler.execute(cmd)
    if result != 0:
        gwalk.cprint(f"Failed to stage changes.", 'red')
        sys.exit(result)

def commit_changes(subject):
    cmd = f'git commit -m "{subject}"'
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
    args = parser.parse_args()

    for patch_file in args.patch_files:
        if not os.path.isfile(patch_file):
            gwalk.cprint(f"Patch file not found: {patch_file}", 'red')
            sys.exit(1)

        if args.verbose:
            gwalk.cprint(f"Processing patch: {patch_file}", 'green')

        subject = extract_subject_from_patch(patch_file)
        if not subject:
            subject = extract_subject_from_filename(patch_file)
            if args.verbose:
                gwalk.cprint(f"Using filename-based subject: {subject}", 'yellow')

        apply_patch(patch_file)
        stage_changes()
        commit_changes(subject)

if __name__ == "__main__":
    main()