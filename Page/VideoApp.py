
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap, QGuiApplication, QFont
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTableWidget, \
    QTableWidgetItem, QSizePolicy, QHeaderView, QAbstractButton

import hashlib
from Page import run_annotation_sequence

from PyQt5.QtWidgets import  QInputDialog, QMessageBox,QLineEdit

from activate import save_license_file
import settings
from Utils import cv2_to_qimage, load_config
from detect_xian import VideoProcessorThread


class VideoApp(QWidget):
    def __init__(self, video_list):
        super().__init__()

        # 初始化视频列表
        self.video_list = video_list
        # ① 记录基准尺寸（窗口启动时大小）
        geo = QGuiApplication.primaryScreen().availableGeometry()
        self.base_w = int(geo.width()  * 0.8)
        self.base_h = int(geo.height() * 0.8)
        self.resize(self.base_w, self.base_h)
        # 设置界面布局
        self.init_ui()

    def init_ui(self):
        # ── 主布局 ─────────────────────────────────
        main_layout = QHBoxLayout(self)

        # ---------- 左：视频预览标签 ----------
        self.display_area = QLabel(alignment=Qt.AlignCenter)
        # ① 允许水平/垂直同时扩张
        self.display_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # 给个最小尺寸，避免窗口极小时挤到 0
        self.display_area.setMinimumSize(320, 240)
        main_layout.addWidget(self.display_area, 7)      # 左右 7:3 比例

        right_layout = QVBoxLayout()
        btn_row = QHBoxLayout()

        self.close_preview_button = QPushButton("关闭预览")
        self.close_preview_button.clicked.connect(self.close_preview)
        btn_row.addWidget(self.close_preview_button)

        self.reload_button = QPushButton("重新加载")
        self.reload_button.clicked.connect(reload2)
        btn_row.addWidget(self.reload_button)

        self.change_passwd_button = QPushButton("修改密码")
        self.change_passwd_button.clicked.connect(self.on_change_password)
        btn_row.addWidget(self.change_passwd_button)

        right_layout.addLayout(btn_row)

        # 视频表格
        self.table = QTableWidget(len(self.video_list), 3)
        self.table.setHorizontalHeaderLabels(['Video ID', '预览', '标注'])

        # ② 列宽自动填满 & 行高根据内容
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

        for i, video in enumerate(self.video_list):
            self.table.setItem(i, 0, QTableWidgetItem(str(video.id)))

            btn_preview = QPushButton("预览")
            btn_preview.clicked.connect(lambda _, vid=video.id: self.process_video(vid))
            self.table.setCellWidget(i, 1, btn_preview)

            btn_annot = QPushButton("标注")
            btn_annot.clicked.connect(lambda _, v=video: self.on_annot_clicked(v))

            # btn_annot.clicked.connect(lambda _, v=video: self.run_annotation_sequence(v))
            self.table.setCellWidget(i, 2, btn_annot)

        right_layout.addWidget(self.table)

        # ③ 右侧布局放到主布局，伸缩因子 3
        main_layout.addLayout(right_layout, 3)

        # ---------- 窗口基本属性 ----------
        self.setWindowTitle('断线检测')
        self.resize(QGuiApplication.primaryScreen().availableGeometry().size() * 0.8)

    def on_change_password(self):
        # 1️⃣ 输入原密码
        old_passwd, ok = QInputDialog.getText(self, "原密码验证", "请输入原密码：", QLineEdit.Password)
        if not ok:
            return
        if hashlib.sha256(old_passwd.encode('utf-8')).hexdigest() != settings.passwd:
            QMessageBox.warning(self, "错误", "原密码错误！")
            return

        # 2️⃣ 输入新密码
        new_passwd1, ok1 = QInputDialog.getText(self, "设置新密码", "请输入新密码：", QLineEdit.Password)
        if not ok1:
            return
        new_passwd2, ok2 = QInputDialog.getText(self, "确认新密码", "请再次输入新密码：", QLineEdit.Password)
        if not ok2:
            return

        if new_passwd1 != new_passwd2:
            QMessageBox.warning(self, "错误", "两次输入的密码不一致！")
            return

        # 3️⃣ 保存新密码（SHA-256 加密）
        settings.passwd = hashlib.sha256(new_passwd1.encode('utf-8')).hexdigest()
        license_data=settings.license_data
        license_data['passwd'] = settings.passwd
        settings.license_data = license_data
        save_license_file(settings.license_data)
        QMessageBox.information(self, "成功", "密码已修改成功！")

    def on_annot_clicked(self,video):
        # 弹出密码输入框
        password, ok = QInputDialog.getText(None, "密码验证", "请输入密码：", QLineEdit.Password)
        if ok:  # 用户点击了确认
            if hashlib.sha256(password.encode('utf-8')).hexdigest() == settings.passwd:
                # 密码正确，执行原函数
                self.run_annotation_sequence(video)
            else:
                # 密码错误，提示
                QMessageBox.warning(None, "错误", "密码错误！")

    def run_annotation_sequence(self, video):
        settings.label_video_id=video.id
        run_annotation_sequence(video)
        settings.label_video_id=-1
    def resizeEvent(self, event):
        scale = min(self.width()/self.base_w, self.height()/self.base_h)
        rescale_widgets(self, scale, base_font_pt=11)   # 11 pt 为设计期字号
        super().resizeEvent(event)

    def process_video(self, video_id):
        settings.show_id=video_id

    def update_display(self, cv_img):
        """把 OpenCV BGR 图像按 QLabel 尺寸等比例显示"""
        qimg = cv2_to_qimage(cv_img)                # 你的工具函数
        pix   = QPixmap.fromImage(qimg)
        # ④ 按当前 label 尺寸等比例缩放
        pix = pix.scaled(self.display_area.size(), Qt.KeepAspectRatio,
                         transformMode=Qt.SmoothTransformation)
        self.display_area.setPixmap(pix)

    def close_preview(self):
        """
        点击关闭预览按钮时，清空展示区域的内容
        """
        settings.show_id=-1
        self.display_area.clear()  # 清空展示区域内容




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

def reload2():
    print('重启')
    stop()
    settings.video_list=[]
    load_config(settings.config_path)
    settings.video_thread = VideoProcessorThread(settings.video_list,window=settings.window)
    settings.video_thread.start()


def stop():
    settings.video_thread._running=False
    for video in settings.video_list:
        video.stop()
    settings.modbusServer.stop()