"""Identity of alternative expected-model series, never additive loss layers."""

LEGACY_EXPECTED_ENERGY_SOURCE = "physics_sdm"


def validate_expected_energy_source(value: object) -> str:
    """Preserve an exact source identifier; reject implicit coercion/normalisation."""
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(
            "expected-energy source must be a non-empty exact str without surrounding whitespace"
        )
    return value
