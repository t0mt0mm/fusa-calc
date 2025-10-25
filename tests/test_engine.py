import math

import pytest

from sifu_core.engine import calculate_one_out_of_two, calculate_single_channel
from sifu_core.models import Assumptions


def _split_lambda(lambda_total: float, du_ratio: float, dd_ratio: float) -> tuple[float, float]:
    total_ratio = du_ratio + dd_ratio
    if total_ratio <= 0:
        raise ValueError
    return lambda_total * du_ratio / total_ratio, lambda_total * dd_ratio / total_ratio


def test_calculate_single_channel_matches_formula(default_assumptions: Assumptions) -> None:
    metrics = calculate_single_channel(1.5e-5, 0.65, 0.35, default_assumptions)

    lam_du, lam_dd = _split_lambda(1.5e-5, 0.65, 0.35)
    expected_pfd = lam_du * (default_assumptions.TI / 2.0 + default_assumptions.MTTR) + lam_dd * default_assumptions.MTTR
    expected_pfh = lam_du

    assert math.isclose(metrics.lambda_du, lam_du)
    assert math.isclose(metrics.lambda_dd, lam_dd)
    assert math.isclose(metrics.pfd, expected_pfd)
    assert math.isclose(metrics.pfh, expected_pfh)


def test_calculate_single_channel_rejects_invalid_ratios(default_assumptions: Assumptions) -> None:
    with pytest.raises(ValueError):
        calculate_single_channel(1.0e-5, 0.0, 0.0, default_assumptions)


@pytest.mark.parametrize(
    "lambda_totals, du_ratio, dd_ratio",
    [([1.0e-5, 1.2e-5], 0.6, 0.4), ([3.0e-6, 4.0e-6], 0.5, 0.5)],
)
def test_calculate_one_out_of_two_matches_beta_model(
    lambda_totals: list[float],
    du_ratio: float,
    dd_ratio: float,
    default_assumptions: Assumptions,
) -> None:
    asm = default_assumptions
    metrics = calculate_one_out_of_two(lambda_totals, du_ratio, dd_ratio, asm)

    total_lambda = sum(lambda_totals)
    lam_du_total, lam_dd_total = _split_lambda(total_lambda, du_ratio, dd_ratio)
    lam_du_ind = (1.0 - asm.beta) * lam_du_total
    lam_dd_ind = (1.0 - asm.beta_D) * lam_dd_total
    lam_d_ind = lam_du_ind + lam_dd_ind

    if lam_d_ind > 0.0:
        w_du = lam_du_ind / lam_d_ind
        w_dd = lam_dd_ind / lam_d_ind
        t_ce = w_du * (asm.TI / 2.0 + asm.MTTR) + w_dd * asm.MTTR
        t_ge = w_du * (asm.TI / 3.0 + asm.MTTR) + w_dd * asm.MTTR
        pfd_ind = 2.0 * (lam_d_ind ** 2) * t_ce * t_ge
        pfh_ind = 2.0 * lam_d_ind * lam_du_ind * t_ce
    else:
        pfd_ind = 0.0
        pfh_ind = 0.0

    pfd_ccf = asm.beta * lam_du_total * (asm.TI / 2.0 + asm.MTTR) + asm.beta_D * lam_dd_total * asm.MTTR
    pfh_ccf = asm.beta * lam_du_total

    expected_pfd = pfd_ind + pfd_ccf
    expected_pfh = pfh_ind + pfh_ccf

    assert math.isclose(metrics.lambda_du, lam_du_total)
    assert math.isclose(metrics.lambda_dd, lam_dd_total)
    assert math.isclose(metrics.pfd, expected_pfd)
    assert math.isclose(metrics.pfh, expected_pfh)


def test_calculate_one_out_of_two_handles_zero_beta(default_assumptions: Assumptions) -> None:
    asm = Assumptions(TI=default_assumptions.TI, MTTR=default_assumptions.MTTR, beta=0.0, beta_D=0.0)
    metrics = calculate_one_out_of_two([7.5e-6, 7.5e-6], 0.7, 0.3, asm)

    total_lambda = sum([7.5e-6, 7.5e-6])
    lam_du_total, lam_dd_total = _split_lambda(total_lambda, 0.7, 0.3)
    lam_du_ind = lam_du_total
    lam_dd_ind = lam_dd_total
    lam_d_ind = lam_du_ind + lam_dd_ind

    w_du = lam_du_ind / lam_d_ind
    w_dd = lam_dd_ind / lam_d_ind
    t_ce = w_du * (asm.TI / 2.0 + asm.MTTR) + w_dd * asm.MTTR
    t_ge = w_du * (asm.TI / 3.0 + asm.MTTR) + w_dd * asm.MTTR
    expected_pfd = 2.0 * (lam_d_ind ** 2) * t_ce * t_ge
    expected_pfh = 2.0 * lam_d_ind * lam_du_ind * t_ce

    assert math.isclose(metrics.pfd, expected_pfd)
    assert math.isclose(metrics.pfh, expected_pfh)
    assert metrics.lambda_du == pytest.approx(lam_du_total)
    assert metrics.lambda_dd == pytest.approx(lam_dd_total)
