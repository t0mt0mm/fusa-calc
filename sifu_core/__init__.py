"""Core math package for SIL calculations."""

from .models import Assumptions, ChannelMetrics, DemandMode
from .conversions import compute_lambda_total, ConversionError
from .engine import (
    calculate_single_channel,
    calculate_one_out_of_two,
)

__all__ = [
    "Assumptions",
    "ChannelMetrics",
    "DemandMode",
    "ConversionError",
    "compute_lambda_total",
    "calculate_single_channel",
    "calculate_one_out_of_two",
]
