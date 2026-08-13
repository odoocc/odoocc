/** @odoo-module **/

import { getEmbeddedProps } from "@html_editor/others/embedded_component_utils";
import { readonlyVideoEmbedding } from "@html_editor/others/embedded_components/core/video/readonly_video";
import { ReadonlyEmbeddedVideoComponent } from "@html_editor/others/embedded_components/core/video/readonly_video";
import { onMounted, useRef } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";

import { BILIBILI_PLATFORM, getBilibiliVideoUrl } from "./bilibili_parser";


function optionalCookiesNeedApproval(host) {
    if (host?.closest("[data-need-cookies-approval]")) {
        return true;
    }
    // Stored HTML fields are rendered from their serialized value. QWeb
    // normally post-processes every classed embedded host. If another
    // renderer bypasses that pass, do not infer policy from the Cookie Bar DOM
    // alone: Odoo only blocks third parties when its separate tracking-domain
    // switch is enabled, and that server-side decision is represented by the
    // data marker above.
    return false;
}

function prepareIframeForOptionalConsent(iframe, host, playerUrl, cookieService) {
    if (optionalCookiesNeedApproval(host)) {
        iframe.dataset.needCookiesApproval = "true";
        if (cookieService) {
            // The marker on the iframe makes it its own approval container;
            // Odoo then starts the standard warning/consent interaction.
            cookieService.manageIframeSrc(iframe, playerUrl);
        } else {
            iframe.dataset.nocookieSrc = playerUrl;
            iframe.src = "about:blank";
        }
        return;
    }
    if (cookieService) {
        cookieService.manageIframeSrc(iframe, playerUrl);
    } else {
        iframe.src = playerUrl;
    }
}


patch(ReadonlyEmbeddedVideoComponent, {
    props: {
        ...ReadonlyEmbeddedVideoComponent.props,
        host: { type: HTMLElement, optional: true },
    },
});

patch(readonlyVideoEmbedding, {
    getProps(host) {
        return { ...getEmbeddedProps(host), host };
    },
});

patch(ReadonlyEmbeddedVideoComponent.prototype, {
    setup() {
        super.setup?.(...arguments);
        if (!this.iframeRef) {
            this.iframeRef = useRef("iframeRef");
        }
        onMounted(() => {
            if (this.props.platform !== BILIBILI_PLATFORM) {
                return;
            }
            const iframe = this.iframeRef.el;
            const playerUrl = getBilibiliVideoUrl(
                this.props.videoId,
                this.props.params || {}
            ).toString();
            const cookieService = this.env.services?.website_cookies;
            prepareIframeForOptionalConsent(
                iframe,
                this.props.host,
                playerUrl,
                cookieService
            );
        });
    },

    get url() {
        if (this.props.platform !== BILIBILI_PLATFORM) {
            return super.url;
        }
        const playerUrl = getBilibiliVideoUrl(
            this.props.videoId,
            this.props.params || {}
        ).toString();
        return optionalCookiesNeedApproval(this.props.host) ? "about:blank" : playerUrl;
    },
});

export { optionalCookiesNeedApproval, prepareIframeForOptionalConsent };
