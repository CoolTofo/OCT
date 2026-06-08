import hashlib
import json
import shutil
import time
import zipfile
from pathlib import Path


SRC = Path.cwd()
PARENT = SRC.parent
STAMP = time.strftime("%Y%m%d_%H%M%S")
OUT_ROOT = SRC / "dist_migration"
BUNDLE_ROOT = OUT_ROOT / f"OCT_migration_dev_{STAMP}"
PACKAGE_DIR = OUT_ROOT / f"OCT_migration_dev_{STAMP}_packages"
ROOT_NAME = BUNDLE_ROOT.name

SPLIT_THRESHOLD = 8 * 1024 * 1024
PART_SIZE = 8 * 1024 * 1024
ZIP_TARGET = 8 * 1024 * 1024
ZIP_LIMIT = 10 * 1024 * 1024

INCLUDE_DIRS = [
    "app",
    "static",
    "tools",
    "python",
    "packages",
    "workflows",
    "Doc",
    "data/canvases",
    "data/comfyui_exports",
    "assets/library",
]

INCLUDE_FILES = [
    "main.py",
    "requirements.txt",
    "VERSION",
    ".gitignore",
    "python.zip",
    "API/.env",
    "API/.env.example",
    "data/api_providers.json",
    "data/asset_library.json",
    "data/prompt_templates.json",
    "data/runninghub_workflows.json",
]

PARENT_FILES = [
    ".editorconfig",
    ".gitattributes",
    ".gitignore",
    ".codexignore",
    "README.md",
]

EMPTY_DIRS = [
    "assets/input",
    "assets/output",
    "assets/preview",
    "output",
    "data/conversations",
]

EXCLUDE_DIR_NAMES = {"__pycache__", ".git", ".svn"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}
EXCLUDE_NAMES = {"tmp_server_err.log", "tmp_server_out.log"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def should_exclude(path: Path) -> bool:
    if set(path.parts) & EXCLUDE_DIR_NAMES:
        return True
    if path.suffix.lower() in EXCLUDE_SUFFIXES:
        return True
    return path.name in EXCLUDE_NAMES


def copy_or_split(src_file: Path, rel: str, split_manifest: list) -> None:
    rel = rel.replace("\\", "/").lstrip("/")
    size = src_file.stat().st_size
    digest = sha256_file(src_file)
    if size <= SPLIT_THRESHOLD:
        dest = BUNDLE_ROOT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dest)
        return

    part_rel_dir = Path("_split_files") / rel
    part_dest_dir = BUNDLE_ROOT / part_rel_dir.parent
    part_dest_dir.mkdir(parents=True, exist_ok=True)
    parts = []
    with src_file.open("rb") as handle:
        index = 1
        while True:
            chunk = handle.read(PART_SIZE)
            if not chunk:
                break
            part_name = f"{part_rel_dir.name}.part{index:03d}"
            part_rel = (part_rel_dir.parent / part_name).as_posix()
            (BUNDLE_ROOT / part_rel).write_bytes(chunk)
            parts.append({"path": part_rel, "bytes": len(chunk)})
            index += 1
    split_manifest.append(
        {"target": rel, "bytes": size, "sha256": digest, "parts": parts}
    )


