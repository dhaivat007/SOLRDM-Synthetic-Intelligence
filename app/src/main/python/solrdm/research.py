"""Research queue and provenance. External text is NEVER executed or treated as instructions."""
import sqlite3, time, json
from .english import EnglishUnderstanding

class ResearchMemory:
    def __init__(self, db_path=':memory:'):
        self.db=sqlite3.connect(db_path)
        self.db.execute('''CREATE TABLE IF NOT EXISTS research (
          id INTEGER PRIMARY KEY, topic TEXT, title TEXT, source_url TEXT,
          source_type TEXT, excerpt TEXT, status TEXT, created REAL)''')
        self.db.commit()
    def add(self,topic,article):
        if not article: return None
        cur=self.db.execute('INSERT INTO research(topic,title,source_url,source_type,excerpt,status,created) VALUES(?,?,?,?,?,?,?)',
            (topic,article['title'],article['source_url'],article['source_type'],article['text'][:12000], 'pending_review',time.time()))
        self.db.commit(); return cur.lastrowid
    def pending(self):
        return self.db.execute('SELECT id,topic,title,source_url,status FROM research WHERE status=? ORDER BY id',('pending_review',)).fetchall()
    def review(self,record_id,approve):
        status='reviewed' if approve else 'rejected'
        cur=self.db.execute('UPDATE research SET status=? WHERE id=? AND status=?',(status,record_id,'pending_review'))
        self.db.commit(); return cur.rowcount==1
    def get(self,record_id):
        return self.db.execute('SELECT id,topic,title,source_url,excerpt,status FROM research WHERE id=?',(record_id,)).fetchone()
    def close(self): self.db.close()

class ResearchController:
    def __init__(self, internet, memory, language=None):
        self.internet=internet; self.memory=memory; self.language=language or EnglishUnderstanding()
    def research(self,topic,max_pages=2):
        if not 1<=max_pages<=5: raise ValueError('max_pages out of bounds')
        results=[]
        for hit in self.internet.search(topic,limit=max_pages):
            article=self.internet.extract(hit.title)
            if article:
                record_id=self.memory.add(topic,article)
                results.append({'record_id':record_id,'title':article['title'],'url':article['source_url'],
                                'status':'pending_review'})
        return results
    def candidate_facts(self,record_id):
        row=self.memory.get(record_id)
        if not row or row[5]!='reviewed': return []
        # Simple sentence segmentation; candidate facts are NOT automatically asserted.
        candidates=[]
        for sentence in row[4][:3000].split('.')[:30]:
            parsed=self.language.parse(sentence.strip(),source=row[3])
            candidates.extend(parsed.facts)
        return candidates
