"""TM1 连接与读取。"""
from tm1_insight.tm1.client import TM1Client, safe_filename, safe_getattr

__all__ = ["TM1Client", "safe_filename", "safe_getattr"]
