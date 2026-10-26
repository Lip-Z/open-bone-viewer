"""Deterministic synthetic geometry; this module contains no patient data."""

from pathlib import Path

import numpy as np
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import (
    CTImageStorage,
    ComputedRadiographyImageStorage,
    ExplicitVRLittleEndian,
    PYDICOM_IMPLEMENTATION_UID,
    generate_uid,
)


def _dataset(path: Path, sop_class: str, study_uid: str, series_uid: str) -> FileDataset:
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = sop_class
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.ImplementationClassUID = PYDICOM_IMPLEMENTATION_UID
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = sop_class
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.Manufacturer = "OpenBone synthetic demo"
    ds.ImageType = ["DERIVED", "SECONDARY"]
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    return ds


def generate_demo(root: Path) -> None:
    """Write a small conventional CT series and a projection DICOM phantom."""
    root.mkdir(parents=True, exist_ok=True)
    study_uid, series_uid = generate_uid(), generate_uid()
    z, y, x = np.indices((48, 64, 64), dtype=np.float32)
    body = ((x - 31.5) / 28) ** 2 + ((y - 31.5) / 24) ** 2 + ((z - 23.5) / 25) ** 2
    outer = ((x - 25) / 13) ** 2 + ((y - 31) / 17) ** 2 + ((z - 23) / 20) ** 2
    inner = ((x - 25) / 10) ** 2 + ((y - 31) / 13) ** 2 + ((z - 23) / 17) ** 2
    second = ((x - 47) / 5) ** 2 + ((y - 31) / 8) ** 2 + ((z - 22) / 15) ** 2
    volume = np.full((48, 64, 64), -1000, dtype=np.int16)
    volume[body < 1] = 40
    volume[outer < 1] = 900
    volume[inner < 1] = 150
    volume[second < 1] = 1200
    for index, plane in enumerate(volume):
        path = root / f"ct_{index:03d}.dcm"
        ds = _dataset(path, CTImageStorage, study_uid, series_uid)
        ds.Modality = "CT"
        ds.SeriesNumber = 1
        ds.InstanceNumber = index + 1
        ds.Rows, ds.Columns = plane.shape
        ds.PixelRepresentation = 1
        ds.PixelSpacing = [0.8, 0.8]
        ds.SliceThickness = 1.1
        ds.SpacingBetweenSlices = 1.1
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.ImagePositionPatient = [-25.2, -25.2, -25.85 + index * 1.1]
        ds.RescaleSlope = 1
        ds.RescaleIntercept = 0
        ds.WindowCenter = 350
        ds.WindowWidth = 1500
        ds.PixelData = plane.astype("<i2").tobytes()
        ds.save_as(path, enforce_file_format=True)
    yy, xx = np.indices((256, 256), dtype=np.float32)
    radial = ((xx - 127.5) / 90) ** 2 + ((yy - 127.5) / 105) ** 2
    projection = np.clip(200 + 1600 * np.maximum(0, 1 - radial), 0, 4095)
    projection[(radial > 0.62) & (radial < 0.8)] += 1200
    path = root / "projection.dcm"
    ds = _dataset(path, ComputedRadiographyImageStorage, study_uid, generate_uid())
    ds.Modality = "CR"
    ds.SeriesNumber = 2
    ds.InstanceNumber = 1
    ds.Rows, ds.Columns = projection.shape
    ds.PixelRepresentation = 0
    ds.PixelSpacing = [0.5, 0.5]
    ds.WindowCenter = 1800
    ds.WindowWidth = 3600
    ds.PixelData = projection.astype("<u2").tobytes()
    ds.save_as(path, enforce_file_format=True)
