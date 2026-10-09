"""Installer removal must be limited to bundled files, with safe NSIS quoting."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'installer'))
from generate_manifest import generate


class InstallerManifest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.app = self.root/'app'
        (self.app/'_internal'/'nested').mkdir(parents=True)
        (self.app/'RhinoConverter.exe').write_bytes(b'fixture')
        (self.app/'_internal'/'nested'/'library.dll').write_bytes(b'fixture')
        self.output = self.root/'uninstall-files.nsh'

    def tearDown(self):
        self.tmp.cleanup()

    def test_exact_deletions_preserve_unrelated_files(self):
        generate(self.app, self.output)
        manifest = self.output.read_text()
        self.assertIn('Delete "$INSTDIR\\RhinoConverter.exe"', manifest)
        self.assertIn('Delete "$INSTDIR\\_internal\\nested\\library.dll"', manifest)
        self.assertNotIn('RMDir /r', manifest)
        self.assertNotIn('*', manifest)
        self.assertNotIn('$DOCUMENTS', manifest)
        self.assertLess(manifest.index('RMDir "$INSTDIR\\_internal\\nested"'),
                        manifest.index('RMDir "$INSTDIR\\_internal"'))

    def test_dollar_in_filename_is_literal(self):
        (self.app/'_internal'/'cost $name.dll').write_bytes(b'fixture')
        generate(self.app, self.output)
        self.assertIn('cost $$name.dll', self.output.read_text())

    def test_incomplete_app_is_rejected(self):
        (self.app/'RhinoConverter.exe').unlink()
        with self.assertRaises(ValueError):
            generate(self.app, self.output)
        self.assertFalse(self.output.exists())

    def test_symlink_to_external_files_is_rejected(self):
        try:
            (self.app/'_internal'/'outside').symlink_to(self.root, target_is_directory=True)
        except OSError as exc:
            self.skipTest('Symlink creation is unavailable: ' + str(exc))
        with self.assertRaises(ValueError):
            generate(self.app, self.output)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
