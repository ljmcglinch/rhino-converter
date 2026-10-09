"""Signed GitHub release updates. No model data, tokens, or remote commands."""
from dataclasses import dataclass, field
from pathlib import Path
import base64
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import threading
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent
MAX_PACKAGE = 2 * 1024**3
FILES = {'windows-x86_64': 'RhinoConverter-Setup.exe',
         'macos-arm64': 'RhinoConverter-Mac-arm64.zip',
         'macos-x86_64': 'RhinoConverter-Mac-x86_64.zip'}


class UpdateError(Exception):
    pass


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,5}\.\d{1,5}\.\d{1,5}', value):
        raise UpdateError('The release has an invalid version.')
    return tuple(map(int, value.split('.')))


def validate_repository(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}', value):
        raise UpdateError('Use a GitHub repository in owner/repository format.')
    return value


def local_version():
    value = (ROOT/'VERSION.txt').read_text(encoding='utf-8').strip()
    version_tuple(value)
    return value


def configuration():
    result = json.loads((ROOT/'update-config.json').read_text(encoding='utf-8'))
    validate_repository(result.get('repository'))
    try:
        key = base64.b64decode(result.get('public_key', ''), validate=True)
    except (ValueError, TypeError) as exc:
        raise UpdateError('Release signing is not configured.') from exc
    if len(key) != 32:
        raise UpdateError('Release signing is not configured.')
    return result


def platform_id():
    architecture = platform.machine().lower()
    if sys.platform == 'win32' and architecture in ('amd64', 'x86_64'):
        return 'windows-x86_64'
    if sys.platform == 'darwin' and architecture in ('arm64', 'aarch64', 'x86_64'):
        return 'macos-' + ('arm64' if architecture in ('arm64', 'aarch64') else 'x86_64')
    raise UpdateError('Automatic updates are supported on Windows x64 and Mac.')


def validate_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in {
            'api.github.com', 'github.com', 'release-assets.githubusercontent.com',
            'objects.githubusercontent.com'} or parsed.username or parsed.password
            or parsed.port not in (None, 443) or parsed.fragment):
        raise UpdateError('The update download URL is not allowed.')
    return url


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_url(url):
    validate_url(url)
    accept = 'application/vnd.github+json' if urllib.parse.urlsplit(url).hostname == 'api.github.com' else 'application/octet-stream'
    request = urllib.request.Request(url, headers={'User-Agent': 'RhinoConverter-Updater', 'Accept': accept})
    return urllib.request.build_opener(SafeRedirect()).open(request, timeout=15)


def fetch_small(url, limit):
    with open_url(url) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise UpdateError('The update metadata is too large.')
    return data


@dataclass(frozen=True)
class Release:
    repository: str
    version: str
    name: str
    size: int
    sha256: str
    signed_manifest: bytes = field(default=b'', repr=False)
    signature: bytes = field(default=b'', repr=False)

    @property
    def url(self):
        return f'https://github.com/{self.repository}/releases/download/v{self.version}/{self.name}'


def verify_manifest(payload, signature, config, current_version, target):
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        key = base64.b64decode(config['public_key'], validate=True)
        sig = base64.b64decode(signature.strip(), validate=True)
        Ed25519PublicKey.from_public_bytes(key).verify(sig, payload)
    except (InvalidSignature, ValueError, KeyError, TypeError) as exc:
        raise UpdateError('The update signature could not be verified. Nothing was installed.') from exc
    try:
        manifest = json.loads(payload)
        if manifest['schema'] != 1 or manifest['repository'] != validate_repository(config['repository']):
            raise UpdateError('The signed release does not match this application.')
        version = manifest['version']
        if version_tuple(version) <= version_tuple(current_version):
            return None
        asset = manifest['assets'][target]
        if asset['name'] != FILES[target]:
            raise UpdateError('The signed release has an unexpected package name.')
        size = asset['size']
        if type(size) is not int or not 0 < size <= MAX_PACKAGE:
            raise UpdateError('The signed release has an invalid download size.')
        if not re.fullmatch(r'[a-f0-9]{64}', asset['sha256']):
            raise UpdateError('The signed release has an invalid file hash.')
        return Release(config['repository'], version, asset['name'], size, asset['sha256'], payload, signature)
    except (KeyError, TypeError, ValueError) as exc:
        raise UpdateError('The signed update metadata is invalid or lacks this platform.') from exc


