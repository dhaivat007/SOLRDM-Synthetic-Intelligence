"""Regressions reproduced during the user-requested engine error review."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app/src/main/python'))
from solrdm import EnglishUnderstanding, EvidenceCorroborator, Example, Fact, RuleLearner, SOLRDM
from solrdm.research import ResearchMemory


class ReviewRegressionTest(unittest.TestCase):
    def engine(self):
        engine = SOLRDM()
        self.addCleanup(engine.close)
        return engine

    def test_english_articles_and_spacing_produce_matching_entities(self):
        parser = EnglishUnderstanding()
        first = parser.parse('  A  rotor  is  a  part of  a motor.  ')
        second = parser.parse('The motor is part of the machine')
        self.assertEqual(first.intent, 'candidate_fact')
        self.assertEqual(first.facts[0].subject, 'rotor')
        self.assertEqual(first.facts[0].object, second.facts[0].subject)
        self.assertEqual(second.facts[0].object, 'machine')
        self.assertEqual(parser.parse('An armature causes the motion').facts[0].subject, 'armature')
        self.assertEqual(parser.parse('The motor contains a front wheel').facts[0].object, 'front wheel')

    def test_english_conditional_and_compound_clauses_require_review(self):
        parser = EnglishUnderstanding()
        for text in (
            'If rotor is part of motor',
            'Rotor is part of motor unless a cover contains it',
            'Assuming rotor is part of motor',
            'Rotor is part of motor and wheel is part of car',
            'Rotor is part of motor or generator',
            'Rotor is part of motor wheel is part of car',
        ):
            with self.subTest(text=text):
                result = parser.parse(text)
                self.assertEqual(result.intent, 'needs_review')
                self.assertEqual(result.facts, ())
        self.assertEqual(parser.parse('Is a rotor part of a motor?').intent, 'question')

    def test_research_review_rejects_truthy_non_boolean_approval(self):
        memory = ResearchMemory()
        self.addCleanup(memory.close)
        article = {'title': 'Rotor', 'source_url': 'https://example.org/rotor',
                   'source_type': 'test', 'text': 'Rotor is part of motor.'}
        record = memory.add('rotor', article)
        for approval in ('false', 'true', 0, 1, None, []):
            with self.subTest(approval=approval), self.assertRaises(ValueError):
                memory.review(record, approval)
            self.assertEqual(memory.get(record)[5], 'pending_review')
        self.assertTrue(memory.review(record, False))
        self.assertEqual(memory.get(record)[5], 'rejected')
        approved = memory.add('rotor', article)
        self.assertTrue(memory.review(approved, True))
        self.assertEqual(memory.get(approved)[5], 'reviewed')

    def test_rule_learning_rejects_non_boolean_auto_approval_without_mutation(self):
        engine = self.engine()
        learner = RuleLearner(engine, min_train=1, min_holdout=1)
        for index in range(30):
            learner.add_example(Example('part_of', 'part_of', 'part_of', True, f'g{index}'))
        for approval in ('false', 'true', 0, 1, None):
            with self.subTest(approval=approval), self.assertRaises(ValueError):
                learner.learn(auto_approve=approval)
            self.assertEqual(engine.rules, [])
            self.assertEqual(engine.db.execute('SELECT COUNT(*) FROM learned_rules').fetchone()[0], 0)
        self.assertEqual(learner.learn(auto_approve=False)[0]['status'], 'candidate')
        self.assertEqual(engine.rules, [])
        self.assertEqual(learner.learn(auto_approve=True)[0]['status'], 'approved')
        self.assertEqual(len(engine.rules), 1)

    def test_corroboration_requires_boolean_review_and_support_flags(self):
        corroborator = EvidenceCorroborator()
        base = {'claim': 'rotor part_of motor', 'supports': True, 'reviewed': True}
        for field in ('reviewed', 'supports'):
            for value in ('false', 'true', 0, 1, None):
                observations = [dict(base, url='https://a.example/x'),
                                dict(base, url='https://b.example/x')]
                observations[0][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    corroborator.assess(observations)
        self.assertFalse(corroborator.assess([
            dict(base, url='https://a.example/x', reviewed=False),
            dict(base, url='https://b.example/x', reviewed=False)])['corroborated'])
        result = corroborator.assess([
            dict(base, url='https://a.example/x'),
            dict(base, url='https://b.example/x', supports=False)])
        self.assertTrue(result['contradiction'])
        self.assertFalse(result['corroborated'])

    def test_validation_rejects_same_source_and_explicitly_unverified_evidence(self):
        engine = self.engine()
        hypothesis = Fact('rotor', 'part_of', 'motor', 0.9, 'lab:a')
        self.assertFalse(engine.validate(hypothesis, hypothesis)['verified'])
        same_source = Fact('rotor', 'part_of', 'motor', 1.0, ' LAB:A ')
        self.assertFalse(engine.validate(hypothesis, same_source)['verified'])
        for source in ('inference', 'inference:derived', 'hypothesis',
                       'user:unverified', 'lab:UNVERIFIED', 'android:user', '', None):
            with self.subTest(source=source):
                evidence = Fact('rotor', 'part_of', 'motor', 1.0, source)
                result = engine.validate(hypothesis, evidence)
                self.assertFalse(result['verified'])
                self.assertFalse(result['independent_source'])
        independent = Fact('rotor', 'part_of', 'motor', 0.9, 'lab:b')
        self.assertTrue(engine.validate(hypothesis, independent)['verified'])
        wrong_triple = Fact('rotor', 'part_of', 'car', 1.0, 'lab:b')
        self.assertFalse(engine.validate(hypothesis, wrong_triple)['verified'])


if __name__ == '__main__':
    unittest.main()
