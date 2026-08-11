import os
import uuid
import httpx
from dotenv import load_dotenv

# Ensure env vars are loaded
load_dotenv()


def _supabase_config():
    """Read Supabase credentials fresh each call."""
    return (
        os.getenv("SUPABASE_URL", "").rstrip("/"),
        os.getenv("SUPABASE_KEY", ""),
    )


async def upload_file_to_supabase(
    file_bytes: bytes,
    filename: str,
    content_type: str = "application/pdf",
    bucket_name: str = "certificates",
) -> str:
    """
    Uploads a file directly to a specified Supabase Storage bucket ('certificates' or 'medicines')
    and returns the public URL.
    """
    supabase_url, supabase_key = _supabase_config()

    if not supabase_url or not supabase_key:
        raise RuntimeError(
            "Supabase credentials (SUPABASE_URL / SUPABASE_KEY) are not set in the environment. "
            "Please check your .env file."
        )

    ext = os.path.splitext(filename)[1]
    unique_filename = f"{uuid.uuid4().hex}{ext}"

    upload_url = f"{supabase_url}/storage/v1/object/{bucket_name}/{unique_filename}"
    headers = {
        "Authorization": f"Bearer {supabase_key}",
        "apikey": supabase_key,
        "Content-Type": content_type or "application/octet-stream",
        "x-upsert": "true",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.post(upload_url, content=file_bytes, headers=headers)

    if res.status_code in (200, 201):
        public_url = f"{supabase_url}/storage/v1/object/public/{bucket_name}/{unique_filename}"
        print(f"[Supabase] Upload successful: {public_url}")
        return public_url

    # Surface Supabase error clearly
    print(f"[Supabase] Upload FAILED status={res.status_code} body={res.text}")
    raise RuntimeError(
        f"Supabase Storage upload to bucket '{bucket_name}' failed (HTTP {res.status_code}): {res.text}"
    )
