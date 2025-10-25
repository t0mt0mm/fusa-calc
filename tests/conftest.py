import pytest

from sifu_core.models import Assumptions


@pytest.fixture
def default_assumptions() -> Assumptions:
    """Standard assumptions used across unit tests."""
    return Assumptions(TI=8760.0, MTTR=8.0, beta=0.1, beta_D=0.02)
