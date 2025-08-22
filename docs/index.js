const statusEl = document.getElementById('status');
const searchInput = document.getElementById('searchInput');
const depthInput = document.getElementById('depthInput');
const toggleCoreq = document.getElementById('toggleCoreq');
const btnApply = document.getElementById('btnApply');
const btnReset = document.getElementById('btnReset');
const layoutSelect = document.getElementById('layoutSelect');
const spreadInput = document.getElementById('spreadInput');
const toggleLabels = document.getElementById('toggleLabels');
// Fixed preset: always load positions_drl.json (or smacof/fa2 depending on precompute)

// Keep node visual size and spacing logic in one place
const NODE_SIZE = 6; // px — must match node width/height in applyStyles
function getMinSpacingPx() {
  return Math.max(1, Math.round(NODE_SIZE * 1.5));
}

/**
 * Build nodes and edges from courses_parsed.json
 * - Node id: index (e.g., "CS 225")
 * - Edge: prereq -> course (type: hard or coreq)
 */
function buildGraphElements(dataset, includeCoreq) {
  const elements = { nodes: new Map(), edges: [] };

  function ensureNode(id, name) {
    if (!elements.nodes.has(id)) {
      elements.nodes.set(id, { data: { id, label: id, name: name || id } });
    }
  }

  function addEdge(src, dst, kind) {
    const id = `${src}->${dst}#${kind}`;
    elements.edges.push({ data: { id, source: src, target: dst, kind } });
  }

  function collectCoursesFromAst(ast) {
    const out = [];
    function walk(node) {
      if (!node || typeof node !== 'object') return;
      const op = node.op;
      if (op === 'COURSE' && node.course) {
        out.push(node.course);
      } else if (node.items && Array.isArray(node.items)) {
        node.items.forEach(walk);
      }
    }
    walk(ast);
    return Array.from(new Set(out));
  }

  for (const c of dataset) {
    const idx = c.index;
    ensureNode(idx, c.name);
    const pr = c.prerequisites || {};
    const hard = pr.hard || { op: 'EMPTY' };
    const coreq = pr.coreq_ok || { op: 'EMPTY' };
    const hardCourses = collectCoursesFromAst(hard);
    const coreqCourses = includeCoreq ? collectCoursesFromAst(coreq) : [];
    for (const pre of hardCourses) {
      ensureNode(pre, null);
      addEdge(pre, idx, 'hard');
    }
    for (const pre of coreqCourses) {
      ensureNode(pre, null);
      addEdge(pre, idx, 'coreq');
    }
  }

  return [Array.from(elements.nodes.values()), elements.edges];
}

function applyStyles(cy, opts) {
  const hideLabels = opts?.hideLabels;
  cy.style([
    { selector: 'node', style: { 'label': hideLabels ? '' : 'data(label)', 'font-size': 6, 'width': NODE_SIZE, 'height': NODE_SIZE, 'background-color': 'data(color)', 'color': '#111827' } },
    { selector: 'edge', style: { 'width': 0.24, 'line-color': '#94a3b8', 'curve-style': 'bezier', 'target-arrow-shape': 'triangle', 'arrow-scale': 0.55, 'target-arrow-color': '#94a3b8' } },
    { selector: 'edge[kind = "coreq"]', style: { 'line-style': 'dashed', 'line-color': '#22c55e', 'target-arrow-color': '#22c55e' } },
    // Hover styles
    { selector: '.hover-edge', style: { 'line-color': '#000000', 'target-arrow-color': '#000000', 'z-index': 999 } },
    { selector: '.hover-node', style: { 'border-color': '#000000', 'border-width': 1, 'z-index': 999 } },
    { selector: '.hover-adjacent', style: { 'border-color': '#000000', 'border-width': 1, 'z-index': 998 } },
  ]);
}

function runLayout(cy, opts) {
  const spread = Number(opts?.spread || 1.5);
  const layout = cy.layout({ name: 'dagre', rankDir: 'LR', nodeSep: 30 * spread, edgeSep: 12 * spread, rankSep: 80 * spread, fit: true, animate: false });
  layout.run();
}

