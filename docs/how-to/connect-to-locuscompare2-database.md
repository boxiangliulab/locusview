# How to: connect locusview to the locuscompare2 database

> **How-to** (Diátaxis) — a task recipe. Goal: give locusview a **least-privilege** connection to the
> shared locuscompare2 MySQL database (schema `colotool`) — **read-only** for the public serving path,
> with a **separate, scoped writer** reserved for Phase-5 contributions.
>
> Background facts (DBMS, version, tables) are in the
> [locuscompare2 database reference](../reference/locuscompare2-database.md). The change process is
> [schema-change coordination](../process/schema-change-coordination.md).
>
> This is Phase-0 planning: locusview has **no** runtime DB code yet (the Phase-1 stack lands with
> ADR-0002). Do the human/ops steps (§1–§3) now; the app-config steps (§4–§5) are the contract Phase-1
> code will implement.

---

## The access model in one picture

```
locuscompare2_backend ──(root / owner)──▶  colotool  (single MySQL 8.3.0 instance, InnoDB)
                                             ▲   ▲
              locusview serving path ────────┘   │   GRANT SELECT   (read-only)     ← Phase 1
              locusview Phase-5 writer ──────────┘   GRANT INSERT/UPDATE on scoped   ← Phase 5, off by default
                                                     contribution tables only
```

Two locusview principals, least privilege each:

| Principal | Used by | Privilege | When |
|---|---|---|---|
| `locusview_ro` | Public read/serving path | `SELECT` only, on QTL tables (**not** `user`/PII) | Phase 1 |
| `locusview_rw` | Contribution ingest only | `SELECT` + `INSERT`/`UPDATE` on an explicit, scoped table set | Phase 5 (created but unused/disabled until then) |

locusview must **never** use the backend's `root` account (`db_config.py` ships a hardcoded shared
`root` password in source; treat it as compromised and do not reuse it — the value is intentionally
not reproduced here).

---

## 0. Shared test/demo read-only account (verified 2026-07-02)

A **non-production, read-only** account exists for development and for the CI contract tests. Use it to
explore the schema and to run the read-path examples — **never** for production serving.

