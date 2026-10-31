"""From-scratch English intent learner: hashed bag-of-words softmax classifier.
No pretrained vocabulary or language model. Evaluation uses unseen group splits.
"""
import math, random, re, hashlib, copy

class EnglishIntentLearner:
    def __init__(self, dimensions=256, rate=0.15, seed=17):
        if not 16<=dimensions<=4096 or not 0<rate<=1: raise ValueError('Bad hyperparameters')
        self.dim=dimensions; self.rate=rate; self.seed=seed; self.weights={}; self.labels=[]
    def features(self, text):
        words=re.findall(r"[a-z]+(?:'[a-z]+)?",text.lower())[:256]
        feats={}
        for w in words:
            idx=int.from_bytes(hashlib.sha256(w.encode()).digest()[:4],'big')%self.dim
            feats[idx]=feats.get(idx,0)+1
        return {k:v/max(1,len(words)) for k,v in feats.items()}
    def predict(self, text):
        if not self.labels: return {'label':None,'score':0.0}
        x=self.features(text)
        scores={label:sum(self.weights[label][i]*v for i,v in x.items()) for label in self.labels}
        m=max(scores.values()); exp={k:math.exp(v-m) for k,v in scores.items()}; z=sum(exp.values())
        probs={k:v/z for k,v in exp.items()}
        label=max(sorted(probs),key=probs.get)
        return {'label':label,'score':probs[label]}
    def fit(self, examples, epochs=40):
        examples=list(examples)
        if not examples or len(examples)>10000 or not 1<=epochs<=300: raise ValueError('Invalid training set')
        labels=sorted({label for text,label in examples})
        if len(labels)<2: raise ValueError('Need at least two labels')
        self.labels=labels; self.weights={k:[0.0]*self.dim for k in labels}
        rng=random.Random(self.seed)
        for _ in range(epochs):
            shuffled=examples[:]; rng.shuffle(shuffled)
            for text,correct in shuffled:
                x=self.features(text)
                scores={k:sum(self.weights[k][i]*v for i,v in x.items()) for k in labels}
                m=max(scores.values()); exp={k:math.exp(v-m) for k,v in scores.items()}; z=sum(exp.values())
                for k in labels:
                    err=(1 if k==correct else 0)-exp[k]/z
                    for i,v in x.items(): self.weights[k][i]+=self.rate*err*v
    def evaluate(self, examples):
        examples=list(examples)
        if not examples: raise ValueError('Empty evaluation set')
        correct=sum(self.predict(text)['label']==label for text,label in examples)
        return {'correct':correct,'total':len(examples),'accuracy':correct/len(examples)}

class GatedLanguageTrainer:
    """Candidate training is accepted only when performance on a fixed external holdout does not regress."""
    def __init__(self, model, holdout, min_accuracy=0.65):
        self.model=model; self.holdout=list(holdout); self.min_accuracy=min_accuracy
        if not self.holdout: raise ValueError('Holdout required')
    def propose(self, training, epochs=40):
        baseline=self.model.evaluate(self.holdout)['accuracy'] if self.model.labels else 0.0
        candidate=copy.deepcopy(self.model); candidate.fit(training,epochs=epochs)
        measured=candidate.evaluate(self.holdout)
        accepted=measured['accuracy']>=max(self.min_accuracy,baseline)
        if accepted: self.model.labels=candidate.labels; self.model.weights=candidate.weights
        return {'accepted':accepted,'baseline_accuracy':baseline,'candidate_accuracy':measured['accuracy'],
                'holdout_size':len(self.holdout),'rollback':not accepted}
