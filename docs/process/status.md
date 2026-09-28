# Project status — locusview

> A **living** "where we are right now" doc — update it whenever phase / PRs / blockers change.
> For durable *decisions* see [`../adr/`](../adr/); for *how we work* see the other
> [`process/`](.) docs; for the roadmap see [`../product/roadmap.md`](../product/roadmap.md).
>
> _Last updated: 2026-08 (see `git log` for precise dates)._

## Phase
**Phase 1 — thin vertical MVP**, now extended with a full Data Browser app shell (see "Scope note"
below). Phase 0 (foundation, process, docs, CI, guardrails) is complete.

## Scope note (2026-08)
`docs/design/gene-page-visualizations.md` (accepted 2026-07-07) had deliberately deferred the
tabbed app shell (Home / Data Browser / News), the Cross-Dataset comparison view, and the
citations panel to follow-up issues — issue #27's scope was gene-page Locus View only. That scope
was then **deliberately expanded**, at explicit user request and aware of the deferral, to build
the full mockup (`docs/design/mockups/LocusView_Standalone_v1.html`) in one pass. See the note at
the top of that design doc for the reconciliation. Two departures from the mockup, both to keep
the app honest to what the DB actually has: (1) the Home dataset table and stats are driven by
`repo.datasets()` — real GTEx v8 counts, not the mockup's placeholder GTEx v10 / Tenk10k figures;
(2) "Cross-Dataset" mode compares across **tissues** (the only axis of comparison that exists
today), not a second data source.

## Database switch note (2026-08) — **updates ADR-0008's premise**
The team stood up a **new Postgres locuscompare2 DB** (`qtl_datasets` -> `qtl_lists` ->
`qtl_snp_{id}` shards; see `src/backend/locusview/connectpostgres.py`'s module docstring), superseding the
MySQL `colotool` DB that ADR-0008 named. At explicit user request, `_default_repository()` now
points at the new Postgres DB (`PostgresQtlRepository`) by default; the old
`LocuscompareRepository` (MySQL) is **commented out, not deleted**, in `requestinfo.py`/
`config.py`/`.env(.example)`/tests — search each file for "Legacy" to find it.
**This isn't a like-for-like swap** — flag these to the team before relying on them:
- The new DB has **richer QTL data**: real `ref`/`alt`/`maf` (resolves **issue #18**'s β-direction
  gap for datasets that use it), a proper `(chrom, position)` index (no more `MAX_EXECUTION_TIME`
  workaround needed for region-mode — see the blocker below, now legacy-only), and more datasets
  in the catalog already (`GTEx_v10` eQTL+sQTL, `CIMA` caQTL) — confirms the mockup's "GTEx v10" /
  multi-dataset framing was aimed at real, in-progress infrastructure, not just placeholder copy.
- The new DB **does** have a real gene-annotation table — `gencode_v39` (`gene_id_key`/
  `gene_name`/`gene_id`/`chr`/`start`/`end`/`strand`, found later this session, not part of the
  original schema pass) — so `resolve_gene()` was rewritten against it and gene-**symbol** search
  (e.g. "TP53") works again, with real coordinates/strand. It still has **no LD-reference table**,
  though: the regional plot still doesn't LD-color points (every point renders in the "no rsID"
  grey — `ld_r2()` always returns `{}`). Follow-up: either land an LD table in the new DB, or have
  `PostgresQtlRepository` blend in the old `LocuscompareRepository` for just that lookup (both DBs
  would need to stay reachable).
- **Live connectivity: connect DIRECTLY to the server, no SSH tunnel (corrected 2026-08).** The
  earlier note here said a tunnel was required because ":5432 times out" — true, but it was
  looking at the wrong port. The server's `docker-compose.yml` publishes Postgres as
  **`15432:5432`**, i.e. host port 15432 -> container port 5432, and *15432 is* reachable from the
  internet. So `LOCUSCOMPARE2_PG_HOST=<db-host>` + `LOCUSCOMPARE2_PG_PORT=15432` works with no
  tunnel at all — confirmed live: 0.12s connect+query direct, vs ~1s through the tunnel, and a
  heavy `/api/locus/multi-track` call went 5-6s -> 2.3s. The container's own 5432 is still
  unpublished (as is right), which is all the original "not exposed" finding actually established.
  The tunnel still works if you prefer it; it's just unnecessary. All `connectpostgres.py` query
  logic has been verified against real data over the direct connection.
