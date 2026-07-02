# locuscompare2 database — schema reference

> **Reference** (Diátaxis) — facts to look up. This page documents the **existing locuscompare2
> database** that locusview reuses as its QTL datastore, per
> [ADR-0008](../adr/0008-store-qtl-in-locuscompare2-database.md) (backlog item **B1**).
>
> It answers issue #1 tasks 1–2: *what DBMS/version is it* and *what is the QTL schema*. The
> connection and least-privilege access model is a separate page —
> [how-to: connect to the locuscompare2 database](../how-to/connect-to-locuscompare2-database.md);
> the change process is [schema-change coordination](../process/schema-change-coordination.md).
>
> **Source of truth.** Everything here was reverse-engineered from the `locuscompare2_backend`
> codebase (the Flask/SQLAlchemy service that owns and writes this database), not from a live `SHOW
> CREATE TABLE` dump — we do not yet have credentials. File citations are given so each fact can be
> re-verified against the backend. Where a value could not be pinned exactly (e.g. the server patch
> version), that is called out. Confirm against the live instance before Phase-1 storage work relies
> on it.

---

## 1. DBMS and version

| Fact | Value | Evidence (in `locuscompare2_backend`) |
|---|---|---|
| Engine | **MySQL** (Community), storage engine **InnoDB** | `docker-compose.yaml` (`image: mysql:latest`); `gencode_v26_hg38` DDL shows `ENGINE=InnoDB` (`debug/mysql.py`) |
| Major version | **MySQL 8.0.x** (see caveat) | `command: --default-authentication-plugin=mysql_native_password` is an 8.0-era server option; client is `mysql-connector-python==8.3.0` (`requirements.txt`) |
| Version pinning | **Unpinned** — deployed from the floating `mysql:latest` tag | `docker-compose.yaml` |
| Driver (app) | **PyMySQL 1.0.2** via SQLAlchemy 2.0.4 / Flask-SQLAlchemy 3.0.3; URL scheme `mysql+pymysql://` | `requirements.txt`, `src/config/db_config.py` |
| Database (schema) name | **`colotool`** | `src/config/db_config.py`, `docker-compose.yaml` (`MYSQL_DATABASE`) |
| Connection charset | `utf8` (an alias for **utf8mb3**, 3-byte — *not* full utf8mb4) | `DB_URI = ...?charset=utf8` |
| Auth plugin | `mysql_native_password` | `docker-compose.yaml` |
| Dev/compose port | host `13306` → container `3306` | `docker-compose.yaml`, `debug/mysql.py` |

**Caveats worth a human decision (issue is labelled `needs-human`):**

- **The version is not pinned.** `mysql:latest` means the actual server version depends on when the
  container was last pulled; it is almost certainly 8.0.x but could drift. Two applications sharing one
  database should pin an explicit tag (e.g. `mysql:8.0`). Flagged in
  [schema-change coordination](../process/schema-change-coordination.md).
- **`utf8` = `utf8mb3`.** The app connects with the 3-byte alias. If any QTL text ever needs 4-byte
  characters this silently truncates; new tables should prefer `utf8mb4`. Note also that
  `gencode_v26_hg38` is declared `DEFAULT CHARSET=latin1` — charset is **not** consistent across
  tables.
- The backend historically also pointed at managed hosts (`*.mysql.aigene.org.cn`, commented out in
  `db_config.py`/`utils.py`). The **canonical instance locusview should read is a decision for the
  data owners** — see the how-to.

---

## 2. The one thing that will bite you: keys are integer-encoded

The high-volume tables do **not** store identifiers as strings. On ingest the backend strips the
prefix and stores a bare integer, so locusview must apply the same transform to query, and the inverse
to display. All transforms live in `src/utils/utils.py`.

