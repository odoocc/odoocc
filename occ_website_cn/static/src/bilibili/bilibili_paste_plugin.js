/** @odoo-module **/

import { Plugin } from "@html_editor/plugin";
import { EmbeddedVideoSelector } from "@html_editor/others/embedded_components/plugins/video_plugin/video_selector_dialog/embedded_video_selector";
import { VideoSelector } from "@html_editor/main/media/media_dialog/video_selector";
import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

import { isBilibiliVideoInput, parseBilibiliVideo } from "./bilibili_parser";


export class BilibiliPastePlugin extends Plugin {
    static id = "occBilibiliPaste";
    static dependencies = ["history", "dom"];

    resources = {
        ...(this.config.allowVideo !== false && {
            paste_media_url_command_providers: this.getCommandForBilibiliUrlPaste.bind(this),
        }),
    };

    getCommandForBilibiliUrlPaste(url) {
        if (!parseBilibiliVideo(url)) {
            return;
        }
        return {
            title: _t("Embed Bilibili Video"),
            description: _t("Embed the Bilibili video in the document."),
            icon: "fa-play-circle",
            run: async () => {
                const videoData = await rpc("/html_editor/video_url/data", { video_url: url });
                if (!videoData?.embed_url || videoData.platform !== "bilibili") {
                    return;
                }
                const embeddedComponents = this.getResource("embedded_components") || [];
                const hasEmbeddedVideo = embeddedComponents.some(({ name }) => name === "video");
                const element = hasEmbeddedVideo
                    ? EmbeddedVideoSelector.createElements([
                          {
                              videoId: videoData.video_id,
                              platform: videoData.platform,
                              params: videoData.params,
                          },
                      ])[0]
                    : VideoSelector.createElements([{ src: videoData.embed_url }])[0];
                if (!element) {
                    return;
                }
                if (!hasEmbeddedVideo) {
                    element.classList.add(...VideoSelector.mediaSpecificClasses);
                }
                this.dependencies.dom.insert(element);
                this.dependencies.history.addStep();
            },
        };
    }
}

// Website Builder discovers addons through this registry. Backend HTML fields
// receive the same behavior via the VideoSelector and their media dialog; URL
// paste is registered where Odoo exposes a stable plugin registry.
registry.category("website-plugins").add(BilibiliPastePlugin.id, BilibiliPastePlugin);

export { isBilibiliVideoInput };
