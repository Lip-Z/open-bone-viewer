# Validation record

Date: 2026-10-26. Version: 0.1.0.

## Environment and installation

Windows, Python 3.12, Node.js and a local Playwright-controlled Chromium browser. The Python environment was created empty inside this project, then installed from the project's own dependency declarations. The frontend uses its own npm dependencies and lockfile. It has no runtime dependency on a prior viewer or dataset.

The one-command launcher completed installation/build, started the loopback service, skipped unnecessary work on the next setup run, and reused an already-running instance. The tested dependency versions are recorded in `requirements-lock.txt` and `requirements-dev-lock.txt`.

## Automated checks

- 66 Python tests passed.
- Coverage includes 24 axis orientation permutations, slice ordering, per-slice calibration, physical coordinates, unsupported geometry, source-data preservation, projection display, ROI/STL geometry, upload/ZIP handling, persistence, local-origin boundaries and injected task-persistence failures.
- TypeScript checking and the production frontend build passed.
- The dependency consistency check passed.
- Existing upstream deprecation warnings remain in Starlette's HTTPX test client and scikit-image's NumPy 2.5 array-shape operations. The Three.js lazy chunk triggers a build-size advisory. These did not fail the checks.

## Private-data checks

A non-public validation set containing multiple CT reconstruction series and compressed projection images was used locally with documented authorization. The images are not included in this repository.

- Every supported CT reconstruction series prepared successfully. Localizers were explicitly rejected as non-volume inputs.
- For every supported CT series, the complete exported source HU volume was compared with independently decoded and spatially sorted original DICOM values; all matched exactly at float32 storage precision.
- Independent physical-coordinate/value checks were run against each acquired CT grid, and all passed.
- Every tested CT series generated surface models and binary STL files with valid declared triangle counts and file sizes.
- Compressed projection DICOM images decoded to PNG and displayed at their expected dimensions. Browser zoom/reset passed for each.
- All original input archive hashes were unchanged after testing.
- After adding the separate body preview, representative full-resolution series were prepared again. Canonical HU and source NRRD payload hashes stayed identical; the preview remained a separate, reversibly selectable display asset.

## Browser checks

The synthetic demo and representative full-resolution private CT series were opened in Chromium. Checks included rendered MPR pixels, linked slice/crosshair controls, window presets, entering/exiting fullscreen, volume and surface display, body/all-structure switching, 3D drag/reset, NRRD and STL downloads, rejecting stale export parameters, and a narrower desktop viewport. Screenshots were inspected.

The patient-facing interface was then exercised at 390×844. CT and X-ray pages had no horizontal overflow; the related help dialog opened at that width without overflow, and its local keyword search returned the expected answer. The CT run covered the three plane canvases, volume rendering, contextual help, fullscreen, surface generation, NRRD/STL downloads and export invalidation. The X-ray run confirmed a non-empty full-resolution image, zoom/reset, contrast/brightness/reset and the image download entry. Both recorded runs had no JavaScript page errors or external browser requests.

The full-resolution CT series were switched repeatedly without stale dimensions. A direct study URL and browser refresh restored the selected study. Selecting a localizer showed a readable unsupported message and no CT canvases. The private projection images were separately displayed and inspected.

All real images, exports, source fingerprints, screenshots and detailed reports remain outside this source checkout. A source-boundary audit found no medical binary assets, installed environments or sampled private identifying values among the Git-visible source files.

## Remaining boundaries

This is validation of the supported local workflows, not validation across all scanners, body regions, operating systems or clinical use cases. Local browser checks and complete application startup were performed on Windows. GitHub Actions passed the Python tests, source audit, dependency installation and frontend build on both Ubuntu and Windows. Complete local application and browser verification on macOS/Linux remains outstanding. Oblique, gantry-tilted, irregular and Enhanced multi-frame CT remain explicitly unsupported.

The optional largest-connected-tissue preview can hide other separate body parts and can retain scanner supports that touch the patient. The complete structure display is always available. Preview filtering is not used for STL generation; surface extraction still uses original canonical HU plus the user's explicit smoothing/ROI choices. It is not automatic anatomical segmentation.
