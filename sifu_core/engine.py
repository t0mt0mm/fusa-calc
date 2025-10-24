"""Pure math routines for SIL calculations."""

from __future__ import annotations

from typing import Iterable, Tuple

from .models import Assumptions, ChannelMetrics


def calculate_single_channel(
    lambda_total: float,
    du_ratio: float,
    dd_ratio: float,
    assumptions: Assumptions,
) -> ChannelMetrics:
    """Return metrics for a 1oo1 channel given ``λ_total`` and DU/DD ratios."""

    lam_du, lam_dd = _split_lambda(lambda_total, du_ratio, dd_ratio)
    ti = assumptions.TI
    mttr = assumptions.MTTR

    pfd = lam_du * (ti / 2.0 + mttr) + lam_dd * mttr
    pfh = lam_du

    return ChannelMetrics(lambda_total=lambda_total, lambda_du=lam_du, lambda_dd=lam_dd, pfd=pfd, pfh=pfh)


def calculate_one_out_of_two(
    lambda_totals: Iterable[float],
    du_ratio: float,
    dd_ratio: float,
    assumptions: Assumptions,
) -> ChannelMetrics:
    """Return metrics for a 1oo2 architecture using current assumptions."""

    total_lambda = sum(float(val) for val in lambda_totals)
    lam_du_total, lam_dd_total = _split_lambda(total_lambda, du_ratio, dd_ratio)

    beta = assumptions.beta
    beta_d = assumptions.beta_D
    ti = assumptions.TI
    mttr = assumptions.MTTR

    lam_du_ind = (1.0 - beta) * lam_du_total
    lam_dd_ind = (1.0 - beta_d) * lam_dd_total
    lam_d_ind = lam_du_ind + lam_dd_ind

    if lam_d_ind > 0.0:
        w_du = lam_du_ind / lam_d_ind
        w_dd = lam_dd_ind / lam_d_ind
        t_ce = w_du * (ti / 2.0 + mttr) + w_dd * mttr
        t_ge = w_du * (ti / 3.0 + mttr) + w_dd * mttr
        pfd_ind = 2.0 * (lam_d_ind**2) * t_ce * t_ge
        pfh_ind = 2.0 * lam_d_ind * lam_du_ind * t_ce
    else:
        t_ce = 0.0
        t_ge = 0.0
        pfd_ind = 0.0
        pfh_ind = 0.0

    pfd_du_ccf = beta * lam_du_total * (ti / 2.0 + mttr)
    pfd_dd_ccf = beta_d * lam_dd_total * mttr
    pfh_ccf = beta * lam_du_total

    pfd = pfd_ind + pfd_du_ccf + pfd_dd_ccf
    pfh = pfh_ind + pfh_ccf

    return ChannelMetrics(
        lambda_total=total_lambda,
        lambda_du=lam_du_total,
        lambda_dd=lam_dd_total,
        pfd=pfd,
        pfh=pfh,
    )


def _split_lambda(lambda_total: float, du_ratio: float, dd_ratio: float) -> Tuple[float, float]:
    total_ratio = du_ratio + dd_ratio
    if total_ratio <= 0:
        raise ValueError("DU/DD ratios must sum to a positive value.")
    du_fraction = du_ratio / total_ratio
    dd_fraction = dd_ratio / total_ratio
    lam_du = lambda_total * du_fraction
    lam_dd = lambda_total * dd_fraction
    return lam_du, lam_dd
