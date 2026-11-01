"""Task integration contracts; controlled responses are not model quality proof."""
import json
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from solrdm_pi.agent import Agent, AgentError
from solrdm_pi.memory import MemoryStore
from solrdm_pi.models import ModelReply
from solrdm_pi.planning import TaskController
from solrdm_pi.workspace import WorkspaceStore
from solrdm_pi.tools import execute_tool


STEP = {"name": "calculate", "arguments": {"expression": "12345*6789"}, "purpose": "Compute the product"}


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.memory = MemoryStore(self.directory.name)
        self.store = WorkspaceStore(self.directory.name)
        self.models = Mock()
        self.models.status.return_value = {"state": "ready", "ready": True, "model_name": "Fixture"}
        self.agent = Agent(self.models, self.memory, lambda: {"preferred_backend": "local"})
        self.controller = TaskController(self.agent, self.store, self.memory)
        self.addCleanup(self.controller.close)

    def test_model_plan_waits_for_explicit_run_then_actual_receipts_persist(self):
        self.models.chat.return_value = json.dumps({"steps": [STEP]})
        task = self.controller.plan("Use calculate to evaluate 12345 * 6789")
        self.assertEqual(task["status"], "planned")
        self.assertIsNone(task["steps"][0]["receipt"])
        self.assertEqual(self.models.chat.call_count, 1)
        self.controller.run(task["id"])
        self.controller.worker.join(3)
        finished = self.store.get(task["id"])
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["steps"][0]["receipt"]["data"]["result"], 83810205)
        self.assertEqual(WorkspaceStore(self.directory.name).get(task["id"]), finished)
        with self.assertRaises(AgentError):
            self.controller.run(task["id"])

    def test_invalid_and_partial_plans_do_not_save_or_execute(self):
        invalid = ['{}', '{"steps":[],"steps":[]}', '{"steps":null}', '{"steps":"bad"}',
                   '{"steps":[{"name":"shell","arguments":{},"purpose":"bad"}]}',
                   ModelReply(json.dumps({"steps": [STEP]}), incomplete=True)]
        for answer in invalid:
            self.models.chat.return_value = answer
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                self.controller.plan("Multiply two numbers")
        self.assertEqual(self.store.list(), [])

    def test_explicit_tool_plan_cannot_switch_to_memory_write(self):
        self.models.chat.return_value = json.dumps({"steps": [{"name": "remember_observation",
            "arguments": {"text": "unrequested", "source": "model"}, "purpose": "Save"}]})
        with self.assertRaises(AgentError):
            self.controller.plan("Use calculate to evaluate 2+2")
        self.assertEqual(self.memory.list(), [])

    def test_plan_and_reflection_share_chat_inference_lock(self):
        self.agent.lock.acquire()
        try:
            with self.assertRaises(AgentError):
                self.controller.plan("Compute 1+1")
        finally:
            self.agent.lock.release()
        self.models.chat.assert_not_called()

    def test_cancel_running_step_keeps_receipt_and_stops_next_action(self):
        entered, release = threading.Event(), threading.Event()
        def delayed(name, args, **kwargs):
            entered.set()
            release.wait(3)
            return execute_tool(name, args, **kwargs)
        task = self.store.create("Two operations", [STEP, STEP])
        with patch("solrdm_pi.planning.execute_tool", side_effect=delayed) as tool:
            self.controller.run(task["id"])
            self.assertTrue(entered.wait(2))
            with self.assertRaises(AgentError):
                self.controller.run(task["id"])
            self.store.cancel(task["id"])
            release.set()
            self.controller.worker.join(3)
            self.assertEqual(tool.call_count, 1)
        result = self.store.get(task["id"])
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["steps"][0]["status"], "completed")
        self.assertEqual(result["steps"][1]["status"], "pending")

    def test_pause_resume_does_not_duplicate_running_step(self):
        entered, release = threading.Event(), threading.Event()
        def delayed(name, args, **kwargs):
            entered.set()
            release.wait(3)
            return execute_tool(name, args, **kwargs)
        task = self.store.create("Two operations", [STEP, STEP])
        with patch("solrdm_pi.planning.execute_tool", side_effect=delayed) as tool:
            self.controller.run(task["id"])
            self.assertTrue(entered.wait(2))
            self.store.pause(task["id"])
            self.controller.run(task["id"], "resume")
            release.set()
            self.controller.worker.join(3)
            self.assertEqual(tool.call_count, 2)
        self.assertEqual(self.store.get(task["id"])["status"], "completed")

    def test_failed_tool_needs_explicit_retry_and_preserves_previous_receipt(self):
        task = self.store.create("Compute product", [STEP])
        with patch("solrdm_pi.planning.execute_tool", side_effect=ValueError("Temporary failure")):
            self.controller.run(task["id"])
            self.controller.worker.join(3)
        self.assertEqual(self.store.get(task["id"])["status"], "failed")
        self.controller.run(task["id"], "retry")
        self.controller.worker.join(3)
        step = self.store.get(task["id"])["steps"][0]
        self.assertEqual([a["status"] for a in step["attempts"]], ["failed", "completed"])

    def test_reflection_is_labeled_analysis_and_does_not_approve_memory(self):
        note = self.memory.add("unverified")
        task = self.store.create("Compute product", [STEP])
        self.models.chat.return_value = json.dumps({"summary": "No steps ran.", "uncertainties": ["Pending work"], "next_steps": ["Run plan"]})
        task = self.controller.reflect(task["id"])
        self.assertEqual(task["status"], "planned")
        self.assertFalse(task["reflection"]["verified"])
        self.assertFalse(task["reflection"]["trains_weights"])
        self.assertEqual(self.memory.list()[0]["id"], note["id"])
        self.assertEqual(self.memory.list()[0]["status"], "unreviewed")

    def test_self_report_requires_no_model_and_uses_real_notebook_counts(self):
        self.models.status.return_value = {"state": "stopped", "ready": False}
        note = self.memory.add("Preference")
        self.memory.review(note["id"], True)
        result = self.agent.run({"text": "Can you learn?"})
        self.assertTrue(result["grounded_self_report"])
        self.assertIn("1 approved", result["text"])
        self.assertIn("do not automatically", result["text"])
        self.models.chat.assert_not_called()


if __name__ == "__main__":
    unittest.main()
