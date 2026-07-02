# ADR-0007: Community-contribution (user-upload) model

- **Status:** Accepted (scope & shape); **detailed design provisional, to be ratified at Phase-5 kickoff**
- **Date:** 2026-07-02
- **Note:** ADR-0006 is reserved for the canonical data schema (to be written in Phase 1 against real
  data); this ADR is numbered 0007 to preserve that reservation.

## Context
A key long-term goal is to let researchers **upload their own QTL datasets**, not only serve curated
ones. This is a significant capability (submission workflow, trust/governance, file-upload security)
and was originally listed out of scope for the Phase-1 read-only MVP. The team reconsidered and
decided it belongs in a **dedicated later phase (Phase 5)**, not bundled into Phase 1. A 4-agent
web-verified research pass produced a concrete design (see
[community-contributions.md](../design/community-contributions.md)).

## Decision
Adopt the following **shape** for community contributions (full design ratified at Phase-5 kickoff):

1. **Sequence, don't bundle** — build and harden the read path first; add contribution as a bolt-on
   that **registers into the same catalog the read path queries** (publish = a catalog row over the
   contributor's normalized Parquet, not per-variant re-ingestion).
2. **Mandated format:** contributors upload **GWAS-SSF** (bgzip TSV + YAML sidecar; eQTL-Catalogue QTL
   extension), validated with the off-the-shelf `gwas-sumstats-tools` — no custom format/validator code.
3. **Human review before publish** — automated validation gates, then one maintainer approves;
   `validated ≠ published`. No auto-publish.
4. **Identity:** magic-link email verification for sessions; ORCID as an optional attribution field.
   Defer OAuth/accounts/RBAC.
5. **Security posture:** presigned direct-to-R2 uploads; three credential-separated trust zones
   (`quarantine → validated → published`, curated isolated); server-authoritative size checks; magic-
   byte sniffing; decompression-bomb guards; read-only, resource-capped DuckDB query surface; rate
   limits; immutable audit trail.
6. **Metadata & schema:** ancestry becomes a **first-class, filterable axis** (distinct from tissue);
   license is stored as a machine-readable **SPDX** id with a derived `commercial_use_allowed` facet
   (`NOASSERTION`/`Other` ⇒ treated as restricted). These extend the
   [schema principles](../reference/schema.md).
7. **Defer** DOIs/versioning (Zenodo is a low-cost fast-follow), reprocessing/liftover, ontology-rich
   metadata, and a submission API.

## Consequences
- **+** Records the decision and its rationale now, while the research is fresh, without committing a
  beginner team to premature construction.
- **+** Keeps Phase 1 a low-risk read-only slice; concentrates untrusted-input risk into one later,
  well-scoped phase.
- **+** Reusing GWAS-SSF + `gwas-sumstats-tools` and "publish = catalog registration" minimizes new code.
- **−** Some specifics (auth, storage-zone details) are recommendations, not yet lived; they may change
  at Phase-5 kickoff. The design doc is explicitly marked provisional.
- **−** Ancestry/license/context schema additions must be honoured by the Phase-1 schema so contributed
  data slots in without a fork — a small forward-compatibility tax paid now.
