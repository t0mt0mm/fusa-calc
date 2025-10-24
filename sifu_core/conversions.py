"""Helpers that convert manufacturer data into runtime-ready lambdas."""

from __future__ import annotations

from typing import Mapping, Optional, Tuple

from .models import Assumptions, DemandMode


class ConversionError(ValueError):
    """Raised when raw data cannot be translated into a λ_total."""


def compute_lambda_total(
    raw: Mapping[str, object],
    demand_mode: DemandMode,
    assumptions: Assumptions,
) -> Tuple[float, str]:
    """Return ``(lambda_total, provenance)`` for the given component.

    Parameters
    ----------
    raw:
        Mapping containing manufacturer data. Recognised keys include
        ``lambda_du``, ``lambda_dd``, ``lambda_total``, ``lambda``, ``pfd``/
        ``pfd_avg`` and ``pfh``/``pfh_avg``.
    demand_mode:
        Either ``"low_demand"`` or ``"high_demand"``. Determines which data
        points are used for the derivation when both PFD and PFH are present.
    assumptions:
        Global assumptions providing the currently active proof-test interval
        (TI) required when deriving λ from PFD.
    """

    if demand_mode not in ("low_demand", "high_demand"):
        raise ConversionError(f"Unsupported demand mode: {demand_mode}")

    name = _preferred_label(raw)
    source_hint = raw.get("source") or raw.get("origin") or raw.get("kind")
    if source_hint:
        context = f"{name} (source: {source_hint})"
    else:
        context = name

    lambda_du = _optional_float(raw, "lambda_du", context)
    lambda_dd = _optional_float(raw, "lambda_dd", context)
    lambda_total = _optional_float(raw, "lambda_total", context)
    lambda_legacy = _optional_float(raw, "lambda", context)

    if lambda_du is not None or lambda_dd is not None:
        if lambda_du is None or lambda_dd is None:
            raise ConversionError(
                f"{context}: both λDU and λDD must be provided when using native λ data."
            )
        if lambda_du < 0 or lambda_dd < 0:
            raise ConversionError(f"{context}: λDU/λDD must be non-negative.")
        return lambda_du + lambda_dd, "native"

    for candidate in (lambda_total, lambda_legacy):
        if candidate is not None:
            if candidate < 0:
                raise ConversionError(f"{context}: λ_total must be non-negative.")
            return candidate, "native"

    pfh = _optional_float(raw, "pfh", context)
    if pfh is None:
        pfh = _optional_float(raw, "pfh_avg", context)
    pfd = _optional_float(raw, "pfd", context)
    if pfd is None:
        pfd = _optional_float(raw, "pfd_avg", context)

    if demand_mode == "high_demand":
        if pfh is None:
            raise ConversionError(
                f"{context}: PFH data required to derive λ_total for high demand mode."
            )
        if pfh < 0:
            raise ConversionError(f"{context}: PFH values must be non-negative (1/h).")
        return pfh, "derived_from_pfh"

    # low demand branch
    if pfd is None:
        raise ConversionError(
            f"{context}: PFD data required to derive λ_total for low demand mode."
        )
    if pfd < 0:
        raise ConversionError(f"{context}: PFD values must be non-negative (dimensionless).")
    if assumptions.TI <= 0:
        raise ConversionError(
            f"{context}: proof-test interval (TI) must be greater than zero to derive λ_total from PFD."
        )
    lambda_from_pfd = 2.0 * pfd / assumptions.TI
    return lambda_from_pfd, "derived_from_pfd"


def _preferred_label(raw: Mapping[str, object]) -> str:
    for key in ("code", "name", "title"):
        val = raw.get(key)
        if isinstance(val, str) and val.strip():
            return val
    return "component"


def _optional_float(
    raw: Mapping[str, object],
    key: str,
    context: str,
) -> Optional[float]:
    value = raw.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ConversionError(f"{context}: invalid numeric value for '{key}'.")
