import os
import uuid
import httpx
from dotenv import load_dotenv

# Ensure env vars are loaded (safe to call multiple times)
load_dotenv()


def _supabase_config():
    """Read Supabase credentials fresh each call so dotenv timing doesn't matter."""
    return (
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_KEY"),
        os.getenv("SUPABASE_BUCKET", "certificates"),
    )


async def upload_file_to_supabase(
    file_bytes: bytes,
    filename: str,
    content_type: str = "application/pdf",
    folder: str = "certificates",
) -> str:
    """
    Uploads a file to Supabase Storage and returns the public URL.
    Raises RuntimeError if the upload fails so the caller gets a proper 500
    instead of silently falling back to local disk.
    """
    supabase_url, supabase_key, supabase_bucket = _supabase_config()

    unique_filename = f"{uuid.uuid4().hex}_{filename}"
    object_path = f"{folder}/{unique_filename}"

    if not supabase_url or not supabase_key:
        raise RuntimeError(
            "Supabase credentials (SUPABASE_URL / SUPABASE_KEY) are not set in the environment. "
            "Please add them to your .env file."
        )

    upload_url = (
        f"{supabase_url.rstrip('/')}/storage/v1/object/{supabase_bucket}/{object_path}"
    )
    headers = {
        "Authorization": f"Bearer {supabase_key}",
        "apikey": supabase_key,
        "Content-Type": content_type or "application/octet-stream",
        "x-upsert": "true",
    }

    print(f"[Supabase] Uploading to: {upload_url}")

    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.post(upload_url, content=file_bytes, headers=headers)

    if res.status_code in (200, 201):
        public_url = (
            f"{supabase_url.rstrip('/')}/storage/v1/object/public"
            f"/{supabase_bucket}/{object_path}"
        )
        print(f"[Supabase] Upload successful: {public_url}")
        return public_url

    # Supabase returned an error — surface it clearly
    print(f"[Supabase] Upload FAILED  status={res.status_code}  body={res.text}")
    raise RuntimeError(
        f"Supabase Storage upload failed (HTTP {res.status_code}): {res.text}"
    )
