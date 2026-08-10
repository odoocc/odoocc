/** @odoo-module **/

import { registry } from "@web/core/registry";

export const approvalDrawerService = {
    dependencies: ["overlay"],
    start(env, { overlay }) {
        const opened = new Map();

        function add(Component, props = {}, options = {}) {
            const key = options.key || Symbol("occ_approval_drawer");
            if (opened.has(key)) {
                return opened.get(key);
            }

            let remove;
            const close = () => remove?.();
            remove = overlay.add(
                Component,
                { ...props, close },
                {
                    onRemove: () => {
                        opened.delete(key);
                        options.onClose?.();
                    },
                }
            );
            opened.set(key, close);
            return close;
        }

        function closeAll() {
            for (const close of [...opened.values()]) {
                close();
            }
        }

        return { add, closeAll };
    },
};

registry.category("services").add("occ_approval_drawer", approvalDrawerService);
