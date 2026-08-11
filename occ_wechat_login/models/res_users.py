import hashlib
import secrets
import unicodedata
from datetime import timedelta

from markupsafe import Markup
from psycopg2 import IntegrityError

from odoo import SUPERUSER_ID, Command, _, api, fields, models, tools
from odoo.exceptions import AccessDenied, ValidationError
from odoo.http import request

from ..const import (
    COMMUNITY_USERNAME_MAX_LENGTH,
    COMMUNITY_USERNAME_MIN_LENGTH,
    EMAIL_VERIFICATION_COOLDOWN_SECONDS,
    EMAIL_VERIFICATION_EXPIRATION_HOURS,
    EMAIL_VERIFICATION_SCOPE,
    EMAIL_VERIFICATION_WRITE_SENTINEL,
    EMAIL_VERIFICATION_WINDOW_LIMIT,
    EMAIL_VERIFICATION_WINDOW_SECONDS,
    INITIAL_PASSWORD_ALPHABET,
    INITIAL_PASSWORD_DIGITS,
    INITIAL_PASSWORD_LENGTH,
    INITIAL_PASSWORD_LOWERCASE,
    INITIAL_PASSWORD_SYMBOLS,
    INITIAL_PASSWORD_UPPERCASE,
    NEW_USER_TYPE_PORTAL,
    NEW_WECHAT_USER_LANGUAGE,
    WECHAT_LOGIN_GRANT_SESSION_KEY,
)


