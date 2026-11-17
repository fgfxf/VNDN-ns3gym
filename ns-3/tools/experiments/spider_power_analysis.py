"""Read sealed runs; retain actual timeout wait, all seeds, and unmodified bins."""
import csv
import hashlib
import json
from pathlib import Path
import statistics

LABELS = ('Naive NDN', 'VTDF', 'RTVTDF', 'TKAN-PDF')
COLORS = ('#888888', '#e69f00', '#009e73', '#9467bd')


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def bin_events(events, start_ns, end_ns, bin_ns=5_000_000_000):
    generated, terminal = {}, {}
    for row in events:
        kind = row['event']
        if kind in ('DUPLICATE_DATA', 'LATE_DATA', 'POST_TERMINAL_DATA'):
            continue
        if kind not in ('GENERATED', 'DATA', 'TIMEOUT'):
            raise ValueError('Unexpected terminal/event in power experiment: '+kind)
        destination = generated if kind == 'GENERATED' else terminal
        identity = row['request_id']
        if identity in destination:
            raise ValueError('Duplicate request event')
        destination[identity] = row
    if not generated or generated.keys() != terminal.keys():
        raise ValueError('Missing request terminal or generation')
    if (end_ns-start_ns) % bin_ns:
        raise ValueError('Window must contain complete bins')
    bins = [dict(bin_start_s=(start_ns+i*bin_ns)/1e9, generated=0, success=0, timeout=0,
                 success_sum_ns=0, timeout_sum_ns=0) for i in range((end_ns-start_ns)//bin_ns)]
    for identity, initial in generated.items():
        row = terminal[identity]
        sent, deadline, ended = (int(row[k]) for k in ('send_ns','deadline_ns','time_ns'))
        if (sent != int(initial['send_ns']) or sent != int(initial['time_ns']) or
                deadline != int(initial['deadline_ns']) or row['name'] != initial['name'] or
                not start_ns <= sent < end_ns or deadline != sent+3_000_000_000 or
                not sent <= ended <= deadline or (row['event']=='TIMEOUT' and ended != deadline)):
            raise ValueError('Invalid request lifetime or terminal')
        target = bins[(sent-start_ns)//bin_ns]
        target['generated'] += 1
        if row['event'] == 'DATA':
            target['success'] += 1
            target['success_sum_ns'] += ended-sent
        else:
            target['timeout'] += 1
            target['timeout_sum_ns'] += ended-sent
    for row in bins:
        row['mean_rtt_ms'] = ((row['success_sum_ns']+row['timeout_sum_ns'])/row['generated']/1e6
                              if row['generated'] else None)
        row['mean_success_rtt_ms'] = row['success_sum_ns']/row['success']/1e6 if row['success'] else None
    return bins


def high_plateau(values):
    longest = 0
    for first in range(len(values)):
        for last in range(first+1, len(values)+1):
            window = values[first:last]
            if min(window) >= 1000 and max(window)-min(window) <= 20:
                longest = max(longest, 5*len(window))
    return longest


def window_stats(bins):
    counts = sum(r['generated'] for r in bins)
    if not counts or any(r['mean_rtt_ms'] is None for r in bins):
        raise ValueError('Missing power-scan time bin')
    values = [r['mean_rtt_ms'] for r in bins]
    return dict(mean_rtt_ms=sum(r['success_sum_ns']+r['timeout_sum_ns'] for r in bins)/counts/1e6,
        timeout_fraction=sum(r['timeout'] for r in bins)/counts,
        temporal_sd_ms=statistics.pstdev(values), peak_to_peak_ms=max(values)-min(values),
        longest_high_plateau_s=high_plateau(values))


def analyze_run(path, power, seed, strategy):
    path = Path(path)
    manifest, config = read(path/'manifest.json'), read(path/'experiment.json')
    if (manifest['status'] != 'complete' or config['strategy'] != strategy or
            config['scenario'] != 'spidermap' or config['seeds']['sumo_seed'] != seed or
            config.get('wifi_tx_power_dbm') != power):
        raise ValueError('Completed run identity mismatch')
    for filename, digest in manifest['artifact_hashes'].items():
        if sha(path/filename) != digest:
            raise ValueError('Sealed artifact changed: '+str(path/filename))
    with (path/'raw/request-events.csv').open() as stream:
        events = list(csv.DictReader(stream))
    bins = bin_events(events, 20_000_000_000, 140_000_000_000)
    if len(bins) != 24 or any(r['generated'] != 250 for r in bins):
        raise ValueError('Expected exactly 6000 requests and 250 per 5-second bin')
    mobility, associations = [], [0]*24
    with (path/'raw/mobility-events.csv').open() as stream:
        for row in csv.DictReader(stream):
            when = int(row['time_ns'])
            if row['event'] == 'SAMPLE':
                mobility.append(tuple(row[k] for k in ('time_ns','vehicle_id','x','y','speed_mps')))
            if row['event']=='ASSOCIATION' and 20e9 <= when < 140e9:
                associations[(when-20_000_000_000)//5_000_000_000] += 1
    for row,count in zip(bins, associations):
        row['association_events'] = count
    return dict(path=str(path), manifest_sha256=sha(path/'manifest.json'), power_dbm=power,
        seed=seed, strategy=strategy, bins=bins, full=window_stats(bins),
        focus=window_stats([r for r in bins if 50 <= r['bin_start_s'] < 90]),
        mobility_sha256=hashlib.sha256(json.dumps(mobility).encode()).hexdigest(),
        request_plan_sha256=sha(config['request_plan']), model=manifest['model'])


def ordered(values):
    return all(values[i]-values[i+1] > 1 for i in range(3))


def compare_power(runs, power):
    if {r['strategy'] for r in runs} != set(range(4)):
        raise ValueError('Need all four strategies')
    identities = [(r['strategy'],r['seed']) for r in runs]
    if len(set(identities)) != len(identities):
        raise ValueError('Cannot average duplicate strategy/seed runs')
    seeds = sorted({r['seed'] for r in runs})
    if any(sorted(r['seed'] for r in runs if r['strategy']==a) != seeds for a in range(4)):
        raise ValueError('Need identical paired seeds for every strategy')
    for seed in seeds:
        group = [r for r in runs if r['seed']==seed]
        if any(len({r[k] for r in group}) != 1 for k in ('mobility_sha256','request_plan_sha256')):
            raise ValueError('Strategy inputs or recorded positions differ')
    aggregate = []
    for strategy in range(4):
        group = [r for r in runs if r['strategy']==strategy]
        bins = []
        for i in range(24):
            row = dict(bin_start_s=20+5*i)
            for key in ('generated','success','timeout','success_sum_ns','timeout_sum_ns','association_events'):
                row[key] = sum(r['bins'][i][key] for r in group)
            row['mean_rtt_ms'] = (row['success_sum_ns']+row['timeout_sum_ns'])/row['generated']/1e6
            row['between_seed_sd_ms'] = statistics.stdev(r['bins'][i]['mean_rtt_ms'] for r in group) if len(group)>1 else 0
            bins.append(row)
        item = dict(strategy=strategy, bins=bins, full=window_stats(bins),
                    focus=window_stats([r for r in bins if 50 <= r['bin_start_s'] < 90]))
        for window in ('full','focus'):
            item[window]['between_seed_mean_sd_ms'] = statistics.stdev(r[window]['mean_rtt_ms'] for r in group) if len(group)>1 else 0
        aggregate.append(item)
    windows = {}
    for key, indices in (('full', range(24)), ('focus', range(6,14))):
        means = [r[key]['mean_rtt_ms'] for r in aggregate]
        windows[key] = dict(means_ms=means, mean_order=ordered(means),
            adjacent_order_pairs=sum(means[i]-means[i+1]>1 for i in range(3)),
            strict_bin_order_fraction=sum(ordered([r['bins'][i]['mean_rtt_ms'] for r in aggregate]) for i in indices)/len(indices))
    coverage_gate = all(r['focus']['timeout_fraction'] <= .30 and
                        r['focus']['longest_high_plateau_s'] <= 15 for r in aggregate)
    variation_gate = all(r['focus']['temporal_sd_ms'] >= 10 and
                         r['focus']['peak_to_peak_ms'] >= 50 for r in aggregate)
    meets = coverage_gate and variation_gate and all(w['mean_order'] and
                w['strict_bin_order_fraction'] > .5 for w in windows.values())
    score = [int(meets), int(coverage_gate), sum(w['adjacent_order_pairs'] for w in windows.values()),
             min(w['strict_bin_order_fraction'] for w in windows.values()),
             -max(r['focus']['longest_high_plateau_s'] for r in aggregate),
             -aggregate[3]['focus']['mean_rtt_ms'], -aggregate[3]['full']['mean_rtt_ms'], -power]
    return dict(power_dbm=power, seeds=seeds, strategies=aggregate, windows=windows,
        coverage_gate=coverage_gate, variation_gate=variation_gate, meets_goal=meets, selection_score=score,
        per_seed_orders={str(seed):{w:ordered([next(r for r in runs if r['seed']==seed and r['strategy']==a)[w]['mean_rtt_ms'] for a in range(4)])
                                      for w in ('full','focus')} for seed in seeds})


def write_csv(path, rows):
    with Path(path).open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def render(root, comparisons, confirmation, records, selected):
    """All outputs are new campaign artifacts; never alter the historical plots."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    plt.rcParams.update({'font.family':'serif', 'font.serif':['Liberation Serif'], 'font.size':11})
    root = Path(root)
    out = root/'figures'
    out.mkdir(exist_ok=True)
    files = []

    def save(fig, name):
        for suffix in ('png','svg','pdf'):
            fig.savefig(out/(name+'.'+suffix), dpi=180, bbox_inches='tight')
        plt.close(fig)
        files.append(name)

    def lines(ax, groups, title, ylim=None, spread=False):
        for group in groups:
            a = group['strategy']
            xs = [r['bin_start_s']+2.5 for r in group['bins']]
            ys = np.array([r['mean_rtt_ms'] for r in group['bins']])
            ax.plot(xs, ys, color=COLORS[a], marker=('o','s','^','D')[a], ms=3,
                    label=LABELS[a], linewidth=1.3)
            if spread:
                sd = np.array([r['between_seed_sd_ms'] for r in group['bins']])
                ax.fill_between(xs, np.maximum(0,ys-sd), ys+sd, color=COLORS[a], alpha=.10)
        ax.set(title=title, xlabel='Interest generation time (s)', ylabel='Mean RTT (ms)', xlim=(20,140))
        if ylim:
            ax.set_ylim(*ylim)
        ax.grid(alpha=.18)

    cols = 3
    rows = (len(comparisons)+cols-1)//cols
    fig, axes = plt.subplots(rows,cols,figsize=(15,4*rows),squeeze=False)
    upper = max(b['mean_rtt_ms'] for c in comparisons for g in c['strategies'] for b in g['bins'])*1.08
    for ax, comparison in zip(axes.flat, comparisons):
        lines(ax, comparison['strategies'], '{} dBm (development seeds)'.format(comparison['power_dbm']), (0,upper))
    for ax in list(axes.flat)[len(comparisons):]:
        ax.set_visible(False)
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='upper center',ncol=4)
    fig.tight_layout(rect=(0,0,1,.95))
    save(fig,'power-scan-overview')
    for comparison in comparisons:
        fig, ax = plt.subplots(figsize=(9,5))
        lines(ax,comparison['strategies'],'Spider — {} dBm, development mean'.format(comparison['power_dbm']))
        ax.legend(ncol=4,fontsize=9)
        save(fig,'development-'+str(comparison['power_dbm']).replace('.','p')+'dBm')
    fig, ax = plt.subplots(figsize=(10,5))
    lines(ax, confirmation['strategies'],'Spider — {} dBm, five independent seeds (mean ± SD)'.format(selected),spread=True)
    ax.legend(ncol=4)
    save(fig,'confirmation-mean-rtt')
    fig = plt.figure(figsize=(10,6))
    ax = fig.add_subplot(111,projection='3d')
    for group in confirmation['strategies']:
        a = group['strategy']
        ax.plot([r['bin_start_s']+2.5 for r in group['bins']],[a]*24,
                [r['mean_rtt_ms'] for r in group['bins']], color=COLORS[a],marker='o',ms=3,label=LABELS[a])
    ax.set(xlabel='Interest generation time (s)',
           yticks=range(4),yticklabels=LABELS,title='Spider — {} dBm, independent seed mean'.format(selected))
    ax.text2D(1.15,.55,'Mean RTT (ms)',transform=ax.transAxes,rotation=90,va='center')
    ax.set_zlim(bottom=min(b['mean_rtt_ms'] for g in confirmation['strategies'] for b in g['bins']))
    ax.view_init(elev=25,azim=-60)
    save(fig,'confirmation-mean-rtt-3d')
    for seed in confirmation['seeds']:
        fig, ax = plt.subplots(figsize=(9,5))
        groups = sorted((r for r in records if r['stage']=='confirmation' and r['seed']==seed),key=lambda r:r['strategy'])
        lines(ax,groups,'Spider — {} dBm, seed {}'.format(selected,seed))
        ax.legend(ncol=4,fontsize=9)
        save(fig,'confirmation-seed-'+str(seed))
    table = []
    for stage, comparisons_for_stage in (('development',comparisons),('confirmation',[confirmation])):
        for comparison in comparisons_for_stage:
            for group in comparison['strategies']:
                for window in ('full','focus'):
                    table.append(dict(stage=stage,power_dbm=comparison['power_dbm'],strategy=LABELS[group['strategy']],
                        window=window, **group[window]))
    write_csv(root/'analysis/power-summary.csv',table)
    write_csv(root/'analysis/time-bins.csv',[dict(stage=r['stage'],power_dbm=r['power_dbm'],seed=r['seed'],strategy=r['strategy'],**b) for r in records for b in r['bins']])
    markup = ['<!doctype html><meta charset="utf-8"><title>Spider power scan</title>',
              '<style>body{max-width:1100px;margin:auto;font-family:serif}img{width:100%}td,th{padding:6px;border:1px solid #ccc}</style>',
              '<h1>Spider transmit-power scan</h1>',
              '<p>Selected on development seeds: {} dBm. Independent confirmation meets all preregistered goals: {}.</p>'.format(selected,confirmation['meets_goal']),
              '<p>Inclusive mean RTT; 3-second timeouts; 5-second bins by generation time. Fixed existing neural checkpoint. All seeds retained.</p>',
              '<p><a href="../analysis/power-summary.csv">Summary CSV</a> · <a href="../analysis/time-bins.csv">All bins CSV</a> · <a href="../analysis/results.json">Results and source paths</a> · <a href="../plan/preregistered-plan.json">Frozen criteria</a></p>']
    markup += ['<h2>'+name+'</h2><a href="'+name+'.pdf">PDF</a> · <a href="'+name+'.svg">SVG</a><img src="'+name+'.png">' for name in files]
    (out/'index.html').write_text('\n'.join(markup),encoding='utf-8')
    return files
