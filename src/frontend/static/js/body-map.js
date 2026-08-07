// Home page body map: GTEx-style leader-line labels over the real EBI Expression Atlas
// anatomogram SVG (ONE figure — see content/body_map.py's docstring for which and why; it used to
// inline male + female side by side, hence `roots` still being a list). Each organ is an invisible
// hit-region path/use whose only child is <title id="name">name</title> — the friendly name lives
// on the nested <title>, not the parent. So this tags each title's PARENT element with
// data-region="<name>" itself, client side, on load. From there, it builds ONE clickable text
// label per region that actually has DB data (an anatomical shape alone isn't an obvious click
// target — see the last conversation this shipped from), positions each label in a left/right
// column based on its organ's on-screen position, and draws a straight connector line from label
// to organ. Clicking a label (or its organ, kept working too) renders that region's datasets as a
// table on the side.
// Data comes from window.BODY_MAP_REGIONS / window.BODY_MAP_LABELS, injected by the partial.
(() => {
  const container = document.getElementById("body-map-container");
  const leaderSvg = document.getElementById("body-map-leaders");
  const leftCol = document.getElementById("body-map-labels-left");
  const rightCol = document.getElementById("body-map-labels-right");
  const tooltip = document.getElementById("body-map-tooltip");
  const panelTitle = document.getElementById("body-map-panel-title");
  const panelTable = document.getElementById("body-map-panel-table");
  const panelTbody = document.getElementById("body-map-panel-tbody");
  const panelEmpty = document.getElementById("body-map-panel-empty");
  if (!container) return;

  // A list of one today — kept plural so adding the second figure back is a one-line change.
  const roots = [document.querySelector("#body-map-figure svg")].filter(Boolean);
  if (!roots.length) return;

  const regions = window.BODY_MAP_REGIONS || {};
  const labels = window.BODY_MAP_LABELS || {};
  const labelFor = (name) => labels[name] || name;

  // ── tag organs, collect one representative element per region that has data ────────────────
  const targetByRegion = {};
  // The female SVG calls it "bladder", the male one "urinary_bladder" (confirmed: the only such
  // alias between the two files), and REGION_KEYWORDS targets the latter — normalize so the
  // rendered figure tags it as the region content/body_map.py expects either way.
  const ORGAN_ALIASES = { bladder: "urinary_bladder" };

  roots.forEach((svg) => {
    svg.querySelectorAll("title").forEach((title) => {
      // Multi-word organs use spaces in the <title>'s text ("adipose tissue") but underscores in
      // its own id attribute ("adipose_tissue", matching REGION_KEYWORDS' targets) — confirmed
      // consistent (once normalized) across every organ in both files except two auto-generated
      // ids ("title120" etc, whose *text* — e.g. "hippocampus" — is the meaningful one). So:
      // normalize the text, don't trust the id.
      let name = title.textContent.trim().toLowerCase().replace(/\s+/g, "_");
      name = ORGAN_ALIASES[name] || name;
      const el = title.parentElement;
      if (!el || !name) return;
      el.dataset.region = name;
      el.removeAttribute("style"); // was fill:none;stroke:none — let our own CSS take over
      el.classList.add("body-region");
      const available = (regions[name] || []).length > 0;
      el.classList.add(available ? "available" : "unavailable");
      if (available && !(name in targetByRegion)) targetByRegion[name] = el;
    });
  });

  const regionNames = Object.keys(targetByRegion);

  // ── side table: click a label or organ -> that region's datasets ───────────────────────────
  // Highlight the chosen region's label/organ and render its datasets into the side table.
  function selectRegion(name) {
    document.querySelectorAll(".body-map-label.active, .body-region.active").forEach((el) => {
      el.classList.remove("active");
    });
    document.querySelector(`.body-map-label[data-region="${CSS.escape(name)}"]`)?.classList.add(
      "active"
    );
    targetByRegion[name]?.classList.add("active");

    panelTitle.textContent = labelFor(name);
    const entries = regions[name] || [];
    if (!entries.length) {
      panelTable.hidden = true;
      panelEmpty.hidden = false;
      return;
    }
    panelEmpty.hidden = true;
    panelTbody.innerHTML = entries
      .map((e) => {
        // Level 2 when present, else level 1 — same rule as Dataset.tissue (see
        // connectpostgres.py's datasets()); not the two joined.
        const context = e.level_2 || e.level_1;
        const href = "/browser?locus_mode=gene&datasets=qtl:" + e.qtl_list_id;
        return `<tr>
          <td>${e.dataset_label}</td>
          <td class="muted"><a href="${href}">${context}</a></td>
        </tr>`;
      })
      .join("");
    panelTable.hidden = false;
  }

  if (!regionNames.length) return; // nothing with data to label — leave the diagram inert

  // ── build one label per region, in the column its organ is visually closer to ──────────────
  const labelElByRegion = {};
  // Create one clickable text label per available region, sorted top-to-bottom and placed in
  // the left or right column depending on which side its organ sits on screen.
  function buildLabels() {
    leftCol.innerHTML = "";
    rightCol.innerHTML = "";
    const containerRect = container.getBoundingClientRect();
    const midX = containerRect.left + containerRect.width / 2;
    const sorted = regionNames.slice().sort((a, b) => {
      return (
        targetByRegion[a].getBoundingClientRect().top -
        targetByRegion[b].getBoundingClientRect().top
      );
    });
    for (const name of sorted) {
      const rect = targetByRegion[name].getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const col = cx < midX ? leftCol : rightCol;
      const label = document.createElement("div");
      label.className = "body-map-label";
      label.textContent = labelFor(name);
      label.dataset.region = name;
      label.addEventListener("click", () => selectRegion(name));
      label.addEventListener("mouseenter", () => setHover(name, true));
      label.addEventListener("mouseleave", () => setHover(name, false));
      col.appendChild(label);
      labelElByRegion[name] = label;
    }
  }

  // Toggle the hover highlight on both a region's label and its organ shape together.
  function setHover(name, on) {
    labelElByRegion[name]?.classList.toggle("hover", on);
    targetByRegion[name]?.classList.toggle("hover", on);
  }

  // ── connector lines, recomputed on resize since label/organ pixel positions can shift ──────
  // Draw one straight <line> per labeled region, from its label to its organ's center.
  function drawLines() {
    const containerRect = container.getBoundingClientRect();
    leaderSvg.setAttribute("width", String(containerRect.width));
    leaderSvg.setAttribute("height", String(containerRect.height));
    leaderSvg.setAttribute("viewBox", `0 0 ${containerRect.width} ${containerRect.height}`);
    leaderSvg.innerHTML = "";
    for (const name of regionNames) {
      const label = labelElByRegion[name];
      const target = targetByRegion[name];
      if (!label || !target) continue;
      const labelRect = label.getBoundingClientRect();
      const targetRect = target.getBoundingClientRect();
      const isLeft = labelRect.left < containerRect.left + containerRect.width / 2;
      const x1 = (isLeft ? labelRect.right : labelRect.left) - containerRect.left;
      const y1 = labelRect.top + labelRect.height / 2 - containerRect.top;
      const x2 = targetRect.left + targetRect.width / 2 - containerRect.left;
      const y2 = targetRect.top + targetRect.height / 2 - containerRect.top;
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", String(x1));
      line.setAttribute("y1", String(y1));
      line.setAttribute("x2", String(x2));
      line.setAttribute("y2", String(y2));
      line.dataset.region = name;
      leaderSvg.appendChild(line);
    }
  }

  buildLabels();
  drawLines();

  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(drawLines, 150);
  });

  // ── direct hover/click on the organ shapes themselves still works too ──────────────────────
  roots.forEach((svg) => {
    svg.querySelectorAll(".body-region.available").forEach((el) => {
      const name = el.dataset.region;
      el.addEventListener("mousemove", (ev) => {
        tooltip.textContent = labelFor(name);
        tooltip.style.left = ev.clientX + 14 + "px";
        tooltip.style.top = ev.clientY + 14 + "px";
        tooltip.hidden = false;
      });
      el.addEventListener("mouseleave", () => {
        tooltip.hidden = true;
      });
      el.addEventListener("click", () => selectRegion(name));
    });
  });
})();