| Identifier | Stored as | Encode (query) | Decode (display) | Notes |
|---|---|---|---|---|
| Gene (`ENSG…`) | `BIGINT` | `get_gene_id_num`: strip `ENSG` + leading zeros, **drop `.NN` version** → int (`ENSG00000204936.3` → `204936`) | `get_gene_id_string`: `ENSG` + zero-pad to 11 digits (`204936` → `ENSG00000204936`) | **Lossy:** version suffix is discarded. The unversioned ENSG is the join key. |
| Variant rsID (`rs…`) | `BIGINT` | `get_rs_id_num`: strip `rs` → int (`rs204936` → `204936`) | `get_rs_id_string`: `'rs' + n` | Only handles the `rs` prefix. Non-`rs` IDs (merged/`TMP_*`/indel names) do **not** round-trip and were historically mapped to `-1` or skipped. |
| Chromosome (`chr…`) | `SMALLINT` | `get_chrom_num`: strip `chr`/`CHR`/`Chr` → int | index into `positions[]` for genome-wide coords | **Autosomes 1–22 only.** `X`/`Y`/`MT` are not integer-parseable and are **dropped at ingest** (`src/services/eqtl.py`: `if type(row[chrom]) != int64: continue`). |

**Consequence for locusview:** a gene/variant lookup must encode inputs the same way, and the served
data has **no chrX/chrY/chrMT eQTL** and no non-rs variants. Both are real coverage gaps to surface in
the UI, not silently.

---

## 3. Genome build and gene annotation

- **Build is GRCh38/hg38.** Confirmed by the cumulative-offset table `positions[]` (GRCh38 chromosome
  lengths, `src/utils/utils.py`) and by the annotation table name `gencode_v26_hg38`. GTEx v8 is
  GRCh38-based; the eQTL-Catalogue `_ge` datasets are GRCh38. There is no build column — GRCh38 is an
  implicit, global invariant of this database.
- **Gene annotation is GENCODE v26** (`gencode_v26_hg38`; an older `gencode_v19_gtex_v6p_hg38` also
  exists). This is the lookup for gene **symbol** and **coordinates**, joined on the *versioned* ENSG
  (`WHERE gene_id LIKE 'ENSG…​.%'`, see `get_gene_name`).

---

## 4. Core QTL schema (what locusview reuses)

### The catalog / shard pattern

QTL data is stored in **two layers**, and this is the single most important structural fact:

1. **`eqtl_raw`** is a **dataset catalog** — one row per tissue/dataset. Its "value-looking" columns
   (`rsid`, `gene_id`, `chrom`, `position`, `alt`, `ref`, `beta`, `pvalue`, `maf`) do **not** hold
   data; they hold the **name of the corresponding column in that dataset's source file**, used by the
   loader to map source → canonical. (See `add_eqtl_raw`/`init_eqtl_raw_list` in `src/services/eqtl.py`,
   which literally assign `gene_id = "molecular_trait_id"`, `chrom = "chromosome"`, etc.)
2. **`eqtl_snp_{eqtl_raw_id}`** holds the actual per-variant associations, **one physical table per
   dataset** (dynamic/sharded; name = `eqtl_snp_` + the `eqtl_raw.id`). There is no single "all eQTL"
   table; you union/query per dataset.

> ⚠ **Do not read `eqtl_raw.gene_id` as a gene.** It is the string `"molecular_trait_id"`. The same
> catalog-with-column-name-mapping pattern applies to `gwas_raw` (§6).

### `eqtl_raw` — eQTL dataset catalog

