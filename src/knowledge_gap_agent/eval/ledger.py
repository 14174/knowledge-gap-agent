from datetime import datetime, timezone
from pathlib import Path
import sqlite3


class BudgetExceeded(RuntimeError):
    pass


class CallLedger:
    """每次真实请求前持久预留；独立连接与即时事务支持并发恢复。"""
    def __init__(self, path, *, limit=2400):
        if not 1 <= limit <= 2400:
            raise ValueError("调用预算必须在1至2400之间")
        self.path, self.limit = Path(path), limit
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY, context TEXT NOT NULL, reserved_at TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS settings (limit_value INTEGER NOT NULL)")
            row = connection.execute("SELECT limit_value FROM settings").fetchone()
            if row is None:
                connection.execute("INSERT INTO settings VALUES (?)", (limit,))
            elif row[0] != limit:
                raise ValueError("恢复预算与原批次冲突")

    def _connect(self):
        return sqlite3.connect(self.path, timeout=30)

    @property
    def used(self):
        with self._connect() as connection:
            return connection.execute("SELECT count(*) FROM attempts").fetchone()[0]

    def reserve(self, context="model"):
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            used = connection.execute("SELECT count(*) FROM attempts").fetchone()[0]
            if used >= self.limit:
                raise BudgetExceeded("真实模型调用预算已耗尽")
            connection.execute("INSERT INTO attempts(context,reserved_at) VALUES (?,?)",
                               (context, datetime.now(timezone.utc).isoformat()))
            return used + 1
