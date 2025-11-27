const EMBEDDED_DATA = {{FLAMEGRAPH_DATA}};

// Global string table for resolving string indices
let stringTable = [];
let originalData = null;
let currentThreadFilter = 'all';

// New heat palette colors (matches CSS variables)
const heatColors = [
  "#0d4a6f",  // heat-1: Coldest (<1%)
  "#1a6b8c",  // heat-2: Cold (1-3%)
  "#2d8a9e",  // heat-3: Cool (3-6%)
  "#4aa89e",  // heat-4: Medium (6-12%)
  "#7ec488",  // heat-5: Warm (12-18%)
  "#c4de6a",  // heat-6: Hot (18-35%)
  "#f4d44d",  // heat-7: Very hot (35-60%)
  "#ff6b35",  // heat-8: Hottest (>=60%)
];

// Function to resolve string indices to actual strings
function resolveString(index) {
  if (typeof index === 'number' && index >= 0 && index < stringTable.length) {
    return stringTable[index];
  }
  return String(index);
}

// Function to recursively resolve all string indices in flamegraph data
function resolveStringIndices(node) {
  if (!node) return node;

  const resolved = { ...node };

  if (typeof resolved.name === 'number') {
    resolved.name = resolveString(resolved.name);
  }
  if (typeof resolved.filename === 'number') {
    resolved.filename = resolveString(resolved.filename);
  }
  if (typeof resolved.funcname === 'number') {
    resolved.funcname = resolveString(resolved.funcname);
  }

  if (Array.isArray(resolved.source)) {
    resolved.source = resolved.source.map(index =>
      typeof index === 'number' ? resolveString(index) : index
    );
  }

  if (Array.isArray(resolved.children)) {
    resolved.children = resolved.children.map(child => resolveStringIndices(child));
  }

  return resolved;
}

// ============================================================================
// Theme & UI Controls
// ============================================================================

function toggleTheme() {
  const html = document.documentElement;
  const current = html.getAttribute('data-theme') || 'dark';
  const next = current === 'dark' ? 'light' : 'dark';
  html.setAttribute('data-theme', next);
  localStorage.setItem('flamegraph-theme', next);

  // Update theme button icon
  const btn = document.getElementById('theme-btn');
  if (btn) {
    btn.innerHTML = next === 'dark' ? '&#9788;' : '&#9790;';  // sun or moon
  }
}

function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  if (sidebar) {
    sidebar.classList.toggle('collapsed');
    localStorage.setItem('flamegraph-sidebar', sidebar.classList.contains('collapsed') ? 'collapsed' : 'expanded');

    // Resize chart after sidebar animation
    setTimeout(() => {
      if (window.flamegraphChart && window.flamegraphData) {
        const chartArea = document.querySelector('.chart-area');
        if (chartArea) {
          window.flamegraphChart.width(chartArea.clientWidth - 32);
          d3.select("#chart").datum(window.flamegraphData).call(window.flamegraphChart);
        }
      }
    }, 300);
  }
}

function restoreUIState() {
  // Restore theme
  const savedTheme = localStorage.getItem('flamegraph-theme');
  if (savedTheme) {
    document.documentElement.setAttribute('data-theme', savedTheme);
    const btn = document.getElementById('theme-btn');
    if (btn) {
      btn.innerHTML = savedTheme === 'dark' ? '&#9788;' : '&#9790;';
    }
  }

  // Restore sidebar state
  const savedSidebar = localStorage.getItem('flamegraph-sidebar');
  if (savedSidebar === 'collapsed') {
    const sidebar = document.getElementById('sidebar');
    if (sidebar) sidebar.classList.add('collapsed');
  }
}

// ============================================================================
// Tooltip
// ============================================================================

