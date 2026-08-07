"""Tissue-name -> body-region mapping for the Home page's interactive body map, and the real EBI
Expression Atlas anatomogram SVG it's drawn on.

**Assets**: ``static/img/anatomogram-{male,female}.svg``, fetched from
``ebi-gene-expression-group/anatomogram`` (the library EBI's own Expression Atlas uses) — CC0
(public domain, sourced from Wikimedia's "Human body features"; see each file's own embedded
metadata).

**Only the female figure is rendered** (one silhouette, 2026-08, by request — it used to draw both
side by side). That's the one that covers the data: of the six regions the current catalog maps to,
``blood`` (``Whole_Blood``) and ``artery`` (``Artery_Tibial``) exist *only* in the female SVG, so
the male figure alone would silently drop them. It's also the broader file overall — 81 drawn
organs vs the male's 72, including the immune cell types (``t_cell``/``b_cell``/``monocyte``/
``platelet``/``natural_killer_cell``) and ``retina``.
**Trade-off**: organs drawn only in the male SVG have no shape now — ``testis``, ``prostate_gland``,
``spinal_cord``, ``penis``, ``epididymis``, ``seminal_vesicle``, ``vas_deferens``. Nothing in the
catalog maps to them today, but a future ``Testis``/``Prostate`` dataset would list under "other"
instead of getting a labeled leader line. :data:`MALE_SVG` is still loaded and the file still
ships, so restoring the second figure is a template + ``body-map.js`` roots change, nothing more.

**Region ids**: each interactive organ in the SVG is an invisible hit-region path whose *only*
child is ``<title id="liver">liver</title>`` — the friendly name lives on the nested ``<title>``,
not the parent. ``static/js/body-map.js`` handles this client-side: on load it tags each title's
parent element with ``data-region="<name>"`` from the title's own text content, then everything
below (hover/click) just queries ``[data-region="..."]``. ``REGION_KEYWORDS`` below maps GTEx-style
tissue-name substrings to those same organ names.

Matched by case-insensitive substring against ``QtlContextEntry.level_1`` (see
``routers/home.py``) — first keyword found wins, so more specific patterns are listed before more
general ones that could otherwise shadow them. An unmatched tissue still shows up (grouped under
"other"), just not highlighted on the silhouette. Extend as more contexts get ingested.
"""

from __future__ import annotations

import re
from pathlib import Path

# Both source SVGs bake in a small clickable badge linking to EBI's own licence page
# (id="a4174", <title>-less, just a green CC-style icon near the figure's feet) — meaningless
# inside this app (CC0 doesn't require attribution anyway), stripped once here at load time.
_EBI_LICENCE_BADGE = re.compile(
    r'<a\s+transform="[^"]*"\s+id="a4174"\s+'
    r'xlink:href="https://www\.ebi\.ac\.uk/gxa/licence\.html">.*?</a>',
    re.DOTALL,
)


def _load_svg(filename: str) -> str:
    """Read one anatomogram SVG off disk and strip the EBI licence badge from it.

    static/ lives in the sibling frontend/ folder now, not inside this package — see
    web.py's _STATIC_DIR comment for why the relative walk-up is safe here.
    """
    path = Path(__file__).resolve().parents[3] / "frontend" / "static" / "img" / filename
    return _EBI_LICENCE_BADGE.sub("", path.read_text(encoding="utf-8"))


# FEMALE_SVG is the one the Home page draws (see module docstring for why). MALE_SVG is kept
# loaded so restoring the two-figure layout stays a one-line template change.
MALE_SVG = _load_svg("anatomogram-male.svg")
FEMALE_SVG = _load_svg("anatomogram-female.svg")
ANATOMOGRAM_SVG = FEMALE_SVG  # what routers/home.py actually renders