def check_release(config, current_version, target):
    repo = validate_repository(config['repository'])
    latest = json.loads(fetch_small(f'https://api.github.com/repos/{repo}/releases/latest', 512 * 1024))
    if latest.get('draft') or latest.get('prerelease'):
        return None
    tag = latest.get('tag_name', '')
    if not tag.startswith('v'):
        raise UpdateError('The latest release does not use a supported version tag.')
    version_tuple(tag[1:])
    base = f'https://github.com/{repo}/releases/download/{tag}/'
    payload = fetch_small(base+'update-manifest.json', 128 * 1024)
    signature = fetch_small(base+'update-manifest.sig', 1024)
    release = verify_manifest(payload, signature, config, current_version, target)
    if release is not None and release.version != tag[1:]:
        raise UpdateError('The signed version does not match the GitHub release.')
    return release


def verify_download(path, release):
    digest = hashlib.sha256()
    size = 0
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
            size += len(chunk)
    if size != release.size or digest.hexdigest() != release.sha256:
        raise UpdateError('The downloaded update did not pass verification. Nothing was installed.')


def download_release(release, destination, progress=lambda value: None, cancel=None):
    cancel = cancel or threading.Event()
    destination = Path(destination)
    partial = destination.with_suffix(destination.suffix+'.part')
    owned_partial = False
    try:
        with open_url(release.url) as response, partial.open('xb') as stream:
            owned_partial = True
            size = 0
            while True:
                if cancel.is_set():
                    raise UpdateError('Update download cancelled.')
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > release.size:
                    raise UpdateError('The download exceeds its signed size.')
                stream.write(chunk)
                progress(size/release.size)
        verify_download(partial, release)
        if cancel.is_set():
            raise UpdateError('Update download cancelled.')
        partial.replace(destination)
        return destination
    except Exception:
        if owned_partial:
            partial.unlink(missing_ok=True)
        raise


def windows_install_script(job_file):
    # The only inserted text is a locally generated path, quoted as a literal.
    path = str(job_file).replace("'", "''")
    return """$ErrorActionPreference = 'Stop'
$job = Get-Content -LiteralPath '%s' -Raw | ConvertFrom-Json
try {
  if (Get-Process -Id $job.parent_pid -ErrorAction SilentlyContinue) {
    try { Wait-Process -Id $job.parent_pid -Timeout 90 -ErrorAction Stop }
    catch { if (Get-Process -Id $job.parent_pid -ErrorAction SilentlyContinue) { throw } }
  }
  if ((Get-FileHash -LiteralPath $job.package -Algorithm SHA256).Hash.ToLower() -ne $job.sha256) { throw 'Update checksum changed.' }
  $setup = Start-Process -FilePath $job.package -ArgumentList '/S' -PassThru -Wait
  if ($setup.ExitCode -ne 0) { throw 'Update installation failed.' }
  $installed = (Get-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\RhinoConverter').InstallLocation
  Start-Process -FilePath (Join-Path $installed 'RhinoConverter.exe')
} catch {
  $_ | Out-String | Set-Content -LiteralPath ($job.package + '.install-error.txt')
  Add-Type -AssemblyName System.Windows.Forms
  [System.Windows.Forms.MessageBox]::Show('The update could not be installed. Your model files were not changed. See the update install-error.txt log.', 'Rhino Converter') | Out-Null
  exit 1
}
""" % path


def launch_windows_update(path, release):
    verify_download(path, release)
    with Path(path).open('rb') as stream:
        if stream.read(2) != b'MZ':
            raise UpdateError('The downloaded installer is not a Windows executable.')
    job = Path(path).with_suffix('.install.json')
    job.write_text(json.dumps({'package': str(Path(path).resolve()), 'sha256': release.sha256,
                              'parent_pid': os.getpid()}), encoding='utf-8')
    command = base64.b64encode(windows_install_script(job).encode('utf-16le')).decode('ascii')
    system_root = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    powershell = system_root/'System32'/'WindowsPowerShell'/'v1.0'/'powershell.exe'
    subprocess.Popen([str(powershell), '-NoProfile', '-NonInteractive', '-EncodedCommand', command],
                     creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     close_fds=True, env=dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1'))


def mac_app_path():
    if not getattr(sys, 'frozen', False):
        raise UpdateError('Install the packaged Mac app before using automatic installation.')
    for parent in Path(sys.executable).resolve().parents:
        if parent.suffix == '.app':
            return parent
    raise UpdateError('The running Mac application bundle could not be found.')


def launch_mac_update(path, release):
    verify_download(path, release)
    target = mac_app_path()
    if not os.access(target.parent, os.W_OK):
        raise UpdateError('You need write access to the Applications folder to install this update.')
    job = Path(path).with_suffix('.install.json')
    job.write_text(json.dumps({'package': str(Path(path).resolve()), 'sha256': release.sha256,
                              'size': release.size, 'parent_pid': os.getpid(),
                              'target': str(target),
                              'manifest': base64.b64encode(release.signed_manifest).decode('ascii'),
                              'signature': release.signature.decode('ascii')}), encoding='utf-8')
    subprocess.Popen([sys.executable, '--apply-mac-update', str(job)], start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     env=dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1'))
