import io
import json
import shutil
import threading
import time
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from openbone.app import create_app


@pytest.fixture
def client(tmp_path):
    application = create_app(tmp_path / "private-runtime")
    with TestClient(application, base_url="http://localhost", headers={"Origin": "http://localhost"}) as session:
        yield session


def png_bytes(color="white"):
    data = io.BytesIO()
    Image.new("RGB", (24, 16), color=color).save(data, format="PNG")
    return data.getvalue()


def test_runtime_data_cannot_be_created_inside_source_checkout():
    from openbone.app import SOURCE_ROOT

    with pytest.raises(RuntimeError):
        create_app(SOURCE_ROOT / "unsafe-test-runtime")
    assert not (SOURCE_ROOT / "unsafe-test-runtime").exists()


def wait_job(client, response):
    assert response.status_code == 202, response.text
    identifier = response.json()["id"]
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{identifier}").json()
        if job["status"] in {"done", "error"}:
            assert job["status"] == "done", job
            return job["result"]
        time.sleep(0.02)
    pytest.fail("Local image-processing job did not finish.")


def test_synthetic_ct_mpr_surface_and_projection_end_to_end(client):
    response = client.post("/api/demo")
    assert response.status_code == 200, response.text
    studies = response.json()["studies"]
    ct = next(study for study in studies if study["kind"] == "ct")
    projection = next(study for study in studies if study["kind"] == "xray")
    assert ct["supported"] and projection["supported"]
    assert "files" not in ct and "group_id" not in ct
    ct_id = ct["id"]
    assert client.get(f"/api/studies/{ct_id}/metadata").status_code == 409
    result = wait_job(client, client.post(f"/api/studies/{ct_id}/prepare"))
    metadata = result["metadata"]
    assert metadata["dimensions_xyz"] == [64, 64, 48]
    assert metadata["dtype"] == "float32"
    assert metadata["coordinate_system"] == "LPS"
    for filename in ["source.nrrd", "volume.rawz", "volume_render.rawz", "metadata.json"]:
        asset = client.get(f"/api/studies/{ct_id}/assets/{filename}")
        assert asset.status_code == 200, filename
        assert "content-encoding" not in asset.headers
        assert asset.headers["cache-control"] == "no-store"
    result = wait_job(client, client.post(f"/api/studies/{ct_id}/mesh", json={"threshold": 500, "smooth": False}))
    model = result["model"]
    assert model["vertices"] > 0 and model["triangles"] > 0
    assert model["coordinate_system"] == "RAS" and model["units"] == "mm"
    for filename in [model["mesh_file"], model["stl_file"]]:
        assert client.get(f"/api/studies/{ct_id}/assets/{filename}").status_code == 200
    result = wait_job(client, client.post(f"/api/studies/{projection['id']}/prepare"))
    assert result["image"]["width"] == 256
    image_response = client.get(f"/api/studies/{projection['id']}/assets/image.png")
    assert image_response.status_code == 200
    assert Image.open(io.BytesIO(image_response.content)).size == (256, 256)
    assert str(client.app.state.repository.root) not in json.dumps(result)


def test_optional_body_rendering_metadata_and_asset_remain_private(client, monkeypatch):
    import openbone.app as api

    original = api.imaging.prepare_ct

    def with_optional_display(root, entry, output):
        metadata = original(root, entry, output)
        if "body_volume_rendering" not in metadata:
            shutil.copyfile(output / metadata["volume_rendering"]["file"], output / "volume_render_body.rawz")
            metadata["body_volume_rendering"] = {**metadata["volume_rendering"], "file": "volume_render_body.rawz"}
        metadata["private_tags"] = {"PatientName": "private-patient-value"}
        for field in ("volume_rendering", "body_volume_rendering"):
            metadata[field]["input_path"] = "C:/private-patient-value/input.dcm"
            metadata[field]["raw_tags"] = {"PatientName": "private-patient-value"}
        return metadata

    monkeypatch.setattr(api.imaging, "prepare_ct", with_optional_display)
    response = client.post("/api/demo")
    study = next(item for item in response.json()["studies"] if item["kind"] == "ct")
    result = wait_job(client, client.post(f"/api/studies/{study['id']}/prepare"))
    metadata = result["metadata"]
    assert metadata["body_volume_rendering"]["file"] == "volume_render_body.rawz"
    assert "private-patient-value" not in json.dumps(result)
    response = client.get(f"/api/studies/{study['id']}/metadata")
    assert response.status_code == 200 and "private-patient-value" not in response.text
    response = client.get(f"/api/studies/{study['id']}/assets/metadata.json")
    assert response.status_code == 200 and "private-patient-value" not in response.text
    response = client.get(f"/api/studies/{study['id']}/assets/volume_render_body.rawz")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    assert "content-encoding" not in response.headers


