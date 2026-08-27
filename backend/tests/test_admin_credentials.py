"""Regression guard for the C3 defect.

GET /admin/credentials masked secrets as `value[:4] + "****"`, while the PUT
handler's "unchanged" guard tested `startswith("****")`. The guard never matched,
so the Admin page posting its own form state back wrote each mask over the real
credential. Editing one unrelated field destroyed every API key and password.

These tests exercise mask_secrets/merge_secrets directly — the pair that the two
route handlers now delegate to.
"""

from app.services.admin_config import (
    SECRET_SENTINEL,
    is_secret_field,
    mask_secrets,
    merge_secrets,
)


class TestIsSecretField:
    def test_detects_known_markers(self):
        assert is_secret_field("tsa_api_key")
        assert is_secret_field("smtp_password")
        assert is_secret_field("session_secret")
        assert is_secret_field("monday_api_token")

    def test_detection_is_case_insensitive(self):
        """The previous check was case-sensitive, so API_KEY leaked in clear text."""
        assert is_secret_field("API_KEY")
        assert is_secret_field("SMTP_Password")
        assert is_secret_field("Session_SECRET")

    def test_non_secret_fields_pass_through(self):
        assert not is_secret_field("tsa_base_url")
        assert not is_secret_field("monday_board_id")
        assert not is_secret_field("email_from")
        assert not is_secret_field("smtp_host")


class TestMaskSecrets:
    def test_secret_is_replaced_entirely(self):
        masked = mask_secrets({"tsa_api_key": "sk-live-abcdef123456"})
        assert masked["tsa_api_key"] == SECRET_SENTINEL

    def test_mask_leaks_no_prefix_of_the_real_value(self):
        """The old mask exposed the first four characters of every secret."""
        secret = "sk-live-abcdef123456"
        masked = mask_secrets({"tsa_api_key": secret})["tsa_api_key"]
        for length in range(1, len(secret) + 1):
            assert not masked.startswith(secret[:length])

    def test_unset_secret_stays_empty(self):
        assert mask_secrets({"tsa_api_key": ""})["tsa_api_key"] == ""

    def test_non_secret_values_are_untouched(self):
        config = {"tsa_base_url": "https://api.tenders-sa.org", "smtp_port": 587}
        assert mask_secrets(config) == config


class TestMergeSecrets:
    def test_editing_one_field_preserves_every_other_secret(self):
        """The C3 regression, end to end: mask, edit one field, save."""
        stored = {
            "tsa_api_key": "sk-live-abcdef123456",
            "monday_api_key": "mk-live-zyxwvu987654",
            "smtp_password": "hunter2-correct-horse",
            "smtp_host": "smtp.old.example.com",
        }
        # What the Admin page receives and holds in form state.
        form = mask_secrets(stored)
        # The operator corrects a typo in one non-secret field and saves.
        form["smtp_host"] = "smtp.new.example.com"

        merged = merge_secrets(form, stored)

        assert merged["tsa_api_key"] == "sk-live-abcdef123456"
        assert merged["monday_api_key"] == "mk-live-zyxwvu987654"
        assert merged["smtp_password"] == "hunter2-correct-horse"
        assert merged["smtp_host"] == "smtp.new.example.com"

    def test_a_new_value_replaces_the_stored_one(self):
        stored = {"tsa_api_key": "sk-old"}
        merged = merge_secrets({"tsa_api_key": "sk-new"}, stored)
        assert merged["tsa_api_key"] == "sk-new"

    def test_empty_string_clears_a_credential(self):
        stored = {"tsa_api_key": "sk-old"}
        merged = merge_secrets({"tsa_api_key": ""}, stored)
        assert merged["tsa_api_key"] == ""

    def test_fields_absent_from_the_payload_are_preserved(self):
        stored = {"tsa_api_key": "sk-old", "smtp_host": "smtp.example.com"}
        merged = merge_secrets({"smtp_host": "other.example.com"}, stored)
        assert merged["tsa_api_key"] == "sk-old"

    def test_sentinel_for_an_unset_field_does_not_invent_a_value(self):
        stored = {"tsa_api_key": ""}
        merged = merge_secrets({"tsa_api_key": SECRET_SENTINEL}, stored)
        assert merged["tsa_api_key"] == ""

    def test_repeated_round_trips_are_stable(self):
        """Saving the form five times must not degrade the stored secret."""
        stored = {"tsa_api_key": "sk-live-abcdef123456", "smtp_host": "a"}
        for _ in range(5):
            stored = merge_secrets(mask_secrets(stored), stored)
        assert stored["tsa_api_key"] == "sk-live-abcdef123456"
