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
    _print_binding_status,
    _send_thread_image,
    _resolve_thread_archive_target,
    _print_thread_status,
    _thread_target_params,
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
            "unsubscribe_available": True,
            "unsubscribe_reason_code": "",
            "unsubscribe_reason": "",
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
            "live_runtime_owner": {"label": "explorer"},
            "live_runtime_holder_labels": ["service@explorer(pid=1234)"],
            "bound_binding_ids": [],
            "attached_binding_ids": [],
            "released_binding_ids": [],
            "interaction_owner": {"label": "none"},
            "reprofile_possible": False,
            "unsubscribe_available": False,
            "unsubscribe_reason_code": "unsubscribe_not_applicable_no_binding",
            "unsubscribe_reason": "当前没有 Feishu 绑定指向该线程。",
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
