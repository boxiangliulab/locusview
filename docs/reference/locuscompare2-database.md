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
> **Status: verified against the live instance on 2026-07-02** (read-only `locusview_test` account,
> MySQL 8.3.0). Facts below were first reverse-engineered from `locuscompare2_backend` and then
> confirmed with `SHOW CREATE TABLE` / `information_schema` / sample queries; verified counts are
> point-in-time and will drift as datasets are loaded.

---

## 1. DBMS and version (verified)

| Fact | Value | How confirmed |
|---|---|---|
| Engine | **MySQL 8.3.0**, "MySQL Community Server - GPL", storage engine **InnoDB** | `SELECT VERSION()`, `@@version_comment`, `@@default_storage_engine` |
| Server charset / collation | **`utf8mb4` / `utf8mb4_0900_ai_ci`** (most tables). Exceptions: `gencode_v26_hg38` and the `tkg_*` 1000G tables are **`latin1`** | `@@character_set_server`; per-table `SHOW CREATE TABLE` |
| Schema (database) name | **`colotool`** | connected |
| Total tables | **990** | `information_schema.tables` |
| Endpoint (test) | Kubernetes **NodePort** `54.254.162.217:31987` (= `mysql.locuscompare2.com:31987`); connections arrive NAT'd (server sees client as `172.21.0.1`). Read-only test account in the [how-to §0](../how-to/connect-to-locuscompare2-database.md) | connect |
| Driver (app) | **PyMySQL 1.0.2** via SQLAlchemy 2.0.4 / Flask-SQLAlchemy 3.0.3; URL scheme `mysql+pymysql://` | `locuscompare2_backend/requirements.txt` |
| App connection charset | backend connects with `?charset=utf8` (**utf8mb3** handshake) against utf8mb4 tables | `locuscompare2_backend/src/config/db_config.py` |

**Caveats worth a human decision (issue is labelled `needs-human`):**

- **Compose pins nothing.** The backend's `docker-compose.yaml` uses `mysql:latest`; the live server
  happens to be **8.3.0**. Two apps sharing one database should pin an explicit tag (e.g. `mysql:8.3`).
  Flagged in [schema-change coordination](../process/schema-change-coordination.md).
- **Connection vs storage charset mismatch.** Storage is `utf8mb4` (good), but the backend connects
  with the 3-byte `utf8`(mb3) alias. locusview should connect with **`utf8mb4`** to match the tables.
- **Charset is not uniform:** `gencode_v26_hg38` and the `tkg_*` reference tables are `latin1` while the
  QTL tables are `utf8mb4`.

---

## 2. The one thing that will bite you: keys are integer-encoded (verified)

The high-volume tables do **not** store identifiers as strings. On ingest the backend strips the
prefix and stores a bare integer, so locusview must apply the same transform to query, and the inverse
to display. Transforms live in `locuscompare2_backend/src/utils/utils.py`. Verified from a live
`eqtl_snp_1` row `(rs_id=867721319, chrom=11, gene_id=177951, position=128951, pvalue='0.837…',
beta='-0.03', se='0.1466', trait_id=NULL)`:

| Identifier | Stored as | Encode (query) | Decode (display) | Notes |
|---|---|---|---|---|
| Gene (`ENSG…`) | `BIGINT` | strip `ENSG` + leading zeros, **drop `.NN` version** (`ENSG00000177951` → `177951`) | `ENSG` + zero-pad to 11 digits (`177951` → `ENSG00000177951`) | **Lossy:** version suffix discarded. |
| Variant rsID (`rs…`) | `BIGINT` | strip `rs` (`rs867721319` → `867721319`) | `'rs' + n` | Only `rs`-prefixed IDs round-trip; merged/`TMP_*`/indel names do not. |
| Chromosome (`chr…`) | `SMALLINT` | strip `chr`/`CHR`/`Chr` → int | — | **Autosomes 1–22 only** — verified `SELECT DISTINCT chrom` returns exactly 1..22. `X`/`Y`/`MT` are dropped at ingest. |

