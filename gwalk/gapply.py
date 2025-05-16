#! python
# -*- coding: utf-8 -*-
#
# This file is part of the gwalk project.
# Copyright (c) 2020-2025 zero <zero.kwok@foxmail.com>
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

def extract_from_patch(patch_file):
    metadata = {}
    with open(patch_file, "r", encoding="utf-8") as file:
        last_line = None
        subject_lines = []
        subject_is_join = False
        newfile_lines = []
        for line in file:
            if 'subject' not in metadata:
                # Subject: [PATCH] feat(window-state): Move window state management to a new
                #  module
                # Subject: [PATCH 05/45] Add .env.developmen
                if line.startswith("Subject:"):
                    subject_is_join = True
                    line = line[len("Subject:") :].strip()                # Remove "Subject:"
                    line = re.sub(r'^\[PATCH\] ', '', line)               # Remove [PATCH] 
                    line = re.sub(r'^\[PATCH [0-9]+/[0-9]+\] ', '', line) # Remove [PATCH X/Y]
                    subject_lines.append(decoded_subject(line))
                elif subject_is_join:
                    if line.startswith((' ', '\t')):
                        subject_lines.append(decoded_subject(line.strip()))
                    else:
                        subject_is_join = False
                        metadata['subject'] = ''.join(subject_lines)

            elif line.startswith('new file mode '):
                # diff --git a/.gitignore b/.gitignore
                # new file mode 100644
                # index 0000000..8296128
                old_file, new_file = re.search(r"diff --git a/(.+?) b/(.+)", last_line).groups()
                assert old_file == new_file
                newfile_lines.append(new_file)
            
            elif line.startswith('rename to '):
                # diff --git a/src/shared/utils/window-state.js b/src/main/window-state.js
                # similarity index 100%
                # rename from src/shared/utils/window-state.js
                # rename to src/main/window-state.js
                newfile_lines.append(line[len('rename to '):])

            last_line = line
        metadata["newfiles"] = newfile_lines

    return metadata

def git_run(cmd, fallback, dry_run=False):
    if dry_run:
        gwalk.cprint(f'(dry-run) > {cmd}', 'cyan')
        return

    gwalk.cprint(f'> {cmd}', 'green')
    code = gwalk.RepoHandler.execute(cmd)
    if code != 0 and  fallback:
        fallback(code, cmd)

def apply_patch(patch_file, dry_run=False):
    def fallback(code, cmd):
        gwalk.cprint(f"Failed to apply patch: {patch_file}, please operate manually.", 'red')
        sys.exit(code)
    git_run(f'git apply -v "{patch_file}"', fallback, dry_run)

def stage_changes(newfiles, dry_run=False):
    def fallback(code, cmd):
        gwalk.cprint(f"Failed to stage changes, please operate manually.", 'red')
        sys.exit(code)
    git_run(f'git add -u', fallback, dry_run)

    cmdlist = [f'git add "{f}"' for f in newfiles]
    for cmd in cmdlist:
        git_run(cmd, fallback, dry_run)

def commit_changes(subject, dry_run=False):
    def fallback(code, cmd):
        gwalk.cprint(f"Failed to create commit, please operate manually.", 'red')
        sys.exit(code)
    git_run(f'git commit -m "{subject}"', fallback, dry_run)

def confirm_delete(patch_file):
    while True:
        answer = input(f"Delete patch file '{patch_file}'? [y/N]: ").strip().lower()
        if answer in ('', 'n', 'no'):
            return False
        elif answer in ('y', 'yes'):
            return True
        print("Please answer 'y' or 'n'")

def delete_patch_file(patch_file, dry_run=False):
    if dry_run:
        gwalk.cprint(f'(dry-run) Would delete patch file: {patch_file}', 'cyan')
        return
    
    if confirm_delete(patch_file):
        try:
            os.remove(patch_file)
            gwalk.cprint(f"Deleted patch file: {patch_file}", 'green')
        except OSError as e:
            gwalk.cprint(f"Failed to delete patch file: {e}", 'red')

def main():
    parser = argparse.ArgumentParser(
        description='A Git helper tool that combines `git apply` and `git commit` operations.',
        formatter_class=argparse.RawTextHelpFormatter,
        epilog='Note: It is recommended to use git format-patch style—it makes things easier!'
    )
    parser.add_argument('patch_files', nargs='+', metavar='patch_file',
                       help='one or more patch files to apply\n')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='show detailed progress information')
    parser.add_argument('-n', '--dry-run', action='store_true',
                       help='show what would be done without actually doing it')
    parser.add_argument('-d', '--delete', action='store_true',
                       help='delete patch file after successful application (with confirmation)')
    args = parser.parse_args()

    for patch_file in args.patch_files:
        if not os.path.isfile(patch_file):
            gwalk.cprint(f"Patch file not found: {patch_file}", 'red')
            sys.exit(1)
        gwalk.cprint(f"Patch: {patch_file}", 'magenta')

        metadata = extract_from_patch(patch_file)

        if args.verbose or args.dry_run:
            if 'subject' not in metadata:
                gwalk.cprint(f"Subject not found, you'll need to enter it later", 'yellow')

            for key in metadata:
                if isinstance(metadata[key], str):
                    gwalk.cprint(f" - {key: <8}: {metadata[key]}", 'white')
                elif isinstance(metadata[key], list):
                    gwalk.cprint(f" - {key: <8}: ", 'white')
                    for item in metadata[key]:
                        gwalk.cprint(f"  - {item}", 'white')

        apply_patch(patch_file, args.dry_run)
        stage_changes(metadata.get("newfiles", []), args.dry_run)
        commit_changes(metadata.get("subject", None), args.dry_run)
        
        if args.delete:
            delete_patch_file(patch_file, args.dry_run)

if __name__ == "__main__":
    main()
