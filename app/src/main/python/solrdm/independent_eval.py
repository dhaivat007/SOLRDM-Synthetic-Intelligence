"""Precommitted, group-separated evaluation. Validation selects settings; test is run once.
All data are synthetic authored examples, NOT an external independent benchmark.
"""
import json,random,hashlib
from .language_learning import EnglishIntentLearner
from .compositional import CompositionalLearner

TEMPLATES={
'math':(['calculate {n}','compute {n}','evaluate {n}','solve {n}','work out {n}','determine the sum of {n}','what is {n} plus two'],['please calculate {n}','can you solve {n}'],['find the numerical answer to {n}','what does {n} equal']),
'research':(['research {n}','search for {n}','look up {n}','find articles on {n}','investigate {n}','browse sources on {n}','find references about {n}'],['please research {n}','can you search for {n}'],['locate publications concerning {n}','seek documentary sources about {n}']),
'science':(['test a hypothesis about {n}','analyze measurements of {n}','fit a model to {n}','discover a pattern in {n}','infer a scientific law for {n}','compare experimental results on {n}','estimate a relationship in {n}'],['please analyze measurements of {n}','can you test a hypothesis about {n}'],['derive an empirical relationship for {n}','identify regularities in observations of {n}']),
'memory':(['remember {n}','save {n}','store {n}','retain {n}','record {n}','memorize {n}','keep a note about {n}'],['please remember {n}','can you store {n}'],['preserve this detail about {n}','commit the following observation to memory {n}'])
}
NOUNS=(['copper','velocity','voltage','turbine','force','gravity'],['viscosity','resonance'],['pressure','conductivity','orbital period','diffusion'])

def build(split):
    i={'train':0,'validation':1,'test':2}[split]
    return [(form.format(n=noun),label) for label,groups in TEMPLATES.items() for form in groups[i] for noun in NOUNS[i]]

def run():
    train=build('train'); validation=build('validation'); test=build('test')
    assert not (set(x for x,_ in train)&set(x for x,_ in validation))
    assert not (set(x for x,_ in train+validation)&set(x for x,_ in test))
    # Training is frozen prior to evaluating test. Validation chooses among predefined candidates.
    candidates=[]
    for cls in (EnglishIntentLearner,CompositionalLearner):
        for epochs in (30,70):
            m=cls();m.fit(train,epochs=epochs)
            candidates.append((m.evaluate(validation)['accuracy'],cls.__name__,epochs,m))
    candidates.sort(key=lambda x:(-x[0],x[1],x[2]))
    best=candidates[0]
    # Baseline and selected model both tested exactly once in this script.
    baseline=EnglishIntentLearner();baseline.fit(train,epochs=70)
    results={
      'protocol':'synthetic group-separated train/validation/test; validation-only selection',
      'train_size':len(train),'validation_size':len(validation),'test_size':len(test),
      'test_sha256':hashlib.sha256(json.dumps(test).encode()).hexdigest(),
      'baseline':baseline.evaluate(test),'selected':{'model':best[1],'epochs':best[2],**best[3].evaluate(test)},
      'validation_candidates':[{'model':n,'epochs':e,'accuracy':a} for a,n,e,_ in candidates],
      'per_class':{label:{'correct':sum(best[3].predict(t)['label']==y for t,y in test if y==label),'total':sum(y==label for _,y in test)} for label in TEMPLATES},
      'limitations':'Tiny authored synthetic dataset, lexical overlap and no independent third-party evaluation; not general English comprehension.'
    }
    return results
if __name__=='__main__': print(json.dumps(run(),indent=2))
