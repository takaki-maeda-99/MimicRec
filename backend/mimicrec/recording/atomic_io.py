from __future__ import annotations
import os
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def _atomic_write_text(path: Path, content: str) -> None:
    """Atomically write `content` to `path` via tmp + os.replace.

    The tmp file is created in `path.parent` (so the rename stays within the
    same filesystem) with a unique name and is unlinked on failure.
    """
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _atomic_write_parquet(table: pa.Table, dst: Path) -> None:
    """Atomically write a pyarrow table to `dst` via tmp + os.replace."""
    parent = dst.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=dst.name + ".", suffix=".tmp", dir=parent)
    os.close(fd)   # pq.write_table opens its own handle
    tmp = Path(tmp_name)
    try:
        pq.write_table(table, tmp)
        os.replace(tmp, dst)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
