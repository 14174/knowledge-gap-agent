import json
import os
import hashlib
from pathlib import Path

from knowledge_gap_agent.utils.canonical import canonical_json


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _seal(path):
    sidecar = Path(str(path) + ".sha256")
    digest = file_hash(path)
    if sidecar.exists():
        if sidecar.read_text(encoding="ascii").strip() != digest:
            raise ValueError("产物字节摘要不一致")
    else:
        with sidecar.open("x", encoding="ascii", newline="\n") as stream:
            stream.write(digest + "\n")
            stream.flush()
            os.fsync(stream.fileno())


def verify_file(path):
    sidecar = Path(str(path) + ".sha256")
    if not sidecar.exists() or sidecar.read_text(encoding="ascii").strip() != file_hash(path):
        raise ValueError(f"产物摘要缺失或失配：{Path(path).name}")


def read_json(path, *, verify=True):
    if verify:
        verify_file(path)
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_jsonl(path, *, verify=True):
    if verify:
        verify_file(path)
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def write_once(path, value):
    """先完整暂存再独占发布；同内容恢复，不覆盖冲突产物。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = canonical_json(value) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise FileExistsError(f"产物冲突：{path}")
        _seal(path)
        return
    import tempfile
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".artifact-")
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_text(encoding="utf-8") != content:
                raise
    finally:
        temporary.unlink(missing_ok=True)
    _seal(path)


def write_jsonl_once(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(canonical_json(row) + "\n" for row in rows)
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise FileExistsError(f"快照冲突：{path}")
        _seal(path)
        return
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    _seal(path)
