"""
Database operations for papers and MOF records.
"""
from __future__ import annotations
import json
import sqlite3
from contextlib import contextmanager
from typing import Optional
from config import MOF_DB_PATH
from database.schema import init_db


@contextmanager
def _conn():
    con = sqlite3.connect(str(MOF_DB_PATH))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    init_db(con)
    try:
        yield con
        con.commit()
    finally:
        con.close()


# ── Papers ────────────────────────────────────────────────────────────────────

def upsert_paper(paper: dict) -> int:
    doi   = (paper.get("doi") or "").strip()
    title = (paper.get("title") or "").strip()
    with _conn() as con:
        cur = con.cursor()
        if doi:
            cur.execute("SELECT id FROM papers WHERE doi = ?", (doi,))
        else:
            cur.execute("SELECT id FROM papers WHERE title = ?", (title,))
        row = cur.fetchone()
        authors = json.dumps(paper.get("authors") or [])
        if row:
            pid = row["id"]
            cur.execute("""
                UPDATE papers SET title=?, year=?, url=?, pmcid=?, source=?,
                    open_access_pdf=?, citation_count=?, publication_date=?,
                    abstract=?, authors=? WHERE id=?
            """, (title, paper.get("year"), paper.get("url"), paper.get("pmcid"),
                  paper.get("source"), paper.get("open_access_pdf"),
                  paper.get("citation_count"), paper.get("publicationDate") or paper.get("publication_date"),
                  paper.get("abstract"), authors, pid))
        else:
            cur.execute("""
                INSERT INTO papers (title, year, url, doi, pmcid, source, open_access_pdf,
                    citation_count, publication_date, abstract, authors)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (title, paper.get("year"), paper.get("url"), doi,
                  paper.get("pmcid"), paper.get("source"), paper.get("open_access_pdf"),
                  paper.get("citation_count"),
                  paper.get("publicationDate") or paper.get("publication_date"),
                  paper.get("abstract"), authors))
            pid = cur.lastrowid
    return int(pid)


def update_paper_status(paper_id: int, status: str, reason: str = "",
                        fulltext_chars: int = 0, fulltext_method: str = "") -> None:
    with _conn() as con:
        con.execute("""
            UPDATE papers SET status=?, failure_reason=?, fulltext_chars=?, fulltext_method=?
            WHERE id=?
        """, (status, reason, fulltext_chars or None, fulltext_method or None, paper_id))


def paper_already_done(doi: str, title: str = "") -> tuple[bool, str]:
    """Return (True, status) if paper was successfully processed (extracted or no_mofs).
    Failed papers are NOT considered done — they should be retried."""
    terminal = ("extracted", "no_mofs")
    with _conn() as con:
        if doi:
            row = con.execute(
                "SELECT status FROM papers WHERE doi=? AND status IN (?,?)", (doi, *terminal)
            ).fetchone()
        else:
            row = con.execute(
                "SELECT status FROM papers WHERE title=? AND status IN (?,?)", (title, *terminal)
            ).fetchone()
    return (True, row["status"]) if row else (False, "")


def list_papers(limit: int = 200) -> list[dict]:
    with _conn() as con:
        rows = con.execute("""
            SELECT id, title, year, doi, source, status, failure_reason,
                   fulltext_chars, fulltext_method, citation_count,
                   publication_date, abstract, authors, created_at
            FROM papers ORDER BY id DESC LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_paper(paper_id: int) -> dict | None:
    with _conn() as con:
        row = con.execute("""
            SELECT id, title, year, url, doi, pmcid, source, status, failure_reason,
                   fulltext_chars, fulltext_method, citation_count, publication_date,
                   abstract, authors, created_at
            FROM papers WHERE id=?
        """, (paper_id,)).fetchone()
    return dict(row) if row else None


# ── Literature MOF records ────────────────────────────────────────────────────

def insert_literature_mofs(paper_id: int, paper_doi: str, paper_title: str,
                           mofs) -> int:
    """
    Insert MOFRecord list from literature extraction.
    One mofs row per unique (mof_name, paper_doi) — structural + best performance summary.
    All individual measurement conditions go into mof_measurements.
    Returns total measurement rows inserted.
    """
    total_measurements = 0
    with _conn() as con:
        for m in mofs:
            name_key = (m.mof_name or "").lower().strip()
            if not name_key:
                continue

            # Best CO2 uptake (highest confidence) — stored on mofs row for sorting/filtering
            co2_meas = sorted(
                [ms for ms in m.measurements if ms.type == "co2_uptake" and ms.value is not None],
                key=lambda x: x.confidence, reverse=True,
            )
            best_co2 = co2_meas[0] if co2_meas else None

            sel_meas = sorted(
                [ms for ms in m.measurements if ms.type == "selectivity" and ms.value is not None],
                key=lambda x: x.confidence, reverse=True,
            )
            best_sel = sel_meas[0] if sel_meas else None

            wc_meas = [ms for ms in m.measurements if ms.type == "working_capacity" and ms.value is not None]
            best_wc = wc_meas[0] if wc_meas else None

            oms_int = (1 if m.has_open_metal_site is True else
                       0 if m.has_open_metal_site is False else None)

            # Upsert mofs row — one per (name, paper_doi)
            existing = con.execute(
                "SELECT id FROM mofs WHERE lower(name)=? AND paper_doi=? AND source='literature'",
                (name_key, paper_doi),
            ).fetchone()

            if existing:
                mof_id = existing["id"]
                # Fill in any structural fields that were missing
                con.execute("""
                    UPDATE mofs SET
                        metal_node      = COALESCE(NULLIF(metal_node,''), ?),
                        functionalization = COALESCE(NULLIF(functionalization,''), ?),
                        topology        = COALESCE(NULLIF(topology,''), ?),
                        has_open_metal_site = COALESCE(has_open_metal_site, ?),
                        surface_area_m2_g        = COALESCE(surface_area_m2_g, ?),
                        pore_volume_cm3_g        = COALESCE(pore_volume_cm3_g, ?),
                        pore_limiting_diameter_A = COALESCE(pore_limiting_diameter_A, ?),
                        largest_cavity_diameter_A = COALESCE(largest_cavity_diameter_A, ?),
                        void_fraction            = COALESCE(void_fraction, ?),
                        crystal_density_g_cm3    = COALESCE(crystal_density_g_cm3, ?),
                        water_stability     = COALESCE(NULLIF(water_stability,''), ?),
                        thermal_stability_c = COALESCE(thermal_stability_c, ?),
                        stability_notes     = COALESCE(NULLIF(stability_notes,''), ?),
                        co2_uptake_value    = COALESCE(co2_uptake_value, ?),
                        co2_uptake_unit     = COALESCE(NULLIF(co2_uptake_unit,''), ?),
                        temperature_k       = COALESCE(temperature_k, ?),
                        pressure_bar        = COALESCE(pressure_bar, ?),
                        selectivity_value   = COALESCE(selectivity_value, ?),
                        selectivity_definition = COALESCE(NULLIF(selectivity_definition,''), ?),
                        application_type    = COALESCE(NULLIF(application_type,''), ?),
                        working_capacity_mmol_g = COALESCE(working_capacity_mmol_g, ?),
                        confidence          = MAX(COALESCE(confidence,0), ?)
                    WHERE id = ?
                """, (
                    m.metal_node, m.functionalization, m.topology or "", oms_int,
                    m.surface_area_m2_g, m.pore_volume_cm3_g,
                    m.pore_limiting_diameter_A, m.largest_cavity_diameter_A,
                    m.void_fraction, m.crystal_density_g_cm3,
                    m.water_stability, m.thermal_stability_c, m.stability_notes,
                    best_co2.value if best_co2 else None,
                    best_co2.unit if best_co2 else None,
                    best_co2.temperature_k if best_co2 else None,
                    best_co2.pressure_bar if best_co2 else None,
                    best_sel.value if best_sel else None,
                    best_sel.selectivity_definition if best_sel else None,
                    best_co2.application_type if best_co2 else (best_sel.application_type if best_sel else None),
                    best_wc.value if best_wc else None,
                    max((ms.confidence for ms in m.measurements), default=0.0),
                    mof_id,
                ))
            else:
                con.execute("""
                    INSERT INTO mofs (
                        source, name, metal_node, functionalization,
                        topology, has_open_metal_site,
                        surface_area_m2_g, pore_volume_cm3_g, pore_limiting_diameter_A,
                        largest_cavity_diameter_A, void_fraction, crystal_density_g_cm3,
                        water_stability, thermal_stability_c, stability_notes,
                        co2_uptake_value, co2_uptake_unit, temperature_k, pressure_bar,
                        selectivity_value, selectivity_definition, application_type,
                        working_capacity_mmol_g,
                        evidence_quote, confidence, paper_id, paper_doi, paper_title
                    ) VALUES (
                        'literature', ?, ?, ?,
                        ?, ?,
                        ?, ?, ?, ?, ?, ?,
                        ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?,
                        ?,
                        ?, ?, ?, ?, ?
                    )
                """, (
                    m.mof_name, m.metal_node, m.functionalization,
                    m.topology or "", oms_int,
                    m.surface_area_m2_g, m.pore_volume_cm3_g,
                    m.pore_limiting_diameter_A, m.largest_cavity_diameter_A,
                    m.void_fraction, m.crystal_density_g_cm3,
                    m.water_stability, m.thermal_stability_c, m.stability_notes,
                    best_co2.value if best_co2 else None,
                    best_co2.unit if best_co2 else None,
                    best_co2.temperature_k if best_co2 else None,
                    best_co2.pressure_bar if best_co2 else None,
                    best_sel.value if best_sel else None,
                    best_sel.selectivity_definition if best_sel else None,
                    best_co2.application_type if best_co2 else (best_sel.application_type if best_sel else None),
                    best_wc.value if best_wc else None,
                    best_co2.evidence_quote if best_co2 else "",
                    max((ms.confidence for ms in m.measurements), default=0.0),
                    paper_id, paper_doi, paper_title,
                ))
                mof_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

            # Insert all individual measurements
            for ms in m.measurements:
                if ms.value is None:
                    continue
                con.execute("""
                    INSERT INTO mof_measurements (
                        mof_id, measurement_type, value, unit,
                        temperature_k, pressure_bar, selectivity_definition,
                        application_type, evidence_quote, confidence,
                        paper_id, paper_doi, paper_title
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    mof_id, ms.type, ms.value, ms.unit,
                    ms.temperature_k, ms.pressure_bar,
                    ms.selectivity_definition, ms.application_type,
                    ms.evidence_quote, ms.confidence,
                    paper_id, paper_doi, paper_title,
                ))
                total_measurements += 1

    return total_measurements


def import_core_mof_csv(csv_path: str) -> int:
    """Import CoRE MOF CSV into the mofs table. Returns count inserted."""
    import csv
    inserted = 0
    with _conn() as con:
        with open(csv_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                def _f(key: str):
                    v = row.get(key, "").strip()
                    try:
                        return float(v) if v else None
                    except ValueError:
                        return None

                name = row.get("name", "").strip() or row.get("refcode", "").strip()
                if not name:
                    continue
                structure_type = "ASR" if "ASR" in (row.get("coreid") or "") else ("FSR" if "FSR" in (row.get("coreid") or "") else "")
                has_oms = (row.get("Has OMS") or "").strip().lower()
                con.execute("""
                    INSERT OR IGNORE INTO mofs (
                        source, source_dataset, name, refcode, coreid,
                        metal_node, topology,
                        surface_area_m2_g, pore_volume_cm3_g, pore_limiting_diameter_A,
                        largest_cavity_diameter_A, void_fraction, crystal_density_g_cm3,
                        has_open_metal_site,
                        water_stability_score, solvent_stability_score, thermal_stability_c,
                        henry_law_co2_class
                    ) VALUES (
                        'core_mof', ?, ?, ?, ?,
                        ?, ?,
                        ?, ?, ?,
                        ?, ?, ?,
                        ?,
                        ?, ?, ?,
                        ?
                    )
                """, (
                    structure_type, name, row.get("refcode", "").strip(), row.get("coreid", "").strip(),
                    (row.get("Metal Types") or "").strip(),
                    (row.get("topology(SingleNodes)") or "").strip(),
                    _f("ASA (m2/g)"), _f("PV (cm3/g)"), _f("PLD (Å)"),
                    _f("LCD (Å)"), _f("VF"), _f("Density (g/cm3)"),
                    1 if has_oms in ("yes", "1", "true") else 0,
                    _f("Water_stability"), _f("Solvent_stability"), _f("Thermal_stability (℃)"),
                    (row.get("KH_Classes") or "").strip(),
                ))
                inserted += 1
    return inserted


def import_core_mof_directory(directory: str) -> dict:
    """Import Becc's CoRE MOF ASR/FSR CSV directory into the unified mofs table."""
    from pathlib import Path
    root = Path(directory)
    candidates = [
        root / "FSR_data_SI_20250204.csv",
        root / "ASR_data_SI_20250204.csv",
    ]
    imported: dict[str, int] = {}
    for path in candidates:
        if path.exists():
            imported[path.name] = import_core_mof_csv(str(path))
    return imported


# ── MOF queries ───────────────────────────────────────────────────────────────

def query_mofs(
    source: Optional[str] = None,
    metal: Optional[str] = None,
    application_type: Optional[str] = None,
    min_surface_area: Optional[float] = None,
    min_co2_uptake: Optional[float] = None,
    min_selectivity: Optional[float] = None,
    min_confidence: float = 0.0,
    search: Optional[str] = None,
    sort_by: str = "surface_area_m2_g",
    sort_desc: bool = True,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Returns (rows, total_count)."""
    conditions = []
    params: list = []

    if source:
        conditions.append("source = ?")
        params.append(source)
    if metal:
        conditions.append("metal_node LIKE ?")
        params.append(f"%{metal}%")
    if application_type:
        conditions.append("application_type = ?")
        params.append(application_type)
    if min_surface_area is not None:
        conditions.append("surface_area_m2_g >= ?")
        params.append(min_surface_area)
    if min_co2_uptake is not None:
        conditions.append("co2_uptake_value >= ?")
        params.append(min_co2_uptake)
    if min_selectivity is not None:
        conditions.append("selectivity_value >= ?")
        params.append(min_selectivity)
    if min_confidence > 0:
        conditions.append("(source = 'core_mof' OR confidence >= ?)")
        params.append(min_confidence)
    if search:
        conditions.append("(name LIKE ? OR metal_node LIKE ? OR paper_title LIKE ?)")
        params += [f"%{search}%"] * 3

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    _SAFE_COLS = {"surface_area_m2_g", "co2_uptake_value", "selectivity_value",
                  "confidence", "thermal_stability_c", "name", "created_at",
                  "water_stability_score", "solvent_stability_score",
                  "pore_limiting_diameter_A", "void_fraction"}
    order_col = sort_by if sort_by in _SAFE_COLS else "surface_area_m2_g"
    order = f"ORDER BY {order_col} {'DESC' if sort_desc else 'ASC'} NULLS LAST"

    with _conn() as con:
        total = con.execute(f"SELECT COUNT(*) FROM mofs {where}", params).fetchone()[0]
        rows = con.execute(
            f"SELECT * FROM mofs {where} {order} LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

        # Embed measurements for literature records
        result = [dict(r) for r in rows]
        lit_ids = [r["id"] for r in result if r["source"] == "literature"]
        if lit_ids:
            placeholders = ",".join("?" * len(lit_ids))
            meas_rows = con.execute(
                f"SELECT * FROM mof_measurements WHERE mof_id IN ({placeholders})"
                " ORDER BY mof_id, measurement_type, confidence DESC",
                lit_ids,
            ).fetchall()
            by_mof: dict[int, list] = {}
            for mr in meas_rows:
                by_mof.setdefault(mr["mof_id"], []).append(dict(mr))
            for r in result:
                r["measurements"] = by_mof.get(r["id"], [])
        else:
            for r in result:
                r["measurements"] = []

    return result, total


def get_mofs_by_paper(paper_id: int) -> list[dict]:
    """Return all MOF records (with measurements) for a given paper_id."""
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM mofs WHERE source='literature' AND id IN "
            "(SELECT DISTINCT mof_id FROM mof_measurements WHERE paper_id=?)"
            " ORDER BY name",
            (paper_id,),
        ).fetchall()
        result = [dict(r) for r in rows]
        if result:
            ids = [r["id"] for r in result]
            placeholders = ",".join("?" * len(ids))
            meas_rows = con.execute(
                f"SELECT * FROM mof_measurements WHERE mof_id IN ({placeholders})"
                " AND paper_id=? ORDER BY mof_id, measurement_type, confidence DESC",
                ids + [paper_id],
            ).fetchall()
            by_mof: dict[int, list] = {}
            for mr in meas_rows:
                by_mof.setdefault(mr["mof_id"], []).append(dict(mr))
            for r in result:
                r["measurements"] = by_mof.get(r["id"], [])
    return result


def get_mof_measurements(mof_id: int) -> list[dict]:
    """Return all measurements for a single MOF record."""
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM mof_measurements WHERE mof_id=?"
            " ORDER BY measurement_type, confidence DESC",
            (mof_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Agent memory ─────────────────────────────────────────────────────────────

def save_agent_memory(query: str, intent: str, summary: str,
                      embedding: list[float]) -> int:
    """Persist a query + response summary + embedding for future context recall."""
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO agent_memory (query, intent, summary, query_embedding) VALUES (?,?,?,?)",
            (query, intent, summary, json.dumps(embedding)),
        )
        return int(cur.lastrowid)


def search_agent_memory(embedding: list[float], top_k: int = 3,
                        min_similarity: float = 0.72) -> list[dict]:
    """
    Find past queries whose embeddings are most similar to the given one.
    Returns up to top_k results above min_similarity, sorted descending.
    """
    import numpy as np

    with _conn() as con:
        rows = con.execute(
            "SELECT query, intent, summary, query_embedding FROM agent_memory"
            " ORDER BY created_at DESC LIMIT 2000"
        ).fetchall()

    if not rows:
        return []

    q = np.array(embedding, dtype=np.float32)
    q_norm = np.linalg.norm(q)
    if q_norm == 0:
        return []
    q /= q_norm

    results: list[dict] = []
    for row in rows:
        try:
            emb = np.array(json.loads(row["query_embedding"]), dtype=np.float32)
            emb_norm = np.linalg.norm(emb)
            if emb_norm == 0:
                continue
            emb /= emb_norm
            sim = float(np.dot(q, emb))
            if sim >= min_similarity:
                results.append({
                    "query":      row["query"],
                    "intent":     row["intent"],
                    "summary":    row["summary"],
                    "similarity": round(sim, 3),
                })
        except Exception:
            continue

    results.sort(key=lambda x: -x["similarity"])
    return results[:top_k]


def get_db_stats() -> dict:
    with _conn() as con:
        total   = con.execute("SELECT COUNT(*) FROM mofs").fetchone()[0]
        core    = con.execute("SELECT COUNT(*) FROM mofs WHERE source='core_mof'").fetchone()[0]
        lit     = con.execute("SELECT COUNT(*) FROM mofs WHERE source='literature'").fetchone()[0]
        papers  = con.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        extracted = con.execute("SELECT COUNT(*) FROM papers WHERE status='extracted'").fetchone()[0]
        app_counts = {r[0]: r[1] for r in con.execute(
            "SELECT application_type, COUNT(*) FROM mofs WHERE source='literature' "
            "GROUP BY application_type"
        ).fetchall()}
    return {
        "total_mofs": total, "core_mof": core, "literature": lit,
        "papers_total": papers, "papers_extracted": extracted,
        "application_types": app_counts,
    }
