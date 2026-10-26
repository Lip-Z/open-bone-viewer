# 开发、启动与支持范围

面向普通使用者的介绍和操作步骤见 [README](../README.md)。本页记录运行选项、输入边界、数据约定与验证入口。

## 运行要求与启动选项

- Python 3.12 或更新版本。
- Node.js 22.12 或更新版本，包含 npm。
- 支持 WebGL 的现代浏览器；当前实际验证环境为 Windows、Python 3.12 与 Chromium，macOS/Linux 尚未实测。

在项目根目录运行 `python run.py`，或在 Windows 双击 `启动查看器.cmd`。首次启动在项目的 `.venv` 和 `frontend/node_modules` 内安装依赖并构建前端，然后打开 `http://127.0.0.1:4318`。首次安装需要联网，查看影像本身不需要联网。

| 选项 | 用途 |
| --- | --- |
| `python run.py --setup-only` | 安装和构建，随后退出 |
| `python run.py --rebuild` | 重新安装依赖、构建并启动 |
| `python run.py --no-browser` | 启动服务，不自动打开浏览器 |
| `python run.py --port 4320` | 使用另一个本机端口（1024–65535） |

更新代码或依赖后，启动器会检查版本指纹并按需安装、构建。若同一端口已有健康的本版服务，普通启动会复用该服务；需要确保后端代码更新生效时，先关闭旧服务窗口再启动。关闭服务终端或按 Ctrl+C 停止服务。Windows 启动脚本会转发上述参数。

## 支持范围与限制

| 输入或功能 | 当前行为 |
| --- | --- |
| 常规单帧 CT DICOM | 按 SeriesInstanceUID 分组、按空间位置排序；支持规则层间距、逐层 rescale 和沿解剖轴的翻转/轴排列；要求 HU 标定和有效空间几何 |
| CT 三平面 | 使用原始校准 HU 的等价轴重排，不插值；联动定位、切片滚动、窗宽窗位与全屏 |
| 三维外观 | 独立的平滑、量化显示副本，通过 GPU 体绘制；不增加原始扫描细节 |
| 主体预览 | 独立显示资产，保留大于 -500 HU 的最大六连通组织；可能隐藏分离的身体部位，也不能可靠移除与身体相连的支撑物 |
| 表面模型 | 原始 HU 上按阈值提取表面，可明确指定体素 ROI 和平滑；不提供自动单骨分割或病例专属测量 |
| X 光等投影 DICOM | 单帧 CR/DX/MG/RF/XA/PX/IO/SC/OT，应用 modality/VOI 显示变换并处理 MONOCHROME1；不支持的编码或数据明确报错 |
| 普通图片 | 导入入口支持 PNG、JPEG、WebP、BMP；重新编码为显示 PNG，图片本身没有可靠的毫米标定 |
| 文件导入 | 多文件、文件夹或 ZIP；不连接云胶片、PACS 或 DICOMweb |
| 示例 | 由代码生成的 CT 与投影图像，无真实患者数据 |

当前不支持斜切方向、机架倾斜、非规则层间距、重复/重叠层位、Enhanced 多帧 CT、CT 定位片、多帧投影 DICOM、MRI，以及非 HU 或 modality LUT 标定的 CT。缺少或混合不兼容空间信息的序列会被拒绝，不会被静默当成普通轴向 CT。

导入限制为一次请求最多 1 GiB、单个文件最多 512 MiB、ZIP 展开总量最多 1 GiB、最多 4096 项，并检查路径和异常压缩比。单个 CT 最多 256,000,000 个体素。解码和建模可能同时占用多份体数据内存；全分辨率 STL 也可能很大，这些上限不代表所有电脑都能顺畅处理。

## 导出与原始数据约定

- `source.nrrd`：保留取得时的网格、逐层校准值和 LPS 空间方向，存储为 float32；没有插值、预览掩膜或表面平滑。它是生成的体数据文件，不是原始 DICOM 归档。
- MPR 使用规范排列后的 float32 HU；其轴重排不改变采样值。
- 体绘制的平滑、量化和可选主体预览只影响三维显示，不覆盖 MPR、源 NRRD 或表面提取输入。
- 表面提取使用原始规范排列 HU，加上用户明确选择的平滑和 ROI。STL 的顶点按 RAS 物理毫米坐标输出。
- “主体预览”不会改变 STL 生成范围。阈值表面可能包含多块骨、支具或扫描床。改变阈值、平滑或 ROI 后，需要重新生成与当前参数匹配的模型才能导出。
- 投影 PNG 是经过显示变换的图片，不是原始探测器数据；普通图片重编码去除文件元数据，但不会擦除像素里的身份文字。

