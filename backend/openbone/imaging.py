"""Generic, local medical-image preparation without patient-specific assumptions.

Arrays stored for the viewer use C-order ``[z, y, x]`` with increasing LPS axes.
The source NRRD retains the acquired grid and per-slice calibrated values. Only
the explicitly labelled rendering copy and optional mesh smoothing alter values.
No identifiers from a DICOM header are written into generated metadata.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import struct
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pydicom
from PIL import Image, ImageOps, UnidentifiedImageError
from pydicom.errors import InvalidDicomError
from pydicom.pixels import apply_modality_lut, apply_voi_lut
from scipy.ndimage import gaussian_filter, generate_binary_structure, label
from skimage.measure import marching_cubes


class ImagingError(ValueError):
    """A readable error that never contains input paths or raw DICOM values."""


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
_CT_STORAGE = "1.2.840.10008.5.1.4.1.1.2"
_PROJECTION_MODALITIES = {"CR", "DX", "MG", "RF", "XA", "PX", "IO", "SC", "OT"}
_AXIS_TOL = 1e-4
_POSITION_TOL_MM = 1e-3
# Decoding has a deliberate bound: several floating-point copies may be needed.
MAX_CT_VOXELS = 256_000_000


def _integer(value: object, default: int = 0) -> int:
    try:
        result = int(value)
        return result if result > 0 else default
    except (ValueError, TypeError, OverflowError):
        return default


def _read_dicom(path: Path, *, header_only: bool = False):
    """Read standard DICOM and common preamble-free files, suppressing PHI logs."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return pydicom.dcmread(path, stop_before_pixels=header_only)
    except InvalidDicomError:
        try:
            with path.open("rb") as stream:
                prefix = stream.read(132)
            likely = (
                path.suffix.lower() in {"", ".dcm", ".dicom", ".dic", ".ima"}
                or prefix[:2] in {b"\x02\x00", b"\x08\x00", b"\x00\x02", b"\x00\x08"}
            )
            if not likely:
                raise ImagingError("This file is not a supported DICOM image.")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                dataset = pydicom.dcmread(path, stop_before_pixels=header_only, force=True)
            if not all(hasattr(dataset, tag) for tag in ("SOPClassUID", "Modality", "Rows", "Columns")):
                raise ImagingError("This file is not a supported DICOM image.")
            return dataset
        except ImagingError:
            raise
        except Exception:
            raise ImagingError("The DICOM file could not be read.") from None
    except Exception:
        raise ImagingError("The DICOM file could not be read.") from None


def _resolved_files(root: Path, entry: dict) -> list[Path]:
    root = Path(root).resolve()
    files = entry.get("files")
    if not isinstance(files, list) or not files or not all(isinstance(p, str) for p in files):
        raise ImagingError("No image files were selected.")
    result = []
    for relative in files:
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            raise ImagingError("An imported image is missing or outside the import folder.")
        result.append(candidate)
    return result


def _vector(dataset, name: str, count: int) -> np.ndarray:
    try:
        value = np.asarray(getattr(dataset, name), dtype=np.float64)
        if value.shape != (count,) or not np.isfinite(value).all():
            raise ValueError
        return value
    except Exception:
        raise ImagingError("CT geometry is missing or invalid.") from None


def _rescale(dataset) -> tuple[float, float]:
    try:
        slope = float(dataset.RescaleSlope)
        intercept = float(dataset.RescaleIntercept)
        if not math.isfinite(slope) or not math.isfinite(intercept) or slope == 0:
            raise ValueError
    except Exception:
        raise ImagingError("CT requires valid per-slice rescale slope and intercept.") from None
    if str(getattr(dataset, "RescaleType", "HU")).strip().upper() not in {"", "HU"}:
        raise ImagingError("This CT uses units other than HU and is not supported in this version.")
    if hasattr(dataset, "ModalityLUTSequence"):
        raise ImagingError("CT modality LUT calibration is not supported in this version.")
    return slope, intercept


