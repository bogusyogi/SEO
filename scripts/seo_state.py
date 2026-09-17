"""Portable state paths and process-safe transactions; no agent framework required."""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def state_dir(root: str | Path = '.') -> Path:
    root = Path(root).expanduser().resolve()
    current, legacy = root / '.seo', root / '.legion' / 'seo'
    # Existing projects remain readable until explicit migration. No dependency on Legion.
    return current if current.exists() or not legacy.exists() else legacy


def atomic_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(data, out, indent=2, ensure_ascii=False, allow_nan=False)
            out.write('\n'); out.flush(); os.fsync(out.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


@contextmanager
def transaction_lock(path: Path, timeout: float = 15) -> Iterator[None]:
    """SQLite provides an OS-released cross-platform writer lock (including on crashes)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path) + '.lock.sqlite', timeout=timeout)
    try:
        conn.execute('CREATE TABLE IF NOT EXISTS mutex (id INTEGER PRIMARY KEY)')
        conn.execute('BEGIN IMMEDIATE')
        yield
        conn.commit()
    except BaseException:
        conn.rollback(); raise
    finally:
        conn.close()


def migrate(root: str | Path) -> dict:
    root = Path(root).resolve()
    src, dst = root / '.legion' / 'seo', root / '.seo'
    if not src.is_dir(): return {'status': 'not_needed', 'path': str(dst)}
    if dst.exists(): raise ValueError('destination .seo already exists; reconcile explicitly, never overwrite')
    stage = root / '.seo-migration'
    if stage.exists(): raise ValueError('incomplete migration exists; inspect .seo-migration first')
    # Never follow symlinks while copying user state or silently import credential files.
    for p in src.rglob('*'):
        if p.is_symlink(): raise ValueError('legacy state contains symlinks; inspect before migration')
    shutil.copytree(src, stage)
    for p in src.rglob('*'):
        if p.is_file() and hashlib.sha256(p.read_bytes()).digest() != hashlib.sha256((stage/p.relative_to(src)).read_bytes()).digest():
            raise ValueError('migration verification failed')
    stage.rename(dst)
    return {'status': 'migrated', 'path': str(dst), 'legacy_preserved': True}
