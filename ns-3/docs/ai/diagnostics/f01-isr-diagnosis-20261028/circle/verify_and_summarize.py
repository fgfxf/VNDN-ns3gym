"""Independent checks of derived request CSVs and compact human-readable tables."""
import csv,json,hashlib
from collections import Counter
from pathlib import Path
P=Path(__file__).resolve().parent
j=json.loads((P/'funnel-report.json').read_text());table=[];verified=[]
for run in j['runs']:
 with (P/run['request_csv']).open() as f:rs=list(csv.DictReader(f))
 assert len(rs)==run['stages']['generated']
 assert len({r['request_id']for r in rs})==len(rs)
 success=[r for r in rs if r['terminal']=='DATA']
 assert len(success)==run['stages']['app_success']
 assert all(int(r['end_ns'])<=int(r['deadline_ns'])for r in success)
 assert sum(int(r['extra_after_deadline_count'])for r in rs)==run['extra_after_deadline']
 assert all(r['terminal']!='DATA'for r in rs if int(r['extra_after_deadline_count']))
 assert sum(bool(r['first_wireless_out_ns'])and int(r['first_wireless_out_ns'])<=int(r['deadline_ns'])for r in rs)==run['stages']['wireless_out_before_deadline']
 assert run['failure_received_complete_data_before_deadline']==0
 category=Counter(r['category']for r in rs)
 assert sum(category.values())==len(rs)
 for c,n in category.items():assert run['stages'][c]==n
 verified.append({'request_csv':run['request_csv'],'requests':len(rs),'status':'PASS'})
 s=run['stages'];lat=run['success_latency']
 table.append({'k':s['generated'],'seed':run['seed_family'],'strategy':run['strategy'],'isr_percent':run['isr_percent'],
 'rsu_uplink_unique':s['rsu_uplink_out'],'returned_to_rsu_unique':s['rsu_data_in'],'wireless_before_deadline_unique':s['wireless_out_before_deadline'],'satisfied':s['app_success'],
 'no_uplink':s.get('failure_no_rsu_uplink_out',0),'returned_no_wireless_before_deadline':s.get('failure_returned_no_wireless_before_deadline',0),
 'failed_after_wireless_before_deadline':s.get('failure_after_wireless_before_deadline',0),
 'success_over_wireless_before_deadline_percent':s['app_success']/s['wireless_out_before_deadline']*100,
 'success_rtt_ms':lat['rtt_ms']['mean_ms'],'last_wireless_to_delivery_ms':lat['last_wireless_to_delivery_ms']['mean_ms'],
 'extra_total':run['extra_total'],'extra_after_deadline':run['extra_after_deadline'],'late_obu_data_in_requests':run['late_obu_data_in_requests']})
with(P/'summary.csv').open('w',newline='')as f:
 w=csv.DictWriter(f,fieldnames=list(table[0]));w.writeheader();w.writerows(table)
(P/'derived-verification.json').write_text(json.dumps({'checks':verified,'requests':sum(x['requests']for x in verified),'status':'PASS'},indent=2)+'\n')
files=[x for x in P.iterdir()if x.is_file()and x.name!='archive-index.json']
(P/'archive-index.json').write_text(json.dumps({'files':[{ 'path':x.name,'bytes':x.stat().st_size,'sha256':hashlib.sha256(x.read_bytes()).hexdigest()}for x in sorted(files)]},indent=2)+'\n')
print('PASS:',len(verified),'runs;',sum(x['requests']for x in verified),'requests')
