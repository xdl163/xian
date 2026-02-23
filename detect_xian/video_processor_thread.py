import csv
import threading
import time
import numpy as np
import cv2

from light_cls import img_cls_pt as img_cls_onnx
from datatypes import Video_error
import settings
from datatypes import Video

def send_error(video_error: Video_error):
    if video_error.error_type in ['断线','亮']:
        settings.modbusServer.update_video_xian(video_error.video.id,video_error.video.xian_light)
    else:
        settings.modbusServer.update_video_abnormal(video_error.video.id,video_error.video.have_abnormal)

    settings.xiandb.insert_event(video_error)

def crop_regions_from_points(image, final_points):
    crops = []
    for _, (x, y, x1, y1, x2, y2) in final_points:
        crops.append(image[y1:y2, x1:x2])
    return crops

def get_crop_boxes(points):
    return [(x1, y1, x2, y2) for _, (_, _, x1, y1, x2, y2) in points]

def batch_crop_numpy(image, boxes):
    return [np.ascontiguousarray(image[y1:y2, x1:x2]) for x1, y1, x2, y2 in boxes]

def crop_regions_from_points2(image, final_points):
    crops = []
    for x, y, x1, y1, x2, y2 in final_points:
        crops.append(image[y1:y2, x1:x2])
    return crops

