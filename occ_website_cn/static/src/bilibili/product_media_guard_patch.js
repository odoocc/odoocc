/** @odoo-module **/

import { CustomMediaDialog } from "@html_editor/fields/x2many_field/custom_media_dialog";
import { VideoSelector } from "@html_editor/main/media/media_dialog/video_selector";
import { patch } from "@web/core/utils/patch";


patch(CustomMediaDialog, {
    defaultProps: {
        ...CustomMediaDialog.defaultProps,
        extraTabs: CustomMediaDialog.defaultProps.extraTabs.map((tab) =>
            tab.Component === VideoSelector
                ? {
                      ...tab,
                      props: { ...tab.props, occDisableBilibili: true },
                  }
                : tab
        ),
    },
});
