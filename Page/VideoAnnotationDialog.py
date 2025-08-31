import os
import cv2
import yaml
import numpy as np
import time

from PyQt5.QtGui import QIntValidator,QFont,QImage,QPixmap
from PyQt5.QtWidgets import QLabel, QApplication, QTableWidget, QTableWidgetItem, QPushButton, QWidget, QVBoxLayout, \
    QFileDialog, QDialog, QDialogButtonBox, QHBoxLayout, QLineEdit, QHeaderView, QAbstractButton, QSlider, QGridLayout, \
    QScrollArea, QComboBox, QCheckBox, QInputDialog, QFrame, QSpinBox, QSizePolicy
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


class VideoLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_win = None  # 引用主窗口，用于事件回调
        self.setMouseTracking(True)          # ←★ 必须打开鼠标追踪

    def mousePressEvent(self, event):
        # 单击事件传递给主窗口处理
        if self.main_win:
            self.main_win.imageClicked(event)

    def mouseMoveEvent(self, event):
        # 鼠标移动事件用于更新放大镜显示
        if self.main_win:
            self.main_win.updateMagnifier(event)


class MoveLabelWindow(QDialog):
    def __init__(self, video:Video, yaml_path="annotations.yaml"):
        super().__init__()
        self.setWindowTitle("视频标注工具")
        # 初始化成员变量
        self.yaml_path = yaml_path
        self.contours_list = []   # 已记录的轮廓信息列表
        self.contour_count = 0    # 用于生成唯一轮廓ID
        self.current_frame = None
        self.original_frame = None  # 冻结帧的原始图像
        self.base_frame = None      # 带标注的图像
        self.was_running = False    # 点击时视频是否在播放

        main_layout = QHBoxLayout(self)  # ← 将布局直接加到 self 上

        # 左侧：视频显示区域
        self.video_label = VideoLabel()
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # 将主窗口引用传给VideoLabel，以便其事件方法调用主窗口对应处理
        self.video_label.main_win = self
        self.video_label.setMouseTracking(True)     # ←★ 双保险，写一行也无妨


        # 进度条
        self.progress_slider = QSlider(Qt.Horizontal)
        self.progress_slider.setRange(0, 0)
        self.progress_slider.sliderMoved.connect(self.slider_moved)

        left_layout = QVBoxLayout()
        left_layout.addWidget(self.video_label)      # 上：视频
        left_layout.addWidget(self.progress_slider)  # 下：进度条
        left_widget = QWidget()
        left_widget.setLayout(left_layout)

        main_layout.addWidget(left_widget)

        # 右侧：控制功能区
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        # 放大镜显示标签
        self.magnifier_label = QLabel("Magnifier")
        self.magnifier_label.setFixedSize(160, 160)
        self.magnifier_label.setFrameShape(QFrame.Box)
        self.magnifier_label.setLineWidth(1)
        self.magnifier_label.setStyleSheet("background-color: black;")
        right_layout.addWidget(self.magnifier_label, alignment=Qt.AlignCenter)
        # Canny阈值输入
        min_layout = QHBoxLayout()
        min_label = QLabel("Canny minVal:")
        self.min_spin = QSpinBox()
        self.min_spin.setRange(0, 255)
        self.min_spin.setValue(150)
        min_layout.addWidget(min_label)
        min_layout.addWidget(self.min_spin)
        right_layout.addLayout(min_layout)
        max_layout = QHBoxLayout()
        max_label = QLabel("Canny maxVal:")
        self.max_spin = QSpinBox()
        self.max_spin.setRange(0, 1000)
        self.max_spin.setValue(250)
        max_layout.addWidget(max_label)
        max_layout.addWidget(self.max_spin)
        right_layout.addLayout(max_layout)
        # 预览按钮
        self.preview_button = QPushButton("预览")
        self.preview_button.clicked.connect(self.previewContours)
        right_layout.addWidget(self.preview_button)
        # 表格显示已记录的轮廓列表
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Contour ID", "操作"])
        # 列宽策略：第一列填充，第二列根据内容调整
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        right_layout.addWidget(self.table)
        # 保存和取消按钮
        btn_layout = QHBoxLayout()
        self.save_button = QPushButton("保存")
        self.save_button.clicked.connect(self.saveContours)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self.cancelAnnotation)
        # ① 创建按钮
        self.close_button = QPushButton("关闭")
        self.close_button.clicked.connect(self.close)   # 直接调用 QMainWindow.close()
        btn_layout.addWidget(self.save_button)
        btn_layout.addWidget(self.cancel_button)
        btn_layout.addWidget(self.close_button)
        right_layout.addLayout(btn_layout)

        main_layout.addWidget(right_widget)
        # ============ 帧缓存 & 采集线程 ============
        self.frames = []                 # 收到的原始帧缓存
        self.frame_index = 0             # 当前在第几帧
        self.capture_thread = FrameCaptureThread(video)
        self.capture_thread.frame_captured.connect(self.handle_new_frame)
        self.capture_thread.start()

        # ==== 读取已有 YAML（只解析，不画）====
        self.contours_list.clear()

        if os.path.exists(self.yaml_path):
            try:
                with open(self.yaml_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
                # === 还原 Canny 阈值（若 YAML 中已保存） ===
                self.min_spin.setValue(int(data.get("canny_min", 150)))
                self.max_spin.setValue(int(data.get("canny_max", 250)))
                ann = data.get('click_annotations', {})
                for cid, info in ann.items():
                    click_xy  = info.get('click_xy',  [0.0, 0.0])
                    center_xy = info.get('center_xy', [0.0, 0.0])
                    size_wh   = info.get('size',      [0.0, 0.0])

                    self.contours_list.append({
                        'id'         : cid,
                        'click_point': tuple(click_xy),
                        'center'     : tuple(center_xy),
                        'size'       : tuple(size_wh),
                        'contour'    : None
                    })

                    # -------★ 解析现有 ID 序号，更新计数器 -------------
                    if cid.startswith("contour_"):
                        try:
                            num = int(cid.split("_")[1])
                            self.contour_count = max(self.contour_count, num)
                        except ValueError:
                            pass  # 非数字后缀，忽略
                    # -------------------------------------------------
                self.updateTable()         # ← 立刻刷新表格
            except Exception as e:
                print("读取 YAML 出错:", e)

    # ----------------------------------------
    # ❷ 采集线程送来一帧 → 加到列表并更新进度条
    # ----------------------------------------
    def handle_new_frame(self, frame):
        """采集线程把新帧送进来"""
        self.current_frame = frame
        self.frames.append(frame)
        # 第一次收到帧：立即显示 & 初始化进度条范围
        if len(self.frames) == 1:
            self.progress_slider.setRange(0, 0)
            self.update_frame()          # 把第0帧推到画面
        # 保留最近 300 帧即可（按2 s采集大约10 min）
        if len(self.frames) > 300:
            self.frames.pop(0)
            # 若 frame_index 被挤掉，回退到最新
            self.frame_index = max(0, len(self.frames) - 1)
        # 实时更新进度条最大值
        self.progress_slider.setRange(0, len(self.frames) - 1)
        # 如果当前停在最新帧（==max），就自动刷新画面
        if self.frame_index == len(self.frames) - 1:
            self.update_frame()

    def displayFrame(self, frame_bgr):
        """将给定的BGR图像显示到video_label上"""
        if frame_bgr is None or frame_bgr.size == 0:
            return
        show = cv2.resize(frame_bgr, (1280, 720))   # ←★ 新增
        rgb  = cv2.cvtColor(show, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch*w, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg)
        # 直接设置pixmap（假设label大小与图像尺寸接近，可按需缩放）
        self.video_label.setPixmap(pixmap)


    # ----------------------------------------
    # ❸ 进度条拖动：只改索引，不重新采集
    # ----------------------------------------
    def slider_moved(self, idx):
        self.frame_index = idx
        self.update_frame()


    # ----------------------------------------
    # ❹ update_frame：把 self.frames[self.frame_index] 画到 QLabel，
    #    并在其上叠加所有已记录的轮廓
    # ----------------------------------------
    def update_frame(self):
        if not self.frames:
            return
        frame = self.frames[self.frame_index]
        show  = frame.copy()

        img_h, img_w = frame.shape[:2]              # ← 用来反归一化

        for d in self.contours_list:
            if d['contour'] is not None:
                # 真 contour（运行期点击后才会有）
                cv2.drawContours(show, [d['contour']], -1, (0,0,255), 2)
                x, y, w, h = cv2.boundingRect(d['contour'])
            else:
                # 只有 center / size（全部是 0-1）
                cx_norm, cy_norm = d['center']
                w_norm,  h_norm  = d['size']

                cx = int(cx_norm * img_w)
                cy = int(cy_norm * img_h)
                w  = int(w_norm  * img_w)
                h  = int(h_norm  * img_h)

                x = cx - w // 2
                y = cy - h // 2
                cv2.rectangle(show, (x, y), (x + w, y + h), (0, 0, 255), 2)

            cv2.putText(show, d['id'], (x, max(0, y-5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,0,255), 1)
        # 缩放到固定显示区 sizeDisplay = (1280,720) 之类
        self.display_frame = cv2.resize(show,(1280,720))
        # 记录比例给放大镜/点击用
        self.scale_x = frame.shape[1] / 1280
        self.scale_y = frame.shape[0] / 720
        # 真正显示
        qimg = QImage(self.display_frame.data,
                            self.display_frame.shape[1],
                            self.display_frame.shape[0],
                            self.display_frame.strides[0],
                            QImage.Format_BGR888)
        self.video_label.setPixmap(QPixmap.fromImage(qimg))


    def imageClicked(self, event):
        """处理视频区域的鼠标点击事件"""
        # ===== 1. 基本有效性检查 ==========================================
        if not self.frames:                 # 还没有收到任何帧
            return

        # 取当前帧索引对应的原始帧 -------------------------------  ### FIX: 始终补 current_frame
        self.current_frame  = self.frames[self.frame_index]
        self.original_frame = self.frames[self.frame_index].copy()

        # self.base_frame 为空的情况：第一次点击或被误清空 ---------  ### FIX
        if self.base_frame is None:
            self.base_frame = self.current_frame.copy()

        # ===== 2. 把点击坐标从 QLabel 空间映射到图像坐标 =============
        lx = event.x();  ly = event.y()

        img_h, img_w = self.current_frame.shape[:2]
        label_w, label_h = self.video_label.width(), self.video_label.height()
        if label_w == 0 or label_h == 0:    # QLabel 还没成型
            return

        scale_x, scale_y = img_w / label_w, img_h / label_h
        img_x, img_y = int(lx * scale_x), int(ly * scale_y)
        img_x = max(0, min(img_x, img_w - 1))
        img_y = max(0, min(img_y, img_h - 1))

        # ===== 3. 灰度 → 模糊 → Canny → 轮廓 =======================
        img_proc = self.current_frame        # 已经是 copy 的，不再额外 copy

        gray = cv2.cvtColor(img_proc, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        min_val, max_val = self.min_spin.value(), self.max_spin.value()
        edges = cv2.Canny(gray, min_val, max_val)

        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            print("未找到任何轮廓")
            return

        # ===== 4. 找到包含点击点的轮廓 =============================
        target_contour = None
        for c in contours:
            if cv2.pointPolygonTest(c, (img_x, img_y), False) >= 0:
                target_contour = c
                break
        if target_contour is None:
            print("点击位置不在任何轮廓内")
            return

        # ===== 5. 记录轮廓信息 & 叠加到 base_frame =================
        x, y, w, h = cv2.boundingRect(target_contour)
        cx, cy     = x + w // 2, y + h // 2

        self.contour_count += 1
        contour_id = f"contour_{self.contour_count}"
        self.contours_list.append({
            'id':         contour_id,
            'click_point': (img_x, img_y),
            'center':     (cx, cy),
            'size':       (w, h),
            'contour':    target_contour
        })

        # ===== 6. 刷新界面 & 表格 ==================================
        self.displayFrame(self.base_frame)   # displayFrame 已加空值防御
        self.updateTable()
        self.update_frame()

    def updateMagnifier(self, event):
        """更新放大镜显示（显示鼠标附近的图像局部放大，并在中心画十字）"""
        if self.current_frame is None:
            return

        # === 1. 计算 ROI ===
        lx, ly = event.x(), event.y()
        img_h, img_w = self.current_frame.shape[:2]
        label_w, label_h = self.video_label.width(), self.video_label.height()
        if label_w == 0 or label_h == 0:
            return

        scale_x, scale_y = img_w / label_w, img_h / label_h
        img_x, img_y = int(lx * scale_x), int(ly * scale_y)

        region = 20                           # ROI 半径（像素）
        x0, y0 = max(0, img_x - region), max(0, img_y - region)
        x1, y1 = min(img_w, img_x + region), min(img_h, img_y + region)
        roi = self.current_frame[y0:y1, x0:x1]
        if roi.size == 0:
            return

        # === 2. 放大 ROI ===
        zoom_factor = 4
        zh, zw = roi.shape[0] * zoom_factor, roi.shape[1] * zoom_factor
        zoom_img = cv2.resize(roi, (zw, zh), interpolation=cv2.INTER_NEAREST)

        # === 3. 在中心绘制十字 ====================================
        cx, cy = zw // 2, zh // 2            # 放大后图像中心
        cross_len = min(zw, zh) // 8         # 十字臂长，可自行调整
        cv2.line(zoom_img, (cx - cross_len, cy), (cx + cross_len, cy), (0, 0, 255), 2)
        cv2.line(zoom_img, (cx, cy - cross_len), (cx, cy + cross_len), (0, 0, 255), 2)
        # ========================================================

        # === 4. 转 QPixmap 显示 ===
        rgb_zoom = cv2.cvtColor(zoom_img, cv2.COLOR_BGR2RGB)
        h2, w2, ch2 = rgb_zoom.shape
        qimg_zoom = QImage(rgb_zoom.data, w2, h2, ch2 * w2, QImage.Format_RGB888)
        pixmap_zoom = QPixmap.fromImage(qimg_zoom)
        pixmap_zoom = pixmap_zoom.scaled(self.magnifier_label.size(),
                                         Qt.KeepAspectRatio,
                                         Qt.FastTransformation)
        self.magnifier_label.setPixmap(pixmap_zoom)


    def previewContours(self):
        """根据当前阈值执行边缘检测，并以弹窗显示所有轮廓"""
        if self.current_frame is None:
            return
        # 使用当前原始帧进行边缘检测
        img = self.original_frame.copy() if self.original_frame is not None else self.current_frame.copy()
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5,5), 0)
        min_val = self.min_spin.value()
        max_val = self.max_spin.value()
        edges = cv2.Canny(gray, min_val, max_val)
        contours, _ = cv2.findContours(edges.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        # 在副本图像上绘制所有轮廓
        preview_img = img.copy()
        cv2.drawContours(preview_img, contours, -1, (0,255,0), 1)
        # 弹出窗口显示预览图像
        preview_dialog = QDialog(self)
        preview_dialog.setWindowTitle("边缘检测预览")
        vbox = QVBoxLayout(preview_dialog)
        label = QLabel()
        rgb_prev = cv2.cvtColor(preview_img, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_prev.shape
        qimg_prev = QImage(rgb_prev.data, w, h, ch*w, QImage.Format_RGB888)
        pixmap_prev = QPixmap.fromImage(qimg_prev)
        label.setPixmap(pixmap_prev)
        vbox.addWidget(label)
        preview_dialog.exec_()

    def updateTable(self):
        """更新表格中的轮廓列表显示"""
        self.table.setRowCount(len(self.contours_list))
        for i, data in enumerate(self.contours_list):
            cid = data['id']
            # 第一列显示轮廓ID
            item = QTableWidgetItem(cid)
            item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)  # 设为不可编辑
            self.table.setItem(i, 0, item)
            # 第二列放置删除按钮
            btn = QPushButton("删除")
            btn.clicked.connect(lambda checked, contour_id=cid: self.removeContour(contour_id))
            self.table.setCellWidget(i, 1, btn)
        self.table.resizeRowsToContents()

    def removeContour(self, contour_id):
        """从记录中删除指定ID的轮廓标注"""
        removed = None
        for idx, data in enumerate(self.contours_list):
            if data['id'] == contour_id:
                removed = self.contours_list.pop(idx)
                break
        if removed is None:
            return
        # 更新表格显示
        self.updateTable()
        self.update_frame()



    def saveContours(self):
        """把 contours_list 全部以 0‒1 归一化格式写回 YAML"""
        if self.current_frame is None:
            print("当前没有可保存的帧")
            return
        img_h, img_w = self.current_frame.shape[:2]

        # 1) 读取旧文件，保留其它字段
        data = {}
        if os.path.exists(self.yaml_path):
            try:
                with open(self.yaml_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
            except Exception as e:
                print("读取 YAML 出错:", e)

        # 2) 整理归一化后的 annotations
        annotations = {}
        for entry in self.contours_list:
            # --- 像素 → 归一化（已是 0‒1 的保持不变） ---
            def norm(val, dim):
                return val if val <= 1.0 else val / dim      # 容错：<=1 视为已归一化
            click_xn = norm(entry['click_point'][0], img_w)
            click_yn = norm(entry['click_point'][1], img_h)

            cx_norm  = norm(entry['center'][0],    img_w)
            cy_norm  = norm(entry['center'][1],    img_h)

            w_norm   = norm(entry['size'][0],      img_w)
            h_norm   = norm(entry['size'][1],      img_h)

            annotations[entry['id']] = {
                'click_xy' : [round(click_xn, 6), round(click_yn, 6)],
                'center_xy': [round(cx_norm, 6),  round(cy_norm, 6)],
                'size'     : [round(w_norm, 6),   round(h_norm, 6)]
            }

        data['click_annotations'] = annotations

        # === 保存 Canny 阈值到 YAML 顶层 ===
        data['canny_min'] = int(self.min_spin.value())
        data['canny_max'] = int(self.max_spin.value())
        # 3) 写回文件
        try:
            with open(self.yaml_path, 'w', encoding='utf-8') as f:
                yaml.safe_dump(data, f, allow_unicode=True)
            print("标注已保存（坐标已归一化）→", self.yaml_path)
        except Exception as e:
            print("写入 YAML 出错:", e)


    def cancelAnnotation(self):
        """取消标注，退出或恢复视频播放"""
        if self.was_running:
            # 如果进入标注前视频在播放，则恢复播放
            self.timer.start(30)
            self.was_running = False
        # 这里可以选择关闭窗口或仅退出标注模式
        # 为简单起见，直接关闭程序
        self.close()

def run_annotation_sequence(video):
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    for annotation_type in ["yarn", "laser_emitter", "laser_wall"]:
        dialog = VideoAnnotationDialog(video, annotation_type,settings.crap_w*2,settings.crap_h*2)
        dialog.exec_()
        if dialog.canceled:
            return False  # 用户点击取消，提前退出
    win = MoveLabelWindow(video, video.yaml_path)
    win.exec_()  # 阻塞，直到用户关闭
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