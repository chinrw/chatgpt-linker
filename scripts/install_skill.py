#!/usr/bin/env python3
"""Install the explicit-invocation skill without overwriting another installation."""
import argparse
import os
import shutil
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, default=Path.home()/'.agents/skills/rethink-plan',
                        help='Exact destination directory; it must not exist')
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]/'skills/rethink-plan'
    dest = args.destination.expanduser().absolute()
    if dest.exists() or dest.is_symlink():
        parser.error('Destination already exists; compare changes and move it aside explicitly before reinstalling.')
    if dest.is_relative_to(source) or source.is_relative_to(dest):
        parser.error('Source and destination must not overlap.')
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, dest)
    for path in dest.rglob('*'):
        os.chmod(path, 0o700 if path.is_dir() else 0o600)
    dest.chmod(0o700)
    print(f'Installed rethink-plan at {dest}. Restart/reload your agent to discover it.')


if __name__ == '__main__':
    main()
