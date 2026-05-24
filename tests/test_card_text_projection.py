import unittest

from bot.card_text_projection import (
    CardTextProjection,
    TERMINAL_RESULT_CARD_MARKER,
    can_render_terminal_result_card,
    project_interactive_card_text,
)
from bot.cards import build_execution_card, build_terminal_result_card
from bot.execution_transcript import ExecutionReplySegment
from bot.terminal_result_semantics import (
    TerminalHeading,
    TerminalStructureSummary,
    encode_terminal_structure_summary,
)


class CardTextProjectionTests(unittest.TestCase):
    def test_terminal_result_card_projects_authoritative_final_reply_text(self) -> None:
        projection = project_interactive_card_text(build_terminal_result_card("最终答复"))

        self.assertIsInstance(projection, CardTextProjection)
        self.assertTrue(projection.has_authoritative_final_reply)
        self.assertEqual(projection.final_reply_text, "最终答复")
        self.assertEqual(projection.text, "最终答复")
        self.assertIn("Codex", projection.visible_text)
        self.assertTrue(projection.final_reply_structure_summary.is_empty)

    def test_terminal_result_card_normalizes_markdown_links_to_visible_urls(self) -> None:
        projection = project_interactive_card_text(
            build_terminal_result_card(
                "- [示例地图链接](https://maps.example.invalid/shanghai/live)"
            )
        )

        self.assertTrue(projection.has_authoritative_final_reply)
        self.assertEqual(
            projection.final_reply_text,
            "- 示例地图链接 (https://maps.example.invalid/shanghai/live)",
        )
        self.assertIn("https://maps.example.invalid/shanghai/live", projection.visible_text)

    def test_terminal_result_card_extracts_lightweight_structure_summary(self) -> None:
        projection = project_interactive_card_text(
            build_terminal_result_card("# 总结\n\n## 下一步\n\n- 事项一\n\n> 注意")
        )

        self.assertEqual(
            projection.final_reply_structure_summary.headings,
            (
                TerminalHeading(level=1, text="总结"),
                TerminalHeading(level=2, text="下一步"),
            ),
        )
        self.assertTrue(projection.final_reply_structure_summary.has_list)
        self.assertTrue(projection.final_reply_structure_summary.has_quote)
        self.assertNotIn("\u200b", projection.visible_text)
        self.assertNotIn("\u200c", projection.visible_text)
        self.assertNotIn("\u200d", projection.visible_text)
        self.assertNotIn("\ufeff", projection.visible_text)
        self.assertIn("【标题】 总结", projection.visible_text)
        self.assertIn("【小节】 下一步", projection.visible_text)
        self.assertEqual(
            projection.final_reply_text,
            "# 总结\n\n## 下一步\n\n- 事项一\n\n> 注意",
        )

    def test_execution_card_projects_visible_text_best_effort(self) -> None:
        projection = project_interactive_card_text(
            build_execution_card(
                "命令输出",
                [ExecutionReplySegment("assistant", "阶段回复")],
                running=False,
            )
        )

        self.assertFalse(projection.has_authoritative_final_reply)
        self.assertIn("Codex", projection.text)
        self.assertIn("执行过程", projection.text)
        self.assertIn("命令输出", projection.text)
        self.assertIn("回复", projection.text)
        self.assertIn("阶段回复", projection.text)

    def test_minimal_terminal_execution_card_projects_placeholder_text(self) -> None:
        projection = project_interactive_card_text(build_execution_card("", [], running=False))

        self.assertFalse(projection.has_authoritative_final_reply)
        self.assertIn("Codex", projection.text)
        self.assertIn("执行过程", projection.text)
        self.assertIn("无", projection.text)

    def test_ordinary_card_ignores_button_labels_but_keeps_visible_text_blocks(self) -> None:
        projection = project_interactive_card_text(
            {
                "header": {
                    "title": {"tag": "plain_text", "content": "外部卡片"},
                },
                "elements": [
                    {"tag": "markdown", "content": "这里是正文"},
                    {
                        "tag": "action",
                        "actions": [
                            {
                                "tag": "button",
                                "text": {"tag": "plain_text", "content": "不应进入投影"},
                            }
                        ],
                    },
                ],
            }
        )

        self.assertEqual(projection.final_reply_text, "")
        self.assertIn("外部卡片", projection.text)
        self.assertIn("这里是正文", projection.text)
        self.assertNotIn("不应进入投影", projection.text)

    def test_ordinary_card_with_marker_like_text_is_not_promoted_to_authoritative_result(self) -> None:
        projection = project_interactive_card_text(
            {
                "header": {
                    "title": {"tag": "plain_text", "content": "示例卡片"},
                },
                "elements": [
                    {
                        "tag": "markdown",
                        "content": "普通说明：`<final_reply_text>demo</final_reply_text>`",
                    }
                ],
            }
        )

        self.assertFalse(projection.has_authoritative_final_reply)
        self.assertEqual(projection.final_reply_text, "")
        self.assertIn("示例卡片", projection.text)
        self.assertIn("<final_reply_text>demo</final_reply_text>", projection.text)

    def test_terminal_result_card_budget_is_fail_closed_on_marker_collision(self) -> None:
        self.assertFalse(
            can_render_terminal_result_card(
                f"包含{TERMINAL_RESULT_CARD_MARKER}隐藏标记",
                char_limit=1000,
            )
        )

    def test_terminal_result_card_budget_is_fail_closed_on_embedded_image_markdown(self) -> None:
        self.assertFalse(
            can_render_terminal_result_card(
                "![示意图](/tmp/phase1_report_diagram.png)",
                char_limit=1000,
            )
        )

    def test_terminal_result_card_without_authoritative_block_fails_closed(self) -> None:
        projection = project_interactive_card_text(
            {
                "header": {
                    "title": {"tag": "plain_text", "content": "Codex"},
                    "template": "green",
                },
                "elements": [
                    {"tag": "markdown", "content": "这里只剩普通展示文本"},
                ],
            }
        )

        self.assertFalse(projection.has_authoritative_final_reply)
        self.assertEqual(projection.final_reply_text, "")
        self.assertIn("Codex", projection.text)
        self.assertIn("这里只剩普通展示文本", projection.visible_text)

    def test_terminal_result_card_requires_green_template(self) -> None:
        projection = project_interactive_card_text(
            {
                "header": {
                    "title": {"tag": "plain_text", "content": "Codex"},
                    "template": "blue",
                },
                "elements": [
                    {"tag": "markdown", "content": f"foo{TERMINAL_RESULT_CARD_MARKER}"},
                ],
            }
        )

        self.assertFalse(projection.has_authoritative_final_reply)
        self.assertEqual(projection.final_reply_text, "")
        self.assertEqual(projection.text, "Codex\n\nfoo")

    def test_terminal_result_card_supports_json2_body_elements_shape(self) -> None:
        card = build_terminal_result_card("# 标题")
        projection = project_interactive_card_text(
            {
                "header": card["header"],
                "body": {"elements": card["elements"]},
            }
        )

        self.assertTrue(projection.has_authoritative_final_reply)
        self.assertEqual(projection.final_reply_text, "# 标题")
        self.assertEqual(
            projection.final_reply_structure_summary.headings,
            (TerminalHeading(level=1, text="标题"),),
        )

    def test_terminal_result_card_supports_history_rendered_shape(self) -> None:
        summary_payload = encode_terminal_structure_summary(
            TerminalStructureSummary(headings=(TerminalHeading(level=2, text="结论"),), has_list=True)
        )
        projection = project_interactive_card_text(
            {
                "title": "Codex",
                "elements": [
                    [
                        {"tag": "text", "text": "【小节】 结论"},
                        {
                            "tag": "text",
                            "text": f"\n- 第一条\n- 第二条{TERMINAL_RESULT_CARD_MARKER}{summary_payload}",
                        },
                    ]
                ],
            }
        )

        self.assertTrue(projection.has_authoritative_final_reply)
        self.assertEqual(projection.final_reply_text, "## 结论\n- 第一条\n- 第二条")
        self.assertEqual(projection.text, "## 结论\n- 第一条\n- 第二条")
        self.assertIn("Codex", projection.visible_text)
