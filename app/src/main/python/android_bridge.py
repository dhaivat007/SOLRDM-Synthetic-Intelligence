"""Bounded Android adapter for the user-supplied SOLRDM v0.7 source bundle.

All supplied modules are imported, but only the six listed offline operations are
exposed here. Importing a module does not establish complete feature parity.
"""
from contextlib import closing
import importlib
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time

MODULES = (
    "solrdm", "solrdm.core", "solrdm.learning", "solrdm.neural",
    "solrdm.science", "solrdm.self_learning", "solrdm.english",
    "solrdm.internet", "solrdm.research", "solrdm.autonomy",
    "solrdm.language_learning", "solrdm.discovery_v05", "solrdm.agent_v06",
    "solrdm.compositional", "solrdm.benchmark", "solrdm.independent_eval",
)
COMMANDS = ("observe", "interpret", "query", "discover", "neural_train", "status")
MAX_PAYLOAD = 4096
MAX_FIELD = 200
MAX_OBSERVATIONS = 1000
MAX_INFERENCE_FACTS = 100
MAX_TRAINING_FACTS = 200
MAX_RESULTS = 100
INFERENCE_ROUNDS = 2
# Serialize bridge operations without retaining thread-affine SQLite connections.
_COMMAND_LOCK = threading.RLock()


def _imports():
    return {name: importlib.import_module(name) for name in MODULES}