- **caQTL phenotype tables rebuilt (2026-08-18).** The six caQTL shards' companions
  (`qtl_snp_3..8_phenotype` — CIMA 3-7, Tenk10k 8) now carry the peak coordinates as real columns,
  `(id, phenotype_id, gene_id, chrom, start, end)` with `chrom` in `"chr1"` form, plus an
  `ix_qtl_snp_{id}_phenotype_locus` index on `(chrom, start, "end")`. `PostgresQtlRepository`
  matches peaks through `_peak_phenotypes()` — **chromosome first, then the peak range** — instead
  of parsing `phenotype_id` with `split_part`, which no index could serve. Measured server-side on
  the live DB (`EXPLAIN (ANALYZE, BUFFERS)`, gene start inside a chr1 peak): shard 3 16.6 ms /
  2004 buffers -> 0.056 ms / 4 buffers; shard 8 34.5 ms / 7642 buffers -> 0.046 ms / 3 buffers.
  Identical rows for all 10 checked gene x dataset pairs. **eQTL/sQTL/pQTL and any other type keep
  the original three columns and must never take that branch** — they resolve phenotypes purely
  through `gencode_v39` -> the phenotype table's `gene_id`. So the branch is now keyed on the
  catalog's `qtl_datasets.qtl_type` (`_is_peak_dataset()`), replacing the old
  `_phenotype_uses_gene_id()` probe: inferring "peak-shaped" from an all-NULL `gene_id` column
  would send a non-caQTL dataset ingested without gene ids down the peak path, querying columns its
  table doesn't have. Verified live: `qtl_type = 'caQTL'` is exactly shards 3-8, which is exactly
  the set of `_phenotype` tables carrying `chrom`.
- **Region mode was listing phenotypes from outside the window (fixed 2026-08-18).** Reported on
  `chr17:6661179-8661779`. `phenotype_summaries_in_region()` picked phenotypes by *variant*
  position — `SELECT DISTINCT phenotype_key FROM qtl_snp_{id} WHERE position BETWEEN ...` — but a
  cis window reaches ~1 Mb past the feature, so peaks/genes well outside the typed region matched
  because their tested variants reached into it. Confirmed live: peak `chr17_5665386_5665629` (a
  megabase to the left) matched on variants spanning 4,666,082-6,665,497. Compounded by
  `ORDER BY phenotype_id` — a *string* sort, so those out-of-window peaks sorted first and filled
  the whole `LIMIT 50`: the Tenk10k panel showed 50 phenotypes of which **0** overlapped, hiding
  all 596 that did. Now each phenotype is placed by its **own** coordinates: caQTL peaks straight
  off the `(chrom, start, "end")` index, everything else via `gencode_v39`'s overlapping genes ->
  `gene_id`. The shard's variant positions aren't consulted for this list at all. Server-side cost
  went 2224 ms / 924k buffers -> 0.244 ms / 11 buffers. Ordering is now by position, so the QTL
  results table says "showing the first 50 in this window", not "top 50 by significance" (these
  summaries carry no p-value — values load when a row is checked).
- Password for the new DB lives in local `.env` (gitignored) — not yet in a secret store; do that
  before any real deployment (mirror how `LOCUSCOMPARE2_DB_PASSWORD` was handled for MySQL).

## Shipped (on `main`, plus this branch's Data Browser work)
- **Foundation:** repo, Diátaxis docs, ADRs 0001–0008, CI (lint / types / tests + genomics smoke +
  docker build), branch protection, `CODEOWNERS`, the teaching layer (`docs/course/`, explainers).
- **App shell:** FastAPI + Jinja2/HTMX, `/health`, config-in-env, `locusview serve`, a shared
  `layout.html` header/nav across three pages (Home / Data Browser / News), one router + template
  (+ static JS where interactive) per feature under `src/backend/locusview/routers/`.
- **Data layer:** the `QtlRepository` interface (`FakeQtlRepository` + real `PostgresQtlRepository`
  over the new shared locuscompare2 Postgres DB — see "Database switch note" below) and the search
  query parser (all 5 query kinds now routed).
- **Gene page + regional plot:** search a gene → its eQTLs across tissues, plus a LocusZoom-style,
  LD-colored regional plot (Plotly) with click-to-recolor and a population selector, on real GTEx v8
  data. CSV/TSV download.
