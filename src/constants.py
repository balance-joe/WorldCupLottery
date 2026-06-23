"""多个模块共用的常量和工具函数。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


CHINA_TZ = timezone(timedelta(hours=8))

WINDOWS = ("open_to_latest", "last_24h", "last_6h")


def parse_time(value) -> datetime | None:
    """将时间字符串或 datetime 解析为带时区的 datetime。

    如果无法解析则返回 None。
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=CHINA_TZ)
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("T", " ")
    if text.endswith("+08:00"):
        text = text[:-6]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=CHINA_TZ)
        except ValueError:
            continue
    return None
