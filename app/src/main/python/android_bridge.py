"""Offline SOLRDM Android observation bridge. Experimental subset, not the full v0.7 engine."""
import os
import sqlite3
import re

def observe(storage_dir, sentence):
    sentence = sentence.strip()
    if len(sentence) > 2000:
        return "Observation too long"
    pattern = re.fullmatch(r"([A-Za-z][A-Za-z -]{0,80}) is part of (?:a |an |the )?([A-Za-z][A-Za-z -]{0,80})[.]?", sentence, re.I)
    if not pattern:
        return "Unsupported sentence structure; no fact saved."
    subject, obj = (v.strip().rstrip(".").lower() for v in pattern.groups())
    path = os.path.join(storage_dir, "solrdm.sqlite3")
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS observations(subject TEXT, predicate TEXT, object TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        db.execute("INSERT INTO observations(subject,predicate,object) VALUES(?,?,?)", (subject, "part_of", obj))
        count = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    return f"Stored: {subject} → part_of → {obj}. Observations: {count}"
