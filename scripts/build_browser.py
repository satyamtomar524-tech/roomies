"""Build the public, device-local app without shipping anybody's database.

Usage: python scripts/build_browser.py [--output dist] [--runtime-cache DIR]
Only the allowlisted UI and Python source enter the output. Pyodide is pinned,
verified against the published npm SHA-512, and served from the same origin.
"""

import argparse
import base64
import hashlib
import io
from pathlib import Path
import shutil
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent
VERSION = "314.0.7"
RUNTIME_URL = f"https://registry.npmjs.org/pyodide/-/pyodide-{VERSION}.tgz"
INTEGRITY = "0YvXxEhfEdpLfb/XkM2BFAeMROq0iMUX2bzzH9pOttyMcWkwq+HbE5uyuGD82LN7y2q+SNvi/6V5JEsOlD2R1A=="
RUNTIME_FILES = ("pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "pyodide-lock.json", "python_stdlib.zip", "pyodide.mjs.map")
PYTHON_FILES = ("__init__.py", "browser.py", "expenses.py", "geometry.py", "household.py", "pricing.py", "storage.py")
WEB_FILES = ("index.html", "guide.html", "guide.css", "style.css", "app.js", "flat.js", "costs.js", "browser.js", "browser-worker.mjs", "browser.css")


def download_runtime(cache):
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / f"pyodide-{VERSION}.tgz"
    raw = archive.read_bytes() if archive.exists() else urllib.request.urlopen(RUNTIME_URL, timeout=60).read()
    if base64.b64encode(hashlib.sha512(raw).digest()).decode() != INTEGRITY:
        raise ValueError("Pyodide package integrity check failed. Remove the cached archive and retry.")
    if not archive.exists():
        archive.write_bytes(raw)
    return raw


def build(output, cache):
    output = output.resolve()
    if output == ROOT or output in ROOT.parents or output == ROOT / "web":
        raise ValueError("Build into a dedicated output directory.")
    output.mkdir(parents=True, exist_ok=True)
    for name in WEB_FILES:
        shutil.copyfile(ROOT / "web" / name, output / name)
    runtime = output / "vendor" / "pyodide"
    runtime.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(download_runtime(cache)), mode="r:gz") as package:
        for name in RUNTIME_FILES:
            member = package.extractfile(f"package/{name}")
            (runtime / name).write_bytes(member.read())
    for name in ("PYODIDE-LICENSE", "PYTHON-LICENSE"):
        shutil.copyfile(ROOT / "docs" / "licenses" / name, runtime / name)
    (runtime / "NOTICE.txt").write_text(
        f"Pyodide {VERSION} (unmodified), MPL-2.0. Source: https://github.com/pyodide/pyodide/tree/{VERSION}\n"
        "Python 3.14.2, PSF license. Source and third-party notices: https://github.com/python/cpython/tree/v3.14.2\n"
        "SQLite is in the public domain. https://sqlite.org/copyright.html\n", encoding="utf-8")
    with zipfile.ZipFile(output / "roomies-python.zip", "w", zipfile.ZIP_DEFLATED) as bundle:
        for name in PYTHON_FILES:
            entry = zipfile.ZipInfo(f"roommate/{name}", (2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(entry, (ROOT / "roommate" / name).read_bytes())
    favicon = '<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 viewBox=%270 0 64 64%27%3E%3Crect width=%2764%27 height=%2764%27 rx=%2717%27 fill=%27%23607e6c%27/%3E%3Ctext x=%2717%27 y=%2746%27 fill=%27white%27 font-family=%27Arial%27 font-weight=%27700%27 font-size=%2740%27%3ER%3C/text%3E%3C/svg%3E" />'
    for name in ("index.html", "guide.html"):
        path = output / name
        html = path.read_text(encoding="utf-8")
        for asset in WEB_FILES:
            html = html.replace(f'"/{asset}"', f'"./{asset}"')
        html = html.replace('href="/guide"', 'href="./guide.html"').replace('href="/"', 'href="./"')
        html = html.replace("</head>", favicon + "\n</head>")
        if name == "index.html":
            html = html.replace('<script src="./flat.js"', '<link rel="stylesheet" href="./browser.css" />\n<script src="./browser.js" defer></script>\n<script src="./flat.js"')
            html = html.replace("Saved on this computer", "Saved in this browser")
            html = html.replace("Roomies · Local workspace", "Roomies · Your own workspace")
            note = '''<aside class="browser-note"><div><strong>Make yourself at home.</strong>
<p>Try the sample, then make it yours. Your changes stay in this browser. Use Export to keep a backup. Sharing the link gives your friends their own space.</p>
<p id="browser-loading" role="status">Opening your workspace…</p></div>
<button id="share-roomies" class="primary-button" type="button">Share Roomies ↗</button></aside>'''
            html = html.replace('<div id="home-overview"', note + '\n<div id="home-overview"')
            html = html.replace("Manual entries work for any store. Automatic checks work only\n                  for supported public product pages.", "Keep the price, delivery cost and date together, so you know what you checked.")
            html = html.replace("A check failure keeps your previous observation. It does not\n                  create a new price.", "Prices are your own dated records. Check the shop again before buying.")
            html = html.replace("backup. Review the import preview before replacing data.", "backup. Clearing browser data removes your records. Review the import preview before replacing data.")
            html = html.replace("</head>", '<meta name="description" content="Plan your student room, find your things, keep a kitchen checklist and split the bills. Try Roomies in your browser." />\n</head>')
        else:
            html = html.replace("Automatic checks work only\n            for compatible public pages; unsupported stores can be recorded\n            manually.", "Open a shop link and record what you see. The browser version does not check retailer pages automatically.")
            html = html.replace("A confirmed saved SKU and matching product link are needed for live\n            variant confidence. Checks run while the local server is open. The\n            sample room cannot produce buying alerts.", "The sample room cannot produce buying alerts. Use your own measurements and confirm the exact product before treating a price as a match.")
            html = html.replace("Member names are labels in one local workspace, not accounts or\n          invitations.", "Your records stay in this browser on this device. Clear site data and they are removed. Sharing the link does not share your flat's records. Member names are labels, not sign-in accounts.")
            html = html.replace("The browser sends JSON to <code>roommate/server.py</code>.", "Pyodide runs the same Python rules in a browser worker. <code>browser.py</code> receives the actions; IndexedDB saves the database on this device.")
        path.write_text(html, encoding="utf-8")
    print(f"Browser app built at {output}; runtime {VERSION}; no user data included.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--runtime-cache", type=Path, default=ROOT / "build" / "runtime-cache")
    args = parser.parse_args()
    build(args.output, args.runtime_cache)
