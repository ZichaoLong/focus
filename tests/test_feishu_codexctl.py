import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from bot.adapters.base import ThreadSummary
from bot.feishu_codexctl import (
    _archive_thread,
    _archive_threads,
    _build_parser,
    _clear_thread_goal,
    _image_send_target_params,
    _list_running_instances,
    _print_binding_list,
    _print_thread_goal,
    _print_thread_list,
    _prompt_text_from_args,
    _print_binding_status,
    _render_table,
    _send_thread_image,
    _send_binding_prompt,
    _set_thread_goal,
    _resolve_thread_archive_target,
    _resolve_thread_archive_targets,
    _remote_adapter,
    _terminal_display_width,
    _print_thread_status,
    _thread_target_params,
    main as feishu_codexctl_main,
)
from bot.instance_resolution import CliInstanceTarget
from bot.service_control_plane import ServiceControlError
from bot.stores.app_server_runtime_store import AppServerRuntimeStore
from bot.stores.instance_registry_store import InstanceRegistryEntry


class FeishuCodexCtlTests(unittest.TestCase):
    def _visual_cell_starts(self, line: str, cells: list[str]) -> list[int]:
        starts: list[int] = []
        offset = 0
        for cell in cells:
            start = line.find(cell, offset)
            self.assertNotEqual(start, -1)
            starts.append(_terminal_display_width(line[:start]))
            offset = start + len(cell)
        return starts

    def test_top_level_help_includes_operator_guidance(self) -> None:
        parser = _build_parser()
        rendered = parser.format_help()

        self.assertIn("本地查看 / 管理面", rendered)
        self.assertIn("不是第二个 Codex 前端", rendered)
        self.assertIn("除 `instance list` 外", rendered)
        self.assertIn("binding clear", rendered)
        self.assertIn("常用命令:", rendered)
        self.assertIn("feishu-codexctl --instance corp-a service status", rendered)
        self.assertIn("thread archive --thread-name demo", rendered)
        self.assertIn("thread goal --thread-id <id>", rendered)
        self.assertIn("prompt send --binding-id <binding_id>", rendered)
        self.assertIn("thread archive --thread-id <id-1> --thread-id <id-2>", rendered)

    def test_thread_help_includes_scope_and_selector_guidance(self) -> None:
        parser = _build_parser()
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as exc:
                parser.parse_args(["thread", "--help"])

        self.assertEqual(exc.exception.code, 0)
        rendered = stdout.getvalue()
        self.assertIn("Thread 管理面", rendered)
        self.assertIn("`list` 默认列当前目录线程", rendered)
        self.assertIn("`--thread-id` 或 `--thread-name`", rendered)
        self.assertIn("thread commands", rendered)
        self.assertIn("goal", rendered)
        self.assertIn("archive", rendered)
        self.assertIn("detach", rendered)
        self.assertIn("attach", rendered)
        self.assertIn("persisted thread", rendered)

    def test_binding_help_includes_clear_semantics(self) -> None:
        parser = _build_parser()
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as exc:
                parser.parse_args(["binding", "--help"])

        self.assertEqual(exc.exception.code, 0)
        rendered = stdout.getvalue()
        self.assertIn("Binding 管理面", rendered)
        self.assertIn("Feishu 本地 bookmark", rendered)
        self.assertIn("不等于 `detach`", rendered)

    def test_binding_clear_accepts_binding_id(self) -> None:
        parser = _build_parser()

        args = parser.parse_args(["binding", "clear", "p2p:ou_user:chat-1"])

        self.assertEqual(args.binding_id, "p2p:ou_user:chat-1")

    def test_binding_clear_all_accepts_no_args(self) -> None:
        parser = _build_parser()

        args = parser.parse_args(["binding", "clear-all"])

        self.assertEqual(args.resource, "binding")
        self.assertEqual(args.action, "clear-all")

    def test_thread_status_accepts_explicit_thread_id(self) -> None:
        parser = _build_parser()

        args = parser.parse_args(["thread", "status", "--thread-id", "thread-1"])

        self.assertEqual(_thread_target_params(args), {"thread_id": "thread-1"})

    def test_thread_status_accepts_explicit_thread_name(self) -> None:
        parser = _build_parser()

        args = parser.parse_args(["thread", "status", "--thread-name", "demo"])

        self.assertEqual(_thread_target_params(args), {"thread_name": "demo"})

    def test_thread_status_requires_explicit_selector(self) -> None:
        parser = _build_parser()

        with self.assertRaises(SystemExit):
            parser.parse_args(["thread", "status"])

    def test_thread_status_rejects_both_selectors(self) -> None:
        parser = _build_parser()

        with self.assertRaises(SystemExit):
            parser.parse_args(["thread", "status", "--thread-id", "thread-1", "--thread-name", "demo"])

    def test_thread_bindings_accepts_explicit_thread_id(self) -> None:
        parser = _build_parser()

        args = parser.parse_args(["thread", "bindings", "--thread-id", "thread-1"])

        self.assertEqual(_thread_target_params(args), {"thread_id": "thread-1"})

    def test_thread_bindings_accepts_explicit_thread_name(self) -> None:
        parser = _build_parser()

        args = parser.parse_args(["thread", "bindings", "--thread-name", "demo"])

        self.assertEqual(_thread_target_params(args), {"thread_name": "demo"})

    def test_thread_goal_defaults_to_show(self) -> None:
        parser = _build_parser()

        args = parser.parse_args(["thread", "goal", "--thread-id", "thread-1"])

        self.assertEqual(args.goal_action, "show")
        self.assertEqual(_thread_target_params(args), {"thread_id": "thread-1"})

    def test_thread_goal_show_accepts_explicit_thread_name(self) -> None:
        parser = _build_parser()

        args = parser.parse_args(["thread", "goal", "show", "--thread-name", "demo"])

        self.assertEqual(args.goal_action, "show")
        self.assertEqual(_thread_target_params(args), {"thread_name": "demo"})

    def test_thread_goal_set_accepts_objective_and_status(self) -> None:
        parser = _build_parser()

        args = parser.parse_args(
            [
                "thread",
                "goal",
                "set",
                "--thread-id",
                "thread-1",
                "--objective",
                "ship goal support",
                "--status",
                "paused",
            ]
        )

        self.assertEqual(args.goal_action, "set")
        self.assertEqual(_thread_target_params(args), {"thread_id": "thread-1"})
        self.assertEqual(args.objective, "ship goal support")
        self.assertEqual(args.status, "paused")

    def test_thread_goal_set_only_accepts_active_and_paused(self) -> None:
        parser = _build_parser()

        for status in ("active", "paused"):
            args = parser.parse_args(
                [
                    "thread",
                    "goal",
                    "set",
                    "--thread-id",
                    "thread-1",
                    "--status",
                    status,
                ]
            )
            self.assertEqual(args.goal_action, "set")
            self.assertEqual(_thread_target_params(args), {"thread_id": "thread-1"})
            self.assertEqual(args.status, status)

    def test_thread_goal_set_rejects_removed_terminal_statuses(self) -> None:
        parser = _build_parser()

        for status in ("blocked", "usageLimited", "budgetLimited", "complete"):
            with self.assertRaises(SystemExit):
                parser.parse_args(
                    [
                        "thread",
                        "goal",
                        "set",
                        "--thread-id",
                        "thread-1",
                        "--status",
                        status,
                    ]
                )

    def test_thread_goal_removed_pause_and_resume_subcommands_are_rejected(self) -> None:
        parser = _build_parser()

        for subcommand in ("pause", "resume"):
            with self.assertRaises(SystemExit):
                parser.parse_args(["thread", "goal", subcommand, "--thread-id", "thread-1"])

    def test_thread_list_defaults_to_cwd_scope(self) -> None:
        parser = _build_parser()

        args = parser.parse_args(["thread", "list"])

        self.assertEqual(args.resource, "thread")
        self.assertEqual(args.action, "list")
        self.assertEqual(args.scope, "cwd")
        self.assertEqual(args.cwd, "")

    def test_thread_list_accepts_global_scope_and_explicit_cwd(self) -> None:
        parser = _build_parser()

        args = parser.parse_args(["thread", "list", "--scope", "global", "--cwd", "/tmp/project"])

        self.assertEqual(args.scope, "global")
        self.assertEqual(args.cwd, "/tmp/project")

    def test_remote_adapter_prefers_running_instance_resolution(self) -> None:
        entry = InstanceRegistryEntry(
            instance_name="aft",
            owner_pid=1234,
            service_token="token-aft",
            control_endpoint="tcp://127.0.0.1:9000",
            app_server_url="ws://127.0.0.1:8765",
            config_dir="/tmp/config-aft",
            data_dir="/tmp/data-aft",
            started_at=1.0,
            updated_at=1.0,
        )
        with patch("bot.feishu_codexctl.load_config_file", return_value={"app_server_url": "ws://127.0.0.1:8765"}):
            with patch(
                "bot.feishu_codexctl.resolve_running_instance_app_server_url",
                return_value="ws://127.0.0.1:43210",
            ) as mock_resolve:
                adapter, _, app_server_url = _remote_adapter(Path("/tmp/data-aft"), running_entry=entry)

        self.assertEqual(app_server_url, "ws://127.0.0.1:43210")
        self.assertEqual(mock_resolve.call_args.args[0], entry)
        self.assertEqual(mock_resolve.call_args.kwargs["configured_app_server_url"], "ws://127.0.0.1:8765")
        adapter.stop()

    def test_main_thread_list_passes_running_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            entry = InstanceRegistryEntry(
                instance_name="aft",
                owner_pid=1234,
                service_token="token-aft",
                control_endpoint="tcp://127.0.0.1:9000",
                app_server_url="ws://127.0.0.1:8765",
                config_dir="/tmp/config-aft",
                data_dir=tmpdir,
                started_at=1.0,
                updated_at=1.0,
            )
            target = CliInstanceTarget(
                instance_name="aft",
                data_dir=Path(tmpdir),
                running_entry=entry,
            )
            with patch("bot.feishu_codexctl._resolve_target_instance", return_value=target):
                with patch("bot.feishu_codexctl._print_thread_list", return_value=0) as mock_print:
                    with patch(
                        "bot.feishu_codexctl.sys.argv",
                        ["feishu-codexctl", "--instance", "aft", "thread", "list"],
                    ):
                        with self.assertRaises(SystemExit) as exc:
                            feishu_codexctl_main()

        self.assertEqual(exc.exception.code, 0)
        self.assertEqual(mock_print.call_args.kwargs["scope"], "cwd")
        self.assertEqual(mock_print.call_args.kwargs["running_entry"], entry)

    def test_main_thread_goal_show_dispatches_to_goal_printer(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = CliInstanceTarget(
                instance_name="aft",
                data_dir=Path(tmpdir),
            )
            with patch("bot.feishu_codexctl._resolve_target_instance", return_value=target):
                with patch("bot.feishu_codexctl._print_thread_goal", return_value=0) as mock_print:
                    with patch(
                        "bot.feishu_codexctl.sys.argv",
                        ["feishu-codexctl", "--instance", "aft", "thread", "goal", "--thread-id", "thread-1"],
                    ):
                        with self.assertRaises(SystemExit) as exc:
                            feishu_codexctl_main()

        self.assertEqual(exc.exception.code, 0)
        self.assertEqual(mock_print.call_args.args[0], Path(tmpdir))
        self.assertEqual(mock_print.call_args.args[1], {"thread_id": "thread-1"})
        self.assertEqual(mock_print.call_args.kwargs["instance_name"], "aft")

    def test_thread_detach_accepts_explicit_thread_id(self) -> None:
        parser = _build_parser()

        args = parser.parse_args(["thread", "detach", "--thread-id", "thread-1"])

        self.assertEqual(_thread_target_params(args), {"thread_id": "thread-1"})

    def test_thread_detach_accepts_explicit_thread_name(self) -> None:
        parser = _build_parser()

        args = parser.parse_args(["thread", "detach", "--thread-name", "demo"])

        self.assertEqual(_thread_target_params(args), {"thread_name": "demo"})

    def test_thread_archive_accepts_explicit_thread_name(self) -> None:
        parser = _build_parser()

        args = parser.parse_args(["thread", "archive", "--thread-name", "demo"])

        self.assertEqual(args.thread_name, "demo")

    def test_thread_archive_accepts_repeated_thread_ids(self) -> None:
        parser = _build_parser()

        args = parser.parse_args(
            ["thread", "archive", "--thread-id", "thread-1", "--thread-id", "thread-2"]
        )

        self.assertEqual(args.thread_ids, ["thread-1", "thread-2"])

    def test_thread_archive_rejects_mixing_thread_id_and_thread_name(self) -> None:
        parser = _build_parser()

        args = parser.parse_args(["thread", "archive", "--thread-id", "thread-1", "--thread-name", "demo"])

        with self.assertRaisesRegex(ValueError, "不能同时提供"):
            _resolve_thread_archive_targets(args)

    def test_image_send_accepts_explicit_thread_selector_and_path(self) -> None:
        parser = _build_parser()

        args = parser.parse_args(["image", "send", "--path", "./diagram.png", "--thread-id", "thread-1"])

        self.assertEqual(args.resource, "image")
        self.assertEqual(args.action, "send")
        self.assertEqual(args.path, "./diagram.png")
        self.assertEqual(_image_send_target_params(args), ({"thread_id": "thread-1"}, "thread-1"))

    def test_image_send_falls_back_to_codex_thread_id_env(self) -> None:
        parser = _build_parser()

        with patch.dict(os.environ, {"CODEX_THREAD_ID": "thread-env-1"}, clear=False):
            args = parser.parse_args(["image", "send", "--path", "./diagram.png"])
            params, preferred_thread_id = _image_send_target_params(args)

        self.assertEqual(params, {"thread_id": "thread-env-1"})
        self.assertEqual(preferred_thread_id, "thread-env-1")

    def test_image_send_requires_selector_when_env_missing(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["image", "send", "--path", "./diagram.png"])

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "CODEX_THREAD_ID"):
                _image_send_target_params(args)

    def test_prompt_send_accepts_inline_text(self) -> None:
        parser = _build_parser()

        args = parser.parse_args(
            ["prompt", "send", "--binding-id", "p2p:ou_user:chat-1", "--text", "继续执行"]
        )

        self.assertEqual(args.resource, "prompt")
        self.assertEqual(args.action, "send")
        self.assertEqual(args.binding_id, "p2p:ou_user:chat-1")
        self.assertEqual(_prompt_text_from_args(args), "继续执行")

    def test_prompt_send_reads_text_file(self) -> None:
        parser = _build_parser()
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_file = Path(tmpdir) / "prompt.txt"
            prompt_file.write_text("继续执行\n", encoding="utf-8")

            args = parser.parse_args(
                [
                    "prompt",
                    "send",
                    "--binding-id",
                    "p2p:ou_user:chat-1",
                    "--text-file",
                    str(prompt_file),
                ]
            )

            self.assertEqual(_prompt_text_from_args(args), "继续执行\n")

    def test_send_binding_prompt_reports_denial(self) -> None:
        stdout = io.StringIO()
        snapshot = {
            "binding_id": "p2p:ou_user:chat-1",
            "thread_id": "thread-1",
            "started": False,
            "turn_id": "",
            "reason_code": "prompt_denied_by_running_turn",
            "reason": "当前线程仍在执行，请等待结束或先执行 `/cancel`。",
            "display_mode": "silent",
            "synthetic_source": "schedule",
        }
        with patch("bot.feishu_codexctl._request", return_value=snapshot):
            with redirect_stdout(stdout):
                result = _send_binding_prompt(
                    Path("/tmp/instance-data"),
                    binding_id="p2p:ou_user:chat-1",
                    text="继续执行",
                    synthetic_source="schedule",
                    instance_name="explorer",
                )

        self.assertEqual(result, 1)
        rendered = stdout.getvalue()
        self.assertIn("instance: explorer", rendered)
        self.assertIn("started: no", rendered)
        self.assertIn("reason code: prompt_denied_by_running_turn", rendered)

    def test_send_binding_prompt_reports_queued_as_success(self) -> None:
        stdout = io.StringIO()
        snapshot = {
            "binding_id": "p2p:ou_user:chat-1",
            "thread_id": "thread-1",
            "started": False,
            "queued": True,
            "queue_position": 2,
            "turn_id": "",
            "reason_code": "",
            "reason": "",
            "display_mode": "silent",
            "synthetic_source": "schedule",
        }
        with patch("bot.feishu_codexctl._request", return_value=snapshot):
            with redirect_stdout(stdout):
                result = _send_binding_prompt(
                    Path("/tmp/instance-data"),
                    binding_id="p2p:ou_user:chat-1",
                    text="继续执行",
                    synthetic_source="schedule",
                    instance_name="explorer",
                )

        self.assertEqual(result, 0)
        rendered = stdout.getvalue()
        self.assertIn("instance: explorer", rendered)
        self.assertIn("started: no", rendered)
        self.assertIn("queued: yes", rendered)
        self.assertIn("queue_position: 2", rendered)

    def test_parser_accepts_global_instance_selector(self) -> None:
        parser = _build_parser()

        args = parser.parse_args(["--instance", "corp-b", "service", "status"])

        self.assertEqual(args.instance, "corp-b")
        self.assertEqual(args.resource, "service")
        self.assertEqual(args.action, "status")

    def test_main_rejects_explicit_uncreated_named_instance(self) -> None:
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch.dict(
                os.environ,
                {
                    "FC_CONFIG_ROOT": str(root / "config"),
                    "FC_DATA_ROOT": str(root / "data"),
                    "FC_INSTANCE": "",
                },
                clear=False,
            ):
                with patch(
                    "bot.feishu_codexctl.sys.argv",
                    ["feishu-codexctl", "--instance", "ghost", "service", "status"],
                ):
                    with patch("bot.feishu_codexctl.sys.stderr", stderr):
                        with self.assertRaises(SystemExit) as exc:
                            feishu_codexctl_main()

        self.assertEqual(exc.exception.code, 2)
        self.assertIn("instance create ghost", stderr.getvalue())

    def test_service_reset_backend_accepts_without_force(self) -> None:
        parser = _build_parser()

        args = parser.parse_args(["service", "reset-backend"])

        self.assertEqual(args.resource, "service")
        self.assertEqual(args.action, "reset-backend")
        self.assertFalse(args.force)

    def test_service_reset_backend_accepts_force_flag(self) -> None:
        parser = _build_parser()

        args = parser.parse_args(["service", "reset-backend", "--force"])

        self.assertEqual(args.resource, "service")
        self.assertEqual(args.action, "reset-backend")
        self.assertTrue(args.force)

    def test_instance_list_prefers_runtime_store_url_over_stale_registry_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            AppServerRuntimeStore(data_dir).save_managed_runtime(
                configured_url="ws://127.0.0.1:8765",
                active_url="ws://127.0.0.1:43210",
                owner_pid=os.getpid(),
                app_server_pid=os.getpid(),
            )
            entry = InstanceRegistryEntry(
                instance_name="explorer",
                owner_pid=os.getpid(),
                service_token="token-explorer",
                control_endpoint="tcp://127.0.0.1:9393",
                app_server_url="ws://127.0.0.1:8765",
                config_dir="/tmp/config-explorer",
                data_dir=str(data_dir),
                started_at=1.0,
                updated_at=1.0,
            )
            stdout = io.StringIO()
            with patch("bot.feishu_codexctl.list_running_instances", return_value=[entry]):
                with redirect_stdout(stdout):
                    result = _list_running_instances()

        self.assertEqual(result, 0)
        rendered = stdout.getvalue()
        self.assertIn("ws://127.0.0.1:43210", rendered)

    def test_render_table_aligns_wide_characters(self) -> None:
        headers = ["THREAD_ID", "PROVIDER", "CWD", "TITLE"]
        rows = [
            ["thread-1", "openai", "/tmp/项目", "修复对齐"],
            ["thread-22", "-", "/tmp/demo", "ascii title"],
        ]

        rendered = _render_table(headers, rows)

        self.assertEqual(_terminal_display_width("项目"), 4)
        self.assertEqual(_terminal_display_width("e\u0301"), 1)
        self.assertNotIn("\t", "\n".join(rendered))
        header_starts = self._visual_cell_starts(rendered[0], headers)
        self.assertEqual(self._visual_cell_starts(rendered[1], rows[0]), header_starts)
        self.assertEqual(self._visual_cell_starts(rendered[2], rows[1]), header_starts)

    def test_thread_list_renders_aligned_columns_without_tabs(self) -> None:
        threads = [
            ThreadSummary(
                thread_id="thread-1",
                cwd="/tmp/项目一",
                name="修复对齐",
                preview="",
                created_at=0,
                updated_at=0,
                source="cli",
                status="idle",
                model_provider="openai",
            ),
            ThreadSummary(
                thread_id="thread-22",
                cwd="/tmp/demo",
                name="ascii title",
                preview="",
                created_at=0,
                updated_at=0,
                source="cli",
                status="idle",
                model_provider=None,
            ),
        ]

        class _FakeAdapter:
            def stop(self) -> None:
                return None

        stdout = io.StringIO()
        with patch("bot.feishu_codexctl._remote_adapter", return_value=(_FakeAdapter(), {"thread_list_query_limit": 100}, "ws://127.0.0.1:8765")):
            with patch("bot.feishu_codexctl.list_global_threads", return_value=threads):
                with redirect_stdout(stdout):
                    result = _print_thread_list(Path("/tmp/instance-data"), scope="global", cwd="")

        self.assertEqual(result, 0)
        lines = stdout.getvalue().splitlines()
        self.assertNotIn("\t", "\n".join(lines))
        header = ["THREAD_ID", "PROVIDER", "CWD", "TITLE"]
        row1 = ["thread-1", "openai", "/tmp/项目一", "修复对齐"]
        row2 = ["thread-22", "-", "/tmp/demo", "ascii title"]
        header_starts = self._visual_cell_starts(lines[0], header)
        self.assertEqual(self._visual_cell_starts(lines[1], row1), header_starts)
        self.assertEqual(self._visual_cell_starts(lines[2], row2), header_starts)

    def test_binding_list_renders_aligned_columns_without_tabs(self) -> None:
        snapshot = {
            "bindings": [
                {
                    "binding_id": "p2p:ou_user:chat-1",
                    "binding_kind": "p2p",
                    "binding_state": "bound",
                    "feishu_runtime_state": "attached",
                    "thread_id": "thread-1234567890",
                    "working_dir": "/tmp/项目二",
                },
                {
                    "binding_id": "group:chat-2",
                    "binding_kind": "group",
                    "binding_state": "detached",
                    "feishu_runtime_state": "idle",
                    "thread_id": "",
                    "working_dir": "/tmp/demo",
                },
            ]
        }
        stdout = io.StringIO()
        with patch("bot.feishu_codexctl._request", return_value=snapshot):
            with redirect_stdout(stdout):
                result = _print_binding_list(Path("/tmp/instance-data"))

        self.assertEqual(result, 0)
        lines = stdout.getvalue().splitlines()
        self.assertNotIn("\t", "\n".join(lines))
        header = ["BINDING_ID", "KIND", "STATE", "RUNTIME", "THREAD", "CWD"]
        row1 = ["p2p:ou_user:chat-1", "p2p", "bound", "attached", "thread-1…", "/tmp/项目二"]
        row2 = ["group:chat-2", "group", "detached", "idle", "-", "/tmp/demo"]
        header_starts = self._visual_cell_starts(lines[0], header)
        self.assertEqual(self._visual_cell_starts(lines[1], row1), header_starts)
        self.assertEqual(self._visual_cell_starts(lines[2], row2), header_starts)

    def test_binding_status_renders_resolved_instance_name(self) -> None:
        stdout = io.StringIO()
        snapshot = {
            "binding_id": "p2p:ou_user:chat-1",
            "binding_kind": "p2p",
            "chat_id": "chat-1",
            "sender_id": "ou_user",
            "working_dir": "/tmp/project",
            "binding_state": "bound",
            "thread_id": "thread-1",
            "thread_title": "demo",
            "feishu_runtime_state": "attached",
            "backend_thread_status": "idle",
            "backend_running_turn": False,
            "live_runtime_owner": {"label": "explorer"},
            "live_runtime_holder_labels": ["service@explorer(pid=1234)"],
            "interaction_owner": {"label": "none"},
            "next_prompt_allowed": True,
            "detach_available": True,
            "detach_reason_code": "",
            "detach_reason": "",
            "approval_policy": "on-request",
            "permissions_profile_id": ":workspace",
            "collaboration_mode": "default",
        }
        with patch("bot.feishu_codexctl._request", return_value=snapshot):
            with redirect_stdout(stdout):
                result = _print_binding_status(Path("/tmp/instance-data"), "p2p:ou_user:chat-1", instance_name="explorer")

        self.assertEqual(result, 0)
        rendered = stdout.getvalue()
        self.assertIn("instance: explorer", rendered)
        self.assertIn("binding: p2p:ou_user:chat-1", rendered)
        self.assertIn("current-instance interaction owner: none", rendered)

    def test_thread_status_renders_resolved_instance_name(self) -> None:
        stdout = io.StringIO()
        snapshot = {
            "thread_id": "thread-1",
            "thread_title": "demo",
            "working_dir": "/tmp/project",
            "backend_thread_status": "notLoaded",
            "backend_running_turn": False,
            "live_runtime_owner": {"label": "explorer"},
            "live_runtime_holder_labels": ["service@explorer(pid=1234)"],
            "bound_binding_ids": [],
            "attached_binding_ids": [],
            "detached_binding_ids": [],
            "interaction_owner": {"label": "none"},
            "detach_available": False,
            "detach_reason_code": "unsubscribe_not_applicable_no_binding",
            "detach_reason": "当前没有 Feishu 绑定指向该线程。",
        }
        with patch("bot.feishu_codexctl._request", return_value=snapshot):
            with redirect_stdout(stdout):
                result = _print_thread_status(
                    Path("/tmp/instance-data"),
                    {"thread_name": "demo"},
                    instance_name="explorer",
                )

        self.assertEqual(result, 0)
        rendered = stdout.getvalue()
        self.assertIn("instance: explorer", rendered)
        self.assertIn("thread: thread-1 demo", rendered)
        self.assertIn("current-instance interaction owner: none", rendered)

    def test_print_thread_goal_renders_goal_snapshot(self) -> None:
        stdout = io.StringIO()
        snapshot = {
            "thread_id": "thread-1",
            "thread_title": "demo",
            "working_dir": "/tmp/project",
            "goal": {
                "thread_id": "thread-1",
                "objective": "ship goal support",
                "status": "active",
                "token_budget": 100,
                "tokens_used": 12,
                "time_used_seconds": 34,
                "created_at": 1712476800,
                "updated_at": 1712476801,
            },
        }
        with patch("bot.feishu_codexctl._request", return_value=snapshot):
            with redirect_stdout(stdout):
                result = _print_thread_goal(
                    Path("/tmp/instance-data"),
                    {"thread_id": "thread-1"},
                    instance_name="explorer",
                )

        self.assertEqual(result, 0)
        rendered = stdout.getvalue()
        self.assertIn("instance: explorer", rendered)
        self.assertIn("thread: thread-1 demo", rendered)
        self.assertIn("objective: ship goal support", rendered)
        self.assertIn("status: active (进行中)", rendered)
        self.assertIn("token budget: 100", rendered)
        self.assertIn("tokens used: 12", rendered)

    def test_set_thread_goal_compacts_empty_fields(self) -> None:
        stdout = io.StringIO()
        snapshot = {
            "thread_id": "thread-1",
            "thread_title": "demo",
            "working_dir": "/tmp/project",
            "goal": {
                "thread_id": "thread-1",
                "objective": "ship goal support",
                "status": "paused",
                "token_budget": None,
                "tokens_used": 12,
                "time_used_seconds": 34,
                "created_at": 1712476800,
                "updated_at": 1712476801,
            },
        }
        with patch("bot.feishu_codexctl._request", return_value=snapshot) as mock_request:
            with redirect_stdout(stdout):
                result = _set_thread_goal(
                    Path("/tmp/instance-data"),
                    {"thread_id": "thread-1"},
                    status="paused",
                    instance_name="explorer",
                )

        self.assertEqual(result, 0)
        self.assertEqual(
            mock_request.call_args.args,
            (
                Path("/tmp/instance-data"),
                "thread/goal/set",
                {
                    "thread_id": "thread-1",
                    "status": "paused",
                },
            ),
        )
        self.assertIn("note: 当前 thread goal 已更新。", stdout.getvalue())

    def test_set_and_clear_thread_goal_render_operation_notes(self) -> None:
        stdout = io.StringIO()
        paused = {
            "thread_id": "thread-1",
            "thread_title": "demo",
            "working_dir": "/tmp/project",
            "goal": {
                "thread_id": "thread-1",
                "objective": "ship goal support",
                "status": "paused",
                "token_budget": None,
                "tokens_used": 12,
                "time_used_seconds": 34,
                "created_at": 1712476800,
                "updated_at": 1712476801,
            },
        }
        cleared = {
            "thread_id": "thread-1",
            "thread_title": "demo",
            "working_dir": "/tmp/project",
            "goal": None,
            "cleared": True,
        }
        with patch("bot.feishu_codexctl._request", side_effect=[paused, cleared]):
            with redirect_stdout(stdout):
                self.assertEqual(
                    _set_thread_goal(
                        Path("/tmp/instance-data"),
                        {"thread_id": "thread-1"},
                        status="paused",
                        instance_name="explorer",
                    ),
                    0,
                )
                self.assertEqual(
                    _clear_thread_goal(Path("/tmp/instance-data"), {"thread_id": "thread-1"}, instance_name="explorer"),
                    0,
                )

        rendered = stdout.getvalue()
        self.assertIn("note: 当前 thread goal 已更新。", rendered)
        self.assertIn("note: 当前 thread goal 已清除。", rendered)
        self.assertIn("goal: （无）", rendered)

    def test_send_thread_image_reports_partial_delivery(self) -> None:
        stdout = io.StringIO()
        snapshot = {
            "thread_id": "thread-1",
            "thread_title": "demo",
            "working_dir": "/tmp/project",
            "local_path": "/tmp/generated.png",
            "delivered_binding_ids": ["p2p:ou_user:chat-1"],
            "failed_binding_ids": ["p2p:ou_other:chat-2"],
        }
        with patch("bot.feishu_codexctl._request", return_value=snapshot):
            with redirect_stdout(stdout):
                result = _send_thread_image(
                    Path("/tmp/instance-data"),
                    {"thread_id": "thread-1"},
                    local_path="/tmp/generated.png",
                    instance_name="explorer",
                )

        self.assertEqual(result, 1)
        rendered = stdout.getvalue()
        self.assertIn("instance: explorer", rendered)
        self.assertIn("delivered bindings: p2p:ou_user:chat-1", rendered)
        self.assertIn("failed bindings: p2p:ou_other:chat-2", rendered)

    def test_archive_thread_prints_scope_note(self) -> None:
        stdout = io.StringIO()
        snapshot = {
            "thread_id": "thread-1",
            "thread_title": "demo",
            "working_dir": "/tmp/project",
            "cleared_binding_ids": ["p2p:ou_user:chat-1"],
        }
        with patch("bot.feishu_codexctl._request", return_value=snapshot):
            with redirect_stdout(stdout):
                result = _archive_thread(
                    Path("/tmp/instance-data"),
                    {"thread_id": "thread-1"},
                    instance_name="explorer",
                )

        self.assertEqual(result, 0)
        rendered = stdout.getvalue()
        self.assertIn("instance: explorer", rendered)
        self.assertIn("cleared bindings in this instance: p2p:ou_user:chat-1", rendered)
        self.assertIn("只清理当前目标实例", rendered)

    def test_archive_threads_batches_partial_failures(self) -> None:
        stdout = io.StringIO()
        target_a = CliInstanceTarget(instance_name="explorer", data_dir=Path("/tmp/explorer-data"))
        target_b = CliInstanceTarget(instance_name="default", data_dir=Path("/tmp/default-data"))

        def _fake_request(data_dir: Path, method: str, params: dict[str, str]):
            self.assertEqual(method, "thread/archive")
            if params["thread_id"] == "thread-2":
                raise ServiceControlError("busy")
            return {
                "thread_id": params["thread_id"],
                "thread_title": "demo",
                "working_dir": str(data_dir),
                "cleared_binding_ids": ["p2p:ou_user:chat-1"],
            }

        with patch("bot.feishu_codexctl._lease_owner_instance", side_effect=["explorer", "default"]):
            with patch("bot.feishu_codexctl._resolve_target_instance", side_effect=[target_a, target_b]):
                with patch("bot.feishu_codexctl._request", side_effect=_fake_request):
                    with redirect_stdout(stdout):
                        result = _archive_threads(["thread-1", "thread-2"])

        self.assertEqual(result, 1)
        rendered = stdout.getvalue()
        self.assertIn("batch archive: total=2", rendered)
        self.assertIn("[1/2] thread: thread-1", rendered)
        self.assertIn("[2/2] thread: thread-2", rendered)
        self.assertIn("instance: explorer", rendered)
        self.assertIn("instance: default", rendered)
        self.assertIn("status: archived", rendered)
        self.assertIn("status: failed", rendered)
        self.assertIn("summary: archived=1 failed=1", rendered)

    def test_archive_threads_continues_after_target_resolution_failure(self) -> None:
        stdout = io.StringIO()
        target_b = CliInstanceTarget(instance_name="default", data_dir=Path("/tmp/default-data"))

        with patch("bot.feishu_codexctl._lease_owner_instance", side_effect=["explorer", "default"]):
            with patch(
                "bot.feishu_codexctl._resolve_target_instance",
                side_effect=[ValueError("ambiguous instance"), target_b],
            ):
                with patch(
                    "bot.feishu_codexctl._request",
                    return_value={
                        "thread_id": "thread-2",
                        "thread_title": "demo",
                        "working_dir": "/tmp/default-data",
                        "cleared_binding_ids": [],
                    },
                ):
                    with redirect_stdout(stdout):
                        result = _archive_threads(["thread-1", "thread-2"])

        self.assertEqual(result, 1)
        rendered = stdout.getvalue()
        self.assertIn("ambiguous instance", rendered)
        self.assertIn("status: failed", rendered)
        self.assertIn("status: archived", rendered)
        self.assertIn("summary: archived=1 failed=1", rendered)

    def test_resolve_thread_archive_target_prefers_live_runtime_owner_for_thread_name(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["thread", "archive", "--thread-name", "demo"])
        bootstrap = CliInstanceTarget(instance_name="default", data_dir=Path("/tmp/default-data"))
        owner_target = CliInstanceTarget(instance_name="explorer", data_dir=Path("/tmp/explorer-data"))
        snapshot = {
            "thread_id": "thread-1",
            "live_runtime_owner": {
                "instance_name": "explorer",
                "label": "explorer",
            },
        }

        with patch("bot.feishu_codexctl._resolve_target_instance", side_effect=[bootstrap, owner_target]):
            with patch("bot.feishu_codexctl._request", return_value=snapshot):
                target, target_params = _resolve_thread_archive_target(args)

        self.assertEqual(target.instance_name, "explorer")
        self.assertEqual(target.data_dir, Path("/tmp/explorer-data"))
        self.assertEqual(target_params, {"thread_id": "thread-1"})

    def test_resolve_thread_archive_targets_prefers_live_runtime_owner_for_each_thread_id(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(
            ["thread", "archive", "--thread-id", "thread-1", "--thread-id", "thread-2"]
        )
        target_a = CliInstanceTarget(instance_name="explorer", data_dir=Path("/tmp/explorer-data"))
        target_b = CliInstanceTarget(instance_name="aft", data_dir=Path("/tmp/aft-data"))

        with patch("bot.feishu_codexctl._lease_owner_instance", side_effect=["explorer", "aft"]):
            with patch("bot.feishu_codexctl._resolve_target_instance", side_effect=[target_a, target_b]):
                targets = _resolve_thread_archive_targets(args)

        self.assertEqual(
            targets,
            [
                (target_a, {"thread_id": "thread-1"}),
                (target_b, {"thread_id": "thread-2"}),
            ],
        )

    def test_main_thread_archive_batch_dispatches_all_targets(self) -> None:
        with patch("bot.feishu_codexctl._archive_threads", return_value=1) as mock_archive:
            with patch(
                "bot.feishu_codexctl.sys.argv",
                [
                    "feishu-codexctl",
                    "thread",
                    "archive",
                    "--thread-id",
                    "thread-1",
                    "--thread-id",
                    "thread-2",
                ],
            ):
                with self.assertRaises(SystemExit) as exc:
                    feishu_codexctl_main()

        self.assertEqual(exc.exception.code, 1)
        self.assertEqual(mock_archive.call_args.args[0], ["thread-1", "thread-2"])
        self.assertEqual(mock_archive.call_args.kwargs["explicit_instance"], "")
