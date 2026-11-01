import concurrent.futures
import copy
import sqlite3
import tempfile
import threading
import unittest

from solrdm_pi.memory import MemoryStore
from solrdm_pi.tools import execute_tool
from solrdm_pi.workspace import WorkspaceStore


def calculation(expression="4*5"):
    return {"name": "calculate", "arguments": {"expression": expression}, "purpose": "Compute the requested result."}


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = WorkspaceStore(self.temp.name)

    def finish(self, task_id, claim=None):
        claim = claim or self.store.start_step(task_id)
        receipt = execute_tool(claim["name"], claim["arguments"])
        return self.store.finish_step(task_id, claim["index"], receipt, attempt_id=claim["attempt_id"])

    def test_plan_is_persistent_private_and_does_not_execute(self):
        task = self.store.create("Compute an answer", [calculation()])
        self.assertEqual(task["status"], "planned")
        self.assertEqual(task["steps"][0]["status"], "pending")
        self.assertIsNone(task["steps"][0]["receipt"])
        self.assertEqual(task["steps"][0]["attempts"], [])
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(WorkspaceStore(self.temp.name).get(task["id"]), task)

    def test_real_receipt_persists_and_completed_work_cannot_rerun(self):
        task = self.store.create("Find the product", [calculation("12345*6789")])
        complete = self.finish(task["id"])
        self.assertEqual(complete["status"], "completed")
        self.assertEqual(complete["steps"][0]["receipt"]["data"]["result"], 83810205)
        self.assertEqual(complete["steps"][0]["attempts"][0]["status"], "completed")
        restored = WorkspaceStore(self.temp.name)
        self.assertEqual(restored.get(task["id"]), complete)
        for operation in (restored.start_step, restored.retry, restored.resume):
            with self.assertRaises(ValueError):
                operation(task["id"])

    def test_claim_is_atomic_and_concurrent_workers_do_not_repeat_side_effect(self):
        memory = MemoryStore(self.temp.name)
        task = self.store.create("Save the user's preference", [{"name": "remember_observation",
            "arguments": {"text": "I prefer metric units", "source": "User request"}, "purpose": "Save for human review."}])
        barrier = threading.Barrier(12)

        def execute(_):
            barrier.wait(timeout=5)
            try:
                claim = self.store.start_step(task["id"])
            except ValueError:
                return False
            receipt = execute_tool(claim["name"], claim["arguments"], memory=memory)
            self.store.finish_step(task["id"], claim["index"], receipt, attempt_id=claim["attempt_id"])
            return True

        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            outcomes = list(pool.map(execute, range(12)))
        self.assertEqual(sum(outcomes), 1)
        self.assertEqual(len(memory.list()), 1)
        self.assertEqual(memory.list()[0]["status"], "unreviewed")
        self.assertEqual(memory.relevant("metric units"), [])
        self.assertEqual(len(self.store.get(task["id"])["steps"][0]["attempts"]), 1)

    def test_cancel_during_execution_preserves_actual_receipt_and_stops_next_step(self):
        task = self.store.create("Calculate twice", [calculation("1+1"), calculation("2+2")])
        started, finish_allowed = threading.Event(), threading.Event()

        def execute():
            claim = self.store.start_step(task["id"])
            started.set()
            finish_allowed.wait(timeout=5)
            return self.finish(task["id"], claim)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(execute)
            self.assertTrue(started.wait(timeout=5))
            self.store.cancel(task["id"])
            with self.assertRaisesRegex(ValueError, "receipt"):
                self.store.delete(task["id"])
            finish_allowed.set()
            cancelled = future.result(timeout=5)
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["steps"][0]["receipt"]["data"]["result"], 2)
        self.assertEqual(cancelled["steps"][1]["status"], "pending")
        self.assertEqual(cancelled["steps"][1]["attempts"], [])
        for action in (self.store.start_step, self.store.resume, self.store.retry):
            with self.assertRaises(ValueError):
                action(task["id"])

    def test_pause_waits_for_inflight_receipt_and_resume_allows_next_step(self):
        task = self.store.create("Calculate twice", [calculation("1+1"), calculation("2+2")])
        claim = self.store.start_step(task["id"])
        self.store.pause(task["id"])
        paused = self.finish(task["id"], claim)
        self.assertEqual(paused["status"], "paused")
        self.assertEqual(paused["steps"][0]["status"], "completed")
        with self.assertRaises(ValueError):
            self.store.start_step(task["id"])
        self.assertEqual(self.store.resume(task["id"])["status"], "planned")
        self.assertEqual(self.finish(task["id"])["status"], "completed")

    def test_pause_final_step_then_resume_marks_completed_without_execution(self):
        task = self.store.create("Compute", [calculation()])
        claim = self.store.start_step(task["id"])
        self.store.pause(task["id"])
        self.finish(task["id"], claim)
        resumed = self.store.resume(task["id"])
        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(len(resumed["steps"][0]["attempts"]), 1)

    def test_failed_receipt_stops_task_and_explicit_retry_retains_evidence(self):
        task = self.store.create("Compute", [calculation()])
        claim = self.store.start_step(task["id"])
        failed = {"tool": "calculate", "status": "failed", "summary": "Test tool failure."}
        result = self.store.finish_step(task["id"], 0, failed, attempt_id=claim["attempt_id"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["steps"][0]["receipt"], failed)
        with self.assertRaises(ValueError):
            self.store.start_step(task["id"])
        self.store.retry(task["id"])
        complete = self.finish(task["id"])
        self.assertEqual(complete["status"], "completed")
        self.assertEqual(complete["steps"][0]["attempts"][0]["receipt"], failed)
        self.assertEqual(len(complete["steps"][0]["attempts"]), 2)

    def test_restart_preserves_unknown_outcome_and_requires_explicit_retry(self):
        memory = MemoryStore(self.temp.name)
        task = self.store.create("Save a preference", [{"name": "remember_observation",
            "arguments": {"text": "Use metres", "source": "User request"}, "purpose": "Save for review."}])
        first_claim = self.store.start_step(task["id"])
        # Simulate a process dying after the real side effect but before saving
        # its receipt. Recovery cannot know whether that effect occurred.
        receipt = execute_tool(first_claim["name"], first_claim["arguments"], memory=memory)
        restored = WorkspaceStore(self.temp.name)
        interrupted = restored.get(task["id"])
        self.assertEqual(interrupted["status"], "interrupted")
        self.assertEqual(interrupted["steps"][0]["attempts"][0]["outcome"], "unknown")
        self.assertIsNone(interrupted["steps"][0]["receipt"])
        self.assertIn("may repeat side effects", interrupted["steps"][0]["attempts"][0]["interruption_reason"])
        self.assertEqual(len(memory.list()), 1)
        for action in (restored.start_step, restored.resume):
            with self.assertRaises(ValueError):
                action(task["id"])
        restored.retry(task["id"])
        next_claim = restored.start_step(task["id"])
        self.assertNotEqual(first_claim["attempt_id"], next_claim["attempt_id"])
        with self.assertRaisesRegex(ValueError, "stale"):
            restored.finish_step(task["id"], 0, receipt, attempt_id=first_claim["attempt_id"])
        self.assertEqual(restored.get(task["id"])["steps"][0]["status"], "running")
        self.assertEqual(len(memory.list()), 1)  # Claiming itself never repeats a tool.

    def test_restart_between_steps_is_paused_without_falsifying_saved_receipt(self):
        task = self.store.create("Compute twice", [calculation(), calculation()])
        first = self.finish(task["id"])
        self.assertEqual(first["status"], "running")
        restored = WorkspaceStore(self.temp.name)
        paused = restored.get(task["id"])
        self.assertEqual(paused["status"], "paused")
        self.assertEqual(paused["steps"][0]["receipt"], first["steps"][0]["receipt"])
        self.assertEqual(paused["steps"][1]["status"], "pending")
        with self.assertRaises(ValueError):
            restored.start_step(task["id"])
        restored.resume(task["id"])
        self.assertEqual(restored.start_step(task["id"])["index"], 1)

    def test_recovery_preserves_pause_and_cancel_intent(self):
        for action in ("pause", "cancel"):
            with self.subTest(action=action):
                task = self.store.create("Compute", [calculation()])
                self.store.start_step(task["id"])
                getattr(self.store, action)(task["id"])
                restored = WorkspaceStore(self.temp.name)
                result = restored.get(task["id"])
                self.assertEqual(result["status"], "paused" if action == "pause" else "cancelled")
                self.assertEqual(result["steps"][0]["status"], "interrupted")
                with self.assertRaises(ValueError):
                    restored.resume(task["id"])

    def test_duplicate_or_wrong_tool_receipts_cannot_overwrite_result(self):
        task = self.store.create("Compute", [calculation()])
        claim = self.store.start_step(task["id"])
        wrong = {"tool": "research_papers", "status": "completed", "summary": "Not the claimed tool"}
        with self.assertRaisesRegex(ValueError, "match"):
            self.store.finish_step(task["id"], 0, wrong, attempt_id=claim["attempt_id"])
        complete = self.finish(task["id"], claim)
        with self.assertRaisesRegex(ValueError, "stale"):
            self.store.finish_step(task["id"], 0, complete["steps"][0]["receipt"], attempt_id=claim["attempt_id"])
        self.assertEqual(self.store.get(task["id"]), complete)

    def test_schema_rejects_unsupported_tools_extra_arguments_and_invalid_numbers(self):
        invalid = [
            {"name": "run_shell", "arguments": {"command": "echo hello"}, "purpose": "Execute shell"},
            {"name": "remember_observation", "arguments": {"text": "Fact", "source": "model", "approved": True}, "purpose": "Bypass review"},
            {"name": "calculate", "arguments": {"expression": "2+2", "other": 1}, "purpose": "Compute"},
            {"name": "calculate", "arguments": {}, "purpose": "Compute"},
            {"name": "calculate", "arguments": {"expression": " "}, "purpose": "Compute"},
            {"name": "calculate", "arguments": {"expression": "2\n+2"}, "purpose": "Compute"},
            {"name": "describe_statistics", "arguments": {"numbers": []}, "purpose": "Review"},
            {"name": "describe_statistics", "arguments": {"numbers": [True]}, "purpose": "Review"},
            {"name": "describe_statistics", "arguments": {"numbers": [float("nan")]}, "purpose": "Review"},
            {"name": "describe_statistics", "arguments": {"numbers": [10 ** 1000]}, "purpose": "Review"},
            {"name": "simulate_projectile", "arguments": {"speed": -1, "angle": 45, "gravity": 9.81}, "purpose": "Simulate"},
        ]
        for step in invalid:
            with self.subTest(step=step), self.assertRaises(ValueError):
                self.store.create("Try a plan", [step])
        self.assertEqual(self.store.list(), [])

    def test_plan_limits_and_returned_data_are_not_mutable_database_references(self):
        for goal, steps, label in [("", [calculation()], ""), ("x" * 4001, [calculation()], ""),
                                   ("Compute", [], ""), ("Compute", [calculation()] * 7, ""),
                                   ("Compute", [calculation()], "x" * 121)]:
            with self.subTest(goal=goal[:10]), self.assertRaises(ValueError):
                self.store.create(goal, steps, label)
        steps = [calculation()]
        task = self.store.create("Compute", steps)
        original = copy.deepcopy(task)
        steps[0]["arguments"]["expression"] = "evil"
        task["steps"][0]["arguments"]["expression"] = "changed"
        self.assertEqual(self.store.get(task["id"]), original)

    def test_capacity_is_atomic_across_concurrent_creation(self):
        self.store.MAX_TASKS = 4

        def create(index):
            try:
                self.store.create(f"Task {index}", [calculation()])
                return True
            except ValueError:
                return False

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(create, range(12)))
        self.assertEqual(sum(results), 4)
        self.assertEqual(self.store.stats()["total"], 4)
        self.store.delete(self.store.list()[0]["id"])
        self.store.create("Capacity freed", [calculation()])

    def test_reflections_are_bounded_unverified_suggestions_and_do_not_change_memory(self):
        memory = MemoryStore(self.temp.name)
        note = memory.add("An uncertain hypothesis", origin="model")
        task = self.store.create("Review a hypothesis", [calculation()])
        reflected = self.store.reflect(task["id"], "Check the hypothesis against observations.",
            ["No independent measurement yet."], ["Collect new measurements."])
        reflection = reflected["reflection"]
        self.assertFalse(reflection["verified"])
        self.assertFalse(reflection["trains_weights"])
        self.assertEqual(reflection["kind"], "suggestion")
        self.assertEqual(reflection["origin"], "model")
        self.assertEqual(memory.list(), [note])
        self.assertEqual(WorkspaceStore(self.temp.name).get(task["id"])["reflection"], reflection)
        self.store.MAX_REFLECTIONS = 1
        with self.assertRaisesRegex(ValueError, "limit"):
            self.store.reflect(task["id"], "More reflection")
        for uncertainty in (["x"] * 9, "Not a list", ["x" * 501]):
            with self.assertRaises(ValueError):
                self.store.reflect(task["id"], "Summary", uncertainty)

    def test_retry_attempt_limit_and_receipt_size_are_bounded(self):
        self.store.MAX_ATTEMPTS = 1
        task = self.store.create("Compute", [calculation()])
        claim = self.store.start_step(task["id"])
        failed = {"tool": "calculate", "status": "failed", "summary": "Tool failed"}
        too_large = dict(failed, data="x" * self.store.MAX_RECEIPT_BYTES)
        with self.assertRaisesRegex(ValueError, "storage limit"):
            self.store.finish_step(task["id"], 0, too_large, attempt_id=claim["attempt_id"])
        self.assertEqual(self.store.get(task["id"])["steps"][0]["status"], "running")
        self.store.finish_step(task["id"], 0, failed, attempt_id=claim["attempt_id"])
        with self.assertRaisesRegex(ValueError, "attempt limit"):
            self.store.retry(task["id"])

    def test_maximum_unicode_notebook_and_research_receipts_fit_storage_bound(self):
        memory = MemoryStore(self.temp.name)
        for _ in range(10):
            note = memory.add("needle " + "\U0001f30d" * 3993, "\U0001f30d" * 500)
            memory.review(note["id"], True)
        item = {"DOI": "10.1234/" + "\U0001f30d" * 180, "title": ["\U0001f30d" * 1000],
                "author": [{"given": "\U0001f30d" * 200}] * 10, "abstract": "\U0001f30d" * 4000}
        for name in ("recall_observations", "research_papers"):
            with self.subTest(tool=name):
                task = self.store.create("Review large bounded evidence", [
                    {"name": name, "arguments": {"query": "needle"}, "purpose": "Review source records."}])
                claim = self.store.start_step(task["id"])
                receipt = execute_tool(name, claim["arguments"], memory=memory,
                    fetch_json=lambda _: {"message": {"items": [item] * 5}})
                complete = self.store.finish_step(task["id"], 0, receipt, attempt_id=claim["attempt_id"])
                self.assertEqual(complete["status"], "completed")
                self.assertEqual(complete["steps"][0]["receipt"], receipt)

    def test_deletion_cascades_evidence_and_stats_describe_actual_active_work(self):
        self.assertEqual(self.store.stats(), {"total": 0, "counts": {}, "current_goal": None, "current_status": None})
        task = self.store.create("Compute", [calculation()])
        self.assertEqual(self.store.stats()["current_goal"], "Compute")
        self.finish(task["id"])
        self.store.reflect(task["id"], "Computed the requested arithmetic.", origin="system")
        self.assertEqual(self.store.stats()["counts"], {"completed": 1})
        self.assertIsNone(self.store.stats()["current_goal"])
        self.store.delete(task["id"])
        with sqlite3.connect(self.store.path) as db:
            for table in ("tasks", "steps", "attempts", "reflections"):
                self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)

    def test_summaries_return_compact_metadata_and_actual_completion_counts(self):
        self.assertEqual(self.store.summaries(), [])
        first = self.store.create("Compute twice", [calculation(), calculation()], label="Two calculations")
        second = self.store.create("Compute once", [calculation()])
        self.finish(first["id"])
        self.store.reflect(first["id"], "One of two steps has completed.", origin="system")
        rows = self.store.summaries()
        self.assertEqual([row["id"] for row in rows], [second["id"], first["id"]])
        self.assertEqual(set(rows[0]), {"id", "goal", "label", "status", "created_at", "updated_at", "step_count", "completed_steps"})
        self.assertEqual((rows[0]["step_count"], rows[0]["completed_steps"]), (1, 0))
        self.assertEqual((rows[1]["step_count"], rows[1]["completed_steps"]), (2, 1))
        self.assertEqual(rows[1]["status"], "running")
        self.assertEqual(rows[1]["label"], "Two calculations")
        self.assertEqual(self.store.summaries(limit=1), rows[:1])
        completed = self.finish(first["id"])
        summary = self.store.summaries()[1]
        self.assertEqual(summary["completed_steps"], 2)
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["updated_at"], completed["updated_at"])
        self.assertEqual(len(self.store.get(first["id"])["steps"]), 2)
        for invalid in (True, 0, -1, 101, "5", 1.5):
            with self.subTest(limit=invalid), self.assertRaises(ValueError):
                self.store.summaries(invalid)

    def test_invalid_ids_limits_and_missing_records(self):
        for value in (True, 0, -1, "1", 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.store.get(value)
        for value in (True, 0, -1, 101, "5", 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.store.list(value)
        for action in (self.store.get, self.store.start_step, self.store.pause, self.store.cancel,
                       self.store.resume, self.store.retry, self.store.delete):
            with self.assertRaisesRegex(ValueError, "not found"):
                action(99999)


if __name__ == "__main__":
    unittest.main()
