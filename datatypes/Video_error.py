# -----------------------------------------------------------------------------
#  Video_error (保持不变)
# -----------------------------------------------------------------------------
'''
grade
-1 无
0 工控机
1 区域 zone
2 摄像头
3 线
'''
from datatypes.Video import Video


class Video_error:
    def __init__(self, video: Video, xian_id, image, frame, error_type,grade,show=True):
        self.video = video
        self.video_id = video.video_id
        self.video_add = video.add_type
        self.time_s = video.this_time
        self.xian_id = xian_id
        self.image = image
        self.frame = frame
        self.error_type = error_type
        self.grade = grade
        self.show = show

