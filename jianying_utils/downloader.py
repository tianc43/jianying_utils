"""Local Jianying draft downloader/importer.

The server can generate portable draft ZIP files without knowing a user's
Jianying path placeholder. This module runs on the user's Windows machine and
performs the final local adaptation before Jianying opens the draft.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path
from typing import Any, Iterable, Optional


PLACEHOLDER_RE = re.compile(r"##_draftpath_placeholder_([^#]+)_##")
PLACEHOLDER_PATH_RE = re.compile(r"^##_draftpath_placeholder_[^#]+_##[/\\](.+)$")
MATERIAL_PREFIXES = ("audio/", "image/", "video/")


def install_draft(
    source: str,
    drafts_dir: Optional[str] = None,
    draft_name: Optional[str] = None,
    placeholder_id: Optional[str] = None,
    overwrite: bool = False,
) -> Path:
    """Download/extract a portable draft ZIP and install it for local Jianying."""
    target_root = Path(drafts_dir or find_default_drafts_dir()).expanduser().resolve()
    if not target_root.is_dir():
        raise RuntimeError(f"Jianying drafts directory does not exist: {target_root}")

    local_placeholder = placeholder_id or detect_placeholder_id(target_root)
    if not local_placeholder:
        raise RuntimeError(
            "Cannot detect Jianying draft placeholder ID. Create one blank draft in "
            "Jianying first, or pass --placeholder-id."
        )

    with tempfile.TemporaryDirectory(prefix="jy_downloader_") as tmp:
        tmp_dir = Path(tmp)
        zip_path = fetch_source(source, tmp_dir)
        extract_dir = tmp_dir / "extract"
        extract_zip_safe(zip_path, extract_dir)

        source_root = single_root_or_self(extract_dir)
        resolved_name = draft_name or infer_draft_name(source_root, zip_path)
        target_dir = unique_target_dir(target_root, resolved_name, overwrite)
        shutil.copytree(source_root, target_dir)

    rewrite_draft(target_dir, target_root, local_placeholder)
    return target_dir


def fetch_source(source: str, tmp_dir: Path) -> Path:
    parsed = urllib.parse.urlparse(source)
    if parsed.scheme in ("http", "https"):
        filename = Path(urllib.parse.unquote(Path(parsed.path).name or "draft.zip")).name
        if not filename.lower().endswith(".zip"):
            filename = f"{filename}.zip"
        out = tmp_dir / filename
        with urllib.request.urlopen(source, timeout=120) as response:
            out.write_bytes(response.read())
        return out

    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise RuntimeError(f"ZIP file does not exist: {path}")
    return path


def extract_zip_safe(zip_path: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    root = target_dir.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if not name or name.startswith("/") or ".." in Path(name).parts:
                raise RuntimeError(f"Unsafe ZIP member path: {info.filename}")
            dest = (root / name).resolve()
            if root not in dest.parents and dest != root:
                raise RuntimeError(f"Unsafe ZIP member path: {info.filename}")
        zf.extractall(root)


def single_root_or_self(extract_dir: Path) -> Path:
    entries = [p for p in extract_dir.iterdir() if p.name != "__MACOSX"]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return extract_dir


def infer_draft_name(source_root: Path, zip_path: Path) -> str:
    content_path = source_root / "draft_content.json"
    if content_path.is_file():
        try:
            data = json.loads(content_path.read_text(encoding="utf-8-sig"))
            name = str(data.get("name") or data.get("draft_name") or "").strip()
            if name:
                return sanitize_name(name)
        except Exception:
            pass
    return sanitize_name(zip_path.stem or f"draft_{uuid.uuid4().hex[:8]}")


def sanitize_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    return cleaned or f"draft_{uuid.uuid4().hex[:8]}"


def unique_target_dir(root: Path, name: str, overwrite: bool) -> Path:
    target = root / sanitize_name(name)
    if overwrite:
        if target.exists():
            shutil.rmtree(target)
        return target
    if not target.exists():
        return target
    for index in range(2, 1000):
        candidate = root / f"{target.name}_{index}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Cannot choose a unique draft directory under {root}")


def rewrite_draft(draft_dir: Path, drafts_root: Path, placeholder_id: str) -> None:
    draft_name = draft_dir.name
    for path in draft_dir.rglob("*"):
        if path.is_file() and is_json_like_draft_file(path.name):
            rewrite_json_file(path, draft_dir, drafts_root, draft_name, placeholder_id)


def is_json_like_draft_file(filename: str) -> bool:
    return (
        filename in {
            "draft_content.json",
            "draft_info.json",
            "draft_meta_info.json",
            "attachment_pc_common.json",
            "draft_agency_config.json",
        }
        or filename.startswith("template")
        and filename.endswith(".tmp")
    )


def rewrite_json_file(
    path: Path,
    draft_dir: Path,
    drafts_root: Path,
    draft_name: str,
    placeholder_id: str,
) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return

    data = rewrite_json_value(data, draft_dir, drafts_root, draft_name, placeholder_id)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")


def rewrite_json_value(
    value: Any,
    draft_dir: Path,
    drafts_root: Path,
    draft_name: str,
    placeholder_id: str,
) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key == "draft_name":
                result[key] = draft_name
            elif key == "draft_fold_path":
                result[key] = str(draft_dir).replace("\\", "/")
            elif key == "draft_root_path":
                result[key] = str(drafts_root)
            elif key == "name" and isinstance(item, str) and not item:
                result[key] = draft_name
            else:
                result[key] = rewrite_json_value(item, draft_dir, drafts_root, draft_name, placeholder_id)
        return result
    if isinstance(value, list):
        return [rewrite_json_value(item, draft_dir, drafts_root, draft_name, placeholder_id) for item in value]
    if isinstance(value, str):
        return rewrite_material_path(value, draft_dir, placeholder_id)
    return value


def rewrite_material_path(value: str, draft_dir: Path, placeholder_id: str) -> str:
    normalized = value.replace("\\", "/")

    match = PLACEHOLDER_PATH_RE.match(normalized)
    if match:
        return make_placeholder_path(placeholder_id, match.group(1))

    if normalized.startswith("__DRAFT_ROOT__/"):
        return make_placeholder_path(placeholder_id, normalized[len("__DRAFT_ROOT__/"):])

    if normalized.startswith(MATERIAL_PREFIXES):
        return make_placeholder_path(placeholder_id, normalized)

    path = Path(value)
    if path.is_absolute():
        try:
            rel = path.resolve().relative_to(draft_dir.resolve())
        except Exception:
            return value
        return make_placeholder_path(placeholder_id, rel.as_posix())

    return value


def make_placeholder_path(placeholder_id: str, suffix: str) -> str:
    normalized_suffix = suffix.replace("\\", "/")
    return f"##_draftpath_placeholder_{placeholder_id}_##/{normalized_suffix}"


def detect_placeholder_id(drafts_root: Path) -> Optional[str]:
    counts: dict[str, int] = {}
    for content_path in iter_recent_draft_jsons(drafts_root):
        try:
            text = content_path.read_text(encoding="utf-8-sig", errors="ignore")
        except Exception:
            continue
        for match in PLACEHOLDER_RE.findall(text):
            counts[match] = counts.get(match, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda item: item[1])[0]


def iter_recent_draft_jsons(drafts_root: Path) -> Iterable[Path]:
    try:
        dirs = [p for p in drafts_root.iterdir() if p.is_dir()]
    except Exception:
        return []
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    result = []
    for draft_dir in dirs[:100]:
        for name in ("draft_content.json", "draft_info.json"):
            path = draft_dir / name
            if path.is_file():
                result.append(path)
    return result


def find_default_drafts_dir() -> str:
    candidates = []
    for env_name in ("JIANYING_NATIVE_DRAFTS_DIR", "JIANYING_DRAFTS_DIR"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(value)

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(
            str(Path(local_app_data) / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft")
        )
    candidates.append(r"D:\jianying\JianyingPro Drafts")

    for candidate in candidates:
        if candidate and Path(candidate).expanduser().is_dir():
            return candidate
    raise RuntimeError("Cannot find Jianying drafts directory. Pass --drafts-dir.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jianying-downloader")
    subparsers = parser.add_subparsers(dest="command", required=True)

    install = subparsers.add_parser("install", help="Download and install a portable draft ZIP")
    install.add_argument("--url", "--source", dest="source", required=True, help="Draft ZIP URL or local ZIP path")
    install.add_argument("--drafts-dir", help="Local Jianying drafts directory")
    install.add_argument("--draft-name", help="Installed draft folder name")
    install.add_argument("--placeholder-id", help="Override detected Jianying placeholder ID")
    install.add_argument("--overwrite", action="store_true", help="Overwrite an existing target draft folder")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "install":
        try:
            target = install_draft(
                source=args.source,
                drafts_dir=args.drafts_dir,
                draft_name=args.draft_name,
                placeholder_id=args.placeholder_id,
                overwrite=args.overwrite,
            )
        except Exception as exc:
            print(f"Install failed: {exc}", file=sys.stderr)
            return 1
        print(f"Installed draft: {target}")
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
