"""Standard-library remote helper for bounded hpc-tools filesystem requests.

This file is shipped as data and streamed to the selected executor. It must
remain self-contained: a target host does not need hpc-tools installed.
"""

from __future__ import annotations

import base64
import errno
import json
import os
import re
import secrets
import signal
import stat
import sys


PROTOCOL_VERSION = 1
TEMP_PREFIX = ".hpc-tools-"
MAX_PATH_CHARACTERS = 4096
MAX_ROOTS = 64
ENV_PREFIX = re.compile(
    r"^\$(?:([A-Za-z_][A-Za-z0-9_]*)|\{([A-Za-z_][A-Za-z0-9_]*)\})(?:/|$)"
)


class HelperError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _failure(action, code, message):
    return {
        "protocol": PROTOCOL_VERSION,
        "ok": False,
        "action": action,
        "error": {"code": code, "message": message},
    }


def _success(action, **values):
    return {
        "protocol": PROTOCOL_VERSION,
        "ok": True,
        "action": action,
        **values,
    }


def _platform_supported():
    required = (
        "O_CLOEXEC",
        "O_DIRECTORY",
        "O_NOFOLLOW",
        "link",
        "replace",
    )
    if any(not hasattr(os, name) for name in required):
        return False
    dir_fd_functions = os.supports_dir_fd
    return all(
        function in dir_fd_functions
        for function in (os.open, os.stat, os.unlink, os.mkdir, os.rmdir)
    )


def _validate_request(request):
    if not isinstance(request, dict):
        raise HelperError("invalid-request", "request must be an object")
    if request.get("protocol") != PROTOCOL_VERSION:
        raise HelperError("invalid-request", "unsupported filesystem protocol")
    action = request.get("action")
    if action not in {"probe", "list", "read", "write", "mkdir", "remove", "cleanup"}:
        raise HelperError("invalid-request", "unknown filesystem action")
    limits = request.get("limits")
    if not isinstance(limits, dict):
        raise HelperError("invalid-request", "limits must be an object")
    for key in ("max_bytes", "max_entries", "max_transfer_bytes"):
        value = limits.get(key)
        if type(value) is not int or value <= 0:
            raise HelperError("invalid-request", "%s must be a positive integer" % key)
    timeout = limits.get("timeout_seconds")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise HelperError("invalid-request", "timeout_seconds must be positive")
    if action == "write" and request.get("mode", 0o600) not in {0o600, 0o700}:
        raise HelperError("invalid-request", "write mode must be 0600 or 0700")
    return action, limits


def _reject_unsafe_expression(value, field):
    if not isinstance(value, str) or not value:
        raise HelperError("invalid-path", "%s must be a non-empty string" % field)
    if value != value.strip() or any(char in value for char in ("\0", "\n", "\r")):
        raise HelperError("invalid-path", "%s contains invalid whitespace" % field)
    if len(value) > MAX_PATH_CHARACTERS:
        raise HelperError("invalid-path", "%s is too long" % field)
    if any(char in value for char in ("*", "?", "[", "]", "`")):
        raise HelperError("invalid-path", "%s contains expansion syntax" % field)


def _expand_expression(value, field, allow_relative):
    _reject_unsafe_expression(value, field)
    if value == "~":
        expanded = os.path.expanduser("~")
        suffix = ""
    elif value.startswith("~/"):
        expanded = os.path.join(os.path.expanduser("~"), value[2:])
        suffix = value[2:]
    elif value.startswith("/"):
        expanded = value
        suffix = value[1:]
    elif value.startswith("$"):
        match = ENV_PREFIX.match(value)
        if match is None:
            raise HelperError("invalid-path", "%s has an invalid environment prefix" % field)
        name = match.group(1) or match.group(2)
        base = os.environ.get(name)
        if not base or not os.path.isabs(base):
            raise HelperError(
                "unavailable-environment",
                "%s environment variable is missing or non-absolute" % name,
            )
        suffix = value[match.end():]
        expanded = os.path.join(base, suffix) if suffix else base
    elif allow_relative:
        expanded = value
        suffix = value
    else:
        raise HelperError("invalid-path", "%s must resolve to an absolute path" % field)

    if "$" in suffix or "~" in suffix:
        raise HelperError("invalid-path", "%s contains extra expansion syntax" % field)
    _validate_segments(suffix, field)
    if not allow_relative and not os.path.isabs(expanded):
        raise HelperError("invalid-path", "%s did not resolve to an absolute path" % field)
    return expanded


