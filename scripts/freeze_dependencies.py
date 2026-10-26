"""Record versions from a tested environment without paths or editable installs."""
from __future__ import annotations

from importlib import metadata
from pathlib import Path
import tomllib

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]


def closure(requirements: list[str]) -> dict[str, str]:
    pending = [Requirement(value).name for value in requirements]
    visited = {}
    while pending:
        name = canonicalize_name(pending.pop())
        if name in visited:
            continue
        installed = metadata.distribution(name)
        visited[name] = installed.version
        for value in installed.requires or []:
            dependency = Requirement(value)
            if dependency.marker is None or dependency.marker.evaluate({'extra': ''}):
                pending.append(dependency.name)
    return visited


def save(name: str, packages: dict[str, str]) -> None:
    lines = ['# Exact versions from the validated Python 3.12 environment.', '# Contains no editable paths or private data.']
    lines.extend(f'{name}=={version}' for name, version in sorted(packages.items()))
    (ROOT / name).write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')


if __name__ == '__main__':
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']
    save('requirements-lock.txt', closure(project['dependencies']))
    save('requirements-dev-lock.txt', closure(project['dependencies'] + project['optional-dependencies']['dev']))
