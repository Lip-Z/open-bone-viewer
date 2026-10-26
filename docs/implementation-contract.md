# Internal implementation contract

OpenBone Viewer is a local-only Python/FastAPI service and React/Vite UI. Source code lives in this directory. Imported and generated medical data must live outside the source tree, under `OPENBONE_DATA_DIR` or a per-user application-data directory.

## Imaging module (`backend/openbone/imaging.py`)

- `scan_directory(root: Path) -> list[dict]`: recursively inspect DICOM and ordinary PNG/JPEG/WebP/BMP images, group conventional CT by SeriesInstanceUID, return entries with `id`, `kind` (`ct` or `xray`), `label` (generic, no patient identifiers), `modality`, `count`, `rows`, `columns`, `files` (relative paths), `supported` and optional `reason`. Each projection DICOM or ordinary image is a separate xray entry. Skip non-images and report unsupported series clearly. IDs must be safe opaque strings. Never extract raw patient tags into public metadata.
- `prepare_ct(root: Path, entry: dict, output: Path) -> dict`: validate geometry, decode and apply per-slice rescale, spatially sort, normalize supported signed-permutation orientations to increasing LPS XYZ. Reject oblique/tilted/irregular/multi-frame data explicitly in v0.1. Preserve original HU/geometry in `source.nrrd`. Store canonical MPR float32 LE in gzip `volume.rawz`, display-only uint8 in gzip `volume_render.rawz`, and `metadata.json`. No case-specific masks/crops. Metadata: `dimensions_xyz`, `spacing_xyz_mm`, `origin_lps_mm`, `source_dimensions_xyz`, `source_spacing_xyz_mm`, `source_orientation`, `dtype: 'float32'`, `volume_rendering: {file, dimensions_xyz, spacing_xyz_mm, content_bounds_xyz, min_hu, max_hu, source}`, `models: []`, and optional `warnings`. `volume.rawz` is exact canonical source HU; display processing must not alter it.
- `prepare_xray(root: Path, entry: dict, output: Path) -> dict`: decode DICOM including MONOCHROME1, apply display VOI, or decode ordinary image, produce `image.png` and return `{file, width, height, warning?}`. Do not claim to remove burned-in identifiers.
- CT metadata may additionally contain `body_volume_rendering`, with the same schema as `volume_rendering`, pointing to `volume_render_body.rawz`. This separately selectable largest-connected-tissue preview affects only display and may hide separate body parts; it does not change the canonical HU, NRRD or mesh input.
- `build_mesh(output: Path, threshold: float, smooth: bool = False, roi: list[int] | None = None) -> dict`: load MPR volume, optional ROI `[xmin,xmax,ymin,ymax,zmin,zmax]` inclusive voxel bounds, create threshold isosurface without anatomical assertions. Mesh uses RAS physical millimeters. Gzip `.meshz` is uint32 magic `0x314d5443`, uint32 vertex count, uint32 face count, float32 XYZ vertices then uint32 face indices. Also generate binary STL in physical mm. Return `{threshold_hu, vertices, triangles, mesh_file, stl_file, smoothing, roi}`. Empty surfaces must yield a readable error.
- `ImagingError` exception with readable user-safe text.

## HTTP API (`backend/openbone/app.py`)

- `GET /api/health` -> `{status:'ok', version:'0.1.0', local_only:true}`.
- `GET /api/studies` -> `{studies: Study[]}`.
- `POST /api/import` multipart repeated `files` (ZIP, DICOM, images; directory upload paths accepted) -> `{studies: Study[], warnings: string[]}`. Save uploads in runtime directory, securely unpack ZIP, scan, persist manifests. Study `{id, kind, label, modality, count, rows, columns, supported, reason?, ready}`. IDs should combine import group plus entry ID to prevent collisions.
- `POST /api/demo` -> same response as import; creates only synthetic phantom data.
- `POST /api/studies/{id}/prepare` -> `{id: jobId, status:'queued'}`; process in background and persist; xray preparation same endpoint.
- `GET /api/jobs/{id}` -> `{id, status:'queued'|'running'|'done'|'error', message, result?: {study_id, metadata?, image?}}`. Catch errors without returning file paths or raw DICOM values. Serialize memory-heavy preparation jobs.
- `GET /api/studies/{id}/metadata` -> CT metadata or xray image metadata (prepared only).
- `POST /api/studies/{id}/mesh` JSON `{threshold: number, smooth: boolean, roi?: number[6]}` -> job; result `{study_id, model}`.
- `GET /api/studies/{id}/assets/{filename}` -> strictly allowlisted prepared files, including `source.nrrd`; MIME application/octet-stream for `.rawz/.meshz/.stl/.nrrd`; no `Content-Encoding: gzip` for custom compressed assets.
- `DELETE /api/studies/{id}` -> `{ok:true}`; delete only runtime files belonging to the selected study, keep source uploads if shared by another study.

Serve the built frontend from `frontend/dist` with a same-origin SPA fallback. Reject non-loopback Host and cross-origin write requests; no wildcard CORS. Default port 4318. Application factory `create_app(data_dir: Path | None = None)` supports isolated tests. `app = create_app()` for uvicorn. Add a synthetic demo through a module `backend/openbone/demo.py` (API agent owns this module).

## Frontend

Plain React/Vite, no Sites/Cloudflare runtime. All data use same-origin `/api`. Accept file and folder import, show study list and supported/unsupported status, prepare then load MPR and volume lazily. MPR canonical Float32Array plus metadata. CT has linked crosshairs/windowing, fullscreen, volume vs mesh, threshold control and explicit generate/export actions. Surface ROI optional but do not label threshold geometry as automatic single-bone segmentation. Xray has image viewer, zoom/contrast/reset. Empty state must show synthetic demo and import choices. Errors must be visible. Cancel/ignore stale loads when switching studies. No case-specific names, dates, measurements, or assets. Runtime errors may be read via browser console; no medical data persisted in localStorage.
