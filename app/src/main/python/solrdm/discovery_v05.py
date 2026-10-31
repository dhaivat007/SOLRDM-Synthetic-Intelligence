"""Candidate numerical hypotheses; evaluation on held-out cases, not proof of causality."""
import math

class HypothesisLab:
    def discover(self, rows, x, y, min_train=6, min_test=3):
        rows=list(rows)
        if len(rows)<min_train+min_test: return []
        # Caller supplies independent case rows; last portion is never used to fit.
        train=rows[:-min_test]; test=rows[-min_test:]
        candidates=[]
        for name,transform in [('linear',lambda v:v),('quadratic',lambda v:v*v),('logarithmic',lambda v:math.log(v) if v>0 else None),('inverse',lambda v:1/v if v else None)]:
            try:
                pts=[(transform(float(r[x])),float(r[y])) for r in train]
                tst=[(transform(float(r[x])),float(r[y])) for r in test]
                if any(a is None or not math.isfinite(a) or not math.isfinite(b) for a,b in pts+tst): continue
                mx=sum(a for a,b in pts)/len(pts); my=sum(b for a,b in pts)/len(pts)
                den=sum((a-mx)**2 for a,b in pts)
                if den<1e-12: continue
                slope=sum((a-mx)*(b-my) for a,b in pts)/den; intercept=my-slope*mx
                pred=[slope*a+intercept for a,b in tst]; actual=[b for a,b in tst]
                rmse=math.sqrt(sum((p-b)**2 for p,b in zip(pred,actual))/len(actual))
                base=sum(float(r[y]) for r in train)/len(train)
                baseline=math.sqrt(sum((base-b)**2 for b in actual)/len(actual))
                candidates.append({'form':name,'slope':slope,'intercept':intercept,'test_rmse':rmse,
                                   'baseline_rmse':baseline,'beats_baseline':rmse<baseline,'test_count':len(test),
                                   'status':'hypothesis_requires_replication'})
            except (KeyError,ValueError,TypeError,OverflowError,ZeroDivisionError): continue
        return sorted(candidates,key=lambda c:c['test_rmse'])