| Field | Value |
|---|---|
| Host / Port | **held out of this repo until the PII grant below is restricted** — see the warning |
| Database | `colotool` |
| User | `locusview_test` |
| Password | **held out** (currently equal to the username, so publishing it + the endpoint = working access) |
| TLS | optional on this test endpoint (connections arrive NAT'd as `172.21.0.1`) |

> 🔴 **Do not publish these credentials until the account is restricted.** As verified on 2026-07-02,
> `locusview_test` holds `GRANT SELECT ON colotool.*` and **can read the `user` table** (442 rows incl.
> `email` and `encrypted_password`). Because this repo is **public**, committing a working password for
> a PII-readable account would expose that PII. Restrict the grant first (below); once `SELECT … FROM
> user` is denied, the password can safely go in this table.

**Restrict the test account to non-PII tables (run as root).** MySQL grants are additive and have no
"all-except", so revoke the schema-wide grant and re-grant everything *except* `user`:

```sql
REVOKE SELECT ON colotool.* FROM 'locusview_test'@'%';
SET SESSION group_concat_max_len = 1024*1024;
-- Generates one GRANT per table except `user`; run the produced statements:
SELECT GROUP_CONCAT(
         CONCAT('GRANT SELECT ON colotool.`', table_name, '` TO ''locusview_test''@''%'';')
         SEPARATOR '\n')
FROM information_schema.tables
WHERE table_schema = 'colotool' AND table_name <> 'user';
FLUSH PRIVILEGES;
```

(A tighter alternative — grant only the QTL/expression/annotation/1000G tables + `eqtl_snp_%` shards —
is Option B in §2; either removes `user` from reach.)

## 1. Prerequisites (data owner)

- Agree which instance is **authoritative** for locusview (open question #1 in the reference). Options:
  the lab's managed MySQL, or a read-replica. **Do not** point production locusview at a laptop
  `docker-compose` instance.
- Confirm network reachability (VPC/security-group/firewall) from where locusview will run.
- Confirm the server enforces TLS for non-local connections (see §5).

## 2. Create the read-only serving role

Table names include **dynamic shards** (`eqtl_snp_{id}`, `gwas_snp_{id}`,
`colocalization_gene_result_{id}`), so per-table grants are impractical — new datasets would silently
be unreadable until re-granted. Two viable shapes:

**Option A — pragmatic, schema-wide SELECT (recommended if PII is isolated).** Simple and shard-proof,
but grants `SELECT` on **every** table in `colotool`, including `user`:

```sql
CREATE USER 'locusview_ro'@'%' IDENTIFIED BY '<strong-random-secret>';
GRANT SELECT ON colotool.* TO 'locusview_ro'@'%';
FLUSH PRIVILEGES;
```

⚠ This exposes the `user` table (email, session `uuid`, `encrypted_password`). **Only choose Option A
if PII is moved out of `colotool`** (reference open question #4) — otherwise use Option B.

**Option B — PII-safe, explicit table set.** Grant only the QTL/expression/annotation tables plus the
current shards, and **re-grant when a dataset is added** (fold this into the ingestion runbook):

```sql
CREATE USER 'locusview_ro'@'%' IDENTIFIED BY '<strong-random-secret>';
-- catalogs, expression, annotation, mapping
GRANT SELECT ON colotool.eqtl_raw                        TO 'locusview_ro'@'%';
GRANT SELECT ON colotool.gwas_raw                        TO 'locusview_ro'@'%';
GRANT SELECT ON colotool.gene_median_tpm                 TO 'locusview_ro'@'%';
GRANT SELECT ON colotool.gene_median_tpm_tissue_relation TO 'locusview_ro'@'%';
GRANT SELECT ON colotool.trait_item                      TO 'locusview_ro'@'%';
GRANT SELECT ON colotool.gencode_v26_hg38                TO 'locusview_ro'@'%';
-- per-dataset shards (repeat for each eqtl_raw.id served)
GRANT SELECT ON colotool.eqtl_snp_1                      TO 'locusview_ro'@'%';
-- …one line per served shard…
FLUSH PRIVILEGES;
```

> **Cleaner long-term fix (recommended to the owners):** expose locusview's read surface as **SQL
> views** in a dedicated schema (e.g. `locusview_read.eqtl_association`) that (a) hide `user`/PII, (b)
> pre-`UNION` or abstract the shards, and (c) cast the text `pvalue`/`beta`/`se` to numeric. Then grant
> `SELECT` only on that schema. This decouples locusview from locuscompare2's physical layout and is
> the safest reader boundary. Tracked in [schema-change coordination](../process/schema-change-coordination.md).

Whichever option, restrict the host (`'locusview_ro'@'10.0.%'` rather than `@'%'`) to locusview's
network where possible.

## 3. Reserve (do not yet use) the Phase-5 writer

Create it now so the boundary is designed in, but keep it **out of the serving path** until Phase 5.
Its scope is only the contribution tables the Phase-5 design defines
([ADR-0007](../adr/0007-community-contribution-model.md)) — never the curated eQTL shards:

```sql
CREATE USER 'locusview_rw'@'10.0.%' IDENTIFIED BY '<different-strong-secret>';
-- Example scope; finalize table names at Phase-5 kickoff. NOT on curated eqtl_snp_* / eqtl_raw.
GRANT SELECT, INSERT, UPDATE ON colotool.lv_contribution      TO 'locusview_rw'@'10.0.%';
GRANT SELECT, INSERT, UPDATE ON colotool.lv_contribution_snp  TO 'locusview_rw'@'10.0.%';
FLUSH PRIVILEGES;
-- Until Phase 5: ALTER USER 'locusview_rw'@'10.0.%' ACCOUNT LOCK;
```

No `DROP`, `ALTER`, `CREATE`, or `GRANT` for either locusview role — **schema/DDL changes are
locuscompare2's**, per the coordination doc.

## 4. Wire the connection into locusview (Phase-1 contract)

Configuration lives in the environment (12-Factor), never in source — matching the existing
`.env.example`. The reader uses the same driver family as the backend (`PyMySQL`); the SQLAlchemy URL:

```
mysql+pymysql://locusview_ro:<secret>@<host>:<port>/colotool?charset=utf8mb4
```

Environment variables (added to `.env.example`):

```bash
LOCUSCOMPARE2_DB_HOST=            # authoritative host (NOT a laptop)
LOCUSCOMPARE2_DB_PORT=3306
LOCUSCOMPARE2_DB_NAME=colotool
LOCUSCOMPARE2_DB_USER=locusview_ro
LOCUSCOMPARE2_DB_PASSWORD=        # injected by the secret store; never committed
LOCUSCOMPARE2_DB_SSL_MODE=REQUIRED
```

Notes for the Phase-1 implementer:
- Prefer `charset=utf8mb4` on locusview's connection even though the backend uses `utf8`(mb3); it is a
  read connection and mb4 is a safe superset for reading.
- Treat `pvalue`/`beta`/`se` as **text** and cast in the app (reference §4/§7); don't assume numeric.
- Apply the integer **encode/decode** on every gene/variant/chrom crossing the boundary (reference §2).
- Use a small connection pool with `pool_recycle` (the backend uses 3600s) — MySQL drops idle
  connections; the compose file sets very long timeouts that a managed host will not.

## 5. Secret handling & security

- **Rotate the shared `root` credential** hardcoded in the backend on the target instance; locusview
  must not use it.
- Store `LOCUSCOMPARE2_DB_PASSWORD` in the deployment secret store (not `.env`, not git). `.env` stays
  gitignored; `.env.example` carries only empty placeholders.
- **Require TLS** for any non-local connection (`SSL_MODE=REQUIRED`); the DB may still be on
  `mysql_native_password`, so the transport must protect the handshake.
- Give the reader a **least-privilege host mask** and, ideally, a **read replica** so serving load and
  ad-hoc queries can't affect the backend's writes.
- The read role is `SELECT`-only, which also contains SQL-injection blast radius — but still use
  parameterized queries in the app.

## 6. Verify

```bash
# reader can read a catalog…
mysql -h "$LOCUSCOMPARE2_DB_HOST" -P "$LOCUSCOMPARE2_DB_PORT" -u locusview_ro -p \
  -e "SELECT id, tissue, type FROM colotool.eqtl_raw LIMIT 5;"

# …and must NOT be able to write (expect: ERROR 1142 command denied)…
mysql -h "$LOCUSCOMPARE2_DB_HOST" -P "$LOCUSCOMPARE2_DB_PORT" -u locusview_ro -p \
  -e "CREATE TABLE colotool._lv_probe (x int);"

# …and (Option B / views) must NOT read PII (expect: denied)
mysql -h "$LOCUSCOMPARE2_DB_HOST" -P "$LOCUSCOMPARE2_DB_PORT" -u locusview_ro -p \
  -e "SELECT email FROM colotool.user LIMIT 1;"
```

A passing setup: catalog read works; write is denied; PII read is denied.
