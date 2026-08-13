import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { getTabableElements } from "@web/core/utils/ui";
import { Interaction } from "@web/public/interaction";

import {
    buildShareEndpoint,
    getSensitiveParameterNames,
    getShareUrl,
    isMobileBrowser,
    isWechatBrowser,
} from "./share_utils";

const POPUP_FEATURES =
    "menubar=no,toolbar=no,resizable=yes,scrollbars=yes,height=550,width=600";

export class ShareCn extends Interaction {
    static selector = ".s_share_cn";
    dynamicContent = {
        ".s_share_cn_action": { "t-on-click.prevent": this.onShareClick },
        ".s_share_cn_dialog_confirm": { "t-on-click": this.onDialogConfirm },
        ".s_share_cn_dialog_close": { "t-on-click": this.closeDialog },
        ".s_share_cn_dialog": { "t-on-keydown": this.onDialogKeydown },
    };

    setup() {
        this.lastTriggerEl = null;
        this.pendingShare = null;
        this.dialogEl = this.el.querySelector(".s_share_cn_dialog");
        this.dialogTitleEl = this.dialogEl.querySelector(".s_share_cn_dialog_title");
        this.dialogBodyEl = this.dialogEl.querySelector(".s_share_cn_dialog_body");
        this.dialogConfirmEl = this.dialogEl.querySelector(".s_share_cn_dialog_confirm");
        this.dialogCancelEl = this.dialogEl.querySelector(".s_share_cn_dialog_cancel");
    }

    destroy() {
        this.closeDialog({ restoreFocus: false });
    }

    /** @param {MouseEvent} ev */
    async onShareClick(ev) {
        const triggerEl = ev.currentTarget;
        this.lastTriggerEl = triggerEl;
        const shareUrl = getShareUrl(browser.location.href);
        const sensitiveNames = getSensitiveParameterNames(shareUrl);
        const platform = triggerEl.dataset.platform;

        if (sensitiveNames.length) {
            this.pendingShare = { platform, shareUrl };
            this.showSensitiveParameterDialog(sensitiveNames);
            return;
        }
        await this.executeShare(platform, shareUrl);
    }

    async onDialogConfirm() {
        if (!this.pendingShare) {
            return;
        }
        const pendingShare = this.pendingShare;
        this.closeDialog();
        await this.executeShare(pendingShare.platform, pendingShare.shareUrl);
    }

    async executeShare(platform, shareUrl) {
        if (platform === "copy") {
            await this.copyShareUrl(shareUrl);
            return;
        }
        if (platform === "wechat") {
            await this.shareToWechat(shareUrl);
            return;
        }

        const targetUrl = buildShareEndpoint(platform, shareUrl, document.title);
        const popup = browser.open(targetUrl, "_blank", POPUP_FEATURES);
        if (!popup) {
            this.services.notification.add(
                _t("分享窗口被浏览器拦截，请允许本站弹出窗口后重试。"),
                { title: _t("无法打开分享窗口"), type: "warning" }
            );
            return;
        }
        try {
            // Keep the popup handle for blocker detection, then sever access
            // back to the source page to prevent reverse tabnabbing.
            popup.opener = null;
        } catch {
            // Some browsers expose a restricted WindowProxy. The share still
            // works, while the destination endpoints are fixed HTTPS origins.
        }
    }

    async copyShareUrl(shareUrl, options = {}) {
        try {
            if (typeof browser.navigator.clipboard?.writeText !== "function") {
                throw new Error("Clipboard API is unavailable");
            }
            await browser.navigator.clipboard.writeText(shareUrl);
            this.services.notification.add(options.successMessage || _t("页面链接已复制。"), {
                type: "success",
            });
            this.lastTriggerEl?.focus();
        } catch {
            this.showCopyFallback(shareUrl, options.failureMessage);
        }
    }

    async shareToWechat(shareUrl) {
        const userAgent = browser.navigator.userAgent || "";
        if (isWechatBrowser(userAgent)) {
            this.showMessageDialog(
                _t("分享到微信"),
                _t("请点击右上角菜单，再选择“分享给朋友”或“分享到朋友圈”。"),
                "wechat"
            );
            return;
        }
        if (isMobileBrowser(userAgent)) {
            await this.copyShareUrl(shareUrl, {
                successMessage: _t("链接已复制，请切换到微信后粘贴分享。"),
                failureMessage: _t("请复制下面的链接，再切换到微信后粘贴分享。"),
            });
            return;
        }
        this.showWechatQrDialog(shareUrl);
    }

