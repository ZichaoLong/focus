import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from bot.feishu_codexctl import (
    _archive_thread,
    _build_parser,
    _image_send_target_params,
    _list_running_instances,
    _print_thread_memory_result,
    _prompt_text_from_args,
    _print_binding_status,
    _send_thread_image,
    _send_binding_prompt,
    _resolve_thread_archive_target,
    _remote_adapter,
    _print_thread_status,
    _thread_target_params,
    main as feishu_codexctl_main,
)
from bot.instance_resolution import CliInstanceTarget
from bot.stores.app_server_runtime_store import AppServerRuntimeStore
from bot.stores.instance_registry_store import InstanceRegistryEntry


class FeishuCodexCtlTests(unittest.TestCase):
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
        self.assertIn("prompt send --binding-id <binding_id>", rendered)

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

        self.assertEqual(_thread_target_params(args), {"thread_name": "demo"})

    def test_thread_memory_accepts_mode_and_reset_flags(self) -> None:
        parser = _build_parser()

        args = parser.parse_args(
            [
                "thread",
                "memory",
                "--thread-id",
                "thread-1",
                "--mode",
                "read_write",
                "--force-reset-backend",
            ]
        )

        self.assertEqual(_thread_target_params(args), {"thread_id": "thread-1"})
        self.assertEqual(args.mode, "read_write")
        self.assertTrue(args.force_reset_backend)

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

    def test_parser_accepts_global_instance_selector(self) -> None:
        parser = _build_parser()

        args = parser.parse_args(["--instance", "corp-b", "service", "status"])

        self.assertEqual(args.instance, "corp-b")
        self.assertEqual(args.resource, "service")
        self.assertEqual(args.action, "status")

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
            "reprofile_possible": False,
            "detach_available": True,
            "detach_reason_code": "",
            "detach_reason": "",
            "approval_policy": "on-request",
            "sandbox": "workspace-write",
            "collaboration_mode": "default",
        }
        with patch("bot.feishu_codexctl._request", return_value=snapshot):
            with redirect_stdout(stdout):
                result = _print_binding_status(Path("/tmp/instance-data"), "p2p:ou_user:chat-1", instance_name="explorer")

        self.assertEqual(result, 0)
        rendered = stdout.getvalue()
        self.assertIn("instance: explorer", rendered)
        self.assertIn("binding: p2p:ou_user:chat-1", rendered)

    def test_thread_status_renders_resolved_instance_name(self) -> None:
        stdout = io.StringIO()
        snapshot = {
            "thread_id": "thread-1",
            "thread_title": "demo",
            "working_dir": "/tmp/project",
            "backend_thread_status": "notLoaded",
            "backend_running_turn": False,
            "thread_memory_mode": "read",
            "live_runtime_owner": {"label": "explorer"},
            "live_runtime_holder_labels": ["service@explorer(pid=1234)"],
            "bound_binding_ids": [],
            "attached_binding_ids": [],
            "detached_binding_ids": [],
            "interaction_owner": {"label": "none"},
            "reprofile_possible": False,
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
        self.assertIn("thread-wise memory mode: read", rendered)

    def test_thread_memory_result_renders_status_only_view(self) -> None:
        stdout = io.StringIO()
        snapshot = {
            "thread_id": "thread-1",
            "thread_title": "demo",
            "working_dir": "/tmp/project",
            "thread_memory_mode": "（未设置）",
            "plan_status": "reset-available",
            "reason_code": "memory_mode_reset_available",
            "reason": "当前 thread 尚未满足 verifiably globally unloaded；可通过 reset 当前实例 backend 后再写入 memory mode。",
            "requested_mode": "",
            "applied": False,
            "requires_reset_backend": True,
            "requires_force_reset_backend": False,
            "backend_reset_performed": False,
            "backend_reset_result": None,
        }
        with patch("bot.feishu_codexctl._request", return_value=snapshot):
            with redirect_stdout(stdout):
                result = _print_thread_memory_result(
                    Path("/tmp/instance-data"),
                    {"thread_id": "thread-1"},
                    instance_name="explorer",
                )

        self.assertEqual(result, 0)
        rendered = stdout.getvalue()
        self.assertIn("instance: explorer", rendered)
        self.assertIn("mutation plan: reset-available", rendered)
        self.assertNotIn("applied: no", rendered)

    def test_thread_memory_result_renders_reset_hint_when_write_not_applied(self) -> None:
        stdout = io.StringIO()
        snapshot = {
            "thread_id": "thread-1",
            "thread_title": "demo",
            "working_dir": "/tmp/project",
            "thread_memory_mode": "off",
            "plan_status": "reset-available",
            "reason_code": "memory_mode_reset_available",
            "reason": "当前 thread 尚未满足 verifiably globally unloaded；可通过 reset 当前实例 backend 后再写入 memory mode。",
            "requested_mode": "read",
            "applied": False,
            "requires_reset_backend": True,
            "requires_force_reset_backend": False,
            "backend_reset_performed": False,
            "backend_reset_result": None,
            "diagnostics": [
                "当前 thread：`thread-1…`",
                "hard blocker：待处理审批/输入请求：`1`",
                "collateral impact：当前实例 loaded threads：`2`",
            ],
        }
        with patch("bot.feishu_codexctl._request", return_value=snapshot):
            with redirect_stdout(stdout):
                result = _print_thread_memory_result(
                    Path("/tmp/instance-data"),
                    {"thread_id": "thread-1"},
                    mode="read",
                    instance_name="explorer",
                )

        self.assertEqual(result, 1)
        rendered = stdout.getvalue()
        self.assertIn("requested mode: read", rendered)
        self.assertIn("hint: 当前可改用 `--reset-backend`", rendered)
        self.assertIn("重置实例 `explorer` 的 backend", rendered)
        self.assertIn("diagnostics:", rendered)
        self.assertIn("- hard blocker：待处理审批/输入请求：`1`", rendered)
        self.assertIn("- collateral impact：当前实例 loaded threads：`2`", rendered)

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
