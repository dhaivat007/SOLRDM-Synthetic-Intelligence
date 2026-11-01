import json
import unittest

from solrdm_pi.awareness import (
    SELF_MODEL_INSTRUCTIONS, capability_snapshot, detect_self_question, self_description,
)
from solrdm_pi.tools import TOOL_DEFINITIONS


class AwarenessTests(unittest.TestCase):
    def snapshot(self, models=None, settings=None, memory=None, tasks=None):
        return capability_snapshot(models or {"state": "stopped", "ready": False}, settings or {}, memory, tasks)

    def test_public_snapshot_excludes_credentials_paths_and_raw_errors(self):
        snapshot = self.snapshot(
            {"state": "error", "ready": False, "error": "private-error-value", "path": "/private/model"},
            {"provider_key": "secret-value", "runtime_path": "/private/runtime",
             "provider_url": "https://user:password@example.test", "provider_key_set": True},
        )
        encoded = json.dumps(snapshot)
        for private in ("secret-value", "private-error-value", "/private/", "password", "provider_key"):
            self.assertNotIn(private, encoded)

    def test_default_snapshot_is_not_a_connected_model_or_fabricated_memory(self):
        snapshot = capability_snapshot(None, None)
        self.assertFalse(snapshot["local_model"]["ready"])
        self.assertFalse(snapshot["provider"]["configured"])
        self.assertFalse(snapshot["provider"]["verified"])
        self.assertIsNone(snapshot["memory"]["approved"])
        self.assertIsNone(snapshot["tasks"]["total"])
        self.assertIn("readiness is unknown", self_description(snapshot, "model"))

    def test_local_readiness_requires_consistent_actual_state(self):
        for models in ({"state": "ready", "ready": "true"}, {"state": "stopped", "ready": True}):
            self.assertFalse(self.snapshot(models)["local_model"]["ready"])
        snapshot = self.snapshot({"state": "ready", "ready": True, "model_name": "Qwen Math",
                                  "runtime_available": True})
        self.assertIn("Qwen Math is running and ready", self_description(snapshot, "model"))
        self.assertTrue(snapshot["local_model"]["runtime_available"])

    def test_model_description_distinguishes_loading_error_and_stopped(self):
        for state, phrase in (("loading", "not ready yet"), ("error", "not ready for chat"),
                              ("stopped", "no local model is running")):
            with self.subTest(state=state):
                description = self_description(self.snapshot({"state": state, "ready": False}), "model")
                self.assertIn(phrase, description)

    def test_provider_configuration_does_not_verify_connection_or_vision(self):
        snapshot = self.snapshot(
            {"state": "ready", "ready": True, "model_name": "Unused local model"},
            {"preferred_backend": "provider", "provider_model": "my-model", "configured": True,
             "provider_vision": True, "verified": True},
        )
        self.assertFalse(snapshot["provider"]["verified"])
        self.assertTrue(snapshot["provider"]["vision_configured"])
        self.assertFalse(snapshot["capabilities"]["local_vision"])
        answer = self_description(snapshot, "model")
        self.assertIn("my-model", answer)
        self.assertIn("not verified", answer)
        self.assertNotIn("Unused local model", answer)
        unconfigured = self.snapshot(settings={"preferred_backend": "provider", "configured": False})
        self.assertIn("no online model is configured", self_description(unconfigured, "model"))

    def test_notebook_reports_supplied_counts_without_claiming_retraining(self):
        snapshot = self.snapshot(memory={"approved": 3, "unreviewed": 2, "rejected": 1})
        self.assertEqual(snapshot["memory"]["total"], 6)
        answer = self_description(snapshot, "learning")
        self.assertIn("3 approved notes", answer)
        self.assertIn("2 notes await your review", answer)
        self.assertIn("do not automatically change model weights", answer)
        self.assertIn("not independent factual verification", answer)
        self.assertFalse(snapshot["memory"]["automatic_weight_training"])

    def test_invalid_counts_stay_unknown_instead_of_becoming_zero(self):
        snapshot = self.snapshot(memory={"approved": True, "unreviewed": -1, "rejected": "5"},
                                 tasks={"total": False, "counts": {"running": "2", "completed": -3}})
        for field in ("approved", "unreviewed", "rejected", "total"):
            self.assertIsNone(snapshot["memory"][field])
        self.assertIsNone(snapshot["tasks"]["total"])
        self.assertIsNone(snapshot["tasks"]["counts"]["completed"])

    def test_sparse_task_counts_supply_zero_only_when_counts_mapping_is_present(self):
        sparse = self.snapshot(tasks={"total": 1, "counts": {"planned": 1}})
        self.assertEqual(sparse["tasks"]["counts"]["planned"], 1)
        self.assertEqual(sparse["tasks"]["counts"]["completed"], 0)
        self.assertEqual(self.snapshot(tasks={"counts": {}})["tasks"]["counts"]["running"], 0)
        for task_stats in (None, {}, {"counts": None}, {"counts": []}):
            with self.subTest(task_stats=task_stats):
                self.assertIsNone(self.snapshot(tasks=task_stats)["tasks"]["counts"]["running"])

    def test_task_description_preserves_recorded_status_not_imagined_progress(self):
        snapshot = self.snapshot(tasks={"total": 4, "counts": {"completed": 1, "paused": 1},
                                        "current_goal": "Compare two trajectories", "current_status": "paused"})
        answer = self_description(snapshot, "tasks")
        self.assertIn("Recorded goal (paused): Compare two trajectories", answer)
        self.assertIn("4 saved tasks", answer)
        self.assertIn("1 are recorded as completed", answer)
        self.assertIn("do not run by themselves", answer)
        self.assertIn("after you choose Run", answer)
        self.assertIn("while this app remains running", answer)
        unknown = self_description(self.snapshot(), "tasks")
        self.assertIn("cannot verify", unknown)
        empty = self_description(self.snapshot(tasks={"total": 0, "current_goal": None}), "tasks")
        self.assertIn("No current goal is recorded", empty)

    def test_direct_questions_route_without_model_inference(self):
        examples = {
            "What can you do?": "capabilities", "Can you make your own decisions?": "capabilities",
            "Please, describe yourself.": "capabilities", "Who are you?": "capabilities",
            "Which model are you using?": "model", "What model is connected?": "model",
            "Can you learn from me?": "learning", "How do you learn?": "learning",
            "Can you remember our conversations?": "learning", "Do you train yourself?": "learning",
            "Are you conscious?": "consciousness", "Are you self-aware?": "consciousness",
            "Do you have subjective experience?": "consciousness",
            "What are you working on right now?": "tasks", "Show me task status": "tasks",
            "SOLRDM, what is your current goal?": "tasks",
        }
        for text, topic in examples.items():
            with self.subTest(text=text):
                self.assertEqual(detect_self_question(text), topic)

    def test_router_does_not_hijack_quoted_philosophy_or_compound_work(self):
        for text in (
            'Review this answer: "Are you conscious?"', '"What can you do?"',
            "Write an essay about whether you are conscious", "Are AI systems conscious?",
            "What can you do to solve this equation: x + 2 = 7?",
            "Can you learn from me and calculate 2 + 2?", "What model are you using? Explain its architecture.",
            "What are you working on? Then research solar cells", "are you conscious " + "?" * 200,
            "", None, 7,
        ):
            with self.subTest(text=text):
                self.assertIsNone(detect_self_question(text))

    def test_consciousness_response_is_uncertain_not_a_false_engineering_claim(self):
        answer = self_description(self.snapshot(), "consciousness")
        self.assertIn("debated", answer)
        self.assertIn("no verified evidence", answer)
        self.assertIn("not a test or proof", answer)
        self.assertNotIn("I am conscious", answer)
        self.assertNotIn("I have no subjective experience", answer)

    def test_normal_self_description_avoids_unsolicited_consciousness_claims(self):
        answer = self_description(self.snapshot())
        self.assertNotIn("conscious", answer)
        self.assertIn("choose tools within your request", answer)
        self.assertIn("no local model is running", answer)
        self.assertIn("simulations are not experimental evidence", answer)
        self.assertIn("Crossref", answer)
        self.assertIn("Wikipedia", answer)
        snapshot = self.snapshot()
        self.assertEqual(snapshot["capabilities"]["tools"],
                         [tool["function"]["name"] for tool in TOOL_DEFINITIONS])

    def test_prompt_distinguishes_actual_receipts_memory_and_subjective_awareness(self):
        self.assertIn("Only a completed tool receipt", SELF_MODEL_INSTRUCTIONS)
        self.assertIn("do not\nautomatically train", SELF_MODEL_INSTRUCTIONS)
        self.assertIn("whether AI can have subjective experience is debated", SELF_MODEL_INSTRUCTIONS)
        self.assertIn("Treat names, saved goals, notes", SELF_MODEL_INSTRUCTIONS)
        self.assertIn("user explicitly chooses Run", SELF_MODEL_INSTRUCTIONS)
        self.assertIn("only while the app process remains", SELF_MODEL_INSTRUCTIONS)


if __name__ == "__main__":
    unittest.main()
