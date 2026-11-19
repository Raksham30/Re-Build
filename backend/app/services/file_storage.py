"""
Stores/retrieves the raw uploaded PDF bytes.

Configured (S3_BUCKET + keys): any S3-compatible store (Cloudflare R2, AWS S3,
            MinIO) under {workspace_id}/{paper_id}.pdf
Not configured: local disk under data/uploads/{workspace_id}/{paper_id}.pdf
            (development only -- container disks are ephemeral).

Parsing needs a local file path, so save_pdf() returns BOTH a storage_path
(what you'd persist/reference) and a guaranteed-local path to hand to the parser.
"""
import os
import shutil
from app.config import get_settings

_s3_client = None


def _key(workspace_id: str, paper_id: str) -> str:
    return f"{workspace_id}/{paper_id}.pdf"


def _get_s3():
    global _s3_client
    if _s3_client is None:
        import boto3
        from botocore.config import Config
        s = get_settings()
        _s3_client = boto3.client(
            "s3",
            endpoint_url=s.s3_endpoint_url or None,
            aws_access_key_id=s.s3_access_key_id,
            aws_secret_access_key=s.s3_secret_access_key,
            region_name=s.s3_region,
            config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"}),
        )
    return _s3_client


def reset_client() -> None:
    """Drops the cached S3 client (used when settings change, e.g. in tests)."""
    global _s3_client
    _s3_client = None


def save_pdf(workspace_id: str, paper_id: str, content: bytes) -> tuple[str, str]:
    """Returns (storage_path, local_path_for_parsing)."""
    settings = get_settings()
    local_dir = os.path.join(settings.local_upload_dir, workspace_id)
    os.makedirs(local_dir, exist_ok=True)
    local_path = os.path.join(local_dir, f"{paper_id}.pdf")
    # Always keep a local copy -- it's the parser's scratch file either way,
    # and it's the only copy at all when S3 isn't configured.
    with open(local_path, "wb") as f:
        f.write(content)

    if settings.use_s3:
        key = _key(workspace_id, paper_id)
        _get_s3().put_object(
            Bucket=settings.s3_bucket, Key=key, Body=content, ContentType="application/pdf"
        )
        return key, local_path

    return local_path, local_path


def get_pdf_bytes(workspace_id: str, paper_id: str) -> bytes | None:
    """Returns the stored PDF, or None if it doesn't exist."""
    settings = get_settings()
    if settings.use_s3:
        from botocore.exceptions import ClientError
        try:
            obj = _get_s3().get_object(Bucket=settings.s3_bucket, Key=_key(workspace_id, paper_id))
            return obj["Body"].read()
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                return None
            raise
    path = os.path.join(settings.local_upload_dir, workspace_id, f"{paper_id}.pdf")
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def delete_pdf(workspace_id: str, paper_id: str) -> None:
    """Removes the stored PDF (local copy + object). Missing files are ignored."""
    settings = get_settings()
    local_path = os.path.join(settings.local_upload_dir, workspace_id, f"{paper_id}.pdf")
    if os.path.exists(local_path):
        os.remove(local_path)
    if settings.use_s3:
        # S3 delete_object is already idempotent (no error for a missing key).
        _get_s3().delete_object(Bucket=settings.s3_bucket, Key=_key(workspace_id, paper_id))


def delete_workspace_files(workspace_id: str) -> None:
    """Removes every stored PDF for a workspace (local folder + objects)."""
    settings = get_settings()
    shutil.rmtree(os.path.join(settings.local_upload_dir, workspace_id), ignore_errors=True)
    if settings.use_s3:
        s3 = _get_s3()
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=settings.s3_bucket, Prefix=f"{workspace_id}/"):
            objs = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if objs:
                s3.delete_objects(Bucket=settings.s3_bucket, Delete={"Objects": objs, "Quiet": True})
