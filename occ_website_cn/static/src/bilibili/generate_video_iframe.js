/** @odoo-module **/

import { MediaVideo } from "@website/interactions/video/media_video";
import { patch } from "@web/core/utils/patch";

import { isBilibiliVideoInput, parseBilibiliVideo } from "./bilibili_parser";


function manageIframeSrcOnLoad(iframe, src) {
    if (!iframe.closest("[data-need-cookies-approval]")) {
        iframe.setAttribute("src", src);
        return;
    }
    iframe.dataset.nocookieSrc = src;
    iframe.dataset.needCookiesApproval = "true";
    iframe.setAttribute("src", "about:blank");
}

function createBilibiliIframe(parent, src, manageIframeSrc) {
    parent.replaceChildren();
    const editionPlaceholder = document.createElement("div");
    editionPlaceholder.className = "css_editable_mode_display";
    const sizePlaceholder = document.createElement("div");
    sizePlaceholder.className = "media_iframe_video_size";
    const iframe = document.createElement("iframe");
    iframe.setAttribute("frameborder", "0");
    iframe.setAttribute("allowfullscreen", "allowfullscreen");
    iframe.setAttribute("referrerpolicy", "strict-origin-when-cross-origin");
    parent.append(editionPlaceholder, sizePlaceholder, iframe);
    (manageIframeSrc || manageIframeSrcOnLoad)(iframe, src);
    return iframe;
}

/**
 * Extend Odoo's saved-video rebuilder while preserving every upstream
 * provider and its future behavior.
 */
export function generateBilibiliIframe(parent, manageIframeSrc) {
    const source = parent.dataset.oeExpression || parent.dataset.src;
    const video = parseBilibiliVideo(source);
    if (!video) {
        // Never leave attacker-controlled iframe markup in a claimed
        // Bilibili container when strict parsing fails.
        parent.replaceChildren();
        return;
    }
    return createBilibiliIframe(parent, video.embedUrl, manageIframeSrc);
}

// MediaVideo itself captured the original named export at module evaluation
// time. Patch its production start path explicitly so dynamically inserted or
// restarted Bilibili containers are rebuilt before upstream behavior runs.
patch(MediaVideo.prototype, {
    start() {
        const source = this.el.dataset.oeExpression || this.el.dataset.src;
        if (isBilibiliVideoInput(source) && !this.el.querySelector(":scope > iframe")) {
            generateBilibiliIframe(this.el, this.services.website_cookies.manageIframeSrc);
        }
        return super.start(...arguments);
    },
});
