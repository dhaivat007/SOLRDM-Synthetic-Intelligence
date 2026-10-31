"""SOLRDM v0.2: bounded, supervised, auditable autonomous rule induction.

Learns relational compositions A(x,y) & B(y,z) => C(x,z) from labeled examples.
Only labeled positives/negatives are evidence; unknown is NOT negative.
"""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
import json, sqlite3, time
from .core import Rule, SOLRDM

@dataclass(frozen=True)
class Example:
    left: str
    right: str
    outcome: str
    label: bool
    group: str
    # group denotes a distinct experiment/case; all observations from a case stay in one split
    def __post_init__(self):
        if not all(isinstance(x,str) and x.strip() for x in (self.left,self.right,self.outcome,self.group)):
            raise ValueError('Relations and group must be nonempty strings')
        if not isinstance(self.label,bool): raise ValueError('label must be boolean')

class RuleLearner:
    def __init__(self, ai: SOLRDM, *, min_train=4, min_holdout=2, min_precision=0.85,
                 max_candidates=500, max_examples=10000):
        self.ai=ai
        self.min_train=min_train; self.min_holdout=min_holdout
        self.min_precision=min_precision; self.max_candidates=max_candidates
        self.max_examples=max_examples
        if min_train<1 or min_holdout<1 or not 0<min_precision<=1 or max_candidates<1 or max_examples<1:
            raise ValueError('Invalid learner limits')
        self.db=ai.db
        self.db.execute('''CREATE TABLE IF NOT EXISTS learning_examples (
            left_rel TEXT, right_rel TEXT, outcome TEXT, label INTEGER, group_id TEXT,
            PRIMARY KEY(left_rel,right_rel,outcome,group_id))''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS learned_rules (
            first_rel TEXT, second_rel TEXT, result_rel TEXT, status TEXT,
            train_positive INTEGER, train_total INTEGER, test_positive INTEGER, test_total INTEGER,
            created REAL, PRIMARY KEY(first_rel,second_rel,result_rel))''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS learning_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT, payload TEXT, created REAL)''')
        self.db.commit()
        self.load_approved()

    def _audit(self,event,payload):
        self.db.execute('INSERT INTO learning_audit(event,payload,created) VALUES (?,?,?)',
                        (event,json.dumps(payload,sort_keys=True),time.time()))

    def add_example(self, ex: Example):
        count=self.db.execute('SELECT COUNT(*) FROM learning_examples').fetchone()[0]
        old=self.db.execute('SELECT label FROM learning_examples WHERE left_rel=? AND right_rel=? AND outcome=? AND group_id=?',
                            (ex.left,ex.right,ex.outcome,ex.group)).fetchone()
        if old is not None and old[0]!=int(ex.label): raise ValueError('Conflicting labels for same case')
        if old is None and count>=self.max_examples: raise RuntimeError('Example limit exceeded')
        self.db.execute('INSERT OR IGNORE INTO learning_examples VALUES(?,?,?,?,?)',
                        (ex.left,ex.right,ex.outcome,int(ex.label),ex.group))
        self._audit('example_added',{'group':ex.group,'label':ex.label})
        self.db.commit()

    @staticmethod
    def _holdout(group):
        # Stable across processes and Python hash seeds. Approximately 25% of groups.
        return int.from_bytes(sha256(group.encode()).digest()[:4],'big') % 4 == 0

    def evaluate(self):
        rows=self.db.execute('SELECT left_rel,right_rel,outcome,label,group_id FROM learning_examples ORDER BY left_rel,right_rel,outcome,group_id').fetchall()
        candidates=sorted(set((a,b,c) for a,b,c,_,_ in rows))
        if len(candidates)>self.max_candidates: raise RuntimeError('Candidate limit exceeded')
        reports=[]
        for a,b,c in candidates:
            relevant=[r for r in rows if r[:3]==(a,b,c)]
            train=[r for r in relevant if not self._holdout(r[4])]
            test=[r for r in relevant if self._holdout(r[4])]
            tp=sum(r[3] for r in train); hp=sum(r[3] for r in test)
            train_precision=tp/len(train) if train else 0
            test_precision=hp/len(test) if test else 0
            eligible=(len(train)>=self.min_train and len(test)>=self.min_holdout
                      and tp>0 and hp>0 and train_precision>=self.min_precision
                      and test_precision>=self.min_precision)
            reports.append({'rule':Rule(a,b,c),'train_positive':tp,'train_total':len(train),
                            'holdout_positive':hp,'holdout_total':len(test),
                            'train_precision':train_precision,'holdout_precision':test_precision,
                            'eligible':eligible})
        return reports

    def learn(self, *, auto_approve=False):
        """Discover rules automatically. Approval defaults to human review.
        auto_approve only for explicitly authorized controlled environments.
        """
        if type(auto_approve) is not bool:
            raise ValueError('auto_approve must be boolean')
        reports=self.evaluate()
        for r in reports:
            rule=r['rule']; status='approved' if r['eligible'] and auto_approve else ('candidate' if r['eligible'] else 'rejected')
            existing=self.db.execute('SELECT status FROM learned_rules WHERE first_rel=? AND second_rel=? AND result_rel=?',
                                     (rule.first,rule.second,rule.result)).fetchone()
            # Previously approved rules are never silently revoked by a new training run.
            if existing and existing[0]=='approved' and status!='approved': status='approved'
            self.db.execute('''INSERT INTO learned_rules VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(first_rel,second_rel,result_rel) DO UPDATE SET
                status=excluded.status,train_positive=excluded.train_positive,
                train_total=excluded.train_total,test_positive=excluded.test_positive,
                test_total=excluded.test_total''',
                (rule.first,rule.second,rule.result,status,r['train_positive'],r['train_total'],
                 r['holdout_positive'],r['holdout_total'],time.time()))
            self._audit('rule_evaluated',{'rule':rule.__dict__,'status':status,'train_precision':r['train_precision'],
                                         'holdout_precision':r['holdout_precision']})
            r['status']=status
            if status=='approved': self.ai.add_rule(rule)
        self.db.commit()
        return reports

    def approve(self,rule: Rule):
        row=self.db.execute('SELECT status FROM learned_rules WHERE first_rel=? AND second_rel=? AND result_rel=?',
                            (rule.first,rule.second,rule.result)).fetchone()
        if row is None or row[0]=='rejected': raise ValueError('Rule not eligible for approval')
        self.db.execute('UPDATE learned_rules SET status=? WHERE first_rel=? AND second_rel=? AND result_rel=?',
                        ('approved',rule.first,rule.second,rule.result))
        self.ai.add_rule(rule); self._audit('rule_approved',rule.__dict__); self.db.commit()

    def revoke(self,rule: Rule):
        self.db.execute('UPDATE learned_rules SET status=? WHERE first_rel=? AND second_rel=? AND result_rel=?',
                        ('revoked',rule.first,rule.second,rule.result))
        self.ai.rules=[r for r in self.ai.rules if r!=rule]
        self._audit('rule_revoked',rule.__dict__); self.db.commit()

    def load_approved(self):
        for a,b,c in self.db.execute("SELECT first_rel,second_rel,result_rel FROM learned_rules WHERE status='approved'"):
            self.ai.add_rule(Rule(a,b,c))
