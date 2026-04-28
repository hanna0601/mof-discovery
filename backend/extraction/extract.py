"""
LLM extraction: gpt-4o single-call (full paper, no chunking).
Falls back to Groq chunked if needed.
One MOFRecord per unique material — all measurement conditions in a measurements list.
"""
from __future__ import annotations
import json
import logging
import time
from typing import Optional
from pydantic import ValidationError
from .models import ExtractionResult, MOFRecord, Measurement, PaperMeta
from config import OPENAI_API_KEY, OPENAI_MODEL, GROQ_KEY, GROQ_MODEL

logger = logging.getLogger(__name__)

CHUNK_SIZE    = 12_000
CHUNK_OVERLAP = 1_500
CHUNK_SLEEP   = 8.0

_MOF_TERMS = {"metal-organic framework", "mof", "mofs", "metal organic framework",
              "mof-74", "mil-", "uio-", "zif-", "hkust", "irmof", "mof74"}
_CO2_TERMS = {"co2", "carbon dioxide", "carbon capture", "co₂",
              "direct air capture", "dac", "flue gas", "post-combustion",
              "pre-combustion", "co2 capture", "greenhouse gas"}
_NON_CO2_SEL = ("c2h2/c2h4", "c2h4/c2h6", "ch4/n2", "n2/ch4", "h2/co2", "n2/o2")

# Names containing these substrings are non-MOF comparison materials and must be dropped.
_EXCLUDE_NAME_TERMS = (
    "zeolite", "activated carbon", "carbon nanotube", "graphene",
    "cof ", "covalent organic", "silica", "alumina", "amine-modified silica",
)

SYSTEM_PROMPT = """You extract MOF (Metal-Organic Framework) data from scientific papers for CO2 capture research.

Return JSON ONLY matching this exact schema:

{
  "paper": {
    "title": "", "year": 2025, "url": "", "doi": "",
    "source": "semantic_scholar",
    "open_access_pdf": "", "pmcid": "", "citation_count": 0, "publication_date": ""
  },
  "mofs": [
    {
      "mof_name": "",
      "metal_node": "",
      "functionalization": "",
      "topology": "",
      "has_open_metal_site": null,
      "surface_area_m2_g": null,
      "pore_volume_cm3_g": null,
      "pore_limiting_diameter_A": null,
      "largest_cavity_diameter_A": null,
      "void_fraction": null,
      "crystal_density_g_cm3": null,
      "water_stability": "",
      "thermal_stability_c": null,
      "stability_notes": "",
      "measurements": [
        {
          "type": "co2_uptake",
          "value": null,
          "unit": "",
          "temperature_k": null,
          "pressure_bar": null,
          "application_type": "",
          "evidence_quote": "",
          "confidence": 0.0
        }
      ]
    }
  ]
}

CRITICAL — one entry per MOF material:
- Return ONE top-level entry per unique MOF (e.g. one entry for HKUST-1, not one per condition).
- All measured conditions for the same MOF go inside its measurements array.
- Use the MOF's standard name as in the paper (e.g. "UiO-66-NH2", "HKUST-1", "MIL-101(Cr)").
- Exclude zeolites (e.g. zeolite 13X, NaX, SAPO), activated carbons, COFs, silica, graphene, carbon nanotubes, and materials used only as comparisons.
- For composite/core-shell materials (e.g. "zeolite@MOF", "MOF/AC"), include ONLY if the MOF component is the primary focus. Use the composite's actual name (e.g. "zeolite 13X@ZIF-8" is acceptable as a composite MOF entry).

measurements array — one entry per distinct measurement:
- type: "co2_uptake" | "selectivity" | "working_capacity"
- For co2_uptake: fill value, unit, temperature_k, pressure_bar, application_type.
- For selectivity: fill value, selectivity_definition (e.g. "CO2/N2"), temperature_k.
- For working_capacity: fill value (mmol/g), temperature_k, pressure_bar range as note in evidence_quote.
- CO2 measurements ONLY. Never N2, CH4, C2H2, C2H4, C2H6 uptake as co2_uptake.
- Selectivity CO2-related only (CO2/N2, CO2/CH4, CO2/H2O). Skip C2H2/C2H4, N2/CH4, N2/O2.

Structural fields — extract only explicitly stated values:
- surface_area_m2_g: BET or Langmuir in m²/g.
- pore_volume_cm3_g: total pore volume in cm³/g.
- pore_limiting_diameter_A: smallest pore diameter in Å (convert nm→Å: ×10).
- largest_cavity_diameter_A: largest cavity diameter in Å (convert nm→Å: ×10).
- void_fraction: 0–1, only if explicitly stated.
- crystal_density_g_cm3: crystal density in g/cm³, only if explicitly stated.
- topology: net topology symbol if named (e.g. "pcu", "sod", "dia"). Empty string if not mentioned.
- has_open_metal_site: true if OMS/CUS stated, false if explicitly absent, null if not mentioned.
- thermal_stability_c: numeric °C from TGA ("stable up to 400°C" → 400.0).
- water_stability: text description from paper ("high", "stable in water", etc.).

application_type classification:
- "DAC" (~400 ppm CO2, very low partial pressure)
- "post_combustion" (~10–15% CO2, ~0.1–0.15 bar)
- "pre_combustion" (>1 bar CO2)
- "" if ambiguous

evidence_quote: exact sentence from paper containing the specific number.
confidence per measurement:
- 0.9–1.0: value + unit + T + P all present
- 0.7–0.89: value + unit, T or P inferred
- 0.5–0.69: value present, units/conditions unclear
- 0.0–0.49: approximate or inferred

Return empty "mofs": [] if no MOF performance data found.
"""


