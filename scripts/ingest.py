"""Pull the morning card drop from Google Drive into posts/<date>/.

The cloud morning job cannot reach the GitHub API from its sandbox, so it
uploads the day folder to Drive instead:

    uploads/<YYYY-MM-DD>/            (inside "NYC Cardnews Assets"/uploads)
      manifest.json
      free/01.png ...   food/...   art/...

This script (run by ingest.yml with GOOGLE_SERVICE_ACCOUNT_JSON) finds
today's ET folder, downloads everything, converts images to JPEG (<8MB),
rewrites the manifest image lists, and writes posts/<date>/ for the
workflow to commit. The Drive folder must be shared (viewer) with the
service account's client_email.

Cron fires around 7:15/7:40 ET (both DST offsets); the script only proceeds
inside the 7:00-7:48 ET window unless manually dispatched. It exits quietly
if the repo already has today's manifest (re-run via dispatch with
FORCE_INGEST=1 to overwrite).
"""
import io
import json
import os
import sys

import requests
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, SLOTS, now_et, today_et, write_json  # noqa: E402

UPLOADS_FOLDER_ID = os.environ.get("DRIVE_UPLOADS_FOLDER_ID",
                                   "1sk0hwtIvXW7o8vK30noIgwjA1btSx0ql")
DRIVE = "https://www.googleapis.com/drive/v3"
MAX_BYTES = 8 * 1024 * 1024


def drive_token():
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON secret is not set")
    info = json.loads(raw)
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive.readonly"])
    creds.refresh(Request())
    return creds.token


def gd(session, params):
    r = session.get(f"{DRIVE}/files", params=params, timeout=60)
    r.raise_for_status()
    return r.json().get("files", [])


def gd_children(session, folder_id):
    return gd(session, {
        "q": f"'{folder_id}' in parents and trashed=false",
        "fields": "files(id,name,mimeType)",
        "pageSize": 100,
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
    })


def gd_download(session, file_id):
    r = session.get(f"{DRIVE}/files/{file_id}",
                    params={"alt": "media", "supportsAllDrives": "true"}, timeout=300)
    r.raise_for_status()
    return r.content


def to_jpeg(data, name):
    im = Image.open(io.BytesIO(data))
    if im.mode != "RGB":
        im = im.convert("RGB")
    for quality in (88, 80, 70, 60, 50, 40):
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality, optimize=True)
        if buf.tell() <= MAX_BYTES:
            return buf.getvalue()
    raise RuntimeError(f"{name}: cannot get under 8MB even at quality 40")


def in_window():
    n = now_et()
    return n.hour == 7 and n.minute <= 48


def main():
    manual = os.environ.get("GITHUB_EVENT_NAME", "") == "workflow_dispatch"
    force = os.environ.get("FORCE_INGEST", "") == "1"
    if not manual and not in_window():
        print(f"outside ET ingest window (ET now {now_et():%H:%M}); exiting")
        return
    date = today_et()
    if (ROOT / "posts" / date / "manifest.json").exists() and not force:
        print(f"posts/{date}/manifest.json already exists; nothing to ingest "
              "(dispatch with force=true to overwrite)")
        return

    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {drive_token()}"

    day_folders = gd(s, {
        "q": f"'{UPLOADS_FOLDER_ID}' in parents and name='{date}' "
             "and mimeType='application/vnd.google-apps.folder' and trashed=false",
        "fields": "files(id,name)",
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
    })
    if not day_folders:
        print(f"no Drive upload folder named {date}; nothing to ingest")
        return
    day_id = day_folders[0]["id"]

    entries = gd_children(s, day_id)
    manifest_file = next((f for f in entries if f["name"] == "manifest.json"), None)
    if not manifest_file:
        raise RuntimeError(f"Drive folder {date} has no manifest.json")
    manifest = json.loads(gd_download(s, manifest_file["id"]).decode("utf-8"))
    if manifest.get("date") != date:
        print(f"warning: manifest date {manifest.get('date')!r} != folder {date}; using folder date")
        manifest["date"] = date

    slot_folders = {f["name"]: f["id"] for f in entries
                    if f["mimeType"] == "application/vnd.google-apps.folder"}
    n_files = 0
    for slot in SLOTS:
        info = manifest.get("slots", {}).get(slot)
        if not info:
            print(f"warning: manifest has no slot {slot!r}; skipping")
            continue
        if slot not in slot_folders:
            raise RuntimeError(f"Drive folder {date} has no {slot}/ subfolder")
        files = {f["name"]: f for f in gd_children(s, slot_folders[slot])}
        listed = info.get("images") or sorted(files)
        new_names = []
        out_dir = ROOT / "posts" / date / slot
        out_dir.mkdir(parents=True, exist_ok=True)
        for i, name in enumerate(listed, 1):
            if name not in files:
                raise RuntimeError(f"{slot}/{name} listed in manifest but missing in Drive")
            jpg = to_jpeg(gd_download(s, files[name]["id"]), name)
            out_name = f"{i:02d}.jpg"
            (out_dir / out_name).write_bytes(jpg)
            new_names.append(out_name)
            n_files += 1
        info["images"] = new_names

    write_json(ROOT / "posts" / date / "manifest.json", manifest)
    n_files += 1
    print(f"ingested {n_files} files for {date} from Drive")


if __name__ == "__main__":
    main()
