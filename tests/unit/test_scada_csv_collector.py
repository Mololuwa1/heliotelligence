"""Unit tests for collectors.scada_csv — no database, no network."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from heliotelligence.collectors.scada_csv import ScadaCsvCollector, _load_column_map, _move_file
from heliotelligence.config.site import SiteConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _site(scada_csv_dir: Path | None = None) -> SiteConfig:
    return SiteConfig(
        id="bracon-ash-001",
        name="Bracon Ash",
        latitude=52.56,
        longitude=1.13,
        timezone="Europe/London",
        capacity_kwp=250.0,
        solcast_resource_id="test-resource",
        tilt_deg=25.0,
        azimuth_deg=0.0,
        scada_csv_dir=scada_csv_dir,
    )


# ---------------------------------------------------------------------------
# _move_file
# ---------------------------------------------------------------------------

def test_move_file_success(tmp_path: Path):
    src = tmp_path / "data.csv"
    src.write_text("ts,val\n2024-01-01,1\n")
    dest_dir = tmp_path / "archive"
    dest_dir.mkdir()
    _move_file(src, dest_dir)
    assert not src.exists()
    assert (dest_dir / "data.csv").exists()


def test_move_file_does_not_raise_on_missing_src(tmp_path: Path, caplog):
    """Missing source file logs an error but does not raise."""
    src = tmp_path / "ghost.csv"
    dest_dir = tmp_path / "archive"
    dest_dir.mkdir()
    _move_file(src, dest_dir)  # should not raise


def test_move_file_preserves_filename(tmp_path: Path):
    src = tmp_path / "export_20240621.csv"
    src.write_text("x")
    dest_dir = tmp_path / "done"
    dest_dir.mkdir()
    _move_file(src, dest_dir)
    assert (dest_dir / "export_20240621.csv").exists()


# ---------------------------------------------------------------------------
# ScadaCsvCollector.poll — trivial early-exit paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_poll_none_scada_dir_returns_zero():
    collector = ScadaCsvCollector(_site(scada_csv_dir=None))
    assert await collector.poll() == 0


@pytest.mark.asyncio
async def test_poll_nonexistent_dir_returns_zero(tmp_path: Path):
    missing = tmp_path / "no_such_dir"
    collector = ScadaCsvCollector(_site(scada_csv_dir=missing))
    assert await collector.poll() == 0


@pytest.mark.asyncio
async def test_poll_empty_dir_returns_zero(tmp_path: Path):
    drop_dir = tmp_path / "drop"
    drop_dir.mkdir()
    collector = ScadaCsvCollector(_site(scada_csv_dir=drop_dir))

    mock_session = AsyncMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("heliotelligence.collectors.scada_csv.get_session_factory", return_value=mock_factory):
        count = await collector.poll()

    assert count == 0


# ---------------------------------------------------------------------------
# ScadaCsvCollector.poll — CSV processing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_poll_passes_uuid_site_id_to_parse_csv(tmp_path: Path, bracon_ash_csv: Path):
    """parse_csv must be called with the UUID string, not the raw YAML text id."""
    drop_dir = tmp_path / "drop"
    drop_dir.mkdir()
    shutil.copy(bracon_ash_csv, drop_dir / "bracon_ash_sample.csv")

    site = _site(scada_csv_dir=drop_dir)
    expected_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, site.id))

    mock_session = AsyncMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    captured: list = []

    async def fake_upsert_all(session, weather, meter, inverters, strings):
        captured.extend(weather + meter + inverters + strings)

    with patch("heliotelligence.collectors.scada_csv.get_session_factory", return_value=mock_factory), \
         patch("heliotelligence.collectors.scada_csv.upsert_all", side_effect=fake_upsert_all):
        await ScadaCsvCollector(site).poll()

    assert captured, "expected at least one row to be upserted"
    for row in captured:
        assert row.site_id == expected_uuid, (
            f"Expected UUID {expected_uuid!r}, got {row.site_id!r}"
        )


@pytest.mark.asyncio
async def test_poll_site_id_is_not_raw_text(tmp_path: Path, bracon_ash_csv: Path):
    drop_dir = tmp_path / "drop"
    drop_dir.mkdir()
    shutil.copy(bracon_ash_csv, drop_dir / "bracon_ash_sample.csv")

    site = _site(scada_csv_dir=drop_dir)
    captured: list = []

    mock_session = AsyncMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    async def fake_upsert_all(session, weather, meter, inverters, strings):
        captured.extend(weather + meter + inverters + strings)

    with patch("heliotelligence.collectors.scada_csv.get_session_factory", return_value=mock_factory), \
         patch("heliotelligence.collectors.scada_csv.upsert_all", side_effect=fake_upsert_all):
        await ScadaCsvCollector(site).poll()

    for row in captured:
        assert row.site_id != site.id


@pytest.mark.asyncio
async def test_poll_processes_csv_moves_to_archive(tmp_path: Path, bracon_ash_csv: Path):
    drop_dir = tmp_path / "drop"
    drop_dir.mkdir()
    shutil.copy(bracon_ash_csv, drop_dir / "bracon_ash_sample.csv")

    site = _site(scada_csv_dir=drop_dir)
    collector = ScadaCsvCollector(site)

    mock_session = AsyncMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("heliotelligence.collectors.scada_csv.get_session_factory", return_value=mock_factory), \
         patch("heliotelligence.collectors.scada_csv.upsert_all", AsyncMock()):
        count = await collector.poll()

    assert count == 1
    assert (drop_dir / "archive" / "bracon_ash_sample.csv").exists()
    assert not (drop_dir / "bracon_ash_sample.csv").exists()


@pytest.mark.asyncio
async def test_poll_failed_parse_moves_to_failed(tmp_path: Path):
    drop_dir = tmp_path / "drop"
    drop_dir.mkdir()
    bad_csv = drop_dir / "bad.csv"
    bad_csv.write_text("col_a,col_b,col_c\n1,2,3\n")  # no timestamp column → ValueError

    site = _site(scada_csv_dir=drop_dir)
    collector = ScadaCsvCollector(site)

    mock_session = AsyncMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("heliotelligence.collectors.scada_csv.get_session_factory", return_value=mock_factory):
        count = await collector.poll()

    assert count == 0
    assert (drop_dir / "failed" / "bad.csv").exists()
    assert not bad_csv.exists()


@pytest.mark.asyncio
async def test_poll_creates_archive_and_failed_dirs(tmp_path: Path):
    drop_dir = tmp_path / "drop"
    drop_dir.mkdir()

    site = _site(scada_csv_dir=drop_dir)
    collector = ScadaCsvCollector(site)

    mock_session = AsyncMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("heliotelligence.collectors.scada_csv.get_session_factory", return_value=mock_factory):
        await collector.poll()

    assert (drop_dir / "archive").is_dir()
    assert (drop_dir / "failed").is_dir()


@pytest.mark.asyncio
async def test_poll_processes_multiple_files(tmp_path: Path, bracon_ash_csv: Path):
    drop_dir = tmp_path / "drop"
    drop_dir.mkdir()
    for i in range(3):
        shutil.copy(bracon_ash_csv, drop_dir / f"export_{i}.csv")

    site = _site(scada_csv_dir=drop_dir)
    collector = ScadaCsvCollector(site)

    mock_session = AsyncMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("heliotelligence.collectors.scada_csv.get_session_factory", return_value=mock_factory), \
         patch("heliotelligence.collectors.scada_csv.upsert_all", AsyncMock()):
        count = await collector.poll()

    assert count == 3
    assert len(list((drop_dir / "archive").glob("*.csv"))) == 3


@pytest.mark.asyncio
async def test_poll_one_fail_does_not_stop_others(tmp_path: Path, bracon_ash_csv: Path):
    """A failed file should not prevent subsequent valid files being processed."""
    drop_dir = tmp_path / "drop"
    drop_dir.mkdir()
    bad_csv = drop_dir / "a_bad.csv"   # 'a' sorts first
    bad_csv.write_text("col_a,col_b,col_c\n1,2,3\n")  # no timestamp column → ValueError
    shutil.copy(bracon_ash_csv, drop_dir / "z_good.csv")  # 'z' sorts last

    site = _site(scada_csv_dir=drop_dir)
    collector = ScadaCsvCollector(site)

    mock_session = AsyncMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("heliotelligence.collectors.scada_csv.get_session_factory", return_value=mock_factory), \
         patch("heliotelligence.collectors.scada_csv.upsert_all", AsyncMock()):
        count = await collector.poll()

    assert count == 1
    assert (drop_dir / "failed" / "a_bad.csv").exists()
    assert (drop_dir / "archive" / "z_good.csv").exists()


# ---------------------------------------------------------------------------
# _load_column_map
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_load_column_map_returns_dict():
    mock_row_1 = MagicMock()
    mock_row_1.scada_field = "SMP10-GHI-F"
    mock_row_1.db_column = "ghi_wm2"
    mock_row_2 = MagicMock()
    mock_row_2.scada_field = "WS_AVG"
    mock_row_2.db_column = "wind_speed_ms"

    mock_result = MagicMock()
    mock_result.__iter__ = MagicMock(return_value=iter([mock_row_1, mock_row_2]))

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    result = await _load_column_map(mock_session, "bracon-ash-001")

    assert result == {"SMP10-GHI-F": "ghi_wm2", "WS_AVG": "wind_speed_ms"}


@pytest.mark.asyncio
async def test_load_column_map_view_missing_returns_empty():
    """DB exception (view not found) → empty dict, session rolled back."""
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=Exception("relation does not exist"))

    result = await _load_column_map(mock_session, "bracon-ash-001")

    assert result == {}
    mock_session.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_load_column_map_empty_view_returns_empty():
    mock_result = MagicMock()
    mock_result.__iter__ = MagicMock(return_value=iter([]))

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    result = await _load_column_map(mock_session, "bracon-ash-001")

    assert result == {}
