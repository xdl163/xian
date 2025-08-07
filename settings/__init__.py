from .settings import (config_path,dir_path,IMAGE_SIZE,RTSP_RECONNECT_INTERVAL,HTTP_RECONNECT_INTERVAL,
                       RELINK_TIME,crap_w,crap_h,HISTORY_LEN,BUF_SIZE,bg_frames,csv_name,
                       ERROR_WIN,CORRECT_WIN,save,save_csv,save_interval,video_output_path,video_output_paths,
                       label_video_id,show_id,point_max_size,model_size,video_list,video_thread,window)

from .mysql_settings import db_host,db_port,db_user,db_password,db_save_day,save_img,save_img_path,xiandb

from .modbus_setttings import modbusServer

__all__ = ['config_path','dir_path',"IMAGE_SIZE",'RTSP_RECONNECT_INTERVAL','HTTP_RECONNECT_INTERVAL',
           'RELINK_TIME','crap_w','crap_h','HISTORY_LEN','BUF_SIZE','bg_frames','csv_name',
           'db_host','db_port','db_user','db_password','db_save_day','save_img','save_img_path','xiandb',
           'modbusServer',
           'ERROR_WIN','CORRECT_WIN','save','save_csv','save_interval','video_output_path','video_output_paths',
           'label_video_id','show_id','point_max_size','model_size','video_list','video_thread','window']


__version__ = "1.0"