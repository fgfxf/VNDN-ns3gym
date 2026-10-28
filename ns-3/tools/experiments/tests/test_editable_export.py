import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

DIRECTORY = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('editable_export_test', DIRECTORY / 'export_editable_plots.py')
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class EditableExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'sealed'
        self.source.mkdir()
        figures = []
        self.programs = {}
        artifacts = {}
        for i in range(52):
            ident = 'figure-{:02d}'.format(i)
            image = ident + '.png'
            (self.source / image).write_bytes(b'sealed')
            artifacts[image] = hashlib.sha256(b'sealed').hexdigest()
            figures.append(dict(id=ident, files={'png': image}, caption_zh='说明', caption_en='Caption'))
            self.programs[ident] = 'DATA = [1, 2]\n'
        (self.source / 'figure-index.json').write_text(json.dumps(dict(
            figure_count=52, figures=figures, artifact_hashes=artifacts, source_tables={})))
        self.index = (self.source / 'figure-index.json').read_bytes()

    def test_52_python_files_and_gallery_are_new_and_repeat_refuses(self):
        output = self.root / 'editable'
        with patch.object(module, 'collect_programs', return_value=self.programs):
            module.export_package(self.source, output, render=False)
            self.assertEqual(len(list(output.glob('*.py'))), 52)
            self.assertEqual(len(list(output.glob('*.cmd'))), 0)
            text = (output / 'index.html').read_text()
            self.assertEqual(text.count('<img '), 52)
            self.assertIn('Date.now()', text)
            edited = output / 'figure-00.py'
            edited.write_text('DATA = [99]\n')
            with self.assertRaises(FileExistsError):
                module.export_package(self.source, output, render=False)
            self.assertEqual(edited.read_text(), 'DATA = [99]\n')
        self.assertEqual((self.source / 'figure-index.json').read_bytes(), self.index)
        self.assertEqual((self.source / 'figure-00.png').read_bytes(), b'sealed')

    def test_changed_sealed_source_is_rejected_before_creating_output(self):
        (self.source / 'figure-00.png').write_bytes(b'changed')
        output = self.root / 'bad'
        with patch.object(module, 'collect_programs', return_value=self.programs):
            with self.assertRaises(ValueError):
                module.export_package(self.source, output, render=False)
        self.assertFalse(output.exists())

    def test_missing_script_is_rejected_before_creating_output(self):
        self.programs.pop('figure-00')
        output = self.root / 'missing'
        with patch.object(module, 'collect_programs', return_value=self.programs):
            with self.assertRaises(ValueError):
                module.export_package(self.source, output, render=False)
        self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
