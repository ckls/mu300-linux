"""Atomic build status publication under temporary Windows sharing contention."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('release_state', ROOT / 'tools/build-release.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class Publication(unittest.TestCase):
    def test_transient_reader_keeps_old_state_until_atomic_replace(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'status.json'
            path.write_text('{"state":"old"}')
            original = Path.replace
            calls = []
            def replace(temporary, destination):
                calls.append(1)
                if len(calls) < 3:
                    self.assertEqual(json.loads(path.read_text()), {'state': 'old'})
                    raise PermissionError('sharing violation')
                return original(temporary, destination)
            with patch.object(Path, 'replace', replace), patch.object(build.time, 'sleep') as sleep:
                build.write_json(path, {'state': 'complete'})
            self.assertEqual(json.loads(path.read_text()), {'state': 'complete'})
            self.assertEqual(sleep.call_count, 2)
            self.assertFalse(path.with_name(path.name + '.new').exists())

    def test_permanent_denial_still_fails_and_preserves_both_states(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'status.json'
            path.write_text('{"state":"old"}')
            with patch.object(Path, 'replace', side_effect=PermissionError('denied')) as replace, \
                 patch.object(build.time, 'sleep') as sleep:
                with self.assertRaises(PermissionError):
                    build.write_json(path, {'state': 'new'})
            self.assertEqual(replace.call_count, 21)
            self.assertEqual(sleep.call_count, 20)
            self.assertEqual(json.loads(path.read_text()), {'state': 'old'})
            self.assertEqual(json.loads(path.with_name(path.name + '.new').read_text()), {'state': 'new'})

    def test_other_io_errors_are_not_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(Path, 'replace', side_effect=OSError('I/O failure')) as replace, \
                 patch.object(build.time, 'sleep') as sleep:
                with self.assertRaises(OSError):
                    build.write_json(Path(folder) / 'status.json', {})
            self.assertEqual(replace.call_count, 1)
            sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
