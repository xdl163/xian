import time
import cv2


# def get_image(frame):
#     if len(frame.shape) != 2:  # 如果是单通道灰度图像
#         h,w = frame.shape[:2]
#         if h!= img_h or w != img_w:
#             frame = cv2.resize(frame, (img_w, img_h))
#         # 缩放 + 灰度
#         scale_ratio = 0.3
#         frame_resized = cv2.resize(frame, (0, 0), fx=scale_ratio, fy=scale_ratio)
#         gray = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2GRAY)
#         gray=gray.astype(np.uint8)
#         return gray, frame_resized
#     return frame,frame

# def detect_abnormal(prev_frame, curr_frame, roi=[0,0,1280,720],w=640):
#     """
#     在 ROI 区域检测两帧之间的差异。
#     :param prev_frame: 上一帧图像（BGR）
#     :param curr_frame: 当前帧图像（BGR）
#     :param roi: 感兴趣区域 (minx, miny, maxx, maxy)，基于原图
#     :return: 是否异常、差分图（缩放后 ROI 区域）、轮廓列表（缩放后且相对于整图）
#     """
#     scale_ratio = 0.3
#     roi=[0,0,img_w,img_h]
#     # 缩放并转为灰度图
#     prev_gray, prev_resized = get_image(prev_frame)
#     curr_gray, curr_resized = get_image(curr_frame)
#
#     if roi is not None:
#         # 原始 ROI 缩放到当前图像坐标
#         minx, miny, maxx, maxy = roi
#         minx = int(minx * scale_ratio)
#         miny = int(miny * scale_ratio)
#         maxx = int(maxx * scale_ratio)
#         maxy = int(maxy * scale_ratio)
#
#         # 检查 ROI 是否越界
#         h, w = prev_gray.shape
#         minx = max(0, minx)
#         miny = max(0, miny)
#         maxx = min(w, maxx)
#         maxy = min(h, maxy)
#
#         if minx >= maxx or miny >= maxy:
#             print("⚠️ ROI 区域无效")
#             return False, None, []
#
#         # 裁剪 ROI 区域
#         prev_crop = prev_gray[miny:maxy, minx:maxx]
#         curr_crop = curr_gray[miny:maxy, minx:maxx]
#
#         if prev_crop.size == 0 or curr_crop.size == 0:
#             print("⚠️ 裁剪后图像为空")
#             return False, None, []
#         # 帧间差分
#         diff = cv2.absdiff(curr_crop, prev_crop)
#     else:
#         diff = cv2.subtract(prev_resized, curr_resized)
#
#     # 中值滤波
#     filtered = cv2.medianBlur(diff, int(11))
#
#     # 二值化
#     _, thresh = cv2.threshold(filtered, 25, 255, cv2.THRESH_BINARY)
#
#     # 形态学处理
#     kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (12, 20))
#     kernel2 = cv2.getStructuringElement(cv2.MORPH_RECT, (24, 100))
#     denoised = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
#     dilated = cv2.dilate(denoised, kernel2)
#
#     # 查找轮廓
#     contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
#
#     adjusted_contours = contours
#
#     if adjusted_contours:
#         return True, dilated, adjusted_contours
#
#     return False, dilated, []
class Video_diff():
    def __init__(self,scale_ratio=0.3):
        self.last_img=None
        self.scale_ratio=scale_ratio

    def diff(self,img1,img2):
        if img1 is None or img2 is None:
            return False, None,None
        # if self.last_img is not None:
        #     img1=self.last_img
        resulr= detect_abnormal(img1,img2,scale_ratio=self.scale_ratio)
        # if resulr[0]:#有遮挡
        #     if self.last_img is None:#之前无遮挡
        #         self.last_img=img1
        # else:
        #     self.last_img=None
        return resulr
def get_image(image, scale_ratio=0.3):
    """
    缩放并转为灰度图
    """
    resized = cv2.resize(image, (0, 0), fx=scale_ratio, fy=scale_ratio)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    return gray, resized
def detect_abnormal(prev_frame, curr_frame, scale_ratio=0.3):
    """
    检测整张图两帧之间的异常（差异区域）。
    :param prev_frame: 上一帧图像（BGR）
    :param curr_frame: 当前帧图像（BGR）
    :param scale_ratio: 缩放比例（默认0.3）
    :return: (是否异常:bool, 差分图:np.ndarray, 异常区域轮廓列表:list)
    """
    # 缩放并转灰度图
    prev_gray, _ = get_image(prev_frame, scale_ratio)
    curr_gray, _ = get_image(curr_frame, scale_ratio)

    # 帧间差分
    diff = cv2.absdiff(curr_gray, prev_gray)

    # 中值滤波
    filtered = cv2.medianBlur(diff, 11)

    # 二值化
    _, thresh = cv2.threshold(filtered, 5, 255, cv2.THRESH_BINARY)

    # 形态学处理
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (6, 14))
    kernel2 = cv2.getStructuringElement(cv2.MORPH_RECT, (24, 100))

    denoised = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
    dilated = cv2.dilate(denoised, kernel2)
    cv2.imshow("Thresh Binary", dilated)

    # 查找轮廓
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    return bool(contours), dilated, contours


if __name__ == '__main__':

    # 初始化差分检测类
    detector = Video_diff(scale_ratio=0.3)

    # 打开视频文件（你可以换成自己的视频路径）
    video_path = r"C:\Users\Lenovo\projects\datasets\xian\vvvvvvv\output_video_1.avi"
    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        print("❌ 无法打开视频文件:", video_path)
        exit()

    # 初始化第一帧
    ret, prev_frame = cap.read()
    if not ret:
        print("❌ 无法读取视频帧")
        exit()

    while True:
        ret, curr_frame = cap.read()
        if not ret:
            break  # 视频结束

        # 进行遮挡/异常检测
        abnormal, diff_img, contours = detector.diff(prev_frame, curr_frame)

        # 显示检测结果
        display = curr_frame.copy()
        if abnormal:
            print("⚠️ 检测到异常区域")
            # 将缩放后的轮廓绘制到原图（注意你也可以放大坐标再画）
            scale = detector.scale_ratio
            for cnt in contours:
                cnt = (cnt / scale).astype(int)
                x, y, w, h = cv2.boundingRect(cnt)
                cv2.rectangle(display, (x, y), (x + w, y + h), (0, 0, 255), 2)

        cv2.imshow("Video Frame", display)
        if diff_img is not None:
            cv2.imshow("Diff Map", cv2.resize(diff_img, (480, 270)))

        if cv2.waitKey(30) & 0xFF == ord('q'):
            break

        prev_frame = curr_frame
        time.sleep(0.1)

    cap.release()
    cv2.destroyAllWindows()