function createTooltip(data) {
  const tooltip = flamegraph.tooltip.defaultFlamegraphTooltip();

  tooltip.show = function (d, element) {
    if (!this._tooltip) {
      this._tooltip = d3.select("body")
        .append("div")
        .attr("class", "fg-tooltip");
    }

    const timeMs = (d.data.value / 1000).toFixed(2);
    const percentage = ((d.data.value / data.value) * 100).toFixed(2);
    const calls = d.data.calls || 0;
    const childCount = d.children ? d.children.length : 0;
    const source = d.data.source;

    const funcname = resolveString(d.data.funcname) || resolveString(d.data.name);
    const filename = resolveString(d.data.filename) || "";
    const isSpecialFrame = filename === "~";

    let sourceHtml = "";
    if (source && Array.isArray(source) && source.length > 0) {
      const lines = source.map(line => {
        const isCurrent = line.startsWith("→");
        const escaped = line.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        return `<div class="fg-tooltip__source-line${isCurrent ? ' current' : ''}">${escaped}</div>`;
      }).join("");

      sourceHtml = `
        <div class="fg-tooltip__source">
          <div class="fg-tooltip__source-title">Source Code</div>
          <div class="fg-tooltip__source-code">${lines}</div>
        </div>`;
    }

    const locationHtml = isSpecialFrame ? "" : `
      <div class="fg-tooltip__location">${filename}${d.data.lineno ? ":" + d.data.lineno : ""}</div>`;

    const html = `
      <div class="fg-tooltip__header">
        <div class="fg-tooltip__title">${funcname}</div>
        ${locationHtml}
      </div>
      <div class="fg-tooltip__stats">
        <span class="fg-tooltip__stat-label">Time</span>
        <span class="fg-tooltip__stat-value">${timeMs} ms</span>
        <span class="fg-tooltip__stat-label">Percent</span>
        <span class="fg-tooltip__stat-value accent">${percentage}%</span>
        ${calls > 0 ? `
          <span class="fg-tooltip__stat-label">Calls</span>
          <span class="fg-tooltip__stat-value">${calls.toLocaleString()}</span>
        ` : ''}
        ${childCount > 0 ? `
          <span class="fg-tooltip__stat-label">Children</span>
          <span class="fg-tooltip__stat-value">${childCount}</span>
        ` : ''}
      </div>
      ${sourceHtml}
      <div class="fg-tooltip__hint">
        ${childCount > 0 ? "Click to zoom into this function" : "Leaf function"}
      </div>
    `;

    // Position tooltip
    const event = d3.event || window.event;
    const mouseX = event.pageX || event.clientX;
    const mouseY = event.pageY || event.clientY;
    const padding = 12;

    this._tooltip.html(html);

    // Measure tooltip
    const node = this._tooltip.node();
    const tooltipWidth = node.offsetWidth || 300;
    const tooltipHeight = node.offsetHeight || 200;

    // Calculate position
    let left = mouseX + padding;
    let top = mouseY + padding;

    if (left + tooltipWidth > window.innerWidth) {
      left = mouseX - tooltipWidth - padding;
      if (left < 0) left = padding;
    }

    if (top + tooltipHeight > window.innerHeight) {
      top = mouseY - tooltipHeight - padding;
      if (top < 0) top = padding;
    }

    this._tooltip
      .style("left", left + "px")
      .style("top", top + "px")
      .classed("visible", true);

    // Update status bar
    updateStatusBar(d.data, data.value);
  };

  tooltip.hide = function () {
    if (this._tooltip) {
      this._tooltip.classed("visible", false);
    }
    clearStatusBar();
  };

  return tooltip;
}

// ============================================================================
// Status Bar
// ============================================================================

function updateStatusBar(nodeData, rootValue) {
  const funcname = resolveString(nodeData.funcname) || resolveString(nodeData.name) || "--";
  const filename = resolveString(nodeData.filename) || "";
  const lineno = nodeData.lineno;
  const timeMs = (nodeData.value / 1000).toFixed(2);
  const percent = ((nodeData.value / rootValue) * 100).toFixed(1);

  document.getElementById('status-ready').style.display = 'none';
  document.getElementById('status-location').style.display = filename && filename !== "~" ? 'flex' : 'none';
  document.getElementById('status-func-item').style.display = 'flex';
  document.getElementById('status-time-item').style.display = 'flex';
  document.getElementById('status-percent-item').style.display = 'flex';

  const fileEl = document.getElementById('status-file');
  if (fileEl && filename && filename !== "~") {
    const basename = filename.split('/').pop();
    fileEl.textContent = lineno ? `${basename}:${lineno}` : basename;
  }

  const funcEl = document.getElementById('status-func');
  if (funcEl) funcEl.textContent = funcname.length > 40 ? funcname.substring(0, 37) + '...' : funcname;

  const timeEl = document.getElementById('status-time');
  if (timeEl) timeEl.textContent = `${timeMs} ms`;

  const percentEl = document.getElementById('status-percent');
  if (percentEl) percentEl.textContent = `${percent}%`;
}

function clearStatusBar() {
  document.getElementById('status-ready').style.display = 'flex';
  document.getElementById('status-location').style.display = 'none';
  document.getElementById('status-func-item').style.display = 'none';
  document.getElementById('status-time-item').style.display = 'none';
  document.getElementById('status-percent-item').style.display = 'none';
}

// ============================================================================
// Flamegraph Creation
// ============================================================================

