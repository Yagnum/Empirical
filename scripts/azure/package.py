"""Build the two zip files Azure App Service deploys (docs/AZURE-DEPLOY.md).

    python scripts/azure/package.py api   -> build/api.zip
    python scripts/azure/package.py web   -> build/web.zip   (run `npm run build` first)

api.zip is the FastAPI source plus requirements.txt; App Service's build
step (Oryx) installs the requirements on the server. web.zip is the
prebuilt Next.js standalone server: server.js, the trimmed node_modules,
the static assets and the public folder - nothing is built on the server,
because the Free tier's 1 GB cannot run a Next.js build.

Pure standard library so it runs the same on Windows, GitHub Actions and
macOS; no `zip` binary needed.
"""

import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build"

API_SKIP_DIRS = {".venv", "__pycache__", "tests", ".pytest_cache", ".ruff_cache", "scripts"}
API_SKIP_FILES = {"uv.lock", ".python-version"}


def _add_tree(zf: zipfile.ZipFile, base: Path, arc_root: str = "", skip_dirs=frozenset(), skip_files=frozenset()) -> int:
    count = 0
    for path in sorted(base.rglob("*")):
        rel = path.relative_to(base)
        if any(part in skip_dirs for part in rel.parts):
            continue
        if path.is_dir() or path.name in skip_files:
            continue
        arc = (Path(arc_root) / rel).as_posix() if arc_root else rel.as_posix()
        zf.write(path, arc)
        count += 1
    return count


def package_api() -> Path:
    src = ROOT / "app" / "api"
    out = BUILD / "api.zip"
    BUILD.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        n = _add_tree(zf, src, skip_dirs=API_SKIP_DIRS, skip_files=API_SKIP_FILES)
    print(f"{out}: {n} files")
    return out


def package_web() -> Path:
    web = ROOT / "app" / "web"
    standalone = web / ".next" / "standalone"
    if not (standalone / "server.js").exists():
        sys.exit("no .next/standalone/server.js - run `npm run build` in app/web first")
    # Next's standalone output leaves the static assets and public folder
    # beside it, expecting the deployer to copy them in. Do that into a
    # staging copy so the build tree itself stays untouched.
    stage = BUILD / "web"
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(standalone, stage)
    shutil.copytree(web / ".next" / "static", stage / ".next" / "static", dirs_exist_ok=True)
    if (web / "public").exists():
        shutil.copytree(web / "public", stage / "public", dirs_exist_ok=True)
    out = BUILD / "web.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        n = _add_tree(zf, stage)
    print(f"{out}: {n} files")
    return out


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else ""
    if which == "api":
        package_api()
    elif which == "web":
        package_web()
    else:
        sys.exit("usage: package.py api|web")
