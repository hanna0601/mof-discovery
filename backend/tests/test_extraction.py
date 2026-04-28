"""
Extraction pipeline test against the uploaded paper.

Run from backend/:
    python -m pytest tests/test_extraction.py -v
    python -m pytest tests/test_extraction.py -v -s     # show print output
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from pathlib import Path

PDF_PATH = Path(__file__).parent.parent.parent / "data" / "uploads" / "1-s2.0-S2212982025001672-main.pdf"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def full_text():
    """Parse the PDF once for all tests."""
    pytest.importorskip("fitz", reason="PyMuPDF not installed")
    assert PDF_PATH.exists(), f"PDF not found: {PDF_PATH}"
    from extraction.parse import pdf_to_text
    text = pdf_to_text(str(PDF_PATH))
    assert len(text) > 500, "PDF parsed to almost nothing — check the file"
    return text


@pytest.fixture(scope="module")
def extraction_result(full_text):
    """Run LLM extraction once for all tests."""
    from extraction.extract import extract_with_llm
    from extraction.models import PaperMeta
    meta = PaperMeta(
        title="Test paper from uploads",
        doi="10.1016/test-upload",
        source="upload",
    )
    result = extract_with_llm(full_text, meta)
    return result


# ── Parse tests ───────────────────────────────────────────────────────────────

class TestParse:
    def test_pdf_exists(self):
        assert PDF_PATH.exists(), f"Upload not found at {PDF_PATH}"

    def test_pdf_produces_text(self, full_text):
        assert len(full_text) > 1000, f"Too short: {len(full_text)} chars"

    def test_text_contains_mof_keywords(self, full_text):
        lower = full_text.lower()
        mof_terms = ["metal-organic framework", "mof", "co2", "carbon dioxide",
                     "carbon capture"]
        found = [t for t in mof_terms if t in lower]
        assert found, f"No MOF/CO2 keywords found. First 500 chars:\n{full_text[:500]}"

    def test_text_has_numbers(self, full_text):
        import re
        numbers = re.findall(r"\d+\.\d+", full_text)
        assert len(numbers) >= 10, "Very few numbers in parsed text — tables may not have parsed"


# ── Extraction tests ──────────────────────────────────────────────────────────

class TestExtraction:
    def test_result_is_not_none(self, extraction_result):
        assert extraction_result is not None

    def test_found_at_least_one_mof(self, extraction_result):
        assert len(extraction_result.mofs) >= 1, (
            "No MOFs extracted. Check LLM API keys and paper content."
        )

    def test_no_duplicate_mof_names(self, extraction_result):
        """Each MOF should appear exactly once — dedup by name."""
        names = [m.mof_name.lower().strip() for m in extraction_result.mofs]
        duplicates = [n for n in names if names.count(n) > 1]
        assert not duplicates, (
            f"Duplicate MOF entries found: {set(duplicates)}\n"
            "The LLM created multiple top-level entries for the same material."
        )

    def test_mof_names_are_non_empty(self, extraction_result):
        empty = [i for i, m in enumerate(extraction_result.mofs) if not m.mof_name.strip()]
        assert not empty, f"MOF entries at indices {empty} have empty names"

    def test_each_mof_has_measurements(self, extraction_result):
        """Every MOF record should have at least one measurement or structural data."""
        problems = []
        for m in extraction_result.mofs:
            has_measurements = len(m.measurements) > 0
            has_structural = any([
                m.surface_area_m2_g, m.pore_volume_cm3_g,
                m.pore_limiting_diameter_A, m.void_fraction,
            ])
            if not has_measurements and not has_structural:
                problems.append(m.mof_name)
        assert not problems, f"MOFs with no data at all: {problems}"

    def test_measurements_have_values(self, extraction_result):
        """No measurement should have a None value."""
        bad = []
        for m in extraction_result.mofs:
            for ms in m.measurements:
                if ms.value is None:
                    bad.append(f"{m.mof_name} / {ms.type}")
        assert not bad, f"Measurements with null value: {bad}"

    def test_co2_uptake_units_are_sensible(self, extraction_result):
        """CO2 uptake units should be recognisable."""
        known_units = {"mmol/g", "mol/kg", "wt%", "mg/g", "cm3/g", "cc/g",
                       "mmol/kg", "mol/g", "mg/kg", "cm³/g"}
        bad = []
        for m in extraction_result.mofs:
            for ms in m.measurements:
                if ms.type == "co2_uptake" and ms.unit:
                    if ms.unit.lower().replace(" ", "") not in {u.replace(" ", "") for u in known_units}:
                        bad.append(f"{m.mof_name}: '{ms.unit}'")
        assert not bad, f"Unrecognised CO2 uptake units — may be hallucinated:\n" + "\n".join(bad)

    def test_temperatures_are_physical(self, extraction_result):
        """Temperatures should be in plausible range (200–500 K)."""
        bad = []
        for m in extraction_result.mofs:
            for ms in m.measurements:
                if ms.temperature_k is not None:
                    if not (200 <= ms.temperature_k <= 500):
                        bad.append(f"{m.mof_name}: {ms.temperature_k} K")
        assert not bad, f"Implausible temperatures (not 200–500 K): {bad}"

    def test_pressures_are_physical(self, extraction_result):
        """Pressures should be positive and ≤ 200 bar."""
        bad = []
        for m in extraction_result.mofs:
            for ms in m.measurements:
                if ms.pressure_bar is not None:
                    if not (0 < ms.pressure_bar <= 200):
                        bad.append(f"{m.mof_name}: {ms.pressure_bar} bar")
        assert not bad, f"Implausible pressures: {bad}"

    def test_confidence_in_range(self, extraction_result):
        """All confidence scores must be 0–1."""
        bad = []
        for m in extraction_result.mofs:
            for ms in m.measurements:
                if not (0.0 <= ms.confidence <= 1.0):
                    bad.append(f"{m.mof_name}/{ms.type}: {ms.confidence}")
        assert not bad, f"Confidence out of [0,1]: {bad}"

    def test_selectivity_is_co2_related(self, extraction_result):
        """Selectivity measurements should be CO2-related, not CH4/N2 or other gases."""
        non_co2 = ("c2h2/c2h4", "c2h4/c2h6", "ch4/n2", "n2/ch4", "n2/o2", "h2/co2")
        bad = []
        for m in extraction_result.mofs:
            for ms in m.measurements:
                if ms.type == "selectivity" and ms.selectivity_definition:
                    defn = ms.selectivity_definition.lower()
                    if any(p in defn for p in non_co2):
                        bad.append(f"{m.mof_name}: '{ms.selectivity_definition}'")
        assert not bad, f"Non-CO2 selectivity slipped through filter: {bad}"

    def test_no_zeolites_or_carbons(self, extraction_result):
        """Pure zeolites, activated carbons, and COFs must not appear.
        Composites like 'zeolite@ZIF-8' are allowed (MOF is the functional material)."""
        exclude_keywords = ["zeolite", "activated carbon", "cof ", "covalent organic",
                            "carbon nanotube", "graphene"]
        bad = []
        for m in extraction_result.mofs:
            name_lower = m.mof_name.lower()
            is_composite = "@" in name_lower or "/" in name_lower
            if is_composite:
                continue  # composites are allowed even if they contain excluded terms
            for kw in exclude_keywords:
                if kw in name_lower:
                    bad.append(m.mof_name)
        assert not bad, f"Non-MOF materials extracted: {bad}"

    def test_structural_fields_are_positive(self, extraction_result):
        """Surface area, pore volume, diameters, void fraction must be positive."""
        bad = []
        for m in extraction_result.mofs:
            for field, val in [
                ("surface_area_m2_g",        m.surface_area_m2_g),
                ("pore_volume_cm3_g",         m.pore_volume_cm3_g),
                ("pore_limiting_diameter_A",  m.pore_limiting_diameter_A),
                ("largest_cavity_diameter_A", m.largest_cavity_diameter_A),
                ("void_fraction",             m.void_fraction),
            ]:
                if val is not None and val <= 0:
                    bad.append(f"{m.mof_name}.{field} = {val}")
        assert not bad, f"Non-positive structural values: {bad}"

    def test_void_fraction_is_fraction(self, extraction_result):
        """Void fraction must be between 0 and 1."""
        bad = []
        for m in extraction_result.mofs:
            if m.void_fraction is not None and not (0 < m.void_fraction < 1):
                bad.append(f"{m.mof_name}: {m.void_fraction}")
        assert not bad, f"Void fraction outside (0,1): {bad}"


# ── Summary helper (run with -s to see) ──────────────────────────────────────

def test_print_summary(extraction_result):
    """Print a human-readable summary of what was extracted."""
    mofs = extraction_result.mofs
    print(f"\n{'='*60}")
    print(f"Extracted {len(mofs)} unique MOF(s) from paper")
    print(f"{'='*60}")
    for m in mofs:
        print(f"\n  {m.mof_name}")
        if m.metal_node:
            print(f"    metal:    {m.metal_node}")
        if m.topology:
            print(f"    topology: {m.topology}")
        if m.has_open_metal_site is not None:
            print(f"    OMS:      {m.has_open_metal_site}")
        if m.surface_area_m2_g:
            print(f"    SA:       {m.surface_area_m2_g} m²/g")
        if m.pore_limiting_diameter_A:
            print(f"    PLD:      {m.pore_limiting_diameter_A} Å")
        if m.void_fraction:
            print(f"    VF:       {m.void_fraction}")
        if m.thermal_stability_c:
            print(f"    thermal:  {m.thermal_stability_c} °C")
        if m.water_stability:
            print(f"    water:    {m.water_stability}")
        print(f"    measurements ({len(m.measurements)}):")
        for ms in m.measurements:
            cond = ""
            if ms.temperature_k:
                cond += f" @{ms.temperature_k}K"
            if ms.pressure_bar:
                cond += f"/{ms.pressure_bar}bar"
            sel = f" ({ms.selectivity_definition})" if ms.selectivity_definition else ""
            print(f"      [{ms.type}] {ms.value} {ms.unit}{sel}{cond}  conf={ms.confidence:.2f}")
            if ms.evidence_quote:
                print(f"        evidence: \"{ms.evidence_quote[:100]}\"")
    print(f"\n{'='*60}\n")
