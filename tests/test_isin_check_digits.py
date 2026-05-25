"""Validate every static ISIN map against the ISO 6166 check digit.

Each ISIN ends in a Luhn-style check digit. A value with the wrong check
digit cannot be a real ISIN, regardless of how it was sourced — typos,
mis-recalls, and copy-paste corruption are all caught here.

A valid check digit does NOT prove the ISIN is correct for the company
(a confabulated value can land on a valid digit by chance), but it is a
necessary condition. This test guards every static map so future edits
fail CI loudly instead of leaking bad data into production.
"""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from equity_aggregator.adapters.aex import AEX_MEMBERS
from equity_aggregator.adapters.bel20 import BEL20_MEMBERS
from equity_aggregator.adapters.cac40 import CAC40_MEMBERS
from equity_aggregator.adapters.dax import DAX_MEMBERS
from equity_aggregator.adapters.ibex35 import IBEX35_MEMBERS
from equity_aggregator.adapters.smi import SMI_MEMBERS
from equity_aggregator.adapters.sp500 import SP500_MEMBERS
from equity_aggregator.adapters.sti import STI_MEMBERS
from equity_aggregator.adapters.wig20 import WIG20_MEMBERS


def _expand(isin: str) -> str | None:
    """Expand letters A-Z to two-digit base-36 values; digits passthrough."""
    out: list[str] = []
    for ch in isin:
        if ch.isdigit():
            out.append(ch)
        elif ch.isalpha():
            out.append(str(ord(ch.upper()) - ord("A") + 10))
        else:
            return None
    return "".join(out)


def is_valid_isin(isin: str) -> bool:
    """ISO 6166 check-digit validation (Luhn variant).

    Steps:
      1. Confirm 12-char alphanumeric structure.
      2. Replace each letter with its base-36 ordinal as two decimal digits.
      3. From the rightmost digit (i=0), double every second digit starting
         with the second-from-right (i=1, 3, 5, …).
      4. Sum the digits of every term. Valid ISINs sum to a multiple of 10.
    """
    if not isin or len(isin) != 12 or not isin.isalnum():
        return False
    digits = _expand(isin)
    if digits is None:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
        total += n // 10 + n % 10
    return total % 10 == 0


# Indices known to have ISINs that fail check-digit validation. These were
# inherited from earlier curated maps where some entries appear to have been
# transcribed by hand and contain typos / confabulated digits. Each entry is
# tagged xfail(strict=True), which means:
#   - still broken → reports xfail, CI stays green.
#   - quietly fixed → reports xpass and FAILS CI, forcing us to remove the
#     marker and confirm the index is now clean.
# Remove the index from _KNOWN_BROKEN after replacing its static map with
# values from an authoritative, regenerable source (mirroring the SSGA SPY
# pipeline used for S&P 500 in scripts/gen_sp500_isins.py).
_KNOWN_BROKEN: frozenset[str] = frozenset()
# Historical context (now fixed; kept as a paper trail):
#   - CAC 40   ML.PA   FR001400AJD7 → FR001400AJ45 (Euronext search)
#   - SMI      NOVN.SW CH0012221060 → CH0012005267 (SIX / Wikipedia)
#   - BEL 20   BEKB.BR BE0003789394 → BE0974258874 (Euronext search)
#   - BEL 20   DIE.BR  BE0974259238 → BE0974259880 (Euronext search)
#   - BEL 20   LOTB.BR BE0003532583 → BE0003604155 (Euronext search)
#   - BEL 20   MELE.BR BE0003469031 → BE0165385973 (Euronext search)
#   - AEX      whole map regenerated from iShares AEX ETF holdings JSON
#              (removed LIGHT.AS, fixed BESI/AGN/DSFIR/UNA stale ISINs)
#   - STI      whole map regenerated from SSGA SPDR STI ETF (ES3) xlsx
#   - WIG20    PCO.WA  LU2434412847 → LU2434412842 (typo on last digit)
#   - WIG20    ZAB.WA  NL0015002CX0 → NL0015002CX3 (typo on last digit)
#   - IBEX 35  PUIG.MC ES0105631009 → ES0105777017 (CNMV / Wikipedia)


def _maybe_xfail(index_name: str) -> pytest.MarkDecorator | None:
    if index_name in _KNOWN_BROKEN:
        return pytest.mark.xfail(
            strict=True,
            reason=(
                f"{index_name} static ISIN map has known check-digit failures; "
                "awaiting regeneration from an authoritative source. Remove "
                "from _KNOWN_BROKEN in test_isin_check_digits.py once fixed."
            ),
        )
    return None


def _param(index_name: str, members: Iterable[object]) -> object:
    mark = _maybe_xfail(index_name)
    if mark is None:
        return pytest.param(index_name, members, id=index_name)
    return pytest.param(index_name, members, id=index_name, marks=mark)


_ALL_MAPS: tuple[object, ...] = (
    _param("DAX", DAX_MEMBERS),
    _param("CAC 40", CAC40_MEMBERS),
    _param("SMI", SMI_MEMBERS),
    _param("BEL 20", BEL20_MEMBERS),
    _param("AEX", AEX_MEMBERS),
    _param("STI", STI_MEMBERS),
    _param("WIG20", WIG20_MEMBERS),
    _param("IBEX 35", IBEX35_MEMBERS),
    _param("S&P 500", SP500_MEMBERS),
)


def test_isin_algorithm_self_test() -> None:
    """Anchor cases — independently known-correct ISINs."""
    # US, EU, UK, CH samples.
    assert is_valid_isin("US0378331005")  # AAPL
    assert is_valid_isin("US5949181045")  # MSFT
    assert is_valid_isin("DE000BASF111")  # BASF
    assert is_valid_isin("NL0000235190")  # Airbus
    assert is_valid_isin("CH0038863350")  # Nestlé
    # Negatives.
    assert not is_valid_isin("US0378331004")  # wrong check digit
    assert not is_valid_isin("US037833100")   # too short
    assert not is_valid_isin("")
    assert not is_valid_isin("BOGUS!!!!!!")


@pytest.mark.parametrize(("index_name", "members"), _ALL_MAPS)
def test_every_member_has_valid_isin_check_digit(
    index_name: str, members: Iterable[object]
) -> None:
    """Every static-map ISIN must satisfy ISO 6166's check-digit rule."""
    failures: list[tuple[str, str]] = []
    for m in members:
        ticker = getattr(m, "ticker")
        isin = getattr(m, "isin")
        if not is_valid_isin(isin):
            failures.append((ticker, isin))
    assert not failures, (
        f"{index_name}: {len(failures)} ISINs have invalid check digits — "
        f"these CANNOT be real ISINs and must be replaced from an "
        f"authoritative source. Offenders: {failures}"
    )
