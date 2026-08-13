/** @odoo-module **/

import { VideoSelector } from "@html_editor/main/media/media_dialog/video_selector";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

import {
    BILIBILI_PLATFORM,
    isBilibiliVideoInput,
    parseBilibiliVideo,
} from "./bilibili_parser";


patch(VideoSelector.prototype, {
    setup() {
        super.setup(...arguments);
        this.PLATFORMS.bilibili = BILIBILI_PLATFORM;
    },

    async updateVideo() {
        const claimedBilibili = isBilibiliVideoInput(this.state.urlInput);
        if (!claimedBilibili) {
            return super.updateVideo(...arguments);
        }
        if (!this.state.urlInput) {
            return super.updateVideo(...arguments);
        }
        if (this.props.occDisableBilibili) {
            this.state.src = "";
            this.state.platform = null;
            this.state.options = [];
            this.state.errorMessage = _t("Bilibili videos are not supported in product media");
            this.props.errorMessages(this.state.errorMessage);
            this.props.selectMedia({});
            return;
        }
        if (this.props.isForBgVideo) {
            this.state.src = "";
            this.state.platform = null;
            this.state.options = [];
            this.state.errorMessage = _t("Bilibili videos cannot be used as background videos");
            this.props.errorMessages(this.state.errorMessage);
            this.props.selectMedia({});
            return;
        }
        // Do not let Odoo's generic embed-code regex turn the matched
        // attribute name (`src`) into the RPC URL. Bilibili URL and official
        // iframe inputs are parsed and sent through their own strict path.
        const parsed = parseBilibiliVideo(this.state.urlInput);
        const videoData = parsed
            ? await this._getVideoURLData(this.state.urlInput, {})
            : { error: true };
        if (videoData?.platform !== BILIBILI_PLATFORM || !videoData.embed_url) {
            this.state.src = "";
            this.state.platform = null;
            this.state.options = [];
            this.state.errorMessage = _t("The provided Bilibili video URL is invalid or unsupported");
            this.props.errorMessages(this.state.errorMessage);
            this.props.selectMedia({});
            return;
        }
        this.state.src = videoData.embed_url;
        this.state.platform = BILIBILI_PLATFORM;
        this.state.options = [];
        this.state.errorMessage = "";
        this.props.errorMessages("");
        this.props.selectMedia({
            id: videoData.embed_url,
            src: videoData.embed_url,
            platform: videoData.platform,
            videoId: videoData.video_id,
            params: videoData.params,
        });
    },
});
