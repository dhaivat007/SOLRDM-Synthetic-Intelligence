"""Independent lifecycle checks with controlled model replies and real stores."""
import json
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from solrdm_pi.agent import Agent, AgentError
from solrdm_pi.memory import MemoryStore
from solrdm_pi.models import ModelReply
from solrdm_pi.planning import TaskController
from solrdm_pi.server import Application
from solrdm_pi.tools import execute_tool
from solrdm_pi.workspace import WorkspaceStore


def step(expression):
    return {"name": "calculate", "arguments": {"expression": expression}, "purpose": "Compute the requested value"}


class PlanningAuditTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.memory = MemoryStore(self.directory.name)
        self.workspace = WorkspaceStore(self.directory.name)
        self.models = Mock()
        self.models.status.return_value = {"ready": True, "state": "ready", "model_name": "Controlled test model"}
        self.agent = Agent(self.models, self.memory, lambda: {"preferred_backend": "local"})
        self.controller = TaskController(self.agent, self.workspace, self.memory)
        self.addCleanup(self.controller.close)

    def wait_worker(self):
        self.controller.worker.join(timeout=3)
        self.assertFalse(self.controller.worker.is_alive(), "The approved task worker did not finish")

    def test_generated_plan_has_no_side_effect_until_explicit_run(self):
        self.models.chat.return_value = json.dumps({"steps": [{
            "name": "remember_observation", "arguments": {"text": "Preferred units: metres", "source": "user request"},
            "purpose": "Save the requested preference for review"}]})
        task = self.controller.plan("Remember that I prefer metres")
        self.assertEqual(task["status"], "planned")
        self.assertEqual(self.memory.list(), [])
        self.assertIsNone(self.controller.worker)
        self.controller.run(task["id"])
        self.wait_worker()
        self.assertEqual(self.workspace.get(task["id"])["status"], "completed")
        self.assertEqual(len(self.memory.list()), 1)
        self.assertEqual(self.memory.list()[0]["status"], "unreviewed")

    def test_partial_duplicate_and_unavailable_model_plans_never_create_tasks(self):
        values = (
            ModelReply('{"steps":[]}', incomplete=True),
            '{"steps":[],"steps":[]}',
            '{"steps":[{"name":"shell","arguments":{"command":"true"},"purpose":"Run code"}]}',
            '{"steps":[{"name":"calculate","arguments":{"expression":"2+2","extra":true},"purpose":"Compute"}]}',
        )
        for value in values:
            with self.subTest(value=value):
                self.models.chat.return_value = value
                with self.assertRaises(ValueError):
                    self.controller.plan("Calculate two plus two")
                self.assertEqual(self.workspace.list(), [])
        self.models.status.return_value = {"ready": False}
        with self.assertRaisesRegex(AgentError, "Load"):
            self.controller.plan("Calculate two plus two")
        self.assertEqual(self.workspace.list(), [])

    def test_only_actual_tool_receipts_mark_steps_complete(self):
        task = self.workspace.create("Two calculations", [step("2+2"), step("sqrt(81)")])
        self.controller.run(task["id"])
        self.wait_worker()
        restored = self.workspace.get(task["id"])
        self.assertEqual(restored["status"], "completed")
        self.assertEqual([item["receipt"]["data"]["result"] for item in restored["steps"]], [4, 9])
        self.assertEqual([len(item["attempts"]) for item in restored["steps"]], [1, 1])
        self.models.chat.assert_not_called()

    def test_pause_during_active_tool_preserves_receipt_and_blocks_next_step(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        task = self.workspace.create("Pause between calculations", [step("2+2"), step("3+3")])

        def blocking_tool(name, arguments, **kwargs):
            entered.set()
            if not release.wait(timeout=3):
                raise RuntimeError("Test did not release active tool")
            return execute_tool(name, arguments, **kwargs)

        with patch("solrdm_pi.planning.execute_tool", side_effect=blocking_tool) as tool:
            self.controller.run(task["id"])
            self.assertTrue(entered.wait(timeout=2))
            self.workspace.pause(task["id"])
            release.set()
            self.wait_worker()
            paused = self.workspace.get(task["id"])
            self.assertEqual(paused["status"], "paused")
            self.assertEqual(paused["steps"][0]["receipt"]["data"]["result"], 4)
            self.assertEqual(paused["steps"][1]["status"], "pending")
            self.assertEqual(tool.call_count, 1)
            self.controller.run(task["id"], "resume")
            self.wait_worker()
            self.assertEqual(tool.call_count, 2)
        completed = self.workspace.get(task["id"])
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(len(completed["steps"][0]["attempts"]), 1)

    def test_cancel_during_active_tool_keeps_result_but_never_starts_next_step(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        task = self.workspace.create("Cancel after current calculation", [step("7*6"), step("10+1")])

        def blocking_tool(name, arguments, **kwargs):
            entered.set()
            if not release.wait(timeout=3):
                raise RuntimeError("Test did not release active tool")
            return execute_tool(name, arguments, **kwargs)

        with patch("solrdm_pi.planning.execute_tool", side_effect=blocking_tool) as tool:
            self.controller.run(task["id"])
            self.assertTrue(entered.wait(timeout=2))
            self.workspace.cancel(task["id"])
            release.set()
            self.wait_worker()
            self.assertEqual(tool.call_count, 1)
        cancelled = self.workspace.get(task["id"])
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["steps"][0]["receipt"]["data"]["result"], 42)
        self.assertEqual(cancelled["steps"][1]["attempts"], [])
        with self.assertRaises(ValueError):
            self.controller.run(task["id"], "resume")

    def test_second_task_is_not_claimed_while_first_tool_is_running(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        first = self.workspace.create("First", [step("1+1")])
        second = self.workspace.create("Second", [step("2+2")])

        def blocking_tool(name, arguments, **kwargs):
            entered.set()
            if not release.wait(timeout=3):
                raise RuntimeError("Test did not release active tool")
            return execute_tool(name, arguments, **kwargs)

        with patch("solrdm_pi.planning.execute_tool", side_effect=blocking_tool):
            self.controller.run(first["id"])
            self.assertTrue(entered.wait(timeout=2))
            with self.assertRaisesRegex(AgentError, "Another task"):
                self.controller.run(second["id"])
            self.assertEqual(self.workspace.get(second["id"])["steps"][0]["attempts"], [])
            release.set()
            self.wait_worker()

    def test_failed_tool_stops_remaining_steps_until_explicit_retry(self):
        task = self.workspace.create("Fail safely", [step("1/0"), step("2+2")])
        self.controller.run(task["id"])
        self.wait_worker()
        failed = self.workspace.get(task["id"])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["steps"][0]["receipt"]["status"], "failed")
        self.assertEqual(failed["steps"][1]["attempts"], [])
        with self.assertRaises(AgentError):
            self.controller.run(task["id"])
        self.assertEqual(len(self.workspace.get(task["id"])["steps"][0]["attempts"]), 1)

    def test_reflection_never_executes_suggested_actions_or_verifies_itself(self):
        task = self.workspace.create("Review calculation", [step("5*5")])
        self.controller.run(task["id"])
        self.wait_worker()
        self.models.chat.return_value = json.dumps({"summary": "The calculator returned 25.",
                                                   "uncertainties": ["Inputs may need review."],
                                                   "next_steps": ["Remember this as a notebook observation."]})
        reflected = self.controller.reflect(task["id"])
        self.assertEqual(self.memory.list(), [])
        self.assertFalse(reflected["reflection"]["verified"])
        self.assertFalse(reflected["reflection"]["trains_weights"])
        self.assertEqual(reflected["reflection"]["origin"], "model")
        self.assertEqual(len(reflected["steps"][0]["attempts"]), 1)

    def test_mode_mismatch_cannot_write_notebook_from_math_chat(self):
        self.models.chat.side_effect = [json.dumps({"tool": "remember_observation", "arguments": {
            "text": "Unrequested note", "source": "controlled model reply"}}),
            '{"answer":"The unsupported action did not run."}']
        result = self.agent.run({"mode": "math", "text": "Calculate 2+2"})
        self.assertEqual(self.memory.list(), [])
        self.assertEqual(result["receipts"][0]["status"], "failed")

    def test_duplicate_application_cannot_recover_an_existing_live_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Application(directory)
            self.addCleanup(app.close)
            task = app.workspace.create("Existing task", [step("2+2")])
            claim = app.workspace.start_step(task["id"])
            with self.assertRaisesRegex(ValueError, "already using this data directory"):
                Application(directory)
            current = app.workspace.get(task["id"])
            self.assertEqual(current["status"], "running")
            self.assertEqual(current["steps"][0]["attempt_id"], claim["attempt_id"])
            self.assertEqual(current["steps"][0]["attempts"][0]["outcome"], "running")
            app.close()


if __name__ == "__main__":
    unittest.main()
