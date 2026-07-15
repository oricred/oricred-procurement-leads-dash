from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logger = structlog.get_logger()

# ⚠️ READ-ONLY CONNECTION — This app must NEVER write to the Tenders-SA database.
# PostgreSQL session is forced to read-only via pool event listener.
TSA_DATABASE_URL = "postgresql+asyncpg://tendersa_app:11111111@10.0.1.175:5432/tendersa_prod"

# Tenders table field map — our names → TSA DB column names
TENDER_FIELD_MAP: dict[str, str] = {
    "id": "t.id",
    "tender_id": "t.tender_id",
    "title": "t.title",
    "reference_number": "t.reference_number",
    "description": "t.description",
    "province": "t.province",
    "estimated_value": "t.estimated_value",
    "closing_date": "t.closing_date",
    "status": "t.status",
    "type": "t.type",
    "publication_date": "t.publication_date",
    "source_organization": "t.source_organization",
    "source_organization_id": "t.source_organization_id",
    "tender_type": "t.type",
    "published_at": "t.publication_date",
    "buyer_org_id": "t.source_organization_id",
    "buyer_name": "t.source_organization",
    "category_id": "tc.canonical_name",
}

AWARD_FIELD_MAP: dict[str, str] = {
    "id": "a.id",
    "tender_id": "a.tender_id",
    "supplier_name": "a.supplier_name",
    "supplier_canonical_id": "a.supplier_canonical_id",
    "amount": "a.amount",
    "award_date": "a.award_date",
    "bee_level": "a.bee_level",
    "bee_points": "a.bee_points",
    "status": "a.status",
    "currency": "a.currency",
}

COMPANY_FIELD_MAP: dict[str, str] = {
    "id": "c.id",
    "name": "c.name",
    "registration_number": "c.registration_number",
    "bbbee_level": "c.bbbee_level",
    "contact_email": "c.contact_email",
    "contact_phone": "c.contact_phone",
    "website": "c.website",
    "tax_number": "c.tax_number",
    "industry_codes": "c.industry_codes",
}

ORGANIZATION_FIELD_MAP: dict[str, str] = {
    "id": "o.id",
    "name": "o.name",
    "organization_type": "o.organization_type",
    "contact_email": "o.contact_email",
    "contact_phone": "o.contact_phone",
    "website": "o.website",
    "confidence_score": "o.confidence_score",
    "normalized_name": "o.normalized_name",
    "slug": "o.slug",
    "contact_email_is_role_based": "o.contact_email_is_role_based",
    "registration_number": "o.registration_number",
    "bbbee_level": "o.bbbee_level",
}

BIDDER_FIELD_MAP: dict[str, str] = {
    "id": "b.id",
    "tender_id": "b.tender_id",
    "name": "b.name",
}

DIRECTOR_FIELD_MAP: dict[str, str] = {
    "id": "d.id",
    "company_id": "d.company_id",
    "full_name": "d.full_name",
    "email": "d.email",
    "phone": "d.phone",
    "equity_percentage": "d.equity_percentage",
}

KEY_PERSONNEL_FIELD_MAP: dict[str, str] = {
    "id": "kp.id",
    "profile_id": "kp.profile_id",
    "full_name": "kp.full_name",
    "role": "kp.role",
    "department": "kp.department",
    "email": "kp.email",
    "phone": "kp.phone",
}

SOURCE_DIRECTOR_FIELD_MAP: dict[str, str] = {
    "id": "sd.id",
    "organization_id": "sd.organization_id",
    "full_name": "sd.full_name",
    "email": "sd.email",
    "phone": "sd.phone",
    "position": "sd.position",
}

CATEGORY_FIELD_MAP: dict[str, str] = {
    "id": "tc.id",
    "name": "tc.name",
    "canonical_name": "tc.canonical_name",
    "parent_id": 'tc."parentId"',
}


def _map_fields(field_map: dict[str, str], fields: list[str] | None) -> str:
    if not fields:
        return ", ".join(field_map.values())
    selected = []
    for f in fields:
        col = field_map.get(f)
        if col:
            selected.append(f"{col} AS {f}")
    if not selected:
        return ", ".join(field_map.values())
    return ", ".join(selected)