    showWechatQrDialog(shareUrl) {
        try {
            // qrcode-generator 1.4.4 is vendored by this module and loaded from
            // the same Odoo asset bundle. It neither uses a CDN nor sends data.
            const qrcodeGenerator = globalThis.qrcode;
            if (typeof qrcodeGenerator !== "function") {
                throw new Error("qrcode-generator is unavailable");
            }
            const previousStringToBytes = qrcodeGenerator.stringToBytes;
            try {
                qrcodeGenerator.stringToBytes = qrcodeGenerator.stringToBytesFuncs["UTF-8"];
                const qr = qrcodeGenerator(0, "M");
                qr.addData(shareUrl);
                qr.make();
                this.dialogBodyEl.replaceChildren();
                const qrWrapperEl = document.createElement("div");
                qrWrapperEl.className = "s_share_cn_qr";
                const qrDocument = new DOMParser().parseFromString(
                    qr.createSvgTag({
                        cellSize: 5,
                        margin: 20,
                        scalable: true,
                    }),
                    "image/svg+xml"
                );
                if (qrDocument.querySelector("parsererror")) {
                    throw new Error("qrcode-generator produced invalid SVG");
                }
                const svgEl = document.importNode(qrDocument.documentElement, true);
                svgEl.setAttribute("role", "img");
                svgEl.setAttribute("aria-label", _t("当前页面链接二维码"));
                qrWrapperEl.append(svgEl);
                const hintEl = document.createElement("p");
                hintEl.className = "small text-muted mt-3 mb-0";
                hintEl.textContent = _t("打开微信扫一扫，扫描二维码后分享当前页面。");
                this.dialogBodyEl.append(qrWrapperEl, hintEl);
            } finally {
                qrcodeGenerator.stringToBytes = previousStringToBytes;
            }
            this.openDialog(_t("分享到微信"));
        } catch {
            this.showCopyFallback(shareUrl, _t("二维码生成失败，请改为手动复制链接。"));
        }
    }

    showSensitiveParameterDialog(sensitiveNames) {
        this.dialogBodyEl.replaceChildren();
        const messageEl = document.createElement("p");
        messageEl.className = "mb-2 s_share_cn_sensitive_warning";
        messageEl.textContent = _t(
            "当前链接包含疑似敏感参数（%s）。模块不会修改链接，请确认链接可以公开后再继续分享。",
            sensitiveNames.join(", ")
        );
        const detailEl = document.createElement("p");
        detailEl.className = "small text-muted mb-0";
        detailEl.textContent = _t("参数值不会显示在此提示中。");
        this.dialogBodyEl.append(messageEl, detailEl);
        this.openDialog(_t("请检查分享链接"), {
            confirmLabel: _t("继续分享"),
            cancelLabel: _t("取消"),
            focusEl: this.dialogCancelEl,
        });
    }

    showCopyFallback(shareUrl, message) {
        this.dialogBodyEl.replaceChildren();
        const messageEl = document.createElement("p");
        messageEl.textContent = message || _t("自动复制失败，请选择并手动复制下面的链接。");
        const inputEl = document.createElement("input");
        inputEl.className = "form-control s_share_cn_copy_fallback";
        inputEl.type = "text";
        inputEl.readOnly = true;
        inputEl.value = shareUrl;
        inputEl.setAttribute("aria-label", _t("待复制的页面链接"));
        this.dialogBodyEl.append(messageEl, inputEl);
        this.openDialog(_t("复制链接"), { focusEl: inputEl });
        inputEl.select();
    }

    showMessageDialog(title, message, kind) {
        this.dialogBodyEl.replaceChildren();
        const messageEl = document.createElement("p");
        messageEl.className = `mb-0 s_share_cn_${kind}_message`;
        messageEl.textContent = message;
        this.dialogBodyEl.append(messageEl);
        this.openDialog(title);
    }

    openDialog(title, options = {}) {
        this.dialogTitleEl.textContent = title;
        this.dialogEl.setAttribute("aria-label", title);
        this.dialogConfirmEl.hidden = !options.confirmLabel;
        this.dialogConfirmEl.textContent = options.confirmLabel || "";
        this.dialogCancelEl.textContent = options.cancelLabel || _t("关闭");
        this.dialogEl.hidden = false;
        this.dialogEl.classList.add("show");
        (options.focusEl || this.dialogEl.querySelector(".s_share_cn_dialog_close")).focus();
    }

    closeDialog(options = {}) {
        if (this.dialogEl.hidden) {
            this.pendingShare = null;
            return;
        }
        this.dialogEl.classList.remove("show");
        this.dialogEl.hidden = true;
        this.dialogBodyEl.replaceChildren();
        this.dialogConfirmEl.hidden = true;
        this.pendingShare = null;
        if (options.restoreFocus !== false && this.lastTriggerEl?.isConnected) {
            this.lastTriggerEl.focus();
        }
    }

    /** @param {KeyboardEvent} ev */
    onDialogKeydown(ev) {
        if (ev.key === "Escape") {
            ev.preventDefault();
            this.closeDialog();
            return;
        }
        if (ev.key !== "Tab") {
            return;
        }
        const tabableEls = getTabableElements(this.dialogEl);
        if (!tabableEls.length) {
            ev.preventDefault();
            this.dialogEl.focus();
            return;
        }
        const firstEl = tabableEls[0];
        const lastEl = tabableEls.at(-1);
        if (ev.shiftKey && (ev.target === firstEl || !this.dialogEl.contains(ev.target))) {
            ev.preventDefault();
            lastEl.focus();
        } else if (!ev.shiftKey && (ev.target === lastEl || !this.dialogEl.contains(ev.target))) {
            ev.preventDefault();
            firstEl.focus();
        }
    }
}

registry.category("public.interactions").add("occ_website_cn.share_cn", ShareCn);
