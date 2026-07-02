# Design proposal — Community contributions (user uploads)

- **Status:** PROPOSAL — for **Phase 5**. Do **not** build yet. This captures a research-backed design
  so the decision is preserved while fresh; it will be **ratified (or revised) at Phase-5 kickoff**
  against the reality of the shipped read path.
- **Diátaxis quadrant:** Design/Explanation (a spec — the *how*, paired with the *why*).
- **Related:** [roadmap Phase 5](../product/roadmap.md) · [schema principles](../reference/schema.md)
  · decision recorded in [ADR-0007](../adr/0007-community-contribution-model.md).
- **Storage note ([ADR-0008](../adr/0008-store-qtl-in-locuscompare2-database.md)):** QTL data now
  lives in the **shared locuscompare2 database**. The "publish = catalog registration over Parquet"
  step (§1) and the trust-zone storage flow (§5) will be **re-derived against that database** once its
  schema is documented (backlog B1, owner Junbin). Treat the storage specifics below as provisional.

## Goal
Let researchers **upload their own QTL datasets**, with curated metadata, **reviewed before they go
public**. Confirmed team decisions: deferred to a later phase (not Phase 1); human review before
publish; a **mandated format + metadata form**.

## 1. Contribution workflow (state machine)
One genuine human gate; everything else automated. Each status change is also a physical
storage-zone move (**copy-forward, never mutate in place**).

```
draft ──submit──▶ awaiting_upload ──(presigned PUT)──▶ uploaded
uploaded ──auto──▶ validating
validating ──fail──▶ validation_failed ──(fix → new upload)──▶ awaiting_upload
validating ──pass──▶ validated ──auto──▶ in_review
in_review ──approve (maintainer)──▶ published
in_review ──request_changes──▶ draft
in_review ──reject──▶ rejected            (terminal, reopenable)
published ──new_version──▶ awaiting_upload   [DEFER]
```

**Publish = catalog registration, not re-ingestion:** one row inserted into a DuckDB `datasets`
table pointing at the contributor's normalized Parquet — so contributed data becomes queryable by the
*same* read path the curated data uses. No per-variant DB load.

## 2. Required metadata (the five fields) + how they map to our schema
All five are **dataset-level** (they attach to provenance/context, never to the per-row
variant/ENSG key). Store machine-readable IDs (CURIEs) + display labels; any free-text "Other" sets
`needs_curation = true`.

| Field | Key(s) | Vocabulary / standard | Required | Maps to |
|---|---|---|---|---|
| Tissue / cell | `tissue_id`, `tissue_label` | **UBERON** (+ **CL** for cell types); eQTL Catalogue ~50-term shortlist as UX seed | Yes | biological-context axis |
| **Ancestry (NEW)** | `ancestries[]` = `{ancestry_category, ancestry_detail?, hancestro_id?, component_n?}` | GWAS-Catalog 17-category list (facet) + optional **HANCESTRO** CURIE | Yes (≥1) | **new axis** (see schema) |
| Sample size | `n_total` (+`n_cases`/`n_controls`/`n_effective`) | driven by `study_type` enum | Yes (`n_total`) | provenance |
| Perturbations | `perturbations[]` = `{perturbation_type, condition_label, condition_ontology_id?, dose?, timepoint_value?/unit?}` | eQTL-Catalogue condition/timepoint model; EFO/CHEBI/NCBITaxon/UO | Yes (≥1; default `none`) | biological-context axis |
| License | `license_spdx` → derived `commercial_use_allowed`, `attribution_required`, `license_url` | **SPDX** IDs (CC0/CC-BY/CC-BY-NC/…); `NOASSERTION`/`Other` ⇒ treated restricted | Yes | provenance (the filter facet) |

Also captured on publish (not user-typed): `genome_build`, `qtl_type`, `contributor_id`, `sha256`,
`validator_version`, `kind = contributed`, a required citation string, optional publication DOI/PMID,
and an internal accession (`LVxxxxxx`).

## 3. Upload format contract
Contributors provide **GWAS-SSF**: a **bgzip**-compressed, tab-delimited summary-stats TSV **+ a YAML
metadata sidecar**, using the eQTL-Catalogue-aligned QTL extension for molecular QTLs. Rationale:
it's the finalized GWAS Catalog community standard (max interoperability with the resources we
cross-link), and a pip-installable validator (`gwas-sumstats-tools`) already exists — **the team
writes zero custom format/validator code**. Internally we normalize accepted files to Parquet
(partition by chromosome) and keep a bgzip+tabix copy for range streaming; contributors never produce
Parquet.

