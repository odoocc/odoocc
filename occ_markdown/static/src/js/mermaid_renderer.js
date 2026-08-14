/** @odoo-module **/

const MERMAID_SELECTOR = "pre.o_occ_markdown_mermaid[data-occ-mermaid-state='pending']";
const MERMAID_SCRIPT_URL =
    "/occ_markdown/static/lib/vditor/dist/js/mermaid/mermaid.min.js?v=11.16.1";

let mermaidLoader;
let diagramSequence = 0;
let initialized = false;

export function loadMermaid() {
    if (window.mermaid) {
        return Promise.resolve(window.mermaid);
    }
    if (!mermaidLoader) {
        mermaidLoader = new Promise((resolve, reject) => {
            const script = document.createElement("script");
            script.src = MERMAID_SCRIPT_URL;
            script.async = true;
            script.dataset.occMermaidRuntime = "1";
            script.addEventListener("load", () =>
                window.mermaid
                    ? resolve(window.mermaid)
                    : reject(new Error("Mermaid 运行资源未正确加载"))
            );
            script.addEventListener("error", () =>
                reject(new Error("Mermaid 运行资源加载失败"))
            );
            document.head.append(script);
        });
    }
    return mermaidLoader;
}

export async function renderMermaidDiagrams(root = document) {
    const diagrams = Array.from(root.querySelectorAll(MERMAID_SELECTOR));
    if (!diagrams.length) {
        return;
    }
    for (const diagram of diagrams) {
        diagram.dataset.occMermaidState = "rendering";
    }
    try {
        const mermaid = await loadMermaid();
        if (!initialized) {
            mermaid.initialize({
                startOnLoad: false,
                securityLevel: "strict",
                theme: "default",
            });
            initialized = true;
        }
        for (const diagram of diagrams) {
            const source = diagram.textContent;
            try {
                const result = await mermaid.render(
                    `occ_mermaid_${Date.now()}_${diagramSequence++}`,
                    source
                );
                const container = document.createElement("div");
                container.className = "o_occ_markdown_mermaid_diagram overflow-auto";
                container.dataset.occMermaidState = "rendered";
                container.innerHTML = result.svg;
                diagram.replaceWith(container);
            } catch {
                diagram.dataset.occMermaidState = "error";
                diagram.classList.add("alert", "alert-warning");
                diagram.title = "流程图渲染失败，请检查 Mermaid 语法。";
            }
        }
    } catch {
        for (const diagram of diagrams) {
            diagram.dataset.occMermaidState = "error";
            diagram.classList.add("alert", "alert-warning");
            diagram.title = "流程图运行资源加载失败。";
        }
    }
}

function startMermaidObserver() {
    renderMermaidDiagrams();
    const observer = new MutationObserver(() => renderMermaidDiagrams());
    observer.observe(document.body, { childList: true, subtree: true });
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", startMermaidObserver, { once: true });
} else {
    startMermaidObserver();
}
