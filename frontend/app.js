// ============================================================================
// Backtester frontend — vanilla JS, single scrolling page, no build step.
// ============================================================================

const API = "/api";

const COLOR_PALETTE = [
  "#1F6F5C", "#B5473B", "#3B6EA5", "#C98A2C",
  "#7C5CBF", "#5C8A3A", "#B5477E", "#4A9BA8",
];

// Static explanations for form fields that aren't computed metrics (shown via (i) icons)
const FIELD_INFO = {
  example: { label: "Example", description: "Just like this." },
  dividend_reinvest: {
    label: "Reinvest Dividends",
    description: "If checked, any dividends paid during the backtest are used to buy more shares (compounding) — matching how most long-term investors actually hold stocks. If unchecked, dividends are simply ignored.",
  },
  transaction_cost: {
    label: "Transaction Cost",
    description: "An estimated cost, in basis points (100 bps = 1%), charged every time the strategy buys or sells — a stand-in for commissions and bid-ask spread. Strategies that trade often are more affected by this than ones that trade rarely.",
  },
  moving_average: {
    label: "Moving Average",
    description: "The average closing price over the last N trading days, recalculated each day as new prices come in. Smooths out day-to-day noise so the underlying trend is easier to see. Shorter windows react faster to recent moves; longer windows are smoother but slower to turn.",
  },
};

// ---------------------------------------------------------------------------
// Global state
// ---------------------------------------------------------------------------
const state = {
  activeTickers: [],           // [{ticker, name}] — shared across chart / metrics / backtest ticker pickers
  compareMode: true,           // default: compare all stocks as % change
  chartRange: "1Y",
  chartViewMode: "line",       // "line" | "candlestick" — single-stock mode only
  focusTicker: null,           // which stock the single-stock view shows
  stockVisible: {},            // ticker -> bool: show this stock's line in compare mode
  mainChart: null,
  maWindows: [20, 50, 200],
  maVisible: {},
  maSeriesRefs: {},
  metricsRange: "1Y",
  metricInfo: {},
  strategies: {},
  currentStrategyParamInfo: {},
  btChart: null,
  optBasket: [],
};

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------
function debounce(fn, wait) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), wait);
  };
}

async function apiGet(path) {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

async function apiPost(path, body) {
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const errBody = await res.json().catch(() => ({}));
    throw new Error(errBody.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

function fmtPct(v, decimals = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(decimals)}%`;
}
function fmtRatio(v, decimals = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toFixed(decimals);
}
function fmtCurrency(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
function dollarAxisFormatter(price) {
  return `$${price.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
}
function percentAxisFormatter(v) {
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}

const PERCENT_METRICS = new Set(["total_return", "cagr", "volatility", "max_drawdown", "var_95", "alpha", "win_rate"]);
const SIGNED_COLOR_METRICS = new Set(["total_return", "cagr", "max_drawdown", "alpha", "sharpe", "sortino", "calmar"]);

function formatMetric(key, value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (PERCENT_METRICS.has(key)) return fmtPct(value);
  return fmtRatio(value);
}
function metricColorClass(key, value) {
  if (!SIGNED_COLOR_METRICS.has(key) || value === null || value === undefined || Number.isNaN(value)) return "";
  if (value > 0) return "val-positive";
  if (value < 0) return "val-negative";
  return "";
}
function metricHeaderCell(key, fallbackLabel) {
  const info = state.metricInfo[key];
  const label = info ? info.label : fallbackLabel || key;
  return `<div class="metric-header-cell">${label}<span class="i-icon" data-metric="${key}"></span></div>`;
}

// ---------------------------------------------------------------------------
// Tooltip system (event delegation — works for dynamically-added icons;
// supports both computed metrics (data-metric) and static/strategy fields (data-field))
// ---------------------------------------------------------------------------
const tooltipBox = document.getElementById("tooltip-box");

function lookupTooltipInfo(icon) {
  if (icon.dataset.metric) return state.metricInfo[icon.dataset.metric];
  if (icon.dataset.field) {
    if (icon.dataset.field.startsWith("param:")) {
      const pname = icon.dataset.field.slice(6);
      const desc = state.currentStrategyParamInfo[pname];
      return desc ? { label: pname, description: desc } : null;
    }
    return FIELD_INFO[icon.dataset.field];
  }
  return null;
}

document.addEventListener("mouseover", (e) => {
  const icon = e.target.closest(".i-icon, .i-icon-inline");
  if (!icon) return;
  const info = lookupTooltipInfo(icon);
  tooltipBox.innerHTML = `<span class="tt-title">${info ? info.label : "Info"}</span>${info ? info.description : "No description available."}`;
  tooltipBox.classList.remove("hidden");
  positionTooltip(e);
});
document.addEventListener("mousemove", (e) => {
  if (!tooltipBox.classList.contains("hidden")) positionTooltip(e);
});
document.addEventListener("mouseout", (e) => {
  if (e.target.closest(".i-icon, .i-icon-inline")) tooltipBox.classList.add("hidden");
});
function positionTooltip(e) {
  const pad = 14;
  let x = e.clientX + pad;
  let y = e.clientY + pad;
  const boxRect = tooltipBox.getBoundingClientRect();
  if (x + boxRect.width > window.innerWidth - 10) x = e.clientX - boxRect.width - pad;
  if (y + boxRect.height > window.innerHeight - 10) y = e.clientY - boxRect.height - pad;
  tooltipBox.style.left = `${x}px`;
  tooltipBox.style.top = `${y}px`;
}

// ---------------------------------------------------------------------------
// Sticky header height sync (keeps the jump-nav pinned exactly under the
// topbar even when the topbar wraps to two lines on narrow screens — avoids
// the visible "slide" that happens when the offset is a hardcoded guess)
// ---------------------------------------------------------------------------
function syncTopbarHeight() {
  const topbar = document.querySelector(".topbar");
  if (topbar) document.documentElement.style.setProperty("--topbar-height", `${topbar.offsetHeight}px`);
}
window.addEventListener("resize", syncTopbarHeight);

// ---------------------------------------------------------------------------
// Jump nav — scroll-spy highlighting (actual scrolling is native <a href="#..">)
// ---------------------------------------------------------------------------
function initScrollSpy() {
  const navLinks = document.querySelectorAll(".jumpnav a");
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        navLinks.forEach((link) => link.classList.toggle("active", link.dataset.section === entry.target.id));
      }
    });
  }, { rootMargin: "-90px 0px -70% 0px", threshold: 0 });
  document.querySelectorAll(".module").forEach((section) => observer.observe(section));
}

