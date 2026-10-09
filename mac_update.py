"""Apply a signed app-bundle update after the main Mac process exits."""
from pathlib import Path, PurePosixPath
import base64
import json
import os
import posixpath
import secrets
import shutil
import stat
import subprocess
import tempfile
import time
import zipfile
from updater import (UpdateError, configuration, local_version, platform_id,
                     verify_manifest, verify_download, mac_app_path)


def validate_archive(path):
    symlinks, members = {}, set()
    with zipfile.ZipFile(path) as archive:
        total = 0
        for info in archive.infolist():
            name = info.filename
            parts = PurePosixPath(name).parts
            if (not parts or '\\' in name or name.startswith('/') or '..' in parts
                    or '\x00' in name or len(name) > 4096
                    or str(PurePosixPath(name)) != name.rstrip('/')
                    or parts[0] not in ('RhinoConverter.app', '__MACOSX')):
                raise UpdateError('The update archive contains an unsafe path.')
            total += info.file_size
            if total > 4 * 1024**3:
                raise UpdateError('The unpacked update is too large.')
            if name in members:
                raise UpdateError('The update archive contains duplicate paths.')
            members.add(name)
            if len(members) > 30000:
                raise UpdateError('The update archive has too many entries.')
            if stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK):
                raise UpdateError('The update archive contains a special file.')
            if stat.S_ISLNK(info.external_attr >> 16):
                if info.file_size > 4096:
                    raise UpdateError('The update has an invalid symbolic link.')
                link = archive.read(info).decode('utf-8')
                target = posixpath.normpath(posixpath.join(posixpath.dirname(name), link))
                if ('\\' in link or '\x00' in link or link.startswith('/') or
                        not target.startswith('RhinoConverter.app/')):
                    raise UpdateError('The update contains a link outside its app bundle.')
                symlinks[name] = target
        for name in members:
            if any(str(parent) in symlinks for parent in PurePosixPath(name).parents):
                raise UpdateError('The update writes through a symbolic link.')
        if 'RhinoConverter.app/Contents/MacOS/RhinoConverter' not in members:
            raise UpdateError('The update has no application executable.')


def wait_for_parent(pid, timeout=90):
    if type(pid) is not int or pid <= 1 or pid == os.getpid():
        raise UpdateError('The update parent process is invalid.')
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        if time.monotonic() >= deadline:
            raise UpdateError('The converter did not close; the update was not installed.')
        time.sleep(0.1)


def apply_update(job_path):
    job_path = Path(job_path)
    target = mac_app_path()
    staging = None
    backup = None
    swapped = False
    try:
        job = json.loads(job_path.read_text(encoding='utf-8'))
        if Path(job['target']).resolve() != target:
            raise UpdateError('The update cannot replace another application.')
        release = verify_manifest(base64.b64decode(job['manifest'], validate=True),
                                  job['signature'].encode('ascii'), configuration(),
                                  local_version(), platform_id())
        if release is None:
            raise UpdateError('This update is not newer than the installed application.')
        package = Path(job['package'])
        verify_download(package, release)
        validate_archive(package)
        staging = Path(tempfile.mkdtemp(prefix='.RhinoConverter-update-', dir=target.parent))
        subprocess.run(['/usr/bin/ditto', '-x', '-k', str(package), str(staging)], check=True)
        candidate = staging/'RhinoConverter.app'
        if not (candidate/'Contents/MacOS/RhinoConverter').is_file():
            raise UpdateError('The extracted app is incomplete.')
        subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(candidate)], check=True)
        wait_for_parent(job['parent_pid'])
        backup = target.with_name(target.stem+'-previous-'+secrets.token_hex(4)+'.app')
        target.rename(backup)
        try:
            candidate.rename(target)
        except Exception:
            backup.rename(target)
            backup = None
            raise
        swapped = True
        subprocess.run(['/usr/bin/open', str(target)], check=True)
        # Keep the previous app as a rollback copy; do not remove its contents.
    except Exception as exc:
        if swapped and backup is not None:
            target.rename(staging/'failed-update.app')
            backup.rename(target)
        job_path.with_suffix('.install-error.txt').write_text(str(exc), encoding='utf-8')
        subprocess.run(['/usr/bin/osascript', '-e',
                        'display alert "Rhino Converter update failed" message "Your previous app and model files were preserved. See the update install-error.txt log."'], check=False)
        subprocess.run(['/usr/bin/open', str(target)], check=False)
        return 1
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
    return 0
