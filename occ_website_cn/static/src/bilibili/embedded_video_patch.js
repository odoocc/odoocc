/** @odoo-module **/

import { EmbeddedVideoComponent } from "@html_editor/others/embedded_components/backend/video/video";
import { ReadonlyEmbeddedVideoComponent } from "@html_editor/others/embedded_components/core/video/readonly_video";
import { patch } from "@web/core/utils/patch";

import { BILIBILI_PLATFORM, getBilibiliVideoUrl } from "./bilibili_parser";


patch(ReadonlyEmbeddedVideoComponent.prototype, {
    get url() {
        if (this.props.platform === BILIBILI_PLATFORM) {
            return getBilibiliVideoUrl(
                this.props.videoId,
                this.props.params || {}
            ).toString();
        }
        return super.url;
    },
});

patch(EmbeddedVideoComponent.prototype, {
    get url() {
        if (this.state.platform === BILIBILI_PLATFORM) {
            return getBilibiliVideoUrl(
                this.state.videoId,
                this.state.params || {}
            ).toString();
        }
        return super.url;
    },

    replaceVideo(media) {
        super.replaceVideo(...arguments);
        this.videoBlock.classList.toggle(
            "occ_bilibili_embedded_video",
            media.platform === BILIBILI_PLATFORM
        );
    },
});