def abstract_is_relevant(abstract: str, title: str = "") -> bool:
    if not abstract and not title:
        return True
    # Check both abstract and title — some papers put key terms only in the title
    combined = (abstract + " " + title).lower()
    return any(t in combined for t in _MOF_TERMS) and any(t in combined for t in _CO2_TERMS)


def extract_with_llm(full_text: str, paper_meta: PaperMeta) -> ExtractionResult:
    """Single-call extraction with gpt-4o, Groq chunked as fallback."""
    if OPENAI_API_KEY:
        result = _single_call(full_text, paper_meta, _openai_chat)
        if result.mofs:
            return result
        logger.info("gpt-4o returned no MOFs for '%s' — falling back to Groq chunks", paper_meta.title[:50])

    if GROQ_KEY:
        return _chunked(full_text, paper_meta)

    return ExtractionResult(paper=paper_meta, mofs=[])


def _single_call(full_text: str, meta: PaperMeta, chat_fn) -> ExtractionResult:
    payload  = {"paper": meta.model_dump(), "full_text": full_text}
    user_msg = json.dumps(payload, ensure_ascii=False)
    raw = _llm_call(user_msg, chat_fn=chat_fn)
    if raw is None:
        return ExtractionResult(paper=meta, mofs=[])
    raw = _strip_fences(raw.strip())
    try:
        result = ExtractionResult.model_validate(json.loads(raw))
        mofs = _merge(_filter_co2(result.mofs))
        return ExtractionResult(paper=meta, mofs=mofs)
    except (json.JSONDecodeError, ValidationError) as e:
        logger.warning("Parse failed for '%s': %s", meta.title[:50], e)
        return ExtractionResult(paper=meta, mofs=[])


def _chunked(full_text: str, meta: PaperMeta) -> ExtractionResult:
    chunks = _chunk(full_text)
    all_mofs: list[MOFRecord] = []
    for i, chunk in enumerate(chunks):
        if i > 0:
            time.sleep(CHUNK_SLEEP)
        payload  = {"paper": meta.model_dump(), "full_text": chunk, "chunk_info": f"{i+1}/{len(chunks)}"}
        user_msg = json.dumps(payload, ensure_ascii=False)
        raw = _llm_call(user_msg, chat_fn=_groq_chat)
        if raw is None:
            continue
        raw = _strip_fences(raw.strip())
        try:
            result = ExtractionResult.model_validate(json.loads(raw))
            all_mofs.extend(result.mofs)
        except (json.JSONDecodeError, ValidationError):
            pass
    return ExtractionResult(paper=meta, mofs=_merge(_filter_co2(all_mofs)))


