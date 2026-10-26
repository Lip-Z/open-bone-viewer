# Architecture and data boundaries

## Runtime

The Python service binds loopback only. It serves a built React application and `/api` on one origin. The frontend does not need a cloud service, an account, a database server or a hospital PACS.

Import -> private upload group -> DICOM series discovery -> explicit series selection -> validated decoding -> prepared private data -> browser viewing.

Large preparation and mesh jobs are serialized. Source code and runtime data must be stored in different directories. Assets are addressed by opaque study IDs; arbitrary paths and original DICOM uploads are not exposed as browser-download endpoints.

## CT geometry

Conventional CT is grouped by SeriesInstanceUID, sorted by position projected onto the slice normal, and checked for a consistent rectangular grid. Repeated slice positions, orientation/spacing changes, non-monochrome pixels, unsupported multi-frame data and irregular or tilted geometry are rejected.

The source volume retains per-slice rescale and full LPS spatial directions in `source.nrrd`. Supported axis-aligned signed-permutation grids are reordered without interpolation to an increasing LPS XYZ grid for MPR. `volume.rawz` contains gzip-compressed little-endian float32 values in Z/Y/X C order. This avoids assuming integer rescale results.

MPR uses the exact canonical HU data. Any smoothing or uint8 quantization for GPU rendering is a display-derived path; it never overwrites MPR/source NRRD. In v0.1 oblique volumes are rejected, not silently relabeled.

A separately selectable body preview retains the largest six-connected tissue component above -500 HU. This can hide separate scanner objects and separate body parts; it is explicitly labeled, can be disabled, and never modifies the complete rendering, MPR, source NRRD or surface-extraction input. It is not an anatomical segmentation and cannot reliably remove objects attached to the body.

## Surface models

Surface extraction uses a chosen HU threshold and optional explicit voxel ROI. Vertices are converted to RAS physical millimeters. `.meshz` contains a 12-byte little-endian header (magic `0x314d5443`, vertex count, triangle count), then float32 XYZ vertices and uint32 triangle indices, all gzip compressed. Binary STL exports the same geometry in millimeters.

A threshold surface may contain several bones and external objects. It is not an anatomical segmentation and is not evidence of cartilage geometry or subvoxel detail. No case-specific anatomical crops or automatic clinical measurements are included.

## Projection images

Projection DICOM is decoded, transformed for display and exported to PNG. The image is a display representation rather than preserved original detector data. MONOCHROME1 is handled explicitly. Ordinary image import strips file metadata through image re-encoding but does not erase text in the pixels. No output should be described as automatically anonymized.

## Release boundary

Only source, manifests, lockfiles, documentation and synthetic-data generators belong in a release. Private import directories, generated volumes/models, source zips, screenshots, caches and installed environments do not. Real-data validation reports should contain only aggregate technical results and source-preservation hashes, and should be reviewed before publication.