def _field(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_FIELD:
        raise ValueError(f"{name} must be a nonempty string of at most {MAX_FIELD} characters")
    if any(ord(c) < 32 for c in value):
        raise ValueError(f"{name} cannot contain control characters")
    return value.strip()


def _migrate_legacy(ai, fact_class):
    """Copy old observations exactly once, preserving originals and row provenance."""
    db = ai.db
    with db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("CREATE TABLE IF NOT EXISTS android_migrations (name TEXT PRIMARY KEY, details TEXT NOT NULL)")
        previous = db.execute("SELECT details FROM android_migrations WHERE name=?", ("observation_bridge_v1",)).fetchone()
        if previous:
            return json.loads(previous[0])
        table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='observations'").fetchone()
        migrated = 0
        if table:
            rows = db.execute("SELECT rowid, subject, predicate, object, COALESCE(CAST(strftime('%s', created_at) AS REAL), ?) FROM observations ORDER BY rowid", (time.time(),))
            for rowid, subject, relation, obj, created in rows:
                source = f"android:legacy:observations:{rowid}"
                fact_class(subject, relation, obj, 0.8, source)
                db.execute("INSERT INTO facts(subject,relation,object,confidence,source,created) VALUES(?,?,?,?,?,?)", (subject, relation, obj, 0.8, source, created))
                migrated += 1
        details = {"legacy_rows_migrated": migrated, "original_observations_retained": True}
        db.execute("INSERT INTO android_migrations(name,details) VALUES(?,?)", ("observation_bridge_v1", json.dumps(details)))
        return details


def _model_path(db_path):
    return Path(str(db_path) + ".neural.json")


def _load_neural(path, neural_class):
    if not path.exists():
        return neural_class()
    if path.stat().st_size > 2_000_000:
        raise ValueError("Saved neural model exceeds the Android size limit")
    with path.open(encoding="utf-8") as stream:
        data = json.load(stream)
    dimensions = data.get("dimensions")
    vectors = data.get("vectors")
    steps = data.get("steps")
    if type(dimensions) is not int or not 1 <= dimensions <= 256:
        raise ValueError("Invalid saved neural dimensions")
    if not isinstance(vectors, dict) or len(vectors) > 2 * MAX_OBSERVATIONS:
        raise ValueError("Invalid saved neural vectors")
    if type(steps) is not int or steps < 0:
        raise ValueError("Invalid saved neural training count")
    for key, vector in vectors.items():
        if not isinstance(key, str) or not key.startswith(("S:", "O:")) or len(key) > MAX_FIELD + 2:
            raise ValueError("Invalid saved neural entity")
        if not isinstance(vector, list) or len(vector) != dimensions or any(type(v) not in (int, float) or not math.isfinite(v) for v in vector):
            raise ValueError("Invalid saved neural vector")
    model = neural_class.load(str(path))
    if "random_state" in data:
        state = data["random_state"]
        model.rng.setstate((state[0], tuple(state[1]), state[2]))
    return model


def _save_neural(model, path):
    """Replace the model atomically; a failed save leaves the old model intact."""
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    os.close(fd)
    try:
        model.save(temporary)
        with open(temporary, encoding="utf-8") as stream:
            data = json.load(stream)
        data["random_state"] = model.rng.getstate()
        with open(temporary, "w", encoding="utf-8") as stream:
            json.dump(data, stream, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def execute(db_path, command, payload):
    """Return JSON; rejected inputs never masquerade as successful operations."""
    try:
        if command not in COMMANDS:
            raise ValueError("Unsupported command")
        if not isinstance(payload, str) or len(payload) > MAX_PAYLOAD:
            raise ValueError(f"Payload must be a string of at most {MAX_PAYLOAD} characters")
        path = Path(os.fspath(db_path)).absolute()
        if str(db_path) == ":memory:":
            raise ValueError("Android bridge requires a persistent database path")
        path.parent.mkdir(parents=True, exist_ok=True)
        with _COMMAND_LOCK:
            modules = _imports()
            core = modules["solrdm.core"]
            neural_class = modules["solrdm.neural"].NeuralRepresentations
            def entity(value):
                return modules["solrdm.english"].EnglishUnderstanding._entity(value) or value.strip().lower()

            def relation_name(value):
                return "_".join(value.lower().split())

            def canonical_fact(fact):
                return core.Fact(entity(fact.subject), relation_name(fact.relation),
                                 entity(fact.object), fact.confidence, fact.source)

            class AndroidEngine(core.SOLRDM):
                def facts(self):
                    # Normalize matching without rewriting historical observations.
                    return [canonical_fact(fact) for fact in super().facts()]

                def infer(self, max_rounds=INFERENCE_ROUNDS, min_confidence=0.25):
                    return super().infer(max_rounds=min(max_rounds, INFERENCE_ROUNDS), min_confidence=min_confidence)

            with closing(AndroidEngine(str(path))) as ai:
                migration = _migrate_legacy(ai, core.Fact)
                ai.add_rule(core.Rule("part_of", "part_of", "part_of"))
                ai.add_rule(core.Rule("type_of", "type_of", "type_of"))
                count = ai.db.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
                if command == "observe":
                    item = json.loads(payload)
                    if not isinstance(item, dict):
                        raise ValueError("Observation payload must be a JSON object")
                    subject = entity(_field(item.get("subject"), "subject"))
                    relation = relation_name(_field(item.get("relation"), "relation"))
                    obj = entity(_field(item.get("object"), "object"))
                    confidence = item.get("confidence", 0.8)
                    if type(confidence) not in (int, float) or not math.isfinite(confidence):
                        raise ValueError("confidence must be a finite number between 0 and 1")
                    fact = core.Fact(subject, relation, obj, confidence, "android:user")
                    exists = ai.db.execute("SELECT 1 FROM facts WHERE subject=? AND relation=? AND object=? AND source=?", (subject, relation, obj, fact.source)).fetchone()
                    if count >= MAX_OBSERVATIONS and not exists:
                        raise ValueError(f"Android observation capacity is {MAX_OBSERVATIONS}; existing data is retained")
                    ai.observe(fact)
                    result = {"ok": True, "message": "Observation saved (not independently verified)", "observations": count + (0 if exists else 1)}
                elif command == "interpret":
                    parsed = modules["solrdm.english"].EnglishUnderstanding().parse(payload)
                    result = {"ok": True, "intent": parsed.intent, "confidence": parsed.confidence, "candidate_facts": [f.__dict__ for f in parsed.facts], "limitations": parsed.limitations, "saved": False}
                elif command == "query":
                    subject = payload.strip() or None
                    if subject is not None:
                        subject = entity(_field(subject, "query subject"))
                    if count <= MAX_INFERENCE_FACTS:
                        facts = ai.query(subject=subject)
                        warning = None
                    else:
                        rows = ai.db.execute("SELECT subject,relation,object,confidence,source FROM facts ORDER BY subject,relation,object,source")
                        facts = []
                        for row in rows:
                            fact = canonical_fact(core.Fact(*row))
                            if subject is None or fact.subject == subject:
                                facts.append(fact)
                                if len(facts) > MAX_RESULTS:
                                    break
                        warning = f"Inference skipped above {MAX_INFERENCE_FACTS} observations; returning stored facts only"
                    result = {"ok": True, "facts": [f.__dict__ for f in facts[:MAX_RESULTS]], "truncated": len(facts) > MAX_RESULTS, "inference_round_limit": INFERENCE_ROUNDS, "warning": warning}
                elif command == "discover":
                    if count > MAX_INFERENCE_FACTS:
                        raise ValueError(f"Hypothesis generation is limited to {MAX_INFERENCE_FACTS} stored observations")
                    hypotheses = ai.discover()
                    result = {"ok": True, "hypotheses": hypotheses[:MAX_RESULTS], "truncated": len(hypotheses) > MAX_RESULTS, "inference_round_limit": INFERENCE_ROUNDS}
                elif command == "neural_train":
                    pairs = set()
                    for subject, obj in ai.db.execute("SELECT subject,object FROM facts ORDER BY subject,object"):
                        pairs.add((entity(subject), entity(obj)))
                        if len(pairs) > MAX_TRAINING_FACTS:
                            break
                    rows = sorted(pairs)
                    if len(rows) > MAX_TRAINING_FACTS:
                        raise ValueError(f"Neural training is limited to {MAX_TRAINING_FACTS} distinct observed pairs")
                    if len(rows) < 2 or len({b for _, b in rows}) < 2:
                        raise ValueError("At least two observations with distinct objects required")
                    model_path = _model_path(path)
                    model = _load_neural(model_path, neural_class)
                    training = model.train(rows, epochs=15, negatives=1)
                    _save_neural(model, model_path)
                    result = {"ok": True, "training": training, "persisted": True, "warning": "Similarity scores are not verified truth probabilities"}
                else:
                    model = _load_neural(_model_path(path), neural_class)
                    result = {"ok": True, "version": "0.7 supplied engine / Android adapter", "observations": count, "neural_training_steps": model.training_steps, "imported_modules": list(modules), "module_count": len(modules), "ui_commands": list(COMMANDS), "general_intelligence": False, "integration_complete": False, "migration": migration, "limits": {"observations": MAX_OBSERVATIONS, "inference_facts": MAX_INFERENCE_FACTS, "inference_rounds": INFERENCE_ROUNDS, "training_pairs": MAX_TRAINING_FACTS, "training_epochs_per_request": 15, "result_rows": MAX_RESULTS}, "limitations": "All supplied modules imported; six offline operations exposed. Advanced rule learning, science, research and language-training workflows are not in this UI. No autonomous internet ingestion."}
                return json.dumps(result, allow_nan=False)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc), "error_type": type(exc).__name__})