模型外观不能证明几何准确性、骨折愈合、软骨状态或承重能力。项目不包含自动诊断、AI 病情问答或临床测量结论。界面答疑为内置操作解释，不会把影像发给在线服务。

## 本地数据与发布边界

默认运行目录为 Windows `%LOCALAPPDATA%/OpenBoneViewer`、macOS `~/Library/Application Support/OpenBoneViewer`、Linux `$XDG_DATA_HOME/OpenBoneViewer`（未设置时为 `~/.local/share/OpenBoneViewer`）。可用 `OPENBONE_DATA_DIR` 指定其他本地目录；该目录必须在源码树之外。

导入会复制输入供处理使用，副本可能保留 DICOM 身份信息；软件不自动脱敏。原始输入路径不会被改写或删除。删除一个序列时，同一导入组被其他序列使用的副本会保留，删除最后一个序列后清理该组。下载到其他位置的文件不受此操作管理。

服务只监听 `127.0.0.1`，前后端同源，校验本地 Host 和写请求来源；不使用外部字体、统计脚本或云端模型。原始 DICOM 副本不作为任意下载路径暴露。不要把这个个人本地服务直接暴露到公网。

公开仓库只包含源码、依赖清单、锁文件、文档和合成数据生成器。真实影像、导出、截图、运行目录、安装环境及测试报告都应留在源码目录之外。`.gitignore` 不能代替发布前检查；“显示在本机”也不能视为“已脱敏”。

## 开发环境

先在项目根目录创建虚拟环境：

```sh
python -m venv .venv
```

Windows 安装经过记录的开发依赖：

```powershell
.venv\Scripts\python -m pip install -r requirements-dev-lock.txt
.venv\Scripts\python -m pip install -e . --no-deps
```

macOS/Linux 对应命令：

```sh
.venv/bin/python -m pip install -r requirements-dev-lock.txt
.venv/bin/python -m pip install -e . --no-deps
```

开发时也可以用虚拟环境中的 Python 执行 `python -m pip install -e ".[dev]"`，按 `pyproject.toml` 的版本范围重新解析依赖。已验证的运行依赖在 `requirements-lock.txt`，完整开发与浏览器测试依赖在 `requirements-dev-lock.txt`；前端依赖由 `frontend/package-lock.json` 锁定。

构建前端：

```sh
cd frontend
npm ci
npm run build
```

`npm run build` 包含 TypeScript 检查。构建完成后返回根目录，通过 `python run.py` 启动，或用已安装依赖的虚拟环境运行 `python -m uvicorn openbone.app:app --host 127.0.0.1 --port 4318`。

## 测试与验证入口

下列 Python 命令均应使用上述虚拟环境，在项目根目录执行。

```sh
python -m pytest -q
python -m pip check
python scripts/audit_source.py
```

测试 DICOM 由代码合成，覆盖空间排序、HU、方向、错误拒绝、原始数据保留、投影显示、ROI/STL、ZIP、本地请求边界和任务持久化。源文件审计检查 Git 可见发布文件，不读取任意个人数据。

浏览器验证需先启动服务，并安装 Chromium：

```sh
python -m playwright install chromium
python scripts/browser_smoke.py --output ../openbone-browser-results
```

可使用 `--url` 指定服务、`--headed` 显示测试浏览器、`--study-id` 核对已有 CT 或 X 光。测试会操作页面并下载结果；默认会导入合成示例。脚本会按影像类型运行对应检查：CT 覆盖三平面、三维和导出，X 光覆盖二维显示、答疑、缩放和恢复。截图和报告目录必须在源码目录之外。

仅在所有者授权且主动提供本机文件路径时，才运行真实资料验证，例如：

```sh
python scripts/validate_private_inputs.py /path/to/authorized-ct.zip --output /path/outside/source/private-results
```

这个工具会把输入导入本地查看器、准备受支持的序列、生成 CT 表面并保存技术报告。CT 的独立全量 HU 和空间核对需要原始 DICOM ZIP；它不会自动删除导入的检查。原始文件前后哈希会被核对，详细结果不能未经审查公开。

发布前可明确指定自己的 DICOM ZIP，额外检查抽样身份字段是否混入 Git 可见源文件：

```sh
python scripts/audit_source.py --private-dicom-zip /path/to/authorized-ct.zip
```

此检查只核对抽样标识，不保证全面脱敏。实际完成的本地验证与边界见 [验证记录](validation.md)，架构见 [数据流说明](architecture.md)，贡献约定见 [CONTRIBUTING](../CONTRIBUTING.md)。
