from odoo import models

from ..const import EMAIL_VERIFICATION_WRITE_SENTINEL


class ResPartner(models.Model):
    _inherit = "res.partner"

    def write(self, values):
        if "email" not in values or self.env.context.get(
            "occ_skip_email_verification_reset"
        ) is EMAIL_VERIFICATION_WRITE_SENTINEL:
            return super().write(values)

        linked_users = (
            self.env["res.users"]
            .sudo()
            .with_context(active_test=False)
            .search(
                [
                    ("partner_id", "in", self.ids),
                    ("occ_wechat_unionid", "!=", False),
                ]
            )
        )
        if not linked_users:
            return super().write(values)

        candidate_email = values.get("email")
        normalized_candidate = False
        if candidate_email:
            normalized_candidate = linked_users[:1]._occ_normalize_verification_email(
                candidate_email
            )

        users_by_partner = {
            partner_id: linked_users.filtered(
                lambda user, partner_id=partner_id: user.partner_id.id == partner_id
            )
            for partner_id in linked_users.partner_id.ids
        }
        intercepted_partners = self.browse()
        passthrough_partners = self.browse()
        for partner in self:
            partner_users = users_by_partner.get(partner.id, self.env["res.users"])
            if partner_users and any(
                normalized_candidate != user.occ_verified_email
                for user in partner_users
            ):
                intercepted_partners |= partner
            else:
                passthrough_partners |= partner

        result = True
        if passthrough_partners:
            passthrough_values = dict(values)
            if normalized_candidate:
                passthrough_values["email"] = normalized_candidate
            result = super(ResPartner, passthrough_partners).write(
                passthrough_values
            ) and result

        if not intercepted_partners:
            return result

        # Never let an unverified candidate address reach the official partner
        # email field, mail followers, automations, or password-reset flows.
        # Other fields from the same write are preserved, while the new address
        # is staged on the linked user until the signed confirmation succeeds.
        intercepted_values = dict(values, email=False)
        result = super(ResPartner, intercepted_partners).write(
            intercepted_values
        ) and result

        intercepted_users = linked_users.filtered(
            lambda user: user.partner_id in intercepted_partners
        )
        for user in intercepted_users:
            reset_values = {
                "occ_verified_email": False,
                "occ_pending_email": normalized_candidate,
                "occ_pending_community_username": False,
                "occ_email_verification_nonce": False,
                "occ_email_verified_at": False,
            }
            user.write(reset_values)
        return result
