import base64
import hashlib
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import subprocess
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import updater
from mac_update import validate_archive, apply_update


class Updates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.key = Ed25519PrivateKey.generate()
        public = self.key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.config = {'repository': 'office/rhino-converter', 'public_key': base64.b64encode(public).decode()}
        self.binary = b'MZverified installer fixture'
        self.manifest = {'schema': 1, 'repository': self.config['repository'], 'version': '0.6.0',
            'assets': {'windows-x86_64': {'name': updater.FILES['windows-x86_64'],
                'size': len(self.binary), 'sha256': hashlib.sha256(self.binary).hexdigest()}}}

    def tearDown(self):
        self.tmp.cleanup()

    def signed(self):
        payload = json.dumps(self.manifest).encode()
        return payload, base64.b64encode(self.key.sign(payload))

    def release(self):
        return updater.verify_manifest(*self.signed(), self.config, '0.5.0', 'windows-x86_64')

    def test_signed_update_selects_fixed_package(self):
        release = self.release()
        self.assertEqual(release.version, '0.6.0')
        self.assertEqual(release.url, 'https://github.com/office/rhino-converter/releases/download/v0.6.0/RhinoConverter-Setup.exe')

    def test_tampering_or_wrong_key_is_rejected(self):
        payload, signature = self.signed()
        with self.assertRaises(updater.UpdateError):
            updater.verify_manifest(payload.replace(b'0.6.0', b'0.9.0'), signature, self.config, '0.5.0', 'windows-x86_64')
        with self.assertRaises(updater.UpdateError):
            updater.verify_manifest(payload, base64.b64encode(Ed25519PrivateKey.generate().sign(payload)), self.config, '0.5.0', 'windows-x86_64')

    def test_unsigned_metadata_is_rejected(self):
        with self.assertRaises(updater.UpdateError):
            updater.verify_manifest(self.signed()[0], b'', self.config, '0.5.0', 'windows-x86_64')

    def test_signed_repository_mismatch_is_rejected(self):
        self.manifest['repository'] = 'attacker/another-app'
        with self.assertRaises(updater.UpdateError):
            self.release()

    def test_older_and_equal_versions_do_not_install(self):
        for version in ('0.4.0', '0.5.0'):
            self.manifest['version'] = version
            self.assertIsNone(self.release())

    def test_unexpected_asset_name_or_size_is_rejected(self):
        asset = self.manifest['assets']['windows-x86_64']
        for name in ('../../evil.exe', 'other.exe'):
            asset['name'] = name
            with self.assertRaises(updater.UpdateError):
                self.release()
        asset['name'] = updater.FILES['windows-x86_64']
        for size in (0, -1, updater.MAX_PACKAGE+1, True):
            asset['size'] = size
            with self.assertRaises(updater.UpdateError):
                self.release()

    def test_only_https_github_download_hosts_are_allowed(self):
        for url in ('http://github.com/a', 'https://evil.example/a', 'file:///tmp/a',
                    'https://github.com@evil.example/a', 'https://user:secret@github.com/a',
                    'https://github.com:8443/a', 'https://github.com/a#fragment'):
            with self.assertRaises(updater.UpdateError):
                updater.validate_url(url)
        updater.validate_url('https://release-assets.githubusercontent.com/a')

    def test_redirect_to_external_host_is_rejected_before_request(self):
        with self.assertRaises(updater.UpdateError):
            updater.SafeRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.example/payload')

    def test_metadata_download_is_size_limited(self):
        with patch('updater.open_url', return_value=io.BytesIO(b'123456')):
            with self.assertRaises(updater.UpdateError):
                updater.fetch_small('https://github.com/file', 5)

    def test_latest_tag_must_match_signed_version(self):
        data = [json.dumps({'tag_name': 'v0.7.0'}).encode(), *self.signed()]
        with patch('updater.fetch_small', side_effect=data):
            with self.assertRaises(updater.UpdateError):
                updater.check_release(self.config, '0.5.0', 'windows-x86_64')

    def test_hash_and_size_verified_before_publish(self):
        release = self.release()
        destination = self.root/release.name
        with patch('updater.open_url', return_value=io.BytesIO(self.binary)):
            updater.download_release(release, destination)
        self.assertEqual(destination.read_bytes(), self.binary)
        self.assertFalse(destination.with_suffix('.exe.part').exists())

    def test_modified_truncated_and_oversized_downloads_are_removed(self):
        release = self.release()
        destination = self.root/release.name
        for body in (b'X'+self.binary[1:], self.binary[:-1], self.binary+b'extra'):
            with patch('updater.open_url', return_value=io.BytesIO(body)):
                with self.assertRaises(updater.UpdateError):
                    updater.download_release(release, destination)
            self.assertFalse(destination.exists())
            self.assertFalse(destination.with_suffix('.exe.part').exists())

    def test_cancellation_preserves_existing_destination(self):
        release = self.release()
        destination = self.root/release.name
        destination.write_bytes(b'previous verified download')
        event = threading.Event(); event.set()
        with patch('updater.open_url', return_value=io.BytesIO(self.binary)):
            with self.assertRaises(updater.UpdateError):
                updater.download_release(release, destination, cancel=event)
        self.assertEqual(destination.read_bytes(), b'previous verified download')

    def test_existing_partial_is_not_deleted(self):
        release = self.release()
        destination = self.root/release.name
        partial = destination.with_suffix('.exe.part')
        partial.write_bytes(b'unrelated')
        with patch('updater.open_url', return_value=io.BytesIO(self.binary)):
            with self.assertRaises(FileExistsError):
                updater.download_release(release, destination)
        self.assertEqual(partial.read_bytes(), b'unrelated')

    def test_windows_handoff_rechecks_hash_before_launch(self):
        path = self.root/'RhinoConverter-Setup.exe'; path.write_bytes(b'tampered')
        with patch('updater.subprocess.Popen') as launch:
            with self.assertRaises(updater.UpdateError):
                updater.launch_windows_update(path, self.release())
            launch.assert_not_called()

    def test_windows_job_path_is_quoted_as_literal(self):
        job = Path("C:/a'folder/job.json")
        code = updater.windows_install_script(job)
        self.assertIn("Get-Content -LiteralPath '" + str(job).replace("'", "''") + "'", code)
        self.assertIn('Wait-Process', code)
        self.assertIn('Get-FileHash', code)

    def archive(self, extra=None):
        path = self.root/'app.zip'
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('RhinoConverter.app/Contents/MacOS/RhinoConverter', b'app')
            if extra:
                for name, data, symlink in extra:
                    info = zipfile.ZipInfo(name)
                    if symlink:
                        info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    z.writestr(info, data)
        return path

    def test_mac_archive_allows_internal_bundle_links(self):
        validate_archive(self.archive([('RhinoConverter.app/Contents/Frameworks/library', '../Resources/library', True)]))

    def test_mac_archive_rejects_traversal_and_external_links(self):
        for name, body, link in (('../outside', b'x', False), ('/outside', b'x', False),
              ('RhinoConverter.app/Contents/link', '/etc/passwd', True),
              ('RhinoConverter.app/Contents/link', '../../../outside', True)):
            with self.assertRaises(updater.UpdateError):
                validate_archive(self.archive([(name, body, link)]))

    def test_mac_archive_rejects_writing_through_symlinks(self):
        with self.assertRaises(updater.UpdateError):
            validate_archive(self.archive([('RhinoConverter.app/Contents/link', 'Resources', True),
                 ('RhinoConverter.app/Contents/link/overwrite', b'x', False)]))

    def test_busy_conversion_blocks_install_before_launch(self):
        from app import Converter
        app = SimpleNamespace(update_busy=False, update_download=self.root/'update.exe',
                              conversion_busy=True, process=None, pending=[], review_source=None)
        with patch('app.messagebox.showinfo') as notice, patch('updater.launch_windows_update') as launch:
            Converter.install_update(app)
            notice.assert_called_once()
            launch.assert_not_called()

    def test_publisher_signature_roundtrip_for_all_platforms(self):
        from release_tools import sign_release
        private = base64.b64encode(self.key.private_bytes(serialization.Encoding.Raw,
                    serialization.PrivateFormat.Raw, serialization.NoEncryption())).decode()
        for name in updater.FILES.values():
            (self.root/name).write_bytes(self.binary)
        sign_release(self.root, self.config['repository'], '0.6.0', private, self.config['public_key'])
        for target in updater.FILES:
            release = updater.verify_manifest((self.root/'update-manifest.json').read_bytes(),
                (self.root/'update-manifest.sig').read_bytes(), self.config, '0.5.0', target)
            self.assertEqual(release.name, updater.FILES[target])

    def mac_job(self, valid=True):
        package = self.archive()
        target = self.root/'RhinoConverter.app'; target.mkdir()
        (target/'previous.txt').write_text('previous app')
        self.manifest['assets'] = {'macos-arm64': {'name': updater.FILES['macos-arm64'],
            'size': package.stat().st_size, 'sha256': hashlib.sha256(package.read_bytes()).hexdigest()}}
        payload, signature = self.signed()
        job = self.root/'job.json'
        job.write_text(json.dumps({'target': str(target), 'package': str(package),
            'manifest': base64.b64encode(payload).decode(),
            'signature': signature.decode() if valid else '', 'parent_pid': 12345}))
        return job, target

    def test_mac_install_worker_rejects_unsigned_direct_invocation(self):
        job, target = self.mac_job(valid=False)
        with patch('mac_update.mac_app_path', return_value=target), patch('mac_update.configuration', return_value=self.config), patch('mac_update.local_version', return_value='0.5.0'), patch('mac_update.platform_id', return_value='macos-arm64'), patch('mac_update.subprocess.run') as run:
            self.assertEqual(apply_update(job), 1)
        self.assertEqual((target/'previous.txt').read_text(), 'previous app')
        self.assertFalse(any(call.args[0][0] == '/usr/bin/ditto' for call in run.call_args_list))

    def test_mac_failed_restart_restores_previous_app(self):
        job, target = self.mac_job()
        failed = []
        def run(command, **kwargs):
            if command[0] == '/usr/bin/ditto':
                candidate = Path(command[-1])/'RhinoConverter.app/Contents/MacOS'
                candidate.mkdir(parents=True)
                (candidate/'RhinoConverter').write_bytes(b'new app')
            if command[0] == '/usr/bin/open' and not failed:
                failed.append(True)
                raise subprocess.CalledProcessError(1, command)
            return SimpleNamespace(returncode=0)
        with patch('mac_update.mac_app_path', return_value=target), patch('mac_update.configuration', return_value=self.config), patch('mac_update.local_version', return_value='0.5.0'), patch('mac_update.platform_id', return_value='macos-arm64'), patch('mac_update.wait_for_parent'), patch('mac_update.subprocess.run', side_effect=run):
            self.assertEqual(apply_update(job), 1)
        self.assertEqual((target/'previous.txt').read_text(), 'previous app')
        self.assertFalse((target/'Contents').exists())


if __name__ == '__main__':
    unittest.main()
