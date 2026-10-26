"""Small, synthetic DICOM fixtures; no patient data or network downloads."""

import gzip
import hashlib
import itertools
import struct
from pathlib import Path

import numpy as np
import pydicom
import pytest
from PIL import Image
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, DigitalXRayImageStorageForPresentation, ExplicitVRLittleEndian, generate_uid

from openbone.imaging import ImagingError, build_mesh, prepare_ct, prepare_xray, scan_directory


def write_dicom(path, pixels, *, modality="CT", series_uid=None, orientation=(1, 0, 0, 0, 1, 0),
                position=(0, 0, 0), spacing=(1.0, 1.0), slope=1.0, intercept=0.0,
                photometric="MONOCHROME2", overrides=None):
    pixels = np.asarray(pixels, dtype="<i2")
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = CTImageStorage if modality == "CT" else DigitalXRayImageStorageForPresentation
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    dataset = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
    dataset.SOPClassUID = file_meta.MediaStorageSOPClassUID
    dataset.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    dataset.Modality = modality
    dataset.SeriesInstanceUID = series_uid or generate_uid()
    dataset.PatientName = "PRIVATE^TEST_PERSON"
    dataset.PatientID = "PRIVATE-TEST-ID"
    dataset.SeriesDescription = "PRIVATE_TEST_DESCRIPTION"
    dataset.Rows, dataset.Columns = pixels.shape
    dataset.SamplesPerPixel = 1
    dataset.PhotometricInterpretation = photometric
    dataset.PixelRepresentation = 1
    dataset.BitsAllocated = 16
    dataset.BitsStored = 16
    dataset.HighBit = 15
    dataset.ImageOrientationPatient = list(orientation)
    dataset.ImagePositionPatient = list(position)
    dataset.PixelSpacing = list(spacing)
    dataset.RescaleSlope = slope
    dataset.RescaleIntercept = intercept
    dataset.RescaleType = "HU" if modality == "CT" else "US"
    dataset.PixelData = pixels.tobytes()
    if overrides:
        for name, value in overrides.items():
            setattr(dataset, name, value)
    dataset.save_as(path, enforce_file_format=True)
    return dataset


def write_ct(root, volume, *, orientation=(1, 0, 0, 0, 1, 0), spacing=(0.7, 1.2, 2.5),
             origin=(10.0, 20.0, 30.0), rescales=None, positions=None):
    root.mkdir(parents=True, exist_ok=True)
    series_uid = generate_uid()
    normal = np.cross(orientation[:3], orientation[3:])
    source_hu = np.empty_like(volume, dtype="<f4")
    paths = []
    for index, plane in enumerate(volume):
        # File names and instance numbers deliberately oppose physical ordering.
        path = root / f"slice_{len(volume) - index:03d}.dcm"
        slope, intercept = rescales[index] if rescales else (1.0, 0.0)
        position = positions[index] if positions is not None else np.asarray(origin) + normal * spacing[2] * index
        write_dicom(path, plane, series_uid=series_uid, orientation=orientation, position=position,
                    spacing=(spacing[1], spacing[0]), slope=slope, intercept=intercept,
                    overrides={"InstanceNumber": len(volume) - index})
        source_hu[index] = np.asarray(plane, dtype=float) * slope + intercept
        paths.append(path)
    return paths, source_hu


def read_raw(output, metadata):
    return np.frombuffer(gzip.decompress((output / "volume.rawz").read_bytes()), dtype="<f4").reshape(metadata["dimensions_xyz"][::-1])


