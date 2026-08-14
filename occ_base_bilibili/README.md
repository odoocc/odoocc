# OdooCC B站基础能力（`occ_base_bilibili`）

本模块为其他 Odoo 19 模块提供严格、离线、可复用的B站视频解析组件。它只识别白名单地址并
生成固定官方播放器 URL，不请求B站接口、不跟随重定向，也不直接加载视频。

## 能力与边界

- Python：`BilibiliVideo`、`parse_bilibili_video()`、
  `is_bilibili_video_input()`、`get_bilibili_video_url_data()`。
- JavaScript：`parseBilibiliVideo()`、`isBilibiliVideoInput()`、
  `getBilibiliVideoUrl()`。
- 支持B站桌面/移动视频页、官方播放器地址、BV、av 和 `p`/`page` 分P。
- 单独 BV 号只有传入 `allow_bare_bvid=True` / `allowBareBvid: true` 才会解析；单独 av 号
  默认允许。
- 拒绝短链、直播、番剧、恶意子域、端口、用户密码、fragment、脚本协议、未知/重复播放器
  参数及非零自动播放。
- 规范播放器地址固定为 `https://player.bilibili.com/player.html`，不会传播任意参数。

本模块不提供菜单、播放器、Cookie 同意或 Website Builder 集成。这些界面和发布策略由调用
模块负责；`occ_website_cn` 是一个调用示例。

## 安装、升级与卸载

```bash
./odoo-bin -d <数据库名> --addons-path=addons,addons_odoocc \
    -i occ_base_bilibili --stop-after-init

./odoo-bin -d <数据库名> --addons-path=addons,addons_odoocc \
    -u occ_base_bilibili --stop-after-init
```

升级前应备份数据库并在副本中回归依赖模块。模块没有持久业务数据；卸载会使依赖模块无法
启动，应先卸载或迁移依赖方。

## 调用示例

```python
from odoo.addons.occ_base_bilibili.services import parse_bilibili_video

video = parse_bilibili_video(
    "https://www.bilibili.com/video/BV1xx411c7mD?p=2"
)
video.video_id       # BV1xx411c7mD
video.page           # 2
video.embed_url      # 固定 HTTPS 播放器地址
```

```javascript
import { parseBilibiliVideo } from "@occ_base_bilibili/bilibili_parser";

const video = parseBilibiliVideo("BV1xx411c7mD", { allowBareBvid: true });
```

## 权限、安全与数据

解析全程在当前进程/浏览器完成，没有控制器、持久模型、ACL、密钥或外部请求。返回地址只含
规范视频号、分P和关闭自动播放参数。调用方仍需决定谁可以插入或发布视频，并对实际 iframe
实施 CSP、Cookie 同意和访问权限策略。

## 测试与验收

```bash
./odoo-bin -d <测试数据库> --addons-path=addons,addons_odoocc \
    -i occ_base_bilibili --test-enable --test-tags=/occ_base_bilibili \
    --stop-after-init

./odoo-bin -d <测试数据库> --addons-path=addons,addons_odoocc \
    -u web,occ_base_bilibili --test-enable \
    --test-tags='/web:WebSuite.test_unit_desktop[@occ_base_bilibili]' \
    --stop-after-init
```

非生产环境可安装 `occ_base_bilibili_test`，从“设置 → OdooCC B站基础能力验收 →
B站视频解析器”交互验证规范视频号、分P和播放器地址；页面不会加载真实视频。

## English summary

`occ_base_bilibili` provides strict, offline Python and JavaScript parsers for canonical
Bilibili video references on Odoo 19. It performs no network requests, rejects shortened or
unsafe inputs and arbitrary player parameters, and deliberately leaves UI, playback, consent,
and publishing policy to consuming modules.

## 许可证与联系

- 作者：Odoo老赵
- 官网：<https://odoocc.com>
- 支持邮箱：<156277468@qq.com>
- 许可证：[GNU Affero General Public License v3.0](../LICENSE)
