import shutil
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

import cv2


@dataclass
class RecordingOptions:
    name: str
    save_roi: bool
    every_n_frames: int
    zip_minutes: float
    max_hours: float | None
    draw_boxes: bool


class RecordingSession:
    def __init__(self, camera_key: str, video, base_dir: Path, options: RecordingOptions):
        self.camera_key = camera_key
        self.video = video
        self.options = options
        self.base_dir = base_dir
        self.dir = self.base_dir / options.name
        self.images_dir = self.dir / "images"
        self.zips_dir = self.dir / "zips"
        self.images_dir.mkdir(parents=True, exist_ok=False)
        self.zips_dir.mkdir(parents=True, exist_ok=True)

        self._idx = 0
        self._saved = 0
        self._started_at = time.time()
        self._last_zip_ts = time.time()
        self._zip_seq = 0
        self._zip_in_progress = False

    def stop(self):
        self._zip_once(force=True)

    def should_stop_by_time(self) -> bool:
        if self.options.max_hours is None:
            return False
        return (time.time() - self._started_at) >= self.options.max_hours * 3600

    def process_frame(self, frame):
        self._idx += 1
        if self._idx % self.options.every_n_frames != 0:
            self._zip_if_needed()
            return

        snap = frame.copy()
        if self.options.save_roi:
            self._save_roi_images(snap)
        else:
            self._save_full_image(snap)
        self._zip_if_needed()

    def _save_roi_images(self, frame):
        points = list((getattr(self.video, "xian_points", {}) or {}).items())
        ts = int(time.time() * 1000)
        for roi_id, (_, _, x1, y1, x2, y2) in points:
            roi = frame[y1:y2, x1:x2]
            if roi.size == 0:
                continue
            out = self.images_dir / f"f{self._idx:08d}_{ts}_roi_{roi_id}.jpg"
            cv2.imwrite(str(out), roi)
            self._saved += 1

    def _save_full_image(self, frame):
        if self.options.draw_boxes:
            points = list((getattr(self.video, "xian_points", {}) or {}).items())
            lights = getattr(self.video, "xian_light", None)
            for i, (_, (_, _, x1, y1, x2, y2)) in enumerate(points):
                color = (0, 255, 0)
                if lights is not None and len(lights) > i and not bool(lights[i]):
                    color = (0, 0, 255)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        ts = int(time.time() * 1000)
        out = self.images_dir / f"f{self._idx:08d}_{ts}.jpg"
        cv2.imwrite(str(out), frame)
        self._saved += 1

    def _zip_if_needed(self):
        if self.options.zip_minutes <= 0:
            return
        if time.time() - self._last_zip_ts >= self.options.zip_minutes * 60:
            self._zip_once()
            self._last_zip_ts = time.time()

    def _zip_once(self, force: bool = False):
        if self._zip_in_progress:
            return
        files = sorted(self.images_dir.glob("*.jpg"))
        if not files:
            return
        if (not force) and len(files) < 10:
            return
        self._zip_in_progress = True
        try:
            zip_path = self.zips_dir / f"part_{self._zip_seq:05d}.zip"
            self._zip_seq += 1
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
                for p in files:
                    zf.write(p, arcname=p.name)
            for p in files:
                p.unlink(missing_ok=True)
        finally:
            self._zip_in_progress = False


