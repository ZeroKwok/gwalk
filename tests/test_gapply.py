import os

import pytest

import gwalk.gapply


pathTest = os.path.dirname(os.path.abspath(__file__))
pathSimples = os.path.join(pathTest, "simples")


class TestExtractor:
    def pathchs(self, path):
        for root, dirs, files in os.walk(pathSimples):
            for file in files:
                if file.endswith(".patch"):
                    yield os.path.join(root, file)

    def test_extract_from_existing_patch_fixtures(self):
        for file in self.pathchs(pathSimples):
            metadata = gwalk.gapply.extract_from_patch(file)
            assert metadata is not None
            assert metadata["subject"] is not None

            if "newfiles" in metadata:
                assert type(metadata["newfiles"]) == list
                assert len(metadata["newfiles"]) >= 0

    def test_extract_subject_continuation_new_file_and_rename(self, tmp_path):
        patch = tmp_path / "sample.patch"
        patch.write_text(
            """From abc Mon Sep 17 00:00:00 2001
Subject: [PATCH 01/02] Add cache and
 settings

diff --git a/new.txt b/new.txt
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/new.txt
@@ -0,0 +1 @@
+new
diff --git a/old.txt b/new_name.txt
similarity index 100%
rename from old.txt
rename to new_name.txt
""",
            encoding="utf-8",
        )

        metadata = gwalk.gapply.extract_from_patch(str(patch))

        assert metadata["subject"] == "Add cache andsettings"
        assert metadata["newfiles"] == ["new.txt", "new_name.txt"]

    def test_decoded_subject_handles_plain_and_encoded_values(self):
        assert gwalk.gapply.decoded_subject("plain") == "plain"
        assert gwalk.gapply.decoded_subject("=?utf-8?b?5rWL6K+V?=") == "测试"


class TestGitRun:
    def test_git_run_dry_run_does_not_execute_or_call_fallback(self, monkeypatch):
        called = []

        monkeypatch.setattr(gwalk.gapply.gwalk.RepoHandler, "execute", lambda cmd: called.append(cmd) or 1)

        gwalk.gapply.git_run("git status", lambda code, cmd: called.append(("fallback", code, cmd)), dry_run=True)

        assert called == []

    def test_git_run_calls_fallback_on_failure(self, monkeypatch):
        fallback = []

        monkeypatch.setattr(gwalk.gapply.gwalk.RepoHandler, "execute", lambda cmd: 5)

        gwalk.gapply.git_run("git status", lambda code, cmd: fallback.append((code, cmd)))

        assert fallback == [(5, "git status")]

    def test_stage_changes_adds_update_and_new_files(self, monkeypatch):
        commands = []

        monkeypatch.setattr(gwalk.gapply, "git_run", lambda cmd, fallback, dry_run=False: commands.append((cmd, dry_run)))

        gwalk.gapply.stage_changes(["new.txt", "renamed.txt"], dry_run=True)

        assert commands == [
            ("git add -u", True),
            ('git add "new.txt"', True),
            ('git add "renamed.txt"', True),
        ]


class TestDeletePatch:
    def test_confirm_delete_accepts_yes_and_no(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda prompt: "yes")
        assert gwalk.gapply.confirm_delete("patch.patch") == True

        monkeypatch.setattr("builtins.input", lambda prompt: "")
        assert gwalk.gapply.confirm_delete("patch.patch") == False

    def test_delete_patch_file_force_removes_file(self, tmp_path):
        patch = tmp_path / "patch.patch"
        patch.write_text("patch\n", encoding="utf-8")

        gwalk.gapply.delete_patch_file(str(patch), force=True)

        assert not patch.exists()

    def test_delete_patch_file_dry_run_keeps_file(self, tmp_path):
        patch = tmp_path / "patch.patch"
        patch.write_text("patch\n", encoding="utf-8")

        gwalk.gapply.delete_patch_file(str(patch), dry_run=True, force=True)

        assert patch.exists()
