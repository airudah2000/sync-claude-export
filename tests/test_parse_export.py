"""Unit tests for parse_export.py, using only synthetic fixture data
constructed inline -- never real personal export data.

Run with: python -m unittest discover -s tests -v
(stdlib unittest only -- this project stays dependency-free; pytest isn't
required and wasn't installed in the dev environment this suite was written
against.)
"""

import argparse
import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import parse_export as pe


def _run_quiet(func, args):
    """Call a cmd_* function while swallowing its stdout/stderr, returning
    (return_code, stdout_text, stderr_text)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = func(args)
    return rc, out.getvalue(), err.getvalue()


class TestTitleFallback(unittest.TestCase):
    def test_real_title_used_as_is(self):
        convo = {"uuid": "abc12345", "name": "My Real Title", "chat_messages": []}
        fields = pe.extract_conversation_fields(convo)
        self.assertEqual(fields["title"], "My Real Title")

    def test_missing_title_falls_back_to_first_human_line(self):
        convo = {
            "uuid": "abc12345",
            "chat_messages": [
                {"sender": "human", "text": "What's the weather like?"},
                {"sender": "assistant", "text": "Sunny."},
            ],
        }
        fields = pe.extract_conversation_fields(convo)
        self.assertEqual(fields["title"], "What's the weather like?")

    def test_missing_title_skips_log_wrapper_lines(self):
        convo = {
            "uuid": "abc12345",
            "chat_messages": [
                {"sender": "human", "text": "<command-name>/mcp</command-name>"},
                {"sender": "human", "text": "Real question here"},
            ],
        }
        fields = pe.extract_conversation_fields(convo)
        self.assertEqual(fields["title"], "Real question here")

    def test_no_usable_text_falls_back_to_generic(self):
        convo = {"uuid": "abc12345", "chat_messages": []}
        fields = pe.extract_conversation_fields(convo)
        self.assertEqual(fields["title"], "Untitled conversation")


class TestManifestUpsert(unittest.TestCase):
    def test_new_entry(self):
        manifest = {}
        status = pe.manifest_upsert(manifest, "k1", "Title", "Proj", "src", "c1", "u1", Path("a/b.md"))
        self.assertEqual(status, "new")
        self.assertIn("k1", manifest)

    def test_unchanged_when_nothing_differs(self):
        manifest = {}
        pe.manifest_upsert(manifest, "k1", "Title", "Proj", "src", "c1", "u1", Path("a/b.md"))
        status = pe.manifest_upsert(manifest, "k1", "Title", "Proj", "src", "c1", "u1", Path("a/b.md"))
        self.assertEqual(status, "unchanged")

    def test_updated_when_updated_timestamp_changes(self):
        manifest = {}
        pe.manifest_upsert(manifest, "k1", "Title", "Proj", "src", "c1", "u1", Path("a/b.md"))
        status = pe.manifest_upsert(manifest, "k1", "Title", "Proj", "src", "c1", "u2", Path("a/b.md"))
        self.assertEqual(status, "updated")

    def test_updated_when_related_projects_changes(self):
        manifest = {}
        pe.manifest_upsert(manifest, "k1", "Title", "Proj", "src", "c1", "u1", Path("a/b.md"), related_projects=[])
        status = pe.manifest_upsert(manifest, "k1", "Title", "Proj", "src", "c1", "u1", Path("a/b.md"), related_projects=["Other"])
        self.assertEqual(status, "updated")


class TestFindRelatedProjects(unittest.TestCase):
    def setUp(self):
        self.patterns = pe.compile_project_patterns([
            ("p1", "RMAS"),
            ("p2", "My professional profile"),
        ])

    def test_short_name_single_incidental_mention_in_turns_is_ignored(self):
        # Real false positive this was written to fix: a short/acronym-like
        # name appearing once, only deep in the conversation, not the title
        # or summary -- should NOT be flagged.
        related = pe.find_related_projects(
            "Immigration strategy", "", "My SC clearance came via RMAS work.", self.patterns)
        self.assertNotIn("RMAS", related)

    def test_short_name_repeated_mentions_in_turns_is_flagged(self):
        text = "RMAS prep continues. RMAS interview next week. Studying RMAS syllabus."
        related = pe.find_related_projects("Sandhurst prep", "", text, self.patterns)
        self.assertIn("RMAS", related)

    def test_short_name_in_title_is_flagged_on_single_mention(self):
        related = pe.find_related_projects("RMAS interview prep", "", "one mention here", self.patterns)
        self.assertIn("RMAS", related)

    def test_long_name_single_mention_in_turns_is_flagged(self):
        related = pe.find_related_projects(
            "Career chat", "", "Let's update My professional profile with this.", self.patterns)
        self.assertIn("My professional profile", related)

    def test_word_boundary_prevents_substring_match(self):
        patterns = pe.compile_project_patterns([("p3", "Sky")])
        related = pe.find_related_projects("Skydiving trip", "", "Skydiving was fun, skyscrapers too.", patterns)
        self.assertEqual(related, [])

    def test_excluded_name_never_returned(self):
        related = pe.find_related_projects("RMAS RMAS RMAS", "", "", self.patterns, exclude_name="RMAS")
        self.assertNotIn("RMAS", related)


class TestDesignChatsParsing(unittest.TestCase):
    def _write_chat(self, chats_dir, filename, uuid, title, project_name, project_uuid, messages):
        chat = {
            "uuid": uuid,
            "title": title,
            "project": {"name": project_name, "uuid": project_uuid} if project_name else None,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-02T00:00:00Z",
            "messages": messages,
        }
        (chats_dir / filename).write_text(json.dumps(chat), encoding="utf-8")

    def _parse(self, chats_dir, parsed_dir, manifest_path):
        args = SimpleNamespace(chats_dir=str(chats_dir), parsed_dir=str(parsed_dir), manifest=str(manifest_path))
        return _run_quiet(pe.cmd_parse_design_chats, args)

    def test_nested_string_content_unwrapped(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            chats_dir, parsed_dir = td / "chats", td / "parsed"
            chats_dir.mkdir()
            self._write_chat(chats_dir, "c1.json", "cid00001", "A Real Title", None, None, [
                {"role": "user", "content": {"content": "Hello from a string-nested body"}},
            ])
            self._parse(chats_dir, parsed_dir, td / "manifest.json")
            md_files = list((parsed_dir / "design-chats" / "standalone").glob("*.md"))
            self.assertEqual(len(md_files), 1)
            self.assertIn("Hello from a string-nested body", md_files[0].read_text(encoding="utf-8"))

    def test_nested_list_content_unwrapped(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            chats_dir, parsed_dir = td / "chats", td / "parsed"
            chats_dir.mkdir()
            self._write_chat(chats_dir, "c1.json", "cid00002", "Another Title", None, None, [
                {"role": "user", "content": {"content": [{"type": "text", "text": "Hello from a list-nested body"}]}},
            ])
            self._parse(chats_dir, parsed_dir, td / "manifest.json")
            md_files = list((parsed_dir / "design-chats" / "standalone").glob("*.md"))
            self.assertEqual(len(md_files), 1)
            self.assertIn("Hello from a list-nested body", md_files[0].read_text(encoding="utf-8"))

    def test_same_project_name_different_uuid_no_collision(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            chats_dir, parsed_dir = td / "chats", td / "parsed"
            chats_dir.mkdir()
            self._write_chat(chats_dir, "c1.json", "cid00003", "Chat One", "Shared Name", "uuid-aaaa1111", [
                {"role": "user", "content": {"content": "first"}},
            ])
            self._write_chat(chats_dir, "c2.json", "cid00004", "Chat Two", "Shared Name", "uuid-bbbb2222", [
                {"role": "user", "content": {"content": "second"}},
            ])
            manifest_path = td / "manifest.json"
            self._parse(chats_dir, parsed_dir, manifest_path)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            paths = {v["path"] for v in manifest.values()}
            self.assertEqual(len(paths), 2, f"expected two distinct paths, got {paths}")
            # both should live under distinct uuid-suffixed folders, not one shared "Shared-Name" folder
            folders = {str(Path(p).parent) for p in paths}
            self.assertEqual(len(folders), 2)

    def test_malformed_file_is_skipped_not_fatal(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            chats_dir, parsed_dir = td / "chats", td / "parsed"
            chats_dir.mkdir()
            self._write_chat(chats_dir, "good.json", "cidgood1", "Good Chat", None, None, [
                {"role": "user", "content": {"content": "valid content"}},
            ])
            (chats_dir / "bad.json").write_text("{not valid json!!", encoding="utf-8")
            manifest_path = td / "manifest.json"
            rc, out, err = self._parse(chats_dir, parsed_dir, manifest_path)
            self.assertEqual(rc, 0)
            self.assertIn("bad.json", err)
            counts = json.loads(out)
            self.assertEqual(counts["skipped_errors"], 1)
            self.assertEqual(counts["new"], 1)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(len(manifest), 1)


class TestProjectsParsing(unittest.TestCase):
    def test_malformed_project_file_is_skipped_not_fatal(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            projects_dir, parsed_dir = td / "projects", td / "parsed"
            projects_dir.mkdir()
            good = {
                "uuid": "proj0001", "name": "Good Project",
                "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-02T00:00:00Z",
                "docs": [],
            }
            (projects_dir / "good.json").write_text(json.dumps(good), encoding="utf-8")
            (projects_dir / "bad.json").write_text("{not valid json!!", encoding="utf-8")

            manifest_path = td / "manifest.json"
            args = SimpleNamespace(projects_dir=str(projects_dir), parsed_dir=str(parsed_dir), manifest=str(manifest_path))
            rc, out, err = _run_quiet(pe.cmd_parse_projects, args)
            self.assertEqual(rc, 0)
            self.assertIn("bad.json", err)
            counts = json.loads(out)
            self.assertEqual(counts["skipped_errors"], 1)
            self.assertEqual(counts["new"], 1)


if __name__ == "__main__":
    unittest.main()
