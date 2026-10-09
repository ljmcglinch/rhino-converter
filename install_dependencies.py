"""Migrate away from the unused VTK renderer, then install pinned dependencies."""
from pathlib import Path
import argparse
import importlib.metadata
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--build', action='store_true')
args = parser.parse_args()
try:
    importlib.metadata.version('cadquery-ocp')
except importlib.metadata.PackageNotFoundError:
    pass
else:
    # Both OCP distributions own the same Python module: uninstall old first.
    subprocess.run([sys.executable, '-m', 'pip', 'uninstall', '-y', 'cadquery-ocp', 'vtk'], check=True)
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--force-reinstall', '--no-deps',
                    'cadquery-ocp-novtk==7.8.1.1.post1'], check=True)
requirements = ROOT/('requirements-build.txt' if args.build else 'requirements.txt')
subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', str(requirements)], check=True)
if args.build:
    subprocess.run([sys.executable, '-m', 'pip_audit', '-r', str(ROOT/'requirements-build.txt')], check=True)