REGION_KEYWORDS: list[tuple[str, str]] = [
    # Blood / immune
    # Plain "blood", not "whole_blood": the catalog uses BOTH spellings for the same organ —
    # GTEx rows say "Whole_Blood", CIMA/Tenk10k caQTL rows just "Blood" — and "whole_blood" (the
    # old keyword) isn't a substring of "Blood", so those six caQTL datasets silently fell through
    # to "other" and vanished from the body map. "blood" matches both. Safe to broaden: nothing
    # below contains "blood" as a substring, so it shadows nothing.
    ("blood", "blood"),
    ("ebv-transformed_lymphocytes", "lymph_node"),
    ("lymph", "lymph_node"),
    ("mono", "leukocyte"),  # e.g. GTEx "Monocyte", CIMA's "cMono_CD14"
    ("bone_marrow", "bone_marrow"),
    # Adipose / adrenal
    ("adipose", "adipose_tissue"),
    ("adrenal", "adrenal_gland"),
    # Artery
    ("artery_coronary", "coronary_artery"),
    ("artery_tibial", "artery"),  # "artery" (generic) is distinct from "aorta" in the SVG
    ("artery", "aorta"),
    # Bladder — "Bladder" (GTEx) / "urinary_bladder" (male SVG) / "bladder" (female SVG, aliased
    # to "urinary_bladder" client-side — see body-map.js's ORGAN_ALIASES) are all the same organ.
    ("bladder", "urinary_bladder"),
    # Kidney (before the generic "cortex" brain keyword below, which "kidney_cortex" would
    # otherwise match first as a substring)
    ("kidney_cortex", "renal_cortex"),
    ("kidney", "kidney"),
    # Brain (specific sub-regions before the generic "brain")
    ("anterior_cingulate", "cerebral_cortex"),
    ("frontal_cortex", "frontal_cortex"),
    ("cerebellar_hemisphere", "cerebellar_hemisphere"),
    ("cerebellum", "cerebellum"),
    ("cortex", "cerebral_cortex"),
    ("hippocampus", "hippocampus"),
    ("amygdala", "amygdala"),
    ("substantia_nigra", "brain"),
    ("putamen", "brain"),
    ("caudate", "brain"),
    ("nucleus_accumbens", "brain"),
    ("hypothalamus", "brain"),
    ("spinal_cord", "spinal_cord"),
    ("pituitary", "pituitary_gland"),
    ("brain", "brain"),
    ("nerve", "nerve"),
    # Breast
    ("breast", "breast"),
    # Cervix
    ("ectocervix", "ectocervix"),
    ("endocervix", "uterine_cervix"),
    ("cervix", "uterine_cervix"),
    # Digestive tract
    ("colon", "colon"),
    ("esophagus_gastroesophageal", "gastroesophageal_junction"),
    ("esophagus", "esophagus"),
    ("stomach", "stomach"),
    ("small_intestine", "small_intestine"),
    ("duodenum", "duodenum"),
    ("ileum", "ileum"),
    ("rectum", "rectum"),
    ("appendix", "appendix"),
    # Fallopian tube
    ("fallopian", "fallopian_tube"),
    # Skin / fibroblasts
    ("fibroblast", "skin"),
    ("skin", "skin"),
    # Heart
    ("heart_atrial_appendage", "atrial_appendage"),
    ("heart_left_ventricle", "left_ventricle"),
    ("heart", "heart"),
    # Liver / lung
    ("liver", "liver"),
    ("lung", "lung"),
    # Salivary gland
    ("parotid", "parotid_gland"),
    ("salivary_gland", "salivary_gland"),
    # Muscle
    ("muscle", "skeletal_muscle"),
    # Reproductive
    ("ovary", "ovary"),
    ("prostate", "prostate_gland"),
    ("testis", "testis"),
    ("uterus", "uterus"),
    ("vagina", "vagina"),
    # Other glands / organs
    ("pancreas", "pancreas"),
    ("spleen", "spleen"),
    ("thyroid", "thyroid_gland"),
]

# Distinct organ names REGION_KEYWORDS can produce -> a readable display label, auto-derived
# (underscores -> spaces, capitalized) rather than hand-maintained.
REGIONS: dict[str, str] = {
    organ: organ.replace("_", " ").capitalize() for _, organ in REGION_KEYWORDS
}


def region_for_tissue(level_1_context: str) -> str | None:
    """An anatomogram organ name for a tissue label, or ``None`` if unmapped (still listed under
    "other", just not highlighted on either silhouette)."""
    lowered = level_1_context.lower()
    for keyword, region in REGION_KEYWORDS:
        if keyword in lowered:
            return region
    return None