def test_folder_upload_persistence_and_shared_source_deletion(client):
    response = client.post("/api/import", files=[
        ("files", ("folder/a.png", png_bytes("red"), "image/png")),
        ("files", ("folder/subfolder/b.png", png_bytes("blue"), "image/png")),
    ])
    assert response.status_code == 200, response.text
    studies = response.json()["studies"]
    assert len(studies) == 2
    assert response.json()["warnings"]
    first, second = studies
    root = client.app.state.repository.root
    with TestClient(create_app(root), base_url="http://localhost") as reopened:
        assert len(reopened.get("/api/studies").json()["studies"]) == 2
    assert client.delete(f"/api/studies/{first['id']}").status_code == 200
    assert any((root / "imports").iterdir())
    result = wait_job(client, client.post(f"/api/studies/{second['id']}/prepare"))
    assert result["image"]["width"] == 24
    assert client.get(f"/api/studies/{second['id']}/assets/manifest.json").status_code == 404
    assert client.get(f"/api/studies/{second['id']}/assets/file-00001.png").status_code == 404
    assert client.delete(f"/api/studies/{second['id']}").status_code == 200
    assert list((root / "imports").iterdir()) == []
    assert client.get("/api/studies").json() == {"studies": []}


@pytest.mark.parametrize("name", ["../escape.png", "/absolute.png", "folder/../../escape.png", "NUL.png"])
def test_unsafe_upload_paths_are_rejected_and_cleaned(client, name):
    result = client.post("/api/import", files={"files": (name, png_bytes(), "image/png")})
    assert result.status_code == 400, result.text
    assert list(client.app.state.repository.imports.iterdir()) == []


def test_windows_browser_upload_filename_is_normalized_and_stored_opaquely(client):
    # python-multipart strips the Windows client path before exposing filename.
    response = client.post("/api/import", files={"files": ("C:\\private\\escape.png", png_bytes(), "image/png")})
    assert response.status_code == 200, response.text
    study = response.json()["studies"][0]
    assert "private" not in json.dumps(study) and "escape" not in json.dumps(study)
    source_files = [path for path in client.app.state.repository.imports.rglob("*") if path.is_file()]
    assert len(source_files) == 1 and source_files[0].name == "file-00000.png"


@pytest.mark.parametrize("archive_type", ["traversal", "symlink", "bomb", "file_count"])
def test_unsafe_zip_archives_are_rejected(client, monkeypatch, archive_type):
    import openbone.app as api

    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if archive_type == "traversal":
            archive.writestr("../escape.png", png_bytes())
        elif archive_type == "symlink":
            info = zipfile.ZipInfo("link")
            info.create_system = 3
            info.external_attr = 0o120777 << 16
            archive.writestr(info, "../../outside")
        elif archive_type == "bomb":
            archive.writestr("very-compressible.dcm", b"0" * (9 * 1024 * 1024))
        else:
            monkeypatch.setattr(api, "MAX_FILES", 3)
            for index in range(4):
                archive.writestr(f"{index}.png", png_bytes())
    result = client.post("/api/import", files={"files": ("study.zip", data.getvalue(), "application/zip")})
    assert result.status_code in {400, 413}, result.text
    assert list(client.app.state.repository.imports.iterdir()) == []


def test_zip_ordinary_image_and_opaque_assets(client):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("检查目录 /踝关节 /private-image.png ", png_bytes())
    response = client.post("/api/import", files={"files": ("private-patient-name.zip", data.getvalue(), "application/zip")})
    assert response.status_code == 200, response.text
    study = response.json()["studies"][0]
    assert "private" not in json.dumps(study)
    wait_job(client, client.post(f"/api/studies/{study['id']}/prepare"))
    assert client.get(f"/api/studies/{study['id']}/assets/image.png").status_code == 200
    assert client.get(f"/api/studies/{study['id']}/assets/private-image.png").status_code == 404
    assert client.get("/api/imports/anything").status_code == 404