async function loadDataset() {
  // Prefer reduced graph if present
  let graph;
  try {
    graph = await fetch('data/graph_reduced.json').then(r => { if (!r.ok) throw new Error('graph_reduced.json'); return r.json(); });
  } catch (e) {
    graph = await fetch('data/graph.json').then(r => { if (!r.ok) throw new Error('graph.json'); return r.json(); });
  }
  // Load parsed courses for node details
  let courses = [];
  try {
    courses = await fetch('data/courses_parsed.json').then(r => { if (!r.ok) throw new Error('courses_parsed.json'); return r.json(); });
  } catch (e) {
    console.warn('courses_parsed.json not found; node details limited');
  }
  async function loadPos(name) {
    try {
      return await fetch(`data/${name}`).then(r => { if (!r.ok) throw new Error(name); return r.json(); });
    } catch (e) { console.warn(`${name} not found`); return {}; }
  }
  // DEFAULT: DRL precomputed positions; fallback to SMACOF, then disk positions
  let positions = await loadPos('positions_drl.json');
  if (!Object.keys(positions).length) positions = await loadPos('positions_smacof.json');
  if (!Object.keys(positions).length) positions = await loadPos('positions.json');
  const courseById = new Map();
  for (const c of courses) if (c && c.index) courseById.set(c.index, c);
  return { graph, positions, courseById };
}

function filterSubgraph(dataset, query, depth, includeCoreq) {
  query = (query || '').trim();
  if (!query) return dataset;
  const isSubject = /^[A-Z]{2,4}$/.test(query);
  const isCourse = /^[A-Z]{2,4}\s+\d/.test(query);
  const wanted = new Set();

  if (isSubject) {
    for (const c of dataset) {
      if (c.index.startsWith(query + ' ')) wanted.add(c.index);
    }
  } else if (isCourse) {
    wanted.add(query.toUpperCase());
  }

  if (!wanted.size) return [];

  // Expand predecessors by depth using edges from AST
  const prereqMap = new Map(); // course -> set(prereq)
  function collectCoursesFromAst(ast) {
    const out = [];
    function walk(node) {
      if (!node || typeof node !== 'object') return;
      const op = node.op;
      if (op === 'COURSE' && node.course) {
        out.push(node.course);
      } else if (node.items && Array.isArray(node.items)) {
        node.items.forEach(walk);
      }
    }
    walk(ast);
    return Array.from(new Set(out));
  }
  for (const c of dataset) {
    const hard = c.prerequisites?.hard || { op: 'EMPTY' };
    const coreq = c.prerequisites?.coreq_ok || { op: 'EMPTY' };
    const pre = new Set(collectCoursesFromAst(hard));
    if (includeCoreq) collectCoursesFromAst(coreq).forEach(x => pre.add(x));
    prereqMap.set(c.index, pre);
  }

  let frontier = new Set(wanted);
  const all = new Set(wanted);
  for (let d = 0; d < depth; d++) {
    const next = new Set();
    for (const course of frontier) {
      const pres = prereqMap.get(course) || new Set();
      pres.forEach(p => { if (!all.has(p)) { all.add(p); next.add(p); } });
    }
    if (!next.size) break;
    frontier = next;
  }
  return dataset.filter(c => all.has(c.index));
}