## 4. Moderation & identity
- **Human review, not auto-publish.** `validated ≠ published`; a single maintainer does a thin check
  (spam/PII, metadata sanity, license validity, plausibility) then approves. Mirrors GWAS
  Catalog/ClinVar/GEO practice.
- **Identity: magic-link email verification** for sessions (1 table + a mailer — cheapest thing giving
  revocable, email-bound provenance + a rate-limit key). **ORCID captured as an optional attribution
  field**, not as an OAuth login (defer OAuth). Rule out anonymous and full accounts/RBAC for now.

## 5. Upload security — the non-negotiables
1. **Presigned direct-to-R2 uploads** (browser → R2; the app never holds file bytes; multipart for
   large files; bucket CORS locked to the portal origin).
2. **Server-chosen object keys** `quarantine/{uuid4}/{name}`; never trust client filename; short URL expiry.
3. **Three credential-separated trust zones** — `quarantine/ → validated/ → published/`, copy-forward;
   curated data in a separate `curated/` prefix the upload code can never write; the query token is
   read-only over `published/`+`curated/`.
4. **Authoritative server-side size enforcement** (re-read from R2 `head_object`; edge body limit).
5. **Sniff magic bytes** (bgzip / `PAR1`), don't trust extension/Content-Type.
6. **Decompression-bomb guard** (cap decompressed bytes + rows while streaming).
7. **SHA-256** on every upload (integrity, idempotency, dedup/abuse).
8. **Validation out-of-band** (background worker, concurrency 1–2, per-job memory/time caps).
9. **DuckDB public surface hardened:** `read_only=True`, parameterized queries only, `memory_limit` +
   statement timeout + row caps.
10. **Rate limits** keyed on verified email + IP; **quarantine TTL** (7–14 d) auto-deletes junk.
11. HTTPS only; CSRF on state-changing HTMX POSTs; strict CSP; `HttpOnly/Secure/SameSite` cookies;
    secrets in env; **immutable audit trail** of every transition. Never serve executable content from
    user storage.

## 6. Scope & the thinnest viable slice
**Sequence, don't bundle:** the read path has no untrusted input; contribution concentrates all the
risk (auth, async worker, storage-zone credentials, validation, moderation). Ship and harden the read
path first, then add contribution as a **bolt-on that registers into the same catalog** the read path
already queries.

**Thinnest viable v1:** magic-link auth → metadata form (~10 fields) → presigned upload to
`quarantine/` → async `gwas-sumstats-tools validate` (+ thin Pandera/tabix checks, machine-readable
errors via HTMX) → one maintainer approve/reject → normalize to Parquet → INSERT catalog row → live,
labelled "contributed" and filterable separately from curated.

**Defer:** uniform reprocessing/harmonization & liftover (require build up front); DOIs & dataset
versioning UI (Zenodo is a low-cost fast-follow); ORCID OAuth login, accounts/RBAC, submitter groups;
ontology-rich sample metadata (free-text + `needs_curation` first); programmatic submission API;
per-variant DB ingestion; ClamAV; embargo/pre-publication access control.

## 7. Decisions to ratify at Phase-5 kickoff
Proposed (from research; confirm against then-current reality): GWAS-SSF as the sole format;
presigned R2 + three trust zones; publish-as-registration; human gate / no auto-publish; magic-link
identity; ancestry as a first-class filter axis; SPDX license + `commercial_use_allowed` facet;
sequence-after-read-path with DOI/versioning deferred. If most survive kickoff review, promote the
relevant ones to their own ADRs then — don't pre-write eight ADRs for work that's phases away.

## 8. Open items to verify before building
Exact required-vs-optional fields in the GWAS Catalog deposition YAML and eQTL Catalogue
`Metadata_standards.md`; the HANCESTRO release to pin; Zenodo's mandatory metadata (if we add DOIs);
and that R2 multipart completion always re-asserts size/checksum server-side.

---
*Provenance: distilled from a 4-agent web-verified research workflow (submission models, metadata &
licensing, upload security) — see the session's contribution-feature research output.*
