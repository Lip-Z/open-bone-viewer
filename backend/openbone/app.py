"""Loopback-only API. Private image files never live in the source checkout."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import re
import shutil
import stat
import sys
import threading
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from . import __version__, imaging
from .demo import generate_demo


SOURCE_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = SOURCE_ROOT / "frontend" / "dist"
MAX_UPLOAD_BYTES = 1024 * 1024 * 1024
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_EXPANDED_BYTES = 1024 * 1024 * 1024
MAX_FILES = 4096
MAX_ZIP_RATIO = 250
ZIP_RATIO_MIN_BYTES = 8 * 1024 * 1024
MAX_PENDING_JOBS = 16
CHUNK_BYTES = 1024 * 1024
OPAQUE_ID = re.compile(r"^[a-f0-9]{32}$")
ASSET_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
ASSET_EXTENSIONS = {".png", ".json", ".rawz", ".meshz", ".stl", ".nrrd"}
STUDY_FIELDS = ("id", "kind", "label", "modality", "count", "rows", "columns", "supported", "reason", "ready")
CT_FIELDS = ("dimensions_xyz", "spacing_xyz_mm", "origin_lps_mm", "source_dimensions_xyz", "source_spacing_xyz_mm", "source_orientation", "source_origin_lps_mm", "coordinate_system", "source_file", "volume_file", "dtype", "volume_rendering", "body_volume_rendering", "models", "warnings")
MODEL_FIELDS = ("threshold_hu", "vertices", "triangles", "mesh_file", "stl_file", "smoothing", "smoothing_sigma_mm", "roi", "coordinate_system", "units")


class UploadTooLarge(Exception):
    pass


def _runtime_root() -> Path:
    if value := os.environ.get("OPENBONE_DATA_DIR"):
        return Path(value).expanduser()
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "OpenBoneViewer"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "OpenBoneViewer"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "OpenBoneViewer"


def _within(path: Path, root: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


def _save_json(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        temporary.replace(path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _safe_upload_name(name: str) -> str:
    # Validate the original path even though files are stored under opaque names.
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    parts = normalized.split("/")
    if not name or len(name) > 1024 or path.is_absolute() or any(
        not part or not part.rstrip(" .") or part in {".", ".."} or ":" in part
        or any(ord(character) < 32 for character in part) or len(part) > 255
        for part in parts
    ):
        raise HTTPException(400, "上传文件包含不安全的路径。")
    for part in parts:
        if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part.rstrip(" .")):
            raise HTTPException(400, "上传文件包含不安全的路径。")
    # Hospital ZIPs can contain Unicode names and harmless trailing spaces.
    # Original names are never used as destination paths, including extensions.
    suffix = PurePosixPath(path.name.rstrip(" .")).suffix.lower()
    return suffix if suffix in {"", ".zip", ".dcm", ".dicom", ".dic", ".ima", ".png", ".jpg", ".jpeg", ".webp", ".bmp"} else ".bin"


class LocalOnlyMiddleware:
    """DNS-rebinding protection, same-origin writes, and streaming body bounds."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {key.decode("latin1").lower(): value.decode("latin1") for key, value in scope["headers"]}
        host = headers.get("host", "")
        parsed = None
        try:
            parsed = urlsplit("http://" + host)
            hostname = parsed.hostname or ""
            _ = parsed.port  # Accessing this property also validates port syntax.
            valid_host = hostname == "localhost" or ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            valid_host = False
        host_count = sum(key.lower() == b"host" for key, _ in scope["headers"])
        if not valid_host or host_count != 1 or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            return await JSONResponse({"detail": "此服务只允许通过本机地址访问。"}, 403)(scope, receive, send)
        if scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
            expected_origin = f"{scope.get('scheme', 'http')}://{host}"
            origin = headers.get("origin")
            if (origin is not None and origin != expected_origin) or headers.get("sec-fetch-site") in {"cross-site", "same-site"}:
                return await JSONResponse({"detail": "请从本机查看器页面执行此操作。"}, 403)(scope, receive, send)
        request_limit = MAX_UPLOAD_BYTES if scope.get("path") == "/api/import" else 64 * 1024
        try:
            content_length = int(headers.get("content-length", "0"))
        except ValueError:
            content_length = request_limit + 1
        if content_length < 0 or content_length > request_limit:
            return await JSONResponse({"detail": "请求超过允许的大小。单次导入上限为 1 GiB。"}, 413)(scope, receive, send)
        received = 0

        async def bounded_receive():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > request_limit:
                raise UploadTooLarge()
            return message

        async def private_send(message):
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.extend([(b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer")])
                message = {**message, "headers": response_headers}
            await send(message)

        await self.app(scope, bounded_receive, private_send)


def _public_study(manifest: dict) -> dict:
    return {key: manifest[key] for key in STUDY_FIELDS if key in manifest}


def _public_metadata(metadata: dict, kind: str) -> dict:
    if kind == "xray":
        return {key: metadata[key] for key in ("file", "width", "height", "warning") if key in metadata}
    result = {key: metadata[key] for key in CT_FIELDS if key in metadata}
    for field in ("volume_rendering", "body_volume_rendering"):
        if isinstance(result.get(field), dict):
            result[field] = {key: value for key, value in result[field].items() if key in {"file", "dimensions_xyz", "spacing_xyz_mm", "content_bounds_xyz", "min_hu", "max_hu", "source"}}
    result["models"] = [{key: model[key] for key in MODEL_FIELDS if key in model} for model in result.get("models", [])]
    return result


class Repository:
    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        if _within(self.root, SOURCE_ROOT):
            raise RuntimeError("Medical runtime data must be stored outside the source checkout.")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.imports = self.root / "imports"
        self.studies_root = self.root / "studies"
        self.jobs_root = self.root / "jobs"
        for directory in (self.imports, self.studies_root, self.jobs_root):
            directory.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.studies: dict[str, dict] = {}
        self.jobs: dict[str, dict] = {}
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="openbone-imaging")
        for path in self.studies_root.glob("*/manifest.json"):
            if OPAQUE_ID.fullmatch(path.parent.name) and not path.parent.is_symlink():
                try:
                    manifest = json.loads(path.read_text(encoding="utf-8"))
                    if manifest.get("id") == path.parent.name and OPAQUE_ID.fullmatch(manifest.get("group_id", "")):
                        self.studies[manifest["id"]] = manifest
                except (OSError, ValueError, TypeError):
                    pass
        for path in self.jobs_root.glob("*.json"):
            if OPAQUE_ID.fullmatch(path.stem):
                try:
                    job = json.loads(path.read_text(encoding="utf-8"))
                    if job.get("status") in {"queued", "running"}:
                        job.update(id=path.stem, status="error", message="任务尚未完成时程序已重启，请重新处理。")
                        job.pop("result", None)
                        _save_json(path, job)
                    self.jobs[path.stem] = job
                except (OSError, ValueError, TypeError):
                    pass

    def get(self, study_id: str) -> dict:
        if not OPAQUE_ID.fullmatch(study_id) or study_id not in self.studies:
            raise HTTPException(404, "没有找到这份影像。")
        return self.studies[study_id]

    def persist(self, manifest: dict) -> None:
        _save_json(self.studies_root / manifest["id"] / "manifest.json", manifest)

    def register_group(self, group_id: str, entries: list[dict]) -> list[dict]:
        added = []
        with self.lock:
            try:
                for entry in entries:
                    study_id = uuid.uuid4().hex
                    directory = self.studies_root / study_id
                    directory.mkdir()
                    manifest = {key: entry[key] for key in STUDY_FIELDS if key in entry and key != "id"}
                    manifest.update(id=study_id, group_id=group_id, entry=entry, ready=False, assets=[])
                    self.persist(manifest)
                    self.studies[study_id] = manifest
                    added.append(manifest)
            except Exception:
                for manifest in added:
                    self.studies.pop(manifest["id"], None)
                    shutil.rmtree(self.studies_root / manifest["id"], ignore_errors=True)
                raise
        return [_public_study(manifest) for manifest in added]

    def enqueue(self, study_id: str, operation: str, options: dict | None = None) -> dict:
        with self.lock:
            manifest = self.get(study_id)
            if not manifest.get("supported"):
                raise HTTPException(422, manifest.get("reason", "暂不支持这种影像。"))
            if operation == "mesh" and (manifest["kind"] != "ct" or not manifest.get("ready")):
                raise HTTPException(409, "请先准备 CT 影像，再生成三维表面。")
            for existing in self.jobs.values():
                if existing.get("study_id") == study_id and existing["status"] in {"queued", "running"}:
                    if operation == "prepare" and existing.get("operation") == "prepare":
                        return {"id": existing["id"], "status": existing["status"]}
                    raise HTTPException(409, "这份影像正在处理中，请等待当前任务结束。")
            if sum(job["status"] in {"queued", "running"} for job in self.jobs.values()) >= MAX_PENDING_JOBS:
                raise HTTPException(429, "处理队列已满，请等待现有任务结束。")
            job_id = uuid.uuid4().hex
            job = {"id": job_id, "status": "queued", "message": "正在排队，等待本机处理。", "study_id": study_id, "operation": operation}
            job_path = self.jobs_root / f"{job_id}.json"
            try:
                _save_json(job_path, job)
                self.jobs[job_id] = job
                self.executor.submit(self.run_job, job_id, options or {})
            except Exception:
                self.jobs.pop(job_id, None)
                try:
                    job_path.unlink(missing_ok=True)
                except OSError:
                    pass
                raise HTTPException(503, "无法创建处理任务，请检查本机存储空间和权限后重试。") from None
            return {"id": job_id, "status": "queued"}

    def run_job(self, job_id: str, options: dict) -> None:
        job = None
        temporary = None
        outcome = {"status": "error", "message": "处理任务意外中止，请重新处理。"}
        try:
            with self.lock:
                job = self.jobs.get(job_id)
                if job is None:
                    return
                manifest = self.studies[job["study_id"]]
                job.update(status="running", message="正在本机处理影像。")
                _save_json(self.jobs_root / f"{job_id}.json", job)
            directory = self.studies_root / manifest["id"]
            output = directory / "prepared"
            temporary = directory / f"work-{uuid.uuid4().hex}"
            if job["operation"] == "prepare":
                temporary.mkdir()
                source = self.imports / manifest["group_id"] / "source"
                processor = imaging.prepare_ct if manifest["kind"] == "ct" else imaging.prepare_xray
                metadata = _public_metadata(processor(source, manifest["entry"], temporary), manifest["kind"])
                _save_json(temporary / "metadata.json", metadata)
                previous = directory / f"previous-{uuid.uuid4().hex}"
                if output.exists():
                    output.rename(previous)
                try:
                    temporary.rename(output)
                except Exception:
                    if previous.exists():
                        previous.rename(output)
                    raise
                if previous.exists():
                    shutil.rmtree(previous, ignore_errors=True)
                result = {"study_id": manifest["id"], "metadata" if manifest["kind"] == "ct" else "image": metadata}
            else:
                model = imaging.build_mesh(output, **options)
                model = {key: model[key] for key in MODEL_FIELDS if key in model}
                metadata = dict(manifest["metadata"])
                models = [item for item in metadata.get("models", []) if item.get("mesh_file") != model["mesh_file"]]
                metadata["models"] = models + [model]
                _save_json(output / "metadata.json", metadata)
                result = {"study_id": manifest["id"], "model": model}
            assets = sorted(path.name for path in output.iterdir() if path.is_file() and not path.is_symlink() and ASSET_NAME.fullmatch(path.name) and path.suffix in ASSET_EXTENSIONS)
            with self.lock:
                updated = {**manifest, "metadata": metadata, "ready": True, "assets": assets}
                self.persist(updated)
                self.studies[manifest["id"]] = updated
                outcome = {"status": "done", "message": "处理完成。", "result": result}
        except imaging.ImagingError as error:
            outcome = {"status": "error", "message": str(error)}
        except Exception:
            outcome = {"status": "error", "message": "影像处理或状态保存失败，请检查文件是否受支持，以及本机存储空间和权限。"}
        finally:
            if temporary is not None and temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)
            with self.lock:
                if job is not None:
                    # Disk errors must never strand an in-memory task in progress.
                    # Publish terminal status only after cleanup, while locked;
                    # deletion cannot race a worker that is still finalizing.
                    job.update(outcome)
                    try:
                        _save_json(self.jobs_root / f"{job_id}.json", job)
                    except Exception:
                        if job["status"] == "done":
                            job["message"] = "处理完成，但任务记录暂未写入磁盘。"
                        else:
                            job["message"] = "处理失败且任务记录无法写入磁盘，请检查本机存储空间和权限。"


def _extract_zip(archive: Path, destination: Path, budget: dict) -> None:
    try:
        with zipfile.ZipFile(archive) as bundle:
            members = bundle.infolist()
            if len(members) > MAX_FILES:
                raise HTTPException(413, "压缩包包含的文件和目录过多。")
            for index, member in enumerate(members):
                name = member.filename.rstrip("/") if member.is_dir() else member.filename
                suffix = _safe_upload_name(name)
                mode = member.external_attr >> 16
                file_type = stat.S_IFMT(mode)
                if file_type not in {0, stat.S_IFREG, stat.S_IFDIR} or member.flag_bits & 1:
                    raise HTTPException(400, "不支持加密压缩包、符号链接或特殊文件。")
                if member.is_dir():
                    continue
                budget["files"] += 1
                if budget["files"] > MAX_FILES or member.file_size > MAX_FILE_BYTES:
                    raise HTTPException(413, "压缩包超过文件数量或单个文件大小限制。")
                # Tiny air-only DICOM slices can legitimately compress >250x.
                # All entries still obey the absolute, incrementally checked caps.
                if member.file_size > ZIP_RATIO_MIN_BYTES and member.file_size > max(member.compress_size, 1) * MAX_ZIP_RATIO:
                    raise HTTPException(413, "压缩包的解压膨胀比例过高，已停止处理。")
                if budget["bytes"] + member.file_size > MAX_EXPANDED_BYTES:
                    raise HTTPException(413, "解压后的文件超过 1 GiB 上限。")
                target = destination / f"{index:05d}{suffix}"
                written = 0
                with bundle.open(member) as stream, target.open("xb") as output:
                    while chunk := stream.read(CHUNK_BYTES):
                        written += len(chunk)
                        budget["bytes"] += len(chunk)
                        if written > MAX_FILE_BYTES or budget["bytes"] > MAX_EXPANDED_BYTES:
                            raise HTTPException(413, "解压后的文件超过允许的大小。")
                        output.write(chunk)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError):
        raise HTTPException(400, "无法读取这个 ZIP 压缩包。") from None


class MeshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    threshold: float = Field(ge=-32768, le=65535)
    smooth: StrictBool = False
    roi: list[int] | None = Field(default=None, min_length=6, max_length=6)


def create_app(data_dir: Path | None = None) -> FastAPI:
    repository = Repository(Path(data_dir) if data_dir is not None else _runtime_root())

    @asynccontextmanager
    async def lifespan(application):
        yield
        await asyncio.to_thread(repository.executor.shutdown, wait=True, cancel_futures=False)

    application = FastAPI(title="OpenBone Viewer", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    application.add_middleware(LocalOnlyMiddleware)
    application.state.repository = repository

    @application.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__, "local_only": True}

    @application.get("/api/studies")
    def list_studies():
        with repository.lock:
            return {"studies": [_public_study(item) for item in repository.studies.values()]}

    @application.post("/api/import")
    async def import_images(request: Request):
        group_id = uuid.uuid4().hex
        group = repository.imports / group_id
        source = group / "source"
        source.mkdir(parents=True)
        form = None
        try:
            try:
                form = await request.form(max_files=MAX_FILES, max_fields=8)
            except UploadTooLarge:
                raise HTTPException(413, "上传超过单次 1 GiB 上限。") from None
            except Exception:
                raise HTTPException(400, "无法读取上传内容，请重新选择文件。") from None
            uploads = [value for key, value in form.multi_items() if key == "files" and isinstance(value, UploadFile)]
            if not uploads:
                raise HTTPException(400, "请选择 DICOM 文件、影像文件夹、ZIP 压缩包或普通图片。")
            budget = {"files": 0, "bytes": 0}
            total = 0
            for index, upload in enumerate(uploads):
                suffix = _safe_upload_name(upload.filename or "")
                path = group / f"incoming-{index:05d}{suffix}"
                size = 0
                with path.open("xb") as stream:
                    while chunk := await upload.read(CHUNK_BYTES):
                        size += len(chunk)
                        total += len(chunk)
                        if size > MAX_FILE_BYTES or total > MAX_UPLOAD_BYTES:
                            raise HTTPException(413, "上传超过允许的大小。单个文件上限为 512 MiB。")
                        stream.write(chunk)
                if suffix == ".zip" or zipfile.is_zipfile(path):
                    destination = source / f"archive-{index:05d}"
                    destination.mkdir()
                    await run_in_threadpool(_extract_zip, path, destination, budget)
                    path.unlink()
                else:
                    budget["files"] += 1
                    budget["bytes"] += size
                    if budget["files"] > MAX_FILES or budget["bytes"] > MAX_EXPANDED_BYTES:
                        raise HTTPException(413, "本次导入超过文件数量或大小限制。")
                    path.rename(source / f"file-{index:05d}{suffix}")
            entries = await run_in_threadpool(imaging.scan_directory, source)
            if not entries:
                raise HTTPException(422, "没有找到可读取的 DICOM 或受支持的普通图片。")
            studies = repository.register_group(group_id, entries)
            warnings = ["X 光或普通图片的像素中可能带有姓名等信息，程序不会自动擦除这些文字。"] if any(item["kind"] == "xray" for item in studies) else []
            return {"studies": studies, "warnings": warnings}
        except HTTPException:
            shutil.rmtree(group, ignore_errors=True)
            raise
        except imaging.ImagingError as error:
            shutil.rmtree(group, ignore_errors=True)
            raise HTTPException(422, str(error)) from None
        except Exception:
            shutil.rmtree(group, ignore_errors=True)
            raise HTTPException(400, "影像导入未能完成，请检查文件后重试。") from None
        finally:
            if form is not None:
                await form.close()

    @application.post("/api/demo")
    async def demo():
        group_id = uuid.uuid4().hex
        group = repository.imports / group_id
        source = group / "source"
        try:
            await run_in_threadpool(generate_demo, source)
            entries = await run_in_threadpool(imaging.scan_directory, source)
            return {"studies": repository.register_group(group_id, entries), "warnings": ["这些影像是程序生成的几何演示，不包含真实患者数据。"]}
        except Exception:
            shutil.rmtree(group, ignore_errors=True)
            raise HTTPException(500, "无法创建合成演示影像。") from None

    @application.post("/api/studies/{study_id}/prepare", status_code=202)
    def prepare(study_id: str):
        return repository.enqueue(study_id, "prepare")

    @application.post("/api/studies/{study_id}/mesh", status_code=202)
    def mesh(study_id: str, options: MeshRequest):
        if options.roi is not None and any(value < 0 for value in options.roi):
            raise HTTPException(422, "选区边界必须使用非负的体素编号。")
        return repository.enqueue(study_id, "mesh", {"threshold": options.threshold, "smooth": options.smooth, "roi": options.roi})

    @application.get("/api/jobs/{job_id}")
    def job_status(job_id: str):
        with repository.lock:
            if not OPAQUE_ID.fullmatch(job_id) or job_id not in repository.jobs:
                raise HTTPException(404, "没有找到这个处理任务。")
            job = repository.jobs[job_id]
            return {key: job[key] for key in ("id", "status", "message", "result") if key in job}

    @application.get("/api/studies/{study_id}/metadata")
    def metadata(study_id: str):
        with repository.lock:
            manifest = repository.get(study_id)
            if not manifest.get("ready"):
                raise HTTPException(409, "请先准备这份影像。")
            return manifest["metadata"]

    @application.get("/api/studies/{study_id}/assets/{filename}")
    def asset(study_id: str, filename: str):
        with repository.lock:
            manifest = repository.get(study_id)
            output = repository.studies_root / study_id / "prepared"
            path = output / filename
            if not ASSET_NAME.fullmatch(filename) or filename not in manifest.get("assets", []) or path.is_symlink() or not _within(path, output) or not path.is_file():
                raise HTTPException(404, "没有找到可下载的处理结果。")
        media_type = "image/png" if path.suffix == ".png" else "application/json" if path.suffix == ".json" else "application/octet-stream"
        return FileResponse(path, media_type=media_type, filename=filename)

    @application.delete("/api/studies/{study_id}")
    def delete_study(study_id: str):
        with repository.lock:
            manifest = repository.get(study_id)
            if any(job.get("study_id") == study_id and job["status"] in {"queued", "running"} for job in repository.jobs.values()):
                raise HTTPException(409, "这份影像正在处理，请等待任务结束后再删除。")
            group_id = manifest["group_id"]
            directory = repository.studies_root / study_id
            if not _within(directory, repository.studies_root):
                raise HTTPException(400, "运行数据目录无效。")
            shutil.rmtree(directory)
            del repository.studies[study_id]
            for job_id, job in list(repository.jobs.items()):
                if job.get("study_id") == study_id:
                    (repository.jobs_root / f"{job_id}.json").unlink(missing_ok=True)
                    del repository.jobs[job_id]
            if not any(item["group_id"] == group_id for item in repository.studies.values()):
                group = repository.imports / group_id
                if _within(group, repository.imports):
                    shutil.rmtree(group, ignore_errors=True)
            return {"ok": True}

    @application.get("/{path:path}")
    def frontend(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "没有找到这个服务接口。")
        candidate = FRONTEND_DIST / path
        if path and _within(candidate, FRONTEND_DIST) and candidate.is_file():
            return FileResponse(candidate)
        index = FRONTEND_DIST / "index.html"
        if index.is_file():
            return FileResponse(index)
        return JSONResponse({"detail": "请先构建查看器界面，再启动本机服务。"}, status_code=503)

    return application


app = create_app()
