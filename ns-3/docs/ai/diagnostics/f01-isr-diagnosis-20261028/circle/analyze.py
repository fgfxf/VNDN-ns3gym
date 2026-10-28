#!/usr/bin/env python3
"""Read existing data only; never edit source, run output, figures or metrics."""
import csv, hashlib, json, math, statistics, tarfile
from collections import Counter, defaultdict
from pathlib import Path
ROOT=Path('/home/fgfxf/ndnSIM/ns-3')
OUT=Path(__file__).resolve().parent
BATCH=ROOT/'data/experiments/quick-fixed-model-20261022'
TABLE=BATCH/'workflow/figures/all/attempt-001/analysis/run-metrics.csv'
TERMINALS={'DATA','TIMEOUT','NACK','STOPPED'}
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
 return h.hexdigest()
def rows(path):
 with path.open(newline='') as f:yield from csv.DictReader(f)
def stats(values):
 a=sorted(values)
 if not a:return {'n':0}
 return {'n':len(a),'mean_ms':statistics.mean(a),'p50_ms':a[(len(a)-1)//2],
 'p95_ms':a[math.floor((len(a)-1)*.95)],'max_ms':a[-1],
 'ge400ms':sum(v>=400 for v in a),'ge490ms':sum(v>=490 for v in a)}
def earliest(items):return min(items) if items else None
def analyze(meta):
 p=Path(meta['run_path']);m=json.loads((p/'manifest.json').read_text())
 assert m['status']=='complete' and m['source']['sha256']==SEAL['source']['sha256']
 assert sha(p/'manifest.json')==meta['manifest_sha256']
 for path,digest in m['input_hashes'].items():assert sha(Path(path))==digest
 if m['model']:assert sha(Path(m['model']['path']))==m['model']['sha256']
 wanted=['experiment.json','run-metrics.json','raw/request-events.csv','raw/data-rx.csv','raw/packet-l3.csv','raw/data-attempts.csv']
 hashes={}
 for rel in wanted:
  digest=sha(p/rel);assert digest==m['artifact_hashes'][rel],rel;hashes[rel]=digest
 req={};names={};diagnostics=Counter()
 for r in rows(p/'raw/request-events.csv'):
  name=r['name'];t=int(r['time_ns'])
  if r['event']=='GENERATED':
   assert name not in names and r['request_id'] not in req
   q={'request_id':r['request_id'],'name':name,'send_ns':int(r['send_ns']),'deadline_ns':int(r['deadline_ns']),
      'node_id':int(r['node_id']),'generation_rsu':int(r['rsu_id']),'terminal':None,'end_ns':None,
      'up':[],'rx':[],'wire':[],'obu_rx':[],'extra':[],'diagnostics':[]}
   req[r['request_id']]=q;names[name]=q
  elif r['event'] in TERMINALS:
   q=names[name];assert q['terminal'] is None
   q['terminal']=r['event'];q['end_ns']=t
   assert r['event']!='DATA' or t<=q['deadline_ns']
  else:
   names[name]['diagnostics'].append((r['event'],t));diagnostics[r['event']]+=1
 assert all(q['terminal'] in TERMINALS for q in req.values())
 for r in rows(p/'raw/data-rx.csv'):
  q=names.get(r['name'])
  if not q:continue
  t,node,face=int(r['time_ns']),int(r['node_id']),int(r['face_id'])
  if node in (0,1) and face==258:q['rx'].append((t,node))
  if node==q['node_id']:q['obu_rx'].append((t,node))
 loads=Counter();wire_by_rsu=Counter();controls=Counter();wire_seen_other=set()
 for r in rows(p/'raw/packet-l3.csv'):
  assert r['direction']=='OUT'
  t,node,face=int(r['time_ns']),int(r['node_id']),int(r['face_id'])
  if node in (0,1) and r['semantic_class'] in ('search','find','relay_data'):controls[r['semantic_class']]+=1
  if node in range(12) and face==257 and 20000000000<=t<140000000000:
   loads[(r['packet_type'],r['semantic_class'],'count')]+=1
   loads[(r['packet_type'],r['semantic_class'],'bytes')]+=int(r['wire_bytes'])
  q=names.get(r['name'])
  if not q:continue
  if node in (0,1) and r['semantic_class']=='business':
   if face==258 and r['packet_type']=='INTEREST':q['up'].append((t,node))
   if face==257 and r['packet_type']=='DATA':
    q['wire'].append((t,node));wire_by_rsu[node]+=1
 for r in rows(p/'raw/data-attempts.csv'):
  q=names[r['name']];q['extra'].append((int(r['time_ns']),r['reason']))
 flat=[];stages=Counter();success_fields=defaultdict(list);failure_fields=defaultdict(list)
 for q in req.values():
  send,deadline,end=q['send_ns'],q['deadline_ns'],q['end_ns'];success=q['terminal']=='DATA'
  up=[(t,n) for t,n in q['up'] if send<=t];rx=[(t,n) for t,n in q['rx'] if send<=t]
  wire=[(t,n)for t,n in q['wire'] if send<=t];obu=[(t,n)for t,n in q['obu_rx'] if send<=t]
  assert len(up)==len(q['up']) and len(rx)==len(q['rx']) and len(wire)==len(q['wire'])
  prewire=[(t,n)for t,n in wire if t<=deadline];prerx=[(t,n)for t,n in rx if t<=deadline]
  stages['generated']+=1;stages['app_success']+=success
  for key,seq in [('rsu_uplink_out',up),('rsu_data_in',rx),('wireless_out',wire),('target_obu_data_in',obu),('rsu_data_in_before_deadline',prerx),('wireless_out_before_deadline',prewire)]:stages[key]+=bool(seq)
  if success:
   category='success'
   assert wire and rx and up and any(t<=end for t,n in wire)
  elif not up:category='failure_no_rsu_uplink_out'
  elif not prerx:category='failure_no_rsu_data_in_before_deadline'
  elif not prewire:category='failure_returned_no_wireless_before_deadline'
  else:category='failure_after_wireless_before_deadline'
  stages[category]+=1
  before_end=[(t,n)for t,n in wire if t<=end]
  first=earliest(wire);last_before_end=max(before_end) if before_end else None
  first_rx=earliest(rx);first_up=earliest(up)
  row={k:q[k] for k in ['request_id','name','node_id','generation_rsu','send_ns','deadline_ns','terminal','end_ns']}
  row.update(category=category,uplink_out_count=len(up),rsu_data_in_count=len(rx),wireless_out_count=len(wire),wireless_out_before_deadline_count=len(prewire),obu_rx_count=len(obu),
   first_uplink_out_ns=first_up[0] if first_up else None,first_rsu_data_in_ns=first_rx[0] if first_rx else None,first_wireless_out_ns=first[0] if first else None,
   last_wireless_before_end_ns=last_before_end[0] if last_before_end else None,extra_count=len(q['extra']),extra_after_deadline_count=sum(t>deadline for t,_ in q['extra']),
   late_obu_data_in_count=sum(t>deadline for t,n in obu),late_data_app_diagnostics=sum(ev=='LATE_DATA' for ev,t in q['diagnostics']))
  for f in ['rtt_ms','send_to_first_rsu_data_ms','send_to_first_wireless_ms','last_wireless_to_delivery_ms','first_wireless_to_delivery_ms']:row[f]=None
  if first_rx:row['send_to_first_rsu_data_ms']=(first_rx[0]-send)/1e6
  if first:row['send_to_first_wireless_ms']=(first[0]-send)/1e6
  if success:
   row['rtt_ms']=(end-send)/1e6
   row['last_wireless_to_delivery_ms']=(end-last_before_end[0])/1e6
   row['first_wireless_to_delivery_ms']=(end-first[0])/1e6
  for f in ['rtt_ms','send_to_first_rsu_data_ms','send_to_first_wireless_ms','last_wireless_to_delivery_ms','first_wireless_to_delivery_ms']:
   if row[f] is not None:(success_fields if success else failure_fields)[f].append(row[f])
  flat.append(row)
 metrics=json.loads((p/'run-metrics.json').read_text());assert stages['generated']==int(meta['generated'])==metrics['generated']
 assert stages['app_success']==int(meta['satisfied'])==metrics['satisfied']
 assert sum(row['extra_count']for row in flat)==metrics['extra_data_app_attempts']
 assert abs(statistics.mean(success_fields['rtt_ms'])-metrics['mean_success_rtt_ms'])<1e-8
 assert sum(v for k,v in stages.items() if k.startswith('failure_'))+stages['success']==stages['generated']
 name='k{}-s{}-a{}'.format(meta['generated'],meta['seed_family'],meta['strategy'])
 with (OUT/(name+'-requests.csv')).open('w',newline='') as f:
  writer=csv.DictWriter(f,fieldnames=list(flat[0]));writer.writeheader();writer.writerows(flat)
 report={k:meta[k]for k in ['run_id','condition_id','seed_family','strategy','run_path','manifest_sha256']}
 report.update(source=m['source'],raw_hashes_verified=hashes,binary_sha256=m['binary']['sha256'],module_sha256=m['binary']['shared_libraries'][str(ROOT/'build/lib/libns3-dev-vndn-nn-rd-debug.so')],input_hashes=m['input_hashes'],model=m['model'],
   isr_percent=stages['app_success']/stages['generated']*100,stages=dict(stages),success_latency={f:stats(v)for f,v in success_fields.items()},failure_latency={f:stats(v)for f,v in failure_fields.items()},
   extra_total=sum(r['extra_count']for r in flat),extra_after_deadline=sum(r['extra_after_deadline_count']for r in flat),
   extra_requests_success=sum(r['extra_count']>0 and r['terminal']=='DATA'for r in flat),
   late_extra_requests_success=sum(r['extra_after_deadline_count']>0 and r['terminal']=='DATA'for r in flat),
   late_obu_data_in_total=sum(r['late_obu_data_in_count']for r in flat),late_obu_data_in_requests=sum(r['late_obu_data_in_count']>0 for r in flat),
   rsu_wireless_records_by_node=dict(wire_by_rsu),wireless_load={':'.join(k):v for k,v in loads.items()},origin_control_l3_counts=dict(controls),
   diagnostics=dict(diagnostics),failure_received_complete_data_before_deadline=sum(r['terminal']!='DATA'and any(t<=r['deadline_ns']for t,n in req[r['request_id']]['obu_rx'])for r in flat),
   request_csv=name+'-requests.csv',success_with_multiple_wireless_candidates=sum(r['terminal']=='DATA' and r['wireless_out_count']>1 for r in flat))
 print(name,report['isr_percent'],dict(stages),flush=True)
 return report,{r['request_id']:r for r in flat}
def compare(k,seed,a,b):
 ar,br=RUNS[(k,seed,a)],RUNS[(k,seed,b)]
 fields=['request_id','name','node_id','send_ns','deadline_ns']
 assert {q:tuple(r[x]for x in fields)for q,r in ar.items()}=={q:tuple(r[x]for x in fields)for q,r in br.items()}
 common=[q for q in ar if ar[q]['terminal']=='DATA' and br[q]['terminal']=='DATA']; onlya=[q for q in ar if ar[q]['terminal']=='DATA'and br[q]['terminal']!='DATA'];onlyb=[q for q in ar if br[q]['terminal']=='DATA'and ar[q]['terminal']!='DATA']
 return {'k':k,'seed':seed,'strategies':[a,b],'input_request_identity_equal':True,'common_success':len(common),'only_first_success':len(onlya),'only_second_success':len(onlyb),
 'common_latency':{str(s):{f:stats([data[q][f]for q in common if data[q][f]is not None])for f in ['rtt_ms','send_to_first_rsu_data_ms','send_to_first_wireless_ms','last_wireless_to_delivery_ms']}for s,data in [(a,ar),(b,br)]},
 'only_first_second_failure_categories':dict(Counter(br[q]['category']for q in onlya)),
 'only_second_first_failure_categories':dict(Counter(ar[q]['category']for q in onlyb))}
SEAL=json.loads((BATCH/'plan/source-seal.json').read_text());assert sha(BATCH/'plan/source.tar.gz')==SEAL['archive_sha256']
archived={}
with tarfile.open(BATCH/'plan/source.tar.gz') as archive:
 for path in ['contrib/vndn-nn-rd/apps/vndn-rsu.cc','contrib/vndn-nn-rd/apps/vndn-rsu.h','contrib/vndn-nn-rd/helper/vndn-experiment-recorder.cc','tools/experiments/summarize.py']:
  data=archive.extractfile(path).read();archived[path]={'archived_sha256':hashlib.sha256(data).hexdigest(),'current_sha256':sha(ROOT/path)}
REPORTS=[];RUNS={}
for meta in rows(TABLE):
 if meta['scene']=='circle' and meta['condition_id'] in ('n10-v30-k9000','n10-v30-k12000') and meta['strategy'] in ('1','3'):
  report,req=analyze(meta);REPORTS.append(report);RUNS[(int(meta['generated']),int(meta['seed_family']),int(meta['strategy']))]=req
assert len(REPORTS)==8
pairs=[compare(k,s,1,3)for k in [9000,12000]for s in [23001,23002]]
output={'schema_version':1,'scope':'All 8 original Circle runs: K9000/K12000 x seed23001/23002 x VTDF/NN. No new simulation or modifications to production/source/raw/figures. Posthoc descriptive diagnostic.',
 'limitations':['RSU outgoing business INTEREST via face258 is evidence of station uplink submission, not direct measurement of first Interest arrival. No RSU Interest RX trace exists in these formal runs.',
 'RSU face258 DATA RX is actual ingress from Router; wireless face257 OUT is L3 submission, not MAC acceptance/transmission. OBU complete DATA RX does not by itself imply terminal success.',
 'Wire-to-delivery intervals include contention, queueing, retries, fragmentation/reassembly; latest eligible output does not establish which output caused delivery.',
 'Funnel failure partitions classify first missing recorded predeadline step; no causal counterfactual. Two seeds are the independent run units, not requests.'],
 'source_seal':SEAL,'wireless_scope':'node 0..11 face257 only; server12/router13 face257 are wired and excluded','selected_archived_vs_current_sources':archived,'run_metrics_table_sha256':sha(TABLE),'runs':REPORTS,'paired_comparisons':pairs}
(OUT/'funnel-report.json').write_text(json.dumps(output,indent=2)+'\n')
print('DONE',OUT/'funnel-report.json',flush=True)
