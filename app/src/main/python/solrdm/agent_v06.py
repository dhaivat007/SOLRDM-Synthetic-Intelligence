"""Bounded cross-domain task planner; explicitly abstains on unsupported tasks."""
import re
from .language_learning import EnglishIntentLearner
from .discovery_v05 import HypothesisLab

class NativeAgent:
 def __init__(self, language_model, min_score=0.55):
  self.language_model=language_model; self.min_score=min_score
 def plan(self, text):
  prediction=self.language_model.predict(text)
  if prediction['score'] < self.min_score:
   return {'status':'abstain','reason':'uncertain intent','prediction':prediction}
  label=prediction['label']
  actions={'math':'request numerical expression and use verified calculator',
           'research':'request approved research source and human review',
           'science':'request measurement dataset and evaluate candidate hypotheses',
           'memory':'request explicit fact and source for reviewed memory'}
  return {'status':'proposed','intent':label,'confidence':prediction['score'], 'next_action':actions.get(label,'ask for clarification')}
 def discover(self,rows,x,y):
  if len(rows)<8: return {'status':'abstain','reason':'at least 8 measurements required'}
  return {'status':'hypothesis','candidates':HypothesisLab().discover(rows,x,y)[:3], 'caution':'correlation is not causation; validate experimentally'}
