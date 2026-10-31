#!/usr/bin/env python3
"""Offline, authored synthetic checks; not external independent evaluation.

Measure symbolic closure and the native neural learner separately. The two
provided language evaluation scripts are retained with their own limitations.
Stdout is one JSON object suitable for a CI evidence artifact.
"""
import hashlib
import json
import platform
from pathlib import Path
import sys
import tempfile
from time import perf_counter

SOURCE = Path(__file__).resolve().parents[1] / 'app/src/main/python'
sys.path.insert(0, str(SOURCE))
from solrdm import SOLRDM, Fact, Rule, NeuralRepresentations
from solrdm.benchmark import run_benchmark
from solrdm.independent_eval import run as run_authored_group_evaluation


def symbolic_benchmark():
    count = 24
    engine = SOLRDM(':memory:')
    try:
        for i in range(count - 1):
            engine.observe(Fact(f'node-{i}', 'part_of', f'node-{i + 1}', 1.0, 'synthetic:fixture'))
        engine.add_rule(Rule('part_of', 'part_of', 'part_of'))
        expected = {(f'node-{i}', 'part_of', f'node-{j}')
                    for i in range(count) for j in range(i + 2, count)}
        start = perf_counter()
        inferred = engine.infer(max_rounds=5)
        elapsed = perf_counter() - start
        actual = {(fact.subject, fact.relation, fact.object) for fact in inferred}
        correct = len(actual & expected)
        assert actual == expected, 'Symbolic transitive closure changed'
        assert len(engine.facts()) == count - 1, 'Inference persisted unverified observations'
        return {
            'task': 'exact transitive closure of an authored chain',
            'observed_edges': count - 1,
            'expected_inferred_edges': len(expected),
            'actual_inferred_edges': len(actual),
            'precision': correct / len(actual),
            'recall': correct / len(expected),
            'inference_seconds': elapsed,
            'limitations': 'One deterministic synthetic relation; no noisy evidence or open-domain reasoning evaluation.',
        }
    finally:
        engine.close()


def neural_benchmark():
    pairs = [(f'entity-{i}', f'target-{i}') for i in range(8)]
    targets = [target for _, target in pairs]
    model = NeuralRepresentations(dimensions=12, learning_rate=0.06, seed=7)
    epochs, negatives = 180, 3
    start = perf_counter()
    result = model.train(pairs, epochs=epochs, negatives=negatives)
    train_elapsed = perf_counter() - start
    positive_scores = [model.score(subject, target) for subject, target in pairs]
    negative_scores = [model.score(subject, target) for subject, expected in pairs
                       for target in targets if target != expected]
    top1_correct = sum(max(targets, key=lambda target: model.score(subject, target)) == expected
                       for subject, expected in pairs)
    assert result['steps'] == len(pairs) * epochs * (1 + negatives)
    assert sum(positive_scores) / len(positive_scores) > sum(negative_scores) / len(negative_scores)
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / 'neural.json')
        model.save(path)
        restored = NeuralRepresentations.load(path)
        assert restored.training_steps == model.training_steps
        assert [restored.score(*pair) for pair in pairs] == positive_scores
    return {
        'task': 'training-pair reconstruction with native logistic negative sampling',
        'seed': 7,
        'dimensions': 12,
        'epochs': epochs,
        'negative_samples_per_positive': negatives,
        'training_pairs': len(pairs),
        'training_steps': result['steps'],
        'top1_training_correct': top1_correct,
        'top1_training_total': len(pairs),
        'mean_positive_similarity': sum(positive_scores) / len(positive_scores),
        'mean_negative_similarity': sum(negative_scores) / len(negative_scores),
        'save_reload_scores_identical': True,
        'training_seconds': train_elapsed,
        'limitations': 'Training-set reconstruction only; no heldout generalization test. Similarities are not truth probabilities.',
    }


def main():
    symbolic = symbolic_benchmark()
    neural = neural_benchmark()
    start = perf_counter()
    supplied_language = run_benchmark()
    supplied_language.pop('model')  # Omit the nonserializable trained Python object.
    supplied_language['evaluation_seconds'] = perf_counter() - start
    supplied_language['limitations'] = 'Small authored synthetic train/test examples, not an external independent benchmark.'
    start = perf_counter()
    supplied_group_eval = run_authored_group_evaluation()
    supplied_group_eval['evaluation_seconds'] = perf_counter() - start
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted((SOURCE / 'solrdm').glob('*.py'))}
    result = {
        'protocol': 'Separate offline symbolic and neural measurements plus supplied authored synthetic language evaluations',
        'environment': {'python': platform.python_version(), 'architecture': platform.machine(),
                        'platform': platform.system()},
        'module_count': len(hashes),
        'module_sha256': hashes,
        'symbolic': symbolic,
        'neural': neural,
        'supplied_language_benchmark': supplied_language,
        'supplied_group_separated_evaluation': supplied_group_eval,
        'limitations': 'No pretrained LLM. No network ingestion. These internal synthetic fixtures do not establish general intelligence, scientific validity, or complete Android UI feature parity. Timings depend on the host.',
    }
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    main()