def expected_canonical(source, orientation, spacing, origin):
    """Independent physical-coordinate placement, without transpose logic."""
    col = np.asarray(orientation[:3])
    row = np.asarray(orientation[3:])
    normal = np.cross(col, row)
    points = []
    for z, y, x in np.ndindex(source.shape):
        points.append(np.asarray(origin) + x * spacing[0] * col + y * spacing[1] * row + z * spacing[2] * normal)
    points = np.array(points)
    low = points.min(axis=0)
    canonical_spacing = np.abs(np.column_stack((col, row, normal))) @ np.asarray(spacing)
    indices = np.rint((points - low) / canonical_spacing).astype(int)
    shape = tuple((indices.max(axis=0) + 1)[::-1])
    expected = np.empty(shape, dtype="<f4")
    for point, value in zip(indices, source.ravel()):
        expected[tuple(point[::-1])] = value
    return expected, canonical_spacing, low


ORIENTATIONS = []
for first_axis, second_axis in itertools.permutations(range(3), 2):
    for first_sign, second_sign in itertools.product((-1, 1), repeat=2):
        first, second = np.zeros(3), np.zeros(3)
        first[first_axis], second[second_axis] = first_sign, second_sign
        ORIENTATIONS.append(tuple(first) + tuple(second))


@pytest.mark.parametrize("orientation", ORIENTATIONS)
def test_signed_permutations_preserve_hu_and_physical_geometry(tmp_path, orientation):
    root, output = tmp_path / "input", tmp_path / "prepared"
    pixels = np.arange(4 * 3 * 5, dtype=np.int16).reshape(4, 3, 5)
    spacing, origin = (0.7, 1.2, 2.5), (10.0, 20.0, 30.0)
    rescales = [(0.5 + index * 0.25, -1024 + index * 10) for index in range(4)]
    paths, source_hu = write_ct(root, pixels, orientation=orientation, spacing=spacing, origin=origin, rescales=rescales)
    original_hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    entries = scan_directory(root)
    assert len(entries) == 1 and entries[0]["supported"]
    metadata = prepare_ct(root, entries[0], output)
    canonical = read_raw(output, metadata)
    expected, expected_spacing, expected_origin = expected_canonical(source_hu, orientation, spacing, origin)
    np.testing.assert_array_equal(canonical, expected)
    np.testing.assert_allclose(metadata["spacing_xyz_mm"], expected_spacing, atol=1e-8)
    np.testing.assert_allclose(metadata["origin_lps_mm"], expected_origin, atol=1e-8)
    assert metadata["dtype"] == "float32"
    assert metadata["source_dimensions_xyz"] == [5, 3, 4]
    assert metadata["source_orientation"] == list(orientation)
    source_header, source_gzip = (output / "source.nrrd").read_bytes().split(b"\n\n", 1)
    assert b"space: left-posterior-superior" in source_header
    assert b"sizes: 5 3 4" in source_header
    assert b"PRIVATE" not in source_header
    source_from_nrrd = np.frombuffer(gzip.decompress(source_gzip), dtype="<f4").reshape(source_hu.shape)
    np.testing.assert_array_equal(source_from_nrrd, source_hu)
    assert original_hashes == [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    rendering = metadata["volume_rendering"]
    assert rendering["dimensions_xyz"] == metadata["dimensions_xyz"]
    assert rendering["content_bounds_xyz"] == [[0, 0, 0], [value - 1 for value in metadata["dimensions_xyz"]]]
    assert len(gzip.decompress((output / rendering["file"]).read_bytes())) == canonical.size
    assert "PRIVATE" not in str(metadata)
    assert "PRIVATE" not in str({key: value for key, value in entries[0].items() if key != "files"})


@pytest.mark.parametrize("failure", ["irregular", "duplicate", "tilt", "oblique", "orientation", "spacing", "dimensions", "multiframe", "units", "rescale"])
def test_unsupported_ct_is_reported_without_private_values(tmp_path, failure):
    root = tmp_path / "input"
    pixels = np.zeros((4, 3, 5), dtype=np.int16)
    paths, _ = write_ct(root, pixels, spacing=(1, 1, 1))
    dataset = pydicom.dcmread(paths[2])
    if failure == "irregular":
        dataset.ImagePositionPatient = [10, 20, 32.25]
    elif failure == "duplicate":
        dataset.ImagePositionPatient = [10, 20, 31]
    elif failure == "tilt":
        dataset.ImagePositionPatient = [10.1, 20, 32]
    elif failure == "oblique":
        for path in paths:
            changed = pydicom.dcmread(path)
            changed.ImageOrientationPatient = [0.9998, 0.02, 0, -0.02, 0.9998, 0]
            changed.save_as(path, enforce_file_format=True)
        dataset = pydicom.dcmread(paths[2])
    elif failure == "orientation":
        dataset.ImageOrientationPatient = [-1, 0, 0, 0, -1, 0]
    elif failure == "spacing":
        dataset.PixelSpacing = [1.1, 1]
    elif failure == "dimensions":
        dataset.Rows = 4
    elif failure == "multiframe":
        dataset.NumberOfFrames = 2
    elif failure == "units":
        dataset.RescaleType = "PRIVATE_TEST_UNIT"
    elif failure == "rescale":
        dataset.RescaleSlope = 0
    dataset.save_as(paths[2], enforce_file_format=True)
    entries = scan_directory(root)
    assert len(entries) == 1  # one UID must never silently split incompatible geometry
    assert entries[0]["supported"] is False
    assert "PRIVATE" not in entries[0]["reason"]
    with pytest.raises(ImagingError) as error:
        prepare_ct(root, entries[0], tmp_path / "output")
    assert "PRIVATE" not in str(error.value)
    assert str(tmp_path) not in str(error.value)


def test_single_slice_and_gantry_tilt_rejected(tmp_path):
    root = tmp_path / "input"
    root.mkdir()
    write_dicom(root / "single.dcm", np.zeros((4, 4), dtype=np.int16))
    assert scan_directory(root)[0]["supported"] is False
    other = tmp_path / "tilted"
    paths, _ = write_ct(other, np.zeros((3, 4, 4), dtype=np.int16))
    for path in paths:
        dataset = pydicom.dcmread(path)
        dataset.GantryDetectorTilt = 10
        dataset.save_as(path, enforce_file_format=True)
    assert scan_directory(other)[0]["supported"] is False


def test_missing_calibration_is_not_assumed_hu(tmp_path):
    root = tmp_path / "input"
    paths, _ = write_ct(root, np.zeros((3, 4, 4), dtype=np.int16))
    dataset = pydicom.dcmread(paths[1])
    del dataset.RescaleIntercept
    dataset.save_as(paths[1], enforce_file_format=True)
    assert scan_directory(root)[0]["supported"] is False


@pytest.mark.parametrize("photometric", ["MONOCHROME1", "MONOCHROME2"])
def test_projection_dicom_voi_and_monochrome_inversion(tmp_path, photometric):
    root, output = tmp_path / "input", tmp_path / "output"
    root.mkdir()
    pixels = np.arange(6, dtype=np.int16).reshape(2, 3)
    write_dicom(root / "xray.dcm", pixels, modality="DX", photometric=photometric,
                overrides={"WindowCenter": 3, "WindowWidth": 3})
    entry = scan_directory(root)[0]
    assert entry["kind"] == "xray" and entry["supported"]
    metadata = prepare_xray(root, entry, output)
    assert metadata["width"] == 3 and metadata["height"] == 2
    with Image.open(output / "image.png") as image:
        displayed = np.asarray(image)
    if photometric == "MONOCHROME2":
        assert displayed[0, 0] == 0 and displayed[-1, -1] == 255
        assert displayed[0, 1] == 0  # VOI clamps below the window, not plain min/max scaling.
    else:
        assert displayed[0, 0] == 255 and displayed[-1, -1] == 0
    assert "burned-in" in metadata["warning"]


def test_ordinary_image_and_unsupported_modality(tmp_path):
    root = tmp_path / "input"
    root.mkdir()
    rgb = np.zeros((8, 12, 3), dtype=np.uint8)
    rgb[:, :, 0] = 125
    Image.fromarray(rgb).save(root / "photo.png")
    write_dicom(root / "mr.dcm", np.zeros((4, 4), dtype=np.int16), modality="MR")
    entries = scan_directory(root)
    image_entry = next(entry for entry in entries if entry["modality"] == "IMAGE")
    assert image_entry["supported"]
    prepare_xray(root, image_entry, tmp_path / "image_out")
    with Image.open(tmp_path / "image_out" / "image.png") as image:
        np.testing.assert_array_equal(np.asarray(image), rgb)
    assert next(entry for entry in entries if entry["modality"] == "DICOM")["supported"] is False


def test_path_traversal_rejected(tmp_path):
    root = tmp_path / "input"
    root.mkdir()
    Image.new("RGB", (2, 2)).save(tmp_path / "outside.png")
    with pytest.raises(ImagingError, match="outside"):
        prepare_xray(root, {"files": ["../outside.png"]}, tmp_path / "output")


def test_16bit_image_display_and_exif_are_handled(tmp_path):
    root = tmp_path / "input"
    root.mkdir()
    pixels = np.array([[0, 1000], [2000, 4000]], dtype=np.uint16)
    exif = Image.Exif()
    exif[315] = "PRIVATE_TEST_AUTHOR"
    Image.fromarray(pixels).save(root / "sixteen.png", exif=exif)
    prepare_xray(root, scan_directory(root)[0], tmp_path / "output")
    with Image.open(tmp_path / "output" / "image.png") as image:
        assert image.getexif().get(315) is None
        np.testing.assert_array_equal(np.asarray(image), [[0, 64], [128, 255]])


def test_mesh_ras_millimeters_roi_stl_and_source_preservation(tmp_path):
    root, output = tmp_path / "input", tmp_path / "output"
    pixels = np.zeros((7, 8, 9), dtype=np.int16)
    pixels[2:5, 2:6, 2:7] = 1000
    write_ct(root, pixels, spacing=(0.5, 1.5, 2), origin=(10, 20, 30))
    metadata = prepare_ct(root, scan_directory(root)[0], output)
    hashes = {name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in ("volume.rawz", "source.nrrd")}
    # A full-volume, unsmoothed mesh must work without an ROI-triggered copy.
    whole_volume_model = build_mesh(output, 500)
    assert whole_volume_model["vertices"] > 0
    assert whole_volume_model["smoothing"] is False
    model = build_mesh(output, 500, roi=[1, 7, 1, 6, 1, 5])
    raw = gzip.decompress((output / model["mesh_file"]).read_bytes())
    magic, vertex_count, face_count = struct.unpack_from("<III", raw)
    assert magic == 0x314D5443
    assert vertex_count == model["vertices"] and face_count == model["triangles"]
    vertices = np.frombuffer(raw, dtype="<f4", count=vertex_count * 3, offset=12).reshape(-1, 3)
    faces = np.frombuffer(raw, dtype="<u4", count=face_count * 3, offset=12 + vertex_count * 12).reshape(-1, 3)
    np.testing.assert_allclose(vertices.min(axis=0), [-13.25, -28.25, 33], atol=1e-5)
    np.testing.assert_allclose(vertices.max(axis=0), [-10.75, -22.25, 39], atol=1e-5)
    assert faces.max() < len(vertices)
    triangles = vertices[faces]
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    outward = triangles.mean(axis=1) - vertices.mean(axis=0)
    assert np.all(np.sum(normals * outward, axis=1) > 0)
    stl = (output / model["stl_file"]).read_bytes()
    assert len(stl) == 84 + 50 * face_count
    assert struct.unpack_from("<I", stl, 80)[0] == face_count
    assert b"RAS millimeters" in stl[:80]
    build_mesh(output, 500, smooth=True)
    for name, digest in hashes.items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
    np.testing.assert_array_equal(read_raw(output, metadata), pixels.astype(np.float32))
    with pytest.raises(ImagingError, match="no surface"):
        build_mesh(output, 2000)
    with pytest.raises(ImagingError, match="ROI"):
        build_mesh(output, 500, roi=[0, 99, 0, 7, 0, 6])
    with pytest.raises(ImagingError, match="finite"):
        build_mesh(output, float("nan"))


def test_tissue_preview_hides_independent_plate_without_changing_source(tmp_path):
    root, output = tmp_path / "input", tmp_path / "output"
    pixels = np.full((9, 12, 14), -1000, dtype=np.int16)
    pixels[2:8, 2:8, 3:10] = 50  # continuous soft-tissue body, not a bone threshold
    pixels[3:7, 3:7, 4:9] = 1000  # internal bone stays part of the same component
    pixels[1:8, 10:11, 1:13] = 500  # disconnected, thinner scanner-support plate
    pixels[1:3, 1:3, 11:13] = 800  # a separate body part is also hidden: disclose it
    paths, source_hu = write_ct(root, pixels)
    source_hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    metadata = prepare_ct(root, scan_directory(root)[0], output)
    full = np.frombuffer(gzip.decompress((output / "volume_render.rawz").read_bytes()), dtype=np.uint8).reshape(pixels.shape)
    preview_meta = metadata["body_volume_rendering"]
    preview = np.frombuffer(gzip.decompress((output / preview_meta["file"]).read_bytes()), dtype=np.uint8).reshape(pixels.shape)
    assert preview_meta["dimensions_xyz"] == metadata["dimensions_xyz"]
    assert preview_meta["spacing_xyz_mm"] == metadata["spacing_xyz_mm"]
    assert preview_meta["content_bounds_xyz"] == [[3, 2, 2], [9, 7, 7]]
    assert preview_meta["min_hu"] == metadata["volume_rendering"]["min_hu"]
    assert preview_meta["max_hu"] == metadata["volume_rendering"]["max_hu"]
    assert full[4, 10, 6] > 0 and preview[4, 10, 6] == 0
    assert full[1, 1, 11] > 0 and preview[1, 1, 11] == 0
    expected_body = np.zeros(pixels.shape, dtype=bool)
    expected_body[2:8, 2:8, 3:10] = True
    np.testing.assert_array_equal(preview[expected_body], full[expected_body])
    assert not preview[~expected_body].any()
    warning = "Largest connected tissue preview may hide separate body parts; original MPR unchanged."
    assert warning in metadata["warnings"] and warning in preview_meta["source"]
    np.testing.assert_array_equal(read_raw(output, metadata), source_hu)
    _, source_gzip = (output / "source.nrrd").read_bytes().split(b"\n\n", 1)
    np.testing.assert_array_equal(np.frombuffer(gzip.decompress(source_gzip), dtype="<f4").reshape(pixels.shape), source_hu)
    assert source_hashes == [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    model = build_mesh(output, 250)
    model_data = gzip.decompress((output / model["mesh_file"]).read_bytes())
    _, vertex_count, _ = struct.unpack_from("<III", model_data)
    vertices = np.frombuffer(model_data, dtype="<f4", count=vertex_count * 3, offset=12).reshape(-1, 3)
    # Mesh still includes the support plate beyond the preview's tissue bbox.
    assert vertices[:, 1].min() < -(20 + 10 * 1.2)
    np.testing.assert_array_equal(read_raw(output, metadata), source_hu)


def test_empty_tissue_preview_is_omitted(tmp_path):
    root, output = tmp_path / "input", tmp_path / "output"
    write_ct(root, np.full((3, 4, 5), -1000, dtype=np.int16))
    metadata = prepare_ct(root, scan_directory(root)[0], output)
    assert "body_volume_rendering" not in metadata
    assert not (output / "volume_render_body.rawz").exists()
    assert (output / "volume_render.rawz").is_file()