| Column | Type | Meaning |
|---|---|---|
| `id` | BIGINT PK | Dataset id; also the shard suffix (`eqtl_snp_{id}`) and the `tissue_id` referenced by TPM (§5). |
| `tissue` | VARCHAR(255) | Dataset name = source filename stem (e.g. `Whole_Blood`, `BLUEPRINT_monocyte_ge`). Used as the human label. |
| `type` | VARCHAR(32), default `gtex-v8` | One of `gtex-v8`, `ge`, `eqtl_catalog`, `leaf-cutter` (constants `EQTL_TYPE_*`). |
| `rsid`,`gene_id`,`chrom`,`position`,`alt`,`ref`,`beta`,`pvalue`,`maf` | VARCHAR(128) | **Source-file column names**, *not* values (e.g. `gene_id="molecular_trait_id"`). Ingest-time mapping only. |
| `url` | VARCHAR(255) | S3/OSS key of the preprocessed dataset tarball (source of alleles/MAF not in the SNP table — see §7). |
| `file_path` | VARCHAR(255) | Path to the dataset on the lab's compute box. |
| `info` (attr `info_json`) | VARCHAR(4096) | JSON of tissue metadata for `eqtl_catalog`/`ge`/`leaf-cutter` datasets (empty for plain GTEx v8). |

Datasets are seeded from **hardcoded lists** in `src/utils/utils.py` (`EQTL_LIST` = GTEx v8's 49
tissues; `EQTL_CATALOG` = eQTL-Catalogue `_ge` datasets), not discovered dynamically.

### `eqtl_snp_{eqtl_raw_id}` — per-dataset eQTL associations (sharded)

One row = one (variant, gene) association within that dataset. Defined by the `EqtlSnp` abstract model
in `src/model/models.py`.

| Column | Type | Meaning |
|---|---|---|
| `id` | BIGINT PK AI | |
| `rs_id` | BIGINT | Variant, integer-encoded (§2). |
| `chrom` | SMALLINT (idx) | Autosome 1–22 (§2). |
| `position` | BIGINT | GRCh38 coordinate. |
| `gene_id` | BIGINT (idx) | Gene, integer-encoded (§2). For `leaf-cutter`, see `trait_id`. |
| `pvalue` | VARCHAR(32) | **Stored as text** — cast on read. |
| `beta` | VARCHAR(32) | Effect size, **text**. Sign is **uninterpretable without the effect allele**, which is not in this table (§7). |
| `se` | VARCHAR(32) | Standard error, **text**. |
| `trait_id` | BIGINT (idx), nullable | Only for `leaf-cutter`: FK → `trait_item.id` (the intron/molecular-trait). Null otherwise. |
| — index | `idx_eqtl_snp_join (chrom, rs_id)` | Plus single-column indexes on `chrom`, `gene_id`. |

**Absent here (important):** no `ref`/`alt`/`effect_allele`, no `maf`, no `variant_id`. See §7.

---

## 5. Gene expression (TPM) tables

### `gene_median_tpm`
| Column | Type | Meaning |
|---|---|---|
| `id` | BIGINT PK | |
| `gene_id` | BIGINT (idx) | Gene, integer-encoded (§2). |
| `description` | VARCHAR(30) | Gene symbol. |

Loaded from GTEx v8 `..._gene_median_tpm.gct` (`src/services/tpm.py`).

### `gene_median_tpm_tissue_relation`
| Column | Type | Meaning |
|---|---|---|
| `id` | BIGINT PK | |
| `tpm_id` | BIGINT | FK → `gene_median_tpm.id`. |
| `tissue_id` | BIGINT | **FK → `eqtl_raw.id`** (not a separate tissue table). |
| `value` | FLOAT | Median TPM for that gene in that tissue. |

> Note the join quirk: "tissue" here is an `eqtl_raw` row id, so TPM tissues only exist for tissues
> that also have an eQTL dataset.

---

## 6. Molecular-trait mapping and the GWAS/coloc co-tenants

locusview's read path is the eQTL/TPM tables above. The tables below live in the **same `colotool`
schema** — they matter for the *coupling* story (why change-coordination exists) and because a
read-only role will see them.

### `trait_item` — leafcutter intron ↔ gene
| Column | Type | Meaning |
|---|---|---|
| `id` | BIGINT PK | The integer referenced by `eqtl_snp_*.trait_id`. |
| `gene_id` | BIGINT (idx) | Gene, integer-encoded. |
| `trait_id` | VARCHAR(64) (idx), nullable | The **original trait string** (e.g. a leafcutter intron id). |

