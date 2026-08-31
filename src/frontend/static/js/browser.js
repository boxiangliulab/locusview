// Data Browser page: sidebar dataset dropdowns + Run Query orchestration.
// Run Query fetches /api/locus/multi-track once; GWAS panels render immediately, QTL results
// render as a checkbox table (see multi-track-plot.js) that the user drives to plot phenotype-
// specific locuszoom panels. Click-to-pin on a QTL panel point drives the variant comparison
// table (routers/comparison.py) against /browser/partials/variant-stats.
(() => {
  const $ = (id) => document.getElementById(id);

  const locusToggle = $("db-locus-toggle");
  const runBtn = $("db-run");

  const emptyEl = $("db-empty");
  const plotArea = $("db-plot-area");
  const plotTitle = $("db-plot-title");
  const plotSub = $("db-plot-sub");
  const geneLinks = $("db-gene-links");
  const tracksEl = $("db-tracks");
  const qtlTableEl = $("db-qtl-table-area");
  const qtlPanelsEl = $("db-qtl-panels");
  const qtlLdLegendEl = $("db-qtl-ld-legend");
  const qtlLdPopulationEl = $("db-qtl-ld-population");
  const populationSel = $("db-population");
  const statsArea = $("db-stats-area");
  const errorEl = $("db-error");

  let locusMode = document.querySelector("#db-locus-toggle .active")?.dataset.locusMode || "gene";
  // Set on every successful query so the population-change handler can re-render GWAS panels
  // (which auto-plot, unlike QTL's checkbox-driven ones) without re-fetching /api/locus/multi-track.
  let lastData = null;
  let lastDatasets = [];

  // Click-to-pin handler for a QTL panel point (see multi-track-plot.js) — loads that position's
  // cross-dataset comparison table.
  const onPointClick = (chrom, position) => {
    loadComparison({ chrom, position, datasets: lastDatasets.join(",") });
  };

  // Toggle which button in a button-group (here, the Gene/Region/Variant locus tabs) has the
  // "active" class.
  function setActive(group, attr, value) {
    group.querySelectorAll(".db-toggle-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset[attr] === value);
    });
  }

  // Show only the locus-input box (gene/region/variant) matching the current tab.
  function applyLocusModeVisibility() {
    $("db-locus-gene").hidden = locusMode !== "gene";
    $("db-locus-region").hidden = locusMode !== "region";
    $("db-locus-variant").hidden = locusMode !== "variant";
  }

  locusToggle.addEventListener("click", (ev) => {
    const btn = ev.target.closest(".db-toggle-btn");
    if (!btn) return;
    locusMode = btn.dataset.locusMode;
    setActive(locusToggle, "locusMode", locusMode);
    applyLocusModeVisibility();
  });

  // Read the sidebar picker's currently-checked qtl:<id>/gwas:<id> keys.
  function selectedDatasets() {
    return BrowserPicker.selectedDatasets();
  }

  // ── locus-input parsing (mirrors locusview.search's regexes, client-side) ──

  // Uppercase a chromosome label and map "M" to "MT", matching the backend's own normalization.
  function normChrom(c) {
    c = c.toUpperCase();
    return c === "M" ? "MT" : c;
  }

  // Parse "chr17:7660000-7690000" (or without the "chr" prefix) into {chrom, start, end}.
  function parseRegion(text) {
    const m = /^(?:chr)?([0-9]{1,2}|MT|[XYM]):([0-9]+)-([0-9]+)$/i.exec(text.trim());
    if (!m) return null;
    return { chrom: normChrom(m[1]), start: parseInt(m[2], 10), end: parseInt(m[3], 10) };
  }

  // Parse an rsID ("rs12345") or a "chr17:7670000" position into {rsid} or {chrom, position}.
  function parseVariant(text) {
    const raw = text.trim();
    const rs = /^rs(\d+)$/i.exec(raw);
    if (rs) return { rsid: parseInt(rs[1], 10) };
    const m = /^(?:chr)?([0-9]{1,2}|MT|[XYM]):([0-9]+)$/i.exec(raw);
    if (m) return { chrom: normChrom(m[1]), position: parseInt(m[2], 10) };
    return null;
  }

  // Show the sidebar's error message and hide the plot/comparison areas.
  function showError(msg) {
    errorEl.textContent = msg;
    errorEl.hidden = false;
    emptyEl.hidden = true;
    plotArea.hidden = true;
    statsArea.hidden = true;
  }

  // Read the active locus tab's input box and validate it into /api/locus/multi-track's params,
  // or an {error} to show instead.
  function locusParams() {
    if (locusMode === "gene") {
      const gene = $("db-gene").value.trim();
      if (!gene) return { error: "Enter an Ensembl gene id, e.g. ENSG00000141510." };
      return { locus_mode: "gene", gene, label: gene };
    }
    if (locusMode === "region") {
      const parsed = parseRegion($("db-region").value);
      if (!parsed) return { error: "Region must look like chr17:7660000-7690000." };
      return { locus_mode: "region", ...parsed, label: `chr${parsed.chrom}:${parsed.start}-${parsed.end}` };
    }
    const parsed = parseVariant($("db-variant").value);
    if (!parsed) return { error: "Variant must be an rsID (rs...) or chr17:7670000." };
    return {
      locus_mode: "variant",
      ...parsed,
      label: parsed.rsid !== undefined ? `rs${parsed.rsid}` : `chr${parsed.chrom}:${parsed.position}`,
    };
  }

  // Run Query: fetch /api/locus/multi-track for the current locus + selected datasets, then
  // render GWAS panels immediately and the QTL phenotype checkbox table.
  async function runLocusView() {
    // A click landing before the picker's default row finishes its async population would
    // otherwise read an empty selection — see browser-picker.js's docstring.
    await BrowserPicker.ready;
    const p = locusParams();
    if (p.error) return showError(p.error);
    const datasets = selectedDatasets();
    if (!datasets.length) return showError("Check at least one QTL or GWAS dataset.");

    const params = new URLSearchParams({ locus_mode: p.locus_mode, datasets: datasets.join(",") });
    if (p.gene) params.set("gene", p.gene);
    if (p.chrom) params.set("chrom", p.chrom);
    if (p.start !== undefined) params.set("start", p.start);
    if (p.end !== undefined) params.set("end", p.end);
    if (p.rsid !== undefined) params.set("rsid", p.rsid);
    if (p.position !== undefined) params.set("position", p.position);

    errorEl.hidden = true;
    emptyEl.hidden = true;
    statsArea.hidden = true;
    plotArea.hidden = false;
    plotTitle.textContent = p.label;
    plotSub.textContent = "";
    geneLinks.hidden = true;
    geneLinks.replaceChildren();
    tracksEl.innerHTML = "<p class='muted'>Loading&hellip;</p>";
    qtlTableEl.innerHTML = "";
    qtlPanelsEl.innerHTML = "";
    qtlLdLegendEl.hidden = true;
    try {
      const resp = await fetch("/api/locus/multi-track?" + params.toString());
      if (!resp.ok) throw new Error((await resp.json()).error || "request failed");
      const data = await resp.json();
      plotSub.textContent = `chr${data.region.chrom}:${data.region.start}-${data.region.end}`;
      if (data.gene?.ensembl_id) {
        // External databases use the stable ENSG id without its annotation-version suffix.
        const ensemblId = data.gene.ensembl_id.split(".", 1)[0];
        const ensemblUrl = `https://www.ensembl.org/id/${encodeURIComponent(ensemblId)}`;
        const titleLink = document.createElement("a");
        titleLink.href = ensemblUrl;
        titleLink.target = "_blank";
        titleLink.rel = "noopener noreferrer";
        titleLink.textContent = data.gene.symbol;
        titleLink.title = `View ${ensemblId} in Ensembl`;
        plotTitle.replaceChildren(titleLink);

        const links = [
          ["Ensembl", ensemblUrl],
          ["Open Targets", `https://platform.opentargets.org/target/${encodeURIComponent(ensemblId)}`],
        ];
        links.forEach(([label, href]) => {
          const link = document.createElement("a");
          link.href = href;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          link.textContent = `${label} ↗`;
          geneLinks.appendChild(link);
        });
        geneLinks.hidden = false;
      }
      lastData = data;
      lastDatasets = datasets;
      if (qtlLdPopulationEl) qtlLdPopulationEl.textContent = populationSel.value;

      // GWAS plots immediately (LD-colored live via its own lead — see multi-track-plot.js's
      // render()). QTL results only show as a checkbox table (a window can legitimately match
      // many different phenotypes at once — see routers/locus.py's _group_by_phenotype); checking
      // a row plots that phenotype's own locuszoom panel below the table, and the user can freely
      // change their selection afterward.
      renderGwas();
      MultiTrackPlot.renderQtlTable(qtlTableEl, data.tracks, (selected) => {
        MultiTrackPlot.renderQtlPanels(
          qtlPanelsEl, data.region, selected, onPointClick, qtlLdLegendEl, populationSel.value
        );
      });
    } catch (e) {
      tracksEl.innerHTML = `<p class="muted">${e.message}</p>`;
    }
  }

  // (Re-)render the GWAS panels from the last fetched data — used both right after Run Query and
  // when the LD population selector changes (GWAS auto-plots, unlike QTL's checkbox-gated panels).
  function renderGwas() {
    if (!lastData) return;
    const gwasTracks = lastData.tracks.filter((t) => t.kind === "gwas");
    if (!gwasTracks.length) {
      tracksEl.innerHTML = "";
      return;
    }
    MultiTrackPlot.render(
      tracksEl, { ...lastData, tracks: gwasTracks }, onPointClick, qtlLdLegendEl, populationSel.value
    );
  }

  // Changing population re-renders whatever's currently on screen: GWAS panels re-render in
  // place (they auto-plot, no checkbox gating), and re-dispatching a checked QTL row's checkbox
  // reuses renderQtlTable's own "change" listener (which recomputes the full checked set, not
  // just the one dispatched) rather than duplicating that logic here.
  populationSel.addEventListener("change", () => {
    if (qtlLdPopulationEl) qtlLdPopulationEl.textContent = populationSel.value;
    renderGwas();
    const checked = qtlTableEl.querySelector(".qtl-pheno-checkbox:checked");
    if (checked) checked.dispatchEvent(new Event("change"));
  });

  // Fetch and render the cross-dataset variant-comparison partial for one (chrom, position).
  async function loadComparison(extra) {
    const params = new URLSearchParams(extra);
    errorEl.hidden = true;
    emptyEl.hidden = true;
    statsArea.hidden = false;
    statsArea.innerHTML = "<p class='muted'>Loading&hellip;</p>";
    try {
      const resp = await fetch("/browser/partials/variant-stats?" + params.toString());
      if (!resp.ok) throw new Error(await resp.text());
      statsArea.innerHTML = await resp.text();
    } catch (e) {
      statsArea.innerHTML = "<p class='muted'>No comparison data available.</p>";
    }
  }

  runBtn.addEventListener("click", () => {
    runLocusView();
  });

  applyLocusModeVisibility();
})();
