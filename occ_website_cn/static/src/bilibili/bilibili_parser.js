/** @odoo-module **/

// 保留既有导入路径，真实实现由通用基础模块提供。
export {
    BILIBILI_PLATFORM,
    BILIBILI_PLAYER_HOST,
    getBilibiliVideoUrl,
    isBilibiliVideoInput,
    parseBilibiliVideo,
} from "@occ_base_bilibili/bilibili_parser";
