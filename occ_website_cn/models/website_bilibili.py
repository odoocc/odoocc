from odoo import models


class Website(models.Model):
    _inherit = "website"

    def _compute_blocked_third_party_domains(self):
        super()._compute_blocked_third_party_domains()
        for website in self:
            domains = website.blocked_third_party_domains.splitlines()
            # ``#ignore_default`` is Odoo's explicit administrator override for
            # the built-in watchlist. Respect it instead of silently restoring
            # a domain the administrator deliberately removed.
            ignores_defaults = (website.sudo().custom_blocked_third_party_domains or "").splitlines()
            if not (ignores_defaults and ignores_defaults[0].startswith("#ignore_default")) and (
                "bilibili.com" not in domains
            ):
                website.blocked_third_party_domains = "\n".join([*domains, "bilibili.com"])

    def _get_blocked_iframe_containers_classes(self):
        return super()._get_blocked_iframe_containers_classes() | {
            "occ_bilibili_embedded_video",
        }
