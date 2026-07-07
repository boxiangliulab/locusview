# Design — Gene-page visualizations: LD-colored regional plot + tissue body map

- **Status:** Accepted; **reconciled with Liu Fei's mockup (2026-07-07)**. Backend shipped (#25); frontend = #27.
- **Diátaxis:** Design/Explanation (a spec — the *how*, with the *why*).
- **Related:** [gene page](../../src/locusview/web.py) · [repository](../../src/locusview/repository.py) ·
  [ADR-0008 (shared DB)](../adr/0008-store-qtl-in-locuscompare2-database.md) ·
  [schema-change coordination](../process/schema-change-coordination.md) · issue #18 (effect allele).
- **Provenance:** distilled from a 4-agent web-verified research workflow; team decisions applied
  (Plotly-first; plot before body map; eQTL body map).

## Goal
Make the gene page show *where and how strong* a gene's eQTLs are:
1. **A regional association plot** (LocusZoom-style) for one gene × one tissue: variants by genomic
   position vs −log₁₀(p), **colored by LD r² to a lead variant** (default = strongest; click to
   re-color). Reference look: locuszoom.org.
2. **A tissue body map** (anatomogram) highlighting which GTEx tissues have a significant eQTL for
   the gene. Reference: proteinatlas.org / GTEx body map.

