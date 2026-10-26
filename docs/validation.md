# Local validation record

Date: 2026-10-26. Version: 0.1.0.

## Environment and installation

Windows, Python 3.12, Node.js and a local Playwright-controlled Chromium browser. The Python environment was created empty inside this project, then installed from the project's own dependency declarations. The frontend uses its own npm dependencies and lockfile. It does not import a runtime or a dataset from the earlier personal viewer.

The one-command launcher completed installation/build, started the loopback service, skipped unnecessary work on the next setup run, and reused an already-running instance. The tested dependency versions are recorded in `requirements-lock.txt` and `requirements-dev-lock.txt`.

## Automated checks

- 66 Python tests passed.
- Coverage includes 24 axis orientation permutations, slice ordering, per-slice calibration, physical coordinates, unsupported geometry, source-data preservation, projection display, ROI/STL geometry, upload/ZIP handling, persistence, local-origin boundaries and injected task-persistence failures.
- TypeScript checking and the production frontend build passed.
- The dependency consistency check passed.
- Existing upstream deprecation warnings remain in Starlette's HTTPX test client and scikit-image's NumPy 2.5 array-shape operations. The Three.js lazy chunk triggers a build-size advisory. These did not fail the checks.

## Private-data checks

Real images were tested locally with the owner's authorization. They are not included in this repository.

- Two CT examinations yielded seven supported reconstruction series and two localizer series. All seven supported series prepared successfully. Both localizers were explicitly rejected as non-volume inputs.
- For every supported CT series, the complete exported source HU volume was compared with independently decoded and spatially sorted original DICOM values; all matched exactly at float32 storage precision.
- Each CT received 2,002 independent physical-coordinate/value checks against its acquired grid, all passed.
- All seven CT series generated surface models and binary STL files with valid declared triangle counts and file sizes.
- Four compressed projection DICOM images decoded to PNG and displayed at their expected dimensions. Browser zoom/reset passed for each.
- All four original input archive hashes were unchanged after testing.
- After adding the separate body preview, one full-resolution series from each examination was prepared again. Canonical HU and source NRRD payload hashes stayed identical; the preview remained a separate, reversibly selectable display asset.

## Browser checks

The synthetic demo and both full-resolution private CT series were opened in Chromium. Checks included rendered MPR pixels, linked slice/crosshair controls, window presets, entering/exiting fullscreen, volume and surface display, body/all-structure switching, 3D drag/reset, NRRD and STL downloads, rejecting stale export parameters, and a narrower desktop viewport. Screenshots were inspected.

The two full-resolution CT series were switched repeatedly without stale dimensions. A direct study URL and browser refresh restored the selected study. Selecting a localizer showed a readable unsupported message and no CT canvases. Four private projection images were separately displayed and inspected. No JavaScript page errors or external browser requests were found in the recorded runs.

All real images, exports, source fingerprints, screenshots and detailed reports remain outside this source checkout. A source-boundary audit found no medical binary assets, installed environments or sampled private identifying values among the Git-visible source files.

## Remaining boundaries

This is validation of the supported local workflows, not validation across all scanners, body regions, operating systems or clinical use cases. macOS/Linux and the added CI workflow have not been run here. Oblique, gantry-tilted, irregular and Enhanced multi-frame CT remain explicitly unsupported.

The optional largest-connected-tissue preview can hide other separate body parts and can retain scanner supports that touch the patient. The complete structure display is always available. Preview filtering is not used for STL generation; surface extraction still uses original canonical HU plus the user's explicit smoothing/ROI choices. It is not automatic anatomical segmentation.
