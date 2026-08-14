from odoo import fields, models

from odoo.addons.occ_base_bilibili.services import (
    is_bilibili_video_input,
    parse_bilibili_video,
)


class OccBaseBilibiliDemo(models.Model):
    _name = "occ.base.bilibili.demo"
    _description = "B站视频解析验收"

    name = fields.Char(string="名称", required=True, default="B站视频解析示例")
    video_input = fields.Text(
        string="B站视频地址或视频号",
        required=True,
        default="https://www.bilibili.com/video/BV1xx411c7mD?p=2",
        help=(
            "支持B站视频页、移动端地址、官方播放器地址、av号，"
            "以及显式允许后的BV号。"
        ),
    )
    allow_bare_bvid = fields.Boolean(string="允许单独输入BV号")
    parse_status = fields.Selection(
        selection=[("pending", "待解析"), ("valid", "有效"), ("invalid", "无效")],
        string="解析状态",
        required=True,
        default="pending",
        readonly=True,
    )
    is_bilibili_input = fields.Boolean(string="是否声明为B站输入", readonly=True)
    canonical_video_id = fields.Char(string="规范视频号", readonly=True)
    page = fields.Integer(string="分P", readonly=True)
    player_url = fields.Char(string="规范播放器地址", readonly=True)

    def action_parse(self):
        for record in self:
            video = parse_bilibili_video(
                record.video_input, allow_bare_bvid=record.allow_bare_bvid
            )
            record.write(
                {
                    "is_bilibili_input": is_bilibili_video_input(
                        record.video_input, allow_bare_bvid=record.allow_bare_bvid
                    ),
                    "parse_status": "valid" if video else "invalid",
                    "canonical_video_id": video.video_id if video else False,
                    "page": video.page if video else 0,
                    "player_url": video.embed_url if video else False,
                }
            )
        return True
