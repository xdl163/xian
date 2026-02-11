"""
activate 包初始化模块，包含授权校验与授权文件处理功能。
"""

from .license_handler import load_license_file, save_license_file
__all__ = ['save_license_file']
__version__ = "1.0"