**Consequence for locusview:** encode inputs the same way; the served eQTL data has **no
chrX/Y/MT** and **no non-rs variants** — surface both as explicit "not covered", not empty results.

---

## 3. Genome build and gene annotation (verified)

- **Build is GRCh38/hg38** throughout (annotation table `gencode_v26_hg38`; GTEx v8 and eQTL-Catalogue
  `_ge` are GRCh38). There is no per-row build column — GRCh38 is a global invariant.
- **Gene annotation: GENCODE v26** — `gencode_v26_hg38`, **58,182 rows**, columns `chr, start, end,
  strand, gene_name, gene_id, type` (gene_name/gene_id/type are `latin1`). `gene_id` here is the
  **versioned** ENSG; the backend joins it with `WHERE gene_id LIKE 'ENSG…​.%'` for symbol/coordinates.

---

## 4. Core QTL schema (what locusview reuses)

### The catalog / shard pattern (verified)

QTL data is stored in **two layers**:

1. **`eqtl_raw`** is a **dataset catalog** — **280 rows**, one per dataset (**49 `gtex-v8`** + **231
   `eqtl_catalog`**; no `ge`/`leaf-cutter` rows exist in this instance). Its value-looking columns
   (`rsid`, `gene_id`, `chrom`, `position`, `alt`, `ref`, `beta`, `pvalue`, `maf`) do **not** hold
   data — they hold the **source-file column name** for that field. Verified: every GTEx row has
   `gene_id='molecular_trait_id'`, `chrom='chromosome'`, `ref='ref'`, `alt='alt'`, `maf='maf'`.
2. **`eqtl_snp_{eqtl_raw_id}`** holds the actual per-variant associations — **one physical table per
   dataset** (**280 shards** live; e.g. `eqtl_snp_1` ≈ 138 M rows). Query per dataset; there is no
   unified "all eQTL" table.

> ⚠ **Do not read `eqtl_raw.gene_id` as a gene.** It is the string `"molecular_trait_id"`. Same
> catalog-with-column-name-mapping pattern applies to `gwas_raw` (§6).

### `eqtl_raw` — eQTL dataset catalog
| Column | Type | Meaning |
|---|---|---|
| `id` | BIGINT PK | Dataset id; also the shard suffix (`eqtl_snp_{id}`) and the `tissue_id` referenced by TPM (§5). |
| `tissue` | VARCHAR(255) | Dataset name = source filename stem (e.g. `Whole_Blood`, `BLUEPRINT_monocyte_ge`). |
| `type` | VARCHAR(32) | `gtex-v8` (49) or `eqtl_catalog` (231). |
| `rsid`,`gene_id`,`chrom`,`position`,`alt`,`ref`,`beta`,`pvalue`,`maf` | VARCHAR(128) | **Source-file column names**, not values. |
| `url` | VARCHAR(255) | S3 key of the preprocessed dataset tarball (source of alleles/MAF — §7/§8). |
| `file_path` | VARCHAR(255) | Path to the dataset on the lab's compute box. |
| `info` (attr `info_json`) | VARCHAR(4096) | JSON tissue metadata for `eqtl_catalog` datasets (empty for plain GTEx v8). |

### `eqtl_snp_{eqtl_raw_id}` — per-dataset eQTL associations (sharded) — verified DDL
```sql
CREATE TABLE `eqtl_snp_1` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `se` varchar(32) NOT NULL,
  `rs_id` bigint NOT NULL,               -- variant, integer-encoded
  `chrom` smallint NOT NULL,             -- autosome 1..22
  `gene_id` bigint NOT NULL,             -- gene, integer-encoded
  `position` bigint NOT NULL,            -- GRCh38 coordinate
  `pvalue` varchar(32) DEFAULT NULL,     -- TEXT: cast on read
  `beta` varchar(32) NOT NULL,           -- TEXT: sign uninterpretable w/o effect allele (§8)
  `trait_id` bigint DEFAULT NULL,        -- FK -> trait_item.id (leafcutter); NULL for gene-level
  PRIMARY KEY (`id`),
  KEY `ix_eqtl_snp_1_gene_id` (`gene_id`), KEY `ix_eqtl_snp_1_chrom` (`chrom`),
  KEY `ix_eqtl_snp_1_trait_id` (`trait_id`), KEY `idx_eqtl_snp_join` (`chrom`,`rs_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
