import os
import cv2
import yaml
import numpy as np
import time

from PyQt5.QtGui import QIntValidator,QFont,QImage,QPixmap
from PyQt5.QtWidgets import QLabel, QApplication, QTableWidget, QTableWidgetItem, QPushButton, QWidget, QVBoxLayout, \
    QFileDialog, QDialog, QDialogButtonBox, QHBoxLayout, QLineEdit, QHeaderView, QAbstractButton, QSlider, QGridLayout, \
    QScrollArea, QComboBox, QCheckBox, QInputDialog
from PyQt5.QtCore import QThread, pyqtSignal,Qt
import settings
from datatypes import Video
from datatypes.Video import Video

def rescale_widgets(root: QWidget, scale: float,
                    min_btn=(100, 30), base_font_pt=10):
    """
    递归地给 root 下面所有子控件按比例缩放。
    scale        : 当前缩放因子
    min_btn      : 设计基准下按钮的最小宽高
    base_font_pt : 设计基准下使用的字体大小（pt）
    """
    for w in root.findChildren(QWidget):
        # 缩放字体
        f = w.font() or QFont()
        f.setPointSizeF(base_font_pt * scale)
        w.setFont(f)

        # 若是按钮，再顺便调一下最小尺寸
        if isinstance(w, QAbstractButton):
            w.setMinimumSize(int(min_btn[0]*scale), int(min_btn[1]*scale))



class FrameCaptureThread(QThread):
    frame_captured = pyqtSignal(object)  # 发出(frame, index)

    def __init__(self, video):
        super().__init__()
        self.video = video
        self.running = True
        self.interval = 2  # 秒

    def run(self):
        while self.running:
            frame = self.video.next_frame()  # 获取下一帧
            if frame is not  None:
                self.frame_captured.emit(frame)
            time.sleep(self.interval)

    def stop(self):
        self.running = False


