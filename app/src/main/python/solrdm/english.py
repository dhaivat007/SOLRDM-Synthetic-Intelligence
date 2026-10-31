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
    def parse(self, text: str, source: str = 'user:unverified') -> Interpretation:
        if not isinstance(text,str) or len(text)>2000: raise ValueError('Text must be <=2000 characters')
        raw=text.strip()
        if not raw: return Interpretation(text,'unknown',(),0.0)
        if re.search(r'\b(not|never|no|might|may|possibly|could)\b',raw,re.I):
            return Interpretation(text,'needs_review',(),0.0,'Negation or uncertainty is not supported.')
        intent='question' if raw.endswith('?') else 'statement'
        if intent=='question': return Interpretation(text,intent,(),0.0)
        for pattern,relation in self._patterns:
            match=re.fullmatch(pattern,raw.rstrip('.! '),re.I)
            if match:
                s=match.group('s').strip().lower(); o=match.group('o').strip().lower()
                if s and o:
                    return Interpretation(text,'candidate_fact',(Fact(s,relation,o,0.5,source),),0.65)
        return Interpretation(text,'unknown',(),0.0)
