"""Private, bounded observation memory; storing a claim never verifies it."""

from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
import sqlite3


class MemoryStore:
    """Each operation gets its own connection, including when called by HTTP threads."""

    MAX_RECORDS = 5000

    def __init__(self, data_dir):
        self.directory = Path(data_dir).expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / "observations.sqlite3"
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY, text TEXT NOT NULL, source TEXT NOT NULL,
                origin TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'unreviewed',
                created_at TEXT NOT NULL, reviewed_at TEXT)""")
        self.path.chmod(0o600)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _limit(value):
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100:
            raise ValueError("Limit must be an integer from 1 to 100.")
        return value

    @staticmethod
    def _id(value):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("Observation ID must be a positive integer.")
        return value

    def add(self, text, source="", origin="user"):
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise ValueError("Observation must contain 1 to 4000 characters.")
        if any(ord(c) < 32 and c not in "\n\t" for c in text):
            raise ValueError("Observation contains unsupported control characters.")
        if not isinstance(source, str) or len(source) > 500 or any(ord(c) < 32 for c in source):
            raise ValueError("Source must be text of at most 500 characters.")
        if origin not in ("user", "model", "research", "import"):
            raise ValueError("Unknown observation origin.")
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            # Keep check and insert atomic across concurrent HTTP requests.
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] >= self.MAX_RECORDS:
                raise ValueError("Observation memory is full. Delete older records before adding more.")
            row_id = db.execute(
                "INSERT INTO observations(text,source,origin,status,created_at) VALUES(?,?,?,'unreviewed',?)",
                (text.strip(), source.strip(), origin, now),
            ).lastrowid
            return dict(db.execute("SELECT * FROM observations WHERE id=?", (row_id,)).fetchone())

    def list(self, limit=50):
        limit = self._limit(limit)
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM observations ORDER BY id DESC LIMIT ?", (limit,))]

    def search(self, query, limit=10):
        limit = self._limit(limit)
        if not isinstance(query, str) or not query.strip() or len(query) > 300:
            raise ValueError("Search query must contain 1 to 300 characters.")
        escaped = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM observations WHERE text LIKE ? ESCAPE '\\' OR source LIKE ? ESCAPE '\\' "
                "ORDER BY CASE status WHEN 'approved' THEN 0 ELSE 1 END,id DESC LIMIT ?",
                (f"%{escaped}%", f"%{escaped}%", limit),
            )]

    def review(self, observation_id, approved):
        observation_id = self._id(observation_id)
        if type(approved) is not bool:
            raise ValueError("Review decision must be true or false.")
        with self._connect() as db:
            changed = db.execute("UPDATE observations SET status=?,reviewed_at=? WHERE id=?", (
                "approved" if approved else "rejected", datetime.now(timezone.utc).isoformat(), observation_id,
            )).rowcount
            if not changed:
                raise ValueError("Observation was not found.")
            return dict(db.execute("SELECT * FROM observations WHERE id=?", (observation_id,)).fetchone())

    def delete(self, observation_id):
        observation_id = self._id(observation_id)
        with self._connect() as db:
            if not db.execute("DELETE FROM observations WHERE id=?", (observation_id,)).rowcount:
                raise ValueError("Observation was not found.")
        return {"deleted": observation_id}
