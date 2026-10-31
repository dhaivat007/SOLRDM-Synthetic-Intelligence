"""Behavioral regression tests for the Android adapter and durable engine state."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

PYTHON_SOURCE = Path(__file__).resolve().parents[1] / "app/src/main/python"
sys.path.insert(0, str(PYTHON_SOURCE))
import android_bridge as bridge


class AndroidEngineBridgeTest(unittest.TestCase):
    def setUp(self):
        self.storage = tempfile.TemporaryDirectory()
        self.addCleanup(self.storage.cleanup)
        self.database = Path(self.storage.name) / "solrdm.sqlite3"

    def call(self, command, payload="", path=None):
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        return json.loads(bridge.execute(str(path or self.database), command, payload))

    def observe(self, subject="rotor", relation="part_of", obj="motor", **extra):
        result = self.call("observe", dict(subject=subject, relation=relation, object=obj, **extra))
        self.assertTrue(result["ok"], result)
        return result

    def seed(self):
        self.observe()
        self.observe("motor", "part_of", "machine")

    def test_status_imports_all_supplied_modules_and_reports_limits(self):
        status = self.call("status")
        self.assertTrue(status["ok"], status)
        expected = {"solrdm" if p.stem == "__init__" else "solrdm." + p.stem for p in (PYTHON_SOURCE / "solrdm").glob("*.py")}
        self.assertEqual(set(status["imported_modules"]), expected)
        self.assertEqual(status["module_count"], 16)
        self.assertFalse(status["general_intelligence"])
        self.assertFalse(status["integration_complete"])
        self.assertEqual(status["observations"], 0)
        self.assertEqual(status["neural_training_steps"], 0)
        self.assertEqual(len(status["ui_commands"]), 6)

    def test_symbolic_inference_is_not_persisted_as_observed_truth(self):
        self.seed()
        response = self.call("query", "rotor")
        self.assertTrue(response["ok"], response)
        derived = [f for f in response["facts"] if f["object"] == "machine"]
        self.assertEqual(len(derived), 1)
        self.assertEqual(derived[0]["source"], "inference")
        self.assertAlmostEqual(derived[0]["confidence"], 0.64)
        self.assertEqual(self.call("status")["observations"], 2)
        discoveries = self.call("discover")["hypotheses"]
        self.assertEqual(len(discoveries), 1)
        self.assertEqual(discoveries[0]["status"], "unverified")
        self.assertEqual(discoveries[0]["hypothesis"]["object"], "machine")
        self.assertEqual(self.call("status")["observations"], 2)

    def test_typed_entities_match_parser_and_query_despite_case_articles_and_spacing(self):
        self.observe("  A Rotor ", "Part Of", "The Motor")
        self.observe("motor", "part_of", "A Machine")
        response = self.call("query", "THE ROTOR")
        self.assertTrue(response["ok"], response)
        facts = response["facts"]
        self.assertTrue(any(f["object"] == "machine" and f["source"] == "inference" for f in facts))
        candidate = self.call("interpret", "A rotor is part of a motor")["candidate_facts"][0]
        self.assertTrue(any(all(f[k] == candidate[k] for k in ("subject", "relation", "object")) for f in facts))
        self.observe("ROTOR", "PART_OF", "MOTOR", confidence=0.9)
        self.assertEqual(self.call("status")["observations"], 2)

    def test_existing_mixed_case_facts_match_without_rewriting_originals(self):
        self.call("status")
        with closing(sqlite3.connect(self.database)) as db:
            db.executemany("INSERT INTO facts VALUES(?,?,?,?,?,?)", [
                ("The Rotor", "Part Of", "A Motor", 0.8, "android:user", 1),
                ("motor", "part_of", "machine", 0.8, "android:user", 2)])
            db.commit()
        self.assertTrue(any(f["object"] == "machine" for f in self.call("query", "rotor")["facts"]))
        with mock.patch.object(bridge, "MAX_INFERENCE_FACTS", 1):
            stored = self.call("query", "ROTOR")
            self.assertEqual(stored["facts"][0]["subject"], "rotor")
            self.assertIn("Inference skipped", stored["warning"])
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute("SELECT subject FROM facts WHERE created=1").fetchone()[0], "The Rotor")

    def test_repeated_user_fact_updates_its_source(self):
        self.observe(confidence=0.5)
        result = self.observe(confidence=0.9)
        self.assertEqual(result["observations"], 1)
        facts = self.call("query", "rotor")["facts"]
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["confidence"], 0.9)
        self.assertEqual(facts[0]["source"], "android:user")

    def test_interpret_requires_explicit_save_and_rejects_uncertainty(self):
        candidate = self.call("interpret", "rotor is part of motor")
        self.assertEqual(candidate["intent"], "candidate_fact")
        self.assertEqual(candidate["candidate_facts"][0]["relation"], "part_of")
        self.assertFalse(candidate["saved"])
        self.assertEqual(self.call("status")["observations"], 0)
        uncertain = self.call("interpret", "rotor might be part of motor")
        self.assertEqual(uncertain["intent"], "needs_review")
        self.assertEqual(uncertain["candidate_facts"], [])

    def test_rejected_observations_do_not_change_facts(self):
        self.observe()
        invalid = [
            "not JSON", "[]", "{}",
            dict(subject="", relation="part_of", object="motor"),
            dict(subject=12, relation="part_of", object="motor"),
            dict(subject="x" * 201, relation="part_of", object="motor"),
            dict(subject="new\nsubject", relation="part_of", object="motor"),
            dict(subject="new", relation="part_of", object="motor", confidence=True),
            dict(subject="new", relation="part_of", object="motor", confidence=float("nan")),
            dict(subject="new", relation="part_of", object="motor", confidence=2),
        ]
        for payload in invalid:
            with self.subTest(payload=payload):
                self.assertFalse(self.call("observe", payload)["ok"])
                self.assertEqual(self.call("status")["observations"], 1)
        self.assertFalse(self.call("interpret", "x" * 4097)["ok"])
        self.assertFalse(self.call("interpret", "x" * 2001)["ok"])
        self.assertFalse(self.call("download_internet", "") ["ok"])

    def test_independent_databases_are_not_bound_to_first_global_engine(self):
        self.seed()
        other = Path(self.storage.name) / "other.sqlite3"
        self.assertEqual(self.call("status", path=other)["observations"], 0)
        response = self.call("observe", dict(subject="wheel", relation="part_of", object="car"), path=other)
        self.assertTrue(response["ok"], response)
        self.assertEqual(self.call("status")["observations"], 2)
        self.assertEqual(self.call("query", "rotor", path=other)["facts"], [])
        self.assertEqual(self.call("query", "wheel")["facts"], [])

    def test_commands_from_different_threads_have_no_sqlite_affinity_error(self):
        def save(index):
            return self.call("observe", dict(subject=f"component {index}", relation="part_of", object="machine"))
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(save, range(8)))
        self.assertTrue(all(r["ok"] for r in responses), responses)
        self.assertEqual(self.call("status")["observations"], 8)

    def test_legacy_migration_keeps_original_rows_duplicates_and_provenance(self):
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("CREATE TABLE observations(subject TEXT,predicate TEXT,object TEXT,created_at TEXT)")
            db.executemany("INSERT INTO observations VALUES(?,?,?,?)", [("rotor", "part_of", "motor", "2026-10-01 12:00:00")] * 2)
            db.commit()
        for _ in range(2):
            result = self.call("status")
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["observations"], 2)
            self.assertEqual(result["migration"]["legacy_rows_migrated"], 2)
        facts = self.call("query", "rotor")["facts"]
        self.assertEqual({f["source"] for f in facts}, {"android:legacy:observations:1", "android:legacy:observations:2"})
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM android_migrations").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(DISTINCT created) FROM facts").fetchone()[0], 1)
        self.observe(confidence=1.0)
        self.assertEqual(self.call("status")["observations"], 3)

    def test_invalid_legacy_row_rolls_back_entire_migration(self):
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("CREATE TABLE observations(subject TEXT,predicate TEXT,object TEXT,created_at TEXT)")
            db.executemany("INSERT INTO observations VALUES(?,?,?,?)", [("rotor", "part_of", "motor", None), ("", "part_of", "motor", None)])
            db.commit()
        self.assertFalse(self.call("status")["ok"])
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM facts").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 2)

    def test_neural_training_rejects_insufficient_data(self):
        self.observe()
        result = self.call("neural_train")
        self.assertFalse(result["ok"])
        self.assertIn("distinct objects", result["error"])
        self.assertFalse(Path(str(self.database) + ".neural.json").exists())

    def test_facts_and_neural_model_survive_fresh_python_process(self):
        self.seed()
        trained = self.call("neural_train")
        self.assertTrue(trained["ok"], trained)
        self.assertTrue(trained["persisted"])
        steps = trained["training"]["steps"]
        self.assertGreater(steps, 0)
        script = "import sys; sys.path.insert(0,sys.argv[1]); from android_bridge import execute; print(execute(sys.argv[2],sys.argv[3],sys.argv[4]))"
        def subprocess_call(command, payload=""):
            run = subprocess.run([sys.executable, "-c", script, str(PYTHON_SOURCE), str(self.database), command, payload], capture_output=True, text=True, check=True, timeout=30)
            return json.loads(run.stdout)
        reopened = subprocess_call("status")
        self.assertEqual(reopened["observations"], 2)
        self.assertEqual(reopened["neural_training_steps"], steps)
        self.assertEqual(len(subprocess_call("query", "rotor")["facts"]), 2)
        continued = subprocess_call("neural_train")
        self.assertEqual(continued["training"]["steps"], steps * 2)
        self.assertEqual(self.call("status")["neural_training_steps"], steps * 2)
        other = Path(self.storage.name) / "other.sqlite3"
        self.assertEqual(self.call("status", path=other)["neural_training_steps"], 0)

    def test_failed_neural_save_leaves_previous_model_intact(self):
        self.seed()
        self.assertTrue(self.call("neural_train")["ok"])
        model_path = Path(str(self.database) + ".neural.json")
        before = model_path.read_bytes()
        with mock.patch.object(bridge.os, "replace", side_effect=OSError("simulated storage failure")):
            result = self.call("neural_train")
        self.assertFalse(result["ok"])
        self.assertEqual(model_path.read_bytes(), before)
        self.assertEqual(list(model_path.parent.glob("*.tmp")), [])

    def test_corrupt_saved_model_is_reported_not_silently_reset(self):
        self.seed()
        Path(str(self.database) + ".neural.json").write_text('{"dimensions": 12, "vectors": {}, "steps": -1}')
        result = self.call("status")
        self.assertFalse(result["ok"])
        self.assertIn("training count", result["error"])

    def test_import_failure_is_visible_in_status(self):
        original = bridge.importlib.import_module
        def importing(name):
            if name == "solrdm.independent_eval":
                raise ImportError("test missing module")
            return original(name)
        with mock.patch.object(bridge.importlib, "import_module", side_effect=importing):
            result = self.call("status")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "ImportError")
        self.assertIn("test missing module", result["error"])

    def test_capacity_guards_do_not_discard_existing_data(self):
        self.seed()
        with mock.patch.object(bridge, "MAX_OBSERVATIONS", 2), mock.patch.object(bridge, "MAX_INFERENCE_FACTS", 1), mock.patch.object(bridge, "MAX_TRAINING_FACTS", 1):
            rejected = self.call("observe", dict(subject="wheel", relation="part_of", object="car"))
            self.assertFalse(rejected["ok"])
            self.assertTrue(self.observe(confidence=0.9)["ok"])
            query = self.call("query")
            self.assertTrue(query["ok"])
            self.assertEqual(len(query["facts"]), 2)
            self.assertIn("Inference skipped", query["warning"])
            self.assertFalse(self.call("discover")["ok"])
            self.assertFalse(self.call("neural_train")["ok"])
        self.assertEqual(self.call("status")["observations"], 2)


if __name__ == "__main__":
    unittest.main()
