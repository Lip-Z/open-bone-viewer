# Third-party software

OpenBone Viewer uses independently maintained open-source libraries. Their licenses and notices continue to apply. The list below is a navigation aid; inspect the exact installed package notices when distributing a binary or dependency bundle.

| Component | Purpose | Upstream |
| --- | --- | --- |
| React / React DOM | Browser UI | https://github.com/facebook/react |
| Three.js | WebGL volume and surface rendering, orbit controls and example volume shader | https://github.com/mrdoob/three.js |
| Lucide | Interface icons | https://lucide.dev/ |
| Vite / TypeScript | Frontend build | https://vite.dev/ / https://www.typescriptlang.org/ |
| FastAPI / Starlette / Uvicorn | Local HTTP service | https://fastapi.tiangolo.com/ / https://www.starlette.io/ / https://www.uvicorn.org/ |
| python-multipart | Local file import | https://github.com/Kludex/python-multipart |
| pydicom | DICOM parsing, pixel transforms and codec selection | https://pydicom.github.io/ |
| pylibjpeg and codec plugins | JPEG/JPEG-LS/JPEG 2000 decompression | https://github.com/pydicom/pylibjpeg |
| NumPy / SciPy | Arrays and display-only filtering | https://numpy.org/ / https://scipy.org/ |
| scikit-image | Marching-cubes surface generation | https://scikit-image.org/ |
| Pillow | Ordinary image reading and PNG export | https://python-pillow.org/ |
| pytest / HTTPX / Playwright | Development checks | https://docs.pytest.org/ / https://www.python-httpx.org/ / https://playwright.dev/ |

The custom UI and rendering components were adapted from the owner's earlier local viewer. Its medical assets, private notes, dedicated case measurements and hosting environment have not been included. Three.js example shaders and controls are imported from the installed Three.js package, whose MIT notice must accompany redistributed copies.

There are no pretrained model weights or downloaded medical datasets in this repository. The demo is generated mathematically by the application.
