// Locus View regional plot: LD-colored scatter (Plotly), click-to-repin a lead variant.
// Shared by the gene page and the Data Browser via displays/partials/_regional_plot.html.
// Reads its data feed from the #lv-regional container's data-endpoint-base attribute, so the
// same script serves both "/api/gene/{key}/regional" (gene page) and "/api/locus/regional"
// (Data Browser, region/variant modes) — see routers/locus.py.
const LocusPlot = (() => {
  const LD_BINS = [[0.2, "#463699"], [0.4, "#26BCE1"], [0.6, "#6EFE68"], [0.8, "#F8C32A"], [1.01, "#DB3D11"]];
  const LEAD_COLOR = "#f97316", TRACK_COLOR = "#2563eb", NO_RSID_COLOR = "#AAAAAA";

  // Map an r² value (or lack of one) to its LocusZoom-style dot color.
  // The 1000G panel stores only r² >= 0.2, so a missing r² means "below the floor", not "no data".
  function r2color(r2, isLead, hasRsid) {
    if (isLead) return LEAD_COLOR;
    if (!hasRsid) return NO_RSID_COLOR;
    if (r2 === null || r2 === undefined) return LD_BINS[0][1];
    for (const [upper, color] of LD_BINS) { if (r2 < upper) return color; }
    return "#DB3D11";
  }
  const r2label = (r2) => (r2 === null || r2 === undefined) ? "< 0.2" : r2.toFixed(2);

  // Append params to a URL, using "&" if it already has a "?" or "?" otherwise.
  function withQuery(base, params) {
    const sep = base.includes("?") ? "&" : "?";
    return base + sep + params;
  }

  // (Re-)draw the plot from state.data.variants and (re)bind the click-to-recolor handler once.
  function render(state) {
    const { plotDiv, data } = state;
    const v = data.variants;
    const hasLd = Boolean(data.reference_present_in_1000g);
    state.ldContextEls.forEach((el) => { el.hidden = !hasLd; });
    state.noLdContextEls.forEach((el) => { el.hidden = hasLd; });
    const traces = [{
      type: "scattergl", mode: "markers",
      x: v.map(d => d.position / 1e6), y: v.map(d => d.log_pvalue),
      customdata: v.map(d => [d.rs_id, d.pvalue, hasLd ? r2label(d.r2) : "", d.gene_id, d.position]),
      marker: {
        color: v.map(d => d.color || (d.is_lead ? LEAD_COLOR : TRACK_COLOR)),
        size: v.map(d => d.is_lead ? 12 : 7),
        symbol: v.map(d => d.is_lead ? "diamond" : "circle"), line: { width: 0 },
      },
      hovertemplate: "rs%{customdata[0]} · chr" + data.region.chrom +
        ":%{customdata[4]:,}<br>p=%{customdata[1]:.2e}" +
        (hasLd ? " · r²=%{customdata[2]}" : "") + "<extra></extra>",
    }];
    const layout = {
      margin: { t: 8, r: 8, b: 44, l: 56 }, hovermode: "closest",
      xaxis: { title: "chr" + data.region.chrom + " (Mb)", gridcolor: "#f1f5f9", zeroline: false },
      yaxis: { title: "-log10(P)", gridcolor: "#f1f5f9", zeroline: false },
      plot_bgcolor: "#ffffff", paper_bgcolor: "#ffffff", font: { color: "#334155", size: 12 },
      shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 7.301, y1: 7.301,
                 line: { color: "#94a3b8", width: 1, dash: "dot" } }],
    };
    Plotly.react(plotDiv, traces, layout, { responsive: true, displayModeBar: false });
    if (!state.clickBound) {
      plotDiv.on("plotly_click", (ev) => onClick(state, ev));
      state.clickBound = true;
    }
  }

  // Click-to-recolor: fetch LD to the clicked point's rsID and re-render with it as the new lead.
  async function onClick(state, ev) {
    const rs = ev.points[0].customdata[0];
    if (rs === null) return;
    const u = "/api/ld?chrom=" + state.data.region.chrom + "&lead=" + rs +
      "&population=" + encodeURIComponent(state.popSel.value);
    const resp = await fetch(u);
    if (!resp.ok) return;
    const payload = await resp.json();
    const hasLd = Boolean(payload.reference_present_in_1000g);
    const m = hasLd ? payload.r2 : null;
    state.data.reference_present_in_1000g = hasLd;
    // Re-point the lead. If this lookup has no usable LD pairs, preserve all points and render
    // them in the plain association colors instead of implying that every point has low r².
    state.data.variants.forEach(d => {
      const hasRsid = d.rs_id !== null && d.rs_id !== undefined;
      const isLead = hasRsid && String(d.rs_id) === String(rs);
      const key = String(d.rs_id);
      d.is_lead = isLead;
      d.r2 = hasLd ? (isLead ? 1.0 : (hasRsid && key in m ? m[key] : null)) : null;
      d.color = hasLd ? r2color(d.r2, isLead, hasRsid) : null;
    });
    render(state);
  }

  // Fetch this state's endpoint for the current tissue/population selection and render it.
  async function load(state) {
    state.plotDiv.style.opacity = "0.4";
    const u = withQuery(
      state.endpointBase,
      "tissue=" + state.tissueSel.value + "&population=" + encodeURIComponent(state.popSel.value)
    );
    try {
      const resp = await fetch(u);
      if (!resp.ok) throw new Error("no data");
      state.data = await resp.json();
      render(state);
    } catch (e) {
      // Purge before wiping the node: Plotly leaves gd.data/gd.layout on the div otherwise, and
      // the "↓ SVG" button (plot-download.js) would happily export the *previous* tissue's plot.
      try {
        Plotly.purge(state.plotDiv);
      } catch {
        /* nothing plotted yet — nothing to purge */
      }
      state.plotDiv.innerHTML = "<p class='muted'>No plot data for this tissue.</p>";
    }
    state.plotDiv.style.opacity = "1";
  }

  // Wire up one regional-plot container: bind the tissue/population selects and load the
  // default tissue's data if one's already selected.
  function init(container) {
    const state = {
      endpointBase: container.dataset.endpointBase,
      plotDiv: container.querySelector("#lv-plot"),
      tissueSel: container.querySelector("#lv-tissue"),
      popSel: container.querySelector("#lv-population"),
      ldContextEls: container.querySelectorAll("[data-ld-context]"),
      noLdContextEls: container.querySelectorAll("[data-no-ld-context]"),
      data: null,
      clickBound: false,
    };
    // Bottom-right "↓ SVG" export for this panel (static/js/plot-download.js); named from the
    // region + tissue currently plotted, so consecutive downloads don't overwrite each other.
    PlotDownload.attach(state.plotDiv, () => {
      const r = state.data && state.data.region;
      const tissue = state.tissueSel.selectedOptions[0]?.text || "";
      return r ? `chr${r.chrom}_${r.start}-${r.end}_${tissue}` : tissue;
    });
    state.tissueSel.addEventListener("change", () => load(state));
    state.popSel.addEventListener("change", () => load(state));
    if (state.tissueSel.options.length) load(state);
    return state;
  }

  return { init, load };
})();
