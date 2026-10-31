"""Transparent, limited English-to-triple parser; not general language understanding."""
import re
from dataclasses import dataclass
from .core import Fact

@dataclass(frozen=True)
class Interpretation:
    text: str
    intent: str
    facts: tuple[Fact, ...]
    confidence: float
    limitations: str = 'Pattern-based English only; ambiguous language requires review.'

class EnglishUnderstanding:
    _patterns = [
        (r'(?P<s>[\w -]+?)\s+is\s+(?:an?\s+)?part of\s+(?P<o>[\w -]+)', 'part_of'),
        (r'(?P<s>[\w -]+?)\s+is\s+(?:an?\s+)?type of\s+(?P<o>[\w -]+)', 'type_of'),
        (r'(?P<s>[\w -]+?)\s+causes\s+(?P<o>[\w -]+)', 'causes'),
        (r'(?P<s>[\w -]+?)\s+contains\s+(?P<o>[\w -]+)', 'contains'),
    ]
    @staticmethod
    def _entity(value):
        # The supported grammar treats simple leading determiners as articles,
        # not part of the entity identifier used for matching relation chains.
        value = ' '.join(value.lower().split())
        return re.sub(r'^(?:a|an|the)(?:\s+|$)', '', value)

    def parse(self, text: str, source: str = 'user:unverified') -> Interpretation:
        if not isinstance(text,str) or len(text)>2000: raise ValueError('Text must be <=2000 characters')
        raw=' '.join(text.split())
        if not raw: return Interpretation(text,'unknown',(),0.0)
        if re.search(r'\b(not|never|no|might|may|possibly|could)\b',raw,re.I):
            return Interpretation(text,'needs_review',(),0.0,'Negation or uncertainty is not supported.')
        intent='question' if raw.endswith('?') else 'statement'
        if intent=='question': return Interpretation(text,intent,(),0.0)
        if re.search(r'\b(if|unless|assuming|provided|when|whenever|and|or|but)\b', raw, re.I):
            return Interpretation(text,'needs_review',(),0.0,'Conditional or compound statements require review.')
        predicates = re.findall(r'\b(?:is\s+(?:an?\s+)?(?:part|type)\s+of|causes|contains)\b', raw, re.I)
        if len(predicates) > 1:
            return Interpretation(text,'needs_review',(),0.0,'Multiple relation clauses require review.')
        for pattern,relation in self._patterns:
            match=re.fullmatch(pattern,raw.rstrip('.! '),re.I)
            if match:
                s=self._entity(match.group('s')); o=self._entity(match.group('o'))
                if s and o:
                    return Interpretation(text,'candidate_fact',(Fact(s,relation,o,0.5,source),),0.65)
        return Interpretation(text,'unknown',(),0.0)