class RecordingManager:
    def __init__(self, root: str | None = None):
        if root is None:
            root = str(Path(__file__).resolve().parent.parent / "recordings")
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._sessions: dict[int, RecordingSession] = {}
        self._download_tasks: dict[tuple[str, str], dict] = {}

    @staticmethod
    def camera_dir_name(video) -> str:
        return f"camera_{video.id}_{getattr(video, 'video_id', '')}_{getattr(video, 'add_type', '')}".replace(" ", "_")

    def start(self, video, options: RecordingOptions):
        with self._lock:
            if int(video.id) in self._sessions:
                raise ValueError("recording already started")
            cam_dir = self.root / self.camera_dir_name(video)
            cam_dir.mkdir(parents=True, exist_ok=True)
            rec_dir = cam_dir / options.name
            if rec_dir.exists():
                raise ValueError("name_exists")
            session = RecordingSession(self.camera_dir_name(video), video, cam_dir, options)
            self._sessions[int(video.id)] = session

    def process_frame(self, video, frame):
        stop_now = False
        with self._lock:
            session = self._sessions.get(int(video.id))
            if session is None:
                return
            if session.should_stop_by_time():
                stop_now = True
            else:
                session.process_frame(frame)
        if stop_now:
            self.stop(int(video.id))

    def stop(self, video_id: int):
        with self._lock:
            session = self._sessions.pop(int(video_id), None)
        if session is not None:
            session.stop()

    def is_recording(self, video_id: int) -> bool:
        with self._lock:
            return int(video_id) in self._sessions

    def list_recordings(self, video):
        cam_dir = self.root / self.camera_dir_name(video)
        if not cam_dir.exists():
            return []
        rows = []
        for d in sorted([p for p in cam_dir.iterdir() if p.is_dir()]):
            rows.append({"name": d.name, "path": str(d)})
        return rows

    def delete_recording(self, video, name: str):
        target = self.root / self.camera_dir_name(video) / name
        if not target.exists():
            raise FileNotFoundError(name)
        shutil.rmtree(target)

    def _build_download_zip(self, rec_dir: Path, name: str) -> Path:
        out = rec_dir / f"{name}_download.zip"
        if out.exists():
            out.unlink()
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as zf:
            for p in sorted(rec_dir.rglob("*.zip")):
                if p.name == out.name:
                    continue
                zf.write(p, arcname=f"zips/{p.name}")
            images_dir = rec_dir / "images"
            if images_dir.exists():
                for p in sorted(images_dir.glob("*.jpg")):
                    zf.write(p, arcname=f"images/{p.name}")
        return out

    def prepare_download_async(self, video, name: str) -> str:
        cam = self.camera_dir_name(video)
        key = (cam, name)
        rec_dir = self.root / cam / name
        if not rec_dir.exists():
            raise FileNotFoundError(name)
        with self._lock:
            task = self._download_tasks.get(key)
            if task and task.get("status") in {"pending", "running"}:
                return task["task_id"]
            task_id = f"{cam}:{name}"
            task = {"task_id": task_id, "status": "pending", "error": "", "output": ""}
            self._download_tasks[key] = task

        def _runner():
            with self._lock:
                self._download_tasks[key]["status"] = "running"
            try:
                out = self._build_download_zip(rec_dir, name)
                with self._lock:
                    self._download_tasks[key]["status"] = "done"
                    self._download_tasks[key]["output"] = str(out)
            except Exception as e:
                with self._lock:
                    self._download_tasks[key]["status"] = "error"
                    self._download_tasks[key]["error"] = str(e)

        threading.Thread(target=_runner, daemon=True).start()
        return task_id

    def download_status(self, video, name: str) -> dict:
        key = (self.camera_dir_name(video), name)
        with self._lock:
            task = self._download_tasks.get(key)
            if not task:
                return {"status": "idle", "ready": False}
            status = task.get("status", "idle")
            return {
                "status": status,
                "ready": status == "done",
                "error": task.get("error", ""),
                "task_id": task.get("task_id", ""),
            }

    def get_prepared_download(self, video, name: str) -> Path:
        rec_dir = self.root / self.camera_dir_name(video) / name
        if not rec_dir.exists():
            raise FileNotFoundError(name)
        out = rec_dir / f"{name}_download.zip"
        if not out.exists():
            raise RuntimeError("not_ready")
        return out

    def get_or_build_download(self, video, name: str) -> Path:
        rec_dir = self.root / self.camera_dir_name(video) / name
        if not rec_dir.exists():
            raise FileNotFoundError(name)
        out = rec_dir / f"{name}_download.zip"
        if out.exists():
            return out
        # 兼容兜底：若前端未走 prepare/status，直接同步打包并返回，避免 409
        return self._build_download_zip(rec_dir, name)