def _filter_co2(mofs: list[MOFRecord]) -> list[MOFRecord]:
    """Remove non-CO2 measurements and non-MOF materials (zeolites, carbons, COFs)."""
    out = []
    for m in mofs:
        name_lower = (m.mof_name or "").lower()
        # For composites like "zeolite 13X@ZIF-8", the part after @ is the MOF shell —
        # keep them. For pure non-MOF names, drop.
        is_composite = "@" in name_lower or "/" in name_lower
        if not is_composite and any(t in name_lower for t in _EXCLUDE_NAME_TERMS):
            logger.debug("Dropping non-MOF material: %s", m.mof_name)
            continue
        valid: list[Measurement] = []
        for ms in m.measurements:
            if ms.value is None:          # drop empty placeholders
                continue
            if ms.type == "selectivity":
                sel_def = (ms.selectivity_definition or "").lower()
                if sel_def and any(p in sel_def for p in _NON_CO2_SEL):
                    continue
                if sel_def and "co2" not in sel_def:
                    continue
            valid.append(ms)
        m = m.model_copy(update={"measurements": valid})
        has_data = (bool(valid)
                    or m.surface_area_m2_g is not None
                    or m.pore_volume_cm3_g is not None
                    or m.pore_limiting_diameter_A is not None)
        if has_data:
            out.append(m)
    return out


def _meas_key(ms: Measurement) -> tuple:
    """Dedup key for a measurement: type + value + T + P."""
    return (ms.type, ms.value, ms.temperature_k, ms.pressure_bar,
            ms.selectivity_definition or "")


def _merge(mofs: list[MOFRecord]) -> list[MOFRecord]:
    """
    Merge records for the same MOF name (case-insensitive).
    Combines measurements, fills structural gaps from other mentions of the same MOF.
    Deduplcates measurements by (type, value, T, P).
    """
    seen: dict[str, MOFRecord] = {}
    for m in mofs:
        key = (m.mof_name or "").lower().strip()
        if not key:
            continue
        if key not in seen:
            seen[key] = m
            continue

        existing = seen[key]
        updates: dict = {}

        # Combine and dedup measurements
        existing_keys = {_meas_key(ms) for ms in existing.measurements}
        new_meas = [ms for ms in m.measurements if _meas_key(ms) not in existing_keys]
        if new_meas:
            updates["measurements"] = existing.measurements + new_meas

        # Fill structural gaps
        for field in ("surface_area_m2_g", "pore_volume_cm3_g", "pore_limiting_diameter_A",
                      "largest_cavity_diameter_A", "void_fraction", "crystal_density_g_cm3",
                      "thermal_stability_c"):
            if getattr(existing, field) is None and getattr(m, field) is not None:
                updates[field] = getattr(m, field)
        for field in ("water_stability", "stability_notes", "topology",
                      "functionalization", "metal_node"):
            if not getattr(existing, field) and getattr(m, field):
                updates[field] = getattr(m, field)
        if existing.has_open_metal_site is None and m.has_open_metal_site is not None:
            updates["has_open_metal_site"] = m.has_open_metal_site

        if updates:
            seen[key] = existing.model_copy(update=updates)

    return list(seen.values())


def _chunk(text: str) -> list[str]:
    if len(text) <= CHUNK_SIZE:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        if end < len(text):
            boundary = text.rfind(". ", start + CHUNK_SIZE // 2, end)
            if boundary != -1:
                end = boundary + 1
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - CHUNK_OVERLAP
    return chunks


def _llm_call(user_msg: str, chat_fn=None, retries: int = 3) -> Optional[str]:
    if chat_fn is None:
        chat_fn = _openai_chat if OPENAI_API_KEY else (_groq_chat if GROQ_KEY else None)
    if chat_fn is None:
        return None
    for attempt in range(retries):
        try:
            return chat_fn(user_msg)
        except Exception as e:
            err = str(e).lower()
            if "429" in err or "rate" in err or "quota" in err:
                wait = 60 * (attempt + 1)
                logger.warning("Rate limit — sleeping %ds", wait)
                time.sleep(wait)
            else:
                logger.error("LLM error: %s", e)
                return None
    return None


def _openai_chat(user_msg: str) -> str:
    import requests as _req
    r = _req.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
        json={"model": OPENAI_MODEL,
              "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                           {"role": "user",   "content": user_msg}],
              "temperature": 0.0, "max_tokens": 8000},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _groq_chat(user_msg: str) -> str:
    from groq import Groq
    resp = Groq(api_key=GROQ_KEY).chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "system", "content": SYSTEM_PROMPT},
                  {"role": "user",   "content": user_msg}],
        temperature=0.0, max_tokens=4000,
    )
    return resp.choices[0].message.content or ""


def _strip_fences(raw: str) -> str:
    idx = raw.find("```")
    if idx != -1:
        raw = raw[idx + 3:].strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
        end = raw.find("```")
        if end != -1:
            raw = raw[:end].strip()
    return raw
