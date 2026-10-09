"""launchd child supervision with bounded stdout/stderr (no shell redirection)."""

from __future__ import annotations

import argparse
import pathlib
import signal
import subprocess
import threading

from bot.diagnostic_logs import append_log, start_log_maintenance


def capture_service(command: list[str], data_dir: pathlib.Path) -> int:
    stopped = start_log_maintenance(data_dir)
    child = None
    terminate_requested = threading.Event()
    previous_handlers = {}

    def request_termination(_signum, _frame):
        terminate_requested.set()

    def drain(stream, name: str) -> None:
        # read1 bounds memory even when a library emits a huge line without '\n'.
        import codecs

        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        with stream:
            while chunk := stream.read1(8192):
                append_log(data_dir, name, decoder.decode(chunk))
            remaining = decoder.decode(b"", final=True)
            if remaining:
                append_log(data_dir, name, remaining)

    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signum] = signal.signal(signum, request_termination)
        child = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        readers = [
            threading.Thread(target=drain, args=(stream, name), daemon=True)
            for stream, name in (
                (child.stdout, "service.stdout.log"),
                (child.stderr, "service.stderr.log"),
            )
        ]
        for reader in readers:
            reader.start()
        while child.poll() is None:
            if terminate_requested.wait(0.1):
                try:
                    child.terminate()
                except ProcessLookupError:
                    pass
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                break
        result = child.wait()
        for reader in readers:
            reader.join(timeout=2)
        return result if result >= 0 else 128 - result
    except Exception as exc:
        append_log(data_dir, "service.stderr.log", f"service launch failed: {exc}\n")
        return 1
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.wait()
        stopped.set()
        for signum, previous in previous_handlers.items():
            signal.signal(signum, previous)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=pathlib.Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("missing service command")
    raise SystemExit(capture_service(command, args.data_dir))


if __name__ == "__main__":
    main()
