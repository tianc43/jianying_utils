"""时间工具 — 时间解析、格式化、转换

适用于 Dify 工作流的代码节点。
"""

import re
from typing import Union, Dict, Any

from pyJianYingDraft import tim, trange, SEC


_NUMERIC_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
_NUMBER_PART = r"\d+(?:\.\d+)?"
_UNIT_TIME_RE = re.compile(
    rf"^[+-]?(?:"
    rf"{_NUMBER_PART}h(?:{_NUMBER_PART}m)?(?:{_NUMBER_PART}s)?|"
    rf"{_NUMBER_PART}m(?:{_NUMBER_PART}s)?|"
    rf"{_NUMBER_PART}s"
    rf")$",
    re.IGNORECASE,
)


def parse_time_value(value: Union[str, float, int]) -> int:
    """将时间值转换为微秒；纯数字字符串按微秒处理，带单位字符串按 tim() 处理。"""
    if isinstance(value, str):
        stripped = value.strip()
        if _NUMERIC_RE.fullmatch(stripped):
            return int(round(float(stripped)))
        if not _UNIT_TIME_RE.fullmatch(stripped):
            raise ValueError(f"不支持的时间格式: {value!r}")
        return tim(stripped)
    return int(round(value))


class TimeTool:
    """时间相关工具类

    剪映内部使用微秒（μs）作为时间单位，1秒 = 1,000,000 微秒。
    """

    # 常量
    MICROSECONDS_PER_SECOND = SEC  # 1,000,000

    @staticmethod
    def parse_time(time_input: Union[str, float, int]) -> Dict[str, Any]:
        """将时间字符串或数字转换为微秒数

        支持格式:
            - "1h52m3s" → 6723000000
            - "0.15s" → 150000
            - "5s" → 5000000
            - "1m30s" → 90000000
            - 直接输入数字视为微秒

        Args:
            time_input: 时间字符串或直接输入微秒数

        Returns:
            dict: {"success": True, "microseconds": int, "message": str}
        """
        result = parse_time_value(time_input)
        return {"success": True, "microseconds": result, "message": "时间解析成功"}

    @staticmethod
    def format_time(microseconds: int) -> Dict[str, Any]:
        """将微秒数格式化为可读时间字符串

        Args:
            microseconds: 微秒数

        Returns:
            dict: {"success": True, "formatted": str, "message": str}
        """
        total_seconds = microseconds / SEC
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        seconds = total_seconds % 60
        formatted = f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"
        return {"success": True, "formatted": formatted, "message": "时间格式化成功"}

    @staticmethod
    def seconds_to_microseconds(seconds: Union[float, int]) -> Dict[str, Any]:
        """秒转微秒

        Args:
            seconds: 秒数

        Returns:
            dict: {"success": True, "microseconds": int, "message": str}
        """
        result = int(round(seconds * SEC))
        return {"success": True, "microseconds": result, "message": "转换成功"}

    @staticmethod
    def milliseconds_to_microseconds(ms: Union[float, int]) -> Dict[str, Any]:
        """毫秒转微秒

        Args:
            ms: 毫秒数

        Returns:
            dict: {"success": True, "microseconds": int, "message": str}
        """
        result = int(round(ms * 1000))
        return {"success": True, "microseconds": result, "message": "转换成功"}

    @staticmethod
    def microseconds_to_seconds(microseconds: int) -> Dict[str, Any]:
        """微秒转秒

        Args:
            microseconds: 微秒数

        Returns:
            dict: {"success": True, "seconds": float, "message": str}
        """
        result = microseconds / SEC
        return {"success": True, "seconds": result, "message": "转换成功"}

    @staticmethod
    def create_timerange(start: Union[str, float], duration: Union[str, float]) -> Dict[str, int]:
        """创建时间范围字典

        Args:
            start: 起始时间（字符串或微秒数）
            duration: 持续时间（字符串或微秒数），注意不是结束时间

        Returns:
            dict: {"start": int, "duration": int} 单位微秒
        """
        return {"start": parse_time_value(start), "duration": parse_time_value(duration)}

    @staticmethod
    def timerange_from_start_end(start: Union[str, float], end: Union[str, float]) -> Dict[str, int]:
        """根据起始和结束时间创建时间范围

        Args:
            start: 起始时间
            end: 结束时间

        Returns:
            dict: {"start": int, "duration": int} 单位微秒
        """
        s = parse_time_value(start)
        e = parse_time_value(end)
        if e < s:
            raise ValueError(f"结束时间 ({e}) 不能小于起始时间 ({s})")
        return {"start": s, "duration": e - s}
