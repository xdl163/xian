import base64
import hashlib
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml
from flask import Flask, Response, jsonify, render_template, request

import settings
from Utils import load_config
from detect_xian import VideoProcessorThread


app = Flask(__name__)
_state_lock = threading.Lock()


def _video_by_id(video_id: int):
    for video in settings.video_list:
        if int(video.id) == int(video_id):
            return video
    return None


def _read_yaml(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _check_password(raw_password: str) -> bool:
    return hashlib.sha256(str(raw_password).encode("utf-8")).hexdigest() == settings.passwd


def _annotation_from_yaml(video):
    data = _read_yaml(video.yaml_path)
    width = max(1, int(video.frame_width))
    height = max(1, int(video.frame_height))

    anns = []
    for idx, coord in (data.get("yarn", {}) or {}).items():
        try:
            x, y = coord
            if x <= 1 and y <= 1:
                x, y = int(x * width), int(y * height)
            anns.append({"type": "yarn", "id": str(idx), "coords": [int(x), int(y)]})
        except Exception:
            continue

    for coord in (data.get("laser_emitter", []) or []):
        try:
            x, y = coord
            if x <= 1 and y <= 1:
                x, y = int(x * width), int(y * height)
            anns.append({"type": "laser_emitter", "id": "1", "coords": [int(x), int(y)]})
        except Exception:
            continue

    for coord in (data.get("laser_wall", []) or []):
        try:
            x, y = coord
            if x <= 1 and y <= 1:
                x, y = int(x * width), int(y * height)
            anns.append({"type": "laser_wall", "id": "1", "coords": [int(x), int(y)]})
        except Exception:
            continue

    hsv_range = data.get("hsv_range", getattr(video, "hsv_range", {
        "h_min": 0,
        "h_max": 179,
        "s_min": 0,
        "s_max": 255,
        "v_min": 178,
        "v_max": 255,
    }))

    return {
        "meta": {
            "video_id": data.get("video_id", ""),
            "add_type": data.get("add_type", ""),
            "id": data.get("id", ""),
            "video_type": data.get("video_type", ""),
            "video_url": data.get("video_url", ""),
            "hsv_range": hsv_range,
        },
        "annotations": anns,
    }


def _save_annotation(video, payload: dict[str, Any]) -> None:
    width = max(1, int(video.frame_width))
    height = max(1, int(video.frame_height))
    data_to_save = _read_yaml(video.yaml_path)

    hsv_range = payload.get("meta", {}).get("hsv_range", getattr(video, "hsv_range", {}))
    video.hsv_range = hsv_range.copy()

    yarn_data = {}
    laser_emitter_data = []
    laser_wall_data = []
    video.xian_points = {}
    video.laser_emitter = []
    video.laser_wall = []

    for item in payload.get("annotations", []):
        x, y = item.get("coords", [0, 0])
        x = max(0, min(int(x), width - 1))
        y = max(0, min(int(y), height - 1))
        x1 = max(x - settings.crap_w, 0)
        y1 = max(y - settings.crap_h, 0)
        x2 = min(x + settings.crap_w, width - 1)
        y2 = min(y + settings.crap_h, height - 1)

        if item.get("type") == "yarn":
            ann_id = str(item.get("id", ""))
            if not ann_id:
                continue
            video.xian_points[ann_id] = (x, y, x1, y1, x2, y2)
            yarn_data[ann_id] = [x / width, y / height]
        elif item.get("type") == "laser_emitter":
            video.laser_emitter.append([x, y, x1, y1, x2, y2])
            laser_emitter_data.append([x / width, y / height])
        elif item.get("type") == "laser_wall":
            video.laser_wall.append([x, y, x1, y1, x2, y2])
            laser_wall_data.append([x / width, y / height])

    meta = payload.get("meta", {})
    video.video_id = str(meta.get("video_id", ""))
    video.add_type = str(meta.get("add_type", ""))
    video.id = str(meta.get("id", video.id))
    video.video_type = str(meta.get("video_type", ""))
    video.video_url = str(meta.get("video_url", ""))

    try:
        video.hsv_lower = np.array([video.hsv_range["h_min"], video.hsv_range["s_min"], video.hsv_range["v_min"]], dtype=np.uint8)
        video.hsv_upper = np.array([video.hsv_range["h_max"], video.hsv_range["s_max"], video.hsv_range["v_max"]], dtype=np.uint8)
    except Exception:
        pass

    data_to_save["id"] = video.id
    data_to_save["yarn"] = yarn_data
    data_to_save["laser_emitter"] = laser_emitter_data
    data_to_save["laser_wall"] = laser_wall_data
    data_to_save["video_id"] = video.video_id
    data_to_save["add_type"] = video.add_type
    data_to_save["video_type"] = meta.get("video_type", "")
    data_to_save["video_url"] = meta.get("video_url", "")
    data_to_save["hsv_range"] = hsv_range

    with open(video.yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data_to_save, f, allow_unicode=True)


def _recognition_payload(video):
    points = getattr(video, "xian_points", {}) or {}
    lights = getattr(video, "xian_light", None)
    results = []

    for i, (label, (_, _, x1, y1, x2, y2)) in enumerate(points.items()):
        is_light = True
        if lights is not None and len(lights) > i:
            is_light = bool(lights[i])
        results.append({
            "id": str(label),
            "x1": int(x1),
            "y1": int(y1),
            "x2": int(x2),
            "y2": int(y2),
            "is_light": is_light,
        })

    return {
        "points": results,
        "have_abnormal": bool(getattr(video, "have_abnormal", False)),
        "frame_width": int(getattr(video, "frame_width", 0) or 0),
        "frame_height": int(getattr(video, "frame_height", 0) or 0),
        "ts": time.time(),
    }


def _apply_runtime_from_config(config: dict[str, Any]) -> None:
    settings.save = bool(config.get("save", settings.save))
    settings.save_csv = bool(config.get("save_csv", settings.save_csv))
    settings.save_img = bool(config.get("save_img", settings.save_img))
    settings.db_save_day = int(config.get("db_save_day", settings.db_save_day))
    settings.ERROR_WIN = int(config.get("error_win", settings.ERROR_WIN))
    settings.CORRECT_WIN = int(config.get("correct_win", settings.CORRECT_WIN))
    settings.BUF_SIZE = int(config.get("BUF_SIZE", settings.BUF_SIZE))
    settings.HISTORY_LEN = int(config.get("HISTORY_LEN", settings.HISTORY_LEN))

    for video in settings.video_list:
        old_hist = list(getattr(video, "history_queue", []))
        video.history_queue = deque(old_hist[-settings.HISTORY_LEN:], maxlen=settings.HISTORY_LEN)
        if hasattr(video, "_buf_lock") and hasattr(video, "_frame_buffer"):
            with video._buf_lock:
                old_buf = list(video._frame_buffer)
                video._frame_buffer = deque(old_buf[-settings.BUF_SIZE:], maxlen=settings.BUF_SIZE)


def _restart_all() -> None:
    if settings.video_thread is not None:
        settings.video_thread.stop()
        settings.video_thread.join(timeout=2)
        settings.video_thread = None

    for video in settings.video_list:
        try:
            video.stop()
        except Exception:
            pass

    if getattr(settings, "modbusServer", None) is not None:
        try:
            settings.modbusServer.stop()
        except Exception:
            pass

    settings.video_list = []
    load_config(settings.config_path)
    settings.video_thread = VideoProcessorThread(settings.video_list, window=None)
    settings.video_thread.start()


@app.get("/")
def index():
    return render_template("index.html", videos=settings.video_list)


@app.get("/api/videos")
def list_videos():
    rows = []
    for video in settings.video_list:
        rows.append({
            "id": int(video.id),
            "video_id": str(getattr(video, "video_id", "") or ""),
            "add_type": str(getattr(video, "add_type", "") or ""),
        })
    return jsonify({"videos": rows})


@app.get("/api/settings")
def get_settings():
    cfg = _read_yaml(settings.config_path)
    return jsonify({
        "save": bool(cfg.get("save", settings.save)),
        "save_csv": bool(cfg.get("save_csv", settings.save_csv)),
        "save_img": bool(cfg.get("save_img", settings.save_img)),
        "db_save_day": int(cfg.get("db_save_day", settings.db_save_day)),
        "error_win": int(cfg.get("error_win", settings.ERROR_WIN)),
        "correct_win": int(cfg.get("correct_win", settings.CORRECT_WIN)),
        "BUF_SIZE": int(cfg.get("BUF_SIZE", settings.BUF_SIZE)),
        "HISTORY_LEN": int(cfg.get("HISTORY_LEN", settings.HISTORY_LEN)),
    })


@app.post("/api/settings")
def save_settings():
    payload = request.get_json(force=True, silent=True) or {}
    cfg = _read_yaml(settings.config_path)
    for k in ["save", "save_csv", "save_img", "db_save_day", "error_win", "correct_win", "BUF_SIZE", "HISTORY_LEN"]:
        if k in payload:
            cfg[k] = payload[k]
    with open(settings.config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    _apply_runtime_from_config(cfg)
    return jsonify({"ok": True})


@app.post("/api/restart")
def restart_backend():
    with _state_lock:
        _restart_all()
    return jsonify({"ok": True})


@app.post("/api/verify-password")
def verify_password():
    payload = request.get_json(force=True, silent=True) or {}
    return jsonify({"ok": _check_password(payload.get("password", ""))})


@app.get("/preview/<int:video_id>")
def preview_page(video_id: int):
    if _video_by_id(video_id) is None:
        return Response("not found", status=404)
    return render_template("preview.html", video_id=video_id)


@app.get("/stream/<int:video_id>")
def stream(video_id: int):
    video = _video_by_id(video_id)
    if video is None:
        return Response("not found", status=404)

    def _stream_generator():
        while True:
            frame = getattr(video, "this_frame", None)
            if frame is None:
                time.sleep(0.2)
                continue
            ok, buf = cv2.imencode(".jpg", frame)
            if not ok:
                time.sleep(0.05)
                continue
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n")
            time.sleep(0.15)

    return Response(_stream_generator(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.get("/api/video/<int:video_id>/recognition")
def get_recognition(video_id: int):
    video = _video_by_id(video_id)
    if video is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(_recognition_payload(video))


@app.get("/api/video/<int:video_id>/frame")
def get_frame(video_id: int):
    video = _video_by_id(video_id)
    if video is None:
        return jsonify({"error": "not found"}), 404
    frame = getattr(video, "this_frame", None)
    if frame is None:
        return jsonify({"error": "no_frame"}), 404
    ok, buf = cv2.imencode(".png", frame)
    if not ok:
        return jsonify({"error": "encode_failed"}), 500
    payload = base64.b64encode(buf.tobytes()).decode("ascii")
    return jsonify({"image": payload, "width": int(frame.shape[1]), "height": int(frame.shape[0]), "ts": time.time()})


@app.get("/api/video/<int:video_id>/annotation")
def get_annotation(video_id: int):
    video = _video_by_id(video_id)
    if video is None:
        return jsonify({"error": "not found"}), 404
    if not _check_password(request.args.get("password", "")):
        return jsonify({"error": "password_error"}), 403
    return jsonify(_annotation_from_yaml(video))


@app.post("/api/video/<int:video_id>/annotation")
def save_annotation(video_id: int):
    video = _video_by_id(video_id)
    if video is None:
        return jsonify({"error": "not found"}), 404
    payload = request.get_json(force=True, silent=True) or {}
    if not _check_password(payload.get("password", "")):
        return jsonify({"error": "password_error"}), 403
    with _state_lock:
        _save_annotation(video, payload)
    return jsonify({"ok": True})


@app.post("/api/change-password")
def change_password():
    payload = request.get_json(force=True, silent=True) or {}
    old_pwd = str(payload.get("old_password", ""))
    new_pwd = str(payload.get("new_password", ""))
    if hashlib.sha256(old_pwd.encode("utf-8")).hexdigest() != settings.passwd:
        return jsonify({"ok": False, "message": "原密码错误"}), 400
    settings.passwd = hashlib.sha256(new_pwd.encode("utf-8")).hexdigest()
    if settings.license_data:
        from activate import save_license_file
        settings.license_data["passwd"] = settings.passwd
        save_license_file(settings.license_data)
    return jsonify({"ok": True})


@app.get("/annotate/<int:video_id>")
def annotate_page(video_id: int):
    video = _video_by_id(video_id)
    if video is None:
        return Response("not found", status=404)
    return render_template(
        "annotate.html",
        video_id=video_id,
        frame_width=int(video.frame_width),
        frame_height=int(video.frame_height),
    )


def run_web_server(host: str = "0.0.0.0", port: int = 5000):
    if settings.config_path is None:
        settings.config_path = str(Path("config.yaml").resolve())
    app.run(host=host, port=port, threaded=True)
