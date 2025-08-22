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
    graph = await fetch('../data/graph_reduced.json').then(r => { if (!r.ok) throw new Error('graph_reduced.json'); return r.json(); });
  } catch (e) {
    graph = await fetch('../data/graph.json').then(r => { if (!r.ok) throw new Error('graph.json'); return r.json(); });
  }
  async function loadPos(name) {
    try {
      return await fetch(`../data/${name}`).then(r => { if (!r.ok) throw new Error(name); return r.json(); });
    } catch (e) { console.warn(`${name} not found`); return {}; }
  }
  // DEFAULT: DRL precomputed positions; fallback to SMACOF, then disk positions
  let positions = await loadPos('positions_drl.json');
  if (!Object.keys(positions).length) positions = await loadPos('positions_smacof.json');
  if (!Object.keys(positions).length) positions = await loadPos('positions.json');
  return { graph, positions };
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

async function main() {
  try {
    const dataset = await loadDataset();
    const data = dataset.graph.nodes.map(n => ({ index: n.id })) // minimal for filtering
    statusEl.textContent = `Loaded ${dataset.graph.nodes.length} nodes.`;

    function render() {
      const query = searchInput.value.trim().toUpperCase();
      const depth = Number(depthInput.value || 0);
      const includeCoreq = toggleCoreq.checked;
      const subset = filterSubgraph(data, query, depth, includeCoreq);
      // Build from precomputed assets and subset selection
      const allowed = new Set(subset.map(s => s.index));
      const nodes = dataset.graph.nodes.filter(n => allowed.has(n.id)).map(n => ({ data: { id: n.id, label: n.id, color: n.color || '#4f46e5' } }));
      const edges = dataset.graph.edges.filter(e => allowed.has(e.source) && allowed.has(e.target))
        .map(e => ({ data: { id: `${e.source}->${e.target}#${e.kind}`, source: e.source, target: e.target, kind: e.kind } }));

      const cy = cytoscape({
        container: document.getElementById('cy'),
        elements: [...nodes, ...edges],
        wheelSensitivity: 0.2,
      });
      applyStyles(cy, { hideLabels: toggleLabels.checked });
      const layoutMode = layoutSelect.value;
      if (layoutMode === 'preset') {
        // Apply preset positions
        nodes.forEach(n => {
          const p = dataset.positions[n.data.id];
          if (p) cy.$id(n.data.id).position({ x: p.x, y: p.y });
        });
        cy.fit(undefined, 40);
      } else if (layoutMode === 'cose') {
        cy.layout({ name: 'cose', fit: true, animate: false, nodeOverlap: getMinSpacingPx(), nodeRepulsion: 800000 * Number(spreadInput.value || 1.5), idealEdgeLength: 40 * Number(spreadInput.value || 1.5) }).run();
      } else if (layoutMode === 'fcose') {
        cy.layout({ name: 'fcose', quality: 'default', fit: true, animate: false, nodeDimensionsIncludeLabels: true, packComponents: true, nodeSeparation: getMinSpacingPx(), idealEdgeLength: 28 * Number(spreadInput.value || 1.5), nodeRepulsion: 12000 * Number(spreadInput.value || 1.5) }).run();
      } else if (layoutMode === 'cola') {
        cy.layout({ name: 'cola', fit: true, animate: false, avoidOverlap: true, nodeSpacing: function() { return getMinSpacingPx(); }, edgeLength: 24 * Number(spreadInput.value || 1.5) }).run();
      } else if (layoutMode === 'elk') {
        cy.layout({ name: 'elk', fit: true, animate: false, elk: { 'elk.algorithm': 'layered', 'elk.layered.spacing.nodeNodeBetweenLayers': 50 * Number(spreadInput.value || 1.5), 'elk.spacing.nodeNode': 20 * Number(spreadInput.value || 1.5) } }).run();
      } else if (layoutMode === 'fa2') {
        // ForceAtlas2 with LinLog to emphasize communities; strong gravity to avoid border crowding
        cy.layout({ name: 'forceAtlas2',
          animated: false,
          gravity: 1.0,
          strongGravity: true,
          linLogMode: true,
          outboundAttractionDistribution: false,
          barnesHutOptimize: true,
          barnesHutTheta: 1.2,
          scalingRatio: 2.0,
          slowDown: 5,
          edgeWeightInfluence: 1,
        }).run();
      } else {
        runLayout(cy, { spread: Number(spreadInput.value || 1.5) });
      }
      statusEl.textContent = `Showing ${nodes.length} nodes, ${edges.length} edges` + (query ? ` (filter: ${query}, depth ${depth})` : '');
      cy.on('tap', 'node', (evt) => {
        const d = evt.target.data();
        alert(`${d.label}`);
      });
    }

    btnApply.addEventListener('click', render);
    btnReset.addEventListener('click', () => {
      searchInput.value = '';
      depthInput.value = '2';
      toggleCoreq.checked = true;
      layoutSelect.value = 'preset';
      spreadInput.value = '1.5';
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