let focusDetailsRef = null; // assigned inside render()
async function main() {
  try {
    const dataset = await loadDataset();
    const data = dataset.graph.nodes.map(n => ({ index: n.id })) // minimal for filtering
    statusEl.textContent = `Loaded ${dataset.graph.nodes.length} nodes.`;

    // Deterministic subject -> color mapping
    function subjectOf(id) {
      return (id || '').split(' ')[0] || '';
    }
    const fixedPalette = {
      'CS': '#2563eb',
      'MATH': '#059669',
      'STAT': '#ef4444',
      'ECE': '#10b981',
      'PHYS': '#f59e0b',
      'CHEM': '#a855f7',
      'BIOE': '#14b8a6',
      'IS': '#0ea5e9',
      'ACCY': '#ec4899',
      'FIN': '#84cc16',
      'BADM': '#fb923c',
      'ME': '#8b5cf6',
      'AE': '#06b6d4',
      'CSE': '#22c55e',
      'LING': '#f97316',
      'PSYC': '#eab308'
    };
    function hashColorFor(subject) {
      // DJB2 string hash -> HSL
      let h = 5381;
      for (let i = 0; i < subject.length; i++) h = ((h << 5) + h) + subject.charCodeAt(i);
      const hue = ((h >>> 0) % 360);
      return `hsl(${hue}, 70%, 45%)`;
    }
    function colorForSubject(subject) {
      if (fixedPalette[subject]) return fixedPalette[subject];
      return hashColorFor(subject);
    }

    let cyRef = null;
    const suggestionsEl = document.getElementById('searchSuggestions');

    // Hide depth/coreq controls permanently if present
    const di = document.getElementById('depthInput');
    if (di && di.closest) { const lab = di.closest('label'); if (lab) lab.style.display = 'none'; }
    const tc = document.getElementById('toggleCoreq');
    if (tc) { tc.checked = true; if (tc.closest) { const lab = tc.closest('label'); if (lab) lab.style.display = 'none'; } }

    // Hide layout/spread controls and pin defaults
    const layoutSelectEl = document.getElementById('layoutSelect');
    if (layoutSelectEl) { layoutSelectEl.value = 'preset'; const lab = layoutSelectEl.closest('label'); if (lab) lab.style.display = 'none'; }
    const spreadInputEl = document.getElementById('spreadInput');
    if (spreadInputEl) { spreadInputEl.value = '1.5'; const lab = spreadInputEl.closest('label'); if (lab) lab.style.display = 'none'; }

    function render() {
      const query = searchInput.value.trim().toUpperCase();
      const depth = 0; // permanently no depth filtering
      const includeCoreq = true; // permanently include corequisites
      const subset = data;
      // Build from precomputed assets and subset selection
      const nodes = dataset.graph.nodes.map(n => {
        const subj = subjectOf(n.id);
        const color = colorForSubject(subj);
        return { data: { id: n.id, label: n.id, color } };
      });
      const edges = dataset.graph.edges.map(e => ({ data: { id: `${e.source}->${e.target}#${e.kind}`, source: e.source, target: e.target, kind: e.kind } }));

      const cy = cytoscape({
        container: document.getElementById('cy'),
        elements: [...nodes, ...edges],
        wheelSensitivity: 0.2,
      });
      cyRef = cy;
      // Disable node dragging by users
      if (cy.autoungrabify) cy.autoungrabify(true);
      cy.nodes().ungrabify();
      applyStyles(cy, { hideLabels: toggleLabels.checked });
      const layoutMode = 'preset'; // permanently preset
      if (layoutMode === 'preset') {
        // Apply preset positions
        nodes.forEach(n => {
          const p = dataset.positions[n.data.id];
          if (p) cy.$id(n.data.id).position({ x: p.x, y: p.y });
        });
        cy.fit(undefined, 40);
      } else {
        // Fallback (should not hit since we pin preset)
        cy.layout({ name: 'dagre', fit: true, animate: false }).run();
      }
      statusEl.textContent = `Showing ${nodes.length} nodes, ${edges.length} edges`;
      // Hover interactions
      const tooltip = null; // remove floating tooltip; use sidebar only
      const sidebar = document.getElementById('sidebar');
      const sidebarBody = document.getElementById('sidebarBody');
      const btnCloseSidebar = document.getElementById('btnCloseSidebar');
      const btnUnlock = document.getElementById('btnUnlock');
      const sidebarHandle = document.getElementById('sidebarHandle');
      let sidebarLocked = false;

      function clearHover() {
        cy.elements('.hover-edge').removeClass('hover-edge');
        cy.elements('.hover-node').removeClass('hover-node');
        cy.elements('.hover-adjacent').removeClass('hover-adjacent');
        // no tooltip
      }

      function astToText(node, parent) {
        if (!node || typeof node !== 'object') return '';
        if (node.op === 'EMPTY') return '';
        if (node.op === 'COURSE') return node.course ? `<span class="course-link" data-course="${node.course}">${node.course}</span>` : '';
        const parts = (node.items || []).map(n => astToText(n, node.op)).filter(Boolean);
        if (!parts.length) return '';
        const sep = node.op === 'AND' ? ' and ' : ' or ';
        let s = parts.join(sep);
        if (parent && parent !== node.op && parts.length > 1) s = `(${s})`;
        return s;
      }

      function renderCourseDetails(courseId, lock) {
        const course = dataset.courseById ? dataset.courseById.get(courseId) : null;
        const name = (course && course.name) || courseId;
        const desc = (course && course.description) || '';
        let hard = '', coreq = '';
        if (course && course.prerequisites) {
          hard = astToText(course.prerequisites.hard, '');
          coreq = astToText(course.prerequisites.coreq_ok, '');
        }
        if (!hard) hard = 'None';
        const header = `<span class="course-link" data-course="${courseId}">${courseId}</span> — <span class="course-link" data-course="${courseId}">${name}</span>`;
        const coreqBlock = coreq ? `<div style="margin-top:4px;"><span style=\"font-weight:600;\">Coreq-allowed:</span> ${coreq}</div>` : '';
        const html = `<div style="font-weight:600;margin-bottom:6px;">${header}</div>${desc ? `<div style=\"margin-bottom:8px;\">${desc}</div>` : ''}<div><span style=\"font-weight:600;\">Hard prerequisites:</span> ${hard}</div>${coreqBlock}`;
        if (sidebar && sidebarBody) {
          sidebar.classList.add('open');
          sidebarBody.innerHTML = html;
          if (sidebarHandle) sidebarHandle.style.display = 'none';
          if (lock) { sidebarLocked = true; if (btnUnlock) btnUnlock.classList.remove('hidden'); } else { if (btnUnlock) btnUnlock.classList.add('hidden'); }
        }
      }

      // make available to search
      focusDetailsRef = (id) => { renderCourseDetails(id, true); };

      // Delegate clicks for course-link inside sidebar
      if (sidebarBody) {
        sidebarBody.addEventListener('click', (e) => {
          const el = e.target.closest('.course-link');
          if (!el || !cyRef) return;
          const cid = el.getAttribute('data-course');
          if (!cid) return;
          const ele = cyRef.$id(cid);
          if (ele.nonempty()) {
            const prevZoom = cyRef.zoom();
            const MIN_FOCUS_ZOOM = 1.5;
            const targetZoom = prevZoom < MIN_FOCUS_ZOOM ? MIN_FOCUS_ZOOM : prevZoom;
            if (targetZoom !== prevZoom) cyRef.zoom(targetZoom);
            cyRef.animate({ center: { eles: ele } }, { duration: 400 });
            cyRef.elements('.hover-node').removeClass('hover-node');
            ele.addClass('hover-node');
            renderCourseDetails(cid, true);
          }
        });
      }

      // Replace edge text content with clickable course links
      cy.on('mouseover', 'edge', (evt) => {
        clearHover();
        const e = evt.target;
        e.addClass('hover-edge');
        e.source().addClass('hover-adjacent');
        e.target().addClass('hover-adjacent');
        if (!sidebarLocked && sidebar && sidebarBody) {
          const s = e.source().data('id');
          const t = e.target().data('id');
          sidebar.classList.add('open');
          sidebarBody.innerHTML = `From <span class=\"course-link\" data-course=\"${s}\">${s}</span> to <span class=\"course-link\" data-course=\"${t}\">${t}</span>`;
          if (btnUnlock) btnUnlock.classList.add('hidden');
          if (sidebarHandle) sidebarHandle.style.display = 'none';
        }
      });
      cy.on('tap', 'edge', (evt) => {
        const e = evt.target;
        const s = e.source().data('id');
        const t = e.target().data('id');
        if (sidebar && sidebarBody) {
          sidebar.classList.add('open');
          sidebarBody.innerHTML = `From <span class=\"course-link\" data-course=\"${s}\">${s}</span> to <span class=\"course-link\" data-course=\"${t}\">${t}</span>`;
          sidebarLocked = true;
          if (btnUnlock) btnUnlock.classList.remove('hidden');
        }
      });

      if (btnCloseSidebar) btnCloseSidebar.onclick = () => { sidebar.classList.remove('open'); sidebarLocked = false; if (btnUnlock) btnUnlock.classList.add('hidden'); if (sidebarHandle) sidebarHandle.style.display = 'inline-block'; };
      if (btnUnlock) btnUnlock.onclick = () => { sidebarLocked = false; btnUnlock.classList.add('hidden'); };
      cy.on('mouseout', 'edge', clearHover);
      if (sidebarHandle) sidebarHandle.onclick = () => { sidebar.classList.toggle('open'); };
      cy.on('mouseout', 'edge', clearHover);

      cy.on('mouseover', 'node', (evt) => {
        clearHover();
        evt.target.addClass('hover-node');
        if (!sidebarLocked) {
          const id = evt.target.data('id');
          renderCourseDetails(id, false);
        }
      });
      cy.on('tap', 'node', (evt) => { renderCourseDetails(evt.target.data('id'), true); });

      cy.on('tap', (evt) => {
        if (evt.target === cy) clearHover();
      });
    }

    // Focus on a specific course; if zoom is too small, zoom in to a minimum before centering
    function focusOnCourse() {
      if (!cyRef) { render(); setTimeout(focusOnCourse, 50); return; }
      const raw = searchInput.value.trim();
      if (!raw) return;
      let id = raw.toUpperCase().replace(/\s+/g, ' ');
      id = id.includes(' ') ? id : id.replace(/^([A-Z]{2,4})(\d)/, '$1 $2');
      const ele = cyRef.$id(id);
      if (ele.nonempty()) {
        const prevZoom = cyRef.zoom();
        const MIN_FOCUS_ZOOM = 1.5; // stronger minimum zoom when focusing
        const targetZoom = prevZoom < MIN_FOCUS_ZOOM ? MIN_FOCUS_ZOOM : prevZoom;
        if (targetZoom !== prevZoom) cyRef.zoom(targetZoom);
        cyRef.animate({ center: { eles: ele } }, { duration: 400 });
        cyRef.elements('.hover-node').removeClass('hover-node');
        ele.addClass('hover-node');
        if (typeof focusDetailsRef === 'function') focusDetailsRef(id);
      }
    }

    btnApply.addEventListener('click', focusOnCourse);
    // Press Enter in search input acts like Apply
    if (searchInput) {
      searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); focusOnCourse(); }
      });
      // suggestions: top 10 prefix matches on typing
      searchInput.addEventListener('input', () => {
        const q = searchInput.value.trim().toUpperCase();
        if (!q) { suggestionsEl.classList.add('hidden'); suggestionsEl.innerHTML=''; return; }
        const list = [];
        for (const n of dataset.graph.nodes) {
          if (n.id.startsWith(q) || (n.label && n.label.toUpperCase().includes(q))) {
            list.push({ id: n.id, label: n.label || n.id });
            if (list.length >= 10) break;
          }
        }
        if (!list.length) { suggestionsEl.classList.add('hidden'); suggestionsEl.innerHTML=''; return; }
        suggestionsEl.innerHTML = list.map(item => `<div class="suggestions-item" data-id="${item.id}"><strong>${item.id}</strong> — ${item.label}</div>`).join('');
        suggestionsEl.classList.remove('hidden');
      });
      suggestionsEl.addEventListener('click', (e) => {
        const el = e.target.closest('.suggestions-item');
        if (!el) return;
        const id = el.getAttribute('data-id');
        if (!id) return;
        searchInput.value = id;
        suggestionsEl.classList.add('hidden');
        focusOnCourse();
      });
      document.addEventListener('click', (e) => {
        if (!suggestionsEl.contains(e.target) && e.target !== searchInput) {
          suggestionsEl.classList.add('hidden');
        }
      });
    }

    btnReset.addEventListener('click', () => {
      searchInput.value = '';
      // layout preset/spread pinned; no reset needed
      toggleLabels.checked = true;
      render();
    });
    layoutSelect.addEventListener('change', render);
    spreadInput.addEventListener('change', render);
    toggleLabels.addEventListener('change', render);

    render();
  } catch (e) {
    statusEl.textContent = 'Failed to load dataset';
    console.error(e);
  }
}

main();


