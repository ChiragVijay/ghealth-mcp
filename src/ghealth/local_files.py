"""Atomic private files for local credentials and configuration."""

import os
import tempfile
from pathlib import Path


def write_private_file(path: Path, content: str) -> None:
    """Write through a unique owner-only temporary file, then atomically replace.

    On Windows the file inherits its parent directory's ACL. POSIX temporary
    files start with mode 0600, before any credentials are written.
    """
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
