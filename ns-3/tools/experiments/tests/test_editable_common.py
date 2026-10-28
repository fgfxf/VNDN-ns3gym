import importlib.util
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / 'editable_plot_common.py'
SPEC = importlib.util.spec_from_file_location('editable_plot_common_test', MODULE)
common = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(common)


class EditableCommonTests(unittest.TestCase):
    def test_import_has_no_output_and_run_updates_related_in_other_cwd(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name) / 'plots with spaces'
            folder.mkdir()
            base = common.make_script('single', 'FIGSIZE = (2, 2)\nDPI = 30',
                'def draw():\n    fig, ax = plt.subplots(figsize=FIGSIZE)\n    ax.plot(DATA)\n    return fig',
                'DATA = [1, 2, 3]', related=('combined',))
            combined = common.make_script('combined', 'FIGSIZE = (2, 2)\nDPI = 30',
                'def draw():\n    numbers = load_plot("single.py")["DATA"]\n    fig, ax = plt.subplots(figsize=FIGSIZE)\n    ax.plot(numbers)\n    return fig', 'DATA = None')
            (folder / 'single.py').write_text(base)
            (folder / 'combined.py').write_text(combined)
            loaded = runpy.run_path(str(folder / 'single.py'))
            self.assertEqual(loaded.get('DATA'), [1, 2, 3])
            self.assertEqual(list(folder.glob('*.png')), [])
            subprocess.run([sys.executable, str(folder / 'single.py')], cwd=name,
                           check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for stem in ('single', 'combined'):
                for ext in ('png', 'svg', 'pdf'):
                    self.assertGreater((folder / (stem + '.' + ext)).stat().st_size, 50)
            first = (folder / 'combined.png').read_bytes()
            (folder / 'single.py').write_text(base.replace('DATA = [1, 2, 3]', 'DATA = [1, 3, 1]'))
            subprocess.run([sys.executable, str(folder / 'single.py')], cwd=name,
                           check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertNotEqual(first, (folder / 'combined.png').read_bytes())
            self.assertEqual(list(Path(name).glob('*.png')), [])

    def test_literals_preserve_missing_and_small_values(self):
        import ast
        values = {'a': [None, 0., 1.2345678901234567, 1e-12], 'b': [100., -3.]}
        self.assertEqual(ast.literal_eval(common.literal(values)), values)

    def test_range_includes_grid_errorbar_and_negative_end(self):
        lo, hi = common.nice_limits([0, 146.040736])
        self.assertEqual((lo, hi), (0, 160))
        lo, hi = common.nice_limits([-3, 2])
        self.assertLessEqual(lo, -3)
        self.assertGreaterEqual(hi, 2)
        self.assertEqual(common.nice_limits([0, 98], percent=True), (0, 100))

    def test_percent_scale_and_original_tick_caption_format(self):
        self.assertGreaterEqual(common.nice_limits([-.007, .5], percent=True)[1], 100)
        with tempfile.TemporaryDirectory() as name:
            script = Path(name) / 'labels.py'
            script.write_text(common.make_script('labels', 'FIGSIZE = (3, 3)',
                'def draw():\n    fig, ax = plt.subplots(figsize=FIGSIZE)\n'
                '    draw_bars(ax, [15.0, 30.0], [{"label": "A", "points": '
                '[{"estimate": 1}, {"estimate": 2}]}])\n'
                '    ax.set_title("Circle")\n    return finish(fig)', 'DATA = []'))
            loaded = runpy.run_path(str(script))
            fig = loaded['draw']()
            self.assertEqual([t.get_text() for t in fig.axes[0].get_xticklabels()], ['15', '30'])
            self.assertEqual(fig.axes[0].get_xlabel(), '(a) Circle')
            loaded['plt'].close(fig)


if __name__ == '__main__':
    unittest.main()
