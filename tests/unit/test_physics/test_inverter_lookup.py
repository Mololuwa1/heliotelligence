"""Tests for exact CEC/SAM Sandia inverter parameter lookup."""

from __future__ import annotations

import pandas as pd
import pytest

from heliotelligence.physics import inverter_lookup
from heliotelligence.physics.inverter import SandiaInverterParameters


def _database() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Manufacturer_Model_ABC": {
                "Paco": 1000.0,
                "Pdco": 1050.0,
                "Vdco": 400.0,
                "Pso": 10.0,
                "C0": 0.0,
                "C1": 0.0,
                "C2": 0.0,
                "C3": 0.0,
                "Pnt": 1.0,
                "Vac": 240.0,
            }
        }
    )


@pytest.mark.parametrize("name", [None, "", "   ", 123])
def test_cec_name_requires_actual_non_whitespace_string(name: object) -> None:
    with pytest.raises(ValueError, match="cec_name"):
        inverter_lookup.resolve_cec_sandia_inverter_model(name)  # type: ignore[arg-type]


def test_exact_cec_name_resolves_with_high_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(inverter_lookup, "_load_cec_inverter_database", _database)

    model = inverter_lookup.resolve_cec_sandia_inverter_model(
        "Manufacturer_Model_ABC"
    )

    assert isinstance(model.parameters, SandiaInverterParameters)
    assert model.parameters.paco_w == 1000.0
    assert model.parameter_source == "cec_sam:Manufacturer_Model_ABC"
    assert model.confidence == "high"


@pytest.mark.parametrize("requested", ["Model_ABC", "manufacturer_model_abc", " Model_ABC "])
def test_cec_lookup_does_not_fuzzy_or_normalize(
    monkeypatch: pytest.MonkeyPatch,
    requested: str,
) -> None:
    monkeypatch.setattr(inverter_lookup, "_load_cec_inverter_database", _database)

    with pytest.raises(ValueError) as error:
        inverter_lookup.resolve_cec_sandia_inverter_model(requested)

    assert str(error.value) == f"CEC/SAM inverter model not found: {requested!r}"


def test_database_loader_uses_bundled_cec_inverter_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def retrieve_sam(name: str) -> pd.DataFrame:
        calls.append(name)
        return _database()

    monkeypatch.setattr(inverter_lookup.pvlib.pvsystem, "retrieve_sam", retrieve_sam)

    assert inverter_lookup._load_cec_inverter_database().equals(_database())
    assert calls == ["CECInverter"]
