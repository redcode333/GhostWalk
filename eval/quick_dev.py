import sys, time; sys.path.insert(0, '.')
from eval.runner import load, run_company, acc, METHODS
cos = load('dev')
t = time.time()
for m in METHODS:
    rows = [r for co in cos for r in run_company(co, m)]
    early = [r for r in rows if r['seq'] < 15]; late = [r for r in rows if r['seq'] >= 45]
    print(f"{m:13s} AC@1 {acc(rows):.3f}  AC@3 {acc(rows,3):.3f}  early {acc(early):.3f}  late {acc(late):.3f}")
pl = [r for co in cos for r in run_company(co, 'ghostwalk', placebo=True)]
print(f"{'placebo':13s} AC@1 {acc(pl):.3f}  early {acc([r for r in pl if r['seq']<15]):.3f} late {acc([r for r in pl if r['seq']>=45]):.3f}")
for h in (1,2,3,5):
    rows=[r for co in cos for r in run_company(co,'ghostwalk',max_hops=h)]; print('depth',h,f"{acc(rows):.3f}")
print('secs', round(time.time()-t,1))