// ---------------------------------------------------------------------------
// Search (top bar — adds to global activeTickers)
// ---------------------------------------------------------------------------
const searchInput = document.getElementById("search-input");
const searchResults = document.getElementById("search-results");

const doSearch = debounce(async (query) => {
  if (!query || query.length < 1) { searchResults.classList.add("hidden"); return; }
  try {
    const results = await apiGet(`/search?q=${encodeURIComponent(query)}`);
    renderSearchResults(results, searchResults, (item) => {
      addActiveTicker(item.ticker, item.name);
      searchInput.value = "";
      searchResults.classList.add("hidden");
    });
  } catch (err) {
    searchResults.innerHTML = `<div class="search-result-empty">${err.message}</div>`;
    searchResults.classList.remove("hidden");
  }
}, 250);

searchInput.addEventListener("input", (e) => doSearch(e.target.value.trim()));
searchInput.addEventListener("focus", (e) => { if (e.target.value.trim()) doSearch(e.target.value.trim()); });
document.addEventListener("click", (e) => {
  if (!e.target.closest(".search-wrap")) searchResults.classList.add("hidden");
  if (!e.target.closest(".opt-basket-wrap")) document.getElementById("opt-search-results").classList.add("hidden");
});

function renderSearchResults(results, container, onSelect) {
  if (!results || results.length === 0) {
    container.innerHTML = `<div class="search-result-empty">No matching stocks in the local database. (The pipeline may not have fetched this ticker yet.)</div>`;
    container.classList.remove("hidden");
    return;
  }
  container.innerHTML = results.map((r, i) =>
    `<div class="search-result-item" data-idx="${i}">
       <span class="sr-ticker">${r.ticker}</span>
       <span class="sr-name">${r.name || ""}</span>
     </div>`
  ).join("");
  container.classList.remove("hidden");
  container.querySelectorAll(".search-result-item").forEach((el, i) => {
    el.addEventListener("click", () => onSelect(results[i]));
  });
}

function addActiveTicker(ticker, name) {
  if (state.activeTickers.some((t) => t.ticker === ticker)) return;
  state.activeTickers.push({ ticker, name });
  state.stockVisible[ticker] = true;
  onActiveTickersChanged();
}
function removeActiveTicker(ticker) {
  state.activeTickers = state.activeTickers.filter((t) => t.ticker !== ticker);
  delete state.stockVisible[ticker];
  onActiveTickersChanged();
}
function onActiveTickersChanged() {
  renderActiveTickerChips();
  renderStocksList();
  syncTopbarHeight(); // chip row can wrap the topbar to a different height
  syncTickerSelect("bt-ticker-select");
  renderMainChart();
  renderMetricsModule();
}

function tickerColor(ticker) {
  const i = state.activeTickers.findIndex((t) => t.ticker === ticker);
  return COLOR_PALETTE[(i < 0 ? 0 : i) % COLOR_PALETTE.length];
}

// --- Stocks module (sidebar): visibility checkbox + delete per stock ---
function renderStocksList() {
  const list = document.getElementById("stocks-list");
  const empty = document.getElementById("stocks-list-empty");
  if (state.activeTickers.length === 0) {
    list.innerHTML = "";
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");
  list.innerHTML = state.activeTickers.map((t) => {
    const checked = state.stockVisible[t.ticker] !== false;
    return `<div class="stock-row">
      <input type="checkbox" data-stock-vis="${t.ticker}" ${checked ? "checked" : ""} title="Show on chart">
      <span class="stock-swatch" style="background:${tickerColor(t.ticker)}"></span>
      <span class="stock-ticker">${t.ticker}</span>
      <button class="stock-delete" data-stock-del="${t.ticker}" aria-label="Remove ${t.ticker}" title="Remove">&times;</button>
    </div>`;
  }).join("");
  list.querySelectorAll("[data-stock-vis]").forEach((cb) => {
    cb.addEventListener("change", () => {
      state.stockVisible[cb.dataset.stockVis] = cb.checked;
      renderMainChart();
    });
  });
  list.querySelectorAll("[data-stock-del]").forEach((b) => {
    b.addEventListener("click", () => removeActiveTicker(b.dataset.stockDel));
  });
}

function renderActiveTickerChips() {
  const wrap = document.getElementById("active-tickers");
  wrap.innerHTML = state.activeTickers.map((t) =>
    `<span class="chip">${t.ticker}<button data-ticker="${t.ticker}" aria-label="Remove ${t.ticker}">&times;</button></span>`
  ).join("");
  wrap.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => removeActiveTicker(b.dataset.ticker)));
}

function syncTickerSelect(selectId) {
  const sel = document.getElementById(selectId);
  const prev = sel.value;
  sel.innerHTML = state.activeTickers.map((t) => `<option value="${t.ticker}">${t.ticker}</option>`).join("");
  if (state.activeTickers.some((t) => t.ticker === prev)) sel.value = prev;
}

// ---------------------------------------------------------------------------
// Chart module (Price / % comparison + Moving Averages)
// ---------------------------------------------------------------------------
document.querySelectorAll("#chart-range button").forEach((btn) => {
  btn.addEventListener("click", () => {
    setActiveRangeButton("chart-range", btn);
    state.chartRange = btn.dataset.range;
    renderMainChart();
  });
});

function setActiveRangeButton(containerId, btn) {
  document.querySelectorAll(`#${containerId} button`).forEach((b) => b.classList.remove("active"));
  btn.classList.add("active");
}

