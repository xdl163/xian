import cv2
import numpy as np
from typing import List, Optional
from collections import deque
"""
摄像头移动检测，先调用find_roi，获取roi区域，然后detect检测
"""
class CamMoveDetector:
    def __init__(self, queue_size=10, motion_threshold=10):
        """
        初始化摄像头移动检测器
        :param queue_size: 缓存图像的队列大小，用于运动检测（默认10张）
        :param motion_threshold: 平移阈值，超过即认为发生了移动
        """
        self.image_queue = deque(maxlen=queue_size)  # 图像队列，用于累积运动检测
        self.prev_image: Optional[np.ndarray] = None  # 上一张图像，用于帧间位移检测
        self.y_line: Optional[int] = None             # 最终检测到的 y 线位置
        self.motion_threshold = motion_threshold      # 位移检测阈值
        self.img_num=0

    def find_nonzero_line_from_bottom(self, img):
        """
        从下往上寻找第一条非零行
        :param img: 二值图像
        :return: 非零行的 y 坐标，找不到返回 -1
        """
        for y in range(img.shape[0] - 1, -1, -1):
            if np.any(img[y, :] != 0):
                return y
        return -1

    def detect_motion_line_y(self, images: List[np.ndarray]) -> int:
        """
        使用累积帧差法检测靠底部的活动区域 y 值
        :param images: RGB 图像序列
        :return: 检测到的 y 坐标（向下偏移 20），找不到则返回 -1
        """
        prev_gray = None
        accum_diff = None
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (10, 5))
        kernel2 = cv2.getStructuringElement(cv2.MORPH_RECT, (20, 10))

        for frame in images:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if accum_diff is None:
                accum_diff = np.zeros_like(gray, dtype=np.uint8)
            if prev_gray is not None:
                diff = cv2.absdiff(gray, prev_gray)
                _, diff_thresh = cv2.threshold(diff, 100, 255, cv2.THRESH_TOZERO)
                accum_diff = cv2.add(accum_diff, diff_thresh)
            prev_gray = gray

        if accum_diff is None:
            return -1

        # 形态学处理增强运动区域
        accum_diff = cv2.erode(accum_diff, kernel, iterations=1)
        accum_diff = cv2.dilate(accum_diff, kernel2, iterations=1)

        y_line = self.find_nonzero_line_from_bottom(accum_diff)
        return y_line + 20 if y_line != -1 else -1

    def detect_shift_between_images(self, img1, img2):
        """
        使用 ORB 特征匹配检测两帧图像之间是否发生了显著平移
        :param img1: 第一帧图像
        :param img2: 第二帧图像
        :return: (是否位移, dx, dy)
        """
        orb = cv2.ORB_create(nfeatures=500)
        kp1, des1 = orb.detectAndCompute(img1, None)
        kp2, des2 = orb.detectAndCompute(img2, None)

        # 关键点不足或描述子为 None，无法检测
        if des1 is None or des2 is None or len(kp1) < 5 or len(kp2) < 5:
            return False, 0, 0

        # BFMatcher 匹配 + 过滤质量差的匹配项
        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        raw_matches = bf.match(des1, des2)
        matches = [m for m in raw_matches if m.distance < 60]
        matches = sorted(matches, key=lambda x: x.distance)

        if len(matches) < 5:
            return False, 0, 0

        # 提取匹配点，估计仿射变换
        src_pts = np.float32([kp1[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
        dst_pts = np.float32([kp2[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)
        M, inliers = cv2.estimateAffinePartial2D(src_pts, dst_pts)

        # 无有效仿射矩阵或内点不足
        if M is None or inliers is None or np.sum(inliers) < 5:
            return False, 0, 0

        dx, dy = M[0, 2], M[1, 2]
        shifted = abs(dx) > self.motion_threshold or abs(dy) > self.motion_threshold
        return shifted, dx, dy

    def is_init(self):
        """
        返回是否初始化结束
        :return:
        """
        return self.y_line is not None

    def find_roi(self, image: np.ndarray) -> bool:
        """
        放入一帧图像，填满队列后进行运动检测，更新 self.y_line
        :param image: 当前图像
        :return: 是否成功检测（队列是否满）
        """
        if self.y_line is not None:
            return True

        if self.img_num %6 ==0:
            self.image_queue.append(image)
            
        self.img_num += 1
        if len(self.image_queue) == self.image_queue.maxlen:
            self.y_line = self.detect_motion_line_y(list(self.image_queue))
            return True
        return False

    def detect(self, image: np.ndarray) -> (bool, float, float):
        """
        判断当前帧与上一帧是否存在摄像头移动
        :param image: 当前图像
        :return: (是否移动, dx, dy)
        """
        if self.is_init():
            return False, 0, 0

        image = image[self.y_line:, :]

        if self.prev_image is None:
            self.prev_image = image
            return False, 0, 0  # 首帧直接认为“有效”
        shifted, dx, dy = self.detect_shift_between_images(self.prev_image, image)
        self.prev_image = image
        return shifted, dx, dy
