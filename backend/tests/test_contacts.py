from app.models.contact import Contact
from app.schemas.contact import ContactCreate, ContactRead, ContactUpdate
from app.services.contact_enrichment import _split_name


class TestSplitName:
    def test_full_name(self):
        assert _split_name("John Peter Doe") == ("John", "Peter Doe")

    def test_single_name(self):
        assert _split_name("John") == ("John", "")

    def test_empty(self):
        assert _split_name("") == ("", "")

    def test_whitespace_padded(self):
        assert _split_name("  John  Doe  ") == ("John", "Doe")


class TestContactModel:
    def test_fields_exist(self):
        fields = {c.name for c in Contact.__table__.columns}
        assert "first_name" in fields
        assert "last_name" in fields
        assert "email" in fields
        assert "phone_direct" in fields
        assert "phone_mobile" in fields
        assert "linkedin_url" in fields
        assert "is_primary" in fields
        assert "company_id" in fields
        assert "organization_id" in fields
        assert "source" in fields

    def test_email_uniqueness_is_enforced_per_entity(self):
        indexes = {i.name: i for i in Contact.__table__.indexes}
        assert "uq_contact_company_email" in indexes
        assert "uq_contact_org_email" in indexes
        assert indexes["uq_contact_company_email"].unique
        assert indexes["uq_contact_org_email"].unique

    def test_email_uniqueness_is_partial(self):
        """Contacts known only by phone store email as NULL, and any number of
        those must coexist for one company. A full unique constraint let only
        one exist — see remediation-01 section 3."""
        for name in ("uq_contact_company_email", "uq_contact_org_email"):
            index = next(i for i in Contact.__table__.indexes if i.name == name)
            predicate = index.dialect_options["postgresql"].get("where")
            assert predicate is not None, f"{name} must be partial"
            assert "email IS NOT NULL" in str(predicate)


class TestContactSchema:
    def test_contact_read_from_attributes(self):
        assert ContactRead.model_config.get("from_attributes") is True

    def test_contact_create_required_fields(self):
        schema = ContactCreate(first_name="John", last_name="Doe", email="john@test.com")
        assert schema.first_name == "John"
        assert schema.last_name == "Doe"
        assert schema.email == "john@test.com"
        assert schema.is_primary is False

    def test_contact_update_all_optional(self):
        schema = ContactUpdate()
        assert schema.first_name is None
        assert schema.last_name is None
        assert schema.email is None

    def test_contact_create_defaults(self):
        schema = ContactCreate(first_name="A", last_name="B", email="a@b.com")
        assert schema.phone_direct is None
        assert schema.phone_mobile is None
        assert schema.linkedin_url is None
        assert schema.is_primary is False
        assert schema.notes is None