def test_loopback_host_and_cross_origin_write_guards(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/health", headers={"Host": "attacker.example"}).status_code == 403
    assert client.get("/api/health", headers={"Host": "192.168.1.8"}).status_code == 403
    assert client.get("/api/health", headers={"Host": "[::1]"}).status_code == 200
    assert client.post("/api/demo", headers={"Origin": "https://attacker.example"}).status_code == 403
    assert client.post("/api/demo", headers={"Origin": "null"}).status_code == 403
    assert client.post("/api/demo", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.post("/api/demo", headers={"Content-Length": str(2 * 1024**3)}).status_code == 413


def test_generic_task_failure_does_not_disclose_paths(client, monkeypatch):
    import openbone.app as api

    response = client.post("/api/import", files={"files": ("input.png", png_bytes(), "image/png")})
    study = response.json()["studies"][0]

    def fail(*args, **kwargs):
        raise RuntimeError("secret patient name C:/private/secret.dcm")

    monkeypatch.setattr(api.imaging, "prepare_xray", fail)
    response = client.post(f"/api/studies/{study['id']}/prepare")
    identifier = response.json()["id"]
    for _ in range(100):
        job = client.get(f"/api/jobs/{identifier}").json()
        if job["status"] == "error":
            break
        time.sleep(0.01)
    assert job["status"] == "error"
    assert "secret" not in json.dumps(job)
    assert client.get(f"/api/studies/{study['id']}/metadata").status_code == 409


def test_large_image_jobs_are_serial_and_active_studies_cannot_be_deleted(client, monkeypatch):
    import openbone.app as api

    response = client.post("/api/import", files=[
        ("files", ("a.png", png_bytes("red"), "image/png")),
        ("files", ("b.png", png_bytes("blue"), "image/png")),
    ])
    first, second = response.json()["studies"]
    original = api.imaging.prepare_xray
    started = threading.Event()
    release = threading.Event()
    invocations = []

    def controlled(root, entry, output):
        invocations.append(entry["id"])
        if len(invocations) == 1:
            started.set()
            assert release.wait(5)
        return original(root, entry, output)

    monkeypatch.setattr(api.imaging, "prepare_xray", controlled)
    first_response = client.post(f"/api/studies/{first['id']}/prepare")
    assert started.wait(5)
    try:
        second_response = client.post(f"/api/studies/{second['id']}/prepare")
        assert second_response.status_code == 202
        assert client.get(f"/api/jobs/{second_response.json()['id']}").json()["status"] == "queued"
        assert client.delete(f"/api/studies/{first['id']}").status_code == 409
        assert len(invocations) == 1
    finally:
        release.set()
    wait_job(client, first_response)
    wait_job(client, second_response)
    assert len(invocations) == 2


def _import_projection(client):
    response = client.post("/api/import", files={"files": ("input.png", png_bytes(), "image/png")})
    assert response.status_code == 200, response.text
    return response.json()["studies"][0]["id"]


@pytest.mark.parametrize("failure", ["queued_save", "executor_submit"])
def test_job_creation_failures_roll_back_queue(client, monkeypatch, failure):
    import openbone.app as api

    study_id = _import_projection(client)
    repository = client.app.state.repository

    def fail(*args, **kwargs):
        raise OSError("private path must not appear in response")

    if failure == "queued_save":
        monkeypatch.setattr(api, "_save_json", fail)
    else:
        monkeypatch.setattr(repository.executor, "submit", fail)
    response = client.post(f"/api/studies/{study_id}/prepare")
    assert response.status_code == 503
    assert "private" not in response.text
    assert repository.jobs == {}
    assert list(repository.jobs_root.glob("*.json")) == []


def test_running_state_save_failure_becomes_error_and_allows_retry(client, monkeypatch):
    import openbone.app as api

    study_id = _import_projection(client)
    original = api._save_json
    jobs_root = client.app.state.repository.jobs_root

    def fail_running(path, value):
        if path.parent == jobs_root and value.get("status") == "running":
            raise OSError("private path must not appear in response")
        original(path, value)

    monkeypatch.setattr(api, "_save_json", fail_running)
    response = client.post(f"/api/studies/{study_id}/prepare")
    assert response.status_code == 202
    for _ in range(100):
        job = client.get(f"/api/jobs/{response.json()['id']}").json()
        if job["status"] == "error":
            break
        time.sleep(0.01)
    assert job["status"] == "error"
    assert "private" not in json.dumps(job)
    monkeypatch.setattr(api, "_save_json", original)
    wait_job(client, client.post(f"/api/studies/{study_id}/prepare"))


@pytest.mark.parametrize("final_status", ["done", "error"])
def test_final_job_save_failure_never_strands_a_running_task(client, monkeypatch, final_status):
    import openbone.app as api

    study_id = _import_projection(client)
    original = api._save_json
    jobs_root = client.app.state.repository.jobs_root

    def fail_terminal_save(path, value):
        if path.parent == jobs_root and value.get("status") in {"done", "error"}:
            raise OSError("cannot save job state")
        original(path, value)

    monkeypatch.setattr(api, "_save_json", fail_terminal_save)
    if final_status == "error":
        def broken_image(*args, **kwargs):
            raise RuntimeError("cannot process image")
        monkeypatch.setattr(api.imaging, "prepare_xray", broken_image)
    response = client.post(f"/api/studies/{study_id}/prepare")
    assert response.status_code == 202
    for _ in range(100):
        job = client.get(f"/api/jobs/{response.json()['id']}").json()
        if job["status"] in {"done", "error"}:
            break
        time.sleep(0.01)
    assert job["status"] == final_status
    assert client.delete(f"/api/studies/{study_id}").status_code == 200