def _validate_segments(suffix, field):
    if not suffix:
        return
    if suffix.endswith("/"):
        raise HelperError("invalid-path", "%s must not end with '/'" % field)
    if any(part in {"", ".", ".."} for part in suffix.split("/")):
        raise HelperError("invalid-path", "%s contains an empty, . or .. segment" % field)


def _root_records(raw_roots):
    if not isinstance(raw_roots, list) or not raw_roots:
        raise HelperError("root-denied", "at least one root grant is required")
    if not all(isinstance(root, str) for root in raw_roots):
        raise HelperError("invalid-request", "roots must be strings")
    if len(raw_roots) > MAX_ROOTS:
        raise HelperError("invalid-request", "too many root grants")
    if len(raw_roots) != len(set(raw_roots)):
        raise HelperError("invalid-request", "roots must not contain duplicates")
    records = []
    for raw in raw_roots:
        expanded = _expand_expression(raw, "root", allow_relative=False)
        if expanded == os.path.sep:
            raise HelperError("root-denied", "the filesystem root cannot be granted")
        records.append((raw, expanded, os.path.realpath(expanded)))
    return records


def _select_root(request):
    roots = _root_records(request.get("roots"))
    raw_path = request.get("path")
    _reject_unsafe_expression(raw_path, "path")
    selected = request.get("root")

    relative = not raw_path.startswith(("/", "~", "$"))
    if relative:
        if selected is None:
            if len(roots) != 1:
                raise HelperError(
                    "invalid-path",
                    "a relative path requires one explicit selected root",
                )
            record = roots[0]
        else:
            matches = [record for record in roots if record[0] == selected]
            if not matches:
                raise HelperError("root-denied", "selected root is not granted")
            record = matches[0]
        relative_path = _expand_expression(raw_path, "path", allow_relative=True)
        return record, tuple(relative_path.split("/")) if relative_path else ()

    expanded_path = _expand_expression(raw_path, "path", allow_relative=False)
    matches = []
    for record in roots:
        lexical_root = record[1]
        try:
            inside = os.path.commonpath((lexical_root, expanded_path)) == lexical_root
        except ValueError:
            inside = False
        if inside:
            matches.append(record)
    if not matches:
        raise HelperError("root-denied", "path is outside the granted roots")
    record = max(matches, key=lambda item: len(item[1]))
    relative_path = os.path.relpath(expanded_path, record[1])
    if relative_path == ".":
        components = ()
    else:
        _validate_segments(relative_path, "path")
        components = tuple(relative_path.split("/"))
    return record, components


