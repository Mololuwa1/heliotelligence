"""P0 regressions execute real SQL over two alternative model series.

SQLite provides an isolated unit database without service/dependency setup.
The adapter supplies PostgreSQL date_trunc and the UUID cast used by analysis;
all source predicates, bindings, aggregates and upsert conflict SQL run unchanged.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.unit.test_engine.test_pipeline import _site

from heliotelligence.analysis import anomaly, degradation
from heliotelligence.api.routers import analysis, benchmarking, expected_energy, reports
from heliotelligence.benchmarking import losses, performance_ratio
from heliotelligence.engine import pipeline
from heliotelligence.engine.expected_energy_source import (
    LEGACY_EXPECTED_ENERGY_SOURCE,
    validate_expected_energy_source,
)
from heliotelligence.engine.upsert import upsert_expected_energy
from heliotelligence.engine.weather_query import get_latest_expected_energy_time

START = datetime(2024, 6, 21, 10, tzinfo=UTC)
END = START + timedelta(hours=2)
SITE = str(uuid.uuid5(uuid.NAMESPACE_DNS, "site-001"))
ALT = "test_model_b"


class Result:
    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self.names = [item[0] for item in cursor.description] if cursor.description else []
        self.rows = [tuple(row) for row in cursor.fetchall()]

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows

    def fetchone(self) -> tuple[Any, ...] | None:
        if self.names == ["MAX(time)"] and self.rows[0][0] is not None:
            return (datetime.fromisoformat(self.rows[0][0]),)
        return self.rows[0] if self.rows else None

    def keys(self) -> list[str]:
        return self.names

    def all(self) -> list[tuple[Any, ...]]:
        return self.rows


class Database:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:", check_same_thread=False)
        self.connection.create_function("date_trunc", 2, self.date_trunc)
        self.connection.executescript("""
            CREATE TABLE expected_energy (
                time TEXT, site_id TEXT, source TEXT, p_ac_kw REAL,
                p_dc_kw REAL, p_dc_stc_kw REAL, poa_total_wm2 REAL,
                t_cell_c REAL, tier_used INTEGER, fit_quality TEXT, quality INTEGER,
                PRIMARY KEY (time, site_id, source)
            );
            CREATE TABLE meter_readings (
                ts TEXT, site_id TEXT, p_ac_kw REAL, e_exported_kwh REAL
            );
        """)
        self.calls: list[tuple[str, Any]] = []

    @staticmethod
    def date_trunc(unit: str, value: str) -> str:
        dt = datetime.fromisoformat(value).replace(minute=0, second=0, microsecond=0)
        return (dt.replace(hour=0) if unit == "day" else dt).isoformat()

    async def execute(self, statement: Any, parameters: Any) -> Result:
        sql = str(statement)
        self.calls.append((sql, parameters))
        sql = sql.replace("CAST(:site_id AS uuid)", ":site_id")
        sql = sql.replace("CAST(mr.site_id AS uuid)", "mr.site_id")

        def convert(row: dict[str, Any]) -> dict[str, Any]:
            return {
                key: value.isoformat() if isinstance(value, datetime) else value
                for key, value in row.items()
            }

        if isinstance(parameters, list):
            cursor = self.connection.executemany(sql, [convert(row) for row in parameters])
        else:
            cursor = self.connection.execute(sql, convert(parameters))
        return Result(cursor)

    @asynccontextmanager
    async def session(self) -> Any:
        yield self


@pytest.fixture
def db() -> Iterator[Database]:
    database = Database()
    yield database
    database.connection.close()


def frame(power: float = 100.0, hour: int = 10) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "p_ac_kw": [power, power],
            "p_dc_kw": [power + 5, power + 5],
            "p_dc_stc_kw": [power + 10, power + 10],
            "poa_total_wm2": [1000.0, 1000.0],
            "t_cell_c": [25.0, 25.0],
            "tier_used": [1, 1],
            "fit_quality": ["high", "high"],
        },
        index=pd.date_range(START.replace(hour=hour), periods=2, freq="h"),
    )


async def seed(db: Database) -> None:
    await upsert_expected_energy(_site(), frame(), db)
    await upsert_expected_energy(_site(), frame(200), db, source=ALT)
    for time in frame().index:
        db.connection.execute(
            "INSERT INTO meter_readings VALUES (?, ?, ?, ?)", (time.isoformat(), SITE, 100.0, 100.0)
        )


@pytest.mark.parametrize("source", ["physics_sdm", "test_shadow", "Candidate_v2", "x y"])
def test_valid_source_is_exact(source: str) -> None:
    assert validate_expected_energy_source(source) == source


class StringSubclass(str):
    pass


@pytest.mark.parametrize(
    "source",
    ["", " ", "\t", " physics_sdm", "physics_sdm ", None, 123, True, StringSubclass("physics_sdm")],
)
def test_invalid_source(source: object) -> None:
    with pytest.raises(ValueError, match="source"):
        validate_expected_energy_source(source)


async def test_writer_default_and_alternative_keep_independent_conflict_rows(db: Database) -> None:
    await seed(db)
    # A later write to A must not overwrite B at identical site/time.
    await upsert_expected_energy(_site(), frame(110), db)
    rows = db.connection.execute(
        "SELECT source, p_ac_kw FROM expected_energy ORDER BY source"
    ).fetchall()
    assert rows == [("physics_sdm", 110.0)] * 2 + [(ALT, 200.0)] * 2
    assert all("ON CONFLICT (time, site_id, source)" in sql for sql, _ in db.calls)


async def test_cursor_and_runner_ignore_later_alternative_model(
    db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await upsert_expected_energy(_site(), frame().iloc[:1], db)
    await upsert_expected_energy(_site(), frame(hour=12).iloc[:1], db, source=ALT)
    assert await get_latest_expected_energy_time(SITE, db) == START
    assert await get_latest_expected_energy_time(SITE, db, source=ALT) == START.replace(hour=12)
    weather_end = START.replace(hour=11)
    monkeypatch.setattr(pipeline, "get_latest_weather_time", AsyncMock(return_value=weather_end))
    chunk = AsyncMock(return_value=1)
    monkeypatch.setattr(pipeline, "_run_chunk", chunk)
    # The cursor itself is real SQL, so an unfiltered MAX would skip this chunk.
    db.commit = AsyncMock()
    result = await pipeline.run_pipeline(_site(), db)
    assert result["chunks_run"] == 1
    assert chunk.await_args.args[2:] == (START, weather_end)
    assert db.calls[-1][1]["source"] == LEGACY_EXPECTED_ENERGY_SOURCE


@pytest.mark.parametrize("resolution", list(expected_energy.Resolution))
@pytest.mark.parametrize("source,power", [("physics_sdm", 100.0), (ALT, 200.0)])
async def test_expected_api_isolates_raw_hourly_daily(
    db: Database,
    resolution: expected_energy.Resolution,
    source: str,
    power: float,
) -> None:
    await seed(db)
    result = await expected_energy.get_expected_energy(
        SITE, START, END, resolution, db, source=source
    )
    assert result
    assert {row["p_ac_kw"] for row in result} == {power}  # never 150
    assert {row["source"] for row in result} == {source}


async def test_default_api_and_pr_numeric_compatibility(db: Database) -> None:
    await seed(db)
    rows = await expected_energy.get_expected_energy(
        SITE,
        START,
        END,
        expected_energy.Resolution.raw,
        db=db,
    )
    assert rows[0]["p_ac_kw"] == 100.0
    legacy = await performance_ratio.calculate_pr(SITE, START, END, db)
    alternative = await performance_ratio.calculate_pr(SITE, START, END, db, source=ALT)
    assert legacy["pr"] == 1.0
    assert legacy["e_expected_kwh"] == 200.0
    assert alternative["pr"] == 0.5
    assert alternative["e_expected_kwh"] == 400.0
    assert legacy["e_actual_kwh"] == alternative["e_actual_kwh"] == 200.0


async def test_loss_waterfall_only_admits_legacy(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    await seed(db)
    monkeypatch.setattr(losses, "_load_site_config", lambda _: _site())
    monkeypatch.setattr(losses, "_fetch_avail_df", AsyncMock(return_value=pd.DataFrame()))
    result = await losses.calculate_losses(SITE, START, END, db)
    assert result["e_exp_kwh"] == 200.0
    before = len(db.calls)
    with pytest.raises(ValueError, match="only physics_sdm"):
        await losses.calculate_losses(SITE, START, END, db, source=ALT)
    assert len(db.calls) == before


async def test_analysis_expected_readers_are_source_isolated(db: Database) -> None:
    await seed(db)
    for fetch in [degradation._fetch_expected_full, anomaly._fetch_joined]:
        legacy = await fetch(SITE, START, END, db)
        alternative = await fetch(SITE, START, END, db, source=ALT)
        column = "expected_kw" if fetch is anomaly._fetch_joined else "p_ac_kw"
        assert legacy[column].tolist() == [100.0, 100.0]
        assert alternative[column].tolist() == [200.0, 200.0]
    db.connection.execute("UPDATE meter_readings SET p_ac_kw=110 WHERE ts=?", (START.isoformat(),))
    a = await anomaly.detect_anomalies(SITE, START, END, db, source=ALT)
    assert a["flags"][0]["expected_kw"] == 200.0
    # Degradation needs more days for a fit, but must still select B's rows.
    await degradation.calculate_degradation(SITE, START, END, db, source=ALT)
    expected_call = [p for sql, p in db.calls if "FROM expected_energy" in sql][-1]
    assert expected_call["source"] == ALT


@pytest.mark.parametrize(
    "endpoint",
    [
        benchmarking.get_benchmarking,
        reports.generate_report,
        analysis.get_degradation,
        analysis.get_anomalies,
    ],
)
async def test_route_guard_rejects_missing_requested_source(
    db: Database,
    monkeypatch: pytest.MonkeyPatch,
    endpoint: Any,
) -> None:
    await seed(db)
    module = __import__(endpoint.__module__, fromlist=["get_session_factory"])
    monkeypatch.setattr(module, "get_session_factory", lambda: db.session)
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await endpoint(SITE, START, END, source="missing_model")
    assert exc.value.status_code == 404
    assert db.calls[-1][1]["source"] == "missing_model"


@pytest.mark.parametrize("endpoint", [benchmarking.get_benchmarking, reports.generate_report])
async def test_aggregate_legacy_routes_fail_clearly_for_alternative_loss_semantics(
    db: Database,
    monkeypatch: pytest.MonkeyPatch,
    endpoint: Any,
) -> None:
    await seed(db)
    module = __import__(endpoint.__module__, fromlist=["get_session_factory"])
    monkeypatch.setattr(module, "get_session_factory", lambda: db.session)
    from fastapi import HTTPException

    with pytest.raises(HTTPException, match="only physics_sdm") as exc:
        await endpoint(SITE, START, END, source=ALT)
    assert exc.value.status_code == 422


@pytest.mark.parametrize("operation", ["write", "cursor", "pr", "losses", "anomaly", "degradation"])
async def test_bad_source_fails_before_database(operation: str) -> None:
    session = AsyncMock()
    with pytest.raises(ValueError):
        if operation == "write":
            await upsert_expected_energy(_site(), pd.DataFrame(), session, source=" bad")
        elif operation == "cursor":
            await get_latest_expected_energy_time(SITE, session, source=" bad")
        else:
            function = {
                "pr": performance_ratio.calculate_pr,
                "losses": losses.calculate_losses,
                "anomaly": anomaly.detect_anomalies,
                "degradation": degradation.calculate_degradation,
            }[operation]
            await function(SITE, START, END, session, source=" bad")
    session.execute.assert_not_called()


def test_api_query_validation_and_default(db: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    app.include_router(expected_energy.router)
    app.include_router(benchmarking.router)
    app.include_router(reports.router)
    app.include_router(analysis.router)

    async def dependency() -> Any:
        yield db

    app.dependency_overrides[expected_energy.get_db] = dependency
    monkeypatch.setattr(benchmarking, "get_session_factory", lambda: db.session)
    monkeypatch.setattr(reports, "get_session_factory", lambda: db.session)
    monkeypatch.setattr(analysis, "get_session_factory", lambda: db.session)
    urls = [
        ("/api/v1/expected-energy/" + SITE, "get"),
        ("/api/v1/benchmarking/" + SITE, "get"),
        ("/api/v1/reports/" + SITE, "post"),
        ("/api/v1/analysis/" + SITE + "/degradation", "get"),
        ("/api/v1/analysis/" + SITE + "/anomalies", "get"),
    ]
    with TestClient(app) as client:
        for url, method in urls:
            for source in ["", " ", " physics_sdm", "physics_sdm "]:
                response = getattr(client, method)(
                    url,
                    params={
                        "start": START.isoformat(),
                        "end": END.isoformat(),
                        "source": source,
                    },
                )
                assert response.status_code == 422
        assert not db.calls
        for path in app.openapi()["paths"].values():
            for operation in path.values():
                parameters = operation.get("parameters", [])
                sources = [p for p in parameters if p["name"] == "source"]
                if sources:
                    assert sources[0]["schema"]["default"] == "physics_sdm"


def test_index_migration_is_reversible_without_data_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = Path("migrations/versions/0007_expected_energy_source_index.py")
    spec = importlib.util.spec_from_file_location("source_index", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0007" and module.down_revision == "0006"
    execute = MagicMock()
    monkeypatch.setattr(module.op, "execute", execute)
    module.upgrade()
    module.downgrade()
    assert [call.args[0] for call in execute.call_args_list] == [
        "CREATE INDEX idx_expected_energy_site_source_time "
        "ON expected_energy (site_id, source, time DESC)",
        "DROP INDEX idx_expected_energy_site_source_time",
    ]


async def test_pipeline_chunk_explicitly_writes_legacy_source(
    db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = frame().index
    weather = pd.DataFrame({"wind_speed_ms": 1.0, "temp_amb_c": 15.0}, index=index)
    poa = pd.DataFrame({"poa_total": 1000.0, "aoi": 0.0, "solar_zenith": 30.0}, index=index)
    monkeypatch.setattr(pipeline, "fetch_weather", AsyncMock(return_value=weather))
    monkeypatch.setattr(pipeline, "calculate_poa", lambda *_: poa)
    monkeypatch.setattr(
        pipeline, "calculate_cell_temp", lambda *_, **kw: pd.Series(25, index=index)
    )
    monkeypatch.setattr(pipeline, "calculate_dc_power", lambda *_, **kw: frame())
    monkeypatch.setattr(pipeline, "calculate_ac_power", lambda *_: frame()[["p_ac_kw"]])
    writer = AsyncMock(return_value=2)
    monkeypatch.setattr(pipeline, "upsert_expected_energy", writer)
    assert await pipeline._run_chunk(_site(), db, START, END) == 2
    assert writer.await_args.kwargs == {"source": LEGACY_EXPECTED_ENERGY_SOURCE}


async def test_legacy_bundle_routes_publish_source_and_forward_one_identity(
    db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed(db)
    for module in [benchmarking, reports]:
        monkeypatch.setattr(module, "get_session_factory", lambda: db.session)
        monkeypatch.setattr(module, "load_sites", lambda _: [_site()])
    monkeypatch.setattr(benchmarking, "_get_capacity_kwp", lambda _: 1000)
    for module in [benchmarking, reports]:
        for name in [
            "calculate_pr",
            "calculate_losses",
            "calculate_degradation",
            "detect_anomalies",
        ]:
            if hasattr(module, name):
                monkeypatch.setattr(module, name, AsyncMock(return_value={"e_expected_kwh": 200}))
        for name in [
            "calculate_availability",
            "calculate_yield",
            "analyse_string_health",
            "analyse_inverter_health",
        ]:
            if hasattr(module, name):
                monkeypatch.setattr(module, name, AsyncMock(return_value={}))
    # Group actuals use telemetry only, never an expected-energy source filter.
    db.connection.execute(
        "CREATE TABLE inverter_readings (inverter_id TEXT, inv_p_ac_kw REAL, site_id TEXT, ts TEXT)"
    )
    benchmark = await benchmarking.get_benchmarking(SITE, START, END)
    assert benchmark["expected_energy_source"] == LEGACY_EXPECTED_ENERGY_SOURCE
    monkeypatch.setattr(reports, "render", lambda _: b"%PDF-test")
    report = await reports.generate_report(SITE, START, END, sections=None)
    assert report.headers["X-Expected-Energy-Source"] == LEGACY_EXPECTED_ENERGY_SOURCE
    for module in [benchmarking, reports]:
        for name in [
            "calculate_pr",
            "calculate_losses",
            "calculate_degradation",
            "detect_anomalies",
        ]:
            if hasattr(module, name):
                assert getattr(module, name).await_args.kwargs == {"source": "physics_sdm"}
        assert module.calculate_availability.await_args.kwargs == {}


@pytest.mark.parametrize(
    "endpoint,name",
    [
        (analysis.get_degradation, "calculate_degradation"),
        (analysis.get_anomalies, "detect_anomalies"),
    ],
)
async def test_analysis_route_forwards_alternative_source(
    db: Database,
    monkeypatch: pytest.MonkeyPatch,
    endpoint: Any,
    name: str,
) -> None:
    await seed(db)
    monkeypatch.setattr(analysis, "get_session_factory", lambda: db.session)
    metric = AsyncMock(return_value={})
    monkeypatch.setattr(analysis, name, metric)
    result = await endpoint(SITE, START, END, source=ALT)
    assert result["expected_energy_source"] == ALT
    assert metric.await_args.kwargs == {"source": ALT}