- **Data Browser, cascading QTL/GWAS picker (2026-08):** the sidebar's dataset picker is a
  cascading builder, not a flat list (doesn't scale visually as more datasets get ingested) —
  under "QTL", one row of three live-connected boxes (**Dataset -> QTL type -> Context**, Context
  multi-select, the other two single-select), a "+ Add QTL" button appends another independent
  row; "GWAS" gets the same idea with two boxes (**Dataset -> Accession+Trait**, multi-select).
  Every box's options come from five small JSON endpoints under `/api/browser/...`
  (`routers/browser.py`) that group `repo.datasets()`/`repo.gwas_datasets()` fresh on every
  request — genuinely live, no caching, no new SQL. Drives the same **stacked multi-track plot**
  (`GET /api/locus/multi-track`) as before — one panel per selected dataset, sharing one
  genomic-position x-axis. **Cross-Dataset mode was removed** — Run Query always renders the
  multi-track plot; click-to-pin on a panel point is the only entry point into the
  variant-comparison table (`routers/comparison.py`), simplified to a plain
  `chrom`+`position`+`datasets` lookup. Still position-based, not rsID-based, for
  `associations_in_region`/`gwas_associations_in_region` (the new-DB shards don't carry a usable
  per-row rsID there — see `connectpostgres.py`'s docstring) — but see the gene-mode item below,
  where rsID *is* now populated.
- **Gene resolution via `gencode_v39` + caQTL support (2026-08):** `resolve_gene()` now queries
  the DB's real gene-annotation table (`gencode_v39`) instead of probing per-dataset phenotype
  tables — resolves a **gene symbol** (e.g. `TP53`) or a versioned/bare Ensembl id in one query,
  with real `chrom`/`start`/`end`/**strand** (this also lifts the old "gene-symbol search is
  down" limitation, see below). `cis_associations()` (the gene-anchored association fetch behind
  both the regional plot and the multi-track endpoint) now branches on whether a dataset's
  phenotype table's `gene_id` is populated: eQTL/sQTL-style datasets match on it directly;
  **caQTL-style datasets** (`gene_id` is `NULL` on every row, e.g. `CIMA`) instead match wherever
  the gene's start (from `gencode_v39`) falls inside the peak's `chr_start_end`-shaped
  `phenotype_id`. Either way, results are now also enriched with `rs_id`/`ref`/`alt` per variant
  (via a bounded `variant_rsid_mapping_raw` join, confirmed fast at this gene-anchored scale — a
  naive inline join blew up the query planner into a full scan of the 9M-row table, fixed by
  resolving `phenotype_key`s first). The Data Browser's multi-track gene-mode window is now
  **gene start +/-1 MB** (was the gene's own span); the Gene page's single-track regional plot is
  unchanged.
- **Home page, live from the DB (2026-08):** dataset table now shows GWAS traits alongside QTL
  datasets (previously QTL-only), with a **Population** column on the QTL table (replacing the
  raw Source id) and an **Accession ID** column on the GWAS table (`GwasDataset.accession`, e.g.
  `GCST90002379`); the "QTL & GWAS Browser" hero badge above the page title was dropped. An
  interactive **tissue body map** uses the **real EBI Expression Atlas anatomogram** SVGs
  (`ebi-gene-expression-group/anatomogram`, CC0, both male + female rendered side by side since
  GTEx tissues span both sexes' anatomy; the EBI licence-badge icon baked into both source files
  is stripped at load time — meaningless in this app). Since an anatomical shape alone wasn't an
  obvious click target, this became a **GTEx-style leader-line diagram** (2026-08): `static/js/
  body-map.js` tags each organ's hit-region client-side (from its `<title>` text), builds one
  clickable text label per region that actually has DB data (only those — not all ~70 organs),
  splits them into left/right columns by the organ's on-screen position, and draws a connector
  line from each label to its organ (recomputed on resize). Clicking a label (the organ shape
  still works too) renders that region's datasets as a real `<table>` on the side, replacing the
  old floating card-list panel.
- **Data Browser QTL results: phenotype-checkbox-driven plotting (2026-08):** every
  `EqtlAssociation` from `cis_associations`/`associations_in_region` now carries `phenotype_id`
  (a genomic window can legitimately match several different phenotypes at once — e.g. a region
  can span multiple genes' cis-windows, confirmed live: 113 distinct phenotypes in one 1 Mb
  window). `routers/locus.py::_group_by_phenotype()` groups a QTL track's variants back into one
  row per phenotype (with its lead variant), capped at 50 rows by significance; every returned
  variant also carries its own `phenotype_id`. `/api/locus/multi-track` attaches the grouped rows
  as each QTL track's `"phenotypes"` field plus `"dataset"`/`"qtl_type"`/`"population"`/
  `"context"` metadata — works identically across all three locus modes (gene mode unchanged;
  region mode surfaces every overlapping phenotype; variant mode too, once resolved). **QTL
  results no longer auto-plot** — GWAS panels still render immediately on Run Query, but QTL only
  shows as a checkbox table (Dataset / QTL type / Population / Context / Phenotype ID / Lead
  position / Lead −log₁₀(p)); checking a row filters that track's already-fetched variants down to
  just that `phenotype_id` client-side (no second fetch) and plots its own locuszoom panel below
  the table, with its own lead recomputed within that phenotype's subset. Selections are freely
  reversible — panels update live as rows are checked/unchecked. New
  `QtlRepository.resolve_variant(rs_id)` — a standalone "does this rsID exist" check, decoupled
  from any selected QTL dataset (unlike the old `associations_for_rsid`-based lookup) — backs
  variant-mode's rsID resolution, so a bare rsID resolves (or cleanly 404s as "not found")
  regardless of which datasets happen to be checked. GWAS is unaffected (no phenotype concept
  there; "click-to-compare unavailable for GWAS" just means GWAS points aren't a click-to-pin
  entry point — the comparison table itself works fine with GWAS data once a position is known).
- **Smaller Data Browser / Home page fixes (2026-08):** the sidebar was too narrow for the
  cascading picker's three-select QTL rows — widened (340px -> 460px) with larger selects. The
  Context dropdown now shows *only* the level-2 label when one exists (e.g. `cMono_CD14`, not
  `Whole_Blood / cMono_CD14` — level 1 alone rarely distinguishes rows within one dataset+type
  and the column was too narrow for the combined form anyway). The Home page body map's
  click-result table now shows `{dataset}-{qtltype}` (no population) as plain text, with the link
  moved from the Dataset column onto the Context column instead.
- **LD coloring for the Data Browser's locuszoom panels + a real body-map bug (2026-08):** the
  1000G phase 3 LD panel (`tkg_p3v5a_ld_chr{chrom}_{population}`, PLINK `--r2` shape) landed in
  the new Postgres DB — `PostgresQtlRepository.ld_r2()` is a real implementation now (was a `{}`
  stub), reusing the exact `SNP_A`/`SNP_B` union-both-directions query the old MySQL
  implementation used (just double-quoted — the table/column names are mixed-case). The
  already-existing `/api/ld` endpoint (built for the Gene page's single-track click-to-recolor)
  needed no changes — the Data Browser's `renderQtlPanels` now calls it for each checked
  phenotype's own (re-scoped) lead, mirroring `regional-plot.js`'s `r2color` scheme exactly, and
  shows a legend once any panel actually gets LD colors. Only gene-mode panels have a per-point
  rsID to color with (`cis_associations`, unchanged scope from before) — region/variant-mode
  panels fall back to the plain fixed color, same as before this landed.
  Separately, a **real body-map bug** was found and fixed: `body-map.js` was reading each SVG
  organ's `<title>` **text content** to match against `content/body_map.py`'s `REGION_KEYWORDS`
  targets, but the source SVGs use *spaces* in multi-word organs' title text (`"adipose tissue"`)
  while their `id` attribute (and every `REGION_KEYWORDS` target) uses underscores
  (`"adipose_tissue"`) — silently dropping every multi-word organ (36 of 73 per file) from the
  diagram. Fixed by normalizing the text (lowercase, spaces -> underscores) instead of trusting
  either raw form; also fixed a keyword-ordering bug (`"Kidney_Cortex"` was matching the generic
  `"cortex"` -> brain keyword before reaching `"kidney_cortex"` -> `renal_cortex`) and aliased the
  one real male/female naming split (`urinary_bladder` / `bladder`). Verified against all 68 real
  GTEx v10 tissue names from the DB's `gtex_tissues` table (the user's suggested canonical list) —
  every one now resolves to a region that actually exists as a drawn organ in at least one figure.
- **Data Browser results layout -> two columns + LD population selector (2026-08):** the results
  area is now a two-column row, not a vertical stack — locuszoom plots (GWAS immediately, then
  the LD legend, then whichever QTL phenotype panels are checked) in the middle
  (`.db-results-plots`), the "QTL results by phenotype" checkbox table in a fixed-width column on
  the right (`.db-results-side`, 420px). A new **LD population** `<select>` (EUR/AFR/AMR/EAS/SAS,
  default EUR) landed in the sidebar, matching the Gene page's existing single-track population
  control — `renderQtlPanels` now takes population as a parameter instead of a hardcoded `"EUR"`;
  changing the selector after phenotype rows are already checked re-fetches and re-colors their
  panels in place (reuses the same checkbox-`change` machinery `renderQtlTable` already wires, by
  re-dispatching it, rather than duplicating the selection-collection logic).
  Also fixed a real (if narrow) race: `BrowserPicker`'s default-row population is async
  (`fetchJSON` calls against the `/api/browser/...` catalog endpoints), so a Run Query click
  landing before it resolves could read an empty `selectedDatasets()` — confirmed live via a
  rapid/no-wait click. `BrowserPicker` now exposes a `ready` Promise, resolved once its initial
  population finishes; `runLocusView()` awaits it first.
  Separately, the **Home page body-map click-result table** looked stretched/cramped once
  multi-row contexts (e.g. Blood's 8 rows) were showing: `<td>` text was wrapping onto two lines
  (no `white-space: nowrap`), and `.body-map-side` was sized as a `flex: 2` share of the row
  (~40% of an up-to-1100px section, i.e. quite wide for a 2-column table) rather than a sensible
  fixed width. Fixed both — rows are single-line now, `.body-map-side` is a fixed 340px, and the
  table's already-existing `.table-wrap { overflow-x: auto }` handles any row whose Context value
  is still too long to fit (confirmed it actually scrolls, doesn't clip). **Superseded the same
  day** — the scroll wasn't wanted; see the next entry.
- **GWAS LD coloring + locuszoom axis/layout polish (2026-08):** `GwasAssociation` now carries
  `ref`/`alt`/`rs_id`, populated unconditionally by `gwas_associations_in_region()`'s new
  `variant_rsid_mapping_raw` join (mirroring `cis_associations`'s enrichment shape) — confirmed
  live: ~2s for a full 2 Mb window (~28k rows, the multi-track plot's actual gene/variant-mode
  window size), still linear (not catastrophic) at 10 Mb (~147k rows: ~7s); a user-typed
  region-mode window has no upper bound today, same pre-existing condition as the unenriched QTL
  path. `multi-track-plot.js`'s GWAS `render()` is now async: it looks up each track's own lead
  (via the `is_lead` flag `_track_variants` already sets) and, if that lead has an `rs_id`, fetches
  `/api/ld` and colors every point the same way QTL panels already did — same legend, now shared
  correctly between GWAS and QTL (`gwasUsedLd`/`qtlUsedLd` module state, since the two render
  independently on different triggers). While verifying this, found and fixed a **real, unrelated
  pre-existing bug**: `_lead_of`/`_min_p` picked the raw min-p row as "lead" even when its p-value
  was exactly `0.0` (a source-data underflow) — but `neg_log10_p`/`_track_variants` then drop that
  row from the rendered set entirely (can't take `log10(0)`), so *no* variant ended up marked
  `is_lead`, silently breaking both the diamond-lead marker and (now) LD lookups for any window
  whose true minimum happens to be `0.0`. Both functions now require `pvalue > 0` to win, matching
  `neg_log10_p`'s own accepted-input rule. Also: locuszoom x-axes (`multi-track-plot.js` and the
  shared `regional-plot.js`) now show a real title, `"chr{chrom} (Mb)"`, with tick position values
  converted to Mb (hover/click still use the raw bp position via `customdata`, unaffected). The
  Data Browser's results columns were rebalanced — `.db-results-side` (the QTL/GWAS-adjacent
  "results by phenotype" table) widened from 420px to 540px, narrowing the middle plots column to
  match.
- **Home page body-map table, corrected (2026-08):** the previous fix's `white-space: nowrap` +
  fixed 340px + horizontal scroll wasn't what was wanted — scrolling itself was the problem, not
  wrapping. Kept `nowrap` (still needed to avoid 2-line rows) but widened `.body-map-side` to
  460px, wide enough that the longest real Context value today (`Whole_Blood /
  Atypical_Bm_ITGAX`, ~394px) fits with room to spare and `.table-wrap`'s scroll never engages.
  Also tightened row padding specifically for this table (`#body-map-panel-table td`, not the
  other two `dataset-table`s on the page, which keep their roomier default) from `14px 18px` to
  `7px 18px` — confirmed row height dropped 49px -> 35px with the fix live.
- **GWAS LD-coloring follow-up fixes (2026-08):** three issues found after the above landed. (1)
  Filter rule settled after two iterations: **only points with no rsID at all are dropped** from
  the plot (once LD was actually fetched for that panel — no lead rsID at all still falls back to
  showing everything in the plain fixed color, unchanged). Every point that *does* have an rsID
  shows, even when the pairwise table has no row for it with this particular lead — that renders
  in the "< 0.2 / not in panel" bin (`r2Color`'s null-r2 branch), not hidden. First tried
  dropping that whole "no row" case too (both GWAS's `render()` and QTL's `renderQtlPanels()`),
  then tried to make it *precise* — split "not in panel" from "in panel but r² < 0.2" by checking
  rsID existence against the pairwise table directly (the panel only stores pairs >= 0.2, so a
  plain miss otherwise conflates the two) — live-tested and found that existence check doesn't
  scale: ~6.4s for 424 candidate rsIDs, ~10s (after switching a naive `UNION`+`DISTINCT` to an
  `EXISTS`-based query) for 1220, and the naive version times out outright past that — a realistic
  gene/region window has 1,000-7,000 candidates, and there's no separate "which SNPs are in this
  population's 1000G panel" table to check against instead (`tkg_p3v5a_hg19` only has 1000 rows,
  unrelated). **Settled (user, 2026-08): show everything with an rsID (< 0.2 included), hide only
  no-rsID points** — the pragmatic version of the same rule, no extra query needed.
  `LD_NO_RSID_COLOR`/`r2Color`'s `hasRsid` param were removed from `multi-track-plot.js` as dead
  code once no-rsID points stopped reaching the color function; the "no rsID" legend swatch was
  dropped too (folded into the legend's caption text instead, since it's no longer a plotted
  color). (2) The LD legend now
  sits above **both** GWAS and QTL sections in the middle column (was positioned between them,
  reading as QTL-only) — moved in `partials/_multi_track_plot.html`, `gwasUsedLd`/`qtlUsedLd` in
  `multi-track-plot.js` already tracked visibility per-source so no JS logic changed. (3) A real
  bug: checking several QTL phenotype rows after GWAS had already rendered could make the GWAS
  panel go blank. Root cause — every `scattergl` panel holds its own WebGL context, and browsers
  cap how many a page can have open (~16 typical); `render()`/`renderQtlPanels()` replace their
  container's panels wholesale on every trigger (e.g. each checkbox toggle) via `innerHTML = ""`,
  which removes the DOM nodes but doesn't release their WebGL contexts — contexts leaked until the
  cap was hit, and the browser silently blanked the oldest (often GWAS, rendered first). Fixed with
  a `purgePanels()` helper that calls `Plotly.purge()` on every `.track-panel-plot` before its
  container is wiped, in both functions. **Later found the WebGL fix insufficient** and the LD
  scope was too narrow — see the next entry.
- **LD parity for region/variant-mode QTL panels + a real WebGL leak fix (2026-08):** two more
  bugs reported after the above. (1) Region/variant-mode QTL panels never got LD colors at all
  (only gene-mode ones did, plus GWAS after its own fix) — root cause: `associations_in_region`
  (backing region/variant mode) has never been rs_id-enriched, unlike `cis_associations`
  (gene mode) — confirmed why it can't be: a 1 Mb region here is 300k+ rows *before* any join
  (vs. GWAS's ~28k for a comparable window — QTL data has one row per position **x** phenotype,
  much denser), so wholesale enrichment isn't viable the way it was for GWAS. Fix: new
  `PostgresQtlRepository.associations_for_phenotype(dataset_id, phenotype_id)` — phenotype-bounded
  (not window-bounded), so it affords the same enrichment `cis_associations` does (confirmed live:
  ~9k rows, ~2.4s) — and a new `GET /api/locus/qtl-phenotype` endpoint. `renderQtlPanels()` in
  `multi-track-plot.js` now checks whether its client-filtered variants carry any rs_id at all; if
  not (region/variant mode), it fetches this new endpoint instead of coloring nothing. Gene mode's
  existing fast path (client-side filter of already-fetched, already-enriched variants, zero extra
  round trips) is untouched. Since region/variant-mode panels now always re-fetch enriched data
  per phenotype anyway, `_qtl_track`'s bulky per-variant `"variants"` field is no longer sent for
  those modes (only the already-small, capped-at-50 `"phenotypes"` summary is) — this incidentally
  fixed a real payload problem found while testing: that field was 54 MB for a 1 Mb region on a
  dense eQTL dataset. (2) The WebGL-context fix from the previous entry turned out insufficient —
  still reproduced (GWAS panel's axes stay but its points vanish after checking several QTL
  phenotypes). `Plotly.purge()` alone doesn't reliably release a `scattergl` panel's WebGL context
  (a known Plotly.js/regl limitation) — `purgePanels()` now also explicitly forces each canvas's
  context to release via the standard `WEBGL_lose_context` extension after purging, rather than
  relying on the browser's own GC timing. Verified live: GWAS + 4 QTL phenotype panels all stay
  intact and LD-colored together (see `docs/process/status.md`'s neighboring entries for the
  underlying LD/legend/hide-rule history).
- **Repo layout split into `src/backend/` and `src/frontend/` (2026-08, user request):** all
  backend Python (the `locusview` package — `routers/`, the data-access layer, `web.py`,
  `config.py`, `content/`, `genomics.py`, `search.py`, `templating.py`, `viz.py`, `cli.py`) now
  lives under `src/backend/locusview/`; HTML templates and `static/` moved to the sibling
  `src/frontend/`, outside the Python package. Only 3 files needed path-computation changes since
  the HTML/static assets were always found via plain filesystem paths, not Python package
  resources: `web.py`'s `_STATIC_DIR`, `templating.py`'s `_TEMPLATES_DIR`, and
  `content/body_map.py`'s SVG loader, all now walk up to the sibling `frontend/` folder (see their
  comments). No import paths changed anywhere else — the package is still named/imported as
  `locusview` throughout, just physically nested one level deeper. `pyproject.toml`'s
  `packages = [...]` updated to match; deliberately did **not** add wheel `force-include` packaging
  for `frontend/` — this app is never deployed as a standalone wheel today (`uv run` always
  executes from a full source checkout, locally or in the Docker image, which `COPY`s the whole
  repo before `uv sync`), so the relative-walk-up path resolution is sufficient without that
  complexity. Verified: `uv sync` rebuilds cleanly from the new location, all 209 tests + ruff +
  mypy pass, and a live server smoke-test (Home page, CSS, JS, and the body-map SVGs specifically,
  since that path computation was the trickiest) all resolve correctly.
- **File renames by function (2026-08, user request):** `repository.py` -> `requestinfo.py`
  (the `QtlRepository` interface + `FakeQtlRepository`), `pg_repository.py` ->
  `connectpostgres.py` (`PostgresQtlRepository`, the real DB implementation), and
  `src/frontend/templates/` -> `src/frontend/displays/`. Same mechanical shape as the
  backend/frontend split above — every `from locusview.repository import ...` /
  `from locusview.pg_repository import ...` became `from locusview.requestinfo import ...` /
  `from locusview.connectpostgres import ...` (class/function names inside are unchanged, only
  the module path), and `templating.py`'s `_TEMPLATES_DIR` now points at `frontend/displays`.
  Test files renamed to match (`test_repository.py` -> `test_requestinfo.py`,
  `test_pg_repository.py` -> `test_connectpostgres.py`) for consistency with the project's
  one-test-file-per-module convention, though this wasn't explicitly requested. While making
  this change, also fixed a real bug found along the way: `_VARIANT_WINDOW` (the legacy
  single-track `/api/locus/regional` endpoint's variant-mode window) had accidentally been left
  at `1_000_000` after a botched edit, contradicting its own comment ("+/-500 kb") — then, per an
  explicit follow-up correction, set back to `1_000_000` deliberately (not reverted-to-500kb) and
  unified with the Data Browser's multi-track variant window, which was already `1_000_000` — the
  two were functionally identical the whole time this session, so the separate
  `_MULTI_TRACK_VARIANT_WINDOW` constant was removed as redundant; both locus tabs' variant modes
  now share one `_VARIANT_WINDOW = 1_000_000` constant.
- **LD-pivot fallback for GWAS/QTL panels (2026-08):** found live — a GWAS panel (TP53 x "Mean
  corpuscular hemoglobin") showed *zero* LD colors (every point in the flat "< 0.2 / not in
  panel" bin) despite 6,838 of its 29,538 variants having a resolvable rsID. Root cause: LD was
  only ever fetched relative to the track's single most significant point (`is_lead`), and that
  *specific* point's rsID happened to be unresolved — common, since only a fraction of positions
  map to one — so `lead.rs_id` was falsy and the whole panel silently skipped `/api/ld` entirely,
  even though plenty of other nearby points had usable rsIDs. Fixed in `multi-track-plot.js`: both
  `render()` (GWAS) and `renderQtlPanels()` (QTL) now pick their LD "pivot" as the best (lowest-p)
  variant *among those with an rsID* (new `bestByPvalue(variants, requireRsid)` helper), not
  simply the overall best p-value point — falls back to the true statistical lead only when LD
  isn't available at all (no rsID-bearing variant anywhere in the set). Verified live: the same
  TP53/"Mean corpuscular hemoglobin" panel now shows a real LD gradient (lead + 4 color bins)
  clustered at the correlated peak, and QTL panels are unaffected (same pivot logic, confirmed
  still colors correctly).

## Next up
- Backlog: provenance banner (#8); unify the legacy `/gene/{name}` page to fully share the Data
  Browser's sidebar/partials (currently only the regional-plot partial is shared).

## Open items / blockers
- **Region-mode `/api/locus/multi-track` is slow-ish (~5.7s) for dense QTL datasets on a 1 Mb
  window.** Was ~14s over the SSH tunnel; dropped to ~5.7s once the app connected directly (see
  the connectivity note above), so the tunnel was a large part of it — but the underlying
  inefficiency is real and remains: the server fetches and iterates all 300k+ raw rows from
  `associations_in_region` just to build `_group_by_phenotype`'s summary and find the track's
  `lead`, even though only ~50 grouped rows reach the response. Likely fix: compute the
  per-phenotype lead/count as a SQL `GROUP BY` aggregate (DB-side) instead of in Python.
- ~~**Gene page (`/gene/{name}`) times out for every gene** — `eqtls_for_gene`'s dataset id 8
  (Tenk10k-caQTL) hangs (~8.5s, then the connection dies).~~ **Resolved 2026-08, and the original
  diagnosis was wrong.** It was never a bad query: id 8 was simply the slowest of 13 sequential
  per-dataset round trips over the SSH tunnel, and the total tipped past pg8000's 8s socket
  timeout. Connecting directly (no tunnel) fixed it with no query change — re-verified live:
  `/gene/TP53` returns 200 in ~5.0s with 401 real rows, and dataset 8 alone now answers in 0.48s.
  Lesson worth keeping: a per-item timeout that only reproduces through a tunnel is evidence about
  the *transport*, not the SQL.
- **Click-to-pin (variant comparison) only works from QTL panels, not GWAS ones** —
  `multi-track-plot.js` only wires the click handler onto `track.kind === "qtl"` points (GWAS
  panels render a "click-to-compare unavailable for GWAS" note instead). Once a `(chrom,
  position)` is picked, though, the comparison table itself compares across both QTL and GWAS
  datasets fine — the gap is purely "how do you pick a position from a GWAS-only view." Not
  fixed — see `routers/comparison.py`'s docstring.
- **#18** (β direction not interpretable) — **resolved for datasets using the new Postgres DB**,
  which stores `ref`/`alt`/`maf` per association; still applies to the legacy MySQL path if that
  ever comes back into use.
- Legacy, MySQL-only (moot while `LocuscompareRepository` stays commented out, but relevant again
  if it's revived): **LD covering index** on `tkg_p3v5a_ld_*` and **`eqtl_snp_*` shards indexed by
  `gene_id` only** (region/rsID queries needed a `MAX_EXECUTION_TIME` hint to avoid hanging) — both
  DDL-on-shared-DB, owner **Junbin**, routed via
  [`schema-change-coordination.md`](schema-change-coordination.md).
- **Board** (Project #5) is stale — needs a sync (closed issues → Done; add #18 + open PRs).

## Team & roles
- Lead: **@boxiangliu** (Boxiang Liu).
- Engineers: **@gaojunbin** (Junbin Gao — owns the locuscompare2 DB), **@GhostAnderson** (Laurentius),
  **@MickYang2333** (YANG Chen), **@wenjing-gakkilove** (Wenjing).
- UI/UX: **@liufei-f** (Liu Fei — owns `docs/design/` + `src/frontend/templates/`).
- Plus a PM and scientists. All new to software engineering; heavy, guardrailed use of coding agents.