@dataclass
class _Geometry:
    order: np.ndarray
    shape_zyx: tuple[int, int, int]
    spacing_xyz: np.ndarray
    origin: np.ndarray
    orientation: np.ndarray
    directions: np.ndarray  # acquired column, row, slice unit vectors as columns
    axis_directions: np.ndarray  # signed permutation after roundoff normalization


def _geometry(datasets: list) -> _Geometry:
    if len(datasets) < 2:
        raise ImagingError("A CT volume needs at least two spatially distinct slices.")
    first = datasets[0]
    uid = str(getattr(first, "SeriesInstanceUID", ""))
    if not uid:
        raise ImagingError("CT series identification is missing.")
    rows, columns = _integer(getattr(first, "Rows", 0)), _integer(getattr(first, "Columns", 0))
    if not rows or not columns:
        raise ImagingError("CT image dimensions are invalid.")
    if rows * columns * len(datasets) > MAX_CT_VOXELS:
        raise ImagingError("This CT is too large for this version. Import a smaller series or reconstruction.")
    orientation = _vector(first, "ImageOrientationPatient", 6)
    col_direction, row_direction = orientation[:3], orientation[3:]
    normal = np.cross(col_direction, row_direction)
    directions = np.column_stack((col_direction, row_direction, normal))
    rounded = np.rint(directions)
    if (
        not np.allclose(directions, rounded, atol=_AXIS_TOL, rtol=0)
        or not np.all(np.sum(np.abs(rounded), axis=0) == 1)
        or not np.all(np.sum(np.abs(rounded), axis=1) == 1)
        or not np.isclose(np.linalg.det(directions), 1, atol=_AXIS_TOL, rtol=0)
    ):
        raise ImagingError("Oblique CT orientations are not supported in this version; use an axis-aligned reconstruction.")
    spacing_yx = _vector(first, "PixelSpacing", 2)
    if np.any(spacing_yx <= 0):
        raise ImagingError("CT pixel spacing must be positive.")
    frame = str(getattr(first, "FrameOfReferenceUID", ""))
    positions = []
    for dataset in datasets:
        if _integer(getattr(dataset, "NumberOfFrames", 1)) != 1:
            raise ImagingError("Multi-frame CT is not supported in this version.")
        if str(getattr(dataset, "SOPClassUID", "")) != _CT_STORAGE:
            raise ImagingError("Only conventional single-frame CT images are supported in this version.")
        if str(getattr(dataset, "Modality", "")).upper() != "CT":
            raise ImagingError("Mixed imaging modalities cannot form one CT volume.")
        if str(getattr(dataset, "SeriesInstanceUID", "")) != uid:
            raise ImagingError("Images from different CT series cannot be combined.")
        if str(getattr(dataset, "FrameOfReferenceUID", "")) != frame:
            raise ImagingError("This CT series mixes incompatible coordinate frames.")
        if (_integer(getattr(dataset, "Rows", 0)), _integer(getattr(dataset, "Columns", 0))) != (rows, columns):
            raise ImagingError("This CT series mixes incompatible image dimensions.")
        if _integer(getattr(dataset, "SamplesPerPixel", 1)) != 1:
            raise ImagingError("Only monochrome CT images are supported.")
        if str(getattr(dataset, "PhotometricInterpretation", "")).upper() not in {"MONOCHROME1", "MONOCHROME2"}:
            raise ImagingError("Only monochrome CT images are supported.")
        if not np.allclose(_vector(dataset, "ImageOrientationPatient", 6), orientation, atol=_AXIS_TOL, rtol=0):
            raise ImagingError("This CT series mixes incompatible image orientations.")
        if not np.allclose(_vector(dataset, "PixelSpacing", 2), spacing_yx, atol=1e-5, rtol=1e-4):
            raise ImagingError("This CT series mixes incompatible pixel spacing.")
        try:
            tilt = float(getattr(dataset, "GantryDetectorTilt", 0))
        except (TypeError, ValueError):
            raise ImagingError("CT gantry tilt metadata is invalid.") from None
        if not math.isfinite(tilt) or abs(tilt) > _AXIS_TOL:
            raise ImagingError("Gantry-tilted CT is not supported in this version.")
        image_type = [str(value).upper() for value in getattr(dataset, "ImageType", [])]
        if "LOCALIZER" in image_type or "SCOUT" in image_type:
            raise ImagingError("CT localizer images cannot form a 3D volume.")
        _rescale(dataset)
        positions.append(_vector(dataset, "ImagePositionPatient", 3))
    positions = np.asarray(positions)
    order = np.argsort(positions @ normal, kind="stable")
    positions = positions[order]
    steps = np.diff(positions, axis=0)
    distances = steps @ normal
    spacing_z = float(np.median(distances))
    if spacing_z <= _POSITION_TOL_MM or np.any(distances <= _POSITION_TOL_MM):
        raise ImagingError("CT contains duplicate or overlapping slice positions.")
    if not np.allclose(distances, spacing_z, atol=_POSITION_TOL_MM, rtol=1e-3):
        raise ImagingError("Irregular CT slice spacing is not supported in this version.")
    if not np.allclose(steps, distances[:, None] * normal, atol=_POSITION_TOL_MM, rtol=0):
        raise ImagingError("Tilted or shifted CT slices are not supported in this version.")
    return _Geometry(
        order=order,
        shape_zyx=(len(datasets), rows, columns),
        spacing_xyz=np.array([spacing_yx[1], spacing_yx[0], spacing_z]),
        origin=positions[0],
        orientation=orientation,
        directions=directions,
        axis_directions=rounded,
    )


