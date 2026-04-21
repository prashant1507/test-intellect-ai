const ARCHIVE_SUFFIXES = new Set([
  ".zip",
  ".rar",
  ".7z",
  ".tar",
  ".gz",
  ".tgz",
  ".bz2",
  ".xz",
  ".jar",
  ".war",
]);

export function isBlockedArchiveFilename(name) {
  if (!name || typeof name !== "string") return false;
  const i = name.lastIndexOf(".");
  if (i < 0) return false;
  return ARCHIVE_SUFFIXES.has(name.slice(i).toLowerCase());
}

export const ARCHIVE_NOT_ALLOWED_MSG =
  "Archive files (e.g. ZIP) are not allowed as mockups. Use PNG, JPEG, GIF, WebP, or PDF.";
