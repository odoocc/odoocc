/** @odoo-module **/

let overlay;
let zoomScale = 1;

function updateZoom() {
    const content = overlay?.querySelector(".o_occ_markdown_zoom_content");
    const label = overlay?.querySelector(".o_occ_markdown_zoom_value");
    if (content) {
        content.style.transform = `scale(${zoomScale})`;
    }
    if (label) {
        label.textContent = `${Math.round(zoomScale * 100)}%`;
    }
}

function closeZoom() {
    overlay?.remove();
    overlay = null;
}

function openZoom(target) {
    closeZoom();
    zoomScale = 1;
    overlay = document.createElement("div");
    overlay.className = "o_occ_markdown_zoom_overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-label", "放大查看");
    const content = target.matches("img") ? document.createElement("img") : target.cloneNode(true);
    if (target.matches("img")) {
        content.src = target.currentSrc || target.src;
        content.alt = target.alt || "图片";
    }
    content.classList.add("o_occ_markdown_zoom_content");
    const toolbar = document.createElement("div");
    toolbar.className = "o_occ_markdown_zoom_toolbar";
    toolbar.innerHTML = `
        <button type="button" class="o_occ_markdown_zoom_out" title="缩小">−</button>
        <span class="o_occ_markdown_zoom_value">100%</span>
        <button type="button" class="o_occ_markdown_zoom_in" title="放大">＋</button>
        <button type="button" class="o_occ_markdown_zoom_reset" title="恢复100%">重置</button>
        <button type="button" class="o_occ_markdown_zoom_close" title="关闭">关闭</button>
    `;
    toolbar.querySelector(".o_occ_markdown_zoom_out").addEventListener("click", (event) => {
        event.stopPropagation();
        zoomScale = Math.max(0.25, zoomScale - 0.1);
        updateZoom();
    });
    toolbar.querySelector(".o_occ_markdown_zoom_in").addEventListener("click", (event) => {
        event.stopPropagation();
        zoomScale = Math.min(4, zoomScale + 0.1);
        updateZoom();
    });
    toolbar.querySelector(".o_occ_markdown_zoom_reset").addEventListener("click", (event) => {
        event.stopPropagation();
        zoomScale = 1;
        updateZoom();
    });
    toolbar.querySelector(".o_occ_markdown_zoom_close").addEventListener("click", closeZoom);
    toolbar.addEventListener("click", (event) => event.stopPropagation());
    overlay.append(content);
    overlay.append(toolbar);
    overlay.addEventListener("click", closeZoom);
    overlay.addEventListener(
        "wheel",
        (event) => {
            event.preventDefault();
            event.stopPropagation();
            zoomScale = Math.min(4, Math.max(0.25, zoomScale + (event.deltaY < 0 ? 0.1 : -0.1)));
            updateZoom();
        },
        { passive: false }
    );
    document.body.append(overlay);
}

function onMediaClick(event) {
    const target = event.target.closest?.(
        "img.o_occ_markdown_zoomable, .o_occ_markdown_mermaid_diagram"
    );
    if (!target || !document.body.contains(target)) {
        return;
    }
    event.preventDefault();
    openZoom(target);
}

document.addEventListener("click", onMediaClick);
document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
        closeZoom();
    }
});
