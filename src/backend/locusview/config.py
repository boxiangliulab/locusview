"""Application configuration, loaded from the environment (12-Factor).

Config lives in environment variables (or a local ``.env`` file), never in source.
Copy ``.env.example`` to ``.env`` to override defaults locally. All variables use the
``LOCUSVIEW_`` prefix, e.g. ``LOCUSVIEW_ENV=production``.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings, read from ``LOCUSVIEW_*`` env vars / ``.env``."""

    model_config = SettingsConfigDict(
        env_prefix="LOCUSVIEW_",
        env_file=".env",
        extra="ignore",
    )

    env: str = "development"  # development | production
    log_level: str = "INFO"
    data_dir: str = "./data"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings (cached)."""
    return Settings()


# ── Legacy: the old MySQL locuscompare2 DB (ADR-0008) ───────────────────────
# Superseded 2026-08 by the new Postgres locuscompare2 DB (PostgresSettings, below), which has
# richer/indexed QTL data. Kept — commented out where it's used (see requestinfo.py) rather than
# deleted — because the new DB has no gene-annotation or LD-reference tables yet, so gene-symbol
# search and LD coloring have no home until that data lands somewhere. Not currently read by
# _default_repository(); left here in case those features need to fall back to it.
#
# class DatabaseSettings(BaseSettings):
#     """Connection settings for the shared locuscompare2 database (ADR-0008).
#
#     Read from ``LOCUSCOMPARE2_DB_*`` env vars / ``.env``. The password is injected by the
#     deployment secret store and must never be committed. locusview connects with a
#     least-privilege, read-only account.
#     """
#
#     model_config = SettingsConfigDict(
#         env_prefix="LOCUSCOMPARE2_DB_",
#         env_file=".env",
#         extra="ignore",
#     )
#
#     host: str = ""
#     port: int = 3306
#     name: str = "colotool"
#     user: str = "locusview_ro"
#     password: str = ""
#     ssl_mode: str = "REQUIRED"
#
#
# @lru_cache
# def get_db_settings() -> DatabaseSettings:
#     """Return the process-wide database settings (cached)."""
#     return DatabaseSettings()


class PostgresSettings(BaseSettings):
    """Connection settings for the new Postgres locuscompare2 DB (superseded MySQL 2026-08).

    Read from ``LOCUSCOMPARE2_PG_*`` env vars / ``.env``. Schema: ``qtl_datasets`` (catalog) ->
    ``qtl_lists`` (one row per dataset x context, id = the ``qtl_snp_{id}`` shard number) ->
    ``qtl_contexts`` (tissue/cell-type labels); ``qtl_snp_{id}`` (chrom, position, ref, alt, beta,
    se, pval, phenotype_key, maf) + ``qtl_snp_{id}_phenotype`` (phenotype_key -> gene_id);
    ``variant_rsid_mapping_raw`` (indexed rsID <-> chrom/pos/ref/alt). No gene-annotation table
    (symbol/coords/strand) and no LD-reference table yet — see connectpostgres.py's
    ``PostgresQtlRepository`` docstring for what that means for gene-symbol search / LD coloring.
    """

    model_config = SettingsConfigDict(
        env_prefix="LOCUSCOMPARE2_PG_",
        env_file=".env",
        extra="ignore",
    )

    host: str = ""
    port: int = 5432
    name: str = "locuscompare2"
    user: str = "locuscompare"
    password: str = ""
    db_schema: str = "public"


@lru_cache
def get_pg_settings() -> PostgresSettings:
    """Return the process-wide Postgres settings (cached)."""
    return PostgresSettings()
