from .settings import (config_path,dir_path,IMAGE_SIZE,RTSP_RECONNECT_INTERVAL,HTTP_RECONNECT_INTERVAL,
                       RELINK_TIME,crap_w,crap_h,HISTORY_LEN,BUF_SIZE,bg_frames,csv_name,
                       ERROR_WIN,CORRECT_WIN,save,save_csv,save_interval,video_output_path,video_output_paths,
                       label_video_id,show_id,point_max_size,model_size,model_threshold,model_path,video_list,video_thread,window,passwd,license_data,recognition_fps,fetch_sleep_idle,fetch_sleep_full,get_frame_interval,refresh_timing_by_fps,set_recognition_fps,push_elapsed,get_elapsed_series)

from .mysql_settings import db_host,db_port,db_user,db_password,db_save_day,save_img,save_img_path,xiandb

from .modbus_setttings import modbusServer

from .diff_settings import medianBlur_ksize,threshold_thresh,kernel_ksize,kernel_ksize2
__all__ = ['config_path','dir_path',"IMAGE_SIZE",'RTSP_RECONNECT_INTERVAL','HTTP_RECONNECT_INTERVAL',
           'RELINK_TIME','crap_w','crap_h','HISTORY_LEN','BUF_SIZE','bg_frames','csv_name',
           'db_host','db_port','db_user','db_password','db_save_day','save_img','save_img_path','xiandb',
           'modbusServer',
           'ERROR_WIN','CORRECT_WIN','save','save_csv','save_interval','video_output_path','video_output_paths',
           'label_video_id','show_id','point_max_size','model_size','model_threshold','model_path','video_list','video_thread','window','passwd','license_data','recognition_fps','fetch_sleep_idle','fetch_sleep_full','get_frame_interval','refresh_timing_by_fps','set_recognition_fps','push_elapsed','get_elapsed_series',
           'medianBlur_ksize','threshold_thresh','kernel_ksize','kernel_ksize2']


__version__ = "1.0"