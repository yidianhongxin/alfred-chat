#!/usr/bin/env python3
"""Regression tests for Alfred Chat's local Obsidian tools."""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
LOCAL_AGENT = REPO / "Workflow" / "local_agent.py"
TEST_ROOT = Path("/Users/DRLer/Desktop")


def load_local_agent():
    spec = importlib.util.spec_from_file_location("local_agent_under_test", LOCAL_AGENT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ObsidianLocalAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.agent = load_local_agent()

    def setUp(self) -> None:
        self.test_vault = Path(tempfile.mkdtemp(prefix="alfred-chat-test-vault-", dir=TEST_ROOT))
        (self.test_vault / "10.DL日记").mkdir(parents=True)
        (self.test_vault / "10.DL日记" / "2026-06-16.md").write_text("老日记内容", encoding="utf-8")
        (self.test_vault / "10.DL日记" / "2026-06-17.md").write_text("最新日记内容", encoding="utf-8")
        os.environ["obsidian_vault_path"] = str(self.test_vault)

    def tearDown(self) -> None:
        shutil.rmtree(self.test_vault, ignore_errors=True)
        os.environ.pop("obsidian_vault_path", None)

    def test_reports_obsidian_read_capability(self) -> None:
        action = self.agent.parse_intent("你能读到OB库的内容么？")
        self.assertIsNotNone(action)
        self.assertEqual(action.type, "obsidian_status")

        status, body, _ = self.agent.execute(action)
        self.assertEqual(status, "success")
        self.assertIn("能读到", body)
        self.assertIn("2 篇日记", body)

    def test_browses_latest_diary_entry(self) -> None:
        action = self.agent.parse_intent("翻阅一下OB库里的日记")
        self.assertIsNotNone(action)
        self.assertEqual(action.type, "obsidian_diary_browse")

        status, body, _ = self.agent.execute(action)
        self.assertEqual(status, "success")
        self.assertIn("2026-06-17.md", body)
        self.assertIn("最新日记内容", body)

    def test_reads_recent_diary_entries(self) -> None:
        action = self.agent.parse_intent("读下最近2天日记")
        self.assertIsNotNone(action)
        self.assertEqual(action.type, "obsidian_diary_recent")
        self.assertEqual(action.count, 2)

        status, body, _ = self.agent.execute(action)
        self.assertEqual(status, "success")
        self.assertIn("最新日记内容", body)
        self.assertIn("老日记内容", body)

    def test_rejects_diary_browse_outside_allowed_home(self) -> None:
        outside_vault = Path(tempfile.mkdtemp(prefix="alfred-chat-outside-vault-"))
        try:
            (outside_vault / "10.DL日记").mkdir()
            (outside_vault / "10.DL日记" / "2026-06-17.md").write_text("不应读取", encoding="utf-8")
            os.environ["obsidian_vault_path"] = str(outside_vault)

            action = self.agent.parse_intent("翻阅一下OB库里的日记")
            self.assertIsNotNone(action)
            status, body, _ = self.agent.execute(action)

            self.assertEqual(status, "error")
            self.assertIn("超出允许范围", body)
        finally:
            shutil.rmtree(outside_vault, ignore_errors=True)

    def test_writes_file_inside_obsidian_vault(self) -> None:
        action = self.agent.parse_intent("写入OB 0.inbox/test.md 内容：hello ob")
        self.assertIsNotNone(action)
        self.assertEqual(action.type, "obsidian_write")

        status, body, _ = self.agent.execute(action)
        self.assertEqual(status, "success")
        self.assertIn("已写入 OB", body)
        self.assertEqual((self.test_vault / "0.inbox" / "test.md").read_text(encoding="utf-8"), "hello ob")

    def test_lists_all_markdown_articles_in_inbox(self) -> None:
        inbox = self.test_vault / "0.inbox"
        inbox.mkdir()
        for name in ["a.md", "b.md", "c.md"]:
            (inbox / name).write_text(f"# {name}", encoding="utf-8")
        (inbox / "ignore.txt").write_text("not article", encoding="utf-8")

        action = self.agent.parse_intent("列出0.inbox里的文章")
        self.assertIsNotNone(action)
        self.assertEqual(action.type, "obsidian_list")

        status, body, footer = self.agent.execute(action)
        self.assertEqual(status, "success")
        self.assertIn("3 篇", body)
        self.assertIn("0.inbox/a.md", body)
        self.assertIn("0.inbox/b.md", body)
        self.assertIn("0.inbox/c.md", body)
        self.assertNotIn("ignore.txt", body)
        self.assertIn("3 篇", footer)


    def test_creates_inbox_note_without_ob_prefix(self) -> None:
        action = self.agent.parse_intent("新建一篇 0.inbox/中国人均寿命2025.md")
        self.assertIsNotNone(action)
        self.assertEqual(action.type, "obsidian_write")
        self.assertEqual(action.path, "0.inbox/中国人均寿命2025.md")

        status, body, _ = self.agent.execute(action)
        self.assertEqual(status, "success")
        self.assertIn("已写入 OB", body)
        target = self.test_vault / "0.inbox" / "中国人均寿命2025.md"
        self.assertTrue(target.exists())
        self.assertEqual(target.read_text(encoding="utf-8"), "")

    def test_strips_一篇_prefix_from_obsidian_path(self) -> None:
        path = self.agent.strip_target_path_noise("一篇 0.inbox/foo.md")
        self.assertEqual(path, "0.inbox/foo.md")
        self.assertTrue(self.agent.looks_like_obsidian_relative_path(path))

    def test_write_file_tool_redirects_obsidian_inbox_path(self) -> None:
        action = self.agent.action_from_tool_call(
            {
                "tool": "write_file",
                "args": {"path": "一篇 0.inbox/tool.md", "content": "via tool"},
            }
        )
        self.assertIsNotNone(action)
        self.assertEqual(action.type, "obsidian_write")
        self.assertEqual(action.path, "0.inbox/tool.md")

        status, _, _ = self.agent.execute(action)
        self.assertEqual(status, "success")
        self.assertEqual(
            (self.test_vault / "0.inbox" / "tool.md").read_text(encoding="utf-8"),
            "via tool",
        )


if __name__ == "__main__":
    unittest.main()
