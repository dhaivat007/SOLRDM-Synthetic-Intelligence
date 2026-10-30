"""Contract tests for the bundled observation subset, not full v0.7 parity."""

import contextlib
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


PYTHON_SOURCE = Path(__file__).resolve().parents[1] / "app/src/main/python"
sys.path.insert(0, str(PYTHON_SOURCE))
from android_bridge import observe


class ObservationBridgeTest(unittest.TestCase):
    def setUp(self):
        self.storage = tempfile.TemporaryDirectory()
        self.addCleanup(self.storage.cleanup)
        self.directory = Path(self.storage.name)
        self.database = self.directory / "solrdm.sqlite3"

    def rows(self):
        with contextlib.closing(sqlite3.connect(self.database)) as database:
            return database.execute(
                "SELECT subject, predicate, object, created_at "
                "FROM observations ORDER BY rowid"
            ).fetchall()

    def test_valid_observation_is_normalized_and_committed(self):
        message = observe(self.directory, "  Rotor IS PART OF a Motor.  ")
        self.assertEqual(
            message, "Stored: rotor → part_of → motor. Observations: 1"
        )
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][:3], ("rotor", "part_of", "motor"))
        self.assertTrue(rows[0][3], "The stored observation needs a timestamp")

    def test_articles_and_multiword_entities(self):
        for article in ("", "a ", "an ", "the "):
            with self.subTest(article=article):
                observe(self.directory, "front-wheel is part of " + article + "motor car")
        self.assertEqual(
            [row[:3] for row in self.rows()],
            [("front-wheel", "part_of", "motor car")] * 4,
        )

    def test_repeated_observations_are_appended_not_deduplicated(self):
        observe(self.directory, "rotor is part of motor")
        message = observe(self.directory, "rotor is part of motor")
        self.assertEqual(len(self.rows()), 2)
        self.assertTrue(message.endswith("Observations: 2"))

    def test_unsupported_input_does_not_create_database(self):
        for sentence in (
            "", "   ", "What is a rotor?", "rotor causes motion",
            "rotor is part of motor; DROP TABLE observations;",
            "rotor is part of motor\nextra statement",
        ):
            with self.subTest(sentence=sentence):
                self.assertEqual(
                    observe(self.directory, sentence),
                    "Unsupported sentence structure; no fact saved.",
                )
                self.assertFalse(self.database.exists())

    def test_rejected_input_does_not_modify_existing_observations(self):
        observe(self.directory, "rotor is part of motor")
        before = self.rows()
        observe(self.directory, "Is the rotor part of a motor?")
        observe(self.directory, "x" * 2001)
        self.assertEqual(self.rows(), before)

    def test_oversized_input_is_rejected_without_writing(self):
        self.assertEqual(observe(self.directory, "x" * 2001), "Observation too long")
        self.assertFalse(self.database.exists())

    def test_separate_storage_directories_do_not_share_observations(self):
        observe(self.directory, "rotor is part of motor")
        with tempfile.TemporaryDirectory() as other_directory:
            message = observe(other_directory, "wheel is part of car")
            self.assertTrue(message.endswith("Observations: 1"))
            with contextlib.closing(sqlite3.connect(
                Path(other_directory) / "solrdm.sqlite3"
            )) as database:
                self.assertEqual(
                    database.execute("SELECT subject FROM observations").fetchall(),
                    [("wheel",)],
                )
        self.assertEqual([row[0] for row in self.rows()], ["rotor"])

    def test_persistence_across_independent_python_processes(self):
        script = (
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "from android_bridge import observe; "
            "print(observe(sys.argv[2], sys.argv[3]))"
        )
        for count, sentence in enumerate(
            ("rotor is part of motor", "wheel is part of car"), start=1
        ):
            process = subprocess.run(
                [sys.executable, "-c", script, str(PYTHON_SOURCE),
                 str(self.directory), sentence],
                check=True, capture_output=True, text=True, timeout=20,
            )
            self.assertTrue(process.stdout.strip().endswith(f"Observations: {count}"))
        self.assertEqual(
            [row[:3] for row in self.rows()],
            [("rotor", "part_of", "motor"), ("wheel", "part_of", "car")],
        )


if __name__ == "__main__":
    unittest.main()
