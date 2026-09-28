// "Download SVG" button for a Plotly locuszoom panel — used by both plot flavours:
// the gene page's single regional plot (static/js/regional-plot.js) and the Data Browser's
// stacked GWAS/QTL panels (static/js/multi-track-plot.js).
//
// attach() wraps the graph div in a positioned container and pins the button to the panel's
// bottom-right corner (CSS: .plot-dl-wrap / .plot-dl-btn in static/css/base.css). The button is
// NOT appended into the graph div itself: Plotly owns that node's children and Plotly.purge()
// (which multi-track-plot.js calls on every re-render) would take the button with it.
//
// Why the export goes through an offscreen clone: both plots draw points with `scattergl`
// (WebGL) for speed, and Plotly's SVG export of a gl trace embeds the point layer as a
// base64 raster image — an .svg file whose points aren't actually vector. The clone re-plots the
// same data/layout with the traces swapped to plain `scatter`, so every point comes out as a real
// vector mark that scales and is editable in Illustrator/Inkscape. If anything in that path
// fails we fall back to Plotly's own downloadImage (raster-in-SVG, but still a file).
const PlotDownload = (() => {
  // Make a string safe to use as a filename component.
  function slug(text) {
    return String(text).replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 80);
  }

  // Hand the browser a data: URL to save under `filename`.
  function saveDataUrl(url, filename) {
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  // Re-plot this panel offscreen as non-WebGL traces and export that as vector SVG.
  async function toVectorSvg(plotDiv, width, height) {
    const ghost = document.createElement("div");
    ghost.style.cssText = `position:absolute;left:-10000px;top:0;width:${width}px;height:${height}px`;
    document.body.appendChild(ghost);
    try {
      const data = plotDiv.data.map((t) => (t.type === "scattergl" ? { ...t, type: "scatter" } : t));
      const layout = { ...plotDiv.layout, width, height };
      await Plotly.newPlot(ghost, data, layout, { staticPlot: true });
      return await Plotly.toImage(ghost, { format: "svg", width, height });
    } finally {
      try {
        Plotly.purge(ghost);
      } catch {
        /* never initialized — nothing to purge */
      }
      ghost.remove();
    }
  }

  // Export `plotDiv` as an SVG download named after nameFn (a string or a () => string, so
  // callers can name the file from whatever is currently plotted).
  async function download(plotDiv, nameFn, btn) {
    if (!plotDiv || !plotDiv.data) return; // nothing plotted yet (loading / "no data" message)
    const name = slug(typeof nameFn === "function" ? nameFn() : nameFn) || "plot";
    const filename = `locusview_${name}.svg`;
    const width = Math.round(plotDiv.offsetWidth) || 900;
    const height = Math.round(plotDiv.offsetHeight) || 420;
    const label = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Saving…";
    try {
      saveDataUrl(await toVectorSvg(plotDiv, width, height), filename);
    } catch (e) {
      // Vector path failed — still give the user a file (gl layer embedded as a raster image).
      Plotly.downloadImage(plotDiv, { format: "svg", width, height, filename: filename.replace(/\.svg$/, "") });
    } finally {
      btn.disabled = false;
      btn.textContent = label;
    }
  }

  // Pin a "Download SVG" button to the bottom-right of `plotDiv`'s panel. Safe to call once per
  // graph div; returns the button.
  function attach(plotDiv, nameFn) {
    const wrap = document.createElement("div");
    wrap.className = "plot-dl-wrap";
    plotDiv.parentNode.insertBefore(wrap, plotDiv);
    wrap.appendChild(plotDiv);

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "plot-dl-btn";
    btn.title = "Download this plot as SVG";
    btn.textContent = "↓ SVG";
    btn.addEventListener("click", () => download(plotDiv, nameFn, btn));
    wrap.appendChild(btn);
    return btn;
  }

  return { attach, download };
})();
