import cv2
import numpy as np
import torch

# =========================
# 全局：加载 PT / TorchScript 模型（只加载一次）
# =========================
MODEL_PATH = r"E:\PycharmProjects\xian_util_new\train\runs\run_3_s4-2\quant_eval_all\int8_scripted.pt"

# MODEL_PATH = r'C:\Users\HXGW\Desktop\1\int8_scripted.pt'
DEVICE = "cpu"   # INT8 Scripted 必须 CPU

_model = torch.jit.load(MODEL_PATH, map_location=DEVICE)
_model.eval()


# session = ort.InferenceSession("rgb_hsv_threshold.onnx", providers=["CPUExecutionProvider"])
def img_cls(image_list):
    """
    检查图片列表中的每张图片是否包含白点，白点根据HSV阈值筛选。

    参数:
    - image_list: 输入的图片列表，每张图片是通过cv2.imread读取的。
    - h_min, h_max: Hue通道的最小和最大值。
    - s_min, s_max: Saturation通道的最小和最大值。
    - v_min, v_max: Value通道的最小和最大值。

    返回:
    - 一个包含1和0的列表，1表示有白点，0表示没有白点。
    """
    h_min, h_max, s_min, s_max, v_min, v_max=0,178,50,255,200,255
    result = []

    for img in image_list:
        # 转换为HSV
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

        # 根据阈值进行筛选
        lower_bound = np.array([h_min, s_min, v_min])
        upper_bound = np.array([h_max, s_max, v_max])
        mask = cv2.inRange(hsv, lower_bound, upper_bound)

        # 检查白点是否存在
        white_spots = np.sum(mask == 255)  # 计算白色像素的数量

        if white_spots > 0:
            result.append(1)  # 有白点
        else:
            result.append(0)  # 没有白点

    return result

# =========================
# 批量分类函数
# =========================
def img_cls_pt(image_list, threshold: float = 0.5, verbose: bool = False):
    """
    使用 PT / TorchScript 模型，对 image_list 进行批量预测

    参数:
    - image_list: List[np.ndarray], BGR 格式（cv2.imread 读入）
    - threshold : float, 判定为 light 的概率阈值（默认 0.5）

    返回:
    - List[int]: 1 表示 light / 有白点，0 表示 black / 无白点
    """

    if len(image_list) == 0:
        return []

    # ---------- 1) 预处理：BGR -> Gray -> 40x40 -> float32 ----------
    batch = []

    for img in image_list:
        # BGR -> Gray
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # resize 到 40x40（与你训练一致）
        if gray.shape != (40, 40):
            gray = cv2.resize(gray, (40, 40), interpolation=cv2.INTER_LINEAR)

        # /255 -> float32
        x = gray.astype(np.float32) / 255.0
        batch.append(x)

    # (N,40,40) -> (N,1,40,40)
    x_np = np.stack(batch, axis=0)
    x_np = np.expand_dims(x_np, axis=1)

    # numpy -> torch
    x = torch.from_numpy(x_np).to(DEVICE)

    # ---------- 2) 推理 ----------
    with torch.no_grad():
        logits = _model(x)                     # (N,2)
        prob = torch.softmax(logits, dim=1)    # (N,2)
        prob_light = prob[:, 1]                # light 类

        pred = (prob_light >= threshold).long()
    # ---------- 2.5) 打印置信度 ----------
    if verbose:
        # 转成 python list，避免打印 tensor 的设备信息
        probs = prob_light.detach().cpu().numpy().tolist()
        # 如果你想要一行打印全部：
        print("[img_cls_pt] prob_light_all:", [round(p, 6) for p in probs])
    # ---------- 3) 返回 python list ----------
    return pred.cpu().tolist()
