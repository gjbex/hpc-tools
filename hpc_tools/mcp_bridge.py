#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import socket
import stat
import struct
import subprocess
import sys
import threading
from pathlib import Path

SOCKET_ENV_VAR = "HPC_TOOLS_MCP_SOCKET"


class BridgeError(RuntimeError):
    """Raised when the private stdio/socket bridge cannot be established."""


def serve(socket_path: Path, command: list[str]) -> int:
    """Expose one host-side stdio MCP process through one private Unix socket."""
    if not command:
        raise BridgeError("serve requires a server command after --")
    selected = _validate_socket_path(socket_path, must_exist=False)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    child: subprocess.Popen[bytes] | None = None
    try:
        listener.bind(str(selected))
        os.chmod(selected, 0o600)
        listener.listen(1)
        connection, _ = listener.accept()
        listener.close()
        with connection:
            _require_same_user(connection)
            child = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=None,
            )
            assert child.stdin is not None
            assert child.stdout is not None
            inbound = threading.Thread(
                target=_socket_to_pipe,
                args=(connection, child.stdin),
                daemon=True,
            )
            inbound.start()
            try:
                _pipe_to_socket(child.stdout, connection)
            finally:
                child.stdout.close()
            try:
                connection.shutdown(socket.SHUT_WR)
            except OSError:
                pass
            return child.wait()
    finally:
        listener.close()
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        try:
            selected.unlink()
        except FileNotFoundError:
            pass


def connect(socket_path: Path) -> int:
    """Relay MCP bytes between client stdio and a private host Unix socket."""
    selected = _validate_socket_path(socket_path, must_exist=True)
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        connection.connect(str(selected))
        outbound = threading.Thread(
            target=_pipe_to_socket,
            args=(sys.stdin.buffer, connection),
            kwargs={"shutdown": True},
            daemon=True,
        )
        outbound.start()
        with connection.makefile("rb", buffering=0) as source:
            shutil.copyfileobj(source, sys.stdout.buffer)
        sys.stdout.buffer.flush()
    finally:
        connection.close()
    return 0


def _validate_socket_path(path: Path, *, must_exist: bool) -> Path:
    if not path.is_absolute() or ".." in path.parts:
        raise BridgeError("socket path must be absolute and normalized")
    parent = path.parent
    if parent.is_symlink() or not parent.is_dir():
        raise BridgeError(f"socket parent must be a real directory: {parent}")
    info = parent.stat()
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise BridgeError("socket parent must be owned by this user with mode 0700")
    if must_exist:
        if path.is_symlink() or not path.exists() or not stat.S_ISSOCK(path.stat().st_mode):
            raise BridgeError(f"MCP socket is not available: {path}")
    elif path.exists() or path.is_symlink():
        raise BridgeError(f"refusing to replace existing socket path: {path}")
    if len(os.fsencode(path)) >= 104:
        raise BridgeError("Unix socket path is too long; select a shorter runtime directory")
    return path


def _require_same_user(connection: socket.socket) -> None:
    if not hasattr(socket, "SO_PEERCRED"):
        return
    credentials = connection.getsockopt(
        socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
    )
    _, uid, _ = struct.unpack("3i", credentials)
    if uid != os.geteuid():
        raise BridgeError("MCP bridge peer has a different Unix uid")


def _socket_to_pipe(connection: socket.socket, pipe: object) -> None:
    try:
        with connection.makefile("rb", buffering=0) as source:
            shutil.copyfileobj(source, pipe)  # type: ignore[arg-type]
        pipe.close()  # type: ignore[attr-defined]
    except (BrokenPipeError, ConnectionError, OSError):
        try:
            pipe.close()  # type: ignore[attr-defined]
        except OSError:
            pass


def _pipe_to_socket(source: object, connection: socket.socket, shutdown: bool = False) -> None:
    try:
        while True:
            chunk = source.read(64 * 1024)  # type: ignore[attr-defined]
            if not chunk:
                break
            connection.sendall(chunk)
    except (BrokenPipeError, ConnectionError, OSError):
        pass
    finally:
        if shutdown:
            try:
                connection.shutdown(socket.SHUT_WR)
            except OSError:
                pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hpc-mcp-bridge")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument("--socket", required=True, type=Path)
    serve_parser.add_argument("command", nargs=argparse.REMAINDER)
    connect_parser = subparsers.add_parser("connect")
    connect_parser.add_argument(
        "--socket",
        type=Path,
        default=None,
        help=f"defaults to {SOCKET_ENV_VAR}",
    )
    args = parser.parse_args(argv)
    try:
        if args.operation == "serve":
            command = args.command[1:] if args.command[:1] == ["--"] else args.command
            return serve(args.socket, command)
        selected = args.socket or (
            Path(os.environ[SOCKET_ENV_VAR]) if SOCKET_ENV_VAR in os.environ else None
        )
        if selected is None:
            raise BridgeError(f"connect requires --socket or {SOCKET_ENV_VAR}")
        return connect(selected)
    except (BridgeError, OSError) as error:
        print(f"hpc-mcp-bridge: {error}", file=sys.stderr)
        return 2


def relay_main(argv: list[str] | None = None) -> int:
    """Console entry point used inside the restricted agent image."""
    return main(["connect", *(argv if argv is not None else sys.argv[1:])])


if __name__ == "__main__":
    selected_main = relay_main if Path(sys.argv[0]).name == "hpc-mcp-relay" else main
    raise SystemExit(selected_main())