> ⚠ Naming inversion: `trait_item.trait_id` is a **string name**; `eqtl_snp_*.trait_id` is the
> **integer `trait_item.id`**. They are not the same field.

### `gwas_raw` — GWAS dataset catalog (same catalog+column-map pattern as `eqtl_raw`)
Confirmed in `src/services/gwas.py`, which reads source columns via `row[gwas_raw_item.rs_id]`, etc.
Real dataset metadata: `trait`, `type`, `sample_size`, `url`, `sha256` (indexed, dedup hash),
`extra`, `tool_config`, `test_genomic_window`. The columns `rs_id`, `chrom`, `position`, `beta`,
`effect_allele`, `other_allele`, `p_value`, `standard_error`, `effect_allele_frequency` are
**source-column-name mappings**, not values.

> 🐛 Data-quality note: the effect-allele-frequency column is declared with a **stray trailing
> double-quote** in the model — `Column('effect_allele_frequency"', …)` — so the physical column name
> is literally `effect_allele_frequency"`. Anyone querying it must quote it exactly. Worth fixing on
> the locuscompare2 side.

### `gwas_snp_{gwas_raw_id}` — per-GWAS SNPs (sharded)
`rs_id` BIGINT, `chrom` SMALLINT, `position` BIGINT, `p_value` FLOAT (idx), `beta` VARCHAR(128),
`se` VARCHAR(128), `manh_plot_used` TINYINT (idx, Manhattan-plot downsample flag); index
`idx_gwas_snp_join (chrom, rs_id)`. Same integer encoding; no allele columns.

### Colocalization result tables
- **`colocalization_record`** — one row per (GWAS × eQTL) coloc run: `task_id`, `gwas_raw_id`,
  `eqtl_raw_id`, `user_id`, p-value cutoffs, `tools`, `population`, timestamps, `duration`, `state`
  (`WAITING|RUNNING|FAILED|SUCCESS|STOPPED`), `progress`, `cromwell_id`, `extra_info`.
- **`colocalization_gene_result_{table_id}`** — per-gene coloc scores, **sharded**; `table_id =
  colocalization_record.id // 10` (`get_colot_result_table_id`). Columns: `job_record_id`, `gene_id`
  (BIGINT, encoded), `chrom`, and per-method scores as **VARCHAR(32)** (`coloc`, `ecaviar`, `enloc`,
  `mrank`, `rank_geo`, `fusion`, `predixcan`, `smr`, `intact`, `coloc_H3`, `p_HEIDI`); index
  `idx_colot_result_join (job_record_id, gene_id)`.
- **`gwas_genomic_loci`** — clustered GWAS loci per run: `job_record_id` (idx), `chrom`, `lead_snp`,
  `total_snp`, `start_pos`, `end_pos`, `rs_id`, `var_id`.
- **`PvalueThre`** — per-record significance thresholds/notes for each coloc method.

### Application / infrastructure tables (not QTL)
- **`user`** — ⚠ **contains PII**: `email`, `user_name`, `uuid` (session token), `encrypted_password`,
  `organisation`, `create_at`. The read-only serving role should **not** be able to read this
  (see the how-to).
- **`news`** — announcement strings + `is_sent` flag.
- **`table1`** (`id`, `job_id`) and **`logs_{year}`** (`id`, `content`, `user_id`, `score`) — legacy /
  placeholder; not used by any query locusview needs.

---

## 7. How locusview reads an eQTL association (recipe)

1. **Resolve dataset(s).** `SELECT id, tissue, type, info FROM eqtl_raw` and pick by `tissue`/`type`.
   The `id` is the shard suffix.
