"""POSIX filesystem primitives. Never follow source-file symlinks.

The service's private state parent and OS account are trusted. This is not a
sandbox against another process with the same UID or against root.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import secrets
import stat
from pathlib import Path, PurePosixPath

from .errors import BridgeError

MAX_JSON = 48 * 1024 * 1024  # must exceed MAX_BUNDLE_BYTES plus JSON framing


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def relative_parts(name: str) -> tuple[str, ...]:
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        raise BridgeError("INVALID_PATH", "Use an explicit, relative POSIX file path.")
    p = PurePosixPath(name)
    if p.is_absolute() or any(s in ("", ".", "..") for s in name.split("/")):
        raise BridgeError("INVALID_PATH", "Absolute paths and traversal are not allowed.")
    return p.parts


def read_source(root: Path, name: str, max_bytes: int) -> tuple[bytes, tuple]:
    """openat/O_NOFOLLOW at every component; reject hardlinks and special files."""
    parts = relative_parts(name)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        source = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            before = os.fstat(source)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise BridgeError("UNSAFE_FILE", "Only regular, non-hardlinked files are allowed.")
            if before.st_size > max_bytes:
                raise BridgeError("FILE_TOO_LARGE", "A selected file exceeds the size limit.")
            chunks, size = [], 0
            while size <= max_bytes:
                piece = os.read(source, min(65536, max_bytes + 1 - size))
                if not piece:
                    break
                chunks.append(piece)
                size += len(piece)
            after = os.fstat(source)
            signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
            if size > max_bytes:
                raise BridgeError("FILE_TOO_LARGE", "A selected file exceeds the size limit.")
            if signature(before) != signature(after):
                raise BridgeError("SOURCE_CHANGED", "Selected input changed during capture; retry.")
            return b"".join(chunks), signature(after)
        finally:
            os.close(source)
    except OSError as exc:
        raise BridgeError("UNSAFE_FILE", "A selected file is missing, linked, or inaccessible.") from exc
    finally:
        os.close(fd)


def private_dir(path: Path, *, create: bool = True) -> Path:
    """Check a state directory itself; ancestors must be administrator-controlled."""
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        st = path.lstat()
    except OSError as exc:
        raise BridgeError("STATE_MISSING", "Initialize the private state directory first.") from exc
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise BridgeError("UNSAFE_STATE", "State directories must be owned by you and mode 0700.")
    return path


def safe_read(path: Path, limit: int = MAX_JSON) -> bytes:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            st = os.fstat(stream.fileno())
            if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or
                    st.st_uid != os.getuid() or st.st_mode & 0o077):
                raise BridgeError("UNSAFE_STATE", "State files must be private regular files.")
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise BridgeError("STATE_LIMIT", "State file exceeds its size limit.")
        return data
    except OSError as exc:
        raise BridgeError("STATE_MISSING", "Required state file is missing or inaccessible.") from exc


def read_json(path: Path) -> dict:
    try:
        value = json.loads(safe_read(path))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeError) as exc:
        raise BridgeError("CORRUPT_STATE", "State is not a valid JSON object.") from exc


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_new(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def atomic_write(path: Path, data: bytes) -> None:
    private_dir(path.parent, create=False)
    temp = path.parent / (".tmp-" + secrets.token_hex(16))
    try:
        if path.is_symlink():
            raise BridgeError("UNSAFE_STATE", "Refusing to replace a linked state file.")
        write_new(temp, data)
        os.replace(temp, path)
        fsync_dir(path.parent)
    finally:
        temp.unlink(missing_ok=True)


@contextlib.contextmanager
def task_lock(directory: Path):
    private_dir(directory, create=False)
    fd = os.open(directory / ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise BridgeError("UNSAFE_STATE", "Invalid task lock file.")
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)
