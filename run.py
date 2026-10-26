"""Bootstrap and start the local viewer without changing the system Python."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import venv
import webbrowser

ROOT = Path(__file__).resolve().parent
ENV = ROOT / '.venv'
PYTHON = ENV / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def call(args: list[str], cwd: Path = ROOT) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def setup(rebuild: bool = False) -> None:
    if sys.version_info < (3, 12):
        raise RuntimeError('Python 3.12 or later is required.')
    if not PYTHON.is_file():
        print('Creating the project Python environment...', flush=True)
        venv.EnvBuilder(with_pip=True).create(ENV)
    marker = ENV / 'openbone-installed.json'
    signature = (ROOT / 'pyproject.toml').read_text(encoding='utf-8')
    lock = ROOT / 'requirements-lock.txt'
    if lock.exists():
        signature += '\n' + lock.read_text(encoding='utf-8')
    recorded = marker.read_text(encoding='utf-8') if marker.exists() else ''
    if rebuild or recorded != signature:
        print('Installing local viewer dependencies...', flush=True)
        if lock.exists():
            call([str(PYTHON), '-m', 'pip', 'install', '-r', str(lock)])
            call([str(PYTHON), '-m', 'pip', 'install', '-e', '.', '--no-deps'])
        else:
            call([str(PYTHON), '-m', 'pip', 'install', '-e', '.'])
        marker.write_text(signature, encoding='utf-8')
    npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
    node = shutil.which('node')
    if not npm or not node:
        raise RuntimeError('Install Node.js 22.12 or later, then restart this launcher.')
    version = subprocess.check_output([node, '--version'], text=True).strip().lstrip('v').split('.')
    if tuple(int(x) for x in version[:2]) < (22, 12):
        raise RuntimeError('Node.js 22.12 or later is required.')
    frontend = ROOT / 'frontend'
    dependency_stamp = frontend / 'node_modules' / '.openbone-lock'
    lock_signature = hashlib.sha256((frontend / 'package-lock.json').read_bytes()).hexdigest()
    if rebuild or not dependency_stamp.is_file() or dependency_stamp.read_text(encoding='ascii') != lock_signature:
        call([npm, 'ci'], frontend)
        dependency_stamp.write_text(lock_signature, encoding='ascii')
    source_hash = hashlib.sha256()
    sources = list((frontend / 'src').rglob('*')) + [frontend / name for name in ('package.json', 'package-lock.json', 'index.html', 'tsconfig.json', 'vite.config.ts')]
    for path in sorted(path for path in sources if path.is_file()):
        source_hash.update(path.relative_to(frontend).as_posix().encode('utf-8'))
        source_hash.update(path.read_bytes())
    source_signature = source_hash.hexdigest()
    build_stamp = frontend / 'dist' / '.openbone-source'
    if rebuild or not (frontend / 'dist' / 'index.html').is_file() or not build_stamp.is_file() or build_stamp.read_text(encoding='ascii') != source_signature:
        print('Building the browser interface...', flush=True)
        call([npm, 'run', 'build'], frontend)
        build_stamp.write_text(source_signature, encoding='ascii')


def running_viewer(url: str) -> bool:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url + '/api/health', timeout=1) as response:
            payload = json.load(response)
        return payload.get('status') == 'ok' and payload.get('local_only') is True and payload.get('version') == '0.1.0'
    except (OSError, ValueError):
        return False


def open_when_ready(url: str) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(90):
        try:
            with opener.open(url + '/api/health', timeout=1) as response:
                payload = json.load(response)
            if payload.get('status') == 'ok' and payload.get('local_only'):
                webbrowser.open(url)
                return
        except (OSError, ValueError):
            time.sleep(0.5)


def main() -> None:
    parser = argparse.ArgumentParser(description='Run OpenBone Viewer on this computer.')
    parser.add_argument('--setup-only', action='store_true')
    parser.add_argument('--rebuild', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--port', type=int, default=4318)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('port must be between 1024 and 65535')
    url = f'http://127.0.0.1:{args.port}'
    if not args.setup_only and not args.rebuild and running_viewer(url):
        print(f'OpenBone Viewer is already running: {url}', flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        return
    setup(args.rebuild)
    if args.setup_only:
        return
    print(f'OpenBone Viewer: {url}\nClose this terminal or press Ctrl+C to stop.', flush=True)
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    try:
        call([str(PYTHON), '-m', 'uvicorn', 'openbone.app:app', '--host', '127.0.0.1', '--port', str(args.port), '--no-access-log'])
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f'Cannot start OpenBone Viewer: {exc}', file=sys.stderr)
        raise SystemExit(1)
