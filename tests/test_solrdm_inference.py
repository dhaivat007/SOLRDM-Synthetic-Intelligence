"""Regression coverage for confidence selection in bounded forward chaining."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app/src/main/python"))
from solrdm.core import Fact, Rule, SOLRDM


class InferenceConfidenceTest(unittest.TestCase):
    def make_engine(self, facts):
        engine = SOLRDM()
        self.addCleanup(engine.close)
        engine.add_rule(Rule("part_of", "part_of", "part_of"))
        for fact in facts:
            engine.observe(fact)
        return engine

    def inference(self, engine, max_rounds=1):
        return {
            (fact.subject, fact.relation, fact.object): fact.confidence
            for fact in engine.infer(max_rounds=max_rounds)
        }

    def test_multiple_sources_use_highest_confidence_in_either_insert_order(self):
        high = Fact("rotor", "part_of", "motor", 0.9, "reviewed:high")
        low = Fact("rotor", "part_of", "motor", 0.2, "reviewed:low")
        next_link = Fact("motor", "part_of", "vehicle", 0.8, "reviewed:chain")
        for evidence in ((high, low), (low, high)):
            with self.subTest(first_source=evidence[0].source):
                engine = self.make_engine([*evidence, next_link])
                self.assertEqual(
                    self.inference(engine),
                    {("rotor", "part_of", "vehicle"): 0.72},
                )
                self.assertEqual(len(engine.facts()), 3)

    def test_competing_paths_keep_best_confidence_with_one_round_budget(self):
        high_path = [
            Fact("a", "part_of", "b", 0.9),
            Fact("b", "part_of", "d", 0.9),
        ]
        low_path = [
            Fact("a", "part_of", "c", 0.6),
            Fact("c", "part_of", "d", 0.6),
        ]
        for facts in (high_path + low_path, low_path + high_path):
            with self.subTest(first_middle=facts[0].object):
                engine = self.make_engine(facts)
                self.assertEqual(
                    self.inference(engine),
                    {("a", "part_of", "d"): 0.81},
                )

    def test_existing_stronger_observation_is_not_downgraded(self):
        engine = self.make_engine([
            Fact("a", "part_of", "b", 0.8),
            Fact("b", "part_of", "c", 0.8),
            Fact("a", "part_of", "c", 0.95, "reviewed:direct"),
        ])
        self.assertEqual(self.inference(engine), {})
        direct = [f for f in engine.facts() if f.subject == "a" and f.object == "c"]
        self.assertEqual(direct[0].confidence, 0.95)

    def test_stronger_inference_remains_separate_from_persisted_observation(self):
        engine = self.make_engine([
            Fact("a", "part_of", "b", 0.9),
            Fact("b", "part_of", "c", 0.9),
            Fact("a", "part_of", "c", 0.3, "reviewed:direct"),
        ])
        self.assertEqual(self.inference(engine), {("a", "part_of", "c"): 0.81})
        direct = [f for f in engine.facts() if f.subject == "a" and f.object == "c"]
        self.assertEqual([(f.confidence, f.source) for f in direct], [(0.3, "reviewed:direct")])


if __name__ == "__main__":
    unittest.main()
