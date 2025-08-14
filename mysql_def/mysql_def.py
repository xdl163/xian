import atexit
import time

import numpy as np
import pymysql
import os
import cv2
from datetime import datetime
from datatypes import Video_error


class XianDB:
    '''
    MySQL 数据表结构：
    id             INT AUTO_INCREMENT   主键，自增ID
    time           DATETIME             事件时间
    camera_id      INT                  摄像头编号
    camera_area    VARCHAR(100)         摄像头所在区域
    line_number    INT                  线编号
    line_number    INT                  线编号
    event_type     VARCHAR(50)          事件类型
    image_path     VARCHAR(255)         图片保存路径
    '''
    def __init__(self, host, port, user, password,save_img_path,save_img,db_save_day):
        self.save_img=save_img
        self.db_save_day=db_save_day
        self.connection = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            charset='utf8mb4',
            autocommit=True
        )
        # 保存图片到本地目录
        self.save_dir = save_img_path
        os.makedirs(self.save_dir, exist_ok=True)
        self.closed = False
        atexit.register(self.close)  # 注册退出时自动调用 close()
        self.init_database_and_table()
        self.create_video_table()
        print('数据库初始化成功')


    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
    def init_database_and_table(self):
        with self.connection.cursor() as cursor:
            cursor.execute("CREATE DATABASE IF NOT EXISTS xian;")
            cursor.execute("USE xian;")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS xian_event (
                id INT AUTO_INCREMENT PRIMARY KEY,
                time DATETIME NOT NULL,
                camera_id INT NOT NULL,
                camera_area VARCHAR(100),
                line_number INT NOT NULL,
                event_type VARCHAR(50),
                image_path VARCHAR(255)
            );
            """)
            print("数据库和表已准备好。")

    def insert_event_t(self, time, camera_id, camera_area, line_number, event_type, image_path):
        with self.connection.cursor() as cursor:
            cursor.execute("USE xian;")
            sql = """
                INSERT INTO xian_event (time, camera_id, camera_area, line_number, event_type, image_path)
                VALUES (%s, %s, %s, %s, %s, %s);
            """
            cursor.execute(sql, (time, camera_id, camera_area, line_number, event_type, image_path))
            # print(f"已添加事件记录，图片路径：{image_path}")

    def insert_event(self, video_error: Video_error):
        now = datetime.now()
        image_filename = f"{video_error.video_id}_{now.strftime('%Y%m%d_%H%M%S_%f')}.jpg"
        image_path = os.path.join(self.save_dir, image_filename)
        if self.save_img:
            # 保存图片
            image_1=video_error.frame
            image_2=video_error.video.this_frame
            height = max(image_1.shape[0], image_2.shape[0])
            image_1_resized = cv2.resize(image_1, (int(image_1.shape[1] * (height / image_1.shape[0])), height))
            image_2_resized = cv2.resize(image_2, (int(image_2.shape[1] * (height / image_2.shape[0])), height))

            # Concatenate the images horizontally
            concatenated_image = np.hstack((image_1_resized, image_2_resized))



            cv2.imwrite(image_path, concatenated_image)
        # 插入记录
        self.insert_event_t(
            time=now,
            camera_id=video_error.video_id,
            camera_area=video_error.video_add,
            line_number=video_error.xian_id,
            event_type=video_error.error_type,
            image_path=image_path
        )



    def delete_events_before_day(self):
        self.delete_events_before(time.time()-self.db_save_day*24*60*60)

    def delete_events_before(self, timestamp_threshold):
        """
        删除指定时间戳之前的所有事件记录，并检查图片文件是否存在，如果存在则删除。
        :param timestamp_threshold: 要删除的时间戳，删除该时间戳之前的所有事件
        """
        # 将时间戳转换为 datetime 对象
        time_threshold = datetime.fromtimestamp(timestamp_threshold)
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("USE xian;")
                # 查找时间阈值之前的所有事件
                cursor.execute("""
                    SELECT image_path FROM xian_event WHERE time < %s;
                """, (time_threshold,))
                events_to_delete = cursor.fetchall()
                print(f'查询到{len(events_to_delete)}条，开始删除记录')
                # 删除记录（按时间直接删除）
                cursor.execute("""
                    DELETE FROM xian_event WHERE time < %s;
                """, (time_threshold,))
                print('开始删除图片')
                # 删除相关的图片文件（如果存在）
                for event in events_to_delete:
                    image_path = event[0]
                    if os.path.exists(image_path):
                        # print(image_path)
                        os.remove(image_path)

                print('图片删除结束,开始提交')
                # 提交删除操作
                self.connection.commit()
                # self.connection.rollback()
                print(f"所有在 {time_threshold} 之前的事件记录和图片已删除。")
        except Exception as e:
            # 如果发生异常，则撤回（回滚）事务
            self.connection.rollback()
            print(f"发生错误，已回滚操作：{e}")

    def close(self):
        if not self.closed:
            try:
                self.connection.close()
                print("连接关闭")
            except Exception as e:
                print(f"关闭数据库连接时发生异常: {e}")
            self.closed = True

        # 方法 2：创建 video_info 表
    def create_video_table(self):
        with self.connection.cursor() as cursor:
            cursor.execute("USE xian;")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS video_info (
                id VARCHAR(255) PRIMARY KEY,
                video_id INT,
                add_type VARCHAR(100),
                ip VARCHAR(100),
                xian_num INT,
                duanxian_num INT,
                status VARCHAR(100),
                update_time DATETIME,
                xian_status VARCHAR(100)  -- 新增的 xian_status 列
            );
            """)
            print("表 video_info 创建完成。")


    def upsert_videos(self, videos: list):
        with self.connection.cursor() as cursor:
            cursor.execute("USE xian;")
            for video in videos:
                xian_num = video.get_xian_num()
                duanxian_num = len(video.xian_points) - xian_num  # 断线数量
                status = video.get_video_type()  # 当前状态

                # Convert xian_light list to a string (comma-separated 1s and 0s)
                xian_status = ''.join([str(1 if light else 0) for light in video.xian_light])

                cursor.execute("SELECT COUNT(*) FROM video_info WHERE id=%s", (video.id,))
                exists = cursor.fetchone()[0]

                if exists:
                    # 更新记录
                    cursor.execute(""" 
                        UPDATE video_info
                        SET video_id=%s, add_type=%s, ip=%s,
                            xian_num=%s, duanxian_num=%s, status=%s, xian_status=%s, update_time=NOW()
                        WHERE id=%s
                    """, (video.video_id, video.add_type, video.ip,
                          xian_num, duanxian_num, status, xian_status, video.id))
                    # print(f"更新视频信息：{video.id}")
                else:
                    # 插入记录
                    cursor.execute(""" 
                        INSERT INTO video_info
                            (id, video_id, add_type, ip, xian_num, duanxian_num, status, xian_status, update_time)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    """, (video.id, video.video_id, video.add_type, video.ip,
                          xian_num, duanxian_num, status, xian_status))
                    # print(f"插入新视频信息：{video.id}")



# if __name__ == '__main__':
#     with XianDB(host='127.0.0.1',port=3306,user='root',password='xu12345678gh',) as xiandb:
#


