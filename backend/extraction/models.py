from __future__ import annotations
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator


class Measurement(BaseModel):
    """One measured performance point at a specific condition."""
    type: str = "co2_uptake"   # co2_uptake | selectivity | working_capacity
    value: Optional[float] = None
    unit: str = ""
    temperature_k: Optional[float] = None
    pressure_bar: Optional[float] = None
    selectivity_definition: str = ""   # e.g. "CO2/N2", "CO2/CH4"
    application_type: str = ""         # DAC | post_combustion | pre_combustion
    evidence_quote: str = ""
    confidence: float = 0.0

    @field_validator("type", "unit", "selectivity_definition", "application_type",
                     "evidence_quote", mode="before")
    @classmethod
    def _coerce(cls, v): return v or ""


class MOFRecord(BaseModel):
    """
    One unique MOF material from a paper.
    Structural/identity fields are top-level.
    All measured performance data (CO2 uptake, selectivity, working capacity)
    lives in the measurements list — one entry per condition.
    """
    mof_name: str = ""
    metal_node: str = ""
    functionalization: str = ""

    # Structural (aligns with CoRE MOF CSV)
    surface_area_m2_g: Optional[float] = None          # ASA (m2/g)
    pore_volume_cm3_g: Optional[float] = None          # PV (cm3/g)
    pore_limiting_diameter_A: Optional[float] = None   # PLD (Å)
    largest_cavity_diameter_A: Optional[float] = None  # LCD (Å)
    void_fraction: Optional[float] = None              # VF
    crystal_density_g_cm3: Optional[float] = None      # Density (g/cm3)
    topology: str = ""                                  # e.g. "pcu", "sod"
    has_open_metal_site: Optional[bool] = None         # Has OMS

    # Stability (aligns with CoRE MOF)
    water_stability: str = ""
    thermal_stability_c: Optional[float] = None        # Thermal_stability (℃)
    stability_notes: str = ""

    # All measured performance points
    measurements: List[Measurement] = Field(default_factory=list)

    @field_validator("mof_name", "metal_node", "functionalization",
                     "water_stability", "topology", "stability_notes", mode="before")
    @classmethod
    def _coerce(cls, v): return v or ""

    @field_validator("measurements", mode="before")
    @classmethod
    def _meas(cls, v): return v if isinstance(v, list) else []


class PaperMeta(BaseModel):
    title: str = ""
    year: Optional[int] = None
    url: str = ""
    doi: str = ""
    pmcid: str = ""
    source: str = "semantic_scholar"
    open_access_pdf: str = ""
    citation_count: Optional[int] = None
    publication_date: str = ""
    abstract: str = ""
    authors: List[str] = Field(default_factory=list)

    @field_validator("title", "url", "doi", "pmcid", "open_access_pdf",
                     "publication_date", "abstract", "source", mode="before")
    @classmethod
    def _coerce(cls, v): return v or ""


class ExtractionResult(BaseModel):
    paper: PaperMeta = Field(default_factory=PaperMeta)
    mofs: List[MOFRecord] = Field(default_factory=list)
