#!/usr/bin/env python3.8
"""Serial, resumable single-variable Spider power scan with held-out confirmation."""
import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import signal
import time

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = ROOT/'data/experiments/spider-power-20261103'
DESIGN = ROOT/'docs/ai/records/spider-power-20261103-plan.json'


def module(name):
    spec = importlib.util.spec_from_file_location('_power_'+name, Path(__file__).with_name(name+'.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


runner = module('run_experiment')
generator = module('generate_inputs')
support = module('followup_campaign')
analysis = module('spider_power_analysis')
read, write, sha = support.read, support.write, support.sha


def tasks(stage, powers, seeds):
    return [dict(id='{}-p{}-s{}-a{}'.format(stage,format(p,'.15g').replace('.','p'),s,a),
                 stage=stage,power_dbm=p,seed=s,strategy=a)
            for p in powers for s in seeds for a in range(4)]


def choose(comparisons):
    if not comparisons:
        raise ValueError('No complete development comparisons')
    return max(comparisons,key=lambda c:c['selection_score'])


def fine_powers(comparison):
    return [] if comparison['meets_goal'] else [comparison['power_dbm']-.5, comparison['power_dbm']+.5]


def initialize(root):
    path = root/'plan/runtime.json'
    if path.exists():
        return read(path)
    design = read(DESIGN)
    models, dependencies, provenance = support.bind_models(ROOT/'data/experiments/retrain-quick-20261021')
    excluded = set(provenance['spidermap']['excluded_development_seeds'])
    if excluded.intersection(design['confirmation_seeds']) or set(design['development_seeds']).intersection(design['confirmation_seeds']):
        raise ValueError('Confirmation seeds overlap training/development')
    model = models['spidermap']
    if model['sha256'] != design['model_sha256'] or Path(model['path']) != ROOT/design['model']:
        raise ValueError('Power scan must use the approved fixed checkpoint')
    dependencies[str(DESIGN)] = sha(DESIGN)
    for seed in design['development_seeds']+design['confirmation_seeds']:
        directory = root/'inputs'/str(seed)
        template = directory/'experiment-template.json'
        if not directory.exists():
            generator.generate_inputs(scenario='spidermap',output_dir=directory,vehicles=10,
                speed_kmh=30,requests=6000,measurement_start=20,measurement_duration=120,
                drain_seconds=3.5,seed=seed,ns3_root=ROOT)
        _, hashes = runner.prepare_inputs(template)
        dependencies.update(hashes)
    write(root/'plan/preregistered-plan.json',design)
    dependencies[str(root/'plan/preregistered-plan.json')] = sha(root/'plan/preregistered-plan.json')
    runtime = dict(schema_version=1,created_utc=runner.utc_now(),design=design,model=model,
        model_provenance=provenance['spidermap'],dependencies=dependencies,
        source=runner.source_snapshot(ROOT),
        binary=support.clean_binary(runner.binary_evidence(ROOT,'vndn-spidermap-simulator')))
    write(path,runtime)
    return runtime


def verify_runtime(runtime):
    runner.verify_hashes(runtime['dependencies'],'Power scan frozen input/model/design')
    if runner.source_snapshot(ROOT)['sha256'] != runtime['source']['sha256']:
        raise ValueError('Source changed after the power scan was frozen')
    if support.clean_binary(runner.binary_evidence(ROOT,'vndn-spidermap-simulator')) != runtime['binary']:
        raise ValueError('Power scan binary or linked libraries changed')


def make_config(root, task):
    template, _ = runner.prepare_inputs(root/'inputs'/str(task['seed'])/'experiment-template.json')
    template.update(wifi_tx_power_dbm=task['power_dbm'],require_formal_contract=True,
                    validation_only=False,training_snapshots=False)
    path = root/'configs'/('p'+format(task['power_dbm'],'.15g').replace('.','p'))/(str(task['seed'])+'.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if read(path) != template:
            raise ValueError('Existing power config differs')
    else:
        write(path,template)
    return path


def recover(root, task, runtime):
    destination = root/'plan/tasks'/(task['id']+'.json')
    completed = []
    for path in sorted((root/'runs'/task['id']).glob('attempt-*/*/manifest.json')):
        manifest = read(path)
        if manifest['status'] != 'complete':
            continue
        if (manifest['source']['sha256'] != runtime['source']['sha256'] or
                support.clean_binary(manifest['binary']) != runtime['binary'] or
                manifest['model'] != (runtime['model'] if task['strategy']==3 else None)):
            raise ValueError('Completed run runtime/model differs')
        runner.verify_hashes(manifest['input_hashes'],'Completed power run input')
        runner.validate_radio_output(path.parent,read(path.parent/'experiment.json'))
        row = analysis.analyze_run(path.parent,task['power_dbm'],task['seed'],task['strategy'])
        row.update(stage=task['stage'],task_id=task['id'])
        completed.append(row)
    if len(completed)>1:
        raise ValueError('Multiple completed attempts for one task')
    if completed:
        if destination.exists() and read(destination) != completed[0]:
            raise ValueError('Completed task record changed')
        write(destination,completed[0])
        return completed[0]
    if destination.exists():
        raise ValueError('Task index exists without its completed raw run')
    return None


def comparisons_for(records, stage):
    return [analysis.compare_power([r for r in records if r['stage']==stage and r['power_dbm']==power],power)
            for power in sorted({r['power_dbm'] for r in records if r['stage']==stage})]


def execute(root):
    if ROOT/'data/experiments' not in root.parents or root.name in ('quick-fixed-model-20261022','retrain-quick-20261021'):
        raise ValueError('Use a new campaign directory under data/experiments')
    for name in ('plan/tasks','analysis','runs','configs'):
        (root/name).mkdir(parents=True,exist_ok=True)
    with (root/'plan/campaign.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        old = read(root/'plan/state.json') if (root/'plan/state.json').exists() else {}
        accumulated = old.get('elapsed_seconds',0)
        started = time.monotonic()
        identity = support.process_identity(os.getpid())
        state = dict(status='initializing',stage='prepare',pid=os.getpid(),start_token=identity[1],
                     completed=0,total=60,maximum_total=76,current=None,started_utc=runner.utc_now())
        cancelled, heartbeat = [], [0]
        previous = {}

        def update(force=False):
            now = time.monotonic()
            if force or now-heartbeat[0]>=5:
                state.update(updated_utc=runner.utc_now(),elapsed_seconds=accumulated+now-started)
                write(root/'plan/state.json',state)
                heartbeat[0] = now

        def check():
            update()
            if cancelled:
                raise KeyboardInterrupt('Stopped immediately; completed runs retained')

        for sig in (signal.SIGINT,signal.SIGTERM):
            previous[sig] = signal.signal(sig,lambda number,frame:cancelled.append(number))
        records = []
        try:
            update(True)
            runtime = initialize(root)
            verify_runtime(runtime)
            design = runtime['design']

            def run_tasks(batch):
                for task in batch:
                    check()
                    state.update(status='running',stage=task['stage'],current=task)
                    update(True)
                    record = recover(root,task,runtime)
                    if record is None:
                        verify_runtime(runtime)
                        config = make_config(root,task)
                        attempts = sorted((root/'runs'/task['id']).glob('attempt-*'))
                        number = len(attempts)+1
                        if number>2:
                            raise ValueError('Two failed attempts already retained: '+task['id'])
                        attempt = root/'runs'/task['id']/('attempt-{:03d}'.format(number))
                        attempt.mkdir(parents=True,exist_ok=False)
                        args = ['--config',str(config),'--output-root',str(attempt),'--block-id',task['id'],
                            '--strategy',str(task['strategy']),'--no-build','--require-formal-contract',
                            '--timeout','900','--python','/usr/bin/python3.8']
                        if task['strategy']==3:
                            args += ['--model-file',runtime['model']['path']]
                        code = runner._run_block(args,ROOT,check)
                        check()
                        record = recover(root,task,runtime)
                        if code or record is None:
                            raise ValueError('Run failed; inspect preserved attempt before resume: '+task['id'])
                    records.append(record)
                    state.update(completed=len(records),current=None)
                    update(True)
                    print('completed',len(records),'/',state['total'],task['id'],
                          'RTT full/focus',round(record['full']['mean_rtt_ms'],3),
                          round(record['focus']['mean_rtt_ms'],3),flush=True)

            run_tasks(tasks('coarse',design['coarse_powers_dbm'],design['development_seeds']))
            coarse = comparisons_for(records,'coarse')
            write(root/'analysis/coarse.json',coarse)
            # 13 dBm is the reference, not an eligible new operating point.
            best = choose([c for c in coarse if c['power_dbm'] != 13])
            fine = fine_powers(best)
            decision = dict(coarse_candidate_dbm=best['power_dbm'],fine_powers_dbm=fine,
                            coarse_meets_goal=best['meets_goal'],selection_score=best['selection_score'])
            decision_path = root/'plan/coarse-decision.json'
            if decision_path.exists() and read(decision_path) != decision:
                raise ValueError('Frozen coarse decision differs')
            write(decision_path,decision)
            state['total'] = 60+8*len(fine)
            update(True)
            run_tasks(tasks('fine',fine,design['development_seeds']))
            comparisons = sorted(coarse+comparisons_for(records,'fine'),key=lambda c:c['power_dbm'])
            selected = choose([c for c in comparisons if c['power_dbm'] != 13])
            selection = dict(selected_power_dbm=selected['power_dbm'],development_meets_goal=selected['meets_goal'],
                selection_score=selected['selection_score'],confirmation_seeds=design['confirmation_seeds'],
                development_manifest_hashes={r['path']:r['manifest_sha256'] for r in records})
            selection_path = root/'plan/selection.json'
            if selection_path.exists() and read(selection_path) != selection:
                raise ValueError('Frozen selection differs; cannot retune on confirmation results')
            write(selection_path,selection)
            run_tasks(tasks('confirmation',[selected['power_dbm']],design['confirmation_seeds']))
            confirmation = comparisons_for(records,'confirmation')[0]
            # Power cannot change SUMO positions or request times, even across stages.
            for seed in {r['seed'] for r in records}:
                for key in ('mobility_sha256','request_plan_sha256'):
                    if len({r[key] for r in records if r['seed']==seed}) != 1:
                        raise ValueError('Single-variable pairing differs across powers: '+key)
            state.update(status='running',stage='figures',current=None)
            update(True)
            results = dict(status='complete',selected_power_dbm=selected['power_dbm'],
                development_meets_goal=selected['meets_goal'],confirmation_meets_goal=confirmation['meets_goal'],
                comparisons=comparisons,confirmation=confirmation,runs=records,
                actual_new_runs=len(records),model=runtime['model'],definition=design['goal_definition'])
            write(root/'analysis/results.json',results)
            figures = analysis.render(root,comparisons,confirmation,records,selected['power_dbm'])
            verify_runtime(runtime)
            artifacts = {str(p.relative_to(root)):sha(p) for folder in ('analysis','figures')
                         for p in (root/folder).rglob('*') if p.is_file()}
            write(root/'plan/completion.json',dict(status='complete',runs=len(records),figures=figures,
                artifact_hashes=artifacts,selected_power_dbm=selected['power_dbm'],
                confirmation_meets_goal=confirmation['meets_goal']))
            state.update(status='complete',stage='complete',selected_power_dbm=selected['power_dbm'],
                         confirmation_meets_goal=confirmation['meets_goal'])
            update(True)
            return 0
        except (Exception,KeyboardInterrupt) as error:
            state.update(status='interrupted' if isinstance(error,KeyboardInterrupt) else 'failed',error=str(error))
            update(True)
            print(state['status'],str(error),flush=True)
            return 130 if isinstance(error,KeyboardInterrupt) else 1
        finally:
            for sig, handler in previous.items():
                signal.signal(sig,handler)


def status(root,watch=False):
    while True:
        path = root/'plan/state.json'
        if not path.exists():
            print('Not started')
            return
        state = read(path)
        print('{} | {} | {}/{} | elapsed {:.1f} min | {}'.format(state['status'],state['stage'],
            state['completed'],state['total'],state['elapsed_seconds']/60,
            state['current']['id'] if state.get('current') else '-'),flush=True)
        if state.get('error'):
            print(state['error'])
        if not watch or state['status'] in ('complete','failed','interrupted'):
            return
        time.sleep(5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('all','resume','status','stop'))
    parser.add_argument('--root',type=Path,default=DEFAULT_ROOT)
    parser.add_argument('--watch',action='store_true')
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command=='status':
        status(root,args.watch)
        return 0
    if args.command=='stop':
        state = read(root/'plan/state.json')
        if state['status'] not in ('initializing','running') or support.process_identity(state['pid']) != (state['pid'],state['start_token']):
            raise ValueError('No matching active power-scan process')
        os.kill(state['pid'],signal.SIGTERM)
        return 0
    return execute(root)


if __name__ == '__main__':
    raise SystemExit(main())
