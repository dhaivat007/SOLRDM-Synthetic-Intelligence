"""Bounded self-learning loop: ingest labeled feedback, propose, evaluate, audit.
No uncontrolled self-training; holdout and human approval remain required.
"""
from .learning import RuleLearner, Example

class SelfLearningController:
    def __init__(self, ai, **kwargs):
        self.learner=RuleLearner(ai, **kwargs)

    def feedback(self, left, right, outcome, correct, case_id):
        self.learner.add_example(Example(left,right,outcome,correct,case_id))

    def cycle(self):
        reports=self.learner.learn(auto_approve=False)
        return {'evaluated':len(reports),'eligible':sum(r['eligible'] for r in reports),
                'pending_approval':[r['rule'].__dict__ for r in reports if r['status']=='candidate'],
                'rejected':sum(r['status']=='rejected' for r in reports)}
