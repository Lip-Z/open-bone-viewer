# Contributing

OpenBone Viewer is a local-first image browser. Small, reproducible improvements to importing, geometry, accessibility, performance and documentation are welcome.

- Never commit real patient images, screenshots, exports, DICOM headers, logs containing identifiers, or runtime data.
- Generate test DICOM in code. Include no patient identifiers and no copied real pixels.
- Keep original source HU and spatial geometry separate from display smoothing, quantization, crops and surface extraction.
- Reject unsupported geometry explicitly. Add synthetic tests for coordinate changes, not just a screenshot.
- Keep all browser requests same-origin. Do not add telemetry, external fonts or implicit cloud uploads.
- Describe which supported inputs and workflows you verified. Do not describe an attractive render as proof of geometric accuracy.

For an issue, include OS/browser versions, the visible error and a synthetic reproduction. Do not paste patient names, IDs, raw headers or original filenames. For a confidential medical-data exposure, do not open a public issue containing the exposed data.
