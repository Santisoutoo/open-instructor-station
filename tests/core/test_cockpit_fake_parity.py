"""``adapters.fake.cockpit_catalog.FAKE_COCKPIT_CATALOG`` must never drift from
``tests/core/fixtures/cockpit/fake-trainer`` (D12, §4.1, §8.1).

The fixture's own module docstring states it is the oracle: it was
hand-written first, and the Python constant matches it, never the other way
around. §8.1 calls this out as a required "consistency guard" — this is that
guard, field for field, so a future edit to either one that the other does
not follow is a same-PR failure, not a silent divergence discovered by a
Wave 2 author months later.
"""

from __future__ import annotations

from pathlib import Path

from adapters.fake.cockpit_catalog import FAKE_COCKPIT_CATALOG
from core.cockpit.catalog import load_catalog_dir

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "cockpit"


def test_fake_catalog_constant_matches_its_yaml_fixture_field_for_field() -> None:
    from_fixture = load_catalog_dir(FIXTURE_DIR / "fake-trainer")
    assert from_fixture == FAKE_COCKPIT_CATALOG
