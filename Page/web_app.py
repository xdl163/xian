import base64
import hashlib
import threading
import time
from typing import Any

import cv2
import yaml
from flask import Flask, Response, jsonify, render_template, request

import settings


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
        x1 = max(x - settings.crap_w * 2, 0)
        y1 = max(y - settings.crap_h * 2, 0)
        x2 = min(x + settings.crap_w * 2, width - 1)
        y2 = min(y + settings.crap_h * 2, height - 1)

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
    data_to_save["id"] = str(meta.get("id", video.id))

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


def _stream_generator(video):
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


@app.get("/")
def index():
    return render_template("index.html", videos=settings.video_list)


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
    return Response(_stream_generator(video), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.get("/stream_result/<int:video_id>")
def stream_result(video_id: int):
    video = _video_by_id(video_id)
    if video is None:
        return Response("not found", status=404)
    return Response(_stream_generator(video), mimetype="multipart/x-mixed-replace; boundary=frame")


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

    ok, buf = cv2.imencode(".jpg", frame)
    if not ok:
        return jsonify({"error": "encode_failed"}), 500

    payload = base64.b64encode(buf.tobytes()).decode("ascii")
    return jsonify({"image": payload, "width": int(frame.shape[1]), "height": int(frame.shape[0]), "ts": time.time()})


@app.get("/api/video/<int:video_id>/annotation")
def get_annotation(video_id: int):
    video = _video_by_id(video_id)
    if video is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(_annotation_from_yaml(video))


@app.post("/api/video/<int:video_id>/annotation")
def save_annotation(video_id: int):
    video = _video_by_id(video_id)
    if video is None:
        return jsonify({"error": "not found"}), 404
    payload = request.get_json(force=True, silent=True) or {}
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
    app.run(host=host, port=port, threaded=True)
