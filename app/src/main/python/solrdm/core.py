"""SOLRDM v0.1: auditable, model-independent synthetic reasoning prototype."""
from __future__ import annotations
from dataclasses import dataclass
from collections import deque
from pathlib import Path
import json, sqlite3, time

@dataclass(frozen=True)
class Fact:
    subject: str
    relation: str
    object: str
    confidence: float = 1.0
    source: str = 'observation'

    def __post_init__(self):
        if not all((self.subject.strip(), self.relation.strip(), self.object.strip())):
            raise ValueError('Fact fields cannot be empty')
        if not 0 <= self.confidence <= 1:
            raise ValueError('Confidence must be between 0 and 1')

@dataclass(frozen=True)
class Rule:
    first: str
    second: str
    result: str
    # A(x,y) and B(y,z) -> C(x,z)

class SOLRDM:
    def __init__(self, db_path: str = ':memory:'):
        self.db = sqlite3.connect(db_path)
        self.db.execute('''CREATE TABLE IF NOT EXISTS facts (
            subject TEXT NOT NULL, relation TEXT NOT NULL, object TEXT NOT NULL,
            confidence REAL NOT NULL, source TEXT NOT NULL, created REAL NOT NULL,
            PRIMARY KEY(subject,relation,object,source))''')
        self.db.commit()
        self.rules: list[Rule] = []
        self.audit: list[dict] = []

    def observe(self, fact: Fact) -> None:
        """Store an observation; repeated evidence from a source updates that source."""
        self.db.execute('''INSERT INTO facts VALUES(?,?,?,?,?,?)
            ON CONFLICT(subject,relation,object,source) DO UPDATE SET
            confidence=excluded.confidence,created=excluded.created''',
            (fact.subject,fact.relation,fact.object,fact.confidence,fact.source,time.time()))
        self.db.commit()
        self.audit.append({'action':'observe','fact':fact.__dict__})

    def facts(self) -> list[Fact]:
        rows = self.db.execute('SELECT subject,relation,object,confidence,source FROM facts').fetchall()
        return [Fact(*row) for row in rows]

    def add_rule(self, rule: Rule) -> None:
        if rule not in self.rules:
            self.rules.append(rule)

    def infer(self, max_rounds: int = 5, min_confidence: float = 0.25) -> list[Fact]:
        """Forward-chain relation compositions; inferred facts are NOT persisted as observations."""
        if max_rounds < 1: raise ValueError('max_rounds must be positive')
        # Different sources may report the same triple. Select the strongest
        # evidence independently of database insertion order.
        known: dict[tuple[str,str,str],Fact] = {}
        for fact in self.facts():
            key = (fact.subject,fact.relation,fact.object)
            if key not in known or known[key].confidence < fact.confidence:
                known[key] = fact
        inferred: dict[tuple[str,str,str],Fact] = {}
        for _ in range(max_rounds):
            additions = {}
            current = list(known.values())
            for rule in self.rules:
                left = [f for f in current if f.relation == rule.first]
                right = [f for f in current if f.relation == rule.second]
                by_subject = {}
                for f in right: by_subject.setdefault(f.subject,[]).append(f)
                for a in left:
                    for b in by_subject.get(a.object,[]):
                        conf = round(a.confidence*b.confidence,6)
                        key = (a.subject,rule.result,b.object)
                        # Competing paths in this round must not overwrite a
                        # stronger pending inference, especially with a bounded
                        # number of rounds.
                        previous = additions.get(key, known.get(key))
                        if conf >= min_confidence and (previous is None or previous.confidence < conf):
                            additions[key] = Fact(*key,conf,'inference')
            if not additions: break
            known.update(additions)
            inferred.update(additions)
        return sorted(inferred.values(),key=lambda f:(f.subject,f.relation,f.object))

    def query(self, subject: str | None = None, relation: str | None = None,
              include_inferred: bool = True) -> list[Fact]:
        facts = self.facts() + (self.infer() if include_inferred else [])
        return [f for f in facts if (subject is None or f.subject == subject)
                and (relation is None or f.relation == relation)]

    def discover(self, min_confidence: float = 0.25) -> list[dict]:
        """Generate explicit hypotheses from rule-derived connections, not verified discoveries."""
        observed = {(f.subject,f.relation,f.object) for f in self.facts()}
        return [{'hypothesis':f.__dict__, 'status':'unverified',
                 'suggested_test':f'Independently verify {f.subject} {f.relation} {f.object}'}
                for f in self.infer(min_confidence=min_confidence)
                if (f.subject,f.relation,f.object) not in observed]

    def validate(self, hypothesis: Fact, evidence: Fact) -> dict:
        """Confirm only exact matching triple with independent, explicit evidence."""
        same = (hypothesis.subject,hypothesis.relation,hypothesis.object) == (evidence.subject,evidence.relation,evidence.object)
        independent = evidence.source not in ('inference','hypothesis')
        verified = same and independent and evidence.confidence >= 0.8
        result = {'verified':verified,'evidence_source':evidence.source,
                  'note':'Threshold-based evidence check, not proof of truth'}
        self.audit.append({'action':'validate','result':result})
        return result

    def close(self): self.db.close()