## Decisions (locked)
| Decision | Choice |
|---|---|
| Chart library | **Plotly.js `scattergl`** (MIT, one CDN tag), *styled like LocusZoom*. LocusZoom.js deferred as a fidelity upgrade. |
| Why not LocusZoom.js now | Its stock adapters key variants on `chr:pos_ref/alt`, which we lack (#18); Plotly lets us join by our integer `rs_id` cleanly. |
| Build order | **PR 1 = regional plot** (+ LD interactivity); **PR 2 = body map**. |
| Body-map data | **eQTL** (only data we have); endpoints take a `qtl_type` param so sQTL slots in later. |
| DB access | **sync pymysql** via the existing `LocuscompareRepository` connection factory (no async engine). |
| Anatomogram asset | **EBI Expression Atlas** SVGs (UBERON-keyed; **CC-BY 4.0** → visible credit required). |

## Design review — reconciled with Liu Fei's mockup (2026-07-07)
Liu Fei (UI/UX) delivered a full-app mockup:
[`mockups/LocusView_Standalone_v1.html`](mockups/LocusView_Standalone_v1.html) — a design-tool export,
the **visual source of truth** for the frontend (a reference, not drop-in code). Reconciliation:

| Question | Decision |
|---|---|
| Plot rendering | **Plotly.js, styled to match** (reuse the shipped #25 backend + Plotly hover/click). Her mockup hand-draws on `<canvas>`; we adopt the *look*, not the canvas. |
| Palette | Her **blue/slate** system — accent `#2563eb`, text `#1e293b`/`#64748b`, surfaces `#f8fafc`/`#e2e8f0`. |
| Lead-variant marker | **Orange `#f97316`** ("marks the variant in orange"), replacing purple `#9632B8` in `LD_COLORS`. |
| First frontend PR (#27) scope | **Gene-page "Locus View" only**; the rest split into follow-up issues (below). |

**Adopted from the mockup:** LD r² coloring (kept); Gene/Region/Variant input modes (already our
parser); tissue/context + dataset selectors; click-to-pin lead; provenance/citations intent.

**Deferred to their own issues (not in #27):** the tabbed **app shell** (Home / Data Browser / News);
the **Cross-Dataset** comparison view; the **contribution** flow (Phase 5, ADR-0007); the
**citations/references** panel.

## Data model (verified against the live DB)
- Association per gene×tissue: shard `eqtl_snp_{dataset_id}` → `(rs_id int, chrom, position, pvalue,
  beta, se)`; ~5,000 cis variants per gene. **No ref/alt/effect_allele or MAF (#18)** → β *direction*
  is not shown; variant identity = integer `rs_id` + position.
- LD: `tkg_p3v5a_ld_chr{1..22,X}_{AFR,AMR,EAS,EUR,SAS}` → `(SNP_A rsid-string, SNP_B rsid-string,
  R2 double)`, pairs stored in one direction.
- Gene coords: `gencode_v26_hg38` (already used by `resolve_gene`).

---

## Phase A — Regional plot (this PR)

### Endpoints (read-only; existing `create_app` factory)
- `GET /api/gene/{key}/regional?tissue={dataset_id}&population=EUR` → **JSON** (contract below):
  the gene's cis variants in that tissue, each with r² to the **default lead** (min-p variant) in the
  chosen population, so first paint is one request.
- `GET /api/ld?chrom=&lead={rs_id_int}&population=EUR` → **JSON** `{rs_id: r2}` for **re-coloring** to
  a user-clicked lead (association stats never recomputed).
- `GET /gene/{key}/plot?tissue={dataset_id}` → **HTML partial** (HTMX target): a `<div>` + a small
  bootstrap script that fetches the JSON and draws the Plotly plot.

The gene page gains a **tissue `<select>`** (options = `repo.datasets()`); choosing a tissue
HTMX-swaps the plot partial. Default tissue = the gene's most significant tissue.

### JSON contract (`/api/gene/{key}/regional`)
```jsonc
{
  "gene": "TP53", "gene_id": 141510, "tissue": "Liver", "dataset_id": 8,
  "build": "GRCh38", "population": "EUR",
  "region": { "chrom": "17", "start": 7565097, "end": 7790855 },
  "lead": { "rs_id": 12345, "position": 7670000, "log_pvalue": 32.4 },
  "variants": [
    { "rs_id": 12345, "chrom": "17", "position": 7670000,
      "pvalue": 3.98e-33, "log_pvalue": 32.4, "beta": 0.42, "se": 0.03,
      "r2": 1.0, "is_lead": true }
    // ~5000 more; r2 null = no LD data (rendered grey, distinct from low r²)
  ]
}
```

### LD color scheme (frozen constant `LD_COLORS`, shared FE/BE)
Bins broken at 0.2/0.4/0.6/0.8 (current LocusZoom.js defaults):

| r² | color | | r² | color |
|---|---|---|---|---|
| 0.8–1.0 | `#DB3D11` | | 0.2–0.4 | `#26BCE1` |
| 0.6–0.8 | `#F8C32A` | | 0.0–0.2 | `#463699` |
| 0.4–0.6 | `#6EFE68` | | lead | `#f97316` orange (diamond, per Liu Fei) |
|  |  | | null (no LD) | `#AAAAAA` |

Plot extras: horizontal genome-wide-significance line at −log₁₀(5e−8); tooltips show
`rsID · chr:pos · p · β (direction not interpretable)`; a **population selector** {AFR,AMR,EAS,EUR,SAS}
with the caveat: *"LD: 1000G phase 3, {POP} — a single-population approximation for this
multi-ancestry dataset; a visual aid to locus structure, not part of the association inference."*

### New repository methods (Protocol + Fake + Locuscompare)
```python
def cis_associations(self, gene_id: int, dataset_id: int) -> list[EqtlAssociation]:
    """ALL cis variants for one gene in ONE tissue (the regional set)."""

def ld_r2(self, chrom: str, lead_rs_id: int, population: str) -> dict[int, float]:
    """{int rs_id -> r2} to the lead, from the 1000G LD table."""

def tissues_with_signal(self, gene_id: int, p_threshold: float = 1e-5
                        ) -> list[tuple[int, str, float]]:
    """(dataset_id, tissue, min_pvalue) — drives the body map (Phase B)."""
```
Pure helpers (module-level, unit-tested like `_shard_table`): `_ld_table(chrom, pop)` with
`CHROMS`/`POPS` whitelists (never interpolate raw input); `LD_COLORS` + `r2_bin()`.

### LD query (symmetric pairs; rsID↔int bridge; NA handling)
```sql
SELECT partner, MAX(R2) AS r2 FROM (
  SELECT SNP_B AS partner, R2 FROM {ld_table} WHERE SNP_A = %s
  UNION ALL
  SELECT SNP_A AS partner, R2 FROM {ld_table} WHERE SNP_B = %s
) t GROUP BY partner;                    -- %s bound = 'rs{lead_int}'
```
Parse partners with `^rs\d+$` → `int(partner[2:])`; skip non-numeric IDs; clamp r² to [0,1]; force
lead r²=1.0. Region variants absent from 1000G → omitted → client renders grey (**NA ≠ 0**). If the
**lead itself** is absent, flag it so the UI warns rather than greying everything. Normalize chrom
(`23`→`X`). `ld_r2` wrapped in a sync LRU cache keyed by `(chrom, pop, lead)`.

### Testing (hermetic)
- Pure helpers (`_ld_table`, `r2_bin`, rsID parsing) unit-tested.
- `cis_associations` + `ld_r2` exercised via the existing **fake DB connection** pattern (assert SQL
  shape + row mapping; symmetric-pair dedupe; NA skip).
- `/api/gene/{key}/regional` and `/gene/{key}/plot` route-tested with an injected `FakeQtlRepository`.
- Ad-hoc (not in CI): verify the real query against the live DB (TP53 in a tissue → ~5000 variants
  with r² to lead).

### Verification (Phase A done)
Run the app; `/gene/TP53` → pick a tissue → a LocusZoom-looking scatter renders, points colored by r²
to the top hit; changing tissue/population updates it; clicking a point re-colors to that lead.

---

## Phase B — Body map (next PR, summarized)
`GET /gene/{key}/bodymap?qtl_type=eqtl` → HTML partial: server-**inlines** the EBI anatomogram SVG
(read once, cached) and injects `<style>` filling the UBERON ids of tissues where the gene has a
significant eQTL, graded by min −log₁₀(p). Uses `tissues_with_signal` + a **vendored static
`gtex_tissue → UBERON` mapping** (seeded from GTEx API; hand-audited: 13 brain subregions collapse to
the brain region; cell lines → off-body chip list). Click a tissue → HTMX-loads that tissue's regional
plot (reuses Phase A's endpoint). Visible **CC-BY** credit to EBI Expression Atlas.

## Deferred (Phase C+)
LocusZoom.js fidelity (gene track + recombination line); sQTL toggle once sQTL data lands; brain
drill-down SVG; multi-tissue forest/overlay; covering DB **indexes** on the LD tables for speed —
**DDL on the shared DB → routed through schema-change-coordination with Junbin** (until then,
big-chromosome LD queries may be slow; acceptable for the MVP).

## Open items for the team
- **LD index** (perf) — owner Junbin, via schema-change-coordination (ADR-0008).
- **β in tooltips** — shown with a "direction not interpretable" caveat (per #18) vs omitted → default:
  show value, caveat in tooltip/legend.
- **Anatomogram tissue mapping** coverage audit + CC-BY attribution wording (Phase B).
