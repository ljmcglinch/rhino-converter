"""Publisher-only release signing tools. Private keys never enter app bundles."""
from pathlib import Path
import argparse
import base64
import hashlib
import json
import os
from updater import FILES, MAX_PACKAGE, validate_repository, version_tuple, configuration

ROOT = Path(__file__).resolve().parent


def configure_public(repository, public_key):
    """Pin an externally managed public key without accessing private material."""
    repository = validate_repository(repository)
    raw = base64.b64decode(public_key, validate=True)
    if len(raw) != 32:
        raise ValueError('The Ed25519 public key must contain exactly 32 bytes.')
    public_key = base64.b64encode(raw).decode('ascii')
    path = ROOT/'update-config.json'
    old = json.loads(path.read_text(encoding='utf-8'))
    if old.get('public_key') and old['public_key'] != public_key:
        raise ValueError('Existing builds trust a different key. Do not rotate it without a migration plan.')
    if old.get('repository') and old['repository'] != repository:
        raise ValueError('Existing builds use a different repository. Plan a migration before changing it.')
    path.write_text(json.dumps({'repository': repository, 'public_key': public_key}, indent=2)+'\n', encoding='utf-8')


def validate_release(repository, tag):
    config = configuration()
    version = (ROOT/'VERSION.txt').read_text(encoding='utf-8').strip()
    version_tuple(version)
    if validate_repository(repository) != config['repository']:
        raise ValueError('This workflow repository does not match update-config.json.')
    if tag != 'v'+version:
        raise ValueError('Tag must match VERSION.txt exactly.')
    return config


def configure(repository, private_key_path):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    repository = validate_repository(repository)
    private_key_path = Path(private_key_path).expanduser().resolve()
    if private_key_path.is_relative_to(ROOT):
        raise ValueError('Keep the private signing key outside the source/project folder.')
    private_key_path.parent.mkdir(parents=True, exist_ok=True)
    if private_key_path.exists():
        key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key_path.read_bytes().strip(), validate=True))
    else:
        key = Ed25519PrivateKey.generate()
        encoded = base64.b64encode(key.private_bytes(serialization.Encoding.Raw,
                serialization.PrivateFormat.Raw, serialization.NoEncryption()))
        descriptor = os.open(private_key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(encoded+b'\n')
    public_key = base64.b64encode(key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode('ascii')
    path = ROOT/'update-config.json'
    old = json.loads(path.read_text(encoding='utf-8'))
    if old.get('public_key') and old['public_key'] != public_key:
        raise ValueError('Existing builds trust a different key. Do not rotate it without a migration plan.')
    configure_public(repository, public_key)
    print('Configured repository:', repository)
    print('Public signing key:', public_key)
    print('Private key saved outside the project:', private_key_path)
    print('Add the CONTENTS of that private file as the UPDATE_SIGNING_KEY secret')
    print('in the GitHub Actions environment named release. Never commit that file.')


def sign_release(directory, repository, version, encoded_key, public_key):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    validate_repository(repository)
    version_tuple(version)
    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(encoded_key.strip(), validate=True))
    actual_public = base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw,
                   serialization.PublicFormat.Raw)).decode('ascii')
    if actual_public != public_key:
        raise ValueError('The release secret does not match the public key bundled in the app.')
    directory = Path(directory)
    assets = {}
    for target, name in FILES.items():
        path = directory/name
        size = path.stat().st_size
        if not 0 < size <= MAX_PACKAGE:
            raise ValueError('Invalid package size: '+name)
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024*1024), b''):
                digest.update(chunk)
        assets[target] = {'name': name, 'size': size, 'sha256': digest.hexdigest()}
    payload = json.dumps({'schema': 1, 'repository': repository, 'version': version, 'assets': assets},
                         sort_keys=True, separators=(',', ':')).encode('utf-8')
    (directory/'update-manifest.json').write_bytes(payload)
    (directory/'update-manifest.sig').write_bytes(base64.b64encode(key.sign(payload))+b'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    configure_cmd = sub.add_parser('configure')
    configure_cmd.add_argument('--repository')
    configure_cmd.add_argument('--private-key', type=Path,
                               default=Path.home()/'RhinoConverterReleaseKeys'/'signing-key.txt')
    public_cmd = sub.add_parser('configure-public')
    public_cmd.add_argument('--repository', required=True)
    public_cmd.add_argument('--public-key', required=True)
    validate_cmd = sub.add_parser('validate')
    validate_cmd.add_argument('--repository', required=True)
    validate_cmd.add_argument('--tag', required=True)
    sign_cmd = sub.add_parser('sign')
    sign_cmd.add_argument('directory', type=Path)
    sign_cmd.add_argument('--repository', required=True)
    sign_cmd.add_argument('--version', required=True)
    args = parser.parse_args()
    if args.command == 'configure':
        configure(args.repository or input('GitHub repository (owner/name): ').strip(), args.private_key)
    elif args.command == 'configure-public':
        configure_public(args.repository, args.public_key)
    elif args.command == 'validate':
        validate_release(args.repository, args.tag)
    else:
        config = validate_release(args.repository, 'v'+args.version)
        sign_release(args.directory, args.repository, args.version,
                     os.environ['UPDATE_SIGNING_KEY'], config['public_key'])


if __name__ == '__main__':
    main()
