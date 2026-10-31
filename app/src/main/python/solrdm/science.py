"""Bounded, domain-agnostic numerical hypothesis search: y ~= a*x + b.
Exploratory discovery only; correlation is not causation or experimental validation.
"""
from dataclasses import dataclass
from hashlib import sha256
import math

@dataclass(frozen=True)
class Measurement:
    case: str
    variable: str
    value: float
    unit: str = ''

class ScientificDiscovery:
    def __init__(self): self.measurements=[]

    def observe(self, m: Measurement):
        if not m.case or not m.variable or not math.isfinite(m.value): raise ValueError('Invalid measurement')
        if any(x.case==m.case and x.variable==m.variable for x in self.measurements): raise ValueError('Duplicate measurement')
        self.measurements.append(m)

    def discover(self, min_train=5, min_test=2, min_r2=0.85):
        cases={}
        units={}
        for m in self.measurements:
            cases.setdefault(m.case,{})[m.variable]=m.value
            if m.variable in units and units[m.variable]!=m.unit: raise ValueError('Inconsistent units')
            units[m.variable]=m.unit
        variables=sorted(units); results=[]
        for x in variables:
            for y in variables:
                if x==y: continue
                rows=[(case,d[x],d[y]) for case,d in sorted(cases.items()) if x in d and y in d]
                train=[r for r in rows if int.from_bytes(sha256(r[0].encode()).digest()[:4],'big')%4 != 0]
                test=[r for r in rows if int.from_bytes(sha256(r[0].encode()).digest()[:4],'big')%4 == 0]
                if len(train)<min_train or len(test)<min_test: continue
                mx=sum(r[1] for r in train)/len(train); my=sum(r[2] for r in train)/len(train)
                denom=sum((r[1]-mx)**2 for r in train)
                if denom<1e-12: continue
                a=sum((r[1]-mx)*(r[2]-my) for r in train)/denom; b=my-a*mx
                yt=[r[2] for r in test]; pred=[a*r[1]+b for r in test]
                mean=sum(yt)/len(yt); total=sum((v-mean)**2 for v in yt)
                if total<1e-12: continue
                r2=1-sum((v-p)**2 for v,p in zip(yt,pred))/total
                if r2>=min_r2:
                    results.append({'hypothesis':f'{y} = {a:.6g} * {x} + {b:.6g}',
                                    'input':x,'output':y,'input_unit':units[x], 'output_unit':units[y],
                                    'slope':a,'intercept':b,'holdout_r2':r2,'train_n':len(train),'test_n':len(test),
                                    'status':'unverified','caveat':'Observational association, not causal proof; independently replicate.'})
        return sorted(results,key=lambda r:-r['holdout_r2'])
