"""Regression guard for the C4 and C5 defects.

`debug` defaulted to True, and debug mode seeded admin@oricred.com with the
password "admin123" on any database with no users. `jwt_secret` defaulted to a
string published in the repository, so anyone could forge an admin token. Nothing
checked either at startup.

These tests pin the safe defaults and the guard that enforces them.
"""

import pytest

from app.config import (
    KNOWN_INSECURE_VALUES,
    MIN_SECRET_LENGTH,
    Settings,
    assert_production_safe,
)

GOOD_SECRET = "x" * MIN_SECRET_LENGTH


def _production(**overrides) -> Settings:
    base = {
        "debug": False,
        "jwt_secret": GOOD_SECRET,
        "session_secret": GOOD_SECRET,
        "database_url": "postgresql+asyncpg://u:p@localhost/oricred",
        "tsa_database_url": "postgresql+asyncpg://u:p@localhost/tendersa",
    }
    base.update(overrides)
    return Settings(**base)


class TestSafeDefaults:
    def test_debug_defaults_off(self):
        """C4: the seeded superuser was gated on this flag, which defaulted on."""
        assert Settings(_env_file=None).debug is False

    def test_signing_secrets_have_no_default(self):
        """C5: a shipped signing key is a published signing key."""
        s = Settings(_env_file=None)
        assert s.jwt_secret == ""
        assert s.session_secret == ""

    def test_tsa_database_url_has_no_default(self):
        """C2: production credentials must not live in the source tree."""
        assert Settings(_env_file=None).tsa_database_url == ""


class TestProductionGuard:
    def test_a_fully_configured_deployment_starts(self):
        assert_production_safe(_production())

    @pytest.mark.parametrize("name", ["jwt_secret", "session_secret", "tsa_database_url"])
    def test_unset_required_setting_is_rejected(self, name):
        with pytest.raises(RuntimeError, match=f"ORICRED_{name.upper()}"):
            assert_production_safe(_production(**{name: ""}))

    @pytest.mark.parametrize("placeholder", sorted(KNOWN_INSECURE_VALUES - {""}))
    def test_every_known_placeholder_is_rejected(self, placeholder):
        """An old .env that copied the shipped placeholders forward must not pass."""
        with pytest.raises(RuntimeError, match="ORICRED_JWT_SECRET"):
            assert_production_safe(_production(jwt_secret=placeholder))

    def test_short_secret_is_rejected(self):
        with pytest.raises(RuntimeError, match="at least 32 characters"):
            assert_production_safe(_production(jwt_secret="tooshort"))

    def test_all_problems_are_reported_together(self):
        """One boot, one readable list — not one error per restart."""
        with pytest.raises(RuntimeError) as exc:
            assert_production_safe(_production(jwt_secret="", session_secret="", tsa_database_url=""))
        message = str(exc.value)
        assert "ORICRED_JWT_SECRET" in message
        assert "ORICRED_SESSION_SECRET" in message
        assert "ORICRED_TSA_DATABASE_URL" in message

    def test_debug_mode_skips_the_guard(self):
        """Local development must stay frictionless."""
        assert_production_safe(Settings(_env_file=None, debug=True))


class TestBootstrapAdmin:
    def test_bootstrap_is_opt_in(self):
        """Neither variable set means no user is created — the C4 fix."""
        s = Settings(_env_file=None)
        assert s.bootstrap_admin_email == ""
        assert s.bootstrap_admin_password == ""

    def test_no_hardcoded_password_remains_in_the_source(self):
        """The literal that C4 was about must not reappear anywhere."""
        import pathlib

        app_dir = pathlib.Path(__file__).resolve().parent.parent / "app"
        for path in app_dir.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert "admin123" not in source, f"hardcoded password found in {path}"
