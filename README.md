# OpenBone Viewer

一个在自己电脑上运行的 CT、X 光和骨骼三维查看器。浏览器界面，中文操作，无需账号。导入和重建由本地服务处理；不向云端发送影像。

当前为 **0.1.0 本地验证版**。项目源码与真实病例分开；仓库仅包含代码和运行时生成的合成示例。

## 启动

需要 Python 3.12 或更新版本，以及 Node.js 22.12 或更新版本。目前实际验证环境为 Windows / Python 3.12 / Chromium；macOS 和 Linux 尚未实测。

Windows 双击 `启动查看器.cmd`。首次启动会在项目自己的 `.venv` 和 `frontend/node_modules` 安装依赖、构建界面，然后打开 <http://127.0.0.1:4318>。首次安装需要联网；安装完成后查看影像不需要联网。

其他平台，或需要看到启动日志时：

```sh
python run.py
```

只安装和构建，不启动：`python run.py --setup-only`。更新源码或依赖后运行 `python run.py --rebuild`。关闭服务终端即可停止。`--no-browser` 可禁止自动打开浏览器。

## 使用

1. 在空白页面选择“合成示例”，先确认本机能正常显示二维和三维。
2. 导入医院提供的 ZIP、DICOM 文件或文件夹，也可以导入 PNG/JPG 等普通图片。压缩包中有多个 CT 序列时，在检查列表中选择要看的序列。
3. CT 准备完成后，点击切片联动定位，滚轮或滑块逐层查看，调整窗宽窗位；三维可旋转、缩放和平移。
4. 选择阈值并生成表面模型。导出的 STL 使用毫米和 RAS 坐标；NRRD 保留原始 CT HU 及 LPS 空间方向。平滑和选区只影响派生三维模型。
5. 可在检查列表删除导入数据。原始输入文件始终保留在你选择它们的位置，不会被本程序改写。

## 当前支持范围

- 常规单帧 CT DICOM：按空间位置排序，按 SeriesInstanceUID 分组，支持不同层数、规则层间距、逐层 rescale 和沿解剖轴的翻转/轴排列。
- X 光：单帧 CR/DX 等投影 DICOM，以及 PNG、JPEG、WebP、BMP 等普通图片。DICOM 解码由 pydicom 和 JPEG/JPEG 2000 插件提供；不支持的编码会明确报错。
- 原始 HU 三平面浏览、窗宽窗位、联动十字定位、全屏、GPU 三维体绘制、阈值表面和 STL/NRRD 导出。
- 合成 CT 与投影影像示例，不包含真实患者资料。

当前**不支持**斜切方向、机架倾斜、非规则层间距、Enhanced 多帧 CT、MRI、PACS 和 DICOMweb。程序应明确拒绝不支持的数据；不会把它们按普通轴向 CT 静默显示。

阈值建模会提取达到该 HU 阈值的表面，可能同时包含多块骨、支具或扫描床。它不提供自动单骨分割。三维显示中的平滑与量化不增加扫描细节；骨折细节应回到原始切片。当前没有自动诊断或病例专属测量。

体绘制可在“主体预览”和“全部结构”间切换。主体预览仅显示最大连通组织，帮助隐藏与主体分离的扫描床或其他物体；它也可能隐藏分离的身体部位。此选项只影响三维显示，原始切片、NRRD 和 STL 建模输入均不受影响。与身体相连的支撑物不一定能被去掉。

## 数据位置和隐私

运行时数据默认放在 Windows `%LOCALAPPDATA%/OpenBoneViewer`、macOS `~/Library/Application Support/OpenBoneViewer` 或 Linux `~/.local/share/OpenBoneViewer`，不放进源码仓库。可用 `OPENBONE_DATA_DIR` 指定另一个**源码目录之外**的本地目录。

本地导入会复制 DICOM/ZIP 供处理使用。这些副本可能保留原始身份信息；原始 NRRD 和 STL/PNG 等派生结果也应视为医疗数据。程序不承诺自动脱敏，尤其不会自动擦除像素内烧录的姓名。请不要把个人影像、运行目录、截图或测试产物提交到公开仓库。

服务默认只监听 `127.0.0.1`，前后端同源，不使用外部字体、统计脚本或云端模型。不要把这个个人本地服务直接暴露到公网。

## 开发和验证

```sh
python -m venv .venv
# Windows: .venv\Scripts\python -m pip install -e ".[dev]"
# macOS/Linux: .venv/bin/python -m pip install -e '.[dev]'
cd frontend
npm ci
npm run build
```

在根目录运行 `python -m pytest`（请使用已安装依赖的虚拟环境）。测试用 DICOM 均由代码合成，覆盖空间排序、HU、方向、错误拒绝、模型导出、ZIP 和本地服务边界。已验证的运行依赖版本记录在 `requirements-lock.txt`，开发与浏览器测试依赖记录在 `requirements-dev-lock.txt`。

浏览器验证使用 `scripts/browser_smoke.py --output <仓库外目录>`，需要安装 Playwright Chromium（`python -m playwright install chromium`）。可选的真实资料核对工具是 `scripts/validate_private_inputs.py`；只有你主动提供本机文件路径时才会读取。测试报告和截图的输出目录必须放在源码仓库外。`python scripts/audit_source.py` 可检查 Git 可见的发布文件是否混入医疗数据或运行环境。

更多说明见 [架构与数据流](docs/architecture.md)、[贡献指南](CONTRIBUTING.md) 和 [第三方依赖](THIRD_PARTY.md)。

本次验证范围与结果见 [验证记录](docs/validation.md)。

## 开源状态

源码采用 MIT 许可证。当前代码仅在本地整理、测试；未创建远端仓库或发布版本。项目由个人影像查看需求演化而来，欢迎用合成或获得授权的数据提交可复现的问题。
