#!/usr/bin/env python3
"""Copy only release source paths into an EMPTY destination; never copy user state."""
import argparse
import shutil
from pathlib import Path

ROOT_FILES = ('README.md','LICENSE','pyproject.toml','MANIFEST.in','.gitignore',
              'CHANGELOG.md','CONTRIBUTING.md','SECURITY.md','AGENTS.md')
ROOT_DIRS = ('src','tests','docs','skills','examples','scripts','.github')
SKIP_DIRS = {'__pycache__','.pytest_cache','.venv','node_modules','state','build','dist'}


def snapshot(source, dest):
    if source.resolve() == dest.resolve() or dest.resolve().is_relative_to(source.resolve()):
        raise ValueError('Destination must be outside the source project.')
    if not dest.is_dir() or any(dest.iterdir()):
        raise ValueError('Destination must be an empty directory.')
    for name in ROOT_FILES:
        path = source/name
        if path.is_symlink():
            raise ValueError('Refusing a linked source file.')
        if path.is_file():
            shutil.copy2(path, dest/name)
    for dirname in ROOT_DIRS:
        root = source/dirname
        if not root.is_dir() or root.is_symlink():
            raise ValueError('Missing or linked source directory: '+dirname)
        for path in root.rglob('*'):
            relative = path.relative_to(source)
            if any(p in SKIP_DIRS or p.endswith(('.egg-info', '.dist-info')) for p in relative.parts):
                continue
            if path.is_symlink():
                raise ValueError('Refusing a linked source entry.')
            if path.is_file():
                if path.suffix in {'.pyc','.pyo','.pem','.key'} or path.name.startswith('.env'):
                    continue
                target = dest/relative
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(path,target)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args=parser.parse_args()
    snapshot(args.source,args.destination)
