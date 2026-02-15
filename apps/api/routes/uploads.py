"""Presigned-upload routes for direct-to-R2 browser uploads."""

import logging
import uuid

import boto3
from fastapi import APIRouter, HTTPException

from apps.api.config import (
    R2_ACCESS_KEY_ID,
    R2_BUCKET_NAME,
    R2_ENDPOINT_URL,
    R2_SECRET_ACCESS_KEY,
    is_r2_available,
)
from apps.api.models.schemas import PresignRequest, PresignResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.post("/uploads/presign", response_model=PresignResponse)
async def presign_upload(body: PresignRequest):
    """Generate a presigned PUT URL so the browser can upload directly to R2."""
    if not is_r2_available():
        raise HTTPException(
            501,
            "Direct upload not available: R2 storage is not configured. "
            "Use multipart upload to /api/jobs instead.",
        )

    file_key = f"originals/{uuid.uuid4()}/{body.filename}"

    client = boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT_URL,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )

    upload_url = client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": R2_BUCKET_NAME,
            "Key": file_key,
            "ContentType": body.content_type,
        },
        ExpiresIn=900,
    )

    logger.info(f"Presigned PUT URL generated: key={file_key}")
    return PresignResponse(file_key=file_key, upload_url=upload_url)