```
**Absent here (important):** no `ref`/`alt`/`effect_allele`, no `maf`, no `variant_id`. See §7–§8.

---

## 5. Gene expression (TPM) tables

- **`gene_median_tpm`** — `id`, `gene_id` (BIGINT, encoded, indexed), `description` (VARCHAR(30), gene
  symbol). Loaded from GTEx v8 median-TPM GCT.
- **`gene_median_tpm_tissue_relation`** — `id`, `tpm_id` (→ `gene_median_tpm.id`), `tissue_id`
  (**→ `eqtl_raw.id`**, not a separate tissue table), `value` (FLOAT median TPM).

---

## 6. Molecular-trait mapping and the other co-tenants

locusview's read path is the eQTL/TPM tables above. The rest of the `colotool` schema matters for the
*coupling* story and because a broad read grant would expose it.

- **`trait_item`** — leafcutter intron ↔ gene: `id` (the int referenced by `eqtl_snp_*.trait_id`),
  `gene_id` (BIGINT, encoded), `trait_id` (VARCHAR(64), the **original trait string**). ⚠ Naming
  inversion: `trait_item.trait_id` is a string name; `eqtl_snp_*.trait_id` is the integer `trait_item.id`.
- **`gwas_raw`** — GWAS dataset catalog, same catalog+column-map pattern as `eqtl_raw`. 🐛 Verified: it
  literally contains a **stray-quote column name `effect_allele_frequency"`** — quote it exactly, and
  consider fixing on the locuscompare2 side.
- **`gwas_snp_{gwas_raw_id}`** — per-GWAS SNPs, **406 shards**; `rs_id`, `chrom`, `position`, `p_value`
  (FLOAT), `beta`, `se`, `manh_plot_used` (TINYINT, Manhattan downsample flag). No allele columns.
- **`colocalization_record`** (≈1.8 K rows) and **`colocalization_gene_result_{id}`** (**174 shards**,
  `id = record.id // 10`; per-method scores as VARCHAR(32)); **`gwas_genomic_loci`**; **`PvalueThre`**.
- **`user`** — ⚠ **PII, 442 rows**: `id`, `email` VARCHAR(64), `user_name` VARCHAR(60), `uuid`
  VARCHAR(64) (session token), `encrypted_password` VARCHAR(256), `organisation` VARCHAR(64),
  `create_at`. **A read-only serving role must not reach this table** (how-to §2/§7).

### 1000 Genomes reference panels (verified — relevant to the allele gap)
The schema also carries **1000 Genomes Phase 3 v5a** reference data, which is where alleles and
population frequencies actually live:

- **`tkg_p3v5a_hg38`** (**82.5 M rows**) and **`tkg_p3v5a_hg19`** — columns `chr, pos, rsid, ref, alt,
  AF, EAS_AF, AMR_AF, AFR_AF, EUR_AF, SAS_AF`; indexed on `rsid` and `(chr,pos)`. (`latin1`.)
- **`tkg_p3v5a_ld_chr{1..22,X}_{AFR,AMR,EAS,EUR,SAS}`** — per-chromosome, per-super-population LD tables.

This means the **`ref`/`alt` alleles and per-ancestry allele frequencies missing from `eqtl_snp_*` can
be recovered by joining variants to `tkg_p3v5a_hg38`** on `rsid` (or `chr,pos`) — see §8.

---

## 7. How locusview reads an eQTL association (recipe)

1. **Resolve dataset(s):** `SELECT id, tissue, type, info FROM eqtl_raw` → pick by `tissue`/`type`; `id`
   is the shard suffix.
2. **Encode keys** (§2): gene→int, variant→int, chrom→smallint.
3. **Query the shard:** `SELECT rs_id, chrom, position, gene_id, pvalue, beta, se, trait_id FROM
   eqtl_snp_{id} WHERE gene_id = :g` (indexes favour `(chrom, rs_id)` and `gene_id`).
