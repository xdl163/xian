from pathlib import Path

import cv2
import numpy as np
import torch

import settings

DEVICE = "cpu"
DEFAULT_MODEL_PATH = Path(__file__).resolve().parent.parent / "model_int8.onnx"

_model = None
_model_path_loaded = None


def _resolve_model_path(path_like: str | None) -> Path:
    if path_like:
        p = Path(path_like)
        if p.is_absolute():
            return p
        return Path(__file__).resolve().parent.parent / p
    return DEFAULT_MODEL_PATH


def reload_model(path_like: str | None = None):
    global _model, _model_path_loaded
    model_path = _resolve_model_path(path_like)
    _model = torch.jit.load(str(model_path), map_location=DEVICE)
    _model.eval()
    _model_path_loaded = str(model_path)
    settings.model_path = str(Path(model_path).name)
    return _model_path_loaded


def _ensure_model_loaded():
    global _model
    if _model is not None:
        return
    cfg_path = getattr(settings, "model_path", None)
    reload_model(cfg_path)


def img_cls(image_list):
    h_min, h_max, s_min, s_max, v_min, v_max = 0, 178, 50, 255, 200, 255
    result = []

    for img in image_list:
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        lower_bound = np.array([h_min, s_min, v_min])
        upper_bound = np.array([h_max, s_max, v_max])
        mask = cv2.inRange(hsv, lower_bound, upper_bound)
        white_spots = np.sum(mask == 255)
        result.append(1 if white_spots > 0 else 0)

    return result


def img_cls_pt(image_list, threshold: float = 0.5, verbose: bool = False):
    if len(image_list) == 0:
        return []

    _ensure_model_loaded()

    batch = []
    for img in image_list:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if gray.shape != (40, 40):
            gray = cv2.resize(gray, (40, 40), interpolation=cv2.INTER_LINEAR)
        x = gray.astype(np.float32) / 255.0
        batch.append(x)

    x_np = np.stack(batch, axis=0)
    x_np = np.expand_dims(x_np, axis=1)
    x = torch.from_numpy(x_np).to(DEVICE)

    with torch.no_grad():
        logits = _model(x)
        prob = torch.softmax(logits, dim=1)
        prob_light = prob[:, 1]
        pred = (prob_light >= threshold).long()

    if verbose:
        probs = prob_light.detach().cpu().numpy().tolist()
        print("[img_cls_pt] prob_light_all:", [round(p, 6) for p in probs])

    return pred.cpu().tolist()
