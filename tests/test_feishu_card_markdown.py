import unittest

from bot.cards import build_execution_card, build_markdown_card
from bot.execution_transcript import ExecutionReplySegment
from bot.feishu_card_markdown import (
    sanitize_runtime_markdown_for_feishu_card,
    sanitize_terminal_result_markdown_for_feishu_json2,
)


class FeishuCardMarkdownTests(unittest.TestCase):
    def test_terminal_result_hardens_ordered_list_continuation_soft_break(self) -> None:
        text = "1. **明确一次性任务**\n   用精确时间："

        self.assertEqual(
            sanitize_terminal_result_markdown_for_feishu_json2(text),
            "1. **明确一次性任务**<br>\n   用精确时间：",
        )

    def test_runtime_card_hardens_ordered_list_continuation_soft_break(self) -> None:
        text = "1. **明确一次性任务**\n   用精确时间："

        self.assertEqual(
            sanitize_runtime_markdown_for_feishu_card(text),
            "1. **明确一次性任务**<br>\n   用精确时间：",
        )

    def test_markdown_card_builder_hardens_list_continuation_soft_break(self) -> None:
        card = build_markdown_card(
            "Codex 帮助",
            "1. **明确一次性任务**\n   用精确时间：",
        )

        self.assertEqual(
            card["elements"][0]["content"],
            "1. **明确一次性任务**<br>\n   用精确时间：",
        )

    def test_execution_card_builder_hardens_list_continuation_soft_break(self) -> None:
        card = build_execution_card(
            "1. **执行步骤**\n   检查状态",
            [ExecutionReplySegment("assistant", "1. **回复步骤**\n   输出结论")],
            running=False,
        )

        markdown_blocks = _collect_markdown_blocks(card)
        self.assertIn("1. **执行步骤**<br>\n   检查状态", markdown_blocks)
        self.assertIn("1. **回复步骤**<br>\n   输出结论", markdown_blocks)

    def test_list_continuation_hardening_does_not_rewrite_nested_lists(self) -> None:
        text = "1. 外层\n    - 内层\n2. 另一项"

        self.assertEqual(
            sanitize_terminal_result_markdown_for_feishu_json2(text),
            text,
        )

    def test_list_continuation_hardening_keeps_indented_code_like_list_text(self) -> None:
        text = "    1. code-like line\n       still code"

        self.assertEqual(
            sanitize_terminal_result_markdown_for_feishu_json2(text),
            text,
        )

    def test_nested_list_item_continuation_can_be_hardened(self) -> None:
        text = "1. outer\n    1. inner\n       detail"

        self.assertEqual(
            sanitize_terminal_result_markdown_for_feishu_json2(text),
            "1. outer\n    1. inner<br>\n       detail",
        )

    def test_list_continuation_hardening_skips_fenced_code_blocks(self) -> None:
        text = (
            "```markdown\n"
            "1. **示例**\n"
            "   不应改写\n"
            "```\n"
            "1. **示例**\n"
            "   应该换行"
        )

        self.assertEqual(
            sanitize_terminal_result_markdown_for_feishu_json2(text),
            (
                "```markdown\n"
                "1. **示例**\n"
                "   不应改写\n"
                "```\n\n"
                "1. **示例**<br>\n"
                "   应该换行"
            ),
        )


def _collect_markdown_blocks(node: object) -> list[str]:
    if isinstance(node, dict):
        blocks: list[str] = []
        if node.get("tag") == "markdown":
            blocks.append(str(node.get("content", "")))
        for value in node.values():
            blocks.extend(_collect_markdown_blocks(value))
        return blocks
    if isinstance(node, list):
        blocks: list[str] = []
        for item in node:
            blocks.extend(_collect_markdown_blocks(item))
        return blocks
    return []


if __name__ == "__main__":
    unittest.main()
