"""Publisher preflight checks use public fixtures only; no private key files."""
import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import release_tools
import updater


class ReleaseConfiguration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = self.root/'update-config.json'
        self.config.write_text('{"repository": "", "public_key": ""}')
        (self.root/'VERSION.txt').write_text('0.5.0\n')
        self.key = base64.b64encode(bytes(range(32))).decode('ascii')
        self.patches = [patch('release_tools.ROOT', self.root), patch('updater.ROOT', self.root)]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def test_public_configuration_and_matching_preflight(self):
        release_tools.configure_public('office/converter', self.key)
        result = release_tools.validate_release('office/converter', 'v0.5.0')
        self.assertEqual(result['public_key'], self.key)
        self.assertEqual({p.name for p in self.root.iterdir()}, {'update-config.json', 'VERSION.txt'})

    def test_invalid_keys_leave_config_unchanged(self):
        original = self.config.read_bytes()
        for key in ('invalid!', '', base64.b64encode(b'short').decode()):
            with self.assertRaises(ValueError):
                release_tools.configure_public('office/converter', key)
            self.assertEqual(self.config.read_bytes(), original)

    def test_key_and_repository_changes_are_refused(self):
        release_tools.configure_public('office/converter', self.key)
        original = self.config.read_bytes()
        for repository, key in [('office/other', self.key),
                ('office/converter', base64.b64encode(bytes(32)).decode())]:
            with self.assertRaises(ValueError):
                release_tools.configure_public(repository, key)
            self.assertEqual(self.config.read_bytes(), original)

    def test_preflight_rejects_wrong_repository_tag_and_malformed_key(self):
        release_tools.configure_public('office/converter', self.key)
        for repository, tag in [('office/other', 'v0.5.0'), ('office/converter', 'v0.5.1'),
                                ('office/converter', '0.5.0')]:
            with self.assertRaises(ValueError):
                release_tools.validate_release(repository, tag)
        self.config.write_text(json.dumps({'repository': 'office/converter', 'public_key': 'x'}))
        with self.assertRaises(updater.UpdateError):
            release_tools.validate_release('office/converter', 'v0.5.0')
