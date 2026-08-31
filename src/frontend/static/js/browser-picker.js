// Data Browser sidebar: cascading QTL (Dataset -> Source project ID -> QTL type -> Context) / GWAS (Dataset ->
// Accession+Trait) picker. Every level is fetched live from routers/browser.py's
// /api/browser/... catalog endpoints as the user narrows each box down, so a newly-ingested
// dataset shows up without a reload — deliberately not a flat pre-rendered list (doesn't scale
// visually as more datasets get ingested). Exposes BrowserPicker.selectedDatasets() ->
// ["qtl:1","gwas:2",...] for browser.js's Run Query, and BrowserPicker.ready — a Promise that
// resolves once the default/preselected rows have finished their async population — so a Run
// Query click that lands before that finishes doesn't read an empty selection (browser.js awaits
// it first).
const BrowserPicker = (() => {
  let resolveReady;
  const ready = new Promise((resolve) => {
    resolveReady = resolve;
  });


  // GET a URL and parse it as JSON, returning [] on any failure (network error or non-2xx).
  async function fetchJSON(url) {
    try {
      const resp = await fetch(url);
      return resp.ok ? await resp.json() : [];
    } catch {
      return [];
    }
  }

  // Replace a <select>'s options with `items` (each either a plain value or a {id, label}
  // object), optionally prefixed with a disabled/blank placeholder option.
  function fillSelect(select, items, placeholder) {
    select.innerHTML = "";
    if (placeholder !== undefined) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = placeholder;
      select.appendChild(opt);
    }
    for (const item of items) {
      const opt = document.createElement("option");
      if (item && typeof item === "object") {
        opt.value = item.id;
        opt.textContent = item.label;
      } else {
        opt.value = item;
        opt.textContent = item;
      }
      select.appendChild(opt);
    }
  }

  // Mark a <select>'s options selected/deselected to match a set of string values.
  function selectValues(select, values) {
    const wanted = new Set((values || []).map(String));
    for (const opt of select.options) opt.selected = wanted.has(opt.value);
  }

  // ── QTL row ──────────────────────────────────────────────────────────────

  // Populate one QTL row's source-project dropdown for the chosen dataset and reset descendants.
  async function loadQtlSourceProjects(row, datasetName) {
    const projectSel = row.querySelector('[data-role="source_project_id"]');
    const typeSel = row.querySelector('[data-role="qtl_type"]');
    const contextSel = row.querySelector('[data-role="context"]');
    typeSel.innerHTML = "";
    typeSel.disabled = true;
    contextSel.innerHTML = "";
    contextSel.disabled = true;
    if (!datasetName) {
      fillSelect(projectSel, [], "Source project ID…");
      projectSel.disabled = true;
      return;
    }
    const projects = await fetchJSON(
      `/api/browser/qtl/source-projects?dataset=${encodeURIComponent(datasetName)}`
    );
    // The user may switch Dataset while the previous request is still in flight. Never let the
    // older response repopulate the row for the newly selected dataset.
    if (row.querySelector('[data-role="dataset"]').value !== datasetName) return;
    fillSelect(projectSel, projects, "Source project ID…");
    projectSel.disabled = false;
    // Every currently integrated dataset has one source project. Select that sole value and
    // continue the cascade automatically instead of leaving QTL type/context disabled behind a
    // redundant extra click. The dropdown remains useful once a dataset has multiple projects.
    if (projects.length === 1) {
      projectSel.value = typeof projects[0] === "object" ? projects[0].id : projects[0];
      await loadQtlTypes(row, datasetName, projectSel.value);
    }
  }

  // Populate the QTL-type dropdown for one dataset + source project.
  async function loadQtlTypes(row, datasetName, sourceProjectId) {
    const typeSel = row.querySelector('[data-role="qtl_type"]');
    const contextSel = row.querySelector('[data-role="context"]');
    contextSel.innerHTML = "";
    contextSel.disabled = true;
    if (!sourceProjectId) {
      fillSelect(typeSel, [], "QTL type…");
      typeSel.disabled = true;
      return;
    }
    const types = await fetchJSON(
      `/api/browser/qtl/types?dataset=${encodeURIComponent(datasetName)}` +
        `&source_project_id=${encodeURIComponent(sourceProjectId)}`
    );
    if (
      row.querySelector('[data-role="dataset"]').value !== datasetName ||
      row.querySelector('[data-role="source_project_id"]').value !== sourceProjectId
    ) return;
    fillSelect(typeSel, types, "QTL type…");
    typeSel.disabled = false;
  }

  // Populate one QTL row's "Context" multi-select for the chosen dataset + type.
  async function loadQtlContexts(row, datasetName, sourceProjectId, qtlType) {
    const contextSel = row.querySelector('[data-role="context"]');
    if (!qtlType) {
      contextSel.innerHTML = "";
      contextSel.disabled = true;
      return;
    }
    const contexts = await fetchJSON(
      `/api/browser/qtl/contexts?dataset=${encodeURIComponent(datasetName)}` +
        `&source_project_id=${encodeURIComponent(sourceProjectId)}` +
        `&qtl_type=${encodeURIComponent(qtlType)}`
    );
    fillSelect(contextSel, contexts);
    contextSel.disabled = false;
  }

  // Bind one QTL row's cascading dropdown listeners and its remove button.
  function wireQtlRow(row) {
    const datasetSel = row.querySelector('[data-role="dataset"]');
    const projectSel = row.querySelector('[data-role="source_project_id"]');
    const typeSel = row.querySelector('[data-role="qtl_type"]');
    datasetSel.addEventListener("change", () => loadQtlSourceProjects(row, datasetSel.value));
    projectSel.addEventListener("change", () =>
      loadQtlTypes(row, datasetSel.value, projectSel.value)
    );
    typeSel.addEventListener("change", () =>
      loadQtlContexts(row, datasetSel.value, projectSel.value, typeSel.value)
    );
    row.querySelector(".picker-row-remove").addEventListener("click", () => row.remove());
  }

  // Append a new QTL picker row from its <template>, wire it, and optionally hydrate it from a
  // deep-linked preset ({dataset, qtl_type, context_ids}).
  async function addQtlRow(preset) {
    const template = document.getElementById("qtl-row-template");
    const container = document.getElementById("qtl-rows");
    if (!template || !container) return;
    const row = template.content.firstElementChild.cloneNode(true);
    container.appendChild(row);
    wireQtlRow(row);

    const datasetSel = row.querySelector('[data-role="dataset"]');
    const datasets = await fetchJSON("/api/browser/qtl/datasets");
    fillSelect(datasetSel, datasets, "Dataset…");

    if (preset) {
      datasetSel.value = preset.dataset;
      await loadQtlSourceProjects(row, preset.dataset);
      const projectSel = row.querySelector('[data-role="source_project_id"]');
      projectSel.value = preset.source_project_id;
      await loadQtlTypes(row, preset.dataset, preset.source_project_id);
      row.querySelector('[data-role="qtl_type"]').value = preset.qtl_type;
      await loadQtlContexts(row, preset.dataset, preset.source_project_id, preset.qtl_type);
      selectValues(row.querySelector('[data-role="context"]'), preset.context_ids);
    }
  }

  // ── GWAS row ─────────────────────────────────────────────────────────────

  // Populate one GWAS row's accession+trait multi-select for the chosen dataset.
  async function loadGwasOptions(row, datasetName) {
    const optSel = row.querySelector('[data-role="option"]');
    if (!datasetName) {
      optSel.innerHTML = "";
      optSel.disabled = true;
      return;
    }
    const opts = await fetchJSON(`/api/browser/gwas/options?dataset=${encodeURIComponent(datasetName)}`);
    fillSelect(optSel, opts);
    optSel.disabled = false;
  }

  // Bind one GWAS row's dataset-change listener and its remove button.
  function wireGwasRow(row) {
    const datasetSel = row.querySelector('[data-role="dataset"]');
    datasetSel.addEventListener("change", () => loadGwasOptions(row, datasetSel.value));
    row.querySelector(".picker-row-remove").addEventListener("click", () => row.remove());
  }

  // Append a new GWAS picker row from its <template>, wire it, and optionally hydrate it from a
  // deep-linked preset ({dataset, option_ids}).
  async function addGwasRow(preset) {
    const template = document.getElementById("gwas-row-template");
    const container = document.getElementById("gwas-rows");
    if (!template || !container) return;
    const row = template.content.firstElementChild.cloneNode(true);
    container.appendChild(row);
    wireGwasRow(row);

    const datasetSel = row.querySelector('[data-role="dataset"]');
    const datasets = await fetchJSON("/api/browser/gwas/datasets");
    fillSelect(datasetSel, datasets, "Dataset…");

    if (preset) {
      datasetSel.value = preset.dataset;
      await loadGwasOptions(row, preset.dataset);
      selectValues(row.querySelector('[data-role="option"]'), preset.option_ids);
    }
  }

  // ── collection + init ────────────────────────────────────────────────────

  // Collect every checked QTL context / GWAS option across all rows as "qtl:<id>"/"gwas:<id>"
  // keys — what browser.js's Run Query sends to /api/locus/multi-track.
  function selectedDatasets() {
    const out = [];
    document.querySelectorAll('#qtl-rows [data-role="context"]').forEach((sel) => {
      for (const opt of sel.selectedOptions) out.push(`qtl:${opt.value}`);
    });
    document.querySelectorAll('#gwas-rows [data-role="option"]').forEach((sel) => {
      for (const opt of sel.selectedOptions) out.push(`gwas:${opt.value}`);
    });
    return out;
  }

  // Wire the "+ Add" buttons and populate the default/preselected rows, then resolve `ready`.
  async function init() {
    const qtlAddBtn = document.getElementById("qtl-add-row");
    const gwasAddBtn = document.getElementById("gwas-add-row");
    if (qtlAddBtn) qtlAddBtn.addEventListener("click", () => addQtlRow());
    if (gwasAddBtn) gwasAddBtn.addEventListener("click", () => addGwasRow());

    const qtlPresets = window.PRESELECTED_QTL_ROWS || [];
    const gwasPresets = window.PRESELECTED_GWAS_ROWS || [];

    if (document.getElementById("qtl-rows")) {
      if (qtlPresets.length) {
        for (const preset of qtlPresets) await addQtlRow(preset);
      } else {
        await addQtlRow();
      }
    }
    if (document.getElementById("gwas-rows")) {
      if (gwasPresets.length) {
        for (const preset of gwasPresets) await addGwasRow(preset);
      } else {
        await addGwasRow();
      }
    }
    resolveReady();
  }

  document.addEventListener("DOMContentLoaded", init);

  return { selectedDatasets, ready };
})();