class ResUsers(models.Model):
    _inherit = "res.users"

    occ_wechat_unionid = fields.Char(
        string="WeChat UnionID",
        copy=False,
        index=True,
        groups="base.group_system",
    )
    occ_wechat_openid = fields.Char(
        string="WeChat OpenID",
        copy=False,
        index=True,
        groups="base.group_system",
    )
    occ_community_username = fields.Char(
        string="OdooCC Community Username",
        copy=False,
        index=True,
    )
    occ_community_username_normalized = fields.Char(
        copy=False,
        index=True,
        groups=fields.NO_ACCESS,
    )
    occ_pending_community_username = fields.Char(
        string="Pending OdooCC Community Username",
        copy=False,
        groups="base.group_system",
    )
    occ_pending_email = fields.Char(
        string="Pending Verified Email",
        copy=False,
        groups="base.group_system",
    )
    occ_verified_email = fields.Char(
        string="Verified Email",
        copy=False,
        index=True,
        groups="base.group_system",
    )
    occ_email_verification_nonce = fields.Char(
        copy=False,
        prefetch=False,
        groups=fields.NO_ACCESS,
    )
    occ_email_verification_sent_at = fields.Datetime(
        string="Verification Email Sent At",
        copy=False,
        groups="base.group_system",
    )
    occ_email_verified_at = fields.Datetime(
        string="Email Verified At",
        copy=False,
        groups="base.group_system",
    )
    occ_email_send_window_start = fields.Datetime(
        copy=False,
        groups=fields.NO_ACCESS,
    )
    occ_email_send_window_count = fields.Integer(
        copy=False,
        groups=fields.NO_ACCESS,
    )
    occ_email_verification_required = fields.Boolean(
        string="Email Verification Required",
        compute="_compute_occ_email_verification_required",
        groups="base.group_system",
    )

    _occ_wechat_unionid_unique = models.Constraint(
        "UNIQUE(occ_wechat_unionid)",
        "A WeChat UnionID can only be linked to one user.",
    )
    _occ_verified_email_unique = models.Constraint(
        "UNIQUE(occ_verified_email)",
        "A verified email address can only be linked to one OdooCC user.",
    )
    _occ_username_unique = models.Constraint(
        "UNIQUE(occ_community_username_normalized)",
        "An OdooCC community username can only be linked to one user.",
    )

    @api.depends(
        "occ_wechat_unionid",
        "occ_verified_email",
        "occ_community_username",
        "email",
    )
    def _compute_occ_email_verification_required(self):
        for user in self:
            user.occ_email_verification_required = user._occ_requires_email_verification()

    def _occ_requires_email_verification(self):
        self.ensure_one()
        if not self.occ_wechat_unionid:
            return False
        normalized_email = tools.email_normalize(self.email or "", strict=False)
        return (
            not self.occ_verified_email
            or normalized_email != self.occ_verified_email
            or not self.occ_community_username
        )

    @api.model
    def _occ_normalize_community_username(self, username):
        display_username = unicodedata.normalize(
            "NFKC", str(username or "")
        ).strip()
        if not (
            COMMUNITY_USERNAME_MIN_LENGTH
            <= len(display_username)
            <= COMMUNITY_USERNAME_MAX_LENGTH
        ):
            raise ValidationError(
                _(
                    "The community username must contain between %(min)s and %(max)s characters.",
                    min=COMMUNITY_USERNAME_MIN_LENGTH,
                    max=COMMUNITY_USERNAME_MAX_LENGTH,
                )
            )

        def is_letter_or_number(character):
            return unicodedata.category(character)[:1] in {"L", "N"}

        if (
            not is_letter_or_number(display_username[0])
            or not is_letter_or_number(display_username[-1])
            or any(
                not is_letter_or_number(character) and character not in {"_", "-"}
                for character in display_username
            )
        ):
            raise ValidationError(
                _(
                    "The community username may only contain letters, numbers, underscores, and hyphens, and must start and end with a letter or number."
                )
            )
        return display_username, display_username.casefold()

    @api.model
    def _occ_generate_initial_password(self):
        characters = [
            secrets.choice(INITIAL_PASSWORD_LOWERCASE),
            secrets.choice(INITIAL_PASSWORD_UPPERCASE),
            secrets.choice(INITIAL_PASSWORD_DIGITS),
            secrets.choice(INITIAL_PASSWORD_SYMBOLS),
        ]
        characters.extend(
            secrets.choice(INITIAL_PASSWORD_ALPHABET)
            for _index in range(INITIAL_PASSWORD_LENGTH - len(characters))
        )
        secrets.SystemRandom().shuffle(characters)
        return "".join(characters)

    def _occ_community_username_suggestion(self, nickname):
        """Return a safe, available username suggestion from a WeChat nickname."""
        self.ensure_one()
        if not isinstance(nickname, str) or not nickname.strip():
            return False
        try:
            display_username, normalized_username = (
                self._occ_normalize_community_username(nickname)
            )
            self._occ_check_community_username_available(normalized_username)
        except ValidationError:
            return False
        return display_username

    @api.model_create_multi
    def create(self, vals_list):
        prepared_values = []
        for values in vals_list:
            values = dict(values)
            if "occ_community_username" in values:
                if values["occ_community_username"]:
                    display_username, normalized_username = (
                        self._occ_normalize_community_username(
                            values["occ_community_username"]
                        )
                    )
                    values.update(
                        {
                            "name": display_username,
                            "signature": Markup("<div>%s</div>") % display_username,
                            "occ_community_username": display_username,
                            "occ_community_username_normalized": normalized_username,
                        }
                    )
                else:
                    values["occ_community_username_normalized"] = False
            prepared_values.append(values)
        return super().create(prepared_values)

    def write(self, values):
        values = dict(values)
        if "occ_community_username" in values:
            if values["occ_community_username"]:
                display_username, normalized_username = (
                    self._occ_normalize_community_username(
                        values["occ_community_username"]
                    )
                )
                values.update(
                    {
                        "name": display_username,
                        "signature": Markup("<div>%s</div>") % display_username,
                        "occ_community_username": display_username,
                        "occ_community_username_normalized": normalized_username,
                    }
                )
            else:
                values["occ_community_username_normalized"] = False

        if "email" not in values or self.env.context.get(
            "occ_skip_email_verification_reset"
        ) is EMAIL_VERIFICATION_WRITE_SENTINEL:
            return super().write(values)

        # Preserve Odoo's special authorization path for users writing only
        # their own self-writeable fields. Other callers must pass the normal
        # res.users ACL/record-rule and field access checks even when ``email``
        # is the only value and no standard user write remains below.
        write_users = self
        self_writeable = self._self_accessible_fields()[1]
        if self == self.env.user and all(
            field_name in self_writeable for field_name in values
        ):
            write_users = self.sudo()
        else:
            self.check_access("write")
            self._check_field_access(self._fields["email"], "write")

        # ``res.users.email`` is delegated to ``res.partner``. Its inverse may
        # bypass the partner override or retain a protected candidate value in
        # the user cache, obscuring the interception result. Split the write so
        # an unverified address can never become an official partner email.
        candidate_email = values.pop("email")
        linked_user_ids = write_users.sudo().filtered("occ_wechat_unionid").ids
        linked_users = write_users.browse(linked_user_ids)
        regular_users = write_users - linked_users

        result = True
        if values:
            result = super(ResUsers, write_users).write(values) and result
        if regular_users:
            result = super(ResUsers, regular_users).write(
                {"email": candidate_email}
            ) and result
        if linked_users:
            result = linked_users.partner_id.write(
                {"email": candidate_email}
            ) and result
        return result

    @api.model
    def _occ_wechat_login_for_unionid(self, unionid):
        digest = hashlib.sha256(unionid.encode("utf-8")).hexdigest()
        return f"wechat_{digest}@odoocc.invalid"

    @api.model
    def _occ_find_or_create_wechat_user(self, unionid, openid, nickname=None):
        unionid = (unionid or "").strip()
        openid = (openid or "").strip()
        if not unionid or not openid:
            raise AccessDenied()

        # ``/occ/wechat/callback`` is an ``auth='none'`` route, so its
        # environment has no current user (and therefore no default company).
        # Use the real superuser environment to preserve the standard
        # ``res.users.create()`` company defaults.
        users = (
            self.with_user(SUPERUSER_ID).sudo().with_context(active_test=False)
        )
        user = users.search([("occ_wechat_unionid", "=", unionid)], limit=1)
        created = False

        if not user:
            name = str(nickname or "").strip()[:256] or _("WeChat User")
            new_user_type = (
                self.env["res.config.settings"]
                .sudo()
                ._occ_wechat_get_new_user_type()
            )
            new_user_group = self.env.ref(
                "base.group_portal"
                if new_user_type == NEW_USER_TYPE_PORTAL
                else "base.group_user"
            )
            values = {
                "name": name,
                "login": self._occ_wechat_login_for_unionid(unionid),
                "lang": NEW_WECHAT_USER_LANGUAGE,
                "occ_wechat_unionid": unionid,
                "occ_wechat_openid": openid,
                "group_ids": [Command.set([new_user_group.id])],
                "active": True,
            }
            try:
                with self.env.cr.savepoint():
                    user = users.with_context(no_reset_password=True).create(values)
                    created = True
            except IntegrityError:
                user = users.search([("occ_wechat_unionid", "=", unionid)], limit=1)
                if not user:
                    raise

        if not user.active:
            raise AccessDenied(_("This WeChat-linked account has been disabled."))

        if openid and user.occ_wechat_openid != openid:
            user.write({"occ_wechat_openid": openid})
        return user, created

    @api.model
    def _occ_repair_legacy_mojibake_display_names(self):
        """Repair provably corrupted legacy names from the verified username.

        Older records can contain the Latin-1 rendering of UTF-8 bytes. Only
        names that exactly match that corrupted rendering of the verified
        community username are repaired, so manually edited names are kept.
        """
        users = self.sudo().with_context(active_test=False).search(
            [
                ("occ_wechat_unionid", "!=", False),
                ("occ_community_username", "!=", False),
            ]
        )
        repaired = users.browse()
        for user in users:
            current_name = user.name or ""
            verified_name = user.occ_community_username or ""
            legacy_mojibake_name = verified_name.encode("utf-8").decode("latin-1")
            if (
                current_name != verified_name
                and current_name == legacy_mojibake_name
            ):
                user.write({"name": verified_name})
                repaired |= user
        return repaired

    def _check_credentials(self, credential, env):
        try:
            return super()._check_credentials(credential, env)
        except AccessDenied as access_denied:
            if credential.get("type") != "occ_wechat":
                raise
            if not request or not env or not env.get("interactive"):
                raise access_denied

            grant = request.session.pop(WECHAT_LOGIN_GRANT_SESSION_KEY, None)
            supplied_token = credential.get("token")
            if not isinstance(grant, dict) or not isinstance(supplied_token, str):
                raise access_denied

            expected_token = grant.get("token")
            expected_uid = grant.get("uid")
            if (
                expected_uid != self.id
                or not isinstance(expected_token, str)
                or not secrets.compare_digest(expected_token, supplied_token)
                or not self.active
                or not self.occ_wechat_unionid
            ):
                raise access_denied

            return {
                "uid": self.id,
                "auth_method": "occ_wechat",
                "mfa": "default",
            }

    def _get_session_token_fields(self):
        return super()._get_session_token_fields() | {"occ_wechat_unionid"}

    @api.model
    def _occ_normalize_verification_email(self, email):
        raw_email = (email or "").strip()
        if not raw_email or not tools.single_email_re.match(raw_email):
            raise ValidationError(_("Please enter a valid email address."))
        normalized_email = tools.email_normalize(raw_email)
        if not normalized_email:
            raise ValidationError(_("Please enter a valid email address."))
        return normalized_email

    def _occ_check_email_available(self, normalized_email):
        self.ensure_one()
        duplicate = self.sudo().with_context(active_test=False).search_count(
            [
                ("id", "!=", self.id),
                "|",
                ("email_normalized", "=", normalized_email),
                ("login", "=ilike", tools.escape_psql(normalized_email)),
            ],
            limit=1,
        )
        if duplicate:
            raise ValidationError(
                _("This email address is already linked to another Odoo user.")
            )

    def _occ_check_community_username_available(self, normalized_username):
        self.ensure_one()
        duplicate = self.sudo().with_context(active_test=False).search_count(
            [
                ("id", "!=", self.id),
                ("occ_community_username_normalized", "=", normalized_username),
            ],
            limit=1,
        )
        if duplicate:
            raise ValidationError(
                _("This community username is already in use. Please choose another one.")
            )

    def _occ_prepare_email_verification(self, email, community_username):
        self.ensure_one()
        user = self.sudo()
        user.lock_for_update(allow_referencing=True)
        user.invalidate_recordset(
            [
                "active",
                "email",
                "occ_wechat_unionid",
                "occ_verified_email",
                "occ_email_verification_sent_at",
                "occ_email_send_window_start",
                "occ_email_send_window_count",
            ]
        )
        if not user.active or not user.occ_wechat_unionid:
            raise ValidationError(_("This account cannot verify an email address."))
        if not user._occ_requires_email_verification():
            raise ValidationError(_("This email address has already been verified."))

        normalized_email = user._occ_normalize_verification_email(email)
        user._occ_check_email_available(normalized_email)
        display_username, normalized_username = (
            user._occ_normalize_community_username(community_username)
        )
        user._occ_check_community_username_available(normalized_username)

        now = fields.Datetime.now()
        if (
            user.occ_email_verification_sent_at
            and now - user.occ_email_verification_sent_at
            < timedelta(seconds=EMAIL_VERIFICATION_COOLDOWN_SECONDS)
        ):
            raise ValidationError(
                _("Please wait before requesting another verification email.")
            )

        window_start = user.occ_email_send_window_start
        window_count = user.occ_email_send_window_count
        if (
            not window_start
            or now - window_start >= timedelta(seconds=EMAIL_VERIFICATION_WINDOW_SECONDS)
        ):
            window_start = now
            window_count = 0
        if window_count >= EMAIL_VERIFICATION_WINDOW_LIMIT:
            raise ValidationError(
                _("Too many verification emails have been requested. Please try again later.")
            )

        nonce = secrets.token_urlsafe(32)
        user.write(
            {
                "occ_pending_email": normalized_email,
                "occ_pending_community_username": display_username,
                "occ_email_verification_nonce": nonce,
                "occ_email_verification_sent_at": now,
                "occ_email_send_window_start": window_start,
                "occ_email_send_window_count": window_count + 1,
            }
        )
        token = tools.hash_sign(
            user.sudo().env,
            EMAIL_VERIFICATION_SCOPE,
            [user.id, nonce],
            expiration_hours=EMAIL_VERIFICATION_EXPIRATION_HOURS,
        )
        return normalized_email, token

    @api.model
    def _occ_decode_email_verification_token(self, token):
        if not isinstance(token, str) or not token or len(token) > 2048:
            return None
        try:
            payload = tools.verify_hash_signed(
                self.sudo().env,
                EMAIL_VERIFICATION_SCOPE,
                token,
            )
        except (TypeError, ValueError, UnicodeError):
            return None
        if (
            not isinstance(payload, list)
            or len(payload) != 2
            or not isinstance(payload[0], int)
            or not isinstance(payload[1], str)
        ):
            return None
        return payload

    @api.model
    def _occ_get_email_verification_user(self, token):
        payload = self._occ_decode_email_verification_token(token)
        if not payload:
            return self.browse()
        user_id, nonce = payload
        user = self.sudo().with_context(active_test=False).browse(user_id).exists()
        if (
            not user
            or not user.active
            or not user.occ_wechat_unionid
            or not user.occ_pending_email
            or not user.occ_pending_community_username
            or not user.occ_email_verification_nonce
            or not secrets.compare_digest(user.occ_email_verification_nonce, nonce)
        ):
            return self.browse()
        return user

    @api.model
    def _occ_confirm_email_verification(self, token):
        payload = self._occ_decode_email_verification_token(token)
        if not payload:
            raise ValidationError(_("This verification link is invalid or has expired."))
        user_id, nonce = payload
        user = self.sudo().with_context(active_test=False).browse(user_id).exists()
        if not user:
            raise ValidationError(_("This verification link is invalid or has expired."))

        user.lock_for_update(allow_referencing=True)
        user.invalidate_recordset(
            [
                "active",
                "occ_wechat_unionid",
                "occ_pending_email",
                "occ_pending_community_username",
                "occ_email_verification_nonce",
            ]
        )
        if (
            not user.active
            or not user.occ_wechat_unionid
            or not user.occ_pending_email
            or not user.occ_pending_community_username
            or not user.occ_email_verification_nonce
            or not secrets.compare_digest(user.occ_email_verification_nonce, nonce)
        ):
            raise ValidationError(_("This verification link is invalid or has expired."))

        normalized_email = user._occ_normalize_verification_email(user.occ_pending_email)
        user._occ_check_email_available(normalized_email)
        display_username, normalized_username = (
            user._occ_normalize_community_username(
                user.occ_pending_community_username
            )
        )
        user._occ_check_community_username_available(normalized_username)
        technical_login = user._occ_wechat_login_for_unionid(user.occ_wechat_unionid)
        initial_password = (
            user._occ_generate_initial_password()
            if user.login == technical_login
            else None
        )
        verification_values = {
            "login": normalized_email,
            "email": normalized_email,
            "occ_verified_email": normalized_email,
            "occ_community_username": display_username,
            "occ_community_username_normalized": normalized_username,
            "occ_pending_email": False,
            "occ_pending_community_username": False,
            "occ_email_verification_nonce": False,
            "occ_email_verified_at": fields.Datetime.now(),
        }
        if initial_password:
            verification_values["password"] = initial_password
        try:
            with self.env.cr.savepoint():
                user.with_context(
                    occ_skip_email_verification_reset=EMAIL_VERIFICATION_WRITE_SENTINEL
                ).write(verification_values)
        except IntegrityError as error:
            constraint_name = getattr(getattr(error, "diag", None), "constraint_name", "")
            if constraint_name == "res_users_occ_username_unique":
                raise ValidationError(
                    _(
                        "This community username is already in use. Please choose another one."
                    )
                ) from error
            raise ValidationError(
                _("This email address is already linked to another Odoo user.")
            ) from error
        return user, initial_password