def _opaque_id(kind: str, key: str) -> str:
    return kind + "_" + hashlib.sha256(key.encode("utf-8", errors="replace")).hexdigest()[:24]


def scan_directory(root: Path) -> list[dict]:
    """Inventory image series using generic labels and opaque, stable identifiers."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise ImagingError("The import folder does not exist.")
    groups: dict[str, list[tuple[str, object]]] = {}
    projections: list[dict] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not path.resolve().is_relative_to(root):
            continue
        relative = path.relative_to(root).as_posix()
        if path.suffix.lower() in _IMAGE_SUFFIXES:
            try:
                with Image.open(path) as image:
                    width, height = image.size
                    image.verify()
                projections.append({
                    "id": _opaque_id("image", relative), "kind": "xray", "label": "Image",
                    "modality": "IMAGE", "count": 1, "rows": height, "columns": width,
                    "files": [relative], "supported": True,
                })
                continue
            except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
                pass
        try:
            dataset = _read_dicom(path, header_only=True)
        except ImagingError:
            if path.suffix.lower() in {".dcm", ".dicom", ".ima"}:
                projections.append({
                    "id": _opaque_id("invalid", relative), "kind": "xray", "label": "DICOM image",
                    "modality": "DICOM", "count": 1, "rows": 0, "columns": 0,
                    "files": [relative], "supported": False, "reason": "The DICOM image could not be read.",
                })
            continue
        if not hasattr(dataset, "Rows") or not hasattr(dataset, "Columns"):
            continue
        modality = str(getattr(dataset, "Modality", "")).upper()
        if modality == "CT":
            uid = str(getattr(dataset, "SeriesInstanceUID", ""))
            key = uid if uid else "missing:" + relative
            groups.setdefault(key, []).append((relative, dataset))
            continue
        supported = modality in _PROJECTION_MODALITIES
        reason = None if supported else "This DICOM imaging modality is not supported in this version."
        if _integer(getattr(dataset, "NumberOfFrames", 1)) != 1:
            supported, reason = False, "Multi-frame DICOM images are not supported in this version."
        entry = {
            "id": _opaque_id("xray", relative), "kind": "xray", "label": "DICOM projection",
            "modality": modality if modality in _PROJECTION_MODALITIES else "DICOM",
            "count": 1, "rows": _integer(getattr(dataset, "Rows", 0)),
            "columns": _integer(getattr(dataset, "Columns", 0)), "files": [relative], "supported": supported,
        }
        if reason:
            entry["reason"] = reason
        projections.append(entry)
    result = []
    for index, (key, images) in enumerate(groups.items(), 1):
        first = images[0][1]
        entry = {
            "id": _opaque_id("ct", key), "kind": "ct", "label": f"CT series {index}",
            "modality": "CT", "count": len(images), "rows": _integer(getattr(first, "Rows", 0)),
            "columns": _integer(getattr(first, "Columns", 0)),
            "files": [relative for relative, _ in images], "supported": True,
        }
        try:
            _geometry([dataset for _, dataset in images])
        except ImagingError as error:
            entry["supported"], entry["reason"] = False, str(error)
        result.append(entry)
    for index, entry in enumerate(projections, 1):
        entry["label"] += f" {index}"
        result.append(entry)
    return result


def _decode_pixels(dataset) -> np.ndarray:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return dataset.pixel_array
    except Exception:
        raise ImagingError(
            "DICOM pixels could not be decoded. The file may be damaged or need a compression decoder (pylibjpeg or GDCM)."
        ) from None


def _write_array_gzip(path: Path, array: np.ndarray, header: bytes = b"") -> None:
    array = np.ascontiguousarray(array)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(header)
        with gzip.GzipFile(fileobj=stream, mode="wb", compresslevel=6, mtime=0) as compressed:
            view = memoryview(array).cast("B")
            for offset in range(0, len(view), 16 * 1024 * 1024):
                compressed.write(view[offset:offset + 16 * 1024 * 1024])
    temporary.replace(path)


def _write_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def _nrrd_header(geometry: _Geometry) -> bytes:
    def vector_text(values):
        return "(" + ",".join(format(float(value), ".17g") for value in values) + ")"
    directions = geometry.directions * geometry.spacing_xyz[np.newaxis, :]
    return ("\n".join([
        "NRRD0005", "# Calibrated acquired CT grid; no interpolation, masking or patient identifiers.",
        "type: float", "dimension: 3", "space: left-posterior-superior",
        "sizes: " + " ".join(map(str, geometry.shape_zyx[::-1])),
        "space directions: " + " ".join(vector_text(directions[:, index]) for index in range(3)),
        "kinds: domain domain domain", "endian: little", "encoding: gzip",
        "space origin: " + vector_text(geometry.origin), "", "",
    ])).encode("ascii")


def _canonicalize(source: np.ndarray, geometry: _Geometry) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    source_directions_zyx = geometry.axis_directions[:, ::-1]
    source_spacing_zyx = geometry.spacing_xyz[::-1]
    source_axis_for_xyz = np.argmax(np.abs(source_directions_zyx), axis=1)
    transpose = tuple(int(value) for value in source_axis_for_xyz[::-1])
    canonical = np.transpose(source, transpose)
    origin = geometry.origin.copy()
    for physical_axis in range(3):
        source_axis = int(source_axis_for_xyz[physical_axis])
        if source_directions_zyx[physical_axis, source_axis] < 0:
            origin += source_directions_zyx[:, source_axis] * source_spacing_zyx[source_axis] * (source.shape[source_axis] - 1)
            canonical = np.flip(canonical, axis=2 - physical_axis)
    spacing_xyz = source_spacing_zyx[source_axis_for_xyz]
    return np.ascontiguousarray(canonical, dtype="<f4"), spacing_xyz, origin


def _mask_largest_tissue_preview(components: np.ndarray, display_u8: np.ndarray) -> list[list[int]] | None:
    """Mask only a reusable display buffer, using a preallocated 0/1 label grid.

    Label in place and count one plane at a time. This avoids a second full-size
    boolean mask and the int64 whole-volume copy made by ``np.bincount``.
    Six-neighbour connectivity deliberately does not join diagonal contacts or
    close gaps. It is a tissue preview, not anatomical or individual-bone
    segmentation; disconnected body parts can be hidden with scanner objects.
    """
    count = label(components, structure=generate_binary_structure(3, 1), output=components)
    if count == 0:
        return None
    sizes = np.zeros(count + 1, dtype=np.uint32)
    for plane in components:
        identifiers, plane_counts = np.unique(plane, return_counts=True)
        sizes[identifiers] += plane_counts.astype(np.uint32)
    largest = int(np.argmax(sizes[1:])) + 1
    del sizes
    nz, ny, nx = components.shape
    lower, upper = [nx, ny, nz], [-1, -1, -1]
    for z, plane in enumerate(components):
        selected = plane == largest
        xs = np.flatnonzero(selected.any(axis=0))
        ys = np.flatnonzero(selected.any(axis=1))
        if len(xs):
            lower = [min(lower[0], int(xs[0])), min(lower[1], int(ys[0])), min(lower[2], z)]
            upper = [max(upper[0], int(xs[-1])), max(upper[1], int(ys[-1])), max(upper[2], z)]
        display_u8[z][~selected] = 0  # 0 maps exactly to the display-only minimum HU.
    return [lower, upper]


def prepare_ct(root: Path, entry: dict, output: Path) -> dict:
    files = _resolved_files(root, entry)
    headers = [_read_dicom(path, header_only=True) for path in files]
    geometry = _geometry(headers)
    source = np.empty(geometry.shape_zyx, dtype="<f4")
    for index, file_index in enumerate(geometry.order):
        dataset = _read_dicom(files[int(file_index)])
        # Validate again so a file changed since scanning cannot silently change the grid.
        expected = headers[int(file_index)]
        if any(str(getattr(dataset, tag, "")) != str(getattr(expected, tag, "")) for tag in (
            "SeriesInstanceUID", "SOPClassUID", "Rows", "Columns", "ImagePositionPatient",
            "ImageOrientationPatient", "PixelSpacing", "NumberOfFrames", "RescaleSlope", "RescaleIntercept",
        )):
            raise ImagingError("A CT image changed during preparation. Import the series again.")
        pixels = _decode_pixels(dataset)
        if pixels.shape != geometry.shape_zyx[1:] or pixels.dtype.kind not in "iuf":
            raise ImagingError("CT pixel dimensions or pixel values are invalid.")
        slope, intercept = _rescale(dataset)
        with np.errstate(over="ignore", invalid="ignore"):
            hu = pixels.astype(np.float64) * slope + intercept
            source[index] = hu.astype("<f4")
        if not np.isfinite(source[index]).all():
            raise ImagingError("CT calibration produced invalid HU values.")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    _write_array_gzip(output / "source.nrrd", source, _nrrd_header(geometry))
    canonical, spacing, origin = _canonicalize(source, geometry)
    del source
    _write_array_gzip(output / "volume.rawz", canonical)
    dimensions = list(map(int, canonical.shape[::-1]))
    hu_min, hu_max = float(canonical.min()), float(canonical.max())
    metadata = {
        "dimensions_xyz": dimensions, "spacing_xyz_mm": spacing.tolist(), "origin_lps_mm": origin.tolist(),
        "source_dimensions_xyz": list(geometry.shape_zyx[::-1]),
        "source_spacing_xyz_mm": geometry.spacing_xyz.tolist(), "source_orientation": geometry.orientation.tolist(),
        "source_origin_lps_mm": geometry.origin.tolist(), "dtype": "float32", "coordinate_system": "LPS",
        "hu_range": [hu_min, hu_max], "hu_array_sha256": hashlib.sha256(memoryview(canonical).cast("B")).hexdigest(),
        "source_file": "source.nrrd", "volume_file": "volume.rawz", "models": [],
        "mpr_interpolation": "None: source HU values reordered by axis permutation and reversal only.",
        "warnings": [
            "3D rendering is a smoothed, quantized display copy; use the original MPR or source NRRD for voxel values.",
            "Threshold surfaces are not anatomical segmentation and may include other bones, casts or scanner supports.",
        ],
    }
    # Smoothing is deliberately limited to a separate 3D display copy. Keep all
    # source slices and the complete field of view, without anatomical masking.
    display_min, display_max = min(-1024.0, hu_min), max(2000.0, hu_max)
    display = gaussian_filter(canonical, sigma=0.45, mode="nearest", output=np.float32)
    display -= display_min
    display *= 255.0 / (display_max - display_min)
    np.rint(display, out=display)
    np.clip(display, 0, 255, out=display)
    display_u8 = display.astype(np.uint8)
    del display
    _write_array_gzip(output / "volume_render.rawz", display_u8)
    metadata["volume_rendering"] = {
        "file": "volume_render.rawz", "dimensions_xyz": dimensions, "spacing_xyz_mm": spacing.tolist(),
        "content_bounds_xyz": [[0, 0, 0], [size - 1 for size in dimensions]],
        "min_hu": display_min, "max_hu": display_max,
        "source": "Display only: Gaussian smoothing (sigma 0.45 source voxels) and 8-bit quantization; full acquired extent, no mask or crop.",
        "smoothing_sigma_voxels": 0.45,
    }
    # Retain the complete display as an independently selectable asset. Only
    # this additional preview hides disconnected structures. Initialize an
    # int32 label grid directly, then release the no-longer-needed HU array
    # before connected-component analysis to limit peak memory.
    components = np.empty(canonical.shape, dtype=np.int32)
    np.greater(canonical, -500.0, out=components)
    del canonical
    body_bounds = _mask_largest_tissue_preview(components, display_u8)
    del components
    if body_bounds is not None:
        preview_warning = "Largest connected tissue preview may hide separate body parts; original MPR unchanged."
        _write_array_gzip(output / "volume_render_body.rawz", display_u8)
        metadata["body_volume_rendering"] = {
            "file": "volume_render_body.rawz", "dimensions_xyz": dimensions,
            "spacing_xyz_mm": spacing.tolist(), "content_bounds_xyz": body_bounds,
            "min_hu": display_min, "max_hu": display_max,
            "source": "Display only: largest 6-connected tissue component above -500 HU, without gap filling or anatomical segmentation; Gaussian smoothing (sigma 0.45 source voxels) and 8-bit quantization. " + preview_warning,
            "smoothing_sigma_voxels": 0.45,
        }
        metadata["warnings"].append(preview_warning)
    _write_json(output / "metadata.json", metadata)
    return metadata


def _normalize_gray(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    if not np.isfinite(values).all():
        raise ImagingError("The image contains invalid display values.")
    low, high = float(values.min()), float(values.max())
    if high <= low:
        return np.zeros(values.shape, dtype=np.uint8)
    return np.clip(np.rint((values - low) * (255.0 / (high - low))), 0, 255).astype(np.uint8)


def prepare_xray(root: Path, entry: dict, output: Path) -> dict:
    files = _resolved_files(root, entry)
    if len(files) != 1:
        raise ImagingError("Select one projection image at a time.")
    path = files[0]
    image = None
    if path.suffix.lower() in _IMAGE_SUFFIXES:
        try:
            with Image.open(path) as original:
                oriented = ImageOps.exif_transpose(original)
                # Medical image exports can be 16-bit PNG/TIFF. RGB conversion
                # would clip these to white instead of mapping their full range.
                if oriented.mode in {"I", "I;16", "I;16L", "I;16B", "F"}:
                    image = Image.fromarray(_normalize_gray(np.asarray(oriented)), mode="L")
                else:
                    image = oriented.convert("RGB")
        except Exception:
            raise ImagingError("The image could not be decoded.") from None
    if image is None:
        dataset = _read_dicom(path)
        if _integer(getattr(dataset, "NumberOfFrames", 1)) != 1:
            raise ImagingError("Multi-frame DICOM images are not supported in this version.")
        if str(getattr(dataset, "Modality", "")).upper() not in _PROJECTION_MODALITIES:
            raise ImagingError("This DICOM imaging modality is not supported as an X-ray image.")
        pixels = _decode_pixels(dataset)
        try:
            if pixels.ndim == 2:
                if str(getattr(dataset, "PhotometricInterpretation", "")).upper() not in {"MONOCHROME1", "MONOCHROME2"}:
                    raise ImagingError("This DICOM color layout is not supported.")
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    calibrated = apply_modality_lut(pixels, dataset)
                    display = apply_voi_lut(calibrated, dataset, index=0)
                gray = _normalize_gray(display)
                if str(getattr(dataset, "PhotometricInterpretation", "")).upper() == "MONOCHROME1":
                    gray = 255 - gray
                image = Image.fromarray(gray, mode="L")
            elif pixels.ndim == 3 and pixels.shape[-1] in (3, 4):
                if pixels.dtype != np.uint8:
                    pixels = _normalize_gray(pixels)
                image = Image.fromarray(pixels[:, :, :3], mode="RGB")
            else:
                raise ImagingError("This DICOM color or frame layout is not supported.")
        except ImagingError:
            raise
        except Exception:
            raise ImagingError("The DICOM display transformation could not be applied.") from None
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    temporary = output / "image.png.tmp"
    # Do not propagate EXIF/text metadata from ordinary image exports. Burned-in
    # annotations remain pixels and are explicitly disclosed in the result.
    image.info.clear()
    image.save(temporary, format="PNG")
    temporary.replace(output / "image.png")
    return {
        "file": "image.png", "width": image.width, "height": image.height,
        "warning": "Images may contain burned-in personal information. Local display does not automatically remove it.",
    }


def _read_volume(output: Path) -> tuple[dict, np.ndarray]:
    try:
        metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
        dimensions = metadata["dimensions_xyz"]
        if len(dimensions) != 3 or any(not isinstance(v, int) or v < 1 for v in dimensions):
            raise ValueError
        count = math.prod(dimensions)
        if count > MAX_CT_VOXELS:
            raise ValueError
        # marching_cubes needs a writable buffer. Read directly into an array
        # instead of retaining a second, immutable decompressed bytes object.
        volume = np.empty(tuple(dimensions[::-1]), dtype="<f4")
        buffer = memoryview(volume).cast("B")
        with gzip.open(output / "volume.rawz", "rb") as stream:
            offset = 0
            while offset < len(buffer):
                size = stream.readinto(buffer[offset:offset + 16 * 1024 * 1024])
                if not size:
                    raise ValueError
                offset += size
            if stream.read(1):
                raise ValueError
        if not np.isfinite(volume).all():
            raise ValueError
        return metadata, volume
    except Exception:
        raise ImagingError("The prepared CT volume is missing or damaged. Prepare the series again.") from None


def _write_stl(path: Path, vertices: np.ndarray, faces: np.ndarray) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(b"OpenBone threshold surface; RAS millimeters".ljust(80, b"\0"))
        stream.write(struct.pack("<I", len(faces)))
        dtype = np.dtype([("normal", "<f4", (3,)), ("vertices", "<f4", (3, 3)), ("attribute", "<u2")])
        for start in range(0, len(faces), 65536):
            triangles = vertices[faces[start:start + 65536]]
            normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
            lengths = np.linalg.norm(normals, axis=1)
            normals /= np.maximum(lengths, np.finfo(np.float32).tiny)[:, None]
            records = np.zeros(len(triangles), dtype=dtype)
            records["normal"], records["vertices"] = normals, triangles
            stream.write(records.tobytes())
    temporary.replace(path)


def build_mesh(output: Path, threshold: float, smooth: bool = False, roi: list[int] | None = None) -> dict:
    try:
        threshold = float(threshold)
        if not math.isfinite(threshold):
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        raise ImagingError("The surface threshold must be a finite HU value.") from None
    output = Path(output)
    metadata, volume = _read_volume(output)
    nx, ny, nz = metadata["dimensions_xyz"]
    if roi is None:
        selected_roi = [0, nx - 1, 0, ny - 1, 0, nz - 1]
    else:
        if not isinstance(roi, list) or len(roi) != 6 or any(type(value) is not int for value in roi):
            raise ImagingError("Surface ROI must contain six inclusive integer voxel bounds.")
        selected_roi = list(roi)
    xmin, xmax, ymin, ymax, zmin, zmax = selected_roi
    if not (0 <= xmin < xmax < nx and 0 <= ymin < ymax < ny and 0 <= zmin < zmax < nz):
        raise ImagingError("Surface ROI must stay inside the volume and span at least two voxels on each axis.")
    try:
        spacing = np.asarray(metadata["spacing_xyz_mm"], dtype=float)
        origin = np.asarray(metadata["origin_lps_mm"], dtype=float)
        if spacing.shape != (3,) or origin.shape != (3,) or not np.isfinite(spacing).all() or not np.isfinite(origin).all() or np.any(spacing <= 0):
            raise ValueError
    except Exception:
        raise ImagingError("The prepared CT geometry is invalid. Prepare the series again.") from None
    surface = volume[zmin:zmax + 1, ymin:ymax + 1, xmin:xmax + 1]
    if smooth:
        surface = gaussian_filter(surface, sigma=0.6 / spacing[::-1], mode="nearest", output=np.float32)
    else:
        surface = np.ascontiguousarray(surface)
    if not float(surface.min()) < threshold < float(surface.max()):
        raise ImagingError("This threshold has no surface in the selected volume. Choose another HU threshold or ROI.")
    try:
        vertices_zyx, faces, _, _ = marching_cubes(
            surface, level=threshold, spacing=tuple(spacing[::-1]), allow_degenerate=False,
        )
    except (ValueError, RuntimeError):
        raise ImagingError("No surface could be generated at this threshold. Choose another threshold or ROI.") from None
    if not len(vertices_zyx) or not len(faces):
        raise ImagingError("No surface could be generated at this threshold.")
    vertices_lps = vertices_zyx[:, ::-1] + origin + np.array([xmin, ymin, zmin]) * spacing
    vertices = (vertices_lps * np.array([-1, -1, 1])).astype("<f4")
    # skimage's default descent ordering becomes outward with the zyx -> xyz
    # reversal. The two additional LPS -> RAS sign flips preserve this winding.
    faces = faces.astype("<u4")
    signature = json.dumps([threshold, bool(smooth), selected_roi], separators=(",", ":"))
    stem = "mesh_" + hashlib.sha256(signature.encode("ascii")).hexdigest()[:16]
    mesh_file, stl_file = stem + ".meshz", stem + ".stl"
    temporary = output / (mesh_file + ".tmp")
    with temporary.open("wb") as stream:
        with gzip.GzipFile(fileobj=stream, mode="wb", compresslevel=6, mtime=0) as compressed:
            compressed.write(struct.pack("<III", 0x314D5443, len(vertices), len(faces)))
            compressed.write(memoryview(vertices).cast("B"))
            compressed.write(memoryview(faces).cast("B"))
    temporary.replace(output / mesh_file)
    _write_stl(output / stl_file, vertices, faces)
    model = {
        "threshold_hu": threshold, "vertices": len(vertices), "triangles": len(faces),
        "mesh_file": mesh_file, "stl_file": stl_file, "smoothing": bool(smooth),
        "smoothing_sigma_mm": 0.6 if smooth else 0.0, "roi": selected_roi,
        "coordinate_system": "RAS", "units": "mm",
    }
    models = [old for old in metadata.get("models", []) if old.get("mesh_file") != mesh_file]
    metadata["models"] = models + [model]
    _write_json(output / "metadata.json", metadata)
    return model
