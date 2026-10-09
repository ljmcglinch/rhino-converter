"""Write exact NSIS uninstall commands for the frozen app's owned files."""
from pathlib import Path
import argparse


def quoted_path(relative):
    text = str(relative).replace('/', '\\')
    if any(char in text for char in '\r\n'):
        raise ValueError('Package filenames must not contain newlines.')
    return text.replace('$', '$$').replace('"', '$\\"')


def generate(app_folder, output):
    app_folder = Path(app_folder)
    if not (app_folder/'RhinoConverter.exe').is_file() or not (app_folder/'_internal').is_dir():
        raise ValueError('Build the complete Windows app folder first.')
    files, directories = [], []
    for path in sorted(app_folder.rglob('*')):
        if path.is_symlink():
            raise ValueError('Windows package must not contain symbolic links.')
        if path.is_file():
            files.append(path.relative_to(app_folder))
        elif path.is_dir():
            directories.append(path.relative_to(app_folder))
    lines = ['; Generated: remove only files included in this package.']
    lines.extend('Delete "$INSTDIR\\%s"' % quoted_path(path) for path in files)
    lines.extend('RMDir "$INSTDIR\\%s"' % quoted_path(path)
                 for path in sorted(directories, key=lambda p: (-len(p.parts), str(p))))
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text('\n'.join(lines)+'\n', encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app_folder', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    generate(args.app_folder, args.output)
