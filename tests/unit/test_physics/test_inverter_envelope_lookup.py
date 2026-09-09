"""Tests for exact CEC/SAM inverter DC operating-envelope lookup."""

from __future__ import annotations

import pandas as pd
import pytest

from heliotelligence.physics import inverter_envelope_lookup
from heliotelligence.physics.inverter_envelope import InverterDcOperatingEnvelope


def _database() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Manufacturer_Model_ABC": {
                "Paco": 6000.0,
                "Pdco": 6158.0,
                "Vdco": 360.0,
                "Pso": 36.0,
                "C0": 0.0,
                "C1": 0.0,
                "C2": 0.0,
                "C3": 0.0,
                "Pnt": 1.8,
                "Vdcmax": 600.0,
                "Idcmax": 32.0,
                "Mppt_low": 200.0,
                "Mppt_high": 500.0,
                "Vac": 277.0,
            }
        }
    )


@pytest.mark.parametrize("name", [None, "", "   ", 123])
def test_cec_name_requires_actual_non_whitespace_string(name: object) -> None:
    with pytest.raises(ValueError, match="cec_name"):
        inverter_envelope_lookup.resolve_cec_inverter_dc_operating_envelope(
            name  # type: ignore[arg-type]
        )


def test_exact_cec_name_resolves_with_high_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        inverter_envelope_lookup,
        "_load_cec_inverter_database",
        _database,
    )
    resolved = inverter_envelope_lookup.resolve_cec_inverter_dc_operating_envelope(
        "Manufacturer_Model_ABC"
    )
    assert isinstance(resolved.envelope, InverterDcOperatingEnvelope)
    assert resolved.envelope.mppt_voltage_min_v == 200.0
    assert resolved.envelope.mppt_voltage_max_v == 500.0
    assert resolved.envelope.absolute_dc_voltage_max_v == 600.0
    assert resolved.envelope.dc_current_max_a == 32.0
    assert resolved.parameter_source == "cec_sam:Manufacturer_Model_ABC"
    assert resolved.confidence == "high"


@pytest.mark.parametrize(
    "requested",
    ["Model_ABC", "manufacturer_model_abc", " Manufacturer_Model_ABC "],
)
def test_cec_lookup_does_not_fuzzy_or_normalize(
    monkeypatch: pytest.MonkeyPatch,
    requested: str,
) -> None:
    monkeypatch.setattr(
        inverter_envelope_lookup,
        "_load_cec_inverter_database",
        _database,
    )
    with pytest.raises(ValueError) as error:
        inverter_envelope_lookup.resolve_cec_inverter_dc_operating_envelope(requested)
    assert str(error.value) == f"CEC/SAM inverter model not found: {requested!r}"


def test_database_loader_uses_bundled_cec_inverter_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def retrieve_sam(name: str) -> pd.DataFrame:
        calls.append(name)
        return _database()

    monkeypatch.setattr(
        inverter_envelope_lookup.pvlib.pvsystem,
        "retrieve_sam",
        retrieve_sam,
    )
    assert inverter_envelope_lookup._load_cec_inverter_database().equals(_database())
    assert calls == ["CECInverter"]


def test_missing_cec_envelope_field_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database().drop(index="Idcmax")
    monkeypatch.setattr(
        inverter_envelope_lookup,
        "_load_cec_inverter_database",
        lambda: database,
    )
    with pytest.raises(ValueError, match="missing inverter envelope keys: Idcmax"):
        inverter_envelope_lookup.resolve_cec_inverter_dc_operating_envelope(
            "Manufacturer_Model_ABC"
        )


def test_non_finite_cec_envelope_field_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database()
    database.loc["Vdcmax", "Manufacturer_Model_ABC"] = float("nan")
    monkeypatch.setattr(
        inverter_envelope_lookup,
        "_load_cec_inverter_database",
        lambda: database,
    )
    with pytest.raises(ValueError, match="absolute_dc_voltage_max_v"):
        inverter_envelope_lookup.resolve_cec_inverter_dc_operating_envelope(
            "Manufacturer_Model_ABC"
        )


def test_real_cec_database_contains_resolvable_operating_envelope() -> None:
    database = inverter_envelope_lookup._load_cec_inverter_database()
    required = ["Mppt_low", "Mppt_high", "Vdcmax", "Idcmax"]
    assert set(required).issubset(database.index)
    usable = database.loc[required].T.dropna()
    usable = usable[
        (usable["Mppt_low"] > 0)
        & (usable["Mppt_high"] > usable["Mppt_low"])
        & (usable["Vdcmax"] >= usable["Mppt_high"])
        & (usable["Idcmax"] > 0)
    ]
    assert not usable.empty
    cec_name = str(usable.index[0])
    resolved = inverter_envelope_lookup.resolve_cec_inverter_dc_operating_envelope(
        cec_name
    )
    row = database[cec_name]
    assert resolved.envelope.mppt_voltage_min_v == pytest.approx(float(row["Mppt_low"]))
    assert resolved.envelope.mppt_voltage_max_v == pytest.approx(float(row["Mppt_high"]))
    assert resolved.envelope.absolute_dc_voltage_max_v == pytest.approx(
        float(row["Vdcmax"])
    )
    assert resolved.envelope.dc_current_max_a == pytest.approx(float(row["Idcmax"]))
    assert resolved.parameter_source == f"cec_sam:{cec_name}"
    assert resolved.confidence == "high"