const compareToggle = document.getElementById("compare-mode-toggle");
compareToggle.checked = state.compareMode;
compareToggle.addEventListener("change", () => {
  state.compareMode = compareToggle.checked;
  renderMainChart();
});

const focusSelect = document.getElementById("focus-ticker-select");
focusSelect.addEventListener("change", (e) => {
  state.focusTicker = e.target.value;
  renderMainChart();
});

document.querySelectorAll("#view-toggle button").forEach((btn) => {
  btn.addEventListener("click", () => {
    setActiveRangeButton("view-toggle", btn);
    state.chartViewMode = btn.dataset.view;
    renderMainChart();
  });
});

function syncFocusTickerSelect() {
  const prev = state.focusTicker;
  focusSelect.innerHTML = state.activeTickers.map((t) => `<option value="${t.ticker}">${t.ticker}</option>`).join("");
  state.focusTicker = state.activeTickers.some((t) => t.ticker === prev) ? prev : (state.activeTickers[0] ? state.activeTickers[0].ticker : null);
  if (state.focusTicker) focusSelect.value = state.focusTicker;
}

// Map a range key to a cutoff date string (YYYY-MM-DD), or null for "all".
function rangeCutoff(rangeKey, lastDateStr) {
  if (!rangeKey || rangeKey.toUpperCase() === "ALL") return null;
  const last = new Date(lastDateStr + "T00:00:00");
  const d = new Date(last);
  switch (rangeKey.toUpperCase()) {
    case "5D": d.setDate(d.getDate() - 8); break;
    case "1M": d.setDate(d.getDate() - 32); break;
    case "3M": d.setDate(d.getDate() - 93); break;
    case "YTD": return `${last.getFullYear()}-01-01`;
    case "1Y": d.setDate(d.getDate() - 366); break;
    case "5Y": d.setFullYear(d.getFullYear() - 5); break;
    default: d.setDate(d.getDate() - 366);
  }
  return d.toISOString().slice(0, 10);
}

// Given a sorted array of date strings + a cutoff, return the index of the first
// visible bar (used to set the visible window without discarding the rest of history).
function firstVisibleIndex(dates, cutoff) {
  if (!cutoff) return 0;
  for (let i = 0; i < dates.length; i++) {
    if (dates[i] >= cutoff) return i;
  }
  return 0;
}

// Apply the selected range as a *visible window* over the full history, so the user
// can still scroll/zoom to older data (edge-locked at the true data bounds).
function applyVisibleRange(chart, dates, fromIdx) {
  if (!dates.length) return;
  try {
    chart.timeScale().setVisibleRange({ from: dates[fromIdx], to: dates[dates.length - 1] });
  } catch (err) {
    chart.timeScale().fitContent();
  }
}

async function renderMainChart() {
  const container = document.getElementById("main-chart");
  const empty = document.getElementById("main-chart-empty");
  const sidebar = document.getElementById("chart-sidebar");
  const viewToggle = document.getElementById("view-toggle");
  const focusField = document.getElementById("focus-stock-field");

  if (state.activeTickers.length === 0) {
    container.classList.add("hidden");
    empty.classList.remove("hidden");
    sidebar.classList.add("hidden");
    compareToggle.disabled = true;
    return;
  }
  container.classList.remove("hidden");
  empty.classList.add("hidden");
  sidebar.classList.remove("hidden");
  compareToggle.disabled = false;
  syncFocusTickerSelect();
  renderMaChecklist();

  const comparing = state.compareMode;
  // In single-stock mode: show the focus dropdown + line/candlestick toggle.
  focusField.classList.toggle("hidden", comparing);
  viewToggle.classList.toggle("hidden", comparing);

  if (comparing) {
    await renderComparisonChart();
  } else {
    await renderSingleChart();
  }
}

// Single-stock view: price ($) or candlesticks, with moving averages.
async function renderSingleChart() {
  const container = document.getElementById("main-chart");
  const ticker = state.focusTicker;
  if (!ticker) return;

  let data;
  try {
    // Fetch full history so the range buttons set a *window* you can scroll beyond.
    data = await apiGet(`/moving-averages?ticker=${ticker}&windows=${state.maWindows.join(",")}&range=ALL`);
  } catch (err) {
    container.innerHTML = `<p class="hint" style="padding:12px">${err.message}</p>`;
    return;
  }

  container.innerHTML = "";
  if (state.mainChart) { state.mainChart.remove(); state.mainChart = null; }
  const chart = LightweightCharts.createChart(container, baseChartOptions(container, dollarAxisFormatter));
  state.mainChart = chart;
  state.maSeriesRefs = {};

  if (state.chartViewMode === "candlestick") {
    const candleSeries = chart.addCandlestickSeries({
      upColor: "#1F6F5C", downColor: "#B5473B", borderVisible: false,
      wickUpColor: "#1F6F5C", wickDownColor: "#B5473B",
      title: `${ticker} (unadjusted OHLC)`,
    });
    candleSeries.setData(data.dates.map((date, idx) => ({
      time: date, open: data.open[idx], high: data.high[idx], low: data.low[idx], close: data.raw_close[idx],
    })));
  } else {
    const priceSeries = chart.addLineSeries({ color: "#16202B", lineWidth: 2, title: `${ticker} price` });
    priceSeries.setData(data.dates.map((date, idx) => ({ time: date, value: data.close[idx] })));
  }

  state.maWindows.forEach((w, i) => {
    const series = chart.addLineSeries({
      color: COLOR_PALETTE[(i + 1) % COLOR_PALETTE.length],
      lineWidth: 1.5,
      title: `${w}-day MA`,
      visible: state.maVisible[w] !== false,
    });
    const values = data.moving_averages[String(w)];
    series.setData(
      data.dates.map((date, idx) => ({ time: date, value: values[idx] })).filter((pt) => pt.value !== null && pt.value !== undefined)
    );
    state.maSeriesRefs[w] = series;
  });

  const fromIdx = firstVisibleIndex(data.dates, rangeCutoff(state.chartRange, data.dates[data.dates.length - 1]));
  applyVisibleRange(chart, data.dates, fromIdx);
}

// Comparison view: every *visible* stock as % change, re-based to the window start,
// with optional moving-average overlays for each shown stock.
async function renderComparisonChart() {
  const container = document.getElementById("main-chart");
  const shown = state.activeTickers.filter((t) => state.stockVisible[t.ticker] !== false);
  if (shown.length === 0) {
    container.innerHTML = `<p class="hint" style="padding:12px">No stocks are checked. Use the Stocks list to show one.</p>`;
    return;
  }

  const tickers = shown.map((t) => t.ticker).join(",");
  let data;
  try {
    data = await apiGet(`/prices?tickers=${tickers}&range=ALL`);
  } catch (err) {
    container.innerHTML = `<p class="hint" style="padding:12px">${err.message}</p>`;
    return;
  }

  // Determine the common latest date and the window cutoff for re-basing.
  let latest = "";
  shown.forEach((t) => {
    const d = data[t.ticker];
    if (d && !d.error && d.dates.length) latest = d.dates[d.dates.length - 1] > latest ? d.dates[d.dates.length - 1] : latest;
  });
  const cutoff = rangeCutoff(state.chartRange, latest);

  container.innerHTML = "";
  if (state.mainChart) { state.mainChart.remove(); state.mainChart = null; }
  const chart = LightweightCharts.createChart(container, baseChartOptions(container, percentAxisFormatter));
  state.mainChart = chart;

  let anyDates = [];
  const anyMaChecked = state.maWindows.some((w) => state.maVisible[w] !== false);

  shown.forEach((t, i) => {
    const d = data[t.ticker];
    if (!d || d.error) return;
    const baseIdx = firstVisibleIndex(d.dates, cutoff);
    const base = d.adj_close[baseIdx] || d.adj_close[0];
    const color = tickerColor(t.ticker);
    const series = chart.addLineSeries({ color, lineWidth: 2, title: t.ticker });
    series.setData(d.dates.map((date, idx) => ({ time: date, value: ((d.adj_close[idx] / base) - 1) * 100 })));
    if (d.dates.length > anyDates.length) anyDates = d.dates;
  });

  // MA overlays (dashed, in each stock's colour), on the same % basis — only if
  // there aren't too many lines already, to keep it readable.
  if (anyMaChecked && shown.length <= 4) {
    for (let i = 0; i < shown.length; i++) {
      const t = shown[i];
      let maData;
      try {
        maData = await apiGet(`/moving-averages?ticker=${t.ticker}&windows=${state.maWindows.join(",")}&range=ALL`);
      } catch (err) { continue; }
      const baseIdx = firstVisibleIndex(maData.dates, cutoff);
      const base = maData.close[baseIdx] || maData.close[0];
      state.maWindows.forEach((w) => {
        if (state.maVisible[w] === false) return;
        const values = maData.moving_averages[String(w)];
        const series = chart.addLineSeries({
          color: tickerColor(t.ticker), lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed,
          title: `${t.ticker} ${w}d MA`, crosshairMarkerVisible: false, lastValueVisible: false,
        });
        series.setData(
          maData.dates
            .map((date, idx) => ({ time: date, value: values[idx] == null ? null : ((values[idx] / base) - 1) * 100 }))
            .filter((pt) => pt.value !== null)
        );
      });
    }
  }

  if (anyDates.length) {
    const fromIdx = firstVisibleIndex(anyDates, cutoff);
    applyVisibleRange(chart, anyDates, fromIdx);
  }
}

document.getElementById("ma-add-btn").addEventListener("click", () => {
  const input = document.getElementById("ma-add-input");
  const val = parseInt(input.value, 10);
  if (!val || val < 2 || val > 500) return;
  if (!state.maWindows.includes(val)) {
    state.maWindows.push(val);
    state.maWindows.sort((a, b) => a - b);
    state.maVisible[val] = true;
  }
  input.value = "";
  renderMainChart();
});

document.getElementById("ma-select-all-btn").addEventListener("click", () => setAllMaVisibility(true));
document.getElementById("ma-select-none-btn").addEventListener("click", () => setAllMaVisibility(false));

function setAllMaVisibility(visible) {
  state.maWindows.forEach((w) => { state.maVisible[w] = visible; });
  renderMaChecklist();
  if (state.compareMode) {
    renderMainChart();
  } else {
    Object.values(state.maSeriesRefs).forEach((series) => series.applyOptions({ visible }));
  }
}

function renderMaChecklist() {
  const wrap = document.getElementById("ma-checkbox-list");
  wrap.innerHTML = state.maWindows.map((w, i) => {
    const checked = state.maVisible[w] !== false;
    const color = COLOR_PALETTE[(i + 1) % COLOR_PALETTE.length];
    return `<label>
      <input type="checkbox" data-window="${w}" ${checked ? "checked" : ""}>
      <span class="swatch" style="background:${color}"></span>${w}-day
    </label>`;
  }).join("");
  wrap.querySelectorAll("input[type=checkbox]").forEach((cb) => {
    cb.addEventListener("change", () => {
      const w = cb.dataset.window;
      state.maVisible[w] = cb.checked;
      if (state.compareMode) {
        renderMainChart();
      } else if (state.maSeriesRefs[w]) {
        state.maSeriesRefs[w].applyOptions({ visible: cb.checked });
      }
    });
  });
}

// ---------------------------------------------------------------------------
// Metrics module
// ---------------------------------------------------------------------------
document.querySelectorAll("#metrics-range button").forEach((btn) => {
  btn.addEventListener("click", () => {
    setActiveRangeButton("metrics-range", btn);
    state.metricsRange = btn.dataset.range;
    renderMetricsModule();
  });
});

const METRICS_COLUMNS = ["total_return", "cagr", "volatility", "sharpe", "sortino", "max_drawdown", "calmar", "beta", "alpha", "var_95", "correlation"];

async function renderMetricsModule() {
  const wrap = document.getElementById("metrics-table-wrap");
  const empty = document.getElementById("metrics-empty");

  if (state.activeTickers.length === 0) {
    wrap.classList.add("hidden");
    empty.classList.remove("hidden");
    return;
  }
  wrap.classList.remove("hidden");
  empty.classList.add("hidden");

  const tickers = state.activeTickers.map((t) => t.ticker).join(",");
  let data;
  try {
    data = await apiGet(`/metrics?tickers=${tickers}&range=${state.metricsRange}&benchmark=SPY`);
  } catch (err) {
    wrap.innerHTML = `<p class="hint">${err.message}</p>`;
    return;
  }

  const rows = state.activeTickers.map((t) => {
    const m = data.metrics[t.ticker];
    if (!m || m.error) return `<tr><td class="ticker-cell">${t.ticker}</td><td colspan="${METRICS_COLUMNS.length}">${m ? m.error : "No data"}</td></tr>`;
    const cells = METRICS_COLUMNS.map((key) => {
      const v = m[key];
      return `<td class="${metricColorClass(key, v)}">${formatMetric(key, v)}</td>`;
    }).join("");
    return `<tr><td class="ticker-cell">${t.ticker}</td>${cells}</tr>`;
  }).join("");

  wrap.innerHTML = `<div class="data-table-wrap"><table class="data-table">
    <thead><tr><th>Stock</th>${METRICS_COLUMNS.map((k) => `<th>${metricHeaderCell(k)}</th>`).join("")}</tr></thead>
    <tbody>${rows}</tbody>
  </table></div>`;
}

// ---------------------------------------------------------------------------
// Backtest module
// ---------------------------------------------------------------------------
async function initBacktestModule() {
  state.strategies = await apiGet("/strategies");
  const sel = document.getElementById("bt-strategy-select");
  sel.innerHTML = Object.entries(state.strategies).map(([key, s]) => `<option value="${key}">${s.label}</option>`).join("");
  sel.addEventListener("change", renderStrategyParams);
  renderStrategyParams();
}

function renderStrategyParams() {
  const key = document.getElementById("bt-strategy-select").value;
  const strat = state.strategies[key];
  if (!strat) return;
  document.getElementById("bt-strategy-desc").textContent = strat.description;
  state.currentStrategyParamInfo = strat.param_info || {};
  const wrap = document.getElementById("bt-params");
  wrap.innerHTML = Object.entries(strat.default_params).map(([pname, pval]) =>
    `<label class="field-label">
      <span class="param-label-row">${pname}<span class="i-icon" data-field="param:${pname}"></span></span>
      <input type="number" step="any" data-param="${pname}" value="${pval}">
    </label>`
  ).join("");
}

document.getElementById("bt-run-btn").addEventListener("click", runBacktest);

async function runBacktest() {
  const ticker = document.getElementById("bt-ticker-select").value;
  if (!ticker) { alert("Add a stock from the search bar at the top first."); return; }
  const strategy = document.getElementById("bt-strategy-select").value;
  const range = document.getElementById("bt-range-select").value;
  const dividendReinvest = document.getElementById("bt-dividend-reinvest").checked;
  const txnCost = parseFloat(document.getElementById("bt-txn-cost").value) || 0;
  const capital = parseFloat(document.getElementById("bt-capital").value) || 10000;

  const params = {};
  document.querySelectorAll("#bt-params input").forEach((inp) => { params[inp.dataset.param] = parseFloat(inp.value); });

  const btn = document.getElementById("bt-run-btn");
  btn.textContent = "Running...";
  btn.disabled = true;
  try {
    const result = await apiPost("/backtest", {
      ticker, strategy, params, range,
      dividend_reinvest: dividendReinvest,
      transaction_cost_bps: txnCost,
      initial_capital: capital,
    });
    renderBacktestResults(result, capital);
  } catch (err) {
    alert(err.message);
  } finally {
    btn.textContent = "Run Backtest";
    btn.disabled = false;
  }
}

function renderBacktestResults(result, capital) {
  document.getElementById("bt-results").classList.remove("hidden");

  const container = document.getElementById("bt-chart");
  container.innerHTML = "";
  if (state.btChart) { state.btChart.remove(); state.btChart = null; }
  const chart = LightweightCharts.createChart(container, baseChartOptions(container, dollarAxisFormatter));
  state.btChart = chart;

  const stratSeries = chart.addLineSeries({ color: COLOR_PALETTE[0], lineWidth: 2, title: `${result.strategy} strategy` });
  stratSeries.setData(result.dates.map((d, i) => ({ time: d, value: result.strategy_equity[i] })));
  const bhSeries = chart.addLineSeries({ color: COLOR_PALETTE[1], lineWidth: 2, title: "Buy & hold" });
  bhSeries.setData(result.dates.map((d, i) => ({ time: d, value: result.buy_hold_equity[i] })));
  chart.timeScale().fitContent();

  const compareKeys = ["total_return", "cagr", "volatility", "sharpe", "sortino", "max_drawdown", "calmar", "win_rate", "avg_win_loss_ratio"];
  const stratFinal = result.strategy_equity[result.strategy_equity.length - 1];
  const bhFinal = result.buy_hold_equity[result.buy_hold_equity.length - 1];

  const rows = compareKeys.map((key) => {
    const sv = result.strategy_metrics[key];
    const bv = result.buy_hold_metrics ? result.buy_hold_metrics[key] : null;
    const bCell = (key === "win_rate" || key === "avg_win_loss_ratio") ? '<td class="ticker-cell">—</td>' : `<td class="${metricColorClass(key, bv)}">${formatMetric(key, bv)}</td>`;
    return `<tr><td class="label-cell">${(state.metricInfo[key] || {}).label || key}</td>
      <td class="${metricColorClass(key, sv)}">${formatMetric(key, sv)}</td>
      ${bCell}</tr>`;
  }).join("");

  document.getElementById("bt-comparison-table-wrap").innerHTML = `
    <div class="data-table-wrap"><table class="data-table">
      <thead><tr><th>Metric</th><th>Strategy</th><th>Buy &amp; Hold</th></tr></thead>
      <tbody>
        <tr><td class="label-cell">Ending value (started at ${fmtCurrency(capital)})</td>
          <td>${fmtCurrency(stratFinal)}</td><td>${fmtCurrency(bhFinal)}</td></tr>
        ${rows}
      </tbody>
    </table></div>`;

  const tradeRows = result.trade_log.map((t) =>
    `<tr><td class="label-cell">${t.entry_date}</td><td class="ticker-cell">${t.exit_date}</td>
      <td>${fmtCurrency(t.entry_price)}</td><td>${fmtCurrency(t.exit_price)}</td>
      <td class="${t.return_pct >= 0 ? "val-positive" : "val-negative"}">${t.return_pct.toFixed(2)}%</td></tr>`
  ).join("");

  document.getElementById("bt-trade-log-wrap").innerHTML = result.trade_log.length
    ? `<div class="data-table-wrap"><table class="data-table">
        <thead><tr><th>Entry Date</th><th>Exit Date</th><th>Entry Price</th><th>Exit Price</th><th>Return</th></tr></thead>
        <tbody>${tradeRows}</tbody>
      </table></div>`
    : `<p class="hint">No completed trades in this period — the strategy either stayed in cash or is still holding a position at the end of the window.</p>`;

  document.getElementById("bt-results").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// ---------------------------------------------------------------------------
// Portfolio Optimizer module
// ---------------------------------------------------------------------------
const optAddInput = document.getElementById("opt-add-input");
const optSearchResults = document.getElementById("opt-search-results");

const doOptSearch = debounce(async (query) => {
  if (!query) { optSearchResults.classList.add("hidden"); return; }
  try {
    const results = await apiGet(`/search?q=${encodeURIComponent(query)}`);
    renderSearchResults(results, optSearchResults, (item) => {
      addToBasket(item.ticker);
      optAddInput.value = "";
      optSearchResults.classList.add("hidden");
    });
  } catch (err) { /* ignore */ }
}, 250);
optAddInput.addEventListener("input", (e) => doOptSearch(e.target.value.trim()));

function addToBasket(ticker) {
  if (!state.optBasket.includes(ticker)) state.optBasket.push(ticker);
  renderBasketChips();
}
function removeFromBasket(ticker) {
  state.optBasket = state.optBasket.filter((t) => t !== ticker);
  renderBasketChips();
}
function renderBasketChips() {
  document.getElementById("opt-basket-chips").innerHTML = state.optBasket.map((t) =>
    `<span class="chip">${t}<button data-ticker="${t}">&times;</button></span>`
  ).join("");
  document.querySelectorAll("#opt-basket-chips button").forEach((b) => b.addEventListener("click", () => removeFromBasket(b.dataset.ticker)));
}

document.getElementById("opt-run-btn").addEventListener("click", runOptimizer);

async function runOptimizer() {
  if (state.optBasket.length < 2) { alert("Add at least 2 stocks to the basket first."); return; }
  const range = document.getElementById("opt-range-select").value;
  const btn = document.getElementById("opt-run-btn");
  btn.textContent = "Optimizing...";
  btn.disabled = true;
  try {
    const result = await apiPost("/optimize", { tickers: state.optBasket, range });
    renderOptimizerResults(result);
  } catch (err) {
    alert(err.message);
  } finally {
    btn.textContent = "Optimize Portfolio";
    btn.disabled = false;
  }
}

function renderOptimizerResults(result) {
  document.getElementById("opt-results").classList.remove("hidden");

  renderFrontierChart(result);

  document.getElementById("opt-minvar-return").textContent = fmtPct(result.min_variance_portfolio.expected_return);
  document.getElementById("opt-minvar-vol").textContent = fmtPct(result.min_variance_portfolio.volatility);
  renderWeights("opt-minvar-weights", result.min_variance_portfolio.weights);

  document.getElementById("opt-maxsharpe-return").textContent = fmtPct(result.max_sharpe_portfolio.expected_return);
  document.getElementById("opt-maxsharpe-vol").textContent = fmtPct(result.max_sharpe_portfolio.volatility);
  document.getElementById("opt-maxsharpe-sharpe").textContent = fmtRatio(result.max_sharpe_portfolio.sharpe_ratio);
  renderWeights("opt-maxsharpe-weights", result.max_sharpe_portfolio.weights);

  const explain = explainOptimizerWeights(result);
  document.getElementById("opt-minvar-explain").innerHTML = explain.minVar;
  document.getElementById("opt-maxsharpe-explain").innerHTML = explain.maxSharpe;

  renderCorrelationMatrix(result.correlation_matrix, result.tickers);

  document.getElementById("opt-results").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// Generate plain-English, deliberately-cautious explanations of why the optimizer
// landed on these weights. We only state things we can verify from the returned
// numbers (per-asset volatility, per-asset return/vol ratio, average correlation),
// and hedge the causal language because weights depend on the whole covariance
// structure, not any single asset in isolation.
function explainOptimizerWeights(result) {
  const assets = result.individual_assets || [];
  const corr = result.correlation_matrix || {};
  const byTicker = {};
  assets.forEach((a) => {
    const ratio = a.volatility > 0 ? a.return / a.volatility : -Infinity;
    byTicker[a.ticker] = { vol: a.volatility, ret: a.return, ratio };
  });

  const tickers = assets.map((a) => a.ticker);
  const avgCorr = (t) => {
    const row = corr[t];
    if (!row) return null;
    const others = tickers.filter((o) => o !== t).map((o) => row[o]).filter((v) => typeof v === "number");
    if (!others.length) return null;
    return others.reduce((s, v) => s + v, 0) / others.length;
  };

  const topWeight = (weights) => {
    const entries = Object.entries(weights).sort((a, b) => b[1] - a[1]);
    return entries.length ? { ticker: entries[0][0], w: entries[0][1] } : null;
  };
  const nNonTrivial = (weights) => Object.values(weights).filter((w) => w >= 0.005).length;

  // Rank helpers (1 = lowest vol / highest ratio)
  const volSorted = [...assets].sort((a, b) => a.volatility - b.volatility).map((a) => a.ticker);
  const ratioSorted = [...assets].sort((a, b) => (byTicker[b.ticker].ratio) - (byTicker[a.ticker].ratio)).map((a) => a.ticker);
  const half = Math.ceil(assets.length / 2);

  // ---- Min-variance ----
  let minVar = "This mix is tuned to make the portfolio's overall ups and downs as small as possible. It favors stocks that are individually steadier and pairs that don't move in lockstep — blending low-correlation assets cancels out some of the swings.";
  const mvTop = topWeight(result.min_variance_portfolio.weights);
  if (mvTop && byTicker[mvTop.ticker]) {
    const volRank = volSorted.indexOf(mvTop.ticker); // 0 = lowest
    let volPhrase;
    if (volRank === 0) volPhrase = "the lowest historical volatility in the basket";
    else if (volRank < half) volPhrase = "among the lower-volatility names in the basket";
    else volPhrase = "a relatively high volatility on its own";
    const ac = avgCorr(mvTop.ticker);
    const corrPhrase = (ac !== null && ac < 0.4) ? `, and it's fairly weakly correlated with the others (avg ${ac.toFixed(2)}), so it helps damp the whole portfolio's swings` : "";
    const volNote = volRank >= half && corrPhrase
      ? " — it earns its weight through diversification (low correlation) rather than low volatility on its own"
      : "";
    minVar += ` The biggest slice here, <strong>${mvTop.ticker}</strong> at ${(mvTop.w * 100).toFixed(1)}%, has ${volPhrase}${corrPhrase}${volNote}.`;
  }
  minVar += " Because it optimizes purely for stability, it can pile into the calmest names and lean away from higher-return ones — so its expected return is usually the lowest of the two portfolios.";

  // ---- Max-Sharpe ----
  let maxSharpe = "This mix maximizes return <em>per unit of risk</em> (the Sharpe ratio) rather than raw return or raw safety. Stocks that delivered more return for each unit of volatility — and that diversify the basket — get more weight.";
  const msTop = topWeight(result.max_sharpe_portfolio.weights);
  if (msTop && byTicker[msTop.ticker]) {
    const ratioRank = ratioSorted.indexOf(msTop.ticker); // 0 = best
    let ratioPhrase;
    if (ratioRank === 0) ratioPhrase = "the strongest historical return-per-unit-of-risk of the basket";
    else if (ratioRank < half) ratioPhrase = "one of the stronger historical return-per-risk profiles in the basket";
    else ratioPhrase = "a solid return-per-risk profile once its diversification benefit is counted";
    maxSharpe += ` The biggest slice, <strong>${msTop.ticker}</strong> at ${(msTop.w * 100).toFixed(1)}%, had ${ratioPhrase}.`;
  }
  const msCount = nNonTrivial(result.max_sharpe_portfolio.weights);
  if (msCount <= 2 && tickers.length > 2) {
    maxSharpe += ` Notice it concentrates in just ${msCount} of the ${tickers.length} names — mean-variance optimizers often bet heavily on recent winners.`;
  }
  maxSharpe += " These are the weights that looked best <em>on the historical window you chose</em>; they're an in-sample fit, not a forward-looking recommendation, and past performance doesn't guarantee future results.";

  return { minVar, maxSharpe };
}

function renderWeights(containerId, weights) {
  const entries = Object.entries(weights).sort((a, b) => b[1] - a[1]);
  document.getElementById(containerId).innerHTML = entries.map(([ticker, w]) =>
    `<div class="weights-row">
      <span class="w-ticker">${ticker}</span>
      <span class="w-bar-track"><span class="w-bar-fill" style="width:${Math.max(w * 100, 1)}%"></span></span>
      <span class="w-pct">${(w * 100).toFixed(1)}%</span>
    </div>`
  ).join("");
}

function renderCorrelationMatrix(matrix, tickers) {
  let html = `<div class="data-table-wrap"><table class="data-table"><thead><tr><th></th>${tickers.map((t) => `<th>${t}</th>`).join("")}</tr></thead><tbody>`;
  tickers.forEach((rowTicker) => {
    html += `<tr><td class="ticker-cell">${rowTicker}</td>`;
    tickers.forEach((colTicker) => {
      const v = matrix[rowTicker] ? matrix[rowTicker][colTicker] : null;
      html += `<td>${corrCell(v)}</td>`;
    });
    html += "</tr>";
  });
  html += "</tbody></table></div>";
  document.getElementById("opt-correlation-wrap").innerHTML = html;
}

function corrCell(v) {
  if (v === null || v === undefined) return "—";
  const intensity = Math.min(Math.abs(v), 1);
  const bg = v >= 0
    ? `rgba(31, 111, 92, ${0.12 + intensity * 0.55})`
    : `rgba(181, 71, 59, ${0.12 + intensity * 0.55})`;
  return `<span class="corr-cell" style="background:${bg}">${v.toFixed(2)}</span>`;
}

function renderFrontierChart(result) {
  const container = document.getElementById("opt-frontier-chart");
  const width = container.clientWidth || 600;
  const height = 300;
  const padding = { top: 20, right: 30, bottom: 40, left: 55 };

  const allPoints = [
    ...result.efficient_frontier,
    ...result.individual_assets.map((a) => ({ return: a.return, volatility: a.volatility })),
  ];
  const maxVol = Math.max(...allPoints.map((p) => p.volatility)) * 1.1;
  const minRet = Math.min(...allPoints.map((p) => p.return), 0);
  const maxRet = Math.max(...allPoints.map((p) => p.return)) * 1.1;

  const xScale = (vol) => padding.left + (vol / maxVol) * (width - padding.left - padding.right);
  const yScale = (ret) => height - padding.bottom - ((ret - minRet) / (maxRet - minRet)) * (height - padding.top - padding.bottom);

  const frontierSorted = [...result.efficient_frontier].sort((a, b) => a.volatility - b.volatility);
  const frontierPath = frontierSorted.map((p, i) => `${i === 0 ? "M" : "L"} ${xScale(p.volatility)} ${yScale(p.return)}`).join(" ");

  let svg = `<svg width="100%" height="${height}" viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg" font-family="Inter, sans-serif">`;
  svg += `<line x1="${padding.left}" y1="${height - padding.bottom}" x2="${width - padding.right}" y2="${height - padding.bottom}" stroke="#E4E2D9"/>`;
  svg += `<line x1="${padding.left}" y1="${padding.top}" x2="${padding.left}" y2="${height - padding.bottom}" stroke="#E4E2D9"/>`;
  svg += `<text x="${(width) / 2}" y="${height - 8}" text-anchor="middle" font-size="12" fill="#64717D">Volatility, annualized (%) →</text>`;
  svg += `<text x="14" y="${padding.top + 10}" font-size="12" fill="#64717D" transform="rotate(-90 14 ${height/2})" text-anchor="middle">Expected Return, annualized (%) →</text>`;
  svg += `<path d="${frontierPath}" fill="none" stroke="#1F6F5C" stroke-width="2.5"/>`;

  result.individual_assets.forEach((a) => {
    const x = xScale(a.volatility), y = yScale(a.return);
    svg += `<circle cx="${x}" cy="${y}" r="4" fill="#97A1AA"/>`;
    svg += `<text x="${x + 7}" y="${y + 4}" font-size="11" fill="#64717D">${a.ticker}</text>`;
  });

  const mv = result.min_variance_portfolio;
  svg += `<circle cx="${xScale(mv.volatility)}" cy="${yScale(mv.expected_return)}" r="6" fill="#3B6EA5" stroke="#fff" stroke-width="1.5"/>`;
  svg += `<text x="${xScale(mv.volatility) + 9}" y="${yScale(mv.expected_return) - 6}" font-size="11" font-weight="700" fill="#3B6EA5">Min Risk</text>`;

  const ms = result.max_sharpe_portfolio;
  svg += `<circle cx="${xScale(ms.volatility)}" cy="${yScale(ms.expected_return)}" r="6" fill="#B5473B" stroke="#fff" stroke-width="1.5"/>`;
  svg += `<text x="${xScale(ms.volatility) + 9}" y="${yScale(ms.expected_return) - 6}" font-size="11" font-weight="700" fill="#B5473B">Max Sharpe</text>`;

  svg += "</svg>";
  container.innerHTML = svg;
}

// ---------------------------------------------------------------------------
// Chart options helper
// ---------------------------------------------------------------------------
function baseChartOptions(container, priceFormatter) {
  return {
    width: container.clientWidth || 600,
    height: container.clientHeight || 340,
    layout: { background: { color: "#FFFFFF" }, textColor: "#64717D", fontFamily: "IBM Plex Mono, monospace" },
    grid: { vertLines: { color: "#F0EFE8" }, horzLines: { color: "#F0EFE8" } },
    rightPriceScale: { borderColor: "#E4E2D9" },
    timeScale: {
      borderColor: "#E4E2D9",
      fixLeftEdge: true,    // can't pan past the earliest data point
      fixRightEdge: true,   // can't pan into empty space beyond today
      minBarSpacing: 0.5,
    },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    localization: priceFormatter ? { priceFormatter } : undefined,
    // We handle wheel zoom ourselves (below) so we can control the speed —
    // the library exposes only on/off for the wheel, not a sensitivity.
    handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
    handleScale: { mouseWheel: false, pinch: true, axisPressedMouseMove: true, axisDoubleClickReset: true },
  };
}

// Custom mouse-wheel zoom, anchored on the cursor. Higher WHEEL_ZOOM_SPEED = faster.
const WHEEL_ZOOM_SPEED = 0.12;
function attachWheelZoom(container, getChart) {
  container.addEventListener("wheel", (e) => {
    const chart = getChart();
    if (!chart) return;
    e.preventDefault();
    const ts = chart.timeScale();
    const lr = ts.getVisibleLogicalRange();
    if (!lr) return;
    const width = lr.to - lr.from;
    const rect = container.getBoundingClientRect();
    const frac = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    const anchor = lr.from + width * frac;
    const factor = e.deltaY < 0 ? (1 - WHEEL_ZOOM_SPEED) : (1 + WHEEL_ZOOM_SPEED);
    const newWidth = Math.max(width * factor, 3); // don't zoom in tighter than ~3 bars
    try {
      ts.setVisibleLogicalRange({ from: anchor - newWidth * frac, to: anchor + newWidth * (1 - frac) });
    } catch (err) { /* library clamps at data edges */ }
  }, { passive: false });
}

// Keep each chart's canvas filling its (bordered) box exactly — no stray white gaps.
function observeChartSize(container, getChart) {
  if (typeof ResizeObserver === "undefined") return;
  const ro = new ResizeObserver(() => {
    const chart = getChart();
    if (chart && container.clientWidth > 0) chart.resize(container.clientWidth, container.clientHeight);
  });
  ro.observe(container);
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
async function init() {
  try {
    state.metricInfo = await apiGet("/metric-info");
  } catch (err) {
    console.error("Backend not reachable yet:", err);
  }
  syncTopbarHeight();
  initScrollSpy();

  // Attach custom wheel-zoom + auto-resize once to the persistent chart container
  // divs (the charts inside them are recreated on each render; these read the
  // current chart from state each time, so they keep working across re-renders).
  const mainChartEl = document.getElementById("main-chart");
  const btChartEl = document.getElementById("bt-chart");
  attachWheelZoom(mainChartEl, () => state.mainChart);
  attachWheelZoom(btChartEl, () => state.btChart);
  observeChartSize(mainChartEl, () => state.mainChart);
  observeChartSize(btChartEl, () => state.btChart);

  renderMainChart();
  renderMetricsModule();
  await initBacktestModule();
}
init();
