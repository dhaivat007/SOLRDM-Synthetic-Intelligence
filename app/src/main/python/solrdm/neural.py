"""Tiny from-scratch neural representation learner (no pretrained weights).
Learns entity embeddings from observed directed pairs with logistic negative sampling.
Scores are similarities, not calibrated truth probabilities.
"""
import math, random, json

class NeuralRepresentations:
    def __init__(self, dimensions=12, learning_rate=0.06, seed=7):
        if not 1 <= dimensions <= 256 or not 0 < learning_rate <= 1:
            raise ValueError('Invalid hyperparameters')
        self.dimensions=dimensions; self.lr=learning_rate; self.rng=random.Random(seed)
        self.vectors={}; self.training_steps=0

    def _vector(self, key):
        if key not in self.vectors:
            self.vectors[key]=[self.rng.uniform(-0.1,0.1) for _ in range(self.dimensions)]
        return self.vectors[key]

    @staticmethod
    def _sigmoid(x):
        return 1/(1+math.exp(-max(-30,min(30,x))))

    def _update(self, a, b, label):
        va=self._vector('S:'+a); vb=self._vector('O:'+b)
        dot=sum(x*y for x,y in zip(va,vb))
        error=label-self._sigmoid(dot)
        old=va[:]
        for i in range(self.dimensions):
            va[i]+=self.lr*error*vb[i]
            vb[i]+=self.lr*error*old[i]
        self.training_steps+=1

    def train(self, pairs, epochs=30, negatives=2):
        pairs=list(pairs)
        if not pairs or not 1 <= epochs <= 500 or not 0 <= negatives <= 20:
            raise ValueError('Invalid training data or limits')
        if len(pairs)>10000 or any(not isinstance(a,str) or not isinstance(b,str) or not a or not b for a,b in pairs):
            raise ValueError('Invalid pairs')
        targets=sorted({b for _,b in pairs}); positives=set(pairs)
        if len(targets)<2 and negatives: raise ValueError('At least two targets needed for negative sampling')
        for _ in range(epochs):
            order=pairs[:]; self.rng.shuffle(order)
            for a,b in order:
                self._update(a,b,1)
                possible=[t for t in targets if (a,t) not in positives]
                for _ in range(negatives):
                    if possible: self._update(a,self.rng.choice(possible),0)
        return {'steps':self.training_steps,'entities':len(self.vectors)}

    def score(self, subject, object):
        if 'S:'+subject not in self.vectors or 'O:'+object not in self.vectors: return None
        return self._sigmoid(sum(x*y for x,y in zip(self.vectors['S:'+subject],self.vectors['O:'+object])))

    def save(self, path):
        with open(path,'w') as f: json.dump({'dimensions':self.dimensions,'lr':self.lr,'vectors':self.vectors,'steps':self.training_steps},f)

    @classmethod
    def load(cls,path):
        with open(path) as f: data=json.load(f)
        obj=cls(data['dimensions'],data['lr']); obj.vectors=data['vectors']; obj.training_steps=data['steps']
        return obj
