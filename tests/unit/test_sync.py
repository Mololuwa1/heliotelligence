"""Unit tests for db.sync.sync_sites — mocked session, no database."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from heliotelligence.config.site import SiteConfig
from heliotelligence.db.sync import _DEFAULT_STRINGS_PER_INV, sync_sites


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_sites() -> list[SiteConfig]:
    return [
        SiteConfig(
            id="bracon-ash-001",
            name="Bracon Ash",
            latitude=52.5612,
            longitude=1.1346,
            timezone="Europe/London",
            capacity_kwp=4998.6,
            solcast_resource_id="res-bracon",
            tilt_deg=20.0,
            azimuth_deg=0.0,
        ),
        SiteConfig(
            id="norfolk-south-002",
            name="Norfolk South",
            latitude=52.6101,
            longitude=0.9812,
            timezone="Europe/London",
            capacity_kwp=9750.0,
            solcast_resource_id="res-norfolk",
            tilt_deg=25.0,
            azimuth_deg=5.0,
        ),
    ]


# ---------------------------------------------------------------------------
# Return value
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sync_sites_returns_count():
    session = AsyncMock()
    count = await sync_sites(_make_sites(), session)
    assert count == 2


@pytest.mark.asyncio
async def test_sync_sites_empty_returns_zero():
    session = AsyncMock()
    count = await sync_sites([], session)
    assert count == 0


# ---------------------------------------------------------------------------
# session.execute called once per site
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sync_sites_executes_once_per_site():
    session = AsyncMock()
    await sync_sites(_make_sites(), session)
    assert session.execute.call_count == 2


@pytest.mark.asyncio
async def test_sync_sites_empty_does_not_execute():
    session = AsyncMock()
    await sync_sites([], session)
    session.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Correct parameter values passed to session.execute
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sync_sites_first_site_params():
    """site_id, site_name, lat/lon, capacity and defaults are correct."""
    session = AsyncMock()
    sites = _make_sites()
    await sync_sites(sites, session)

    # execute is called as: session.execute(sql_text, params_dict)
    first_call_params = session.execute.call_args_list[0][0][1]

    assert first_call_params["site_id"] == uuid.uuid5(uuid.NAMESPACE_DNS, "bracon-ash-001")
    assert isinstance(first_call_params["site_id"], uuid.UUID)
    assert first_call_params["site_name"] == "Bracon Ash"
    assert first_call_params["site_code"] == "bracon-ash-001"   # plain text id; conflict target
    assert first_call_params["latitude"] == pytest.approx(52.5612)
    assert first_call_params["longitude"] == pytest.approx(1.1346)
    assert first_call_params["timezone"] == "Europe/London"
    assert first_call_params["capacity_kwp"] == pytest.approx(4998.6)
    assert first_call_params["strings_per_inv"] == _DEFAULT_STRINGS_PER_INV
    assert first_call_params["subsidy_type"] is None


@pytest.mark.asyncio
async def test_sync_sites_second_site_params():
    session = AsyncMock()
    sites = _make_sites()
    await sync_sites(sites, session)

    second_call_params = session.execute.call_args_list[1][0][1]

    assert second_call_params["site_id"] == uuid.uuid5(uuid.NAMESPACE_DNS, "norfolk-south-002")
    assert isinstance(second_call_params["site_id"], uuid.UUID)
    assert second_call_params["site_name"] == "Norfolk South"
    assert second_call_params["site_code"] == "norfolk-south-002"
    assert second_call_params["latitude"] == pytest.approx(52.6101)
    assert second_call_params["longitude"] == pytest.approx(0.9812)
    assert second_call_params["capacity_kwp"] == pytest.approx(9750.0)
    assert second_call_params["strings_per_inv"] == _DEFAULT_STRINGS_PER_INV
    assert second_call_params["subsidy_type"] is None


@pytest.mark.asyncio
async def test_sync_sites_strings_per_inv_default():
    """Default strings_per_inv is 32 for all sites."""
    session = AsyncMock()
    await sync_sites(_make_sites(), session)
    for c in session.execute.call_args_list:
        assert c[0][1]["strings_per_inv"] == 32


@pytest.mark.asyncio
async def test_sync_sites_subsidy_type_null():
    """subsidy_type is always None (not yet in SiteConfig)."""
    session = AsyncMock()
    await sync_sites(_make_sites(), session)
    for c in session.execute.call_args_list:
        assert c[0][1]["subsidy_type"] is None


@pytest.mark.asyncio
async def test_sync_sites_site_code_is_plain_text_id():
    """site_code stores the plain text YAML id; site_id is the derived UUID."""
    session = AsyncMock()
    sites = _make_sites()
    await sync_sites(sites, session)
    for i, site in enumerate(sites):
        params = session.execute.call_args_list[i][0][1]
        assert params["site_code"] == site.id
        assert params["site_id"] != site.id  # UUID, not the raw text


@pytest.mark.asyncio
async def test_sync_sites_uuid_is_deterministic():
    """Same site.id must always produce the same UUID (called twice)."""
    session1, session2 = AsyncMock(), AsyncMock()
    sites = _make_sites()
    await sync_sites(sites, session1)
    await sync_sites(sites, session2)
    for i in range(len(sites)):
        p1 = session1.execute.call_args_list[i][0][1]
        p2 = session2.execute.call_args_list[i][0][1]
        assert p1["site_id"] == p2["site_id"]


@pytest.mark.asyncio
async def test_sync_sites_uuid_version_is_5():
    session = AsyncMock()
    await sync_sites(_make_sites(), session)
    for c in session.execute.call_args_list:
        assert c[0][1]["site_id"].version == 5


# ---------------------------------------------------------------------------
# SQL text object is passed (not a raw string)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sync_sites_passes_sqlalchemy_text_object():
    """The first positional arg to execute must be a SQLAlchemy ClauseElement."""
    from sqlalchemy.sql.elements import ClauseElement

    session = AsyncMock()
    await sync_sites(_make_sites()[:1], session)

    sql_arg = session.execute.call_args_list[0][0][0]
    assert isinstance(sql_arg, ClauseElement)


# ---------------------------------------------------------------------------
# Caller is responsible for commit — sync_sites does NOT commit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sync_sites_does_not_commit():
    session = AsyncMock()
    await sync_sites(_make_sites(), session)
    session.commit.assert_not_called()
