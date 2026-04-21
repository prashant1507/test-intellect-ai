from __future__ import annotations

import base64
from pathlib import Path

from fastapi import HTTPException

_ALLOWED = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf"})
_ARCHIVE_SUFFIXES = frozenset({".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".jar", ".war"})


def _norm_mime(m: str) -> str:
    x = (m or "").strip().lower().split(";")[0].strip()
    if x == "image/jpg":
        return "image/jpeg"
    return x


def _archive_suffix(filename: str) -> bool:
    return Path(filename or "").suffix.lower() in _ARCHIVE_SUFFIXES


def _looks_like_zip_archive(data: bytes) -> bool:
    return len(data) >= 4 and data[:4] == b"PK\x03\x04"


def _reject_archives(fn: str, data: bytes) -> None:
    if _archive_suffix(fn):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Archive files are not allowed as mockups ({fn or 'file'}). "
                "Use PNG, JPEG, GIF, WebP, or PDF."
            ),
        )
    if _looks_like_zip_archive(data):
        raise HTTPException(
            status_code=400,
            detail=(
                "ZIP archives are not allowed as mockups (file contents look like a ZIP). "
                "Use PNG, JPEG, GIF, WebP, or PDF."
            ),
        )


def sniff_image_mime(data: bytes) -> str | None:
    if len(data) >= 8 and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 3 and data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(data) >= 6 and data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def sniff_pdf_mime(data: bytes) -> str | None:
    if len(data) >= 4 and data.startswith(b"%PDF"):
        return "application/pdf"
    return None


def _validated_name_mime(fn: str, mime_hint: str, data: bytes, *, upload: bool) -> tuple[str, str]:
    m = sniff_image_mime(data) or sniff_pdf_mime(data) or _norm_mime(mime_hint)
    if m not in _ALLOWED:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported or invalid file type for {fn or 'upload'}. Use PNG, JPEG, GIF, WebP, or PDF."
                if upload
                else f"Attachment {fn} is not supported (PNG, JPEG, GIF, WebP, or PDF)."
            ),
        )
    if upload:
        raw = (fn or "").strip()
        if raw:
            name = raw
        else:
            name = "upload.pdf" if m == "application/pdf" else "upload.png"
    else:
        name = fn
    return name, m


def merge_and_validate(
    *,
    enabled: bool,
    max_count: int,
    max_total_bytes: int,
    uploads: list[tuple[str, bytes, str]],
    jira_parts: list[tuple[str, str, bytes]],
) -> list[tuple[str, str, bytes]]:
    if not enabled:
        if uploads or jira_parts:
            raise HTTPException(
                status_code=400,
                detail="Requirement images are disabled (LLM_REQUIREMENT_IMAGES_ENABLED=false).",
            )
        return []
    combined: list[tuple[str, str, bytes]] = []
    for fn, data, ct in uploads:
        _reject_archives(fn, data)
        name, m = _validated_name_mime(fn, ct, data, upload=True)
        combined.append((name, m, data))
    for fn, mime, data in jira_parts:
        _reject_archives(fn, data)
        name, m = _validated_name_mime(fn, mime, data, upload=False)
        combined.append((name, m, data))
    if len(combined) > max_count:
        raise HTTPException(
            status_code=400,
            detail=f"At most {max_count} file(s) total (uploads + selected ticket attachments).",
        )
    total = sum(len(b) for _, _, b in combined)
    if total > max_total_bytes:
        mb = max_total_bytes // (1024 * 1024)
        raise HTTPException(
            status_code=400,
            detail=f"Combined attachment size exceeds the server limit ({mb} MB).",
        )
    return combined


def images_to_state_payload(images: list[tuple[str, str, bytes]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for fn, mime, data in images:
        out.append(
            {
                "filename": fn,
                "mime_type": mime,
                "b64": base64.b64encode(data).decode("ascii"),
            }
        )
    return out


def state_payload_to_images(rows: list[dict] | None) -> list[tuple[str, str, bytes]]:
    out: list[tuple[str, str, bytes]] = []
    for x in rows or []:
        if not isinstance(x, dict):
            continue
        b64 = (x.get("b64") or "").strip()
        if not b64:
            continue
        try:
            raw = base64.b64decode(b64)
        except Exception:
            continue
        fn = str(x.get("filename") or "image").strip() or "image"
        mt = str(x.get("mime_type") or "image/png").strip() or "image/png"
        out.append((fn, mt, raw))
    return out
