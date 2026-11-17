"""Inclusive RTT, frozen ranking, and complete paired seed comparisons."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('power_analysis', Path(__file__).resolve().parents[1]/'spider_power_analysis.py')
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


def events():
    result = []
    for index, sent, terminal, delay in ((1,20.1,'DATA',.1),(2,24.9,'TIMEOUT',3)):
        base = dict(request_id=str(index), name='/content/'+str(index),
                    send_ns=round(sent*1e9), deadline_ns=round((sent+3)*1e9))
        result += [dict(base, event='GENERATED', time_ns=base['send_ns']),
                   dict(base, event=terminal, time_ns=round((sent+delay)*1e9))]
    return result


class PowerAnalysisTests(unittest.TestCase):
    def test_timeout_is_actual_wait_and_stays_in_generation_bin(self):
        rows = analysis.bin_events(events(), 20_000_000_000, 30_000_000_000)
        self.assertEqual(rows[0]['generated'], 2)
        self.assertEqual(rows[0]['mean_rtt_ms'], 1550)
        self.assertEqual(rows[0]['mean_success_rtt_ms'], 100)
        self.assertEqual(rows[0]['timeout'], 1)
        self.assertIsNone(rows[1]['mean_rtt_ms'])

    def test_no_duplicate_missing_or_late_success_is_accepted(self):
        cases = [events()+[events()[1]], events()[:-1]]
        late = events()
        late[1]['time_ns'] = late[1]['deadline_ns']+1
        cases.append(late)
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                analysis.bin_events(rows, 20_000_000_000, 30_000_000_000)

    def test_high_plateau_requires_consecutive_high_close_bins(self):
        self.assertEqual(analysis.high_plateau([1919,1920,1921,1919]), 20)
        self.assertEqual(analysis.high_plateau([300,301,300,300]), 0)
        self.assertEqual(analysis.high_plateau([1900,1921,1910,1905]), 15)

    def test_ranking_ties_are_not_wins(self):
        self.assertTrue(analysis.ordered([1000,800,600,400]))
        self.assertFalse(analysis.ordered([1000,800,600,600]))
        self.assertFalse(analysis.ordered([1000,800,600,599.9]))

    def test_missing_strategy_cannot_enter_selection(self):
        with self.assertRaisesRegex(ValueError, 'four strategies'):
            analysis.compare_power([dict(strategy=0, seed=1)], 19)

    def test_missing_seed_or_duplicate_is_not_averaged_away(self):
        runs = [dict(strategy=a, seed=1) for a in range(4)]
        runs.append(dict(strategy=0, seed=2))
        with self.assertRaisesRegex(ValueError, 'paired seeds'):
            analysis.compare_power(runs, 19)
        runs = [dict(strategy=a, seed=1) for a in range(4)]
        runs.append(copy.deepcopy(runs[0]))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            analysis.compare_power(runs, 19)

    def test_3d_rtt_label_is_inside_tight_export(self):
        import matplotlib.figure
        groups = []
        for strategy in range(4):
            bins = [dict(bin_start_s=20+5*i, generated=250, success=200, timeout=50,
                         success_sum_ns=((1900+30*i+50*strategy)*250-150000)*1_000_000,
                         timeout_sum_ns=150_000_000_000,
                         mean_rtt_ms=1900+30*i+50*strategy, between_seed_sd_ms=0,
                         association_events=0) for i in range(24)]
            groups.append(dict(strategy=strategy,bins=bins,full=analysis.window_stats(bins),
                               focus=analysis.window_stats(bins[6:14])))
        comparison = dict(power_dbm=19,strategies=groups,seeds=[93001],meets_goal=False)
        records = [dict(r,stage='confirmation',seed=93001,power_dbm=19) for r in groups]
        checked = []
        def inspect(fig,path,**kwargs):
            if not str(path).endswith('-3d.png'):
                return
            ax = fig.axes[0]
            zticks = list(zip(ax.get_zticks(),ax.get_zticklabels()))
            fig.canvas.draw()
            renderer = fig.canvas.get_renderer()
            box = fig.get_tightbbox(renderer).transformed(fig.dpi_scale_trans)
            labels = [t for t in [ax.zaxis.label]+list(ax.texts) if t.get_text()=='Mean RTT (ms)']
            self.assertEqual(len(labels),1)
            extent = labels[0].get_window_extent(renderer)
            self.assertTrue(box.contains(extent.x0,extent.y0) and box.contains(extent.x1,extent.y1))
            lower, upper = ax.get_zlim()
            tick_right = max(t.get_window_extent(renderer).x1
                             for value,t in zticks
                             if t.get_visible() and lower<=value<=upper)
            self.assertGreaterEqual(extent.x0-tick_right,8,
                                    'RTT title must not overlap four-digit z-axis ticks')
            checked.append(True)
        with tempfile.TemporaryDirectory() as temp, patch.object(matplotlib.figure.Figure,'savefig',inspect):
            root = Path(temp)
            (root/'analysis').mkdir()
            analysis.render(root,[comparison],comparison,records,19)
        self.assertEqual(checked,[True])


if __name__ == '__main__':
    unittest.main()