def write_restore_files(split_manifest: list) -> None:
    manifest_path = BUNDLE_ROOT / "_split_files_manifest.json"
    manifest_path.write_text(
        json.dumps(split_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    restore_script = r"""$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ManifestPath = Join-Path $Root '_split_files_manifest.json'
if (!(Test-Path -LiteralPath $ManifestPath)) {
    Write-Host 'No split file manifest found. Nothing to restore.'
    exit 0
}
$Items = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($Item in $Items) {
    $Target = Join-Path $Root $Item.target
    New-Item -ItemType Directory -Force -Path (Split-Path $Target -Parent) | Out-Null
    if (Test-Path -LiteralPath $Target) { Remove-Item -LiteralPath $Target -Force }
    $Out = [System.IO.File]::Open($Target, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write)
    try {
        foreach ($Part in $Item.parts) {
            $PartPath = Join-Path $Root $Part.path
            if (!(Test-Path -LiteralPath $PartPath)) { throw "Missing part: $($Part.path)" }
            $In = [System.IO.File]::OpenRead($PartPath)
            try { $In.CopyTo($Out) } finally { $In.Dispose() }
        }
    } finally { $Out.Dispose() }
    $Hash = (Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($Hash -ne [string]$Item.sha256) { throw "SHA256 mismatch: $($Item.target)" }
    Write-Host "Restored $($Item.target)"
}
Write-Host 'Large files restored successfully.'
"""
    (BUNDLE_ROOT / "restore-large-files.ps1").write_text(
        restore_script, encoding="utf-8"
    )

    readme = f"""# OCT migration development clean package

Created: {STAMP}

This package is for moving to another computer while keeping the project runnable
and editable.

Included:
- Source/runtime files: main.py, app/, static/, tools/
- Embedded runtime: python/
- Offline dependency wheels: packages/
- Recovery archive: python.zip
- Docs: Doc/ and root help files
- Existing workflows and presets: workflows/, data/comfyui_exports/,
  data/runninghub_workflows.json, data/prompt_templates.json,
  data/asset_library.json, data/canvases/, assets/library/
- API settings and existing keys: API/.env, API/.env.example,
  data/api_providers.json
- Parent development helper files: _dev_root_files/

Cleaned:
- Generated input/output media under assets/input, assets/output,
  assets/preview, and output
- Conversation contents under data/conversations
- Python bytecode caches and temporary logs

Restore on the new computer:
1. Extract all OCT_migration_dev_{STAMP}_part*.zip files to the same folder.
2. Enter the extracted {ROOT_NAME} folder.
3. Run PowerShell: ./restore-large-files.ps1
4. Double-click the launch script.
5. If dependencies are missing, run the install-dependencies script.

Warning: API/.env is included and may contain API keys. Do not upload this package
to public storage or share it with untrusted people.
"""
    (BUNDLE_ROOT / "MIGRATION_DEV_README.md").write_text(readme, encoding="utf-8")


def collect_files(split_manifest: list) -> None:
    BUNDLE_ROOT.mkdir(parents=True, exist_ok=True)
    PACKAGE_DIR.mkdir(parents=True, exist_ok=True)

    for rel_dir in INCLUDE_DIRS:
        src_dir = SRC / rel_dir
        if not src_dir.exists():
            continue
        for src_file in src_dir.rglob("*"):
            if src_file.is_file() and not should_exclude(src_file):
                copy_or_split(src_file, src_file.relative_to(SRC).as_posix(), split_manifest)

    for rel in INCLUDE_FILES:
        src_file = SRC / rel
        if src_file.exists() and src_file.is_file() and not should_exclude(src_file):
            copy_or_split(src_file, rel, split_manifest)

    for rel in PARENT_FILES:
        src_file = PARENT / rel
        if src_file.exists() and src_file.is_file() and not should_exclude(src_file):
            copy_or_split(src_file, f"_dev_root_files/{rel}", split_manifest)

    for src_file in SRC.iterdir():
        if (
            src_file.is_file()
            and src_file.suffix.lower() in {".bat", ".command", ".md", ".txt"}
            and not should_exclude(src_file)
        ):
            copy_or_split(src_file, src_file.name, split_manifest)

    for rel_dir in EMPTY_DIRS:
        folder = BUNDLE_ROOT / rel_dir
        folder.mkdir(parents=True, exist_ok=True)
        (folder / ".gitkeep").write_text("", encoding="utf-8")


def zip_bundle() -> list:
    files = sorted(
        [path for path in BUNDLE_ROOT.rglob("*") if path.is_file()],
        key=lambda path: path.relative_to(BUNDLE_ROOT).as_posix(),
    )
    groups = []
    current = []
    current_size = 0
    for path in files:
        size = path.stat().st_size
        if current and current_size + size > ZIP_TARGET:
            groups.append(current)
            current = []
            current_size = 0
        current.append(path)
        current_size += size
    if current:
        groups.append(current)

    packages = []
    for index, group in enumerate(groups, 1):
        zip_path = PACKAGE_DIR / f"OCT_migration_dev_{STAMP}_part{index:03d}.zip"
        with zipfile.ZipFile(
            zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            for path in group:
                rel = path.relative_to(BUNDLE_ROOT).as_posix()
                archive.write(path, arcname=f"{ROOT_NAME}/{rel}")
        size = zip_path.stat().st_size
        if size > ZIP_LIMIT:
            raise RuntimeError(f"zip exceeds 10 MB: {zip_path} ({size} bytes)")
        packages.append(
            {
                "name": zip_path.name,
                "bytes": size,
                "mb": round(size / 1024 / 1024, 3),
                "sha256": sha256_file(zip_path),
            }
        )
    return packages


def main() -> None:
    split_manifest = []
    collect_files(split_manifest)
    write_restore_files(split_manifest)
    packages = zip_bundle()
    manifest = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": str(SRC),
        "bundle_root": str(BUNDLE_ROOT),
        "package_dir": str(PACKAGE_DIR),
        "zip_root_folder": ROOT_NAME,
        "limit_bytes": ZIP_LIMIT,
        "split_threshold_bytes": SPLIT_THRESHOLD,
        "split_files": split_manifest,
        "included": {
            "runtime": ["python/", "packages/", "requirements.txt", "python.zip"],
            "development": ["main.py", "app/", "static/", "tools/", "_dev_root_files/"],
            "docs": ["Doc/", "MIGRATION_DEV_README.md"],
            "presets_workflows": [
                "workflows/",
                "data/comfyui_exports/",
                "data/runninghub_workflows.json",
                "data/prompt_templates.json",
                "data/asset_library.json",
                "data/canvases/",
                "assets/library/",
            ],
            "api_keys": ["API/.env", "API/.env.example", "data/api_providers.json"],
        },
        "excluded_clean_content": [
            "assets/input media",
            "assets/output media",
            "assets/preview media",
            "output media",
            "data/conversations content",
            "__pycache__",
            "*.pyc",
            "tmp logs",
        ],
        "packages": packages,
    }
    (PACKAGE_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "package_dir": str(PACKAGE_DIR),
                "bundle_root": str(BUNDLE_ROOT),
                "package_count": len(packages),
                "max_mb": max(item["mb"] for item in packages),
                "total_mb": round(sum(item["bytes"] for item in packages) / 1024 / 1024, 3),
                "split_file_count": len(split_manifest),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
