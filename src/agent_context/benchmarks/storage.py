"""Bounded JSON streaming, fingerprints and private atomic artifact writes."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from agent_context.benchmarks.models import BenchmarkError


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def cache_valid(path: Path) -> bool:
    checksum = path.with_name(path.name + ".sha256")
    if not path.exists() or not checksum.exists():
        # An interrupted publish is incomplete, never an implicit cache hit.
        path.unlink(missing_ok=True)
        checksum.unlink(missing_ok=True)
        return False
    if digest(path) != checksum.read_text().strip():
        raise BenchmarkError("preparation cache checksum mismatch")
    return True


def seal_cache(path: Path) -> None:
    atomic_write(path.with_name(path.name + ".sha256"), digest(path) + "\n")


def records(path: Path, max_record_bytes: int) -> Iterator[Any]:
    """Stream top-level arrays or JSONL; a single wrapper object is bounded.

    This avoids loading multi-GB LongMemEval arrays into memory. The cap applies
    to an individual JSON value, not the whole array/file.
    """
    decoder = json.JSONDecoder()
    with path.open(encoding="utf-8") as stream:
        buffer = ""
        array: bool | None = None
        expect_value = True
        ended = False
        has_values = False
        while True:
            block = stream.read(65536)
            buffer += block
            if array is None and buffer.strip():
                buffer = buffer.lstrip()
                array = buffer.startswith("[")
                if array:
                    buffer = buffer[1:]
            while array is not None:
                buffer = buffer.lstrip()
                if ended:
                    if buffer:
                        raise BenchmarkError("trailing data after JSON array")
                    break
                if array and not expect_value:
                    if buffer.startswith(","):
                        buffer, expect_value = buffer[1:], True
                        continue
                    if buffer.startswith("]"):
                        buffer, ended = buffer[1:], True
                        continue
                    if buffer:
                        raise BenchmarkError("missing JSON array separator")
                    break
                if array and buffer.startswith("]"):
                    if has_values or buffer[1:].strip():
                        raise BenchmarkError("invalid JSON array end")
                    buffer, ended = buffer[1:], True
                    break
                if not buffer:
                    break
                try:
                    value, end = decoder.raw_decode(buffer)
                except json.JSONDecodeError:
                    break
                if len(buffer[:end].encode()) > max_record_bytes:
                    raise BenchmarkError("JSON record exceeds configured byte limit")
                yield value
                has_values = True
                buffer, expect_value = buffer[end:], not bool(array)
            if len(buffer.encode()) > max_record_bytes + 65536:
                raise BenchmarkError("JSON record exceeds configured byte limit")
            if not block:
                if buffer.strip() or array is None or (array and not ended):
                    raise BenchmarkError("empty, oversized or incomplete dataset JSON")
                return
