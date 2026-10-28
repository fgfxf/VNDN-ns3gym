#!/usr/bin/env python3
"""Read-only Circle RTT diagnosis from all five loads and four strategies."""
import csv,hashlib,json,statistics,math
from pathlib import Path
from collections import defaultdict
ROOT=Path('/home/fgfxf/ndnSIM/ns-3');OUT=Path(__file__).resolve().parent
BASE=ROOT/'data/experiments/quick-fixed-model-20261022/workflow/figures/all/attempt-001'
COND={1500:'n10-v30-k1500',3000:'n10-v30-k3000',6000:'baseline',9000:'n10-v30-k9000',12000:'n10-v30-k12000'}
def rows(p):
 with p.open()as f:yield from csv.DictReader(f)
def sha(p):
 h=hashlib.sha256()
 with p.open('rb')as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def summary(v):
 if not v:return {'n':0}
 a=sorted(v);return {'n':len(a),'mean_ms':statistics.mean(a),'p50_ms':a[(len(a)-1)//2],'p95_ms':a[math.floor((len(a)-1)*.95)],'ge400ms':sum(x>=400 for x in a),'ge490ms':sum(x>=490 for x in a)}
RUNS={};reports=[];points=list(rows(BASE/'analysis/plot-summary.csv'))
for meta in rows(BASE/'analysis/run-metrics.csv'):
 if meta['scene']!='circle' or meta['condition_id']not in COND.values():continue
 key=(int(meta['generated']),int(meta['seed_family']),int(meta['strategy']));p=Path(meta['run_path']);m=json.loads((p/'manifest.json').read_text())
 assert sha(p/'manifest.json')==meta['manifest_sha256'] and m['status']=='complete'
 hashes={}
 for rel in ['raw/request-events.csv','raw/packet-l3.csv','raw/data-rx.csv','run-metrics.json']:
  hashes[rel]=sha(p/rel);assert hashes[rel]==m['artifact_hashes'][rel]
 req={};byname={}
 for r in rows(p/'raw/request-events.csv'):
  rid=r['request_id'];t=int(r['time_ns']);ev=r['event']
  if ev=='GENERATED':
   assert rid not in req
   q={'name':r['name'],'send_ns':int(r['send_ns']),'deadline_ns':int(r['deadline_ns']),'node':int(r['node_id']),'terminal':None,'wire':[],'rx':[]};req[rid]=q;byname[r['name']]=q
  elif ev in ('DATA','TIMEOUT','NACK','STOPPED'):
   q=req[rid];assert q['terminal']is None;q.update(terminal=ev,end_ns=t)
   if ev=='DATA':assert t<=q['deadline_ns'];q['rtt_ms']=(t-q['send_ns'])/1e6
 for r in rows(p/'raw/packet-l3.csv'):
  if r['node_id']in('0','1')and r['face_id']=='257'and r['packet_type']=='DATA'and r['semantic_class']=='business':
   q=byname.get(r['name'])
   if q:q['wire'].append((int(r['time_ns']),int(r['node_id'])))
 for r in rows(p/'raw/data-rx.csv'):
  if r['node_id']in('0','1')and r['face_id']=='258':
   q=byname.get(r['name'])
   if q:q['rx'].append((int(r['time_ns']),int(r['node_id'])))
 success={};missing=0;multiple=0
 for rid,q in req.items():
  assert q['terminal']is not None
  if q['terminal']!='DATA':continue
  wire=sorted((t,n)for t,n in q['wire']if q['send_ns']<=t<=q['end_ns']);rx=sorted((t,n)for t,n in q['rx']if q['send_ns']<=t<=q['end_ns'])
  if not wire:missing+=1
  else:
   q['send_to_wire_ms']=(wire[0][0]-q['send_ns'])/1e6
   q['wire_to_delivery_ms']=(q['end_ns']-wire[-1][0])/1e6
   multiple+=len(wire)>1
   same=[t for t,n in rx if n==wire[0][1]and t<=wire[0][0]]
   if same:q['rsu_return_to_wire_ms']=(wire[0][0]-min(same))/1e6
  success[rid]=q
 assert len(req)==int(meta['generated'])and len(success)==int(meta['satisfied'])
 assert abs(sum(q['rtt_ms']for q in success.values())/len(success)-float(meta['mean_success_rtt_ms']))<1e-8
 fields=['rtt_ms','send_to_wire_ms','wire_to_delivery_ms','rsu_return_to_wire_ms']
 report={'k':key[0],'seed':key[1],'strategy':key[2],'run_path':str(p),'manifest_sha256':meta['manifest_sha256'],'source':m['source'],'verified_hashes':hashes,'generated':len(req),'satisfied':len(success),'missing_wire':missing,'multiple_wire_success':multiple,'latency':{f:summary([q[f]for q in success.values()if f in q])for f in fields}}
 reports.append(report);RUNS[key]=(req,success);print(key,report['latency']['rtt_ms']['mean_ms'],report['latency'].get('wire_to_delivery_ms'),flush=True)
assert len(reports)==40
comparisons=[];table=[]
for k,c in COND.items():
 for seed in [23001,23002]:
  ref=RUNS[(k,seed,0)][0]
  for a in [1,2,3]:assert {r:(q['name'],q['send_ns'],q['node'])for r,q in ref.items()}=={r:(q['name'],q['send_ns'],q['node'])for r,q in RUNS[(k,seed,a)][0].items()}
  for a,b in [(0,3),(1,3),(2,3)]:
   aa=RUNS[(k,seed,a)][1];bb=RUNS[(k,seed,b)][1];common=set(aa)&set(bb)
   comparisons.append({'k':k,'seed':seed,'strategies':[a,b],'common_successes':len(common),'only_first':len(set(aa)-set(bb)),'only_second':len(set(bb)-set(aa)),
    'common_latency':{str(s):{f:summary([d[r][f]for r in common if f in d[r]])for f in fields}for s,d in[(a,aa),(b,bb)]}})
 for a in range(4):
  rr=[r for r in reports if r['k']==k and r['strategy']==a];n=sum(r['satisfied']for r in rr);mean=sum(r['latency']['rtt_ms']['mean_ms']*r['satisfied']for r in rr)/n
  match=next(r for r in points if r['scene']=='circle'and r['condition_id']==c and int(r['strategy'])==a and r['metric']=='mean_success_rtt_ms');assert abs(mean-float(match['estimate']))<1e-8
  table.append({'k':k,'strategy':a,'mean_success_rtt_ms':mean,'generated_total':k*2,'satisfied_total':n,'isr_percent':n/k/2*100,'mean_last_wireless_to_delivery_ms':sum(r['latency']['wire_to_delivery_ms']['mean_ms']*r['satisfied']for r in rr)/n,'repetitions':2})
with(OUT/'f02-circle-points.csv').open('w',newline='')as f:
 w=csv.DictWriter(f,fieldnames=list(table[0]));w.writeheader();w.writerows(table)
report={'scope':'All 40 original Circle Interest-scan runs: five loads, two seeds, four strategies. No new experiment; all successes, no filtering favourable results.','request_count':sum(r['generated']for r in reports),'method':'Original DATA terminals only, send-to-DATA, pooled success-weighted mean. Each pair is same load+seed+request ID and equal frozen request identity. Wireless interval uses latest eligible RSU face257 DATA output before delivery, not pure MAC queue time.','runs':reports,'comparisons':comparisons,'points':table}
(OUT/'rtt-report.json').write_text(json.dumps(report,indent=2)+'\n');print('PASS',len(reports),'runs',report['request_count'],'requests; 20 F02 points restored')
