// Shared Plotly x axis keeps gene spans, association points and SVG exports aligned.
// Packing follows LocusZoom's approach: measure the label as well as the gene body.
const GeneTrack = (() => {
  const cache = new Map();
  const states = new WeakMap();
  const COMPACT_ROWS = 1;
  const EXPANDED_ROWS = 40;
  const ROW_HEIGHT = 30;
  const escape = (s) => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const measureCanvas = document.createElement('canvas');

  async function load(chrom, start, end) {
    if (end - start > 10000000) return { genes: [], message: 'Zoom to 10 Mb or less to see genes' };
    const key = `${chrom}:${start}-${end}`;
    if (!cache.has(key)) {
      const request = fetch(`/api/locus/genes?chrom=${encodeURIComponent(chrom)}&start=${start}&end=${end}`)
        .then(r => { if (!r.ok) throw new Error('Gene annotation unavailable'); return r.json(); });
      cache.set(key, request);
      request.catch(() => { if (cache.get(key) === request) cache.delete(key); });
      if (cache.size > 40) cache.delete(cache.keys().next().value);
    }
    return cache.get(key);
  }

  function layer(payload, region, width, highlight, expanded, fontFamily) {
    const span = Math.max(1, region.end - region.start);
    const context = measureCanvas.getContext('2d');
    context.font = `italic 11px ${fontFamily}`;
    const px = bp => (bp - region.start) / span * width;
    const bp = pixel => (region.start + pixel / width * span) / 1e6;
    const selected = g => String(g.gene_id) === String(highlight) || g.symbol === highlight;
    const ends = [], placed = [];
    // Keep the query gene visible, followed by named genes, then unnamed Ensembl features.
    const genes = payload.genes.filter(g => g.start <= region.end && g.end >= region.start)
      .sort((a, b) => Number(selected(b)) - Number(selected(a)) ||
        Number(/^ENSG/.test(a.symbol)) - Number(/^ENSG/.test(b.symbol)) || a.start - b.start);
    for (const g of genes) {
      const left = px(Math.max(region.start, g.start));
      const right = px(Math.min(region.end, g.end));
      const direction = g.strand === '+' ? ' →' : g.strand === '-' ? '← ' : '';
      let name = g.symbol;
      while (context.measureText(name + direction).width > width - 12 && name.length > 3) name = name.slice(0, -2) + '…';
      const label = g.strand === '-' ? direction + name : name + direction;
      const labelWidth = context.measureText(label).width + (selected(g) ? 5 : 0);
      const center = Math.max(labelWidth / 2 + 4, Math.min(width - labelWidth / 2 - 4, (left + right) / 2));
      const occupiedStart = Math.min(left, center - labelWidth / 2) - 9;
      const occupiedEnd = Math.max(right, center + labelWidth / 2) + 9;
      let row = ends.findIndex(intervals => intervals.every(([a, b]) => occupiedEnd <= a || occupiedStart >= b));
      if (row < 0) {
        if (ends.length >= (expanded ? EXPANDED_ROWS : COMPACT_ROWS)) continue;
        row = ends.length; ends.push([]);
      }
      ends[row].push([occupiedStart, occupiedEnd]);
      placed.push({ g, left, right, center, row, label, occupiedStart, occupiedEnd });
    }

    const shapes = [];
    const traces = [false, true].flatMap(active => {
      const linesX = [], linesY = [], arrowsX = [], arrowsY = [];
      const labelsX = [], labelsY = [], labels = [], labelHover = [];
      const hoverX = [], hoverY = [], hoverText = [];
      const color = active ? '#2563eb' : '#7b899c';
      const labelColor = active ? '#1d4ed8' : '#475569';
      for (const { g, left, right, center, row, label, occupiedStart, occupiedEnd } of placed) {
        if (selected(g) !== active) continue;
        const y = -row;
        const length = g.end - g.start + 1;
        const size = length >= 1000000 ? `${(length / 1000000).toFixed(2)} Mb` :
          length >= 1000 ? `${(length / 1000).toFixed(1)} kb` : `${length} bp`;
        const strand = g.strand === '+' ? 'Forward strand (+)' : g.strand === '-' ? 'Reverse strand (−)' : 'Strand unknown';
        const hover = `<b>${escape(g.symbol)}</b><br>${escape(g.ensembl_id)}<br>` +
          `chr${escape(g.chrom)}:${g.start.toLocaleString()}–${g.end.toLocaleString()}<br>${strand} · ${size}`;
        linesX.push(bp(left), bp(right), null);
        linesY.push(y, y, null);
        // Terminal ticks mark real gene boundaries; clipped genes continue beyond the viewport.
        for (const edge of [g.start >= region.start ? left : null, g.end <= region.end ? right : null]) {
          if (edge === null) continue;
          linesX.push(bp(edge), bp(edge), null);
          linesY.push(y - 0.10, y + 0.10, null);
        }
        // Fixed pixel spacing keeps direction chevrons quiet at every genomic zoom level.
        if (g.strand === '+' || g.strand === '-') {
          const count = Math.floor((right - left) / 22);
          for (let i = 0; i < count; i++) {
            const x = left + (i + 0.5) * (right - left) / count;
            const back = x + (g.strand === '+' ? -3 : 3);
            arrowsX.push(bp(back), bp(x), bp(back), null);
            arrowsY.push(y - 0.085, y, y + 0.085, null);
          }
        }
        labelsX.push(bp(center)); labelsY.push(y + 0.30);
        labels.push(active ? `<b><i>${escape(label)}</i></b>` : `<i>${escape(label)}</i>`);
        labelHover.push(hover);
        // An invisible hit area makes the whole span easy to inspect without adding visible dots.
        const hitCount = Math.max(1, Math.ceil((right - left) / 14));
        for (let i = 0; i <= hitCount; i++) {
          hoverX.push(bp(left + (right - left) * i / hitCount)); hoverY.push(y); hoverText.push(hover);
        }
        if (active) shapes.push({ type: 'rect', xref: 'x', yref: 'y2',
          x0: bp(Math.max(0, occupiedStart + 3)), x1: bp(Math.min(width, occupiedEnd - 3)),
          y0: y - 0.23, y1: y + 0.69,
          fillcolor: '#eaf2ff', line: { width: 0 }, layer: 'below' });
      }
      const common = { type: 'scatter', yaxis: 'y2', showlegend: false, meta: { geneTrack: true } };
      return [
        { ...common, mode: 'lines', x: linesX, y: linesY, text: [], hoverinfo: 'skip',
          line: { width: active ? 2 : 1.4, color }, connectgaps: false },
        { ...common, mode: 'lines', x: arrowsX, y: arrowsY, text: [], hoverinfo: 'skip',
          line: { width: 1, color }, connectgaps: false },
        { ...common, mode: 'markers', x: hoverX, y: hoverY, text: [], hovertext: hoverText,
          marker: { size: 14, color: 'rgba(0,0,0,0)' }, hoverinfo: 'none',
          hoverlabel: { bgcolor: '#ffffff', bordercolor: '#dbe3ef', font: { color: '#334155', size: 12, family: fontFamily } } },
        { ...common, mode: 'text', x: labelsX, y: labelsY, text: labels, hovertext: labelHover,
          hoverinfo: 'none', textposition: 'middle center',
          textfont: { size: 11, color: labelColor, family: fontFamily },
          hoverlabel: { bgcolor: '#ffffff', bordercolor: '#dbe3ef', font: { color: '#334155', size: 12, family: fontFamily } } },
      ];
    });
    return { traces, shapes, rows: Math.max(1, ends.length), count: placed.length,
      total: genes.length, hidden: genes.length - placed.length, truncated: payload.truncated,
      message: payload.message || (!genes.length ? 'No annotated genes in this region' : '') };
  }

  function controls(state, genes, top) {
    if (!state.button) {
      state.button = document.createElement('button');
      state.button.type = 'button';
      state.button.className = 'gene-track-toggle';
      state.button.addEventListener('click', () => {
        state.expanded = !state.expanded;
        draw(state, state.range);
      });
      // plot-download.js has wrapped the canvas by the time the first request completes.
      const wrapper = state.div.closest('.plot-dl-wrap') || state.div.parentElement;
      wrapper.style.position = 'relative';
      wrapper.appendChild(state.button);
    }
    state.button.hidden = !(genes.hidden || state.expanded) || Boolean(genes.message);
    state.button.textContent = state.expanded ? 'Collapse' : 'Expand';
    state.button.setAttribute('aria-expanded', String(state.expanded));
    state.button.setAttribute('aria-label', state.expanded ? 'Collapse gene track' : 'Expand gene track to show more genes');
    state.button.style.top = `${top}px`;
  }

  async function draw(state, range) {
    const serial = ++state.serial;
    state.range = range;
    if (state.tooltip) state.tooltip.hidden = true;
    const [start, end] = range.map(v => Math.max(0, Math.round(v * 1e6)));
    let payload;
    try { payload = await load(state.region.chrom, start, end); }
    catch { payload = { genes: [], message: 'Gene annotation unavailable · zoom or rerun to retry' }; }
    if (states.get(state.div) !== state || state.serial !== serial || !state.div.isConnected) return;
    const region = { ...state.region, start, end };
    const margin = { ...state.layout.margin, t: 12, b: 44 };
    const width = Math.max(80, state.div.clientWidth - margin.l - margin.r);
    const fontFamily = getComputedStyle(state.div).fontFamily;
    const genes = layer(payload, region, width, state.highlight, state.expanded, fontFamily);
    const associationHeight = state.associationHeight;
    const geneHeight = genes.rows * ROW_HEIGHT + 12;
    const gap = 52;
    const total = associationHeight + gap + geneHeight;
    const headerY = (geneHeight + 24) / total;
    const hasControl = Boolean(genes.hidden || state.expanded) && !genes.message;
    const count = genes.hidden || genes.truncated ? `${genes.count} of ${genes.truncated ? '1,000+' : genes.total}` : `${genes.total}`;
    const detail = genes.message ? ` · ${genes.message}` : (genes.hidden ? ' · zoom in for detail' : '');
    const compactHeader = width < 620;
    const annotations = [
      { xref: 'paper', yref: 'paper', x: 0, y: headerY, xanchor: 'left', yanchor: 'middle',
        text: `<b>Genes</b>  <span style="color:#7b899c">${count}${compactHeader ? '' : detail}</span>`,
        showarrow: false, font: { size: 11, color: '#334155', family: fontFamily } },
      { xref: 'paper', yref: 'paper', x: 1, y: headerY, xanchor: 'right', yanchor: 'middle',
        xshift: hasControl ? -83 : 0,
        text: compactHeader ? 'GRCh38' : 'GENCODE v39 · GRCh38 · gene spans',
        showarrow: false, font: { size: 10, color: '#94a3b8', family: fontFamily } },
    ];
    if (genes.message && compactHeader) annotations.push({ xref: 'paper', yref: 'y2', x: 0.5, y: 0,
      text: genes.message, showarrow: false, font: { size: 10, color: '#94a3b8' } });
    state.div.style.aspectRatio = 'auto';
    state.div.style.height = `${total + margin.t + margin.b}px`;
    const layout = { ...state.layout,
      height: total + margin.t + margin.b,
      margin,
      xaxis: { ...state.layout.xaxis, range, autorange: false, anchor: 'y2',
        showline: true, linecolor: '#e2e8f0', linewidth: 1, ticks: 'outside',
        ticklen: 4, tickcolor: '#cbd5e1', tickfont: { size: 10, color: '#64748b' },
        title: { text: `Chromosome ${region.chrom} (Mb)`, standoff: 12, font: { size: 11, color: '#64748b' } } },
      yaxis: { ...state.layout.yaxis, domain: [(geneHeight + gap) / total, 1] },
      yaxis2: { domain: [0, geneHeight / total], range: [-genes.rows + 0.28, 0.92],
        visible: false, fixedrange: true, anchor: 'x' },
      shapes: [...(state.layout.shapes || []),
        { type: 'rect', xref: 'paper', yref: 'paper', x0: 0, x1: 1, y0: 0, y1: (geneHeight + 40) / total,
          fillcolor: '#f8fafc', line: { width: 0 }, layer: 'below' },
        { type: 'line', xref: 'paper', yref: 'paper', x0: 0, x1: 1,
          y0: (geneHeight + 40) / total, y1: (geneHeight + 40) / total,
          line: { color: '#e2e8f0', width: 1 }, layer: 'below' },
        ...genes.shapes],
      annotations: [...(state.layout.annotations || []), ...annotations],
    };
    // Keep the association y zoom while changing the gene viewport.
    if (state.div.layout?.yaxis?.range) layout.yaxis.range = state.div.layout.yaxis.range;
    await Plotly.react(state.div, [...state.traces, ...genes.traces], layout, state.config);
    if (states.get(state.div) === state && state.serial === serial) {
      controls(state, genes, margin.t + associationHeight + 16);
    }
  }

  async function plot(div, traces, layout, config, region, highlight) {
    const previous = states.get(div);
    if (previous?.listener) div.removeListener('plotly_relayout', previous.listener);
    previous?.button?.remove();
    previous?.tooltip?.remove();
    if (previous?.hoverListener) div.removeListener('plotly_hover', previous.hoverListener);
    if (previous?.unhoverListener) div.removeListener('plotly_unhover', previous.unhoverListener);
    previous?.observer?.disconnect();
    clearTimeout(previous?.timer);
    const range = layout.xaxis.range || [region.start / 1e6, region.end / 1e6];
    const state = { div, traces, layout, config, region, highlight, serial: 0, expanded: previous?.expanded || false,
      associationHeight: Math.max(210, Math.round(Math.min(div.clientWidth, 830) * 3 / 8 - 30)) };
    states.set(div, state);
    // Show associations immediately even if the annotation service is slow.
    await Plotly.react(div, traces, layout, config);
    await draw(state, range);
    if (states.get(div) !== state || !div.isConnected) return;
    state.listener = event => {
      let next;
      if (event['xaxis.autorange']) next = range;
      else if (event['xaxis.range']) next = event['xaxis.range'];
      else if (event['xaxis.range[0]'] !== undefined) next = [event['xaxis.range[0]'], event['xaxis.range[1]']];
      if (!next || next.some(v => !Number.isFinite(Number(v)))) return;
      state.serial++;
      clearTimeout(state.timer);
      state.timer = setTimeout(() => draw(state, next.map(Number)), 180);
    };
    div.on('plotly_relayout', state.listener);
    state.tooltip = document.createElement('div');
    state.tooltip.className = 'gene-track-tooltip';
    state.tooltip.setAttribute('role', 'tooltip');
    state.tooltip.hidden = true;
    const wrapper = div.closest('.plot-dl-wrap') || div.parentElement;
    wrapper.appendChild(state.tooltip);
    state.unhoverListener = () => { state.tooltip.hidden = true; };
    state.hoverListener = event => {
      const point = event.points?.[0];
      if (!point?.data.meta?.geneTrack) { state.unhoverListener(); return; }
      const content = point.data.hovertext?.[point.pointNumber];
      if (!content) return;
      state.tooltip.innerHTML = content;
      state.tooltip.hidden = false;
      const bounds = wrapper.getBoundingClientRect();
      const canvasBounds = div.getBoundingClientRect();
      const x = event.event?.clientX !== undefined ? event.event.clientX - bounds.left :
        canvasBounds.left - bounds.left + point.xaxis.l2p(point.x) + point.xaxis._offset;
      const y = event.event?.clientY !== undefined ? event.event.clientY - bounds.top :
        canvasBounds.top - bounds.top + point.yaxis.l2p(point.y) + point.yaxis._offset;
      state.tooltip.style.left = `${Math.max(6, Math.min(wrapper.clientWidth - state.tooltip.offsetWidth - 6, x - state.tooltip.offsetWidth / 2))}px`;
      state.tooltip.style.top = `${Math.max(6, y - state.tooltip.offsetHeight - 12)}px`;
    };
    div.on('plotly_hover', state.hoverListener);
    div.on('plotly_unhover', state.unhoverListener);
    let lastWidth = div.clientWidth;
    state.observer = new ResizeObserver(() => {
      if (!div.isConnected) { state.observer.disconnect(); return; }
      if (Math.abs(div.clientWidth - lastWidth) < 2) return;
      lastWidth = div.clientWidth;
      state.associationHeight = Math.max(210, Math.round(Math.min(lastWidth, 830) * 3 / 8 - 30));
      state.serial++;
      clearTimeout(state.timer);
      state.timer = setTimeout(() => draw(state, state.range), 100);
    });
    state.observer.observe(div);
  }
  return { plot };
})();
