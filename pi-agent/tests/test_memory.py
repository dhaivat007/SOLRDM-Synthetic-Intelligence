import concurrent.futures
import tempfile
import unittest
from pathlib import Path

from solrdm_pi.memory import MemoryStore


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.memory = MemoryStore(self.temp.name)

    def test_saved_memory_is_unreviewed_and_survives_restart(self):
        record = self.memory.add("Water sample warmed", "experiment log", "user")
        self.assertEqual(record["status"], "unreviewed")
        self.assertIsNone(record["reviewed_at"])
        restored = MemoryStore(self.temp.name)
        self.assertEqual(restored.search("water")[0], record)
        self.assertEqual(Path(restored.path).stat().st_mode & 0o777, 0o600)

    def test_review_requires_actual_bool_and_keeps_provenance(self):
        record = self.memory.add("A model hypothesis", "conversation", "model")
        for value in (1, 0, "false", "true", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.memory.review(record["id"], value)
        reviewed = self.memory.review(record["id"], True)
        self.assertEqual(reviewed["status"], "approved")
        self.assertEqual(reviewed["origin"], "model")
        self.assertEqual(reviewed["source"], "conversation")
        self.assertIsNotNone(reviewed["reviewed_at"])
        self.assertEqual(self.memory.review(record["id"], False)["status"], "rejected")

    def test_search_is_literal_not_sql_or_wildcard(self):
        first = self.memory.add("100% cotton", "test")
        self.memory.add("1000 cotton", "test")
        self.assertEqual([r["id"] for r in self.memory.search("100%")], [first["id"]])
        self.assertEqual(self.memory.search("' OR 1=1 --"), [])
        self.assertEqual(self.memory.search("_"), [])

    def test_relevant_recalls_approved_fact_from_different_question_wording(self):
        record = self.memory.add("My dog is named Max", "User conversation", "user")
        reviewed = self.memory.review(record["id"], True)
        self.assertEqual(self.memory.search("What is my dog named?"), [])
        self.assertEqual(self.memory.relevant("What is my dog named?"), [reviewed])
        # Preserve the original provenance and review status, not a generated
        # assertion that the memory has been independently verified.
        found = self.memory.relevant("Can you tell me about my dog?")[0]
        self.assertEqual(found["source"], "User conversation")
        self.assertEqual(found["origin"], "user")
        self.assertEqual(found["status"], "approved")

    def test_relevant_excludes_unreviewed_and_rejected_records(self):
        approved = self.memory.add("Dog named Max")
        self.memory.review(approved["id"], True)
        self.memory.add("Dog named Rex", origin="model")
        rejected = self.memory.add("Dog named Spot", origin="model")
        self.memory.review(rejected["id"], False)
        self.assertEqual([r["id"] for r in self.memory.relevant("What is my dog named?")], [approved["id"]])
        self.memory.review(approved["id"], False)
        self.assertEqual(self.memory.relevant("dog"), [])

    def test_relevant_ranks_distinct_overlap_and_does_not_match_substrings(self):
        first = self.memory.add("The solar battery needs maintenance")
        second = self.memory.add("Solar panels collect sunlight")
        third = self.memory.add("Battery compartment location")
        dogma = self.memory.add("Dogma is a belief")
        for row in (first, second, third, dogma):
            self.memory.review(row["id"], True)
        found = self.memory.relevant("What about the solar battery?", limit=2)
        self.assertEqual(found[0]["id"], first["id"])
        self.assertEqual(len(found), 2)
        self.assertEqual(self.memory.relevant("dog"), [])
        # Repeating one query term does not increase its rank.
        self.assertEqual(self.memory.relevant("solar solar solar battery")[0]["id"], first["id"])

    def test_relevant_normalizes_unicode_case_and_accents(self):
        first = self.memory.add("My favourite café is nearby")
        second = self.memory.add("Die Straße ist lang")
        self.memory.review(first["id"], True)
        self.memory.review(second["id"], True)
        self.assertEqual(self.memory.relevant("Which CAFE\u0301 is nearby?")[0]["id"], first["id"])
        self.assertEqual(self.memory.relevant("STRASSE")[0]["id"], second["id"])

    def test_relevant_empty_queries_limits_and_token_cap(self):
        record = self.memory.add("Needle useful note")
        self.memory.review(record["id"], True)
        for query in ("", "   ", "What can you tell me about it?", "an of to", "x" * 65):
            with self.subTest(query=query):
                self.assertEqual(self.memory.relevant(query), [])
        with self.assertRaises(ValueError):
            self.memory.relevant("x" * 2001)
        with self.assertRaises(ValueError):
            self.memory.relevant(None)
        with self.assertRaises(ValueError):
            self.memory.relevant("needle", limit=True)
        terms = [f"term{i}" for i in range(32)]
        self.assertEqual(self.memory.relevant(" ".join(terms + ["needle"])), [])
        self.assertEqual(self.memory.relevant("needle " + " ".join(terms))[0]["id"], record["id"])

    def test_bounded_memory_and_deletion(self):
        self.memory.MAX_RECORDS = 2
        first = self.memory.add("first")
        self.memory.add("second")
        with self.assertRaisesRegex(ValueError, "full"):
            self.memory.add("third")
        self.memory.delete(first["id"])
        self.memory.add("third")
        self.assertEqual(len(self.memory.list()), 2)
        with self.assertRaisesRegex(ValueError, "not found"):
            self.memory.delete(99999)

    def test_concurrent_writes_do_not_exceed_limit(self):
        self.memory.MAX_RECORDS = 4
        def add(i):
            try:
                self.memory.add(f"observation {i}")
                return True
            except ValueError:
                return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(add, range(12)))
        self.assertEqual(sum(results), 4)
        self.assertEqual(len(self.memory.list()), 4)

    def test_invalid_inputs_and_missing_records(self):
        for value in (True, 0, -1, 101, 1.5, "5"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.memory.list(value)
        for value in (True, 0, -1, "1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.memory.delete(value)
        for text in ("", " ", "x" * 4001, "nul\0text", None):
            with self.subTest(text=repr(text)[:30]), self.assertRaises(ValueError):
                self.memory.add(text)
        with self.assertRaises(ValueError):
            self.memory.add("ok", origin="verified")
        with self.assertRaises(ValueError):
            self.memory.review(9999, True)


if __name__ == "__main__":
    unittest.main()