2. **Encode the query keys** (§2): gene `ENSG…` → int; variant `rs…` → int; chrom `chr…` → smallint.
3. **Query the shard.** `SELECT rs_id, chrom, position, gene_id, pvalue, beta, se, trait_id FROM
   eqtl_snp_{id} WHERE gene_id = :g` (add `chrom`/`position` window as needed — indexes favour
   `(chrom, rs_id)` and `gene_id`).
4. **Cast** `pvalue`/`beta`/`se` from text to float.
5. **Decode for display** (§2): int → `ENSG…`, int → `rs…`. Join `gencode_v26_hg38` on the versioned
   ENSG for **gene symbol + coordinates**; join `gene_median_tpm(+_tissue_relation)` for expression.
6. **For alleles / MAF / effect-allele-aware β** (not in the DB — §8), read the dataset's source
   tarball via `eqtl_raw.url`, or fold alleles into the schema during Phase-1 reconciliation.

---

## 8. Reconciliation against locusview's schema principles

locusview's [canonical schema principles](schema.md) were written before this database was chosen.
ADR-0008 says they must now be **reconciled** with reality. The material gaps:

| locusview principle (`schema.md`) | locuscompare2 reality | Gap / action |
|---|---|---|
| **#1 stable keys** — variant key `chrom:pos:ref:alt`; unversioned ENSG gene key | Variant key is an **rsID integer** (no ref/alt); gene key is unversioned ENSG int ✓ | Gene key aligns. **Variant key does not** — there is no normalized `chrom:pos:ref:alt`, and rsIDs "merge and change" exactly as the principle warns. Decide a variant-identity strategy in Phase 1. |
| **#2 effect direction is explicit** — always store `effect_allele`; β relative to `alt` | `eqtl_snp_*` stores **no ref/alt/effect_allele**; β sign is uninterpretable from the DB alone | **Biggest gap.** Alleles live only in source files (`eqtl_raw.url`). Either ingest alleles into the schema or always carry the source file. This directly threatens the "#1 cross-dataset bug" the principle exists to prevent. |
| **#3 biological-context axis** (`is_single_cell`, UBERON/CL/EFO) | Only a free-text `tissue` string + a coarse `type`; no ontology columns | Add the structured context axis in Phase 1; map existing `tissue` strings to UBERON. |
| **#4 provenance travels with every record** (build, harmonization, pipeline/version, access date) | Partial: `type`, `url`, `file_path`, `info_json`, GWAS `sha256`; **no** genome-build/harmonization/version columns | Build is an implicit global GRCh38; make provenance explicit per dataset. |
| **#5 genome build canonical GRCh38** | GRCh38 throughout ✓ | Aligned. |
| **MAF available** (implied by downstream filtering) | `eqtl_snp_*` has **no `maf`** (only a column-name placeholder in `eqtl_raw`) | Source-file only; ingest if needed for serving. |
| Coverage | **Autosomes 1–22 only; rs-style variants only** (§2) | Surface chrX/Y/MT and non-rs variants as explicit "not covered", not empty results. |

These gaps are **inputs to ADR-0006** (the canonical schema, to be ratified in Phase 1 against real
rows) and to the Phase-5 contribution model ([ADR-0007](../adr/0007-community-contribution-model.md)).

---

## 9. Open questions for the data owners (`needs-human`)

1. **Canonical instance & credentials** — which host is authoritative (local compose vs a managed
   MySQL), and issue locusview a least-privilege account (see the how-to).
2. **Pin the server version** — replace `mysql:latest` with an explicit tag.
3. **Alleles/MAF** — can the eQTL SNP tables gain `ref`/`alt`/`maf` columns (or a materialized view),
   so β sign is interpretable without the source tarballs?
4. **PII isolation** — move `user` (and other app tables) out of the reader's reach, ideally into a
   separate schema, so a QTL read grant can't touch personal data.
5. **utf8mb3 → utf8mb4** and the `effect_allele_frequency"` column-name typo — fix on the
   locuscompare2 side or document as permanent quirks.
