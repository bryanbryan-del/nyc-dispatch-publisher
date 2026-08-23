"""Commit a day's cards + manifest into this repo via the GitHub API.

This script runs OUTSIDE the repo — the morning card job downloads just this
one file — so it is deliberately self-contained (no common.py import).

Auth:  env GH_TOKEN  — fine-grained PAT, Contents: Read/write on the target
                       repo only. Never printed, never written to disk.
Repo:  env GH_REPO   — e.g. bryanbryan-del/nyc-dispatch-publisher

Input directory (--dir) layout:
    <dir>/manifest.json          {"date": "YYYY-MM-DD", "slots": {"free": {...}}}
    <dir>/free/*.png|*.jpg       (order = manifest images list, else name order)
    <dir>/food/..., <dir>/art/...

Every image is converted to JPEG (RGB, 4:5 is the job's responsibility),
re-encoded under 8MB, renamed 01.jpg, 02.jpg, ... per slot; the manifest's
images lists are rewritten to match. Everything lands in one commit under
posts/<date>/ on main.  Prints:  committed <n> files for <date> -> <sha>
"""
import argparse
import base64
import io
import json
import os
import sys
from pathlib import Path

import requests
from PIL import Image

API = "https://api.github.com"
MAX_BYTES = 8 * 1024 * 1024


def die(msg):
    print(f"ERROR: {msg}")
    sys.exit(1)


def gh(session, method, path, **kw):
    r = session.request(method, f"{API}{path}", timeout=120, **kw)
    if r.status_code >= 300:
        # response bodies from the API never echo the token
        die(f"github {method} {path} -> HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def to_jpeg(path):
    im = Image.open(path)
    if im.mode != "RGB":
        im = im.convert("RGB")
    for quality in (88, 80, 70, 60, 50, 40):
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality, optimize=True)
        if buf.tell() <= MAX_BYTES:
            return buf.getvalue()
    die(f"{path.name}: cannot get under 8MB even at quality 40")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="day folder containing manifest.json + slot dirs")
    ap.add_argument("--branch", default="main")
    args = ap.parse_args()

    token = os.environ.get("GH_TOKEN", "").strip()
    repo = os.environ.get("GH_REPO", "").strip()
    if not token:
        die("env GH_TOKEN is not set")
    if not repo or "/" not in repo:
        die("env GH_REPO is not set (expected owner/repo)")

    day_dir = Path(args.dir)
    manifest_file = day_dir / "manifest.json"
    if not manifest_file.exists():
        die(f"{manifest_file} not found")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    date = manifest.get("date", "").strip()
    if not date:
        die("manifest.json has no 'date'")

    # -- convert images, rewrite manifest image lists --------------------
    files = {}  # repo path -> bytes
    for slot, info in manifest.get("slots", {}).items():
        slot_dir = day_dir / slot
        if not slot_dir.is_dir():
            die(f"slot folder missing: {slot_dir}")
        listed = info.get("images") or []
        sources = [slot_dir / n for n in listed] if listed else sorted(
            p for p in slot_dir.iterdir()
            if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
        )
        if not sources:
            die(f"no images in {slot_dir}")
        new_names = []
        for i, src in enumerate(sources, 1):
            if not src.exists():
                die(f"listed image missing: {src}")
            name = f"{i:02d}.jpg"
            files[f"posts/{date}/{slot}/{name}"] = to_jpeg(src)
            new_names.append(name)
        info["images"] = new_names

    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    files[f"posts/{date}/manifest.json"] = manifest_bytes

    # -- one commit via the git data API ---------------------------------
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    ref = gh(s, "GET", f"/repos/{repo}/git/ref/heads/{args.branch}")
    base_commit = ref["object"]["sha"]
    base_tree = gh(s, "GET", f"/repos/{repo}/git/commits/{base_commit}")["tree"]["sha"]

    tree = []
    for path, data in sorted(files.items()):
        blob = gh(s, "POST", f"/repos/{repo}/git/blobs",
                  json={"content": base64.b64encode(data).decode(), "encoding": "base64"})
        tree.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
    new_tree = gh(s, "POST", f"/repos/{repo}/git/trees",
                  json={"base_tree": base_tree, "tree": tree})
    commit = gh(s, "POST", f"/repos/{repo}/git/commits",
                json={"message": f"cards {date}", "tree": new_tree["sha"],
                      "parents": [base_commit]})
    gh(s, "PATCH", f"/repos/{repo}/git/refs/heads/{args.branch}",
       json={"sha": commit["sha"]})

    print(f"committed {len(files)} files for {date} -> {commit['sha'][:7]}")


if __name__ == "__main__":
    main()
