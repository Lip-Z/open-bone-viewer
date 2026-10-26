"""Check the Git-visible source boundary without printing patient identifiers."""
from __future__ import annotations

import argparse
from io import BytesIO
import json
from pathlib import Path
import subprocess
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_SUFFIXES = {'.dcm', '.dicom', '.zip', '.nrrd', '.npy', '.npz', '.rawz', '.meshz', '.stl', '.png', '.jpg', '.jpeg', '.pdf'}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--private-dicom-zip', type=Path, action='append', default=[])
    args = parser.parse_args()
    visible = subprocess.check_output(['git', '-c', 'core.quotepath=false', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT).decode('utf-8').split('\0')
    files = sorted(set(name for name in visible if name))
    problems = []
    contents = {}
    for relative in files:
        path = ROOT / relative
        if path.suffix.lower() in FORBIDDEN_SUFFIXES or any(part in {'node_modules', '.venv', 'data', 'private', 'runtime', 'uploads', 'output', 'test-artifacts'} for part in path.relative_to(ROOT).parts):
            problems.append({'file': relative, 'reason': 'Medical/binary/runtime asset in release boundary'})
            continue
        try:
            contents[relative] = path.read_text(encoding='utf-8')
        except UnicodeError:
            problems.append({'file': relative, 'reason': 'Unexpected binary file'})
    identifiers = set()
    for archive in args.private_dicom_zip:
        import pydicom
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                if member.is_dir():
                    continue
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter('ignore')
                        dataset = pydicom.dcmread(BytesIO(bundle.read(member)), stop_before_pixels=True, force=True)
                    if not hasattr(dataset, 'SOPClassUID'):
                        continue
                    for tag in ('PatientName', 'PatientID', 'PatientBirthDate', 'AccessionNumber', 'InstitutionName'):
                        value = str(getattr(dataset, tag, '')).strip()
                        if len(value) >= 6:
                            identifiers.add(value)
                    break
                except Exception:
                    continue
    for relative, text in contents.items():
        if any(identifier in text for identifier in identifiers):
            problems.append({'file': relative, 'reason': 'Private DICOM identifier appears in source'})
    result = {'passed': not problems, 'source_files_checked': len(files), 'private_identifiers_checked': len(identifiers), 'problems': problems}
    print(json.dumps(result, ensure_ascii=False))
    if problems:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
