"""
activate 包初始化模块，包含授权校验与授权文件处理功能。
"""

from .license_handler import load_license_file, save_license_file
from .validator import AuthorizationValidator
from .activate import activate_if_needed

__all__ = ["activate_if_needed", "AuthorizationValidator"]
__version__ = "1.0"
