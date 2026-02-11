import os
import cv2
import yaml
import numpy as np
import time

from PyQt5.QtGui import QIntValidator,QFont,QImage,QPixmap
from PyQt5.QtWidgets import QLabel, QApplication, QTableWidget, QTableWidgetItem, QPushButton, QWidget, QVBoxLayout, \
    QFileDialog, QDialog, QDialogButtonBox, QHBoxLayout, QLineEdit, QHeaderView, QAbstractButton, QSlider, QGridLayout, \
    QScrollArea, QComboBox, QCheckBox, QInputDialog, QFrame, QSpinBox, QSizePolicy, QRadioButton
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
    def __init__(self, video: Video, half_w=8, half_h=8):
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
        # self.annotation_type = annotation_type
        self.annotation_data = []
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

        self.last_event = None  # 上次鼠标事件

        # 放大镜预览标签
        self.magnifier_label = QLabel(self)
        self.magnifier_label.setFixedSize(200, 200)
        self.magnifier_label.setStyleSheet("border: 1px solid black;")
        self.magnifier_label.setAlignment(Qt.AlignCenter)

        # === 标注信息表格 ===
        self.table_widget = QTableWidget(self)
        self.table_widget.setColumnCount(3)
        self.table_widget.setHorizontalHeaderLabels(["点编号", "类型", "删除"])

        self.table_widget.setColumnWidth(0, 100)
        self.table_widget.setColumnWidth(1, 100)
        self.table_widget.setColumnWidth(2, 100)
        # ② 让列宽随窗口撑满
        self.table_widget.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        # 行高根据内容自调
        self.table_widget.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._table_syncing = False
        self.table_widget.itemChanged.connect(self.on_table_item_changed)

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

        # 添加单选按钮
        self.radio_yarn = QRadioButton("纱线")
        self.radio_emitter = QRadioButton("激光发射器")
        self.radio_wall = QRadioButton("激光墙壁")
        self.radio_yarn.setChecked(True)  # 默认选中纱线模式
        # 将单选按钮加入布局
        radio_layout = QHBoxLayout()
        radio_layout.addWidget(QLabel("标注类型："))
        radio_layout.addWidget(self.radio_yarn)
        radio_layout.addWidget(self.radio_emitter)
        radio_layout.addWidget(self.radio_wall)
        # 连接切换事件
        self.radio_yarn.toggled.connect(self.on_type_change)
        self.radio_emitter.toggled.connect(self.on_type_change)
        self.radio_wall.toggled.connect(self.on_type_change)

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
        right_layout.addLayout(radio_layout)

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

    def on_type_change(self):
        if self.radio_yarn.isChecked():
            self.current_type = "yarn"
        elif self.radio_emitter.isChecked():
            self.current_type = "laser_emitter"
        elif self.radio_wall.isChecked():
            self.current_type = "laser_wall"
        self.update_description()
        # 非纱线模式下禁用自动编号选项
        self.auto_increment_checkbox.setEnabled(self.current_type == "yarn")


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

        type_map = {"yarn": "纱线", "laser_emitter": "激光发射器", "laser_wall": "激光墙壁"}
        self.table_widget.setRowCount(len(self.annotation_data))
        for row, ann in enumerate(self.annotation_data):
            print(ann)
            # 点编号列
            item_id = QTableWidgetItem(str(ann['id']))
            item_id.setTextAlignment(Qt.AlignCenter)
            item_id.setFlags(item_id.flags() | Qt.ItemIsEditable)
            self.table_widget.setItem(row, 0, item_id)
            # 类型列
            item_type = QTableWidgetItem(type_map.get(ann['type'], ann['type']))
            item_type.setTextAlignment(Qt.AlignCenter)
            self.table_widget.setItem(row, 1, item_type)
            # 删除按钮列
            btn_delete = QPushButton("删除")
            btn_delete.clicked.connect(lambda _, r=row: self.delete_annotation(r))
            self.table_widget.setCellWidget(row, 2, btn_delete)

        # ── 让行高列宽根据内容自动调整 ───────────────
        self.table_widget.resizeColumnsToContents()
        self.table_widget.resizeRowsToContents()

    def on_table_item_changed(self, item: QTableWidgetItem):
        if self._table_syncing:
            return
        if item.column() != 0:
            return
        row = item.row()
        if row < 0 or row >= len(self.annotation_data):
            return

        new_id = item.text().strip()
        if not new_id:
            self._table_syncing = True
            item.setText(str(self.annotation_data[row].get("id", "")))
            self._table_syncing = False
            return

        ann = self.annotation_data[row]
        if ann.get("type") == "yarn":
            for idx, other in enumerate(self.annotation_data):
                if idx != row and other.get("type") == "yarn" and str(other.get("id")) == new_id:
                    self._table_syncing = True
                    item.setText(str(ann.get("id", "")))
                    self._table_syncing = False
                    return

        ann["id"] = new_id
        self.update_frame()


    def delete_annotation(self, row_index: int):
        """
        删除指定行索引对应的标注点，并更新界面。
        """
        if 0 <= row_index < len(self.annotation_data):
            del self.annotation_data[row_index]
            # 刷新画面和表格
            self.update_frame()
            self.update_table()

    def toggle_auto_increment(self, state):
        self.auto_increment = state == Qt.Checked

    def update_description(self):
        self.description_label.setText("纱线亮点标注：可以标注多个点。")
    #     if self.annotation_type == "yarn":
    #         self.description_label.setText("纱线亮点标注：可以标注多个点。")
    #     elif self.annotation_type == "laser_emitter":
    #         self.description_label.setText("激光发射器亮点标注：只允许标注一个点。")
    #     elif self.annotation_type == "laser_wall":
    #         self.description_label.setText("激光照射墙壁亮点标注：只允许标注一个点。")

    def update_frame(self):
        # 1) 取帧与空帧保护
        if not self.frames or self.frame_index < 0 or self.frame_index >= len(self.frames):
            return
        frame = self.frames[self.frame_index]

        # 2) HSV 显示或原始显示
        if self.hsv_checkbox.isChecked():
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            lower = np.array([self.hsv_range['h_min'],
                              self.hsv_range['s_min'],
                              self.hsv_range['v_min']], dtype=np.uint8)
            upper = np.array([self.hsv_range['h_max'],
                              self.hsv_range['s_max'],
                              self.hsv_range['v_max']], dtype=np.uint8)
            mask = cv2.inRange(hsv, lower, upper)
            show = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
            self.video_frame = show.copy()
        else:
            show = frame.copy()
            self.video_frame = frame.copy()

        # 3) 先缩放到固定显示区，再记录比例（原始→显示 的比例）
        disp_w, disp_h = 1280, 720
        self.display_frame = cv2.resize(show, (disp_w, disp_h))
        self.scale_x = frame.shape[1] / disp_w
        self.scale_y = frame.shape[0] / disp_h

        # 4) 颜色映射
        color_map = {
            "yarn": (0, 255, 0),  # 绿
            "laser_emitter": (0, 0, 255),  # 红
            "laser_wall": (255, 0, 0)  # 蓝
        }

        # 5) 统一列表绘制（内部坐标为像素坐标）
        self._table_syncing = True
        for ann in getattr(self, "annotation_data", []):
            ann_type = ann.get("type", "yarn")
            color = color_map.get(ann_type, (0, 255, 0))

            # 原始像素坐标 -> 显示坐标
            x_pix, y_pix = ann.get("coords", (0, 0))
            x_disp = int(x_pix / self.scale_x)
            y_disp = int(y_pix / self.scale_y)

            # 矩形框（half_w/half_h 为半宽半高，单位像素的“原图尺度”；
            # 这里我们已在显示尺度上作图，直接用 half_w/half_h）
            tl = (x_disp - self.half_w, y_disp - self.half_h)
            br = (x_disp + self.half_w, y_disp + self.half_h)
            cv2.rectangle(self.display_frame, tl, br, color, 1)

            # 标注文字
            if ann_type == "yarn":
                label = str(ann.get("id", ""))
            else:
                # 两个激光类只显示编号 1
                label = "1"
            cv2.putText(self.display_frame, label, (x_disp + 5, max(0, y_disp - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, lineType=cv2.LINE_AA)

        # 6) 显示到 QLabel
        qimg = QImage(self.display_frame.data,
                      self.display_frame.shape[1],
                      self.display_frame.shape[0],
                      self.display_frame.strides[0],
                      QImage.Format_BGR888)
        self.frame_label.setPixmap(QPixmap.fromImage(qimg))

        # 7) 刷新右侧表格
        self.update_table()
        self._table_syncing = False

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
        # 1) 当前模式（默认回退到 yarn）
        ann_type = getattr(self, "current_type", None)
        if ann_type not in ("yarn", "laser_emitter", "laser_wall"):
            ann_type = "yarn"

        # 2) 将显示坐标 -> 原图像素坐标，并做边界夹紧
        x_disp, y_disp = event.pos().x(), event.pos().y()
        real_x = int(x_disp * self.scale_x)
        real_y = int(y_disp * self.scale_y)
        # 若尚未获取到视频尺寸，做保护
        width = getattr(self.video, "frame_width", 0) or (self.frames[0].shape[1] if self.frames else 0)
        height = getattr(self.video, "frame_height", 0) or (self.frames[0].shape[0] if self.frames else 0)
        if width > 0 and height > 0:
            real_x = max(0, min(real_x, width - 1))
            real_y = max(0, min(real_y, height - 1))

        # 3) 根据类型分别处理
        if ann_type == "yarn":
            # 3-1 生成或输入编号
            if getattr(self, "auto_increment", False):
                label = str(getattr(self, "auto_id_counter", 1))
                # 若该编号已存在，则递增直到找到未占用编号
                existing_ids = {str(a.get("id")) for a in self.annotation_data if a.get("type") == "yarn"}
                while label in existing_ids:
                    self.auto_id_counter = int(label) + 1
                    label = str(self.auto_id_counter)
                # 成功占用当前编号后，自增一次供下次使用
                self.auto_id_counter = int(label) + 1
            else:
                text, ok = QInputDialog.getText(self, "编号输入", "请输入该点编号：")
                if not ok or not text.strip():
                    return
                label = text.strip()

            # 3-2 若该 yarn ID 已存在：更新坐标；否则追加
            updated = False
            for a in self.annotation_data:
                if a.get("type") == "yarn" and str(a.get("id")) == label:
                    a["coords"] = (real_x, real_y)
                    updated = True
                    break
            if not updated:
                self.annotation_data.append({
                    "type": "yarn",
                    "id": label,
                    "coords": (real_x, real_y),
                })

        elif ann_type in ("laser_emitter", "laser_wall"):
            # 仅允许一个点；存在则移动，不存在则新增（编号恒为 "1"）
            found = False
            for a in self.annotation_data:
                if a.get("type") == ann_type:
                    a["coords"] = (real_x, real_y)
                    found = True
                    break
            if not found:
                self.annotation_data.append({
                    "type": ann_type,
                    "id": "1",
                    "coords": (real_x, real_y),
                })

        # 4) 刷新画面与表格
        self.update_frame()

    def undo_last_point(self):
        """
        撤回当前类型下最近添加的一个标注。
        """
        ann_type = getattr(self, "current_type", None)
        if ann_type not in ("yarn", "laser_emitter", "laser_wall"):
            ann_type = "yarn"

        if not getattr(self, "annotation_data", None):
            return

        # 找到当前类型的最后一个条目（从后往前找）
        for idx in range(len(self.annotation_data) - 1, -1, -1):
            if self.annotation_data[idx].get("type") == ann_type:
                # 删除之
                removed = self.annotation_data.pop(idx)

                # 若是 yarn，需要更新自增计数（设为当前列表中最大数字ID+1）
                if ann_type == "yarn":
                    yarn_ids = [
                        int(a["id"]) for a in self.annotation_data
                        if a.get("type") == "yarn" and str(a.get("id")).isdigit()
                    ]
                    self.auto_id_counter = (max(yarn_ids) + 1) if yarn_ids else 1
                break  # 只撤回一个

        # 刷新界面
        self.update_frame()
        # 如果你的 update_table 没在 update_frame 里调用，可以单独再调：
        # self.update_table()

    def clear_all_points(self):
        """
        清空当前类型下的所有标注。
        """
        ann_type = getattr(self, "current_type", None)
        if ann_type not in ("yarn", "laser_emitter", "laser_wall"):
            ann_type = "yarn"

        if not getattr(self, "annotation_data", None):
            self.annotation_data = []

        # 仅清当前类型
        self.annotation_data = [a for a in self.annotation_data if a.get("type") != ann_type]

        # 若是 yarn，将自增计数重置为 1
        if ann_type == "yarn":
            self.auto_id_counter = 1

        # 刷新界面
        self.update_frame()
        # 如果你的 update_table 没在 update_frame 里调用，可以单独再调：
        # self.update_table()

    def confirm_and_close(self):
        # 获取图像尺寸用于坐标归一化
        width = self.video.frame_width
        height = self.video.frame_height

        # 初始化将要保存的 YAML 数据结构
        data_to_save = {}
        if os.path.exists(self.video.yaml_path):
            try:
                with open(self.video.yaml_path, 'r') as f:
                    data_to_save = yaml.safe_load(f) or {}
            except Exception as e:
                print("YAML读取失败：", e)
                data_to_save = {}

        # 准备三个字段的数据容器
        yarn_data = {}
        laser_emitter_data = []
        laser_wall_data = []

        # 重置视频对象中的注释容器，用于保存像素坐标及区域
        self.video.xian_points = {}
        self.video.laser_emitter = []
        self.video.laser_wall = []

        # 遍历内部注释列表，根据类型分别处理
        for item in self.annotation_data:
            x, y = item["coords"]
            # 计算矩形区域四角坐标（用于放大镜/点击等功能）
            x1 = max(x - self.half_w, 0)
            y1 = max(y - self.half_h, 0)
            x2 = min(x + self.half_w, width - 1)
            y2 = min(y + self.half_h, height - 1)

            if item["type"] == "yarn":
                # 保存像素坐标及区域到视频对象
                self.video.xian_points[item["id"]] = (x, y, x1, y1, x2, y2)
                # 归一化坐标保存到 YAML 数据
                yarn_data[item["id"]] = [x / width, y / height]

            elif item["type"] == "laser_emitter":
                self.video.laser_emitter.append([x, y, x1, y1, x2, y2])
                laser_emitter_data.append([x / width, y / height])

            elif item["type"] == "laser_wall":
                self.video.laser_wall.append([x, y, x1, y1, x2, y2])
                laser_wall_data.append([x / width, y / height])

        # 将准备好的数据赋值回 YAML 数据字典，确保保留三类字段
        data_to_save["yarn"] = yarn_data if yarn_data else {}
        data_to_save["laser_emitter"] = laser_emitter_data if laser_emitter_data else []
        data_to_save["laser_wall"] = laser_wall_data if laser_wall_data else []

        # 保存其它元数据字段回 YAML 数据字典
        self.video.video_id = self.video_id_input.text()
        self.video.add_type = self.add_type_input.text()
        self.video.id = self.id_input.text()
        data_to_save["video_id"] = self.video.video_id
        data_to_save["add_type"] = self.video.add_type
        data_to_save["id"] = self.video.id
        data_to_save["video_type"] = self.url_type_input.currentText()
        data_to_save["video_url"] = self.url_input.text()
        self.video.hsv_range = self.hsv_range.copy()
        data_to_save["hsv_range"] = self.hsv_range.copy()

        # 将数据写回 YAML 文件
        with open(self.video.yaml_path, 'w') as f:
            yaml.safe_dump(data_to_save, f)

        # 关闭对话框前的清理工作
        self.accept()
        self.capture_thread.stop()
        self.capture_thread.wait()

    def cancel_and_close(self):
        self.canceled = True
        self.reject()
        self.capture_thread.stop()
        self.capture_thread.wait()

    def load_annotations(self):
        # 初始化内部数据结构
        self.annotation_data = []
        yaml_path = self.video.yaml_path
        data = {}
        try:
            with open(yaml_path, 'r') as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            print("YAML读取失败：", e)
            data = {}

        # 获取图像宽高用于反归一化
        width = self.video.frame_width
        height = self.video.frame_height

        # 读取 yarn 字段（字典形式）并转换为像素坐标，加入统一列表
        yarn_entries = data.get("yarn", {})
        for idx, coord in yarn_entries.items():
            try:
                x_norm, y_norm = coord  # 归一化坐标
            except Exception:
                # 若数据格式不符预期，跳过该项
                continue
            # 将归一化坐标转换为图像像素坐标
            if x_norm <= 1 and y_norm <= 1:
                x = int(x_norm * width)
                y = int(y_norm * height)
            else:
                x = int(x_norm)
                y = int(y_norm)
            # 添加到内部列表，保存类型、ID和坐标
            self.annotation_data.append({
                "type": "yarn",
                "id": str(idx),
                "coords": (x, y)
            })

        # 读取 laser_emitter 字段（列表形式）并转换为像素坐标，加入统一列表
        emitter_entries = data.get("laser_emitter", [])
        for coord in emitter_entries:
            try:
                x_norm, y_norm = coord
            except Exception:
                continue
            if x_norm <= 1 and y_norm <= 1:
                x = int(x_norm * width)
                y = int(y_norm * height)
            else:
                x = int(x_norm)
                y = int(y_norm)
            self.annotation_data.append({
                "type": "laser_emitter",
                "id":'1',
                "coords": (x, y)
            })

        # 读取 laser_wall 字段（列表形式）并转换为像素坐标，加入统一列表
        wall_entries = data.get("laser_wall", [])
        for coord in wall_entries:
            try:
                x_norm, y_norm = coord
            except Exception:
                continue
            if x_norm <= 1 and y_norm <= 1:
                x = int(x_norm * width)
                y = int(y_norm * height)
            else:
                x = int(x_norm)
                y = int(y_norm)
            self.annotation_data.append({
                "type": "laser_wall",
                "id": '1',
                "coords": (x, y)
            })

        # 根据 yarn 的已有 ID 设置自增计数器（auto_id_counter）
        yarn_ids = [int(item["id"]) for item in self.annotation_data
                    if item["type"] == "yarn" and str(item["id"]).isdigit()]
        if yarn_ids:
            self.auto_id_counter = max(yarn_ids) + 1
        else:
            self.auto_id_counter = 0

        # 加载其它元数据字段到界面和视频对象
        self.video.video_id = data.get("video_id", "")
        self.video.add_type = data.get("add_type", "")
        self.video.id = data.get("id", "")
        self.video.hsv_range = data.get("hsv_range", self.video.hsv_range.copy())
        self.hsv_range = self.video.hsv_range.copy()
        # 将元数据显示到对应的输入框
        self.video_id_input.setText(self.video.video_id)
        self.add_type_input.setText(self.video.add_type)
        self.id_input.setText(self.video.id)
        self.url_input.setText(data.get("video_url", ""))
        self.url_type_input.setCurrentText(data.get("video_type", ""))
        # 更新HSV范围输入框
        for k in self.video.hsv_range:
            self.hsv_inputs[k].setText(str(self.video.hsv_range[k]))

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


def run_annotation_sequence(video):
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    dialog = VideoAnnotationDialog(video, settings.crap_w * 2, settings.crap_h * 2)
    dialog.exec_()
    # for annotation_type in ["yarn", "laser_emitter", "laser_wall"]:
    #     dialog = VideoAnnotationDialog(video, annotation_type,settings.crap_w*2,settings.crap_h*2)
    #     dialog.exec_()
    #     if dialog.canceled:
    #         return False  # 用户点击取消，提前退出
    # win = MoveLabelWindow(video, video.yaml_path)
    # win.exec_()  # 阻塞，直到用户关闭
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