class VideoProcessorThread(threading.Thread):
    def __init__(self, videos, send_error_func=send_error, interval=None,window=None):
        super().__init__()
        self.videos = videos
        self.window = window
        self.send_error_func = send_error_func
        self.interval = float(interval) if interval is not None else settings.get_frame_interval()
        self._running = True
        self.video_writer = None
        self.errors_all=[]
        self.last_del_db_time=time.time()
        settings.xiandb.delete_events_before_day()


    def update_plc_all(self):
        for video in self.videos:
            settings.modbusServer.update_video(video.id,video.xian_light,video.have_abnormal)

    def draw_warning_on_image(self,image, video_id):
        text = f"Camera {video_id} moved! Please re-annotate and reload."
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 1
        color = (0, 0, 255)  # 红色
        thickness = 2
        position = (50, 50)  # 左上角偏移

        # 绘制背景框（提高可读性）
        (text_width, text_height), _ = cv2.getTextSize(text, font, font_scale, thickness)
        cv2.rectangle(image, (position[0] - 10, position[1] - text_height - 10),
                      (position[0] + text_width + 10, position[1] + 10),
                      (255, 255, 255), -1)

        # 绘制文本
        cv2.putText(image, text, position, font, font_scale, color, thickness, cv2.LINE_AA)
        return image


    def run(self):
        # zero_nums_diffs=[]
        # csv_path = "../zero_diff_log.csv"
        num = 0

        while self._running:
            num += 1
            if num % 30 == 0:
                num=0
                self.update_plc_all()
                if time.time() -self.last_del_db_time > 1*24*60*60:
                    settings.xiandb.delete_events_before_day()
                    self.last_del_db_time = time.time()
                settings.xiandb.upsert_videos(self.videos)
            start = time.time()
            if self.videos:

                frame_null_num=0
                # ---------- 逐 video 处理 ----------
                for video in self.videos:
                    if video.id ==settings.label_video_id:
                        continue

                    
                    # kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (int(7/640*video.frame_width), 1))

                    frame = video.next_frame()
                    if frame is None:           # 无帧
                        frame_null_num += 1
                        continue
                    # frame_clean=frame.copy()


                    if not getattr(video, "enable_recognition", True):
                        if int(settings.show_id)==int(video.id):
                            self.window.update_display(frame)
                        continue

                    # ————————————— 1. 若未配置线点，直接跳过 —————————————
                    if not video.xian_points:
                        if settings.save:
                            video.save_img(frame,settings.video_output_paths[int(video.id)] if settings.video_output_paths is not None else settings.video_output_path)
                        if settings.save_csv:
                            video.save_img_csv(settings.video_output_paths[int(video.id)] if settings.video_output_paths is not None else settings.video_output_path)
                        continue


                    errors=self.detect_errors(video, frame)
                    if len(errors)>0:
                        if int(settings.show_id)==int(video.id):
                            self.window.update_display(frame)
                        continue

                    if not video.camMoveDetector.is_init():
                        video.camMoveDetector.find_roi(frame)

                    # ————————————— 2. 计算最小 ROI（只向下扩 30%） —————————————
                    boxes = np.array([(v[2], v[3], v[4], v[5])   # 取 (x1,y1,x2,y2)
                                      for v in video.xian_points.values()], dtype=np.int32)

                    left, top = boxes[:, 0].min(), boxes[:, 1].min()
                    right, bottom = boxes[:, 2].max(), boxes[:, 3].max()
                    h = bottom - top
                    bottom = bottom + int(h * 0.5)              # 仅向下扩 30 %
                    top =  top - int(h * 0.5)
                    right += 10
                    left -= 10
                    x0 = max(left, 0)
                    y0 = max(top, 0)
                    x1 = min(right,  frame.shape[1] - 1)
                    y1 = min(bottom, frame.shape[0] - 1)
                    roi = frame[y0:y1, x0:x1]


                    # ————————————— 3. HSV → 二值化（两张掩码） —————————————
                    # hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

                    # base_mask = cv2.inRange(hsv, video.hsv_lower, video.hsv_upper)

                    # base_mask2 = cv2.dilate(base_mask, kernel, 1)

                    # # 3-2 细条纹过滤掩码（new_mask）
                    # contours, _ = cv2.findContours(base_mask2, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    # strip_mask = np.zeros_like(base_mask2)
                    # for cnt in contours:
                    #     x, y, w, h_cnt = cv2.boundingRect(cnt)
                    #     if w < settings.point_max_size:
                    #         cv2.drawContours(strip_mask, [cnt], -1, 255, -1)

                    # strip_mask = cv2.erode(strip_mask, kernel, 1)

                    # ————————————— 4. 初始化 —————————————

                    # ————————————— 3. 用 PT 模型判定每个点位（替代二值化/条纹过滤） —————————————

                    # 初始化（保留你原来的初始化块）
                    if not isinstance(video.xian_light, np.ndarray):
                        n = len(video.xian_points)
                        video.xian_light       = np.ones(n, dtype=bool)
                        video.xian_allow_light = np.ones(n, dtype=bool)
                        video.error_counts     = np.zeros(n, dtype=np.uint16)
                        video.correct_counts   = np.zeros(n, dtype=np.uint16)
                        video._fail_mask       = np.empty(n, dtype=bool)
                        video._pass_mask       = np.empty(n, dtype=bool)
                        video.white_num        = np.zeros(n, dtype=np.uint16)

                    # n = len(video.xian_points)

                    # 将 boxes 转到 ROI 内部坐标（保留你的做法）
                    roi_boxes = boxes.copy()
                    roi_boxes[:, [0, 2]] -= x0
                    roi_boxes[:, [1, 3]] -= y0

                    # clip 到 ROI 边界（重要：否则可能出现负数或超过 roi 尺寸）
                    H, W = roi.shape[:2]
                    roi_boxes[:, [0, 2]] = np.clip(roi_boxes[:, [0, 2]], 0, W)
                    roi_boxes[:, [1, 3]] = np.clip(roi_boxes[:, [1, 3]], 0, H)

                    # valid：框必须有面积（后续计数/状态更新都只在 valid==True 上进行）
                    valid = (roi_boxes[:, 2] > roi_boxes[:, 0]) & (roi_boxes[:, 3] > roi_boxes[:, 1])

                    # 裁剪 patch（只裁剪 valid 的），并记录回填索引
                    patches = []
                    idx_map = []  # patches[k] 对应点位 idx_map[k]
                    for i, (x1r, y1r, x2r, y2r) in enumerate(roi_boxes):
                        if not valid[i]:
                            continue
                        patch = roi[y1r:y2r, x1r:x2r]  # 注意：这里使用“右开区间”，与 detect_errors 的 crop 风格一致
                        if patch.size == 0:
                            valid[i] = False
                            continue
                        patches.append(np.ascontiguousarray(patch))
                        idx_map.append(i)

                    # 默认 hit 先用上一帧状态兜底，保证 shape / dtype 一致
                    hit_model = video.xian_light.copy()

                    # 批量推理：返回 [0/1]，1=light
                    if patches:
                        print(video.id)
                        pred_list = img_cls_onnx(patches, threshold=float(getattr(settings, "model_threshold", 0.9)), verbose=False)  # 这里的 0.5 你也可以做成 settings.xxx
                        for k, i in enumerate(idx_map):
                            hit_model[i] = (pred_list[k] == 1)

                    # 最终 hit：只有 valid=True 才采用新结果，否则保持旧状态（与你原来 np.where(valid, hit1, video.xian_light) 一致）
                    hit = np.where(valid, hit_model, video.xian_light)


                    fail_raw = ~hit          # 本帧“断线”判定
                    ok_raw   =  hit          # 本帧“亮”判定

                    # 更新失败和通过掩码
                    video._fail_mask[:] = np.logical_and(fail_raw, valid)
                    video._pass_mask[:] = np.logical_and(ok_raw,   valid)


                    # 更新错误和正确计数
                    err, cor, lit = video.error_counts, video.correct_counts, video.xian_light

                    # 只在 valid==True 的点位上更新计数
                    # err += np.logical_and(fail_raw, valid)
                    err += np.logical_and.reduce((fail_raw, valid, (err <= settings.ERROR_WIN)))
                    cor += np.logical_and.reduce((ok_raw, valid, (cor <= settings.CORRECT_WIN)))

                    # 确保错误和正确计数在互相冲突的情况下归零
                    err[np.logical_and(ok_raw,   valid)] = 0#当前为亮，断线归零
                    cor[np.logical_and(fail_raw, valid)] = 0#当前断线，亮归零

                    # 有争议点二次确认（同样只看 valid）
                    need_chk = np.where(((np.logical_and(fail_raw, valid) & lit) | (np.logical_and(ok_raw, valid) & ~lit)) &#这一帧与当前状态不一致
                                        ((err == 1) | (err == settings.ERROR_WIN) |
                                         (cor == 1) | (cor == settings.CORRECT_WIN)))[0]

                    # print(video.id,need_chk)
                    if need_chk.size and len(self.detect_errors(video, frame, mast=True))!=0:
                        print('异常失败')
                        err[need_chk] = 0
                        fail_raw[need_chk] = False
                    # 断线 / 恢复亮
                    broke_idx = np.where(np.logical_and((err >= settings.ERROR_WIN),  lit))[0]
                    light_idx = np.where(
                        np.logical_and.reduce((
                            cor >= settings.CORRECT_WIN,
                            ~lit,
                            video.xian_allow_light
                        ))
                    )[0]
                    light_piao_idx = np.where(
                        np.logical_and.reduce((
                            cor >= settings.CORRECT_WIN,
                            ~lit,
                            ~video.xian_allow_light
                        ))
                    )[0]
                    # print(light_idx,light_piao_idx,video.xian_allow_light)
                    # 更新持久状态
                    lit[broke_idx] = False
                    lit[light_idx] = True
                    # video.xian_allow_light[broke_idx] = False
                    cor[broke_idx] = 0
                    cor[light_piao_idx]=0
                    err[light_idx] = 0

                    if np.all(~video.xian_light):
                        video.xian_allow_light = np.ones(len(video.xian_allow_light), dtype=bool)
                    # frame = cv2.cvtColor(strip_mask, cv2.COLOR_GRAY2BGR)
                    # ————————————— 5. 标注 + 上报（保持不变） —————————————
                    self.draw_status(frame,video)
                    xw, yh = settings.crap_w + 5, settings.crap_h + 5
                    for idx in broke_idx:
                        pid, (cx, cy, *_ ) = list(video.xian_points.items())[idx]
                        cv2.rectangle(frame, (cx - xw, cy - yh), (cx + xw, cy + yh), (0, 0, 255), 3)
                        self.errors_all.append(Video_error(video, pid, roi, frame, '断线',3))
                        # self.send_error_func(Video_error(video, pid, roi, frame, '断线'))

                    for idx in light_idx:
                        pid, (cx, cy, *_ ) = list(video.xian_points.items())[idx]
                        cv2.rectangle(frame, (cx - xw, cy - yh), (cx + xw, cy + yh), (0, 255, 0), 3)
                        self.errors_all.append(Video_error(video, pid, roi, frame, '亮',3))
                        # self.send_error_func(Video_error(video, pid, roi, frame, '亮'))
                    if int(settings.show_id)==int(video.id):
                        self.window.update_display(frame)
                    if settings.save:
                        video.save_img(frame, settings.video_output_paths[int(video.id)] if settings.video_output_paths is not None else settings.video_output_path)
                    if settings.save_csv:
                        video.save_img_csv(settings.video_output_paths[int(video.id)] if settings.video_output_paths is not None else settings.video_output_path)
                if frame_null_num>0:
                    print(f'缺少画面{frame_null_num}')
            else:
                # 没有视频源时延迟一会儿
                time.sleep(2)
            for video_error in self.errors_all:
                self.send_error_func(video_error)
            self.errors_all.clear()
            # 控制每轮处理时间
            elapsed = time.time() - start
            print('总耗时', elapsed)
            time.sleep(max(0, self.interval - elapsed))

    def stop(self):
        self._running = False  # 停止线程循环

    def detect_errors(self, video: Video, frame, mast=False):
        """
        检测视频帧的遮挡、激光发射器、激光落点异常
        """
        errors = []
        if video.camMove:
            frame = self.draw_warning_on_image(frame, video.id)
            errors.append("摄像头移动")
        # 检查遮挡异常
        if len(errors)==0 and (video.have_abnormal or mast) and video.last_img() is not None and video.this_time - video.abnormal_time > 3:
            if video.video_diff.diff(video.last_img(), frame.copy())[0]:
                errors.append("遮挡")
                video.abnormal_time = int(time.time())
                if not video.have_abnormal:
                    video.have_abnormal = True
                    self.errors_all.append(Video_error(video, -1, None, frame, '遮挡',2))
            else:
                if video.have_abnormal:
                    video.have_abnormal = False
                    video.xian_allow_light = np.ones(len(video.xian_allow_light), dtype=bool)
                    self.errors_all.append(Video_error(video, -1, None, frame, '恢复',-1))
                video.abnormal_time = -1

        elif video.have_abnormal:
            errors.append("遮挡")


        # # 检查激光发射器
        # if len(errors)==0 and video.laser_emitter is not  None and len(video.laser_emitter) != 0 and (video.light_send_error or mast) and video.this_time - video.light_send_error_time > 10:
        #     print(video.laser_emitter[0])
        #     x, y, x1, y1, x2, y2 = video.laser_emitter[0]
        #     crop = frame[y1:y2, x1:x2]
        #     print(len(crop))
        #     if img_cls_onnx([crop])[0] == 0:
        #         errors.append("激光发射器")
        #         video.light_send_error_time = video.this_time
        #         if not video.light_send_error:
        #             video.light_send_error = True
        #             self.errors_all.append(Video_error(video, -1, None, frame, '激光发射器',1))
        #     else:
        #         if video.light_send_error:
        #             video.light_send_error = False
        #             self.errors_all.append(Video_error(video, -1, None, frame, '恢复',-1))
        #         video.light_send_error_time = -1
        # elif video.light_send_error:
        #     errors.append("激光发射器")

        # 检查激光落点
        if len(errors)==0 and video.laser_wall is not  None and len(video.laser_wall) != 0   and (video.laser_wall_error or mast) and video.this_time - video.laser_wall_error_time > 10:
            x, y, x1, y1, x2, y2 = video.laser_wall[0]
            crop = frame[y1:y2, x1:x2]
            # crop = crop_regions_from_points2(frame, video.laser_wall)[0]
            if img_cls_onnx([crop])[0] == 0:
                errors.append("激光落点")
                video.laser_wall_error_time = video.this_time
                if not video.laser_wall_error:
                    video.laser_wall_error = True
                    self.errors_all.append(Video_error(video, -1, None, frame, '激光落点',1))
            else:
                video.laser_wall_error_time = -1
                if video.laser_wall_error:
                    video.laser_wall_error = False
                    self.errors_all.append(Video_error(video, -1, None, frame, '恢复',-1))
        elif video.laser_wall_error:
            errors.append("激光落点")


        # 检查摄像头移动检测        if (video.have_abnormal or mast) and video.last_img() is not None and video.this_time - video.abnormal_time > 10:
        if len(errors)==0 and (video.camMove or mast) :
            if video.camMoveDetector.detect(frame)[0]:
                video.camMove = True
                errors.append('摄像头移动')
                self.errors_all.append(Video_error(video, -1, None, frame, '摄像头移动',2))
                frame = self.draw_warning_on_image(frame, video.id)


        if len(errors) > 0:
            print(errors)
        if settings.save:
            if '遮挡' in errors:
                # 绘制遮挡异常框
                roi = video.getRoi()  # 获取遮挡区域
                cv2.rectangle(frame, (roi[0], roi[1]), (roi[2], roi[3]), (0, 0, 255), 1)  # 绘制红色矩形框
                cv2.putText(frame, "have_abnormal", (roi[0], roi[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
            if "激光发射器" in errors:
                for (_,_,x1, y1, x2, y2) in video.laser_emitter:
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 1)  # 绘制蓝色矩形框
                cv2.putText(frame, "light_send_error", (video.laser_emitter[0][0], video.laser_emitter[0][1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 0, 0), 2)
            if '激光落点' in errors:
                # 绘制激光落点异常框
                for (_,_,x1, y1, x2, y2) in video.laser_wall:
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 1)  # 绘制绿色矩形框
                cv2.putText(frame, "laser_wall_error", (video.laser_wall[0][0], video.laser_wall[0][1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)

        return errors


    def draw_status(self, frame, video):
        """
        Draw rectangles or circles to represent different statuses:
        - Blocked areas (遮挡)
        - Broken lines (断线)
        - Highlighted points (亮)
        """
        for idx, (pid, (x, y, x1, y1, x2, y2)) in enumerate(video.xian_points.items()):
            if video._fail_mask[idx]:  # If the point is broken
                color = (0, 0, 255)  # Red for broken line
                thickness = 1
            elif video._pass_mask[idx]:  # If the point is fixed
                color = (0, 255, 0)  # Green for fixed
                thickness = 1
            else:
                color = (255, 255, 255)  # Default white
                thickness = 1

            # 绘制矩形框
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
            # 绘制矩形框

        # You can also draw text or other shapes to highlight specific areas (like blocked areas).
