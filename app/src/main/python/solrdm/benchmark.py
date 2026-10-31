"""Frozen, group-separated evaluation for native English intent learning."""
from dataclasses import dataclass
import hashlib, json, random
from .language_learning import EnglishIntentLearner

# Separately authored sentence templates. Holdout uses unseen constructions AND nouns.
TRAIN = {
 'math':['calculate {x}', 'compute {x}', 'find the value of {x}', 'work out {x}'],
 'research':['research {x}', 'look up {x}', 'search for {x}', 'find sources about {x}'],
 'science':['test a hypothesis about {x}', 'fit an equation for {x}', 'analyze measurements of {x}', 'model the relation in {x}'],
 'memory':['remember {x}', 'store the fact about {x}', 'save information on {x}', 'record {x}'],
}
TEST = {
 'math':['what is the result for {x}', 'could you evaluate {x}'],
 'research':['locate references concerning {x}', 'please investigate {x}'],
 'science':['infer a mathematical law from {x}', 'discover a pattern in the data for {x}'],
 'memory':['keep this knowledge about {x}', 'retain the observation concerning {x}'],
}
TRAIN_NOUNS=['velocity','gravity','copper','resistance','turbine','voltage']
TEST_NOUNS=['orbital period','thermal conductivity','diffusion','fluid pressure']

def examples(templates,nouns):
 return [(template.format(x=noun),label) for label,forms in templates.items() for template in forms for noun in nouns]

def fingerprint(data):
 return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()

def run_benchmark(epochs=80):
 train=examples(TRAIN,TRAIN_NOUNS); test=examples(TEST,TEST_NOUNS)
 assert not ({t for t,_ in train}&{t for t,_ in test})
 model=EnglishIntentLearner(seed=17)
 model.fit(train,epochs=epochs)
 report=model.evaluate(test)
 per_class={label: {'correct':sum(model.predict(t)['label']==y for t,y in test if y==label), 'total':sum(y==label for _,y in test)} for label in sorted(TEST)}
 # Majority class chance baseline is 25% on balanced benchmark.
 return {'accuracy':report['accuracy'],'correct':report['correct'],'total':report['total'], 'per_class':per_class,'chance_baseline':0.25,'train_size':len(train),'test_fingerprint':fingerprint(test),'model':model}
