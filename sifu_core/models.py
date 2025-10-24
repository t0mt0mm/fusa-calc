"""Domain models for SIL core computations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DemandMode = Literal["low_demand", "high_demand"]


@dataclass(frozen=True)
class Assumptions:
    """Global calculation assumptions expressed in hours and fractions."""

    TI: float  # Proof-test interval in hours
    MTTR: float  # Mean time to repair in hours
    beta: float  # Common-cause share for dangerous undetected failures
    beta_D: float  # Common-cause share for dangerous detected failures


@dataclass(frozen=True)
class ChannelMetrics:
    """Computed metrics for a channel or architecture."""

    lambda_total: float
    lambda_du: float
    lambda_dd: float
    pfd: float
    pfh: float
