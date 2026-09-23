// Data Browser: stacked Plotly panels, all sharing the same genomic-position x-axis range so
// signal peaks can be compared visually.
//
// GWAS panels render via render(), which is async: it fetches LD for each track's "pivot" —
// bestByPvalue(variants, true), the best (lowest-p) point that actually HAS an rsID, which isn't
// always the track's single most significant point (that true top hit may itself lack an rsID —
// common, since only a fraction of positions resolve one; falling back to the next-best
// rsID-bearing point means the panel still gets LD-colored instead of silently getting none) —
// before drawing, so GWAS points are LD-colored whenever ANY variant nearby has an rsID
// (GwasAssociation is enriched via connectpostgres.py's gwas_associations_in_region — see its
// docstring for the join/perf notes). Points without an rsID remain visible in gray.
//
// QTL results DON'T auto-plot — a genomic window can legitimately match many different
// phenotypes at once (see routers/locus.py's _group_by_phenotype), so instead of one blob of
// every matched variant, renderQtlTable() shows a checkbox row per matched phenotype; checking
// one calls renderQtlPanels(), which filters that track's already-fetched variants down to just
// that phenotype_id (no second fetch — every variant's phenotype_id came back in the original
// /api/locus/multi-track response) and plots it as its own panel, LD-fetched around the same kind
// of rsID-bearing pivot point as GWAS. It fetches /api/ld (same endpoint the single-track regional
// plot's click-to-recolor uses) and LD-colors every point that also has an rsID, mirroring
// regional-plot.js's r2color scheme exactly — a point whose rsID has no r² on record with the
// pivot still shows, in the "< 0.2 / not in panel" color (the 1000G table only stores pairs
// >= 0.2, see ld_r2's docstring). Points without an rsID remain visible in gray. The user can
// freely check/uncheck rows and the panels update to match.
// gwasUsedLd/qtlUsedLd track each source's own last render so the shared LD legend
// (#db-qtl-ld-legend) stays visible if *either* is currently showing LD colors.
//
// Click-to-pin only works on QTL points (GWAS shards have no gene concept to resolve a comparison
// from — see routers/comparison.py) — clicking one calls back with {chrom, position} so the
// caller (browser.js) can fetch the variant-comparison partial.
const MultiTrackPlot = (() => {
  const TRACK_COLOR = { qtl: "#2563eb", gwas: "#7c3aed" };
  const LEAD_COLOR = "#f97316";
  // Variant-mode searches mark the searched variant with a pink diamond drawn over the lead/LD
  // colors (see queryVariantMarker()).
  const QUERY_COLOR = "#ec4899";
  // Every locuszoom marker (SNP points, lead diamonds, searched-variant diamond) is drawn at 1.3x
  // its base size below, keeping their relative sizes.
  const MARKER_SCALE = 1.3;
  const LD_BINS = [[0.2, "#463699"], [0.4, "#26BCE1"], [0.6, "#6EFE68"], [0.8, "#F8C32A"], [1.01, "#DB3D11"]];
  const LD_NO_RSID_COLOR = "#AAAAAA";
  let gwasUsedLd = false;
  let qtlUsedLd = false;

  // Show the shared LD legend if either GWAS or QTL is currently displaying LD colors.
  function updateLegend(legendEl) {
    if (legendEl) legendEl.hidden = !(gwasUsedLd || qtlUsedLd);
  }

  // Points without an rsID remain visible in gray because they cannot be looked up in the LD panel.
  function r2Color(r2, isLead, hasRsid = true) {
    if (isLead) return LEAD_COLOR;
    if (!hasRsid) return LD_NO_RSID_COLOR;
    if (r2 === null || r2 === undefined) return LD_BINS[0][1];
    for (const [upper, color] of LD_BINS) {
      if (r2 < upper) return color;
    }
    return LD_BINS[LD_BINS.length - 1][1];
  }
  const r2Label = (r2) => (r2 === null || r2 === undefined ? "< 0.2" : r2.toFixed(2));

  // The best (lowest-p) variant in the list, optionally restricted to ones with an rsID. Used to
  // find the true statistical lead (requireRsid: false — the fallback marker when no LD is
  // available at all) and the LD-fetch/coloring pivot (requireRsid: true — see render()'s comment
  // for why this isn't simply "the single most significant point").
  function bestByPvalue(variants, requireRsid) {
    let best = null;
    for (const v of variants) {
      if (requireRsid && (v.rs_id === null || v.rs_id === undefined)) continue;
      if (v.pvalue != null && (!best || best.pvalue == null || v.pvalue < best.pvalue)) best = v;
    }
    return best;
  }

  // Turn a track's key ("qtl:1", "gwas:2:ENSG...") into a DOM-safe element id.
  function panelId(key) {
    return "track-plot-" + key.replace(/[^a-zA-Z0-9_-]/g, "-");
  }

  // scattergl panels each hold their own WebGL context; browsers cap how many a page can have
  // open at once (commonly ~16, sometimes fewer) and silently blank out an existing one past that
  // cap (axes/gridlines are SVG and keep rendering fine — only the WebGL point layer goes empty,
  // which is exactly what a leaked-context panel looks like). Every render()/renderQtlPanels()
  // call below replaces its container's panels wholesale (e.g. each time a phenotype checkbox is
  // toggled) — Plotly.purge() alone is not reliably enough to free a scattergl panel's context
  // (a known Plotly.js limitation: regl, its WebGL layer, doesn't always release the context
  // synchronously), so contexts leaked across repeated toggles until some other panel (often GWAS,
  // created earliest) went blank even though this was already calling Plotly.purge() before every
  // wipe. Force it: after purging, explicitly lose each canvas's WebGL context via the standard
  // WEBGL_lose_context extension, so it's actually released before the DOM node is removed.
  function purgePanels(container) {
    container.querySelectorAll(".track-panel-plot").forEach((el) => {
      const canvases = [...el.querySelectorAll("canvas")];
      try {
        Plotly.purge(el);
      } catch {
        /* not an initialized plot (e.g. still showing "Loading…") — nothing to purge */
      }
      for (const canvas of canvases) {
        const gl = canvas.getContext("webgl2") || canvas.getContext("webgl");
        const ext = gl && gl.getExtension("WEBGL_lose_context");
        if (ext) ext.loseContext();
      }
    });
  }

  // The searched variant's plotted point(s) in this panel as an extra pink-diamond trace, or — when
  // this dataset has no association at that position — a pink dotted vertical line at it instead,
  // so the searched position is still visible. An rsID search keeps only the points carrying that
  // rsID when any do (a position can hold several alleles). Returns {traces, shapes}.
  function queryVariantMarker(v, region, queryVariant, customdata) {
    if (!queryVariant) return { traces: [], shapes: [] };
    let hits = v.map((d, i) => i).filter((i) => v[i].position === queryVariant.position);
    if (queryVariant.rs_id != null) {
      const sameRsid = hits.filter((i) => v[i].rs_id === queryVariant.rs_id);
      if (sameRsid.length) hits = sameRsid;
    }
    const name = queryVariant.rs_id != null
      ? "rs" + queryVariant.rs_id
      : `chr${region.chrom}:${queryVariant.position.toLocaleString()}`;
    if (!hits.length) {
      const x = queryVariant.position / 1e6;
      return {
        traces: [],
        shapes: [{ type: "line", yref: "paper", x0: x, x1: x, y0: 0, y1: 1, line: { color: QUERY_COLOR, width: 1.5, dash: "dot" } }],
      };
    }
    return {
      traces: [{
        type: "scattergl",
        mode: "markers",
        x: hits.map((i) => v[i].position / 1e6),
        y: hits.map((i) => v[i].log_pvalue),
        customdata: hits.map((i) => customdata[i]),
        marker: { color: QUERY_COLOR, size: 14 * MARKER_SCALE, symbol: "diamond", opacity: 1, line: { color: "#9d174d", width: 1.5 } },
        hovertemplate:
          `<b>Searched variant ${name}</b><br>chr${region.chrom}:%{customdata[0]:,}<br>p=%{customdata[1]:.2e}` +
          "<extra></extra>",
      }],
      shapes: [],
    };
  }

  // Draw one Plotly scattergl panel for a single track (GWAS, or one QTL phenotype), appended
  // into `container`, wiring click-to-pin for QTL points. `queryVariant` ({chrom, position,
  // rs_id}, variant-mode searches only) adds the pink searched-variant marker.
  function renderTrack(container, track, region, onPointClick, queryVariant) {
    const panel = document.createElement("div");
    panel.className = "track-panel";
    const status = track.status?.message || (!track.variants?.length ? "No association variants were returned for this dataset." : "");
    panel.innerHTML = `
      <div class="track-panel-header">
        <span class="track-panel-kind track-panel-kind-${track.kind}">${track.kind.toUpperCase()}</span>
        <span class="track-panel-label">${track.label}</span>
        ${track.kind === "qtl" ? "" : '<span class="muted mono track-panel-n">click-to-compare unavailable for GWAS</span>'}
      </div>
      ${track.notice ? `<p class="muted track-panel-status">${track.notice}</p>` : ""}
      ${status ? `<p class="muted track-panel-status">${status}</p>` : `<div id="${panelId(track.key)}" class="track-panel-plot"></div>`}
    `;
    container.appendChild(panel);
    if (status) return;

    const plotDiv = panel.querySelector(".track-panel-plot");
    const fallbackColor = TRACK_COLOR[track.kind] || "#64748b";
    const v = track.variants;
    const hasAnyRsid = v.some((d) => d.rs_id !== null && d.rs_id !== undefined);
    const hasAnyLd = v.some((d) => d.color);
    const customdata = v.map((d) => [
      d.position,
      d.pvalue,
      d.is_lead,
      d.rs_id ? "rs" + d.rs_id : "",
      d.color ? r2Label(d.r2) : "",
    ]);
    const trace = {
      type: "scattergl",
      mode: "markers",
      x: v.map((d) => d.position / 1e6),
      y: v.map((d) => d.log_pvalue),
      customdata,
      marker: {
        // d.color (set once LD is fetched) wins when present; otherwise the plain fixed-color/
        // lead scheme, matching today's behaviour when LD isn't available.
        color: v.map((d) => d.color || (d.is_lead ? LEAD_COLOR : fallbackColor)),
        size: v.map((d) => (d.is_lead ? 11 : 6) * MARKER_SCALE),
        symbol: v.map((d) => (d.is_lead ? "diamond" : "circle")),
        opacity: 0.75,
        line: { width: 0 },
      },
      hovertemplate:
        "chr" + region.chrom + ":%{customdata[0]:,}<br>p=%{customdata[1]:.2e}" +
        (hasAnyRsid ? "<br>%{customdata[3]}" : "") +
        (hasAnyLd ? "<br>r<sup>2</sup>=%{customdata[4]}" : "") +
        "<extra></extra>",
    };
    const queryMarker = queryVariantMarker(v, region, queryVariant, customdata);
    const layout = {
      margin: { t: 6, r: 8, b: 40, l: 50 },
      hovermode: "closest",
      xaxis: {
        range: [region.start / 1e6, region.end / 1e6],
        title: { text: "chr" + region.chrom + " (Mb)", font: { size: 11 } },
        gridcolor: "#f1f5f9",
        zeroline: false,
      },
      yaxis: { title: "-log10(P)", gridcolor: "#f1f5f9", zeroline: false },
      plot_bgcolor: "#ffffff",
      paper_bgcolor: "#ffffff",
      font: { color: "#334155", size: 11 },
      shapes: [
        { type: "line", xref: "paper", x0: 0, x1: 1, y0: 7.301, y1: 7.301, line: { color: "#94a3b8", width: 1, dash: "dot" } },
        ...queryMarker.shapes,
      ],
      showlegend: false,
    };
    Plotly.newPlot(plotDiv, [trace, ...queryMarker.traces], layout, { responsive: true, displayModeBar: false });
    // Bottom-right "↓ SVG" export for this panel (static/js/plot-download.js). Attached after
    // newPlot so the export always sees a plotted div; it wraps plotDiv rather than living inside
    // it, so purgePanels()'s Plotly.purge() can't strip the button.
    PlotDownload.attach(plotDiv, () => `${track.kind}_chr${region.chrom}_${track.label}`);

    if (track.kind === "qtl" && onPointClick) {
      plotDiv.on("plotly_click", (ev) => {
        const [position] = ev.points[0].customdata;
        onPointClick(region.chrom, position);
      });
    }
  }

  // Render every GWAS track immediately, LD-colored where possible (see module comment above).
  async function render(container, data, onPointClick, legendEl, population) {
    purgePanels(container);
    container.innerHTML = "";
    gwasUsedLd = false;
    if (!data.tracks.length) {
      updateLegend(legendEl);
      container.innerHTML = "<p class='muted'>No datasets selected.</p>";
      return;
    }
    container.innerHTML = "<p class='muted'>Loading&hellip;</p>";

    const panels = await Promise.all(
      data.tracks.map(async (track) => {
        // The LD "pivot" is the best (lowest-p) point that actually HAS an rsID — not necessarily
        // the track's single most significant point. If the true top hit lacks an rsID (common —
        // only a fraction of positions resolve one), it cannot be LD-fetched, so we use the next
        // best rsID-bearing point while retaining every point in the plot.
        const pivot = bestByPvalue(track.variants, true);
        const ld = pivot ? await fetchLd(data.region.chrom, pivot.rs_id, population) : null;
        if (!ld?.available) {
          return {
            ...track,
            notice: pivot
              ? (ld?.error || "LD coloring is unavailable; all variants are shown without LD colors.")
              : "No variant in this dataset has an rsID; all variants are shown in gray.",
          };
        }
        gwasUsedLd = true;
        // Keep every plotted point. Variants without an rsID cannot be looked up and are shown in
        // gray; rsID-bearing points absent from the pair table are below the panel's 0.2 floor.
        const variants = track.variants.map((v) => {
          const isPivot = v === pivot;
          const hasRsid = v.rs_id !== null && v.rs_id !== undefined;
          const key = String(v.rs_id);
          const r2 = isPivot ? 1.0 : key in ld.r2 ? ld.r2[key] : null;
          return { ...v, is_lead: isPivot, r2, color: r2Color(r2, isPivot, hasRsid) };
        });
        return { ...track, variants };
      })
    );

    container.innerHTML = "";
    panels.forEach((track) => renderTrack(container, track, data.region, onPointClick, data.query_variant));
    updateLegend(legendEl);
  }

  // ── QTL results table: one checkbox row per (track x phenotype) ────────────────────────────
  // Render the sortable "QTL results by phenotype" checkbox table and wire each row's checkbox
  // to call back with the full currently-checked set.
  function renderQtlTable(container, tracks, onSelectionChange) {
    const rows = [];
    for (const track of tracks) {
      if (track.kind !== "qtl") continue;
      for (const p of track.phenotypes || []) rows.push({ track, p });
    }
    const statusRows = tracks
      .filter((track) => track.kind === "qtl" && track.status?.message)
      .map((track) => `<p class="muted track-status-line"><strong>${track.label}:</strong> ${track.status.message}</p>`)
      .join("");
    if (!rows.length) {
      container.innerHTML = statusRows || "<p class='muted track-status-line'>No QTL phenotype was found for the requested locus.</p>";
      onSelectionChange([]);
      return;
    }
    rows.sort((a, b) => {
      if (a.p.lead_pvalue == null) return 1;
      if (b.p.lead_pvalue == null) return -1;
      return a.p.lead_pvalue - b.p.lead_pvalue;
    });

    // Read every currently-checked row's {track, p} pair.
    function collectSelected() {
      return [...container.querySelectorAll(".qtl-pheno-checkbox:checked")].map(
        (el) => rows[Number(el.dataset.index)]
      );
    }

    const body = rows
      .map(
        ({ track, p }, i) => `
        <tr>
          <td class="qtl-tight"><input type="checkbox" class="qtl-pheno-checkbox" data-index="${i}"></td>
          <td class="qtl-tight">${track.dataset}</td>
          <td class="qtl-tight">${track.source_project_id || ""}</td>
          <td class="qtl-tight"><span class="badge badge-blue">${track.qtl_type}</span></td>
          <td class="qtl-tight mono muted">${track.population}</td>
          <td class="qtl-wide"><div>${track.context}</div></td>
          <td class="qtl-wide qtl-pheno mono"><div>${p.phenotype_id || ""}</div></td>
        </tr>`
      )
      .join("");
    container.innerHTML = `
      ${statusRows}
      <div class="card" style="padding:0;overflow:hidden">
        <div style="padding:14px 18px;border-bottom:1px solid var(--line);font-size:13px;font-weight:600;color:var(--ink)">
          QTL results by phenotype
          <span class="muted" style="font-weight:400;font-size:11px">${rows.length >= 50 ? "showing the first 50 phenotype IDs — " : ""}check a row to load and plot its locuszoom</span>
        </div>
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th class="qtl-tight"></th><th class="qtl-tight">Dataset</th><th class="qtl-tight">Source ID</th>
                <th class="qtl-tight">QTL type</th><th class="qtl-tight">Population</th><th class="qtl-wide">Context</th>
                <th class="qtl-wide qtl-pheno">Phenotype ID</th>
              </tr>
            </thead>
            <tbody>${body}</tbody>
          </table>
        </div>
      </div>
    `;
    container.querySelectorAll(".qtl-pheno-checkbox").forEach((cb) => {
      cb.addEventListener("change", () => onSelectionChange(collectSelected()));
    });
    onSelectionChange([]); // nothing checked yet — caller clears any stale panels
  }

  // ── QTL locuszoom panels for the currently-checked phenotype rows, LD-colored when possible ─
  // Fetch r² of every variant to one lead rsID from /api/ld, or null when the lookup fails or
  // returns no usable LD pairs.
  async function fetchLd(chrom, leadRsId, population) {
    try {
      const resp = await fetch(
        `/api/ld?chrom=${encodeURIComponent(chrom)}&lead=${leadRsId}&population=${encodeURIComponent(population)}`
      );
      if (!resp.ok) return null;
      const payload = await resp.json();
      return { available: true, r2: payload.r2 || {} };
    } catch {
      return { available: false, error: "LD lookup failed; all variants are shown without LD colors." };
    }
  }

  // Initial QTL searches return phenotype IDs only. Fetch one selected phenotype's bounded,
  // enriched variant set on demand so large datasets never cross the wire before selection.
  async function fetchPhenotypeVariants(datasetId, phenotypeId, chrom, start, end) {
    try {
      const resp = await fetch(
        `/api/locus/qtl-phenotype?dataset_id=${datasetId}&phenotype_id=${encodeURIComponent(phenotypeId)}` +
          `&chrom=${encodeURIComponent(chrom)}&start=${start}&end=${end}`
      );
      const payload = await resp.json();
      if (!resp.ok) return { variants: [], error: payload.error || "Association request failed." };
      return { variants: payload.variants || [], error: payload.status?.message || null };
    } catch {
      return { variants: [], error: "Association request failed; please try again." };
    }
  }

  // Render one locuszoom panel per checked phenotype row, LD-colored where possible (see module
  // comment above).
  async function renderQtlPanels(container, region, selections, onPointClick, legendEl, population, queryVariant) {
    qtlUsedLd = false;
    purgePanels(container);
    if (!selections.length) {
      container.innerHTML = "";
      updateLegend(legendEl);
      return;
    }
    container.innerHTML = "<p class='muted'>Loading&hellip;</p>";

    const panels = await Promise.all(
      selections.map(async ({ track, p }) => {
        let variants = track.variants.filter((v) => v.phenotype_id === p.phenotype_id);
        let fetchError = null;
        const hasAnyRsid = variants.some((v) => v.rs_id !== null && v.rs_id !== undefined);
        if (!hasAnyRsid && track.dataset_id != null) {
          const fetched = await fetchPhenotypeVariants(
            track.dataset_id, p.phenotype_id, region.chrom, region.start, region.end
          );
          variants = fetched.variants;
          fetchError = fetched.error;
        }
        if (!variants.length) {
          return {
            key: `${track.key}:${p.phenotype_id}`,
            kind: "qtl",
            label: `${track.label} — ${p.phenotype_id}`,
            variants: [],
            status: { code: "no_data", message: fetchError || "No association variants were found in the displayed window." },
          };
        }
        // is_lead on the source track is scoped to the WHOLE track's lead (across every matched
        // phenotype), not this one phenotype's — recompute it within just this filtered subset.
        // The LD pivot (best p-value AMONG rsID-havers) may differ from the true statistical
        // lead when that top hit itself lacks an rsID — see render()'s comment for why falling
        // back to it, rather than giving up on LD, matters.
        const pivot = bestByPvalue(variants, true);
        const ld = pivot ? await fetchLd(region.chrom, pivot.rs_id, population) : null;
        if (ld?.available) qtlUsedLd = true;
        const effectiveLead = ld?.available ? pivot : bestByPvalue(variants, false);
        const scoped = variants.map((v) => {
          const isLead = v === effectiveLead;
          const hasRsid = v.rs_id !== null && v.rs_id !== undefined;
          const key = String(v.rs_id);
          const r2 = ld?.available ? (isLead ? 1.0 : key in ld.r2 ? ld.r2[key] : null) : null;
          return {
            ...v,
            is_lead: isLead,
            r2,
            color: ld?.available ? r2Color(r2, isLead, hasRsid) : null,
          };
        });
        const notice = !ld?.available
          ? (pivot
            ? (ld?.error || "LD coloring is unavailable; all variants are shown without LD colors.")
            : "No variant in this phenotype has an rsID; all variants are shown in gray.")
          : null;
        return {
          key: `${track.key}:${p.phenotype_id}`,
          kind: "qtl",
          label: `${track.label} — ${p.phenotype_id}`,
          variants: scoped,
          notice,
        };
      })
    );

    container.innerHTML = "";
    panels.forEach((panel) => renderTrack(container, panel, region, onPointClick, queryVariant));
    updateLegend(legendEl);
  }

  return { render, renderQtlTable, renderQtlPanels };
})();
