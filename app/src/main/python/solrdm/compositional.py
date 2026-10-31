"""Native sparse compositional classifier: learned word/character ngram features, no pretrained weights."""
import re,hashlib
from .language_learning import EnglishIntentLearner

class CompositionalLearner(EnglishIntentLearner):
    def __init__(self, dimensions=4096, rate=0.25, seed=17):
        super().__init__(dimensions,rate,seed)
    def features(self,text):
        words=re.findall(r"[a-z]+",text.lower())[:128]
        tokens=[]
        for word in words:
            tokens.append('w:'+word)
            if len(word)>=5:
                tokens.extend('c:'+word[i:i+4] for i in range(len(word)-3))
        # local composition: phrase order, not merely a bag of words
        tokens.extend('b:'+a+'_'+b for a,b in zip(words,words[1:]))
        feats={}
        for tok in tokens:
            idx=int.from_bytes(hashlib.sha256(tok.encode()).digest()[:4],'big')%self.dim
            feats[idx]=feats.get(idx,0)+1
        norm=max(1,len(words))**0.5
        return {k:v/norm for k,v in feats.items()}
