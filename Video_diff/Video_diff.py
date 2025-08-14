import time
import cv2
import settings


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
    filtered = cv2.medianBlur(diff, settings.medianBlur_ksize)

    # 二值化
    _, thresh = cv2.threshold(filtered, settings.threshold_thresh, 255, cv2.THRESH_BINARY)

    # 形态学处理
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, settings.kernel_ksize)
    kernel2 = cv2.getStructuringElement(cv2.MORPH_RECT, settings.kernel_ksize2)

    denoised = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
    dilated = cv2.dilate(denoised, kernel2)
    # cv2.imshow("Thresh Binary", dilated)

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

        # cv2.imshow("Video Frame", display)
        # if diff_img is not None:
        #     cv2.imshow("Diff Map", cv2.resize(diff_img, (480, 270)))

        if cv2.waitKey(30) & 0xFF == ord('q'):
            break

        prev_frame = curr_frame
        time.sleep(0.1)

    cap.release()
    cv2.destroyAllWindows()
