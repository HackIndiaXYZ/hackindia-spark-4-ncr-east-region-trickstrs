from flask import Flask, request, send_from_directory, jsonify, render_template, Response
import os
import time
import threading
import json
import socket
import re
import datetime


app = Flask(__name__)
last_seen = {}

UPLOAD = "uploads"
STATE_PATH = os.path.join(UPLOAD, "state.json")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_APP_JS_PATH = os.path.join(BASE_DIR, "static", "app.js")
UI_INDEX_PATH = os.path.join(BASE_DIR, "templates", "index.html")

os.makedirs(UPLOAD, exist_ok=True)

online_users = []
url_queue = {}  # legacy (kept for compatibility)

# file_state[item_id] = {"from": str|None, "type": "file"|"url", "created": float, "seen_by": [user,...], ...}
# - for type=="file": item_id is the filename in UPLOAD
# - for type=="url" : item_id is a generated id; the url is stored in meta["url"]
file_state = {}


def load_state():
    global file_state
    try:
        if os.path.exists(STATE_PATH):
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                file_state = data
    except Exception as e:
        print("State load error:", e)
        file_state = {}

    # --- migration / normalization (supports older versions) ---
    changed = False
    for item_id, meta in list(file_state.items()):
        if not isinstance(meta, dict):
            file_state.pop(item_id, None)
            changed = True
            continue

        # normalize seen_by
        seen_by = meta.get("seen_by")
        if not isinstance(seen_by, list):
            meta["seen_by"] = []
            changed = True

        item_type = meta.get("type")

        # older servers stored urls as files in UPLOAD and marked type=="url"
        if item_type == "url":
            url_val = meta.get("url")
            if not isinstance(url_val, str) or not url_val.strip():
                legacy_path = os.path.join(UPLOAD, item_id)
                if os.path.isfile(legacy_path):
                    try:
                        with open(legacy_path, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read().strip()
                        if content:
                            meta["url"] = content
                            changed = True
                            # optional cleanup: remove legacy url text file
                            try:
                                os.remove(legacy_path)
                            except Exception:
                                pass
                    except Exception:
                        pass

        # remove dangling "file" entries that no longer exist on disk
        if item_type == "file":
            if not os.path.isfile(os.path.join(UPLOAD, item_id)):
                file_state.pop(item_id, None)
                changed = True

    if changed:
        save_state()


def save_state():
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(file_state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("State save error:", e)


def unique_name(original: str, prefix: str) -> str:
    base = os.path.basename(original or "file")
    safe_base = base.replace("\\", "_").replace("/", "_")
    t = int(time.time() * 1000)
    return f"{prefix}_{t}_{safe_base}"


def mark_seen(user: str, name: str):
    if not user or not name:
        return
    meta = file_state.get(name)
    if not meta:
        meta = {"from": None, "type": "file", "created": time.time(), "seen_by": []}
        file_state[name] = meta
    seen = meta.get("seen_by") or []
    if user not in seen:
        seen.append(user)
        meta["seen_by"] = seen
        save_state()


def mark_all_seen_for_user(user: str):
    """
    When a user joins, they should start with an empty inbox:
    mark all existing items as seen for that user.
    """
    if not user:
        return
    changed = False
    for item_id, meta in file_state.items():
        if not isinstance(meta, dict):
            continue
        seen = meta.get("seen_by")
        if not isinstance(seen, list):
            seen = []
            meta["seen_by"] = seen
            changed = True
        if user not in seen:
            seen.append(user)
            changed = True
    if changed:
        save_state()


load_state()


def get_lan_ip() -> str:
    """
    Best-effort LAN IP detection (no external calls).
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # doesn't send packets; just picks a suitable local interface
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        return "127.0.0.1"


@app.route("/ping", methods=["GET"])
def ping():
    """
    Simple LAN health check for clients.
    """
    return jsonify({"status": "ok", "time": time.time()})


def pick_next_item_for_user(user: str):
    """
    Returns the next unseen item for a user (oldest first), or None.
    """
    if not user:
        return None
    candidates = []
    for item_id, meta in file_state.items():
        if not isinstance(meta, dict):
            continue
        seen = meta.get("seen_by") or []
        if user in seen:
            continue
        # skip invalid URL items
        if meta.get("type") == "url":
            url_val = meta.get("url")
            if not isinstance(url_val, str) or not url_val.strip():
                continue
        try:
            created = float(meta.get("created") or 0)
        except Exception:
            created = 0.0
        candidates.append((created, item_id, meta))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    _, item_id, meta = candidates[0]
    return item_id, meta


@app.route("/register", methods=["POST"])
def register():

    user = request.form.get("user") or request.json.get("name")

    if not user:
        return {"status": "error", "msg": "no user"}, 400

    # If this is a new session (first time seen since server started),
    # start them with no pending items.
    first_session = user not in last_seen

    if user not in online_users:
        online_users.append(user)

    last_seen[user] = time.time()  # ✅ IMPORTANT

    if first_session:
        mark_all_seen_for_user(user)

    print("Online users:", online_users)

    return {"status": "ok"}


# -------- upload --------

@app.route("/upload", methods=["POST"])
def upload():

    if "file" not in request.files:
        return "No file", 400

    f = request.files["file"]

    sender = request.form.get("from") or request.form.get("user") or None

    # avoid collisions; keep original name inside saved name
    name = unique_name(f.filename, "upload")
    path = os.path.join(UPLOAD, name)

    f.save(path)

    file_state[name] = {
        "from": sender,
        "type": "file",
        "created": time.time(),
        # sender should not receive their own upload
        "seen_by": [sender] if sender else []
    }
    save_state()

    print("Saved:", name, "from:", sender)

    return "OK"


# -------- list --------

@app.route("/files", methods=["GET"])
def files():

    user = request.args.get("user")

    # Legacy listing for older clients (gesture_123.py).
    # It expects /files to return downloadable items, including URL payloads.
    all_files = []
    for f, meta in file_state.items():
        if not isinstance(meta, dict):
            continue
        item_type = meta.get("type")
        if item_type not in ("file", "url"):
            continue
        if os.path.isfile(os.path.join(UPLOAD, f)):
            all_files.append(f)

    # if user is provided, only return items not yet seen by that user
    if user:
        visible = []
        for name in all_files:
            meta = file_state.get(name)
            if not meta:
                # treat unknown file as visible
                visible.append(name)
                continue
            seen = meta.get("seen_by") or []
            if user not in seen:
                visible.append(name)
        return jsonify({"files": visible})

    return jsonify({"files": all_files})


# -------- download --------

@app.route("/download/<name>", methods=["GET"])
def download(name):

    path = os.path.join(UPLOAD, name)

    if not os.path.exists(path):
        return "Not found", 404

    # If user is provided, mark as seen when they download it.
    user = request.args.get("user")
    if user:
        mark_seen(user, name)

    return send_from_directory(UPLOAD, name)


# -------- delete --------

@app.route("/delete/<name>", methods=["POST"])
def delete(name):

    # Two modes:
    # - If request includes user, mark file as seen for that user (do not delete globally).
    # - Else, delete file globally (admin/sender cleanup).
    user = (
        request.args.get("user")
        or request.form.get("user")
        or (request.json.get("user") if request.is_json else None)
        or request.form.get("from")
    )

    if user:
        mark_seen(user, name)
        return jsonify({"status": "ok", "mode": "seen", "user": user})

    path = os.path.join(UPLOAD, name)
    if os.path.exists(path):
        os.remove(path)
        file_state.pop(name, None)
        save_state()
        print("Deleted:", name)
    return jsonify({"status": "ok", "mode": "deleted"})

@app.route("/send_url", methods=["POST"])
def send_url():

    cleanup_users()

    data = request.json

    sender = data["from"]
    url = data["url"]

    print(f"{sender} sent URL:", url)

    # Store URL as an in-state item AND as a file in uploads/ (legacy clients depend on /files).
    item_id = unique_name("url.txt", f"url_{sender}")
    path = os.path.join(UPLOAD, item_id)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(url)
    except Exception as e:
        print("URL file save error:", e)
    file_state[item_id] = {
        "from": sender,
        "type": "url",
        "url": url,
        "created": time.time(),
        "seen_by": [sender]  # sender should not receive their own URL
    }
    save_state()

    # Keep legacy queue too (optional), for existing clients that poll /get_url/<user>
    for user in online_users:
        if user == sender:
            continue
        if user not in url_queue:
            url_queue[user] = []
        already_exists = any(item.get("url") == url for item in url_queue[user])
        if not already_exists:
            url_queue[user].append({"from": sender, "url": url})

    return {"status": "ok", "id": item_id}


@app.route("/next", methods=["GET"])
def next_item():
    """
    Get the next unseen item for a user (URL or file).
    This is the recommended receive API for LAN clients.
    """
    user = request.args.get("user")
    if not user:
        return jsonify({"status": "error", "msg": "missing user"}), 400

    item = pick_next_item_for_user(user)
    if not item:
        return jsonify({"status": "ok", "type": "none"})

    item_id, meta = item
    item_type = meta.get("type")

    if item_type == "url":
        # mark seen immediately when delivered
        mark_seen(user, item_id)
        return jsonify({
            "status": "ok",
            "type": "url",
            "from": meta.get("from"),
            "url": (meta.get("url") or "")
        })

    if item_type == "file":
        # client will download; server will mark seen on /download?user=
        return jsonify({
            "status": "ok",
            "type": "file",
            "from": meta.get("from"),
            "name": item_id
        })

    return jsonify({"status": "ok", "type": "none"})

@app.route("/get_url/<user>")
def get_url(user):

    if user in url_queue and url_queue[user]:
        data = url_queue[user].pop(0)

        print(f"Delivered to {user}:", data)

        return jsonify(data)  # ✅ FIX

    return jsonify({})


@app.route("/heartbeat", methods=["POST"])
def heartbeat():

    user = request.form.get("user") or request.json.get("name")

    if not user:
        return {"status": "error"}, 400

    last_seen[user] = time.time()

    if user not in online_users:
        online_users.append(user)

    return {"status": "ok"}


def cleanup_loop():

    while True:
        cleanup_users()
        time.sleep(3)


def cleanup_users():

    now = time.time()

    for user in list(last_seen.keys()):

        if now - last_seen[user] > 5:  # 5 sec timeout

            print("Removing offline user:", user)

            last_seen.pop(user)

            if user in online_users:
                online_users.remove(user)

            if user in url_queue:
                url_queue.pop(user)


def format_bytes(num_bytes: int) -> str:
    try:
        n = int(num_bytes)
    except Exception:
        return "0 B"
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{(n / 1024):.1f} KB"
    return f"{(n / (1024 * 1024)):.1f} MB"


def human_date_short(ts: float) -> str:
    try:
        dt = datetime.datetime.fromtimestamp(float(ts))
        return dt.strftime("%d %b")
    except Exception:
        return ""


def parse_url_path(url: str) -> str:
    if not isinstance(url, str):
        return ""
    base = url.split("?", 1)[0].split("#", 1)[0]
    parts = base.rstrip("/").split("/")
    return parts[-1] if parts else base


def infer_type_from_name(name_or_url: str) -> tuple[str, str]:
    """
    Returns (type, emoji) matching the frontend's display.
    """
    if not isinstance(name_or_url, str):
        return "other", "📦"

    leaf = parse_url_path(name_or_url)
    _, ext = os.path.splitext(leaf)
    ext = (ext or "").lower().lstrip(".")

    image_exts = {"jpg", "jpeg", "png", "gif", "webp", "svg", "bmp", "tif", "tiff"}
    video_exts = {"mp4", "avi", "mov", "mkv", "webm"}
    audio_exts = {"mp3", "wav", "aac", "ogg", "flac"}
    doc_exts = {"pdf", "doc", "docx", "txt", "md", "ppt", "pptx", "xls", "xlsx"}

    if ext in image_exts:
        return "image", "🖼️"
    if ext in video_exts:
        return "video", "🎬"
    if ext in audio_exts:
        return "audio", "🎵"
    if ext in doc_exts:
        return "doc", "📄"

    # Heuristic fallback
    low = (name_or_url or "").lower()
    if "pdf" in low:
        return "doc", "📄"

    return "other", "📦"


def extract_display_name(item_id: str, meta: dict) -> str:
    if not isinstance(meta, dict):
        return str(item_id)
    if meta.get("type") == "url":
        return meta.get("url") or str(item_id)
    if isinstance(item_id, str) and item_id.startswith("upload_"):
        # upload_<t>_<original>
        return re.sub(r"^upload_\d+_", "", item_id)
    return str(item_id)


def build_ui_sample_data():
    """
    Build SAMPLE_SESSIONS and SAMPLE_FILES for the existing frontend.
    Note: the frontend currently uses these constants as initial state only.
    """
    received_files = []
    sessions_by_sender = {}

    for item_id, meta in (file_state or {}).items():
        if not isinstance(meta, dict):
            continue
        item_type = meta.get("type")
        sender = meta.get("from") or "unknown"
        created = meta.get("created") or time.time()
        seen_by = meta.get("seen_by") or []
        if not isinstance(seen_by, list):
            seen_by = []

        display_name = extract_display_name(item_id, meta)
        f_type, f_emoji = infer_type_from_name(display_name)

        # Size string
        size_str = "URL"
        if item_type == "file":
            path = os.path.join(UPLOAD, item_id)
            try:
                size_str = format_bytes(os.path.getsize(path))
            except Exception:
                size_str = "0 B"

        # Consider as "received" if some user other than sender has seen it.
        others_seen = [u for u in seen_by if u and u != sender]
        if len(others_seen) > 0:
            received_files.append({
                "name": display_name,
                "type": f_type,
                "size": size_str,
                "from": sender,
                "date": human_date_short(created),
                "emoji": f_emoji,
            })

        if sender not in sessions_by_sender:
            try:
                iso_date = datetime.datetime.fromtimestamp(float(created)).isoformat()
            except Exception:
                iso_date = datetime.datetime.utcnow().isoformat()

            sessions_by_sender[sender] = {
                "id": f"sess_{sender}",
                "roomName": f"room_{sender}",
                "role": "host",
                "server": "lan",
                "date": iso_date,
                "duration": "—",
                "filesReceived": 0,
                "filesSent": 0,
                "files": []
            }

        s = sessions_by_sender[sender]
        if item_type in ("file", "url"):
            s["filesSent"] += 1
            s["filesReceived"] += len(others_seen)
            s["files"].append({
                "name": display_name,
                "type": f_type,
                "size": size_str,
                "from": sender
            })

    sessions = list(sessions_by_sender.values())

    # Sort by session date
    def _ts(x):
        try:
            return datetime.datetime.fromisoformat(x.get("date") or "").timestamp()
        except Exception:
            return 0
    sessions.sort(key=_ts, reverse=True)

    # Keep bounded
    return sessions[:20], received_files[:50]


@app.route("/")
def ui_index():
    if os.path.exists(UI_INDEX_PATH):
        return render_template("index.html")
    return "index.html not found.", 404


@app.route("/static/app.js")
def ui_app_js():
    """
    Inject live server state into the frontend's SAMPLE_SESSIONS and SAMPLE_FILES.
    """
    if not os.path.exists(STATIC_APP_JS_PATH):
        return Response("// app.js not found", mimetype="application/javascript")

    try:
        with open(STATIC_APP_JS_PATH, "r", encoding="utf-8") as f:
            js = f.read()
    except Exception:
        return Response("// failed to read app.js", mimetype="application/javascript")

    sessions, received_files = build_ui_sample_data()

    sample_sessions_js = json.dumps(sessions, ensure_ascii=False)
    sample_files_js = json.dumps(received_files, ensure_ascii=False)

    js = re.sub(
        r"const SAMPLE_SESSIONS\\s*=\\s*\\[[\\s\\S]*?\\];",
        f"const SAMPLE_SESSIONS = {sample_sessions_js};",
        js,
        count=1,
    )
    js = re.sub(
        r"const SAMPLE_FILES\\s*=\\s*\\[[\\s\\S]*?\\];",
        f"const SAMPLE_FILES = {sample_files_js};",
        js,
        count=1,
    )

    return Response(js, mimetype="application/javascript")


if __name__ == "__main__":
    threading.Thread(target=cleanup_loop, daemon=True).start()
    ip = get_lan_ip()
    print(f"LAN server running at: http://{ip}:5000")
    app.run(host="0.0.0.0", port=5000)