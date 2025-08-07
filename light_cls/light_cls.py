import cv2
import numpy as np




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