function ensureLibraryLoaded() {
  if (typeof flamegraph === "undefined") {
    console.error("d3-flame-graph library not loaded");
    document.getElementById("chart").innerHTML =
      '<div style="padding: 40px; text-align: center; color: var(--text-muted);">Error: d3-flame-graph library failed to load</div>';
    throw new Error("d3-flame-graph library failed to load");
  }
}

function createFlamegraph(tooltip, rootValue) {
  const chartArea = document.querySelector('.chart-area');
  const width = chartArea ? chartArea.clientWidth - 32 : window.innerWidth - 300;

  let chart = flamegraph()
    .width(width)
    .cellHeight(20)
    .transitionDuration(300)
    .minFrameSize(1)
    .tooltip(tooltip)
    .inverted(true)
    .setColorMapper(function (d) {
      const percentage = d.data.value / rootValue;
      let colorIndex;
      if (percentage >= 0.6) colorIndex = 7;
      else if (percentage >= 0.35) colorIndex = 6;
      else if (percentage >= 0.18) colorIndex = 5;
      else if (percentage >= 0.12) colorIndex = 4;
      else if (percentage >= 0.06) colorIndex = 3;
      else if (percentage >= 0.03) colorIndex = 2;
      else if (percentage >= 0.01) colorIndex = 1;
      else colorIndex = 0;
      return heatColors[colorIndex];
    });

  return chart;
}

function renderFlamegraph(chart, data) {
  d3.select("#chart").datum(data).call(chart);
  window.flamegraphChart = chart;
  window.flamegraphData = data;
  populateStats(data);
}

// ============================================================================
// Search
// ============================================================================

function updateSearchHighlight(searchTerm, searchInput) {
  d3.selectAll("#chart rect")
    .classed("search-match", false)
    .classed("search-dim", false);

  // Clear active state from all hotspots
  document.querySelectorAll('.hotspot').forEach(h => h.classList.remove('active'));

  if (searchTerm && searchTerm.length > 0) {
    let matchCount = 0;

    d3.selectAll("#chart rect").each(function (d) {
      if (d && d.data) {
        const name = resolveString(d.data.name) || "";
        const funcname = resolveString(d.data.funcname) || "";
        const filename = resolveString(d.data.filename) || "";
        const lineno = d.data.lineno;
        const term = searchTerm.toLowerCase();

        // Check if search term looks like file:line pattern
        const fileLineMatch = term.match(/^(.+):(\d+)$/);
        let matches = false;

        if (fileLineMatch) {
          // Exact file:line matching
          const searchFile = fileLineMatch[1];
          const searchLine = parseInt(fileLineMatch[2], 10);
          const basename = filename.split('/').pop().toLowerCase();
          matches = basename.includes(searchFile) && lineno === searchLine;
        } else {
          // Regular substring search
          matches =
            name.toLowerCase().includes(term) ||
            funcname.toLowerCase().includes(term) ||
            filename.toLowerCase().includes(term);
        }

        if (matches) {
          matchCount++;
          d3.select(this).classed("search-match", true);
        } else {
          d3.select(this).classed("search-dim", true);
        }
      }
    });

    if (searchInput) {
      searchInput.classList.remove("has-matches", "no-matches");
      searchInput.classList.add(matchCount > 0 ? "has-matches" : "no-matches");
    }

    // Mark matching hotspot as active
    document.querySelectorAll('.hotspot').forEach(h => {
      if (h.dataset.searchterm && h.dataset.searchterm.toLowerCase() === searchTerm.toLowerCase()) {
        h.classList.add('active');
      }
    });
  } else if (searchInput) {
    searchInput.classList.remove("has-matches", "no-matches");
  }
}

function searchForHotspot(funcname) {
  const searchInput = document.getElementById('search-input');
  const searchWrapper = document.querySelector('.search-wrapper');
  if (searchInput) {
    searchInput.value = funcname;
    if (searchWrapper) {
      searchWrapper.classList.add('has-value');
    }
    performSearch();
    searchInput.focus();
  }
}

function initSearchHandlers() {
  const searchInput = document.getElementById("search-input");
  const searchWrapper = document.querySelector(".search-wrapper");
  if (!searchInput) return;

  let searchTimeout;
  function performSearch() {
    const term = searchInput.value.trim();
    updateSearchHighlight(term, searchInput);
    // Toggle has-value class for clear button visibility
    if (searchWrapper) {
      searchWrapper.classList.toggle("has-value", term.length > 0);
    }
  }

  searchInput.addEventListener("input", function () {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(performSearch, 150);
  });

  window.performSearch = performSearch;
}

function clearSearch() {
  const searchInput = document.getElementById("search-input");
  const searchWrapper = document.querySelector(".search-wrapper");
  if (searchInput) {
    searchInput.value = "";
    searchInput.classList.remove("has-matches", "no-matches");
    if (searchWrapper) {
      searchWrapper.classList.remove("has-value");
    }
    // Clear highlights
    d3.selectAll("#chart rect")
      .classed("search-match", false)
      .classed("search-dim", false);
    // Clear active hotspot
    document.querySelectorAll('.hotspot').forEach(h => h.classList.remove('active'));
  }
}

// ============================================================================
// Resize Handler
// ============================================================================

function handleResize(chart, data) {
  let resizeTimeout;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimeout);
    resizeTimeout = setTimeout(function () {
      if (chart && data) {
        const chartArea = document.querySelector('.chart-area');
        const newWidth = chartArea ? chartArea.clientWidth - 32 : window.innerWidth - 300;
        chart.width(newWidth);
        d3.select("#chart").datum(data).call(chart);
      }
    }, 100);
  });
}

// ============================================================================
// Hotspot Stats
// ============================================================================

function populateStats(data) {
  const totalSamples = data.value || 0;
  const functionMap = new Map();

  function collectFunctions(node) {
    if (!node) return;

    let filename = typeof node.filename === 'number' ? resolveString(node.filename) : node.filename;
    let funcname = typeof node.funcname === 'number' ? resolveString(node.funcname) : node.funcname;

    if (!filename || !funcname) {
      const nameStr = typeof node.name === 'number' ? resolveString(node.name) : node.name;
      if (nameStr?.includes('(')) {
        const match = nameStr.match(/^(.+?)\s*\((.+?):(\d+)\)$/);
        if (match) {
          funcname = funcname || match[1];
          filename = filename || match[2];
        }
      }
    }

    filename = filename || 'unknown';
    funcname = funcname || 'unknown';

    if (filename !== 'unknown' && funcname !== 'unknown' && node.value > 0) {
      let childrenValue = 0;
      if (node.children) {
        childrenValue = node.children.reduce((sum, child) => sum + child.value, 0);
      }
      const directSamples = Math.max(0, node.value - childrenValue);
      const funcKey = `${filename}:${node.lineno || '?'}:${funcname}`;

      if (functionMap.has(funcKey)) {
        const existing = functionMap.get(funcKey);
        existing.directSamples += directSamples;
        existing.directPercent = (existing.directSamples / totalSamples) * 100;
        if (directSamples > existing.maxSingleSamples) {
          existing.filename = filename;
          existing.lineno = node.lineno || '?';
          existing.maxSingleSamples = directSamples;
        }
      } else {
        functionMap.set(funcKey, {
          filename: filename,
          lineno: node.lineno || '?',
          funcname: funcname,
          directSamples,
          directPercent: (directSamples / totalSamples) * 100,
          maxSingleSamples: directSamples
        });
      }
    }

    if (node.children) {
      node.children.forEach(child => collectFunctions(child));
    }
  }

  collectFunctions(data);

  const hotSpots = Array.from(functionMap.values())
    .filter(f => f.directPercent > 0.5)
    .sort((a, b) => b.directPercent - a.directPercent)
    .slice(0, 3);

  // Populate and animate hotspot cards
  for (let i = 0; i < 3; i++) {
    const num = i + 1;
    const card = document.getElementById(`hotspot-${num}`);
    const funcEl = document.getElementById(`hotspot-func-${num}`);
    const fileEl = document.getElementById(`hotspot-file-${num}`);
    const percentEl = document.getElementById(`hotspot-percent-${num}`);
    const samplesEl = document.getElementById(`hotspot-samples-${num}`);

    if (i < hotSpots.length && hotSpots[i]) {
      const h = hotSpots[i];
      const filename = h.filename || 'unknown';
      const lineno = h.lineno ?? '?';
      const isSpecialFrame = filename === '~' && (lineno === 0 || lineno === '?');

      let funcDisplay = h.funcname || 'unknown';
      if (funcDisplay.length > 30) funcDisplay = funcDisplay.substring(0, 27) + '...';

      if (funcEl) funcEl.textContent = funcDisplay;
      if (fileEl) {
        if (isSpecialFrame) {
          fileEl.textContent = '--';
        } else {
          const basename = filename !== 'unknown' ? filename.split('/').pop() : 'unknown';
          fileEl.textContent = `${basename}:${lineno}`;
        }
      }
      if (percentEl) percentEl.textContent = `${h.directPercent.toFixed(1)}%`;
      if (samplesEl) samplesEl.textContent = ` (${h.directSamples.toLocaleString()})`;
    } else {
      if (funcEl) funcEl.textContent = '--';
      if (fileEl) fileEl.textContent = '--';
      if (percentEl) percentEl.textContent = '--';
      if (samplesEl) samplesEl.textContent = '';
    }

    // Add click handler and animate entrance
    if (card) {
      if (i < hotSpots.length && hotSpots[i]) {
        const h = hotSpots[i];
        const basename = h.filename !== 'unknown' ? h.filename.split('/').pop() : '';
        const searchTerm = basename && h.lineno !== '?' ? `${basename}:${h.lineno}` : h.funcname;
        card.dataset.searchterm = searchTerm;
        card.onclick = () => searchForHotspot(searchTerm);
      } else {
        card.onclick = null;
        delete card.dataset.searchterm;
      }

      setTimeout(() => {
        card.classList.add('visible');
      }, 100 + i * 80);
    }
  }
}

// ============================================================================
// Thread Filter
// ============================================================================

function initThreadFilter(data) {
  const threadFilter = document.getElementById('thread-filter');
  const threadSection = document.getElementById('thread-section');

  if (!threadFilter || !data.threads) return;

  threadFilter.innerHTML = '<option value="all">All Threads</option>';

  const threads = data.threads || [];
  threads.forEach(threadId => {
    const option = document.createElement('option');
    option.value = threadId;
    option.textContent = `Thread ${threadId}`;
    threadFilter.appendChild(option);
  });

  if (threads.length > 1 && threadSection) {
    threadSection.style.display = 'block';
  }
}

function filterByThread() {
  const threadFilter = document.getElementById('thread-filter');
  if (!threadFilter || !originalData) return;

  const selectedThread = threadFilter.value;
  currentThreadFilter = selectedThread;

  let filteredData;
  if (selectedThread === 'all') {
    filteredData = originalData;
  } else {
    const threadId = parseInt(selectedThread);
    filteredData = filterDataByThread(originalData, threadId);

    if (filteredData.strings) {
      stringTable = filteredData.strings;
      filteredData = resolveStringIndices(filteredData);
    }
  }

  const tooltip = createTooltip(filteredData);
  const chart = createFlamegraph(tooltip, filteredData.value);
  renderFlamegraph(chart, filteredData);
}

function filterDataByThread(data, threadId) {
  function filterNode(node) {
    if (!node.threads || !node.threads.includes(threadId)) {
      return null;
    }

    const filteredNode = { ...node, children: [] };

    if (node.children && Array.isArray(node.children)) {
      filteredNode.children = node.children
        .map(child => filterNode(child))
        .filter(child => child !== null);
    }

    return filteredNode;
  }

  const filteredRoot = { ...data, children: [] };

  if (data.children && Array.isArray(data.children)) {
    filteredRoot.children = data.children
      .map(child => filterNode(child))
      .filter(child => child !== null);
  }

  function recalculateValue(node) {
    if (!node.children || node.children.length === 0) {
      return node.value || 0;
    }
    const childrenValue = node.children.reduce((sum, child) => sum + recalculateValue(child), 0);
    node.value = Math.max(node.value || 0, childrenValue);
    return node.value;
  }

  recalculateValue(filteredRoot);
  return filteredRoot;
}

// ============================================================================
// Control Functions
// ============================================================================

function resetZoom() {
  if (window.flamegraphChart) {
    window.flamegraphChart.resetZoom();
  }
}

function exportSVG() {
  const svgElement = document.querySelector("#chart svg");
  if (svgElement) {
    const serializer = new XMLSerializer();
    const svgString = serializer.serializeToString(svgElement);
    const blob = new Blob([svgString], { type: "image/svg+xml" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "flamegraph.svg";
    a.click();
    URL.revokeObjectURL(url);
  }
}

// ============================================================================
// Initialization
// ============================================================================

function initFlamegraph() {
  ensureLibraryLoaded();
  restoreUIState();

  let processedData = EMBEDDED_DATA;
  if (EMBEDDED_DATA.strings) {
    stringTable = EMBEDDED_DATA.strings;
    processedData = resolveStringIndices(EMBEDDED_DATA);
  }

  originalData = processedData;
  initThreadFilter(processedData);

  const tooltip = createTooltip(processedData);
  const chart = createFlamegraph(tooltip, processedData.value);
  renderFlamegraph(chart, processedData);
  initSearchHandlers();
  handleResize(chart, processedData);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initFlamegraph);
} else {
  initFlamegraph();
}
