// Read-only view of stored ChartFrames. Nothing here recomputes chanlun or scores.
(function () {
  "use strict";

  const BUY = new Set(["second_buy", "third_buy", "first_buy"]);
  const CHANNELS = ["structure", "location", "resonance", "volatility_volume", "signal_bar", "session"];
  const LABELS = { second_buy: "2B", third_buy: "3B", second_sell: "2S", third_sell: "3S", first_buy: "1B", first_sell: "1S" };
  const state = { symbol: null, timeframe: "15m", chart: null, overlays: [], drawn: null };

  const $ = (id) => document.getElementById(id);
  const seconds = (iso) => Math.floor(Date.parse(iso) / 1000);
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  function cell(row, text, className) {
    const td = document.createElement("td");
    td.textContent = text == null ? "" : String(text);
    if (className) td.className = className;
    row.appendChild(td);
  }

  async function getJson(url) {
    const response = await fetch(url, { cache: "no-store" });
    const body = await response.json();
    return { ok: response.ok, body };
  }

  async function loadBoard() {
    const { body } = await getJson("/api/symbols");
    const rows = $("rows");
    rows.replaceChildren();
    $("board-empty").hidden = body.length > 0;
    for (const item of body) {
      const tr = document.createElement("tr");
      if (item.outside_universe) tr.className = "outside";
      if (item.symbol === state.symbol) tr.classList.add("selected");
      cell(tr, item.outside_universe ? "outside_universe" : item.rank);
      cell(tr, item.symbol);
      cell(tr, item.bias_4h || "—");
      cell(tr, item.last_action || "—");
      cell(tr, item.holding ? "●" : "");
      tr.addEventListener("click", () => select(item.symbol));
      rows.appendChild(tr);
    }
    if (!state.symbol && body.length) select(body[0].symbol);
    $("updated").textContent = "更新 " + new Date().toLocaleTimeString();
  }

  function ensureChart() {
    if (state.chart) return state.chart;
    const host = $("chart");
    state.chart = LightweightCharts.createChart(host, {
      autoSize: true,
      layout: { background: { color: css("--panel") }, textColor: css("--text") },
      grid: { vertLines: { color: css("--line") }, horzLines: { color: css("--line") } },
      timeScale: { timeVisible: true, secondsVisible: false },
    });
    return state.chart;
  }

  function clearOverlays() {
    for (const series of state.overlays) state.chart.removeSeries(series);
    state.overlays = [];
  }

  function line(points, options) {
    const series = state.chart.addLineSeries(Object.assign({ lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false }, options));
    series.setData(points);
    state.overlays.push(series);
    return series;
  }

  function biPoints(bis, first) {
    const byTime = new Map();
    for (const bi of bis) {
      byTime.set(seconds(bi.start_time), bi.start_price);
      byTime.set(seconds(bi.end_time), bi.end_price);
    }
    return [...byTime.entries()]
      .filter(([time]) => time >= first)
      .sort((a, b) => a[0] - b[0])
      .map(([time, value]) => ({ time, value }));
  }

  function draw(frame, fit) {
    const chart = ensureChart();
    clearOverlays();
    const candles = frame.bars.map((bar) => ({
      time: seconds(bar.open_time), open: bar.open, high: bar.high, low: bar.low, close: bar.close,
    }));
    const price = chart.addCandlestickSeries({ upColor: css("--buy"), downColor: css("--sell"), borderVisible: false, wickUpColor: css("--buy"), wickDownColor: css("--sell") });
    price.setData(candles);
    state.overlays.push(price);
    const first = candles.length ? candles[0].time : 0;
    const last = candles.length ? candles[candles.length - 1].time : 0;

    const points = biPoints(frame.bis, first);
    if (points.length > 1) line(points, { color: css("--accent"), lineWidth: 2 });

    for (const zs of frame.zhongshus) {
      const start = Math.max(seconds(zs.start_time), first);
      const end = Math.min(seconds(zs.end_time), last);
      if (end <= start) continue;
      for (const level of [zs.zg, zs.zd]) {
        line([{ time: start, value: level }, { time: end, value: level }], { color: "#f0a020", lineWidth: 1 });
      }
    }

    const markers = frame.signals
      .map((signal) => ({ time: seconds(signal.bar_open_time), signal }))
      .filter((item) => item.time >= first)
      .sort((a, b) => a.time - b.time)
      .map(({ time, signal }) => {
        const buy = BUY.has(signal.type);
        return {
          time,
          position: buy ? "belowBar" : "aboveBar",
          color: buy ? css("--buy") : css("--sell"),
          shape: buy ? "arrowUp" : "arrowDown",
          text: LABELS[signal.type] || signal.type,
        };
      });
    price.setMarkers(markers);

    if (frame.position) {
      price.createPriceLine({ price: frame.position.avg_price, color: css("--accent"), lineWidth: 1, title: "avg" });
    }
    if (frame.stop_price != null) {
      price.createPriceLine({ price: frame.stop_price, color: css("--sell"), lineWidth: 1, lineStyle: 2, title: "stop" });
    }
    if (fit) chart.timeScale().fitContent();
  }

  function showJev(frame) {
    const assessment = frame ? frame.assessment : null;
    $("proposed").textContent = assessment ? assessment.proposed_action : "—";
    $("score").textContent = assessment ? Number(assessment.score).toFixed(4) : "—";
    $("vetoes").textContent = frame && frame.veto_codes && frame.veto_codes.length ? frame.veto_codes.join(", ") : "—";
    const body = $("channels");
    body.replaceChildren();
    for (const name of CHANNELS) {
      const tr = document.createElement("tr");
      const component = assessment ? assessment.components[name] : null;
      cell(tr, name);
      cell(tr, component ? Number(component.adjusted).toFixed(3) : "");
      body.appendChild(tr);
    }
  }

  async function loadFrame() {
    if (!state.symbol) return;
    const url = "/api/frame?symbol=" + encodeURIComponent(state.symbol) + "&timeframe=" + state.timeframe;
    const { ok, body } = await getJson(url);
    $("title").textContent = state.symbol;
    $("no-frame").hidden = ok;
    $("chart").hidden = !ok;
    if (!ok) {
      $("bias").textContent = "";
      showJev(null);
      return;
    }
    $("bias").textContent = body.structure_bias + " · " + body.last_action;
    const key = state.symbol + "|" + state.timeframe;
    draw(body, state.drawn !== key);
    state.drawn = key;
    if (state.timeframe === "15m") {
      showJev(body);
    } else {
      const m15 = await getJson("/api/frame?symbol=" + encodeURIComponent(state.symbol) + "&timeframe=15m");
      showJev(m15.ok ? m15.body : null);
    }
  }

  function select(symbol) {
    state.symbol = symbol;
    for (const tr of $("rows").children) tr.classList.toggle("selected", tr.children[1].textContent === symbol);
    loadFrame();
  }

  for (const button of document.querySelectorAll("#timeframes button")) {
    button.addEventListener("click", () => {
      state.timeframe = button.dataset.tf;
      for (const other of document.querySelectorAll("#timeframes button")) other.classList.toggle("active", other === button);
      loadFrame();
    });
  }

  async function refresh() {
    try {
      await loadBoard();
      await loadFrame();
    } catch (error) {
      $("updated").textContent = "讀取失敗";
    }
  }

  refresh();
  setInterval(refresh, 15000);
})();