4. **Cast** `pvalue`/`beta`/`se` text → float.
5. **Decode + enrich:** int→`ENSG…`/`rs…`; join `gencode_v26_hg38` (versioned ENSG) for symbol +
   coordinates; join `gene_median_tpm(+_tissue_relation)` for expression.
6. **For alleles / AF:** join `tkg_p3v5a_hg38` on `rsid`/`(chr,pos)` (§8) — or read the dataset source
   tarball via `eqtl_raw.url`.

---

## 8. Reconciliation against locusview's schema principles (verified)

| locusview principle (`schema.md`) | locuscompare2 reality (verified) | Gap / action |
|---|---|---|
| **#1 stable keys** — `chrom:pos:ref:alt`; unversioned ENSG | Gene key = unversioned ENSG int ✓. Variant key = **rsID int, no ref/alt** in `eqtl_snp_*` | Gene aligns. **No normalized variant id**; rsIDs merge/change. Decide a variant-identity strategy in Phase 1 (rsID + `tkg` join, or ingest `chr:pos:ref:alt`). |
| **#2 effect direction explicit** — store `effect_allele`; β vs `alt` | `eqtl_snp_*` has **no ref/alt/effect_allele** — β sign uninterpretable alone. **BUT** `tkg_p3v5a_hg38` provides `ref`/`alt` per variant | **Reduced from "blocking" to "resolvable":** join to 1000G to recover ref/alt. ⚠ Caveat: 1000G ref/alt ≠ the *dataset's* effect allele; the eQTL source file remains the authority for β direction. Confirm alignment before trusting signs. |
| **#3 biological-context axis** (`is_single_cell`, UBERON/CL/EFO) | Free-text `tissue` + coarse `type` only | Add structured context in Phase 1; map `tissue` → UBERON. |
| **#4 provenance per record** (build, harmonization, versions) | Partial: `type`, `url`, `file_path`, `info_json`; no build/harmonization columns | Build is implicit GRCh38; make provenance explicit per dataset. |
| **#5 GRCh38 canonical** | GRCh38 throughout ✓ | Aligned. |
| **MAF available** | Not in `eqtl_snp_*`. `tkg_p3v5a_hg38` has `AF` + per-pop (`EAS/AMR/AFR/EUR/SAS`) | Recover population AF via 1000G join (again ≠ dataset MAF); or ingest from source. |
| Coverage | **Autosomes 1–22 only; rs-style variants only** (verified) | Surface as explicit "not covered". |

These feed **ADR-0006** (canonical schema, Phase 1) and the Phase-5 model
([ADR-0007](../adr/0007-community-contribution-model.md)).

---

## 9. Open questions for the data owners (`needs-human`)

Updated with what the live check answered:

1. ✅ **DBMS/version** — MySQL **8.3.0** (but pin the compose tag; `mysql:latest` today ≠ tomorrow).
2. **Authoritative host** — the verified endpoint is a **test** Kubernetes NodePort
   (`54.254.162.217:31987`). Confirm the host locusview *production* should read (managed instance /
   read replica), and issue it a least-privilege account (how-to).
3. **PII isolation.** The `user` table (442 rows: email + `encrypted_password`) sits in `colotool`. The
   test reader has now been **scoped to exclude `user`** (verified 2026-07-02: `SELECT … FROM user` →
   `ERROR 1142`), so every reader grant must likewise exclude it. Cleaner still: move `user`/app tables
   to a separate schema so a QTL read grant *cannot* reach PII (how-to §0/§7).
4. **Alleles/MAF** — confirmed recoverable via the `tkg_p3v5a_hg38` 1000G join, but that is not the
   dataset's own effect allele. Decide whether to add `ref`/`alt` to the eQTL tables (or a view) so β
   is interpretable without the source tarballs.
5. **Quirks to fix or accept** — the `effect_allele_frequency"` column-name typo; `utf8mb4` tables vs
   the backend's `utf8`(mb3) connection; `latin1` on `gencode`/`tkg` tables.
