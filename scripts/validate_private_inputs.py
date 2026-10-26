"""Opt-in local validation; never stores a real input or report in source control."""
from __future__ import annotations

import argparse
from collections import defaultdict
import gzip
import hashlib
from io import BytesIO
import json
from pathlib import Path
import struct
import time
import warnings
import zipfile

import httpx
import numpy as np
import pydicom

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            result.update(data)
    return result.hexdigest()


def wait(api: httpx.Client, response: httpx.Response) -> dict:
    response.raise_for_status()
    job_id = response.json()['id']
    for _ in range(720):
        response = api.get(f'/api/jobs/{job_id}')
        response.raise_for_status()
        job = response.json()
        if job['status'] == 'done':
            return job['result']
        if job['status'] == 'error':
            raise AssertionError(job['message'])
        time.sleep(.5)
    raise AssertionError('Local job did not complete within six minutes')


def references(archive: Path) -> dict:
    groups = defaultdict(list)
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            if member.is_dir():
                continue
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore')
                    data = pydicom.dcmread(BytesIO(bundle.read(member)), force=True)
                if str(getattr(data, 'Modality', '')) == 'CT' and hasattr(data, 'PixelData'):
                    groups[str(data.SeriesInstanceUID)].append(data)
            except Exception:
                continue
    return groups


def verify_ct(api: httpx.Client, study: dict, groups: dict) -> dict:
    study_id = study['id']
    meta = api.get(f'/api/studies/{study_id}/metadata').json()
    raw_response = api.get(f'/api/studies/{study_id}/assets/volume.rawz')
    raw_response.raise_for_status()
    canonical_bytes = gzip.decompress(raw_response.content)
    canonical = np.frombuffer(canonical_bytes, dtype='<f4').reshape(meta['dimensions_xyz'][::-1])
    nrrd_response = api.get(f'/api/studies/{study_id}/assets/source.nrrd')
    nrrd_response.raise_for_status()
    header, compressed = nrrd_response.content.split(b'\n\n', 1)
    source_bytes = gzip.decompress(compressed)
    source = np.frombuffer(source_bytes, dtype='<f4').reshape(meta['source_dimensions_xyz'][::-1])
    matching = [group for group in groups.values() if len(group) == study['count'] and int(group[0].Rows) == study['rows'] and int(group[0].Columns) == study['columns']]
    matched = False
    for group in matching:
        orientation = np.array(group[0].ImageOrientationPatient, dtype=float)
        normal = np.cross(orientation[:3], orientation[3:])
        ordered = sorted(group, key=lambda data: np.dot(np.array(data.ImagePositionPatient, dtype=float), normal))
        source_equal = True
        for i, dataset in enumerate(ordered):
            expected = (dataset.pixel_array.astype(np.float64) * float(dataset.RescaleSlope) + float(dataset.RescaleIntercept)).astype('<f4')
            if not np.array_equal(source[i], expected):
                source_equal = False
                break
        if not source_equal:
            continue
        # Independent point-by-point physical-coordinate check against acquired data.
        acquired_directions = np.column_stack((orientation[:3], orientation[3:], normal))
        acquired_spacing = np.array([float(ordered[0].PixelSpacing[1]), float(ordered[0].PixelSpacing[0]), np.median([np.dot(np.array(ordered[i + 1].ImagePositionPatient, dtype=float) - np.array(ordered[i].ImagePositionPatient, dtype=float), normal) for i in range(len(ordered) - 1)])])
        acquired_origin = np.array(ordered[0].ImagePositionPatient, dtype=float)
        dimensions = np.array(meta['dimensions_xyz'])
        rng = np.random.default_rng(261026)
        points = rng.integers(0, dimensions, size=(2000, 3))
        points = np.vstack((points, np.zeros(3, dtype=int), dimensions - 1))
        physical = np.array(meta['origin_lps_mm']) + points * np.array(meta['spacing_xyz_mm'])
        original_index = np.rint(((physical - acquired_origin) @ acquired_directions) / acquired_spacing).astype(int)
        for point, original in zip(points, original_index):
            if canonical[point[2], point[1], point[0]] != source[original[2], original[1], original[0]]:
                raise AssertionError('Canonical physical-coordinate check failed')
        matched = True
        break
    if not matched:
        raise AssertionError('Exported source HU differ from independently decoded DICOM')
    mesh = wait(api, api.post(f'/api/studies/{study_id}/mesh', json={'threshold': 300, 'smooth': False}))['model']
    stl_response = api.get(f'/api/studies/{study_id}/assets/{mesh["stl_file"]}')
    stl_response.raise_for_status()
    stl = stl_response.content
    faces = struct.unpack_from('<I', stl, 80)[0]
    if len(stl) != 84 + 50 * faces or faces != mesh['triangles']:
        raise AssertionError('STL topology length mismatch')
    return {'study_id': study_id, 'kind': 'ct', 'dimensions_xyz': meta['dimensions_xyz'], 'spacing_xyz_mm': meta['spacing_xyz_mm'], 'source_hu_exact': True, 'physical_samples_equal': len(points), 'volume_sha256': hashlib.sha256(canonical_bytes).hexdigest(), 'nrrd_has_lps_geometry': b'space: left-posterior-superior' in header and b'space directions:' in header, 'surface_triangles': faces, 'stl_bytes': len(stl)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('inputs', nargs='+', type=Path)
    parser.add_argument('--url', default='http://127.0.0.1:4318')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.is_relative_to(ROOT):
        parser.error('The private validation report must be outside the source checkout.')
    output.mkdir(parents=True, exist_ok=True)
    report = {'sources': [], 'studies': [], 'passed': False}
    with httpx.Client(base_url=args.url, timeout=360, trust_env=False) as api:
        for number, input_path in enumerate(args.inputs, 1):
            path = input_path.resolve()
            before = digest(path)
            with path.open('rb') as stream:
                response = api.post('/api/import', files=[('files', (path.name, stream, 'application/octet-stream'))])
            response.raise_for_status()
            entries = response.json()['studies']
            groups = references(path) if zipfile.is_zipfile(path) else {}
            for study in entries:
                if not study['supported']:
                    report['studies'].append({'input_number': number, 'study_id': study['id'], 'kind': study['kind'], 'supported': False, 'reason': study.get('reason', '')})
                    continue
                wait(api, api.post(f'/api/studies/{study["id"]}/prepare'))
                if study['kind'] == 'ct':
                    result = verify_ct(api, study, groups)
                else:
                    meta = api.get(f'/api/studies/{study["id"]}/metadata').json()
                    image = api.get(f'/api/studies/{study["id"]}/assets/{meta["file"]}')
                    image.raise_for_status()
                    if not image.content.startswith(b'\x89PNG\r\n\x1a\n'):
                        raise AssertionError('Projection image is not a PNG')
                    result = {'study_id': study['id'], 'kind': 'xray', 'dimensions': [meta['width'], meta['height']], 'png_decoded': True}
                result['input_number'] = number
                report['studies'].append(result)
                print(json.dumps({'input_number': number, 'kind': study['kind'], 'passed': True}), flush=True)
            after = digest(path)
            if before != after:
                raise AssertionError('An original input file changed')
            report['sources'].append({'input_number': number, 'sha256_before': before, 'sha256_after': after, 'unchanged': True})
            del groups
    report['passed'] = True
    (output / 'private-validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': True, 'sources': len(report['sources']), 'studies': len(report['studies'])}))


if __name__ == '__main__':
    main()
