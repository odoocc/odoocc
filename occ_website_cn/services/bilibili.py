"""向后兼容的B站解析导入路径。"""

from odoo.addons.occ_base_bilibili.services import (
    BilibiliVideo,
    get_bilibili_video_url_data,
    is_bilibili_video_input,
    parse_bilibili_video,
)

__all__ = [
    "BilibiliVideo",
    "get_bilibili_video_url_data",
    "is_bilibili_video_input",
    "parse_bilibili_video",
]
