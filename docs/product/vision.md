# Vision

> **What this is:** one page describing where locusview is going in the next 1–3 years — the problem,
> who has it, and what success looks like. It is deliberately about *outcomes*, not features. When a
> decision is hard, we come back here and ask "which choice serves the vision?"

## The problem

Quantitative trait locus (QTL) data — the statistical links between genetic variants and molecular
traits like gene expression — is one of the most useful resources in modern genomics for turning a
GWAS hit into a mechanism. But it is **scattered**. A researcher asking a simple question ("what are
the eQTLs for *my* gene, and in which tissues?") must visit GTEx, the eQTL Catalogue, eQTLGen, and
others; each has a different interface, file format, genome build, and set of conventions. The data
is public, yet effectively **hard to use**.

## Who has it

- **Bench and computational biologists** interpreting a locus: "is this variant an eQTL, for which
  gene, in which tissue or cell type?"
- **Statistical geneticists** doing colocalization and fine-mapping who need harmonized summary
  statistics they can trust and cite.
- **Students and newcomers** who don't yet know which of a dozen portals to start with.

## What success looks like (1–3 years)

A researcher comes to **one** place, types a gene, a variant, or a region, and immediately sees the
QTL evidence across public datasets — with consistent coordinates, explicit effect directions, clear
provenance, and a one-click, honestly-licensed download. They trust it enough to cite it. Over time,
locusview covers the major public bulk sources, then single-cell and context-specific QTL, without
the user ever thinking about the format wrangling underneath.

**We will know we are succeeding when** researchers reach for locusview first instead of bookmarking
five portals, and when its downloads show up in methods sections.

## What we believe

- **Aggregation with integrity beats aggregation with volume.** Consistent, provenance-stamped,
  correctly-oriented data is worth more than a larger pile of mismatched numbers.
- **Open and self-hostable.** Public data deserves an open tool that outlives any single grant.
- **Built in the open, as a teachable craft.** How we build locusview is itself a contribution —
  a worked example of doing software engineering, with AI agents, responsibly.

## What this vision is *not*
Not a new QTL-*calling* method, not a genotype/individual-level data host, not a GWAS catalog. We
*re-serve and harmonize* published summary-level QTL data and make it findable.
