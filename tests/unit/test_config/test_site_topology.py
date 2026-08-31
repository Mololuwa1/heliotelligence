"""Tests for Site → Inverter → MPPT → String topology configuration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from heliotelligence.config.site import SiteConfig


def _site(**overrides: object) -> SiteConfig:
    data: dict[str, object] = {
        "id": "test-site",
        "name": "Topology Test",
        "latitude": 52.0,
        "longitude": 1.0,
        "timezone": "Europe/London",
        "capacity_kwp": 1000.0,
        "solcast_resource_id": "test-resource",
    }
    data.update(overrides)
    return SiteConfig.model_validate(data)


def _topology() -> dict[str, object]:
    return {
        "inverters": [
            {
                "id": "INV-01",
                "group_id": "BLOCK-A",
                "mppts": [
                    {
                        "id": "MPPT-01",
                        "strings": [
                            {
                                "id": "STR-001",
                                "modules_per_string": 24,
                                "zone_id": "ZONE-A",
                            },
                            {
                                "id": "STR-002",
                                "modules_per_string": 24,
                                "zone_id": "ZONE-A",
                            },
                        ],
                    },
                    {
                        "id": "MPPT-02",
                        "strings": [
                            {
                                "id": "STR-003",
                                "modules_per_string": 24,
                                "zone_id": "ZONE-B",
                            }
                        ],
                    },
                ],
            },
            {
                "id": "INV-02",
                "mppts": [
                    {
                        "id": "MPPT-01",
                        "strings": [
                            {"id": "STR-004", "modules_per_string": 24}
                        ],
                    }
                ],
            },
        ]
    }


def test_legacy_site_without_explicit_topology_still_validates() -> None:
    site = _site()

    assert site.electrical_topology is None


def test_topology_preserves_physical_hierarchy_and_counts() -> None:
    site = _site(electrical_topology=_topology())

    topology = site.electrical_topology
    assert topology is not None
    assert topology.inverter_count == 2
    assert topology.mppt_count == 3
    assert topology.string_count == 4
    assert topology.inverters[0].mppts[0].strings[0].zone_id == "ZONE-A"


def test_same_mppt_id_is_allowed_on_different_inverters() -> None:
    site = _site(electrical_topology=_topology())

    topology = site.electrical_topology
    assert topology is not None
    assert topology.inverters[0].mppts[0].id == "MPPT-01"
    assert topology.inverters[1].mppts[0].id == "MPPT-01"


def test_duplicate_mppt_id_within_inverter_is_rejected() -> None:
    topology = _topology()
    first_inverter = topology["inverters"][0]  # type: ignore[index]
    first_inverter["mppts"].append(  # type: ignore[index,union-attr]
        {"id": "MPPT-01", "strings": []}
    )

    with pytest.raises(ValidationError, match="Duplicate MPPT id"):
        _site(electrical_topology=topology)


def test_duplicate_string_id_across_site_is_rejected() -> None:
    topology = _topology()
    second_inverter = topology["inverters"][1]  # type: ignore[index]
    second_inverter["mppts"][0]["strings"][0]["id"] = "STR-001"  # type: ignore[index]

    with pytest.raises(ValidationError, match="Duplicate string id 'STR-001'"):
        _site(electrical_topology=topology)


def test_duplicate_inverter_id_is_rejected() -> None:
    topology = _topology()
    second_inverter = topology["inverters"][1]  # type: ignore[index]
    second_inverter["id"] = "INV-01"  # type: ignore[index]

    with pytest.raises(ValidationError, match="Duplicate inverter id"):
        _site(electrical_topology=topology)


def test_string_requires_positive_module_count() -> None:
    topology = _topology()
    first_inverter = topology["inverters"][0]  # type: ignore[index]
    first_string = first_inverter["mppts"][0]["strings"][0]  # type: ignore[index]
    first_string["modules_per_string"] = 0  # type: ignore[index]

    with pytest.raises(ValidationError, match="greater than 0"):
        _site(electrical_topology=topology)