def _open_root(record):
    try:
        fd = os.open(
            record[2],
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
    except FileNotFoundError:
        raise HelperError("not-found", "granted root does not exist")
    except NotADirectoryError:
        raise HelperError("not-directory", "granted root is not a directory")
    except OSError as error:
        raise HelperError("root-denied", "could not open granted root: %s" % error)
    return fd


def _open_directory_at(root_fd, components):
    current = os.dup(root_fd)
    try:
        for component in components:
            try:
                next_fd = os.open(
                    component,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                    dir_fd=current,
                )
            except FileNotFoundError:
                raise HelperError("not-found", "directory does not exist")
            except NotADirectoryError:
                raise HelperError("not-directory", "path component is not a directory")
            except OSError as error:
                if error.errno == errno.ELOOP:
                    raise HelperError("symlink-denied", "symbolic links are not followed")
                raise HelperError("io-error", "could not open directory: %s" % error)
            os.close(current)
            current = next_fd
        return current
    except Exception:
        os.close(current)
        raise


def _open_parent_at(root_fd, components):
    if not components:
        raise HelperError("root-denied", "the granted root itself is not a destination")
    try:
        parent = _open_directory_at(root_fd, components[:-1])
    except HelperError as error:
        if error.code == "not-found":
            raise HelperError("missing-parent", "destination parent does not exist")
        raise
    return parent, components[-1]


def _entry_kind(mode):
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISLNK(mode):
        return "symlink"
    return "special"


def _list_directory(root_fd, components, limits):
    directory_fd = _open_directory_at(root_fd, components)
    entries = []
    truncated = False
    try:
        with os.scandir(directory_fd) as iterator:
            for item in iterator:
                if len(entries) >= limits["max_entries"]:
                    truncated = True
                    break
                metadata = item.stat(follow_symlinks=False)
                entries.append({
                    "name": item.name,
                    "kind": _entry_kind(metadata.st_mode),
                    "size": metadata.st_size if stat.S_ISREG(metadata.st_mode) else None,
                    "mode": stat.S_IMODE(metadata.st_mode),
                })
    finally:
        os.close(directory_fd)
    return _success("list", entries=entries, truncated=truncated)


def _read_file(root_fd, components, limits):
    parent_fd, name = _open_parent_at(root_fd, components)
    file_fd = None
    try:
        try:
            file_fd = os.open(
                name,
                os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=parent_fd,
            )
        except FileNotFoundError:
            raise HelperError("not-found", "file does not exist")
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise HelperError("symlink-denied", "symbolic links are not followed")
            raise HelperError("io-error", "could not open file: %s" % error)
        metadata = os.fstat(file_fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise HelperError("special-file-denied", "path is not a regular file")
        remaining = limits["max_bytes"] + 1
        chunks = []
        while remaining:
            chunk = os.read(file_fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        truncated = len(data) > limits["max_bytes"] or metadata.st_size > limits["max_bytes"]
        data = data[:limits["max_bytes"]]
        return _success(
            "read",
            data=base64.b64encode(data).decode("ascii"),
            size=metadata.st_size,
            truncated=truncated,
        )
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(parent_fd)


def _existing_kind(parent_fd, name):
    try:
        metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    return _entry_kind(metadata.st_mode)


def _write_file(root_fd, components, request, limits):
    encoded = request.get("data")
    if not isinstance(encoded, str):
        raise HelperError("invalid-request", "write data must be base64 text")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        raise HelperError("invalid-request", "write data is not valid base64")
    if len(data) > limits["max_transfer_bytes"]:
        raise HelperError("limit-exceeded", "write exceeds max_transfer_bytes")

    parent_fd, name = _open_parent_at(root_fd, components)
    temp_name = "%s%s.tmp" % (TEMP_PREFIX, secrets.token_hex(12))
    temp_fd = None
    published = False
    try:
        existing = _existing_kind(parent_fd, name)
        if existing == "symlink":
            raise HelperError("symlink-denied", "destination is a symbolic link")
        if existing not in {None, "file"}:
            raise HelperError("conflict", "destination is not a regular file")
        if existing is not None and not request.get("overwrite", False):
            raise HelperError("conflict", "destination already exists")

        temp_fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_fd,
        )
        os.fchmod(temp_fd, request.get("mode", 0o600))
        view = memoryview(data)
        while view:
            written = os.write(temp_fd, view)
            if written <= 0:
                raise HelperError("io-error", "short write while staging destination")
            view = view[written:]
        os.fsync(temp_fd)
        os.close(temp_fd)
        temp_fd = None

        if request.get("overwrite", False):
            os.replace(temp_name, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        else:
            try:
                os.link(
                    temp_name,
                    name,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileExistsError:
                raise HelperError("conflict", "destination appeared during publication")
            os.unlink(temp_name, dir_fd=parent_fd)
        published = True
        os.fsync(parent_fd)
        return _success("write", size=len(data), overwritten=existing is not None)
    finally:
        if temp_fd is not None:
            os.close(temp_fd)
        if not published:
            try:
                os.unlink(temp_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        os.close(parent_fd)


def _make_directory(root_fd, components):
    parent_fd, name = _open_parent_at(root_fd, components)
    try:
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            raise HelperError("conflict", "destination already exists")
        os.fsync(parent_fd)
        return _success("mkdir")
    finally:
        os.close(parent_fd)


def _remove_entry(root_fd, components):
    parent_fd, name = _open_parent_at(root_fd, components)
    try:
        kind = _existing_kind(parent_fd, name)
        if kind is None:
            raise HelperError("not-found", "path does not exist")
        if kind == "symlink":
            raise HelperError("symlink-denied", "symbolic links are not removed")
        if kind == "file":
            os.unlink(name, dir_fd=parent_fd)
        elif kind == "directory":
            try:
                os.rmdir(name, dir_fd=parent_fd)
            except OSError as error:
                if error.errno in {errno.ENOTEMPTY, errno.EEXIST}:
                    raise HelperError("not-empty", "directory is not empty")
                raise
        else:
            raise HelperError("special-file-denied", "special files are not removed")
        os.fsync(parent_fd)
        return _success("remove", kind=kind)
    finally:
        os.close(parent_fd)


def _cleanup(directory_fd, limits):
    removed = []
    truncated = False
    with os.scandir(directory_fd) as iterator:
        for item in iterator:
            if len(removed) >= limits["max_entries"]:
                truncated = True
                break
            if not item.name.startswith(TEMP_PREFIX) or not item.name.endswith(".tmp"):
                continue
            metadata = item.stat(follow_symlinks=False)
            if not stat.S_ISREG(metadata.st_mode):
                continue
            os.unlink(item.name, dir_fd=directory_fd)
            removed.append(item.name)
    if removed:
        os.fsync(directory_fd)
    return _success("cleanup", removed=removed, truncated=truncated)


def _timeout(_signum, _frame):
    raise HelperError("timeout", "filesystem helper time limit exceeded")


def handle_request(request):
    action = request.get("action") if isinstance(request, dict) else None
    try:
        action, limits = _validate_request(request)
        if not _platform_supported():
            raise HelperError(
                "unsupported-platform",
                "required descriptor-based filesystem primitives are unavailable",
            )
        if action == "probe":
            return _success("probe", available=True, protocol=PROTOCOL_VERSION)

        old_handler = signal.signal(signal.SIGALRM, _timeout)
        signal.setitimer(signal.ITIMER_REAL, float(limits["timeout_seconds"]))
        root_fd = None
        try:
            record, components = _select_root(request)
            root_fd = _open_root(record)
            if action == "list":
                return _list_directory(root_fd, components, limits)
            if action == "read":
                return _read_file(root_fd, components, limits)
            if action == "write":
                return _write_file(root_fd, components, request, limits)
            if action == "mkdir":
                return _make_directory(root_fd, components)
            if action == "remove":
                return _remove_entry(root_fd, components)
            if action == "cleanup":
                directory_fd = _open_directory_at(root_fd, components)
                try:
                    return _cleanup(directory_fd, limits)
                finally:
                    os.close(directory_fd)
            raise HelperError("invalid-request", "unsupported action")
        finally:
            if root_fd is not None:
                os.close(root_fd)
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old_handler)
    except HelperError as error:
        return _failure(action, error.code, error.message)
    except PermissionError:
        return _failure(action, "permission-denied", "filesystem permission denied")
    except OSError as error:
        return _failure(action, "io-error", "filesystem operation failed: %s" % error)
    except Exception as error:
        return _failure(action, "internal-error", "filesystem helper failed: %s" % error)


def main():
    try:
        request = json.load(sys.stdin.buffer)
    except Exception as error:
        response = _failure(None, "protocol-error", "could not decode request: %s" % error)
    else:
        response = handle_request(request)
    encoded = json.dumps(response, sort_keys=True, separators=(",", ":"))
    sys.stdout.write(encoded)
    sys.stdout.flush()


if __name__ == "__main__":
    main()
