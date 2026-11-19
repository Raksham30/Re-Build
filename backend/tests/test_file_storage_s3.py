"""file_storage against a mocked S3 (moto): upload, read back, delete, workspace purge."""
import os
import pytest

moto = pytest.importorskip("moto")


@pytest.fixture()
def fs(tmp_path, monkeypatch):
    import boto3
    from app.config import get_settings
    from app.services import file_storage
    with moto.mock_aws():
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
        monkeypatch.setenv("S3_BUCKET", "papers-test")
        monkeypatch.setenv("S3_ACCESS_KEY_ID", "k")
        monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "s")
        monkeypatch.setenv("S3_REGION", "us-east-1")
        monkeypatch.setenv("S3_ENDPOINT_URL", "")
        monkeypatch.setenv("LOCAL_UPLOAD_DIR", str(tmp_path / "up"))
        get_settings.cache_clear(); file_storage.reset_client()
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="papers-test")
        yield file_storage
        get_settings.cache_clear(); file_storage.reset_client()


def _keys():
    import boto3
    r = boto3.client("s3", region_name="us-east-1").list_objects_v2(Bucket="papers-test")
    return sorted(o["Key"] for o in r.get("Contents", []))


def test_roundtrip_and_delete(fs):
    key, local = fs.save_pdf("w1", "p1", b"%PDF-1 data")
    assert key == "w1/p1.pdf" and os.path.exists(local)
    assert _keys() == ["w1/p1.pdf"]
    assert fs.get_pdf_bytes("w1", "p1") == b"%PDF-1 data"
    fs.delete_pdf("w1", "p1")
    assert _keys() == [] and not os.path.exists(local)
    assert fs.get_pdf_bytes("w1", "p1") is None
    fs.delete_pdf("w1", "p1")                      # deleting twice must not raise


def test_delete_workspace_only_touches_that_workspace(fs):
    for ws, pid in (("w1", "a"), ("w1", "b"), ("w2", "c")):
        fs.save_pdf(ws, pid, b"x")
    fs.delete_workspace_files("w1")
    assert _keys() == ["w2/c.pdf"]


def test_local_mode_when_s3_not_configured(tmp_path, monkeypatch):
    from app.config import get_settings
    from app.services import file_storage
    for v in ("S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(v, "")
    monkeypatch.setenv("LOCAL_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    path, local = file_storage.save_pdf("w", "p", b"hi")
    assert path == local and file_storage.get_pdf_bytes("w", "p") == b"hi"
    get_settings.cache_clear()