def _build_tender_where(filters: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    if not filters:
        return "", {}
    clauses: list[str] = []
    params: dict[str, Any] = {}

    tender_ids = filters.get("tender_ids")
    if tender_ids:
        clauses.append("t.tender_id = ANY(:tender_ids)")
        params["tender_ids"] = tender_ids if isinstance(tender_ids, list) else [tender_ids]

    provinces = filters.get("province")
    if provinces:
        if isinstance(provinces, list):
            clauses.append("LOWER(t.province) = ANY(:province)")
            params["province"] = [p.lower() for p in provinces]
        else:
            clauses.append("LOWER(t.province) = :province")
            params["province"] = provinces.lower()

    categories = filters.get("category")
    if categories:
        if isinstance(categories, list):
            clauses.append("LOWER(tc.canonical_name) = ANY(:category)")
            params["category"] = [c.lower() for c in categories]
        else:
            clauses.append("LOWER(tc.canonical_name) = :category")
            params["category"] = categories.lower()

    value_min = filters.get("value_min")
    if value_min is not None:
        clauses.append("t.estimated_value >= :value_min")
        params["value_min"] = float(value_min)

    value_max = filters.get("value_max")
    if value_max is not None:
        clauses.append("t.estimated_value <= :value_max")
        params["value_max"] = float(value_max)

    since = filters.get("since")
    if since:
        clauses.append("t.publication_date >= :since OR t.created_at >= :since")
        params["since"] = since

    until = filters.get("until")
    if until:
        clauses.append("(t.publication_date <= :until OR t.created_at <= :until)")
        params["until"] = until

    status_list = filters.get("status")
    if status_list:
        if isinstance(status_list, list):
            clauses.append("t.status = ANY(:status_list)")
            params["status_list"] = status_list
        else:
            clauses.append("t.status = :status_list")
            params["status_list"] = status_list

    entity_types = filters.get("entity_type")
    if entity_types:
        if isinstance(entity_types, list):
            clauses.append("LOWER(o.organization_type) = ANY(:entity_type)")
            params["entity_type"] = [et.lower() for et in entity_types]
        else:
            clauses.append("LOWER(o.organization_type) = :entity_type")
            params["entity_type"] = entity_types.lower()

    closing_from = filters.get("closing_from")
    if closing_from:
        clauses.append("t.closing_date >= :closing_from")
        params["closing_from"] = closing_from

    closing_to = filters.get("closing_to")
    if closing_to:
        clauses.append("t.closing_date <= :closing_to")
        params["closing_to"] = closing_to

    search = filters.get("search")
    if search:
        clauses.append("(LOWER(t.title) LIKE :search OR LOWER(t.description) LIKE :search OR LOWER(t.reference_number) LIKE :search)")
        params["search"] = f"%{search.lower()}%"

    # Exclude categories
    exclude_cats = filters.get("_exclude_categories")
    if exclude_cats:
        if isinstance(exclude_cats, list):
            clauses.append("LOWER(tc.canonical_name) != ALL(:_exclude_cats)")
            params["_exclude_cats"] = [c.lower() for c in exclude_cats]
        else:
            clauses.append("LOWER(tc.canonical_name) != :_exclude_cats")
            params["_exclude_cats"] = exclude_cats.lower()

    where = " AND ".join(clauses)
    if where:
        where = "WHERE " + where
    return where, params


def _build_award_where(filters: dict[str, Any] | None) -> tuple[str, dict[str, Any], str]:
    join_clause = ""
    if not filters:
        return "", {}, ""
    clauses: list[str] = []
    params: dict[str, Any] = {}

    tender_ids = filters.get("tender_ids")
    if tender_ids:
        clauses.append("a.tender_id = ANY(:tender_ids)")
        params["tender_ids"] = tender_ids if isinstance(tender_ids, list) else [tender_ids]

    supplier = filters.get("supplier")
    if supplier:
        clauses.append("LOWER(a.supplier_name) LIKE :supplier")
        params["supplier"] = f"%{supplier.lower()}%"

    since = filters.get("since")
    if since:
        clauses.append("a.award_date >= :since")
        params["since"] = since

    until = filters.get("until") or filters.get("before")
    if until:
        clauses.append("a.award_date < :until")
        params["until"] = until

    value_min = filters.get("value_min")
    if value_min is not None:
        clauses.append("a.amount >= :value_min")
        params["value_min"] = float(value_min)

    value_max = filters.get("value_max")
    if value_max is not None:
        clauses.append("a.amount <= :value_max")
        params["value_max"] = float(value_max)

    buyer_org_id = filters.get("buyer_org_id")
    category_ids = filters.get("category_ids") or filters.get("category")
    provinces = filters.get("provinces") or filters.get("province")

    if buyer_org_id or category_ids or provinces:
        join_clause = "JOIN tenders t ON t.id = a.tender_id"
        if category_ids:
            join_clause += " LEFT JOIN tender_category_relations tcr ON tcr.tender_id = t.id LEFT JOIN tender_categories tc ON tc.id = tcr.category_id"

    if buyer_org_id:
        clauses.append("t.source_organization_id = :buyer_org_id")
        params["buyer_org_id"] = buyer_org_id

    if category_ids:
        values = category_ids if isinstance(category_ids, list) else [category_ids]
        clauses.append("LOWER(tc.canonical_name) = ANY(:category_ids)")
        params["category_ids"] = [str(v).lower() for v in values]

    if provinces:
        values = provinces if isinstance(provinces, list) else [provinces]
        clauses.append("LOWER(t.province) = ANY(:provinces)")
        params["provinces"] = [str(v).lower() for v in values]

    where = " AND ".join(clauses)
    if where:
        where = "WHERE " + where
    return where, params, join_clause
def _build_company_where(filters: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    if not filters:
        return "", {}
    clauses: list[str] = []
    params: dict[str, Any] = {}

    names = filters.get("names")
    if names:
        clauses.append("LOWER(c.name) = ANY(:names)")
        params["names"] = [n.lower() for n in (names if isinstance(names, list) else [names])]

    api_ids = filters.get("api_ids")
    if api_ids:
        clauses.append("c.id = ANY(:api_ids)")
        params["api_ids"] = api_ids if isinstance(api_ids, list) else [api_ids]

    registration = filters.get("registration")
    if registration:
        clauses.append("c.registration_number = :registration")
        params["registration"] = registration

    bee_min = filters.get("bee_level_min")
    if bee_min is not None:
        clauses.append("c.bbbee_level >= :bee_min")
        params["bee_min"] = int(bee_min)

    bee_max = filters.get("bee_level_max")
    if bee_max is not None:
        clauses.append("c.bbbee_level <= :bee_max")
        params["bee_max"] = int(bee_max)

    search = filters.get("search")
    if search:
        clauses.append("LOWER(c.name) LIKE :search")
        params["search"] = f"%{search.lower()}%"

    where = " AND ".join(clauses)
    if where:
        where = "WHERE " + where
    return where, params


def _build_org_where(filters: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    if not filters:
        return "", {}
    clauses: list[str] = []
    params: dict[str, Any] = {}

    ids_val = filters.get("ids")
    if ids_val:
        clauses.append("o.id = ANY(:ids)")
        params["ids"] = ids_val if isinstance(ids_val, list) else [ids_val]

    names = filters.get("names")
    if names:
        clauses.append("LOWER(o.name) = ANY(:names)")
        params["names"] = [n.lower() for n in (names if isinstance(names, list) else [names])]

    org_types = filters.get("type")
    if org_types:
        if isinstance(org_types, list):
            clauses.append("LOWER(o.organization_type) = ANY(:org_types)")
            params["org_types"] = [t.lower() for t in org_types]
        else:
            clauses.append("LOWER(o.organization_type) = :org_types")
            params["org_types"] = org_types.lower()

    where = " AND ".join(clauses)
    if where:
        where = "WHERE " + where
    return where, params


class TSADatabase:
    """
    ⚠️ READ-ONLY PostgreSQL interface to the Tenders-SA database.
    Builds parameterized SELECT queries from filter dicts.

    This class will NEVER write to the Tenders-SA database:
    - Connection URL enforces default_transaction_read_only=on
    - All queries are SELECT-only
    - Any attempt to execute INSERT/UPDATE/DELETE will be rejected by PostgreSQL
    """

    READ_ONLY = True  # Safety flag — intentionally no write methods exist

    def __init__(self):
        self._engine = create_async_engine(
            TSA_DATABASE_URL,
            echo=False,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            connect_args={
                "server_settings": {"default_transaction_read_only": "on"},
            },
        )
        self._session_factory = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False,
        )

    async def close(self):
        await self._engine.dispose()

    # ── Tenders ──

    async def query_tenders(
        self,
        filters: dict[str, Any] | None = None,
        fields: list[str] | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Query tenders with SQL-level filtering.
        Joins with categories and organizations for filter support.
        """
        select_cols = _map_fields(TENDER_FIELD_MAP, fields)
        where, params = _build_tender_where(filters)

        # Join with category_relations + categories for category filtering
        # Left join with source_organizations for entity_type filtering
        sql = f"""
            SELECT {select_cols}
            FROM tenders t
            LEFT JOIN tender_category_relations tcr ON tcr.tender_id = t.id
            LEFT JOIN tender_categories tc ON tc.id = tcr.category_id
            LEFT JOIN source_organizations o ON o.id = t.source_organization_id
            {where}
            ORDER BY t.created_at DESC
            LIMIT :limit OFFSET :offset
        """
        params["limit"] = limit
        params["offset"] = max(offset, 0)

        async with self._session_factory() as session:
            result = await session.execute(text(sql), params)
            rows = result.mappings().all()
            return [dict(row) for row in rows]

    async def query_tenders_from_config(
        self,
        config: dict[str, Any],
        since: str | None = None,
        fields: list[str] | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Build filters from qualification config and query tenders."""
        filters: dict[str, Any] = {}

        if since:
            filters["since"] = since

        value_rules = config.get("value_range", {}).get("rules", [])
        for rule in value_rules:
            if rule.get("min") is not None:
                filters["value_min"] = rule["min"]
            if rule.get("max") is not None:
                filters["value_max"] = rule["max"]

        sector_rules = config.get("sector", {}).get("rules", [])
        for rule in sector_rules:
            if rule.get("type") == "include" and rule.get("values"):
                filters["category"] = rule["values"]
            elif rule.get("type") == "exclude" and rule.get("values"):
                filters["_exclude_categories"] = rule["values"]

        province_rules = config.get("province", {}).get("rules", [])
        for rule in province_rules:
            if rule.get("type") == "include" and rule.get("values"):
                filters["province"] = rule["values"]

        entity_rules = config.get("entity_type", {}).get("rules", [])
        for rule in entity_rules:
            if rule.get("type") == "include" and rule.get("values"):
                filters["entity_type"] = rule["values"]

        default_fields = fields or [
            "tender_id", "title", "description", "estimated_value",
            "province", "closing_date", "status", "type",
            "source_organization_id", "source_organization",
            "publication_date", "category_id",
        ]

        return await self.query_tenders(filters, default_fields, limit)

    async def count_tenders(self, filters: dict[str, Any] | None = None) -> int:
        where, params = _build_tender_where(filters)
        sql = f"""
            SELECT COUNT(DISTINCT t.id)
            FROM tenders t
            LEFT JOIN tender_category_relations tcr ON tcr.tender_id = t.id
            LEFT JOIN tender_categories tc ON tc.id = tcr.category_id
            LEFT JOIN source_organizations o ON o.id = t.source_organization_id
            {where}
        """
        async with self._session_factory() as session:
            result = await session.execute(text(sql), params)
            return result.scalar() or 0

    # ── Awards ──

    async def query_awards(
        self,
        filters: dict[str, Any] | None = None,
        fields: list[str] | None = None,
        limit: int = 1000,
        direction: str = "desc",
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        select_cols = _map_fields(AWARD_FIELD_MAP, fields)
        where, params, join_clause = _build_award_where(filters)
        params["limit"] = limit
        params["offset"] = max(offset, 0)

        sql = f"""
            SELECT {select_cols}
            FROM tender_awards a
            {join_clause}
            {where}
            ORDER BY a.award_date {"ASC" if direction.lower() == "asc" else "DESC"} NULLS LAST
            LIMIT :limit OFFSET :offset
        """
        async with self._session_factory() as session:
            result = await session.execute(text(sql), params)
            rows = result.mappings().all()
            return [dict(row) for row in rows]

    # ── Companies ──

    async def query_companies(
        self,
        filters: dict[str, Any] | None = None,
        fields: list[str] | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        select_cols = _map_fields(COMPANY_FIELD_MAP, fields)
        where, params = _build_company_where(filters)
        params["limit"] = limit
        params["offset"] = max(offset, 0)

        sql = f"""
            SELECT {select_cols}
            FROM companies c
            {where}
            ORDER BY c.name
            LIMIT :limit OFFSET :offset
        """
        async with self._session_factory() as session:
            result = await session.execute(text(sql), params)
            rows = result.mappings().all()
            return [dict(row) for row in rows]

    # ── Organizations ──

    async def query_organizations(
        self,
        filters: dict[str, Any] | None = None,
        fields: list[str] | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        select_cols = _map_fields(ORGANIZATION_FIELD_MAP, fields)
        where, params = _build_org_where(filters)
        params["limit"] = limit
        params["offset"] = max(offset, 0)

        sql = f"""
            SELECT {select_cols}
            FROM source_organizations o
            {where}
            ORDER BY o.name
            LIMIT :limit OFFSET :offset
        """
        async with self._session_factory() as session:
            result = await session.execute(text(sql), params)
            rows = result.mappings().all()
            return [dict(row) for row in rows]

    # ── Bidders ──

    async def query_bidders(
        self,
        tender_ids: list[str] | None = None,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        select_cols = _map_fields(BIDDER_FIELD_MAP, None)
        sql = f"""
            SELECT {select_cols}
            FROM tender_bidders b
        """
        params: dict[str, Any] = {}
        if tender_ids:
            sql += " WHERE b.tender_id = ANY(:tender_ids)"
            params["tender_ids"] = tender_ids
        sql += " ORDER BY b.name"
        params["limit"] = limit
        params["offset"] = max(offset, 0)
        sql += " LIMIT :limit"

        async with self._session_factory() as session:
            result = await session.execute(text(sql), params)
            rows = result.mappings().all()
            return [dict(row) for row in rows]

    # ── Directors (company) ──

    async def query_directors(
        self,
        company_ids: list[str] | None = None,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        select_cols = _map_fields(DIRECTOR_FIELD_MAP, None)
        sql = f"""
            SELECT {select_cols}
            FROM directors d
        """
        params: dict[str, Any] = {}
        if company_ids:
            sql += " WHERE d.company_id = ANY(:company_ids)"
            params["company_ids"] = company_ids
        sql += " ORDER BY d.full_name"
        params["limit"] = limit
        params["offset"] = max(offset, 0)
        sql += " LIMIT :limit"

        async with self._session_factory() as session:
            result = await session.execute(text(sql), params)
            rows = result.mappings().all()
            return [dict(row) for row in rows]

    # ── Key Personnel (company profiles) ──

    async def query_key_personnel(
        self,
        profile_ids: list[str] | None = None,
        company_ids: list[str] | None = None,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        select_cols = _map_fields(KEY_PERSONNEL_FIELD_MAP, None)
        sql = f"""
            SELECT {select_cols}
            FROM key_personnel kp
        """
        params: dict[str, Any] = {}
        where_parts = []
        if profile_ids:
            where_parts.append("kp.profile_id = ANY(:profile_ids)")
            params["profile_ids"] = profile_ids
        if company_ids:
            sql += " JOIN company_profiles cp ON cp.id = kp.profile_id"
            where_parts.append("cp.company_id = ANY(:company_ids)")
            params["company_ids"] = company_ids
        if where_parts:
            sql += " WHERE " + " AND ".join(where_parts)
        sql += " ORDER BY kp.full_name"
        params["limit"] = limit
        params["offset"] = max(offset, 0)
        sql += " LIMIT :limit"

        async with self._session_factory() as session:
            result = await session.execute(text(sql), params)
            rows = result.mappings().all()
            return [dict(row) for row in rows]

    # ── Source Directors (buyer org) ──

    async def query_source_directors(
        self,
        organization_ids: list[str] | None = None,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        select_cols = _map_fields(SOURCE_DIRECTOR_FIELD_MAP, None)
        sql = f"""
            SELECT {select_cols}
            FROM source_directors sd
        """
        params: dict[str, Any] = {}
        if organization_ids:
            sql += " WHERE sd.organization_id = ANY(:organization_ids)"
            params["organization_ids"] = organization_ids
        sql += " ORDER BY sd.full_name"
        params["limit"] = limit
        params["offset"] = max(offset, 0)
        sql += " LIMIT :limit"

        async with self._session_factory() as session:
            result = await session.execute(text(sql), params)
            rows = result.mappings().all()
            return [dict(row) for row in rows]

    # ── Categories ──

    async def query_categories(self) -> list[dict[str, Any]]:
        select_cols = _map_fields(CATEGORY_FIELD_MAP, None)
        sql = f"SELECT {select_cols} FROM tender_categories tc ORDER BY tc.name"
        async with self._session_factory() as session:
            result = await session.execute(text(sql))
            rows = result.mappings().all()
            return [dict(row) for row in rows]