class VideoAnnotationDialog(QDialog):
    def __init__(self, video: Video, annotation_type, half_w=8, half_h=8):
        super().__init__()

        self.setWindowTitle("视频亮点标注")
        geo = QApplication.primaryScreen().availableGeometry()
        self.base_w = int(geo.width()  * 0.8)
        self.base_h = int(geo.height() * 0.8)

        # 初始大小 & 居中
        self.resize(self.base_w, self.base_h)
        self.move((geo.width()  - self.base_w)  // 2,
                  (geo.height() - self.base_h) // 2)

        # === 基本参数初始化 ===
        self.video = video
        self.annotation_type = annotation_type
        self.annotation_data = {} if annotation_type == "yarn" else []
        self.canceled = False
        self.auto_increment = False  # 是否启用自动编号
        self.auto_id_counter = 1  # 自动编号计数器
        # self.cropped_images = {}  # 存储点击点周围的图像（用于放大或分析）

        # HSV颜色筛选默认值
        self.hsv_range = {
            "h_min": 0, "h_max": 179,
            "s_min": 0, "s_max": 255,
            "v_min": 178, "v_max": 255
        }

        self.half_h = half_h  # 截图高度的一半
        self.half_w = half_w  # 截图宽度的一半
        self.frame_index = 0  # 当前帧索引

        self.video_frame = None  # 原始帧
        self.display_frame = None  # 显示帧

        # 视频显示标签
        self.frame_label = QLabel(self)
        self.frame_label.setFixedSize(1280, 720)
        self.frame_label.setMouseTracking(True)  # 启用鼠标移动追踪
        self.frame_label.mousePressEvent = self.handle_mouse_click  # 鼠标点击回调
        self.frame_label.mouseMoveEvent = self.handle_mouse_move  # 鼠标移动回调

        # 视频缩放比例（用于坐标转换）
        self.scale_x = 1.0
        self.scale_y = 1.0

        # 进度条
        self.progress_slider = QSlider(Qt.Horizontal)
        self.progress_slider.setRange(0, 1)
        self.progress_slider.sliderMoved.connect(self.slider_moved)

        # HSV 输入区域
        self.hsv_inputs = {}
        hsv_labels = ['H Min', 'S Min', 'V Min', 'H Max', 'S Max', 'V Max']
        hsv_keys = ['h_min', 's_min', 'v_min', 'h_max', 's_max', 'v_max']
        hsv_layout = QGridLayout()
        for i, (label, key) in enumerate(zip(hsv_labels, hsv_keys)):
            l = QLabel(label)
            e = QLineEdit(str(self.hsv_range[key]))
            e.setFixedWidth(40)
            self.hsv_inputs[key] = e
            hsv_layout.addWidget(l, 0 if i < 3 else 1, i % 3 * 2)
            hsv_layout.addWidget(e, 0 if i < 3 else 1, i % 3 * 2 + 1)
        for key, edit in self.hsv_inputs.items():
            edit.editingFinished.connect(self.on_hsv_input_change)
        self.hsv_checkbox = QCheckBox("HSV阈值显示")
        self.hsv_checkbox.stateChanged.connect(self.toggle_hsv_display)
        # # HSV 筛选预览
        # self.filtered_preview = QLabel("HSV筛选预览（前三个）")
        # self.filtered_preview.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        # self.filtered_preview.setFixedSize(200, 320)

        # # 全图预览按钮
        # self.full_preview_button = QPushButton("预览全部")
        # self.full_preview_button.clicked.connect(self.show_full_preview_dialog)

        self.last_event = None  # 上次鼠标事件

        # 放大镜预览标签
        self.magnifier_label = QLabel(self)
        self.magnifier_label.setFixedSize(200, 200)
        self.magnifier_label.setStyleSheet("border: 1px solid black;")
        self.magnifier_label.setAlignment(Qt.AlignCenter)

        # === 标注信息表格 ===
        self.table_widget = QTableWidget(self)
        self.table_widget.setColumnCount(3)
        self.table_widget.setHorizontalHeaderLabels(["点编号", "删除", "V"])
        self.table_widget.setColumnWidth(0, 100)
        self.table_widget.setColumnWidth(1, 100)
        self.table_widget.setColumnWidth(2, 100)
        # ② 让列宽随窗口撑满
        self.table_widget.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        # 行高根据内容自调
        self.table_widget.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

        # 滚动区域包装表格
        scroll_area = QScrollArea()
        scroll_area.setWidget(self.table_widget)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFixedHeight(200)

        # === 信息输入控件 ===
        self.video_id_input = QLineEdit()
        self.video_id_input.setPlaceholderText("请输入摄像头编号")
        self.add_type_input = QLineEdit()
        self.add_type_input.setPlaceholderText("请输入区域")
        self.id_input = QLineEdit()
        self.id_input.setPlaceholderText("请输入id(唯一)")
        self.url_type_input = QComboBox()
        self.url_type_input.addItem("http")
        self.url_type_input.addItem("rtsp")
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("请输入url")

        # 自动编号复选框
        self.auto_increment_checkbox = QCheckBox("自动填充编号")
        self.auto_increment_checkbox.stateChanged.connect(self.toggle_auto_increment)

        # 如果 video 对象已带有初始值，填入对应输入框
        if hasattr(self.video, 'video_id') and self.video.video_id:
            self.video_id_input.setText(self.video.video_id)
        if hasattr(self.video, 'add_type') and self.video.add_type:
            self.add_type_input.setText(self.video.add_type)
        if hasattr(self.video, 'id') and self.video.id:
            self.id_input.setText(str(self.video.id))

        # 操作按钮
        self.undo_button = QPushButton("撤回")
        self.clear_button = QPushButton("清除全部")
        self.confirm_button = QPushButton("确定")
        self.cancel_button = QPushButton("取消")

        # 描述标签
        self.description_label = QLabel()
        self.description_label.setWordWrap(True)

        # 操作按钮绑定函数
        self.undo_button.clicked.connect(self.undo_last_point)
        self.clear_button.clicked.connect(self.clear_all_points)
        self.confirm_button.clicked.connect(self.confirm_and_close)
        self.cancel_button.clicked.connect(self.cancel_and_close)

        # 左侧（视频+进度）布局
        layout = QVBoxLayout()
        layout.addWidget(self.frame_label)
        layout.addWidget(self.progress_slider)

        # 右侧（表单+控件）布局
        right_layout = QVBoxLayout()
        right_layout.addWidget(scroll_area)
        right_layout.addWidget(QLabel("摄像头编号："))
        right_layout.addWidget(self.video_id_input)
        right_layout.addWidget(QLabel("区域："))
        right_layout.addWidget(self.add_type_input)
        right_layout.addWidget(QLabel("id(唯一)："))
        right_layout.addWidget(self.id_input)
        right_layout.addWidget(QLabel("url"))
        right_layout.addWidget(self.url_input)
        right_layout.addWidget(QLabel("类型"))
        right_layout.addWidget(self.url_type_input)
        right_layout.addWidget(self.auto_increment_checkbox)
        right_layout.addLayout(hsv_layout)
        right_layout.addWidget(self.hsv_checkbox)

        # right_layout.addWidget(self.filtered_preview)
        # right_layout.addWidget(self.full_preview_button)
        right_layout.addWidget(self.undo_button)
        right_layout.addWidget(self.clear_button)
        right_layout.addWidget(self.confirm_button)
        right_layout.addWidget(self.cancel_button)
        right_layout.addWidget(self.description_label)
        right_layout.addStretch()

        # 主布局
        main_layout = QHBoxLayout()
        main_layout.addLayout(layout)
        main_layout.addLayout(right_layout)
        self.setLayout(main_layout)
        self.frames = []  # 存储每秒采集到的帧
        # === 启动采集线程 ===
        self.capture_thread = FrameCaptureThread(self.video)
        self.capture_thread.frame_captured.connect(self.handle_new_frame)
        self.capture_thread.start()
        # 加载原始标注和初始帧
        self.load_annotations()
        self.update_description()
        self.update_frame()

    def on_hsv_input_change(self):
        for k, edit in self.hsv_inputs.items():
            try:
                self.hsv_range[k] = int(edit.text())
            except ValueError:
                return
        if self.hsv_checkbox.isChecked():
            self.update_frame()

    def toggle_hsv_display(self, state):
        self.update_frame()

    def resizeEvent(self, event):
        """窗口大小变化时自动调整控件尺寸/字体。"""
        scale = min(self.width()/self.base_w, self.height()/self.base_h)
        rescale_widgets(self, scale)        # 调整当前窗口及子控件
        super().resizeEvent(event)

    def handle_new_frame(self, frame):
        self.frames.append(frame)
        # 第一次设置滑动条范围（只做一次）
        if len(self.frames) == 1:
            self.progress_slider.setRange(0, len(self.frames)-1)  # 或 len(self.frames)-1
            self.update_frame()
        if len(self.frames) > 100:
            self.frames.pop(0)
        self.progress_slider.setRange(0,len(self.frames)-1)


    def update_magnifier_position(self, event):
        """
        根据鼠标位置更新放大镜标签的位置
        """
        # 获取鼠标的位置
        x = event.pos().x()
        y = event.pos().y()
        # 将放大镜位置设置为鼠标位置附近
        self.magnifier_label.move(x-90 , y - 170)  # 设置放大镜标签在鼠标右下方（可以调整偏移量）

    def update_table(self):
        """
        根据当前 annotation_data 刷新表格内容：
        - 列 0：点编号
        - 列 1：删除按钮
        - 列 2：V 列，显示 (x, y) 坐标
        """
        self.table_widget.setRowCount(len(self.annotation_data))

        if self.annotation_type == "yarn":
            # 因为 dict 在 PyQt <5.15 中不保证插入顺序，可先排序一下键
            for row, (label, (x, y)) in enumerate(sorted(self.annotation_data.items(),
                                                         key=lambda kv: int(kv[0]) if kv[0].isdigit() else kv[0])):
                # ── 列 0：编号 ───────────────────────────
                item_label = QTableWidgetItem(label)
                item_label.setTextAlignment(Qt.AlignCenter)
                self.table_widget.setItem(row, 0, item_label)

                # ── 列 1：删除按钮 ───────────────────────
                btn_delete = QPushButton("删除")
                # 注意 lambda 默认绑定晚；用缺省参数锁定当前 label
                btn_delete.clicked.connect(lambda _, lbl=label: self.delete_annotation(lbl))
                self.table_widget.setCellWidget(row, 1, btn_delete)

                # ── 列 2：坐标显示 / V 列 ─────────────────
                item_coord = QTableWidgetItem(f"({x}, {y})")
                item_coord.setTextAlignment(Qt.AlignCenter)
                self.table_widget.setItem(row, 2, item_coord)

        else:  # 激光类只有一个点
            for row, (x, y) in enumerate(self.annotation_data):
                self.table_widget.setItem(row, 0, QTableWidgetItem(str(row + 1)))

                btn_delete = QPushButton("删除")
                btn_delete.clicked.connect(lambda _, idx=row: self.clear_all_points())
                self.table_widget.setCellWidget(row, 1, btn_delete)

                self.table_widget.setItem(row, 2, QTableWidgetItem(f"({x}, {y})"))

        # ── 让行高列宽根据内容自动调整 ───────────────
        self.table_widget.resizeColumnsToContents()
        self.table_widget.resizeRowsToContents()

    def update_table(self):
        """
        更新表格内容，当标注点添加时更新表格显示。
        """
        self.table_widget.setRowCount(len(self.annotation_data))
        if self.annotation_type == "yarn":
            for row, (label, point) in enumerate(self.annotation_data.items()):
                self.table_widget.setItem(row, 0, QTableWidgetItem(label))
                # 创建删除按钮
                delete_button = QPushButton("删除")
                delete_button.clicked.connect(lambda checked, label=label: self.delete_annotation(label))
                self.table_widget.setCellWidget(row, 1, delete_button)


    def delete_annotation(self, label):
        """
        删除指定点的标注数据，并更新表格。
        """
        # 从标注数据中删除
        if label in self.annotation_data:
            del self.annotation_data[label]
            self.update_frame()  # 更新画面




    def toggle_auto_increment(self, state):
        self.auto_increment = state == Qt.Checked

    def update_description(self):
        if self.annotation_type == "yarn":
            self.description_label.setText("纱线亮点标注：可以标注多个点。")
        elif self.annotation_type == "laser_emitter":
            self.description_label.setText("激光发射器亮点标注：只允许标注一个点。")
        elif self.annotation_type == "laser_wall":
            self.description_label.setText("激光照射墙壁亮点标注：只允许标注一个点。")

    def update_frame(self):
        # 读取帧并处理
        if self.frame_index>=len(self.frames):
            return
        frame=self.frames[self.frame_index]
        if self.hsv_checkbox.isChecked():
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            lower = np.array([self.hsv_range['h_min'], self.hsv_range['s_min'], self.hsv_range['v_min']])
            upper = np.array([self.hsv_range['h_max'], self.hsv_range['s_max'], self.hsv_range['v_max']])
            mask = cv2.inRange(hsv, lower, upper)
            mask_bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
            self.video_frame = mask_bgr.copy()
            self.display_frame = cv2.resize(mask_bgr, (1280, 720))
        else:
            self.display_frame = cv2.resize(frame, (1280, 720))
            self.video_frame = frame.copy()

        self.scale_x = frame.shape[1] / 1280
        self.scale_y = frame.shape[0] / 720
        # 根据标注类型进行绘制
        if self.annotation_type == "yarn":
            # for label, (real_x, real_y) in self.annotation_data.items():
            #     crop = frame[max(0, real_y - self.half_h):real_y + self.half_h, max(0, real_x - self.half_w):real_x + self.half_w]
            #     self.cropped_images[label] = crop
            for label, point in self.annotation_data.items():
                x, y = int(point[0] / self.scale_x), int(point[1] / self.scale_y)
                top_left = (x - self.half_w, y - self.half_h)
                bottom_right = (x + self.half_w, y + self.half_h)
                cv2.rectangle(self.display_frame, top_left, bottom_right, (0, 255, 0), 1)
                cv2.putText(self.display_frame, label, (x + 5, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        else:
            for point in self.annotation_data:

                x, y = int(point[0] / self.scale_x), int(point[1] / self.scale_y)
                top_left = (x - self.half_w, y - self.half_h)
                bottom_right = (x + self.half_w, y + self.half_h)
                cv2.rectangle(self.display_frame, top_left, bottom_right, (0, 255, 0), 1)
        # 将处理后的帧显示到界面上
        image = QImage(self.display_frame.data, self.display_frame.shape[1], self.display_frame.shape[0],
                             self.display_frame.strides[0], QImage.Format_BGR888)
        self.frame_label.setPixmap(QPixmap.fromImage(image))
        self.update_table()


    def show_magnifier(self, event):
        # 获取放大镜区域
        x = event.pos().x()
        y = event.pos().y()
        real_x = int(x * self.scale_x)
        real_y = int(y * self.scale_y)

        crop = self.video_frame[max(0, real_y - self.half_h):real_y + self.half_h, max(0, real_x - self.half_w):real_x + self.half_w]

        magnified_crop = cv2.resize(crop, (100, 100))
        magnified_image = QImage(magnified_crop.data, magnified_crop.shape[1], magnified_crop.shape[0],
                                       magnified_crop.strides[0], QImage.Format_BGR888)

        self.magnifier_label.setPixmap(QPixmap.fromImage(magnified_image))

        # 设置鼠标为十字形
        self.setCursor(Qt.CrossCursor)

    def toggle_auto_increment(self, state):
        self.auto_increment = state == Qt.Checked

    def slider_moved(self, value):
        self.frame_index = value
        self.update_frame()


    def handle_mouse_move(self, event):
        """
        鼠标移动事件处理
        实时更新放大镜区域
        """
        self.last_event = event  # 保存事件
        self.update_magnifier(event)  # 更新放大镜效果区域
        self.update_magnifier_position(event)  # 更新放大镜的位置


    def update_magnifier(self, event):
        if self.video_frame is None:
            return
        # 获取鼠标的位置并计算放大镜区域
        x = event.pos().x()
        y = event.pos().y()
        real_x = int(x * self.scale_x)
        real_y = int(y * self.scale_y)

        # 获取放大镜区域（从鼠标位置开始，大小为 `2 * self.half`）
        crop = self.video_frame[max(0, real_y - self.half_h):real_y + self.half_h, max(0, real_x - self.half_w):real_x + self.half_w]
        # 放大镜效果
        magnified_crop = cv2.resize(crop, (200, 200))

        # 在放大镜区域绘制十字
        center_x, center_y = magnified_crop.shape[1] // 2, magnified_crop.shape[0] // 2
        cross_size = 20  # 十字的大小

        # 画水平线
        cv2.line(magnified_crop, (center_x - cross_size, center_y), (center_x + cross_size, center_y), (0, 0, 255), 2)
        # 画垂直线
        cv2.line(magnified_crop, (center_x, center_y - cross_size), (center_x, center_y + cross_size), (0, 0, 255), 2)

        # 将修改后的放大镜图像转化为 Qt 图像
        magnified_image = QImage(magnified_crop.data, magnified_crop.shape[1], magnified_crop.shape[0],
                                       magnified_crop.strides[0], QImage.Format_BGR888)

        # 更新放大镜标签
        self.magnifier_label.setPixmap(QPixmap.fromImage(magnified_image))

        # 设置鼠标为十字形
        self.setCursor(Qt.CrossCursor)

    def handle_mouse_click(self, event):
        if self.annotation_type in ["laser_emitter", "laser_wall"] and len(self.annotation_data) >= 1:
            return

        x = event.pos().x()
        y = event.pos().y()
        real_x = int(x * self.scale_x)
        real_y = int(y * self.scale_y)
        if self.annotation_type == "yarn":
            if self.auto_increment:
                label = str(self.auto_id_counter)
                self.auto_id_counter += 1
            else:
                text, ok = QInputDialog.getText(self, "编号输入", "请输入该点编号：")
                if not ok or not text.strip():
                    return
                label = text.strip()
                self.auto_id_counter=int(label)+1
            self.annotation_data[label] = (real_x, real_y)
            # crop = self.video_frame[max(0, real_y - self.half_h):real_y + self.half_h, max(0, real_x - self.half_w):real_x + self.half_w]
            # self.cropped_images[label] = crop
            # 裁剪图像并进行 HSV 筛选
            # self.update_hsv_preview()


        else:
            self.annotation_data = [(real_x, real_y)]
        self.update_frame()

    # def update_hsv_preview(self):
    #     if not self.cropped_images:
    #         return
    #
    #     try:
    #         for k in self.hsv_inputs:
    #             self.hsv_range[k] = int(self.hsv_inputs[k].text())
    #     except:
    #         return
    #     previews = []
    #     for crop in list(self.cropped_images.values())[:4]:
    #         hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    #         lower = np.array([self.hsv_range['h_min'], self.hsv_range['s_min'], self.hsv_range['v_min']])
    #         upper = np.array([self.hsv_range['h_max'], self.hsv_range['s_max'], self.hsv_range['v_max']])
    #         mask = cv2.inRange(hsv, lower, upper)
    #         preview = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
    #         preview = cv2.resize(preview, (100, 100))
    #         previews.append(preview)
    #
    #     if previews:
    #         rows = (len(previews) + 1) // 2
    #         result = np.ones((rows * 100, 2 * 100, 3), dtype=np.uint8) * 255
    #         for idx, p in enumerate(previews):
    #             row, col = divmod(idx, 2)
    #             result[row * 100:(row + 1) * 100, col * 100:(col + 1) * 100] = p
    #
    #         image = QImage(result.data, result.shape[1], result.shape[0],
    #                              result.strides[0], QImage.Format_BGR888)
    #         self.filtered_preview.setPixmap(QPixmap.fromImage(image))

    def undo_last_point(self):
        if self.annotation_type == "yarn" and self.annotation_data:
            last_key = list(self.annotation_data.keys())[-1]
            self.annotation_data.pop(last_key)
            self.auto_id_counter = int(last_key) if last_key.isdigit() else self.auto_id_counter
        elif self.annotation_type in ["laser_emitter", "laser_wall"] and self.annotation_data:
            self.annotation_data = []
        self.update_frame()

    def clear_all_points(self):
        self.annotation_data = {} if self.annotation_type == "yarn" else []
        if self.annotation_type == "yarn":
            self.auto_id_counter = 1
        self.update_frame()

    def confirm_and_close(self):
        self.video.hsv_lower = np.array([self.hsv_range['h_min'], self.hsv_range['s_min'], self.hsv_range['v_min']])
        self.video.hsv_upper = np.array([self.hsv_range['h_max'], self.hsv_range['s_max'], self.hsv_range['v_max']])
        self.video.video_id = self.video_id_input.text()
        self.video.add_type = self.add_type_input.text()
        self.video.id = self.id_input.text()
        url_type=self.url_type_input.currentText()
        url=self.url_input.text()
        width = self.video.frame_width
        height = self.video.frame_height

        yaml_path = self.video.yaml_path
        data_to_save = {}
        if os.path.exists(yaml_path):
            try:
                with open(yaml_path, 'r') as f:
                    data_to_save = yaml.safe_load(f) or {}
            except Exception as e:
                print("YAML读取失败：", e)
                data_to_save = {}

        if self.annotation_type == "yarn":
            self.video.xian_points={}
            normalized_data = {}
            for idx,(x,y) in self.annotation_data.items():
                x1 = max(x - self.half_w, 0)
                y1 = max(y - self.half_h, 0)
                x2 = min(x + self.half_w, width - 1)
                y2 = min(y + self.half_h, height - 1)
                self.video.xian_points[idx] = (x,y,x1, y1, x2, y2)
                normalized_data[idx] = [x / width, y / height]
            # self.video.xian_points = self.annotation_data.copy()
            data_to_save[self.annotation_type] = normalized_data
        elif self.annotation_type == "laser_emitter":
            self.video.laser_emitter=[]
            normalized_data = []
            for x,y in self.annotation_data:
                x1 = max(x - self.half_w, 0)
                y1 = max(y - self.half_h, 0)
                x2 = min(x + self.half_w, width - 1)
                y2 = min(y + self.half_h, height - 1)
                self.video.laser_emitter.append([x,y,x1, y1, x2, y2])
                normalized_data.append([x / width, y / height])
            # self.video.laser_emitter = self.annotation_data.copy()
            data_to_save[self.annotation_type] = normalized_data
        elif self.annotation_type == "laser_wall":
            self.video.laser_wall=[]
            normalized_data = []
            for x,y in self.annotation_data:
                x1 = max(x - self.half_w, 0)
                y1 = max(y - self.half_h, 0)
                x2 = min(x + self.half_w, width - 1)
                y2 = min(y + self.half_h, height - 1)
                self.video.laser_wall.append([x,y,x1, y1, x2, y2])
                normalized_data.append([x / width, y / height])
            # self.video.laser_wall = self.annotation_data.copy()
            data_to_save[self.annotation_type] = normalized_data
        data_to_save['video_id'] = self.video.video_id
        data_to_save['add_type'] = self.video.add_type
        data_to_save['hsv_range'] = self.hsv_range
        data_to_save['id'] = self.video.id
        data_to_save['video_type'] = url_type
        data_to_save['video_url'] = url
        with open(yaml_path, 'w') as f:
            yaml.safe_dump(data_to_save, f)

        self.accept()
        self.capture_thread.stop()
        self.capture_thread.wait()

    # def show_full_preview_dialog(self):
    #     if not self.cropped_images:
    #         return
    #
    #     try:
    #         for k in self.hsv_inputs:
    #             self.hsv_range[k] = int(self.hsv_inputs[k].text())
    #     except:
    #         return
    #
    #     previews = []
    #     for crop in self.cropped_images.values():
    #         hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    #         lower = np.array([self.hsv_range['h_min'], self.hsv_range['s_min'], self.hsv_range['v_min']])
    #         upper = np.array([self.hsv_range['h_max'], self.hsv_range['s_max'], self.hsv_range['v_max']])
    #         mask = cv2.inRange(hsv, lower, upper)
    #         preview = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
    #         preview = cv2.resize(preview, (100, 100))
    #         previews.append(preview)
    #
    #     if not previews:
    #         return
    #
    #     columns = 4
    #     rows = (len(previews) + columns - 1) // columns
    #     result = np.ones((rows * 100, columns * 100, 3), dtype=np.uint8) * 255
    #     for idx, p in enumerate(previews):
    #         row, col = divmod(idx, columns)
    #         result[row * 100:(row + 1) * 100, col * 100:(col + 1) * 100] = p
    #
    #     image = QImage(result.data, result.shape[1], result.shape[0],
    #                          result.strides[0], QImage.Format_BGR888)
    #
    #     dialog = QDialog(self)
    #     dialog.setWindowTitle("全部二值图预览")
    #     scroll = QScrollArea()
    #     label = QLabel()
    #     label.setPixmap(QPixmap.fromImage(image))
    #     scroll.setWidget(label)
    #     scroll.setWidgetResizable(True)
    #
    #     layout = QVBoxLayout(dialog)
    #     layout.addWidget(scroll)
    #
    #     # 设置窗口大小，最多不超过 600x600，内容小则自适应
    #     width = min(result.shape[1] + 20, 600)
    #     height = min(result.shape[0] + 20, 600)
    #     dialog.resize(width, height)
    #     dialog.exec_()


    def cancel_and_close(self):
        self.canceled = True
        self.reject()
        self.capture_thread.stop()
        self.capture_thread.wait()

    def load_annotations(self):
        self.video.hsv_range = self.hsv_range.copy()
        yaml_path = self.video.yaml_path
        self.video.video_id = ""
        self.video.add_type = ""
        try:
            with open(yaml_path, 'r') as f:
                data = yaml.safe_load(f) or {}
                annotation_data = data.get(self.annotation_type, {} if self.annotation_type == "yarn" else [])
                if self.annotation_type == "yarn":
                    self.annotation_data={}
                    for idx,(x,y) in annotation_data.items():
                        if x<=1 and y<=1:
                            self.annotation_data[idx] = (int(x*self.video.frame_width), int(y*self.video.frame_height))
                        else:
                            self.annotation_data[idx] = (int(x), int(y))
                else:
                    self.annotation_data=[]
                    for x,y in annotation_data:
                        if x<=1 and y<=1:
                            self.annotation_data.append((int(x*self.video.frame_width), int(y*self.video.frame_height)))
                        else:
                            self.annotation_data.append((int(x), int(y)))
                self.video.video_id = data.get("video_id", "")
                self.video_id_input.setText(self.video.video_id)
                self.video.add_type = data.get("add_type", "")
                self.add_type_input.setText(self.video.add_type)
                self.video.id = data.get("id", "")
                self.id_input.setText(self.video.id)

                self.url_input.setText(data.get("video_url", ""))
                self.url_type_input.setCurrentText(data.get("video_type", ""))

                self.hsv_range = data.get("hsv_range", self.hsv_range)
                self.video.hsv_range = self.hsv_range.copy()
                for k in self.hsv_range:
                    self.hsv_inputs[k].setText(str(self.hsv_range[k]))
        except Exception as e:
            print("YAML读取失败：", e)
            self.annotation_data = {} if self.annotation_type == "yarn" else []

        if self.annotation_type == "yarn":
            # self.update_hsv_preview()
            keys = list(self.annotation_data.keys())
            numeric_keys = [int(k) for k in keys if k.isdigit()]
            if numeric_keys:
                self.auto_id_counter = max(numeric_keys) + 1


    def closeEvent(self, event):
        if hasattr(self, "capture_thread"):
            self.capture_thread.stop()
            self.capture_thread.wait()
        event.accept()


class ClickableLabel(QLabel):
    # 定义一个信号，在鼠标按下时发射
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        # 让 label 有“可点击”的感觉，比如加个边框，或 setCursor
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        # 当鼠标点击时，发射 clicked 信号
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        # 不要忘记调用父类事件，以免其他事件处理被阻断
        super().mousePressEvent(event)

def run_annotation_sequence(video):
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    for annotation_type in ["yarn", "laser_emitter", "laser_wall"]:
        dialog = VideoAnnotationDialog(video, annotation_type,settings.crap_w*2,settings.crap_h*2)
        dialog.exec_()
        if dialog.canceled:
            return False  # 用户点击取消，提前退出
    return True  # 全部完成


class YamlFileSelector(QDialog):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("选择 YAML 配置文件")
        self.setGeometry(100, 100, 400, 250)

        # 主布局
        layout = QVBoxLayout()

        # 标签显示选择的 YAML 文件路径
        self.file_path_label = QLabel("选择的 YAML 配置文件路径将显示在这里")
        layout.addWidget(self.file_path_label)

        # 选择文件按钮
        self.select_file_button = QPushButton("选择 YAML 文件")
        self.select_file_button.clicked.connect(self.select_yaml_file)
        layout.addWidget(self.select_file_button)

        # 添加 w 和 h 输入框部分
        input_layout = QHBoxLayout()

        self.width_label = QLabel("宽度 (w):")
        self.width_input = QLineEdit()
        self.width_input.setValidator(QIntValidator(0, 100))
        input_layout.addWidget(self.width_label)
        input_layout.addWidget(self.width_input)

        self.height_label = QLabel("高度 (h):")
        self.height_input = QLineEdit()
        self.height_input.setValidator(QIntValidator(0, 100))
        input_layout.addWidget(self.height_label)
        input_layout.addWidget(self.height_input)

        layout.addLayout(input_layout)

        # 确认和取消按钮
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)

        self.selected_file_path = ""  # 存储选择的文件路径

    def select_yaml_file(self):
        # 打开 YAML 文件选择对话框
        file, _ = QFileDialog.getOpenFileName(self, "选择 YAML 配置文件", "", "YAML 文件 (*.yaml *.yml)")
        if file:
            self.selected_file_path = file
            self.file_path_label.setText(f"选择的 YAML 文件路径：{file}")

    def get_selected_file_path(self):
        return self.selected_file_path

    def get_dimensions(self):
        width = self.width_input.text()
        height = self.height_input.text()
        if width.isdigit() and height.isdigit():
            return int(width), int(height)
        else:
            return 10, 10  # 默认值
def load_video_yaml(yaml_path):
    try:
        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        video_type = data.get("video_type", "")
        if video_type=='':
            print('video_type缺失')
            return None
        video_url=data.get("video_url", "")
        if video_url=='':
            print('video_url缺失')
            return None
        if video_type == "rtsp":
            video= Video(rtsp_url=video_url)
        elif video_type == "http":
            video= Video(http_url=video_url)
        else:
            print('未知类型')
            return None
        video.load_yaml(yaml_path)
        return video

    except Exception as e:
        print("load_yaml 解析失败：", e)
        return None
if __name__ == '__main__':
    app = QApplication([])  # 创建 QApplication 实例
    while True:
        window = YamlFileSelector()
        if window.exec_() == QDialog.Accepted:  # 用户点击 OK 按钮
            selected_file_path = window.get_selected_file_path()  # 获取选择的文件路径
            w,h=window.get_dimensions()
            settings.crap_h=h
            settings.crap_w=w
            print(f"选择的文件路径是: {selected_file_path}")
            video=load_video_yaml(selected_file_path)
            time.sleep(10)
            run_annotation_sequence(video)
            # run_annotation_sequence(Video(video_path=r"D:\BaiduNetdiskDownload\断纱判断\断纱特征\紫色\resize2\2024-11-07_11-29-49_0_fixed.mp4",start_t=False))
        else:
            break