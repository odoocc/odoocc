from odoo import http
from odoo.addons.html_editor.controllers.main import HTML_Editor

from ..services import get_bilibili_video_url_data, is_bilibili_video_input


class OccWebsiteCnHtmlEditor(HTML_Editor):
    """Add Bilibili without changing the upstream providers."""

    @http.route()
    def video_url_data(
        self,
        video_url,
        autoplay=False,
        loop=False,
        hide_controls=False,
        hide_fullscreen=False,
        hide_dm_logo=False,
        hide_dm_share=False,
        start_from=False,
    ):
        if is_bilibili_video_input(video_url):
            # Bilibili 1.0 has no playback options. In particular, never turn
            # an editor's stale/background-video options into player params.
            if any(
                (
                    autoplay,
                    loop,
                    hide_controls,
                    hide_fullscreen,
                    hide_dm_logo,
                    hide_dm_share,
                    start_from,
                )
            ):
                return get_bilibili_video_url_data(None)
            return get_bilibili_video_url_data(video_url)
        return super().video_url_data(
            video_url,
            autoplay=autoplay,
            loop=loop,
            hide_controls=hide_controls,
            hide_fullscreen=hide_fullscreen,
            hide_dm_logo=hide_dm_logo,
            hide_dm_share=hide_dm_share,
            start_from=start_from,
        )
