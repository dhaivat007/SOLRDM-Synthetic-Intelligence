"""Persistent bounded task execution, not subjective awareness or model training.

This store authorizes no tools itself. The caller must claim a step, execute the
existing tool, then save its actual receipt with the claim's attempt_id. A lost
receipt leaves an unknown outcome; startup never silently repeats that work.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sqlite3

from .tools import TOOL_DEFINITIONS


_SCHEMAS = {item["function"]["name"]: item["function"]["parameters"] for item in TOOL_DEFINITIONS}
_INTERRUPTION = ("Application stopped before a completion receipt was recorded. "
                 "The outcome is unknown; explicitly retrying may repeat side effects.")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _text(value, maximum, label, *, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise ValueError(f"{label} must contain {'0' if empty else '1'} to {maximum} characters.")
    if any(ord(c) < 32 and c not in "\n\t" or ord(c) == 127 for c in value):
        raise ValueError(f"{label} contains unsupported control characters.")
    return value.strip()


def _schema(value, schema, label):
    """Validate the small JSON Schema subset used by existing tool definitions."""
    kind = schema["type"]
    if kind == "object":
        if not isinstance(value, dict):
            raise ValueError(f"{label} must be an object.")
        properties = schema["properties"]
        if set(value) != set(schema["required"]) or set(value) - set(properties):
            raise ValueError(f"{label} must contain exactly: {', '.join(properties)}.")
        for key, item in value.items():
            _schema(item, properties[key], f"{label}.{key}")
    elif kind == "string":
        if (not isinstance(value, str) or not value.strip()
                or not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 4000)
                or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError(f"{label} must be bounded nonempty text without control characters.")
    elif kind == "number":
        try:
            valid = (type(value) in (int, float) and math.isfinite(value)
                     and schema["minimum"] <= value <= schema["maximum"])
        except (OverflowError, TypeError):
            valid = False
        if not valid:
            raise ValueError(f"{label} must be a finite number within the tool's supported range.")
    elif kind == "array":
        if not isinstance(value, list) or not schema["minItems"] <= len(value) <= schema["maxItems"]:
            raise ValueError(f"{label} has an unsupported number of items.")
        for item in value:
            _schema(item, schema["items"], label + "[]")
    else:
        # A future tool must explicitly extend validation before plans can use it.
        raise ValueError(f"Unsupported tool parameter type: {kind}.")


def _json(value, maximum):
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise ValueError("Task data must be finite JSON values.") from None
    if len(encoded.encode("utf-8")) > maximum:
        raise ValueError("Task data exceeds its storage limit.")
    return encoded


class WorkspaceStore:
    """One app instance; separate connections make HTTP thread claims atomic.

    Initialization recovers unfinished attempts. Use recover=False only for an
    additional live connection owner; never run two independent task executors
    against this database during startup recovery.
    """

    MAX_TASKS = 100
    MAX_STEPS = 6
    MAX_ATTEMPTS = 10
    MAX_REFLECTIONS = 10
    MAX_RECEIPT_BYTES = 262144

    def __init__(self, data_dir, *, recover=True):
        self.directory = Path(data_dir).expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / "workspace.sqlite3"
        if self.path.is_symlink():
            raise ValueError("Workspace database must not be a symbolic link.")
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
        self.path.chmod(0o600)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, goal TEXT NOT NULL,
                    label TEXT NOT NULL, status TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS steps (
                    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    step_index INTEGER NOT NULL, name TEXT NOT NULL,
                    arguments TEXT NOT NULL, purpose TEXT NOT NULL, status TEXT NOT NULL,
                    PRIMARY KEY(task_id, step_index));
                CREATE TABLE IF NOT EXISTS attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL, step_index INTEGER NOT NULL,
                    status TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT,
                    receipt TEXT, interruption_reason TEXT,
                    FOREIGN KEY(task_id, step_index) REFERENCES steps(task_id, step_index) ON DELETE CASCADE);
                CREATE TABLE IF NOT EXISTS reflections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    summary TEXT NOT NULL, uncertainties TEXT NOT NULL,
                    next_steps TEXT NOT NULL, origin TEXT NOT NULL, created_at TEXT NOT NULL);
            """)
        if recover:
            self.recover_interrupted()

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _id(value):
        if type(value) is not int or value <= 0:
            raise ValueError("Task and attempt IDs must be positive integers.")
        return value

    def _task(self, db, task_id):
        row = db.execute("SELECT * FROM tasks WHERE id=?", (self._id(task_id),)).fetchone()
        if row is None:
            raise ValueError("Task not found.")
        result = dict(row)
        result["steps"] = []
        for row in db.execute("SELECT * FROM steps WHERE task_id=? ORDER BY step_index", (task_id,)):
            step = {"index": row["step_index"], "name": row["name"], "arguments": json.loads(row["arguments"]),
                    "purpose": row["purpose"], "status": row["status"], "attempts": []}
            for attempt_row in db.execute("SELECT * FROM attempts WHERE task_id=? AND step_index=? ORDER BY id", (task_id, step["index"])):
                attempt = dict(attempt_row)
                attempt["receipt"] = json.loads(attempt["receipt"]) if attempt["receipt"] else None
                attempt["outcome"] = "unknown" if attempt["status"] == "interrupted" else attempt["status"]
                step["attempts"].append(attempt)
            last = step["attempts"][-1] if step["attempts"] else None
            step["attempt_id"] = last["id"] if last else None
            step["receipt"] = last["receipt"] if last else None
            result["steps"].append(step)
        result["reflections"] = []
        for row in db.execute("SELECT * FROM reflections WHERE task_id=? ORDER BY id", (task_id,)):
            item = dict(row)
            item["uncertainties"] = json.loads(item["uncertainties"])
            item["next_steps"] = json.loads(item["next_steps"])
            item.update({"verified": False, "kind": "suggestion", "trains_weights": False})
            result["reflections"].append(item)
        result["reflection"] = result["reflections"][-1] if result["reflections"] else None
        return result

    def create(self, goal, steps, label=""):
        goal = _text(goal, 4000, "Goal")
        label = _text(label, 120, "Label", empty=True) or goal[:120]
        if not isinstance(steps, list) or not 1 <= len(steps) <= self.MAX_STEPS:
            raise ValueError(f"A plan must contain 1 to {self.MAX_STEPS} steps.")
        validated = []
        for step in steps:
            if not isinstance(step, dict) or set(step) != {"name", "arguments", "purpose"}:
                raise ValueError("Each step must contain exactly name, arguments, and purpose.")
            name = step["name"]
            if not isinstance(name, str) or name not in _SCHEMAS:
                raise ValueError("Plan uses an unavailable tool.")
            _schema(step["arguments"], _SCHEMAS[name], name)
            validated.append((name, _json(step["arguments"], 65536), _text(step["purpose"], 500, "Step purpose")))
        now = _now()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] >= self.MAX_TASKS:
                raise ValueError("Task workspace is full. Delete older tasks before creating more.")
            task_id = db.execute("INSERT INTO tasks(goal,label,status,created_at,updated_at) VALUES(?,?,'planned',?,?)", (goal, label, now, now)).lastrowid
            db.executemany("INSERT INTO steps(task_id,step_index,name,arguments,purpose,status) VALUES(?,?,?,?,?,'pending')",
                           [(task_id, index, *step) for index, step in enumerate(validated)])
            return self._task(db, task_id)

    def get(self, task_id):
        with self._connect() as db:
            db.execute("BEGIN")
            return self._task(db, task_id)

    def list(self, limit=50):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Limit must be an integer from 1 to 100.")
        with self._connect() as db:
            db.execute("BEGIN")
            return [self._task(db, row[0]) for row in db.execute("SELECT id FROM tasks ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

    def summaries(self, limit=100):
        """Compact navigation records; detailed receipts are fetched per task."""
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Limit must be an integer from 1 to 100.")
        with self._connect() as db:
            db.execute("BEGIN")
            return [dict(row) for row in db.execute("""
                SELECT tasks.id,tasks.goal,tasks.label,tasks.status,tasks.created_at,tasks.updated_at,
                    COUNT(steps.step_index) AS step_count,
                    SUM(CASE WHEN steps.status='completed' THEN 1 ELSE 0 END) AS completed_steps
                FROM tasks LEFT JOIN steps ON steps.task_id=tasks.id
                GROUP BY tasks.id ORDER BY tasks.id DESC LIMIT ?
            """, (limit,))]

    def stats(self):
        with self._connect() as db:
            db.execute("BEGIN")
            counts = {row["status"]: row["count"] for row in db.execute("SELECT status,COUNT(*) AS count FROM tasks GROUP BY status")}
            current = db.execute("SELECT goal,status FROM tasks WHERE status NOT IN ('completed','cancelled') ORDER BY CASE status WHEN 'running' THEN 0 WHEN 'paused' THEN 1 WHEN 'interrupted' THEN 2 WHEN 'planned' THEN 3 ELSE 4 END,id DESC LIMIT 1").fetchone()
            return {"total": sum(counts.values()), "counts": counts,
                    "current_goal": current["goal"] if current else None,
                    "current_status": current["status"] if current else None}

    def start_step(self, task_id):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = self._task(db, task_id)
            if task["status"] not in ("planned", "running"):
                raise ValueError(f"Task is {task['status']}; it cannot start another step.")
            step = next((step for step in task["steps"] if step["status"] != "completed"), None)
            if not step or step["status"] != "pending":
                raise ValueError("Task already has a running step or requires an explicit retry.")
            if len(step["attempts"]) >= self.MAX_ATTEMPTS:
                raise ValueError("This step has reached its attempt limit. Create a new task after reviewing the receipts.")
            now = _now()
            attempt_id = db.execute("INSERT INTO attempts(task_id,step_index,status,started_at) VALUES(?,?,'running',?)", (task_id, step["index"], now)).lastrowid
            db.execute("UPDATE steps SET status='running' WHERE task_id=? AND step_index=?", (task_id, step["index"]))
            db.execute("UPDATE tasks SET status='running',updated_at=? WHERE id=?", (now, task_id))
            return {"task_id": task_id, "index": step["index"], "name": step["name"],
                    "arguments": step["arguments"], "purpose": step["purpose"], "attempt_id": attempt_id}

    def finish_step(self, task_id, step_index, receipt, *, attempt_id):
        self._id(attempt_id)
        if type(step_index) is not int or not 0 <= step_index < self.MAX_STEPS:
            raise ValueError("Invalid step index.")
        if not isinstance(receipt, dict) or receipt.get("status") not in ("completed", "failed"):
            raise ValueError("A step needs its actual completed or failed tool receipt.")
        _text(receipt.get("summary"), 12000, "Receipt summary")
        encoded = _json(receipt, self.MAX_RECEIPT_BYTES)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = self._task(db, task_id)
            if step_index >= len(task["steps"]):
                raise ValueError("Step not found.")
            step = task["steps"][step_index]
            if step["status"] != "running" or step["attempt_id"] != attempt_id:
                raise ValueError("Attempt is stale or already finished; no receipt was overwritten.")
            if receipt.get("tool") != step["name"]:
                raise ValueError("Receipt tool does not match the claimed step.")
            now = _now()
            status = receipt["status"]
            db.execute("UPDATE attempts SET status=?,ended_at=?,receipt=? WHERE id=?", (status, now, encoded, attempt_id))
            db.execute("UPDATE steps SET status=? WHERE task_id=? AND step_index=?", (status, task_id, step_index))
            if task["status"] in ("paused", "cancelled"):
                task_status = task["status"]
            elif status == "failed":
                task_status = "failed"
            elif all(item["status"] == "completed" for item in task["steps"] if item["index"] != step_index):
                task_status = "completed"
            else:
                task_status = "running"
            db.execute("UPDATE tasks SET status=?,updated_at=? WHERE id=?", (task_status, now, task_id))
            return self._task(db, task_id)

    def pause(self, task_id):
        return self._control(task_id, "pause")

    def cancel(self, task_id):
        return self._control(task_id, "cancel")

    def resume(self, task_id):
        return self._control(task_id, "resume")

    def retry(self, task_id):
        """Explicit user retry; unknown previous side effects may be repeated."""
        return self._control(task_id, "retry")

    def _control(self, task_id, action):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = self._task(db, task_id)
            status = task["status"]
            if action == "cancel":
                if status == "completed":
                    raise ValueError("Completed tasks cannot be cancelled.")
                status = "cancelled"
            elif action == "pause":
                if status not in ("planned", "running", "paused"):
                    raise ValueError("Only planned or running tasks can be paused.")
                status = "paused"
            elif action == "resume":
                if status != "paused":
                    raise ValueError("Only paused tasks can be resumed.")
                if any(step["status"] in ("failed", "interrupted") for step in task["steps"]):
                    raise ValueError("Failed or interrupted steps require an explicit retry.")
                status = ("completed" if all(step["status"] == "completed" for step in task["steps"])
                          else "running" if any(step["status"] == "running" for step in task["steps"]) else "planned")
            else:
                if status not in ("failed", "interrupted", "paused"):
                    raise ValueError("Only failed or interrupted work can be explicitly retried.")
                step = next((item for item in task["steps"] if item["status"] != "completed"), None)
                if not step or step["status"] not in ("failed", "interrupted"):
                    raise ValueError("There is no failed or interrupted step to retry.")
                if len(step["attempts"]) >= self.MAX_ATTEMPTS:
                    raise ValueError("This step has reached its attempt limit.")
                db.execute("UPDATE steps SET status='pending' WHERE task_id=? AND step_index=?", (task_id, step["index"]))
                status = "planned"
            db.execute("UPDATE tasks SET status=?,updated_at=? WHERE id=?", (status, _now(), task_id))
            return self._task(db, task_id)

    def recover_interrupted(self):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task_ids = [row[0] for row in db.execute("SELECT DISTINCT task_id FROM steps WHERE status='running'")]
            now = _now()
            # A process can stop after saving a receipt and before claiming its
            # next step. That work is safely paused, not still executing.
            db.execute("UPDATE tasks SET status='paused',updated_at=? WHERE status='running' AND NOT EXISTS (SELECT 1 FROM steps WHERE steps.task_id=tasks.id AND steps.status='running')", (now,))
            db.execute("UPDATE attempts SET status='interrupted',ended_at=?,interruption_reason=? WHERE status='running'", (now, _INTERRUPTION))
            db.execute("UPDATE steps SET status='interrupted' WHERE status='running'")
            for task_id in task_ids:
                db.execute("UPDATE tasks SET status=CASE WHEN status IN ('paused','cancelled') THEN status ELSE 'interrupted' END,updated_at=? WHERE id=?", (now, task_id))
            return len(task_ids)

    def reflect(self, task_id, summary, uncertainties=None, next_steps=None, *, origin="model"):
        summary = _text(summary, 2000, "Reflection summary")
        lists = []
        for value, label in ((uncertainties, "Uncertainties"), (next_steps, "Suggested next steps")):
            value = [] if value is None else value
            if not isinstance(value, list) or len(value) > 8:
                raise ValueError(f"{label} must contain at most eight text items.")
            lists.append(_json([_text(item, 500, label) for item in value], 20000))
        if origin not in ("user", "model", "system"):
            raise ValueError("Unknown reflection origin.")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._task(db, task_id)
            if db.execute("SELECT COUNT(*) FROM reflections WHERE task_id=?", (task_id,)).fetchone()[0] >= self.MAX_REFLECTIONS:
                raise ValueError("This task has reached its reflection limit.")
            now = _now()
            db.execute("INSERT INTO reflections(task_id,summary,uncertainties,next_steps,origin,created_at) VALUES(?,?,?,?,?,?)", (task_id, summary, *lists, origin, now))
            db.execute("UPDATE tasks SET updated_at=? WHERE id=?", (now, task_id))
            return self._task(db, task_id)

    def delete(self, task_id):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = self._task(db, task_id)
            if any(step["status"] == "running" for step in task["steps"]):
                raise ValueError("A running step must return its receipt before the task can be deleted.")
            db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
            return {"deleted": task_id}
