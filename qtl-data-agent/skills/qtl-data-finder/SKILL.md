---
name: qtl-data-finder
description: Exhaustively discover QTL literature and datasets across Google Search, Google Scholar, Europe PMC and PMC, for every molecular, cellular and context-specific QTL type; retain every candidate in the dated qtlliteraturereview TSV with provenance even when data access is unknown or unavailable.
---

# QTL data finder

This is the discovery stage. Its contract is recall-first: a paper or dataset candidate must never be silently dropped because an API omitted it, the article is closed access, an accession is missing, or a download URL has not yet been located. Later stages may reject or gate a row, but this skill records it first.

The hand-off table is `qtlliteraturereview-YYYY-MM-DD.tsv`; one row is one publication candidate until reading establishes that it contains one or more datasets.

```bash
F=qtl-data-agent/skills/qtl-data-finder/scripts/find_qtl.py
python3 "$F" review --families all open-web --top-per-query 500 --out qtlliteraturereview-$(date +%F).tsv
python3 "$F" discover --seed https://www.nature.com/articles/s41467-026-76575-4 \
  --append qtlliteraturereview-$(date +%F).tsv
python3 "$F" read qtlliteraturereview-$(date +%F).tsv
python3 "$F" name-datasets qtlliteraturereview-$(date +%F).tsv
```

## Search coverage

Run all four source routes and preserve the source names in `search_terms`/`evidence_source`:

1. Google Search: search exact QTL phrases, dataset names, article titles, DOI and `"data availability"`, including `site:nature.com`, `site:pmc.ncbi.nlm.nih.gov`, repository and supplement searches.
2. Google Scholar: search title/author variants and every QTL synonym; inspect “cited by” and “related articles” for papers missed by keyword indexing. Do not treat a Scholar result as verified data until the primary paper or repository is read.
3. Europe PMC REST: use `review` with cursor pagination and every family below.
4. PMC/full text: use Europe PMC `fullTextXML` and PMC article pages/supplements. A PMC hit and its publisher DOI are the same publication after deduplication, not a reason to discard either provenance.

The default organism expression is deliberately broad (`human`, donors, patients, cohort, tissue, blood, brain, etc.). Do not constrain tissue, organ, cell type, ancestry, disease, developmental stage, stimulation, sex, or sample size. Add focused queries freely, then append them to the same table.

Families include molecular types (`eQTL`, cis/trans-eQTL, `sQTL`, `pQTL`, `caQTL`, `haQTL`, `hQTL`, `meQTL`/`mQTL`, metabolite/lipid QTL, `riboQTL`, `miQTL`, `apaQTL`, `isoQTL`, `circQTL`, `tuQTL`), and biological contexts (single-cell/scQTL, single-nucleus, cell-type/state, pseudobulk, context-dependent/response/dynamic/interaction QTL, disease, treatment, infection, stimulation, developmental, tissue and organ). Include papers that call the result molecular QTL, allele-specific QTL, xQTL, or use a term not yet in the vocabulary.

`review` is an API sweep, not proof of completeness. Repeat it with narrower tissue/cell/state terms, publication-year ranges, resource names and Google/Scholar exports. Use `papers QUERY --append TABLE` for an ad-hoc Europe PMC query.

## Seeds and the “missing Nature paper” rule

For any result from Google, Scholar, PMC, a publisher page, or a user, immediately preserve the seed:

```bash
python3 "$F" discover --seed URL_OR_DOI --source google --append TABLE
# multiple URLs/DOIs can be supplied with repeated --seed or --seed-file
```

`discover` writes a candidate even when only a URL/DOI is known. Nature article URLs are normalized to their DOI (`10.1038/s41467-026-76575-4` for `s41467-026-76575-4`). A seed remains in the TSV with `access_route=unknown`, `direct_download=unknown`, and an explicit provenance marker until it is read; it is never filtered by `has_data`, accession, journal, or access status.

Deduplicate by DOI, PMID/PMCID, then normalized title, while unioning all `search_terms`, URLs, accessions and source provenance. Never deduplicate two rows that differ by dataset, QTL type, tissue, cell type/state, condition, ancestry, release, or quantification method.

## Reading and recording evidence

`read` checks (in order) PMC/Europe PMC full text and supplements, publisher page, OpenAlex/Crossref/Semantic Scholar metadata, Unpaywall locations, and repository links. Extract DOI/PMID/PMCID, title, authors, Data Availability text, repository/accession links, summary-statistics URLs, contact email, donor count, QTL type, tissue/cell/state/condition, ancestry, and dataset name. A landing page, raw FASTQ/BAM/VCF, expression matrix, LD panel or GWAS trait file is not a QTL association-statistics URL.

Write findings with `update`. If nothing is found, still update `evidence_source` and `extraction_note` (for example `data_not_located_after_pmc_publisher_repository_search`). Use `access_route=unavailable`, `request`, `controlled`, `blocked`, `portal`, or `supplement` as appropriate; reserve `unknown` for genuinely unread rows. Missing data is a recorded outcome, not a deletion.

A paper can yield multiple rows: one per dataset × QTL type × biological context. `sample_size` is donor/participant count, never cell count. Keep exact links and quoted section/sentence in `extraction_note`; retain repository accession and publication provenance even if verification later fails.

## Output schema and downstream hand-off

The skill owns these columns:

`record_id publication_title publication_url doi pmid first_author authors year journal contact_email qtl_type qtl_context population sample_size dataset_name download_url access_route direct_download extraction_note evidence_source search_terms search_date`

`qtl-record-verifier` may mark a row rejected, gated, blocked or verified, but must not erase discovery candidates. Only verified association-level files proceed to `download-qtl` and `sumstats-manifest`; request/controlled/unavailable rows stay in the review TSV and request queue.

Google/Scholar browsing may require an interactive browser or exported result list. Record the query, result URL, date and source in `search_terms`; never claim a source was searched when it was not. Do not send email or access controlled individual-level data.
