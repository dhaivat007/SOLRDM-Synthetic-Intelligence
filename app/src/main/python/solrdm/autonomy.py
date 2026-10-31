"""Bounded, opt-in research scheduler. Never runs on import or without caller invocation."""
import sqlite3, time
from urllib.parse import urlparse

class ResearchScheduler:
    def __init__(self, controller, db_path=':memory:', *, approved_topics=(), interval_seconds=86400, max_pages=2):
        if interval_seconds < 60 or not 1 <= max_pages <= 5: raise ValueError('Invalid limits')
        self.controller=controller; self.topics=set(approved_topics); self.interval=interval_seconds; self.max_pages=max_pages
        self.db=sqlite3.connect(db_path)
        self.db.execute('CREATE TABLE IF NOT EXISTS research_schedule(topic TEXT PRIMARY KEY, last_run REAL NOT NULL)')
    def run_due(self, now=None):
        now=time.time() if now is None else now
        reports=[]
        for topic in sorted(self.topics):
            last=self.db.execute('SELECT last_run FROM research_schedule WHERE topic=?',(topic,)).fetchone()
            if last and now-last[0]<self.interval: continue
            try:
                records=self.controller.research(topic,max_pages=self.max_pages)
                self.db.execute('INSERT OR REPLACE INTO research_schedule VALUES(?,?)',(topic,now)); self.db.commit()
                reports.append({'topic':topic,'queued':len(records),'status':'pending_review'})
            except Exception as exc:
                reports.append({'topic':topic,'status':'error','error':type(exc).__name__})
        return reports

class EvidenceCorroborator:
    """Require distinct approved domains; flags conflicts, never establishes factual truth."""
    def __init__(self, min_sources=2):
        if min_sources<2: raise ValueError('Need multiple independent sources')
        self.min_sources=min_sources
    def assess(self, observations):
        # Each item must refer to the same explicit, nonempty claim.
        observations = list(observations)
        claims = [o.get('claim') for o in observations]
        if any(not isinstance(claim, str) or not claim.strip() for claim in claims):
            raise ValueError('Each observation requires a nonempty claim')
        if len(set(claim.strip() for claim in claims)) > 1:
            raise ValueError('Cannot corroborate different claims together')
        domains={True:set(),False:set()}
        for o in observations:
            if not o.get('reviewed'): continue
            parsed=urlparse(o.get('url',''))
            if parsed.scheme!='https' or not parsed.hostname: continue
            domains[bool(o['supports'])].add(parsed.hostname.lower())
        conflict=bool(domains[True] and domains[False])
        return {'corroborated':len(domains[True])>=self.min_sources and not conflict,
                'contradiction':conflict,'supporting_domains':len(domains[True]),
                'opposing_domains':len(domains[False]),'needs_human_review':True}
