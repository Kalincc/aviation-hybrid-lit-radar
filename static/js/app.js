/* ==========================================================================
   Aviation Hybrid Lit Radar — app.js
   纯静态实现：无构建、无第三方库、所有图表为手写 inline SVG。
   数据只来自后端 /api/*；所有服务端文本一律通过 textContent 写入。
   ========================================================================== */
(function () {
  'use strict';

  /* ------------------------------------------------------------------ *
   * 1. 常量
   * ------------------------------------------------------------------ */
  var DEFAULT_DAYS = 90;
  var PAGE_SIZE = 12;
  var DAY_OPTIONS = [7, 30, 90, 180, 0];
  var FETCH_TIMEOUT = 15000;
  var REFRESH_TIMEOUT = 200000; // 刷新接口同步执行，最长 180s
  var SEARCH_DEBOUNCE = 300;
  var TOAST_DURATION = 3000;
  var RUN_LIMIT = 3;
  var MONTH_LIMIT = 12;
  var TAG_LIMIT = 7;

  var SOURCE_FALLBACK = {
    arxiv: 'arXiv',
    openalex: 'OpenAlex',
    semantic_scholar: 'Semantic Scholar'
  };

  /* ------------------------------------------------------------------ *
   * 2. 状态
   * ------------------------------------------------------------------ */
  var state = {
    days: DEFAULT_DAYS,
    q: '',
    openSource: '',
    source: '',
    sort: 'date_desc',
    page: 1,
    pageSize: PAGE_SIZE,
    total: 0,
    items: [],
    meta: null,
    stats: null,
    runs: [],
    recent30: null,
    view: 'loading',
    refreshing: false,
    loadingAll: false,
    seq: { meta: 0, papers: 0, stats: 0, runs: 0, recent30: 0 }
  };

  var loadErrors = { meta: null, papers: null, stats: null };
  var searchTimer = null;
  var toastTimer = null;

  /* ------------------------------------------------------------------ *
   * 3. DOM 引用
   * ------------------------------------------------------------------ */
  var progressBar = document.getElementById('progress-bar');
  var lastUpdateText = document.getElementById('last-update-text');
  var daysControl = document.getElementById('days-control');
  var refreshBtn = document.getElementById('refresh-btn');
  var refreshLabel = document.getElementById('refresh-label');
  var keyNotice = document.getElementById('key-notice');

  var errorBanner = document.getElementById('error-banner');
  var errorMessage = document.getElementById('error-message');
  var retryBtn = document.getElementById('retry-btn');

  var statTotal = document.getElementById('stat-total');
  var statTotalSub = document.getElementById('stat-total-sub');
  var statOpen = document.getElementById('stat-open');
  var statOpenSub = document.getElementById('stat-open-sub');
  var statRecent = document.getElementById('stat-recent');
  var statRecentSub = document.getElementById('stat-recent-sub');
  var statLatest = document.getElementById('stat-latest');
  var statLatestSub = document.getElementById('stat-latest-sub');

  var searchInput = document.getElementById('search-input');
  var sortSelect = document.getElementById('sort-select');
  var openChips = document.getElementById('open-chips');
  var sourceChips = document.getElementById('source-chips');
  var resultsMeta = document.getElementById('results-meta');
  var resultsRegion = document.getElementById('results-region');
  var listCol = document.getElementById('list-col');
  var pagination = document.getElementById('pagination');
  var prevPage = document.getElementById('prev-page');
  var nextPage = document.getElementById('next-page');
  var pageInfo = document.getElementById('page-info');

  var chartMonth = document.getElementById('chart-month');
  var chartTags = document.getElementById('chart-tags');
  var chartDonut = document.getElementById('chart-donut');
  var chartRuns = document.getElementById('chart-runs');

  var toast = document.getElementById('toast');

  /* ------------------------------------------------------------------ *
   * 4. 通用工具
   * ------------------------------------------------------------------ */
  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function pad2(n) {
    return n < 10 ? '0' + n : String(n);
  }

  function parseDate(value) {
    if (typeof value !== 'string' || !value) return null;
    var dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
    if (dateOnly) {
      return new Date(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3]));
    }
    var d = new Date(value);
    return isNaN(d.getTime()) ? null : d;
  }

  function formatDate(value) {
    if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}/.test(value)) {
      return value.slice(0, 10);
    }
    var d = parseDate(value);
    if (!d) return '日期未知';
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
  }

  function formatMonthDay(value) {
    var d = parseDate(value);
    if (!d) return null;
    return pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
  }

  function formatDateTime(value) {
    var d = parseDate(value);
    if (!d) return null;
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()) +
      ' ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes());
  }

  function formatRunTime(value) {
    var d = parseDate(value);
    if (!d) return '—';
    return pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()) +
      ' ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes());
  }

  function normalizeText(value) {
    if (value === undefined || value === null) return '';
    return String(value).replace(/\s+/g, ' ').trim();
  }

  function asStringList(value) {
    var list = [];
    if (Array.isArray(value)) {
      list = value;
    } else if (typeof value === 'string') {
      list = value.split(/[,;，；]/);
    }
    var result = [];
    for (var i = 0; i < list.length; i += 1) {
      var item = normalizeText(list[i]);
      if (item) result.push(item);
    }
    return result;
  }

  function toCount(value) {
    var n = Number(value);
    return Number.isFinite(n) && n > 0 ? Math.round(n) : 0;
  }

  function finiteNumber(value) {
    var n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  function truncateText(value, maxLength) {
    var s = String(value || '');
    if (s.length <= maxLength) return s;
    return s.slice(0, Math.max(1, maxLength - 1)) + '…';
  }

  function safeHttpUrl(value) {
    if (typeof value !== 'string') return '';
    var raw = value.trim();
    if (!/^https?:\/\//i.test(raw)) return '';
    try {
      var u = new URL(raw);
      if (u.protocol !== 'http:' && u.protocol !== 'https:') return '';
      return u.href;
    } catch (err) {
      return '';
    }
  }

  function cloneTemplate(id) {
    var tpl = document.getElementById(id);
    if (!tpl || !tpl.content) return document.createDocumentFragment();
    return document.importNode(tpl.content, true);
  }

  function prefersReducedMotion() {
    return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  }

  function scrollToList() {
    if (!listCol || typeof listCol.scrollIntoView !== 'function') return;
    try {
      listCol.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' });
    } catch (err) {
      listCol.scrollIntoView();
    }
  }

  /* ------------------------------------------------------------------ *
   * 5. 内联图标（Lucide 线性风格；禁止 emoji）
   * ------------------------------------------------------------------ */
  var SVG_NS = 'http://www.w3.org/2000/svg';

  var ICONS = {
    check: [['path', { d: 'M20 6 9 17l-5-5' }]],
    x: [['path', { d: 'M18 6 6 18' }], ['path', { d: 'm6 6 12 12' }]],
    question: [
      ['circle', { cx: 12, cy: 12, r: 9 }],
      ['path', { d: 'M9.1 9a3 3 0 0 1 5.8 1c0 2-3 2.2-3 4' }],
      ['path', { d: 'M12 17h.01' }]
    ],
    'external-link': [
      ['path', { d: 'M15 3h6v6' }],
      ['path', { d: 'M10 14 21 3' }],
      ['path', { d: 'M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6' }]
    ],
    copy: [
      ['rect', { x: 9, y: 9, width: 12, height: 12, rx: 2 }],
      ['path', { d: 'M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1' }]
    ],
    'chevron-down': [['path', { d: 'm6 9 6 6 6-6' }]]
  };

  function svgIcon(name, size, extraClass) {
    var defs = ICONS[name] || ICONS.check;
    var svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('width', String(size || 16));
    svg.setAttribute('height', String(size || 16));
    svg.setAttribute('class', 'icon' + (extraClass ? ' ' + extraClass : ''));
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    for (var i = 0; i < defs.length; i += 1) {
      var node = document.createElementNS(SVG_NS, defs[i][0]);
      var attrs = defs[i][1] || {};
      Object.keys(attrs).forEach(function (key) {
        node.setAttribute(key, String(attrs[key]));
      });
      svg.appendChild(node);
    }
    return svg;
  }

  /* ------------------------------------------------------------------ *
   * 6. SVG 图表基础工具
   * ------------------------------------------------------------------ */
  function svgEl(tag, attrs) {
    var node = document.createElementNS(SVG_NS, tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (key) {
        node.setAttribute(key, String(attrs[key]));
      });
    }
    return node;
  }

  function svgText(parent, x, y, text, className) {
    var t = svgEl('text', { x: x, y: y });
    if (className) t.setAttribute('class', className);
    t.textContent = String(text);
    parent.appendChild(t);
    return t;
  }

  function svgTitle(text) {
    var t = document.createElementNS(SVG_NS, 'title');
    t.textContent = String(text);
    return t;
  }

  function svgRoot(width, height, ariaLabel) {
    var svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
    svg.setAttribute('class', 'chart-svg');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', ariaLabel);
    return svg;
  }

  function chartEmpty(container, text) {
    container.textContent = '';
    container.appendChild(el('p', 'chart-empty', text || '暂无数据'));
  }

  /* ------------------------------------------------------------------ *
   * 7. API 请求
   * ------------------------------------------------------------------ */
  function ApiError(message, status) {
    this.name = 'ApiError';
    this.message = message;
    this.status = status || 0;
  }
  ApiError.prototype = Object.create(Error.prototype);
  ApiError.prototype.constructor = ApiError;

  async function requestJson(path, options) {
    var opts = options || {};
    var controller = new AbortController();
    var timeout = opts.timeout || FETCH_TIMEOUT;
    var timer = setTimeout(function () {
      controller.abort();
    }, timeout);

    try {
      var headers = { Accept: 'application/json' };
      var init = {
        method: opts.method || 'GET',
        headers: headers,
        signal: controller.signal,
        cache: 'no-store'
      };
      if (opts.body !== undefined) {
        headers['Content-Type'] = 'application/json';
        init.body = JSON.stringify(opts.body);
      }

      var response;
      try {
        response = await fetch(path, init);
      } catch (err) {
        if (controller.signal.aborted) throw new ApiError('请求超时，请稍后重试', 0);
        throw new ApiError('无法连接后端服务', 0);
      }

      var payload = null;
      try {
        payload = await response.json();
      } catch (err) {
        payload = null;
      }

      if (!response.ok) {
        var detail = payload && payload.detail;
        var message = '';
        if (typeof detail === 'string') {
          message = detail;
        } else if (detail && typeof detail === 'object' && typeof detail.message === 'string') {
          message = detail.message;
        }
        throw new ApiError(message || ('请求失败（HTTP ' + response.status + '）'), response.status);
      }

      return payload;
    } finally {
      clearTimeout(timer);
    }
  }

  /* ------------------------------------------------------------------ *
   * 8. 错误横幅 / toast / 加载态
   * ------------------------------------------------------------------ */
  function renderErrorBanner() {
    var message = loadErrors.meta || loadErrors.papers || loadErrors.stats;
    if (message) {
      errorMessage.textContent = '数据加载失败：' + message;
      errorBanner.hidden = false;
    } else {
      errorBanner.hidden = true;
    }
  }

  function setLoadError(key, message) {
    loadErrors[key] = message || '未知错误';
    renderErrorBanner();
  }

  function clearLoadError(key) {
    if (!loadErrors[key]) return;
    loadErrors[key] = null;
    renderErrorBanner();
  }

  function clearAllErrors() {
    loadErrors.meta = null;
    loadErrors.papers = null;
    loadErrors.stats = null;
    renderErrorBanner();
  }

  function showToast(message, isError) {
    toast.textContent = message;
    if (isError) toast.classList.add('toast--error');
    else toast.classList.remove('toast--error');
    toast.classList.add('is-visible');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      toast.classList.remove('is-visible');
    }, TOAST_DURATION);
  }

  function setRefreshBusy(busy) {
    state.refreshing = busy;
    refreshBtn.disabled = busy;
    if (busy) {
      refreshBtn.setAttribute('aria-busy', 'true');
      refreshLabel.textContent = '抓取中…';
      progressBar.hidden = false;
    } else {
      refreshBtn.removeAttribute('aria-busy');
      refreshLabel.textContent = '刷新数据';
      progressBar.hidden = true;
    }
  }

  function setResultsMetaLoading() {
    resultsMeta.classList.remove('is-error');
    resultsMeta.textContent = '正在加载文献…';
  }

  function updateResultsMeta() {
    resultsMeta.classList.remove('is-error');
    var text = '共 ' + state.total + ' 篇 · ' +
      (state.days > 0 ? '时间窗口 ' + state.days + ' 天' : '全部时间');
    if (state.q) text += ' · 关键词 “' + state.q + '”';
    resultsMeta.textContent = text;
  }

  /* ------------------------------------------------------------------ *
   * 9. 骨架屏
   * ------------------------------------------------------------------ */
  function showListSkeleton() {
    state.view = 'loading';
    resultsRegion.classList.remove('is-updating');
    resultsRegion.setAttribute('aria-busy', 'true');
    resultsRegion.textContent = '';
    for (var i = 0; i < 3; i += 1) {
      resultsRegion.appendChild(cloneTemplate('tpl-skeleton-card'));
    }
    pagination.hidden = true;
  }

  function renderStatsSkeleton() {
    var nodes = [statTotal, statOpen, statRecent, statLatest];
    for (var i = 0; i < nodes.length; i += 1) {
      var node = nodes[i];
      node.textContent = '';
      node.setAttribute('aria-busy', 'true');
      var skeleton = el('span', 'skeleton skeleton--value');
      skeleton.setAttribute('aria-hidden', 'true');
      node.appendChild(skeleton);
      node.appendChild(el('span', 'visually-hidden', '加载中'));
    }
    statTotalSub.textContent = '当前时间窗口';
    statOpenSub.textContent = '按提取结果';
    statRecentSub.textContent = '按发表时间';
    statLatestSub.textContent = '最新一篇';
  }

  function buildChartSkeleton(container, kind) {
    container.textContent = '';
    var wrap = el('div', 'chart-skeleton');
    wrap.setAttribute('aria-hidden', 'true');
    if (kind === 'runs') {
      wrap.appendChild(el('span', 'skeleton skeleton--chart-line'));
      wrap.appendChild(el('span', 'skeleton skeleton--chart-line skeleton--w70'));
      wrap.appendChild(el('span', 'skeleton skeleton--chart-line skeleton--w90'));
    } else {
      wrap.appendChild(el('span', 'skeleton skeleton--chart-lg'));
      wrap.appendChild(el('span', 'skeleton skeleton--chart-line skeleton--w90'));
      wrap.appendChild(el('span', 'skeleton skeleton--chart-line skeleton--w70'));
    }
    container.appendChild(wrap);
  }

  function showChartSkeletons() {
    buildChartSkeleton(chartMonth, 'chart');
    buildChartSkeleton(chartTags, 'chart');
    buildChartSkeleton(chartDonut, 'chart');
    buildChartSkeleton(chartRuns, 'runs');
  }

  function showPageSkeleton() {
    renderStatsSkeleton();
    showChartSkeletons();
    showListSkeleton();
    setResultsMetaLoading();
  }

  /* ------------------------------------------------------------------ *
   * 10. 元数据 / 顶栏
   * ------------------------------------------------------------------ */
  function applyMeta(initial) {
    var meta = state.meta;
    if (initial) {
      var defaultDays = Number(meta && meta.default_days);
      state.days = DAY_OPTIONS.indexOf(defaultDays) !== -1 ? defaultDays : DEFAULT_DAYS;
    }
    syncDays();
    updateLastUpdate();
    updateKeyNotice();
    renderSourceChips();
  }

  function updateLastUpdate() {
    var meta = state.meta;
    var formatted = meta && meta.last_refresh ? formatDateTime(meta.last_refresh) : null;
    lastUpdateText.textContent = formatted ? '最后更新 ' + formatted : '最后更新 —';
  }

  function updateKeyNotice() {
    var llm = state.meta && state.meta.llm;
    var heuristicOnly = !!(llm && llm.enabled === false);
    keyNotice.hidden = !heuristicOnly;
  }

  function sourceLabelFor(id, provided) {
    var label = normalizeText(provided);
    if (label) return label;
    return SOURCE_FALLBACK[id] || String(id || '未知来源');
  }

  function syncDays() {
    var buttons = daysControl.querySelectorAll('button[data-days]');
    Array.prototype.forEach.call(buttons, function (btn) {
      var days = parseInt(btn.getAttribute('data-days'), 10);
      var active = days === state.days;
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
      btn.classList.toggle('is-active', active);
    });
  }

  function renderSourceChips() {
    var meta = state.meta;
    var sources = meta && Array.isArray(meta.sources) ? meta.sources : [];
    var items = [];
    sources.forEach(function (item) {
      if (!item || !item.id) return;
      var id = String(item.id);
      items.push({
        id: id,
        label: sourceLabelFor(id, item.label),
        enabled: item.enabled !== false
      });
    });
    if (!items.length) {
      Object.keys(SOURCE_FALLBACK).forEach(function (id) {
        items.push({ id: id, label: SOURCE_FALLBACK[id], enabled: true });
      });
    }

    var ids = items.map(function (item) { return item.id; });
    if (state.source && ids.indexOf(state.source) === -1) state.source = '';

    sourceChips.textContent = '';
    var allBtn = el('button', 'chip', '全部');
    allBtn.type = 'button';
    allBtn.setAttribute('data-source', '');
    allBtn.setAttribute('aria-pressed', state.source === '' ? 'true' : 'false');
    if (state.source === '') allBtn.classList.add('is-active');
    sourceChips.appendChild(allBtn);

    items.forEach(function (item) {
      var btn = el('button', 'chip', item.label);
      btn.type = 'button';
      btn.setAttribute('data-source', item.id);
      var active = state.source === item.id;
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
      if (active) btn.classList.add('is-active');
      if (!item.enabled) {
        btn.disabled = true;
        btn.title = '该来源暂未启用';
      }
      sourceChips.appendChild(btn);
    });
  }

  /* ------------------------------------------------------------------ *
   * 11. 统计卡
   * ------------------------------------------------------------------ */
  function setStat(node, subNode, value, subText) {
    node.setAttribute('aria-busy', 'false');
    node.textContent = value;
    subNode.textContent = subText;
  }

  function renderRecentStat() {
    if (state.recent30 === null) {
      setStat(statRecent, statRecentSub, '—', '按发表时间');
    } else {
      setStat(statRecent, statRecentSub, state.recent30, '按发表时间');
    }
  }

  function renderStats() {
    var stats = state.stats;
    if (!stats) {
      renderStatsUnavailable();
      return;
    }

    var total = finiteNumber(stats.total);
    setStat(
      statTotal,
      statTotalSub,
      total === null ? '—' : total,
      state.days > 0 ? '时间窗口 ' + state.days + ' 天' : '全部时间'
    );

    var ratio = stats.open_source_ratio || {};
    var yes = toCount(ratio.yes);
    var no = toCount(ratio.no);
    var unknown = toCount(ratio.unknown);
    var denominator = yes + no + unknown;
    if (denominator > 0) {
      var percent = Math.round((yes / denominator) * 100);
      setStat(statOpen, statOpenSub, percent + '%', '开源 ' + yes + ' / 共 ' + denominator);
    } else {
      setStat(statOpen, statOpenSub, '—', '暂无提取数据');
    }

    renderRecentStat();

    var latest = stats.latest_published ? formatMonthDay(stats.latest_published) : null;
    setStat(statLatest, statLatestSub, latest || '—', '最新一篇');
  }

  function renderStatsUnavailable() {
    setStat(statTotal, statTotalSub, '—', '暂无数据');
    setStat(statOpen, statOpenSub, '—', '暂无数据');
    setStat(statRecent, statRecentSub, '—', '暂无数据');
    setStat(statLatest, statLatestSub, '—', '暂无数据');
  }

  /* ------------------------------------------------------------------ *
   * 12. 图表：月度趋势 / 标签分布 / 开源环形图 / 抓取记录
   * ------------------------------------------------------------------ */
  function buildMonthSeries(rows) {
    var data = [];
    rows.forEach(function (row) {
      if (!row) return;
      var month = String(row.month || '');
      if (!/^\d{4}-\d{2}$/.test(month)) return;
      var monthNumber = Number(month.slice(5, 7));
      if (monthNumber < 1 || monthNumber > 12) return;
      data.push({ month: month, count: toCount(row.count) });
    });
    if (!data.length) return [];
    data.sort(function (a, b) {
      return a.month < b.month ? -1 : a.month > b.month ? 1 : 0;
    });

    var firstYear = Number(data[0].month.slice(0, 4));
    var firstMonth = Number(data[0].month.slice(5, 7));
    var lastYear = Number(data[data.length - 1].month.slice(0, 4));
    var lastMonth = Number(data[data.length - 1].month.slice(5, 7));
    var totalMonths = (lastYear - firstYear) * 12 + (lastMonth - firstMonth) + 1;
    if (!Number.isFinite(totalMonths) || totalMonths <= 0) return data.slice(-MONTH_LIMIT);
    if (totalMonths > 240) return data.slice(-MONTH_LIMIT);

    var counts = {};
    data.forEach(function (item) { counts[item.month] = item.count; });

    var series = [];
    var year = firstYear;
    var month = firstMonth;
    while (year < lastYear || (year === lastYear && month <= lastMonth)) {
      var key = year + '-' + pad2(month);
      series.push({ month: key, count: counts[key] || 0 });
      month += 1;
      if (month > 12) {
        month = 1;
        year += 1;
      }
    }
    return series.slice(-MONTH_LIMIT);
  }

  function renderMonthChart() {
    var stats = state.stats;
    var rows = stats && Array.isArray(stats.by_month) ? stats.by_month : [];
    var series = buildMonthSeries(rows);
    if (!series.length) {
      chartEmpty(chartMonth);
      return;
    }

    var max = 1;
    series.forEach(function (item) {
      if (item.count > max) max = item.count;
    });

    var width = 320;
    var height = 170;
    var left = 10;
    var right = 10;
    var top = 22;
    var bottom = 22;
    var plotWidth = width - left - right;
    var plotHeight = height - top - bottom;
    var baseY = top + plotHeight;
    var slot = plotWidth / series.length;
    var barWidth = Math.min(30, slot * 0.62);

    var total = 0;
    var peak = series[0];
    series.forEach(function (item) {
      total += item.count;
      if (item.count > peak.count) peak = item;
    });

    var label = '按发表月份文献数柱状图，' + series[0].month + ' 至 ' +
      series[series.length - 1].month + '，共 ' + total + ' 篇，最高 ' +
      peak.month + ' 的 ' + peak.count + ' 篇。';
    var svg = svgRoot(width, height, label);
    svg.appendChild(svgEl('line', {
      x1: left, y1: baseY, x2: width - right, y2: baseY, 'class': 'chart-axis'
    }));

    series.forEach(function (item, index) {
      var x = left + index * slot + (slot - barWidth) / 2;
      if (item.count > 0) {
        var barHeight = Math.max(2, (item.count / max) * plotHeight);
        var rect = svgEl('rect', {
          x: x,
          y: baseY - barHeight,
          width: barWidth,
          height: barHeight,
          rx: Math.min(3, barWidth / 2),
          'class': 'chart-bar'
        });
        rect.appendChild(svgTitle(item.month + ' · ' + item.count + ' 篇'));
        svg.appendChild(rect);
        svgText(svg, x + barWidth / 2, baseY - barHeight - 4, item.count, 'chart-value');
      }
      svgText(svg, x + barWidth / 2, height - 6, item.month.slice(5), 'chart-label');
    });

    chartMonth.textContent = '';
    chartMonth.appendChild(svg);
  }

  function renderTagChart() {
    var stats = state.stats;
    var rows = stats && Array.isArray(stats.by_tag) ? stats.by_tag : [];
    var data = [];
    rows.forEach(function (row) {
      if (!row) return;
      var tag = normalizeText(row.tag);
      if (!tag) return;
      data.push({ tag: tag, count: toCount(row.count) });
    });
    data = data.slice(0, TAG_LIMIT);
    if (!data.length) {
      chartEmpty(chartTags);
      return;
    }

    var max = 1;
    data.forEach(function (item) {
      if (item.count > max) max = item.count;
    });

    var width = 320;
    var rowHeight = 22;
    var padTop = 8;
    var padBottom = 8;
    var height = padTop + data.length * rowHeight + padBottom;
    var labelWidth = 104;
    var trackX = 108;
    var trackWidth = 160;
    var countX = 318;

    var aria = '标签分布条形图：' + data.map(function (item) {
      return item.tag + ' ' + item.count + ' 篇';
    }).join('，') + '。';
    var svg = svgRoot(width, height, aria);

    data.forEach(function (item, index) {
      var trackY = padTop + index * rowHeight + 7;
      var labelNode = svgText(svg, 2, trackY + 8, truncateText(item.tag, 8), 'chart-tag-label');
      labelNode.appendChild(svgTitle(item.tag + ' · ' + item.count + ' 篇'));
      svg.appendChild(svgEl('rect', {
        x: trackX, y: trackY, width: trackWidth, height: 8, rx: 4, 'class': 'chart-track'
      }));
      if (item.count > 0) {
        var barWidth = Math.max(2, (item.count / max) * trackWidth);
        var rect = svgEl('rect', {
          x: trackX, y: trackY, width: barWidth, height: 8, rx: 4,
          'class': 'chart-bar chart-bar--h'
        });
        rect.appendChild(svgTitle(item.tag + ' · ' + item.count + ' 篇'));
        svg.appendChild(rect);
      }
      svgText(svg, countX, trackY + 8, item.count, 'chart-tag-count');
    });

    chartTags.textContent = '';
    chartTags.appendChild(svg);
  }

  function renderDonut() {
    var stats = state.stats;
    var ratio = stats && stats.open_source_ratio;
    var yes = toCount(ratio && ratio.yes);
    var no = toCount(ratio && ratio.no);
    var unknown = toCount(ratio && ratio.unknown);
    var total = yes + no + unknown;
    if (total <= 0) {
      chartEmpty(chartDonut);
      return;
    }

    var width = 320;
    var height = 176;
    var cx = 160;
    var cy = 78;
    var radius = 52;
    var strokeWidth = 20;
    var circumference = 2 * Math.PI * radius;

    var svg = svgRoot(width, height,
      '开源状态环形图：开源 ' + yes + ' 篇，闭源 ' + no + ' 篇，未知 ' + unknown + ' 篇，共 ' + total + ' 篇。');
    svg.appendChild(svgEl('circle', {
      cx: cx, cy: cy, r: radius, 'class': 'donut-track'
    }));

    var segments = [
      { label: '开源', value: yes, className: 'donut-seg donut-seg--yes' },
      { label: '闭源', value: no, className: 'donut-seg donut-seg--no' },
      { label: '未知', value: unknown, className: 'donut-seg donut-seg--unknown' }
    ];

    var offset = 0;
    segments.forEach(function (segment) {
      if (segment.value <= 0) return;
      var length = (segment.value / total) * circumference;
      var circle = svgEl('circle', {
        cx: cx,
        cy: cy,
        r: radius,
        'class': segment.className,
        'stroke-dasharray': length + ' ' + (circumference - length),
        'stroke-dashoffset': String(-offset),
        transform: 'rotate(-90 ' + cx + ' ' + cy + ')'
      });
      circle.appendChild(svgTitle(segment.label + ' ' + segment.value + ' 篇（' +
        Math.round((segment.value / total) * 100) + '%）'));
      svg.appendChild(circle);
      offset += length;
    });

    var totalLabel = svgText(svg, cx, cy + 4, total, 'donut-total');
    if (String(total).length > 4) totalLabel.setAttribute('font-size', '22');
    svgText(svg, cx, cy + 24, '篇', 'donut-unit');

    chartDonut.textContent = '';
    chartDonut.appendChild(svg);

    var legend = el('div', 'donut-legend');
    var legendItems = [
      { label: '开源', value: yes, dotClass: 'donut-dot donut-dot--yes' },
      { label: '闭源', value: no, dotClass: 'donut-dot donut-dot--no' },
      { label: '未知', value: unknown, dotClass: 'donut-dot donut-dot--unknown' }
    ];
    legendItems.forEach(function (item) {
      var row = el('div', 'donut-legend__item');
      var dot = el('span', item.dotClass);
      dot.setAttribute('aria-hidden', 'true');
      row.appendChild(dot);
      row.appendChild(el('span', 'donut-legend__label', item.label));
      var percent = total > 0 ? Math.round((item.value / total) * 100) : 0;
      row.appendChild(el('span', 'donut-legend__value', item.value + ' · ' + percent + '%'));
      legend.appendChild(row);
    });
    chartDonut.appendChild(legend);
  }

  function runStatusLabel(status) {
    if (status === 'success') return '成功';
    if (status === 'partial') return '部分成功';
    if (status === 'error') return '失败';
    return '进行中';
  }

  function runDotClass(status) {
    if (status === 'success') return 'run-dot--success';
    if (status === 'partial') return 'run-dot--partial';
    if (status === 'error') return 'run-dot--error';
    return 'run-dot--running';
  }

  function renderRuns() {
    var runs = Array.isArray(state.runs) ? state.runs : [];
    if (!runs.length) {
      chartEmpty(chartRuns, '暂无抓取记录');
      return;
    }

    var list = el('ul', 'run-list');
    list.setAttribute('aria-label', '最近抓取记录');
    runs.slice(0, RUN_LIMIT).forEach(function (run) {
      var item = el('li', 'run-item');
      var status = normalizeText(run && run.status);

      var top = el('div', 'run-item__top');
      var dot = el('span', 'run-dot ' + runDotClass(status));
      dot.setAttribute('aria-hidden', 'true');
      top.appendChild(dot);
      top.appendChild(el('span', 'run-item__status', runStatusLabel(status)));
      top.appendChild(el('span', 'run-item__time',
        formatRunTime(run && (run.finished_at || run.started_at))));
      item.appendChild(top);

      item.appendChild(el('p', 'run-item__meta',
        '抓取 ' + toCount(run && run.fetched) +
        ' · 入库 ' + toCount(run && run.inserted) +
        ' · 提取 ' + toCount(run && run.extracted)));
      list.appendChild(item);
    });

    chartRuns.textContent = '';
    chartRuns.appendChild(list);
  }

  function renderStatsCharts() {
    renderMonthChart();
    renderTagChart();
    renderDonut();
  }

  function renderChartsUnavailable() {
    chartEmpty(chartMonth);
    chartEmpty(chartTags);
    chartEmpty(chartDonut);
  }

  /* ------------------------------------------------------------------ *
   * 13. 文献卡片
   * ------------------------------------------------------------------ */
  function sourceBadgeClass(source) {
    if (source === 'arxiv') return 'badge--source-arxiv';
    if (source === 'openalex') return 'badge--source-openalex';
    if (source === 'semantic_scholar' || source === 's2') return 'badge--source-s2';
    return 'badge--source-other';
  }

  function openBadge(value) {
    var map = {
      yes: { className: 'badge--open-yes', label: '开源', icon: 'check' },
      no: { className: 'badge--open-no', label: '闭源', icon: 'x' },
      unknown: { className: 'badge--open-unknown', label: '未知', icon: 'question' }
    };
    var item = map[value] || map.unknown;
    var badge = el('span', 'badge ' + item.className);
    badge.appendChild(svgIcon(item.icon, 12));
    badge.appendChild(document.createTextNode(item.label));
    badge.title = '代码开源状态：' + item.label;
    return badge;
  }

  function modeBadge(mode) {
    var isLlm = mode === 'llm';
    var badge = el('span', 'badge ' + (isLlm ? 'badge--mode-llm' : 'badge--mode-heuristic'),
      isLlm ? 'LLM' : '启发式');
    badge.title = isLlm ? '大模型提取' : '启发式提取';
    return badge;
  }

  function contributionIsAbstractExcerpt(paper) {
    if (!paper || paper.extraction_mode !== 'heuristic') return false;
    var oneLine = normalizeText(paper.one_line_contribution);
    var abstract = normalizeText(paper.abstract);
    if (!oneLine || !abstract) return false;
    var head = oneLine.replace(/[。．.!?！？…]+$/g, '').trim();
    if (!head) return false;
    return abstract.indexOf(head) === 0 || abstract.indexOf(oneLine) === 0;
  }

  function setCopyButtonContent(button, copied) {
    button.textContent = '';
    button.appendChild(svgIcon(copied ? 'check' : 'copy', 12));
    button.appendChild(document.createTextNode(copied ? '已复制' : '复制'));
  }

  function fallbackCopy(text, onSuccess) {
    var area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.top = '0';
    area.style.left = '-9999px';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    var ok = false;
    try {
      ok = document.execCommand('copy');
    } catch (err) {
      ok = false;
    }
    document.body.removeChild(area);
    if (ok) onSuccess();
    else showToast('复制失败，请手动选择文本', true);
  }

  function copyEvidenceText(text, button) {
    function onSuccess() {
      showToast('已复制证据摘录');
      setCopyButtonContent(button, true);
      setTimeout(function () {
        setCopyButtonContent(button, false);
      }, 2000);
    }
    if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
      navigator.clipboard.writeText(text).then(onSuccess, function () {
        fallbackCopy(text, onSuccess);
      });
    } else {
      fallbackCopy(text, onSuccess);
    }
  }

  function buildEvidenceBlock(labelText, text) {
    var block = el('div', 'evidence__block');
    var head = el('div', 'evidence__block-head');
    head.appendChild(el('span', 'evidence__label', labelText));

    var copyBtn = el('button', 'evidence__copy');
    copyBtn.type = 'button';
    copyBtn.setAttribute('aria-label', '复制' + labelText);
    setCopyButtonContent(copyBtn, false);
    copyBtn.addEventListener('click', function () {
      copyEvidenceText(text, copyBtn);
    });
    head.appendChild(copyBtn);
    block.appendChild(head);

    var quote = document.createElement('blockquote');
    quote.textContent = text;
    block.appendChild(quote);
    return block;
  }

  function buildEvidence(paper) {
    var evidence = document.createElement('details');
    evidence.className = 'evidence';

    var summary = document.createElement('summary');
    summary.className = 'evidence__summary';
    summary.appendChild(document.createTextNode('证据摘录'));
    summary.appendChild(svgIcon('chevron-down', 14, 'evidence__chevron'));
    evidence.appendChild(summary);

    var body = el('div', 'evidence__body');
    var contributionEvidence = normalizeText(paper.contribution_evidence);
    var codeEvidence = normalizeText(paper.code_evidence);
    if (contributionEvidence) {
      body.appendChild(buildEvidenceBlock('一句话贡献依据', contributionEvidence));
    }
    if (codeEvidence) {
      body.appendChild(buildEvidenceBlock('开源判断依据', codeEvidence));
    }
    if (!body.childNodes.length) {
      var abstractText = normalizeText(paper.abstract);
      body.appendChild(el('p', 'evidence__empty',
        abstractText ? '摘要未提及代码开源信息' : '该条目无可用摘要'));
    }
    evidence.appendChild(body);
    return evidence;
  }

  function buildPaperCard(paper) {
    var card = el('article', 'paper-card');
    var title = normalizeText(paper.title) || '无标题';
    var url = safeHttpUrl(paper.url);

    // 顶部：来源 / 日期 / 开源状态
    var top = el('div', 'paper-card__top');
    top.appendChild(el('span', 'badge ' + sourceBadgeClass(paper.source),
      sourceLabelFor(paper.source, paper.source_label)));

    var dateNode = el('time', 'paper-card__date', formatDate(paper.published));
    if (typeof paper.published === 'string' && /^\d{4}-\d{2}-\d{2}/.test(paper.published)) {
      dateNode.setAttribute('datetime', paper.published.slice(0, 10));
    }
    top.appendChild(dateNode);

    var openNode = openBadge(paper.code_open_source);
    openNode.classList.add('paper-card__open');
    top.appendChild(openNode);
    card.appendChild(top);

    // 标题（仅 http(s) 链接且新窗口打开）
    var heading = el('h3', 'paper-card__title');
    if (url) {
      var link = el('a', 'paper-card__link', title);
      link.href = url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.appendChild(svgIcon('external-link', 14, 'paper-card__ext'));
      heading.appendChild(link);
    } else {
      heading.textContent = title;
    }
    card.appendChild(heading);

    // 作者
    var authors = asStringList(paper.authors);
    var authorsNode = el('p', 'paper-card__authors');
    if (authors.length) {
      var authorsText = authors.length > 3
        ? '作者：' + authors.slice(0, 3).join(', ') + ' 等 ' + authors.length + ' 人'
        : '作者：' + authors.join(', ');
      authorsNode.textContent = authorsText;
      authorsNode.title = authors.join(', ');
    } else {
      authorsNode.textContent = '作者信息缺失';
    }
    card.appendChild(authorsNode);

    // 一句话贡献
    var contribution = normalizeText(paper.one_line_contribution);
    var contributionNode = el('div', 'paper-card__contribution');
    contributionNode.appendChild(el('span', 'paper-card__contribution-label', '一句话贡献：'));
    if (contribution) {
      contributionNode.appendChild(el('span', 'paper-card__contribution-text', contribution));
      if (contributionIsAbstractExcerpt(paper)) {
        var excerptBadge = el('span', 'badge badge--excerpt paper-card__excerpt', '摘要直摘');
        excerptBadge.title = '一句话贡献由摘要截断生成';
        contributionNode.appendChild(excerptBadge);
      }
    } else {
      contributionNode.classList.add('paper-card__contribution--empty');
      contributionNode.appendChild(el('span', 'paper-card__contribution-text', '暂无提取结果'));
    }
    card.appendChild(contributionNode);

    // 方法 / 数据集
    var chipRow = el('div', 'paper-card__chips');
    var methods = asStringList(paper.methods).slice(0, 4);
    var datasets = asStringList(paper.datasets).slice(0, 2);
    methods.forEach(function (method) {
      chipRow.appendChild(el('span', 'tag-chip', method));
    });
    datasets.forEach(function (dataset) {
      chipRow.appendChild(el('span', 'tag-chip', '数据集：' + dataset));
    });
    if (!methods.length && !datasets.length) {
      chipRow.appendChild(el('span', 'tag-chip tag-chip--empty', '未提取方法/数据集'));
    }
    card.appendChild(chipRow);

    // 证据摘录
    card.appendChild(buildEvidence(paper));

    // 底栏：置信度 / 模式 / 原文链接
    var footer = el('div', 'paper-card__footer');
    var confidenceBox = el('div', 'confidence');
    var confidenceValue = finiteNumber(paper.confidence);
    if (confidenceValue === null) {
      confidenceBox.appendChild(el('span', 'confidence__label', '置信度 —'));
    } else {
      var percent = Math.round(confidenceValue * 100);
      if (percent < 0) percent = 0;
      if (percent > 100) percent = 100;
      confidenceBox.appendChild(el('span', 'confidence__label', '置信度 ' + percent + '%'));
      var track = el('span', 'confidence__track');
      track.setAttribute('aria-hidden', 'true');
      track.title = '提取置信度 ' + percent + '%';
      var fill = el('span', 'confidence__fill');
      if (percent < 50) fill.classList.add('is-low');
      fill.style.width = percent + '%';
      track.appendChild(fill);
      confidenceBox.appendChild(track);
    }
    footer.appendChild(confidenceBox);

    var metaBox = el('div', 'paper-card__meta');
    metaBox.appendChild(modeBadge(paper.extraction_mode));
    if (url) {
      var linkOut = el('a', 'paper-card__linkout', '查看原文');
      linkOut.href = url;
      linkOut.target = '_blank';
      linkOut.rel = 'noopener noreferrer';
      linkOut.appendChild(svgIcon('external-link', 14));
      metaBox.appendChild(linkOut);
    }
    footer.appendChild(metaBox);
    card.appendChild(footer);

    return card;
  }

  /* ------------------------------------------------------------------ *
   * 14. 列表 / 分页 / 结果状态
   * ------------------------------------------------------------------ */
  function renderResultsError() {
    state.view = 'error';
    resultsRegion.classList.remove('is-updating');
    resultsRegion.setAttribute('aria-busy', 'false');
    resultsRegion.textContent = '';
    resultsRegion.appendChild(cloneTemplate('tpl-error'));
    pagination.hidden = true;
    resultsMeta.classList.add('is-error');
    resultsMeta.textContent = '文献列表加载失败';
  }

  function renderResults() {
    resultsRegion.classList.remove('is-updating');
    resultsRegion.setAttribute('aria-busy', 'false');
    resultsRegion.textContent = '';

    if (state.items.length) {
      state.view = 'ready';
      state.items.forEach(function (paper) {
        resultsRegion.appendChild(buildPaperCard(paper));
      });
      return;
    }

    var hasFilters = !!(state.q || state.openSource || state.source);
    if (state.total > 0 || hasFilters) {
      state.view = 'no-results';
      resultsRegion.appendChild(cloneTemplate('tpl-no-results'));
    } else {
      state.view = 'empty';
      resultsRegion.appendChild(cloneTemplate('tpl-empty'));
    }
  }

  function getTotalPages() {
    if (!state.total || state.total <= 0) return 0;
    return Math.max(1, Math.ceil(state.total / state.pageSize));
  }

  function renderPagination() {
    var totalPages = getTotalPages();
    if (totalPages <= 1) {
      pagination.hidden = true;
      return;
    }
    pagination.hidden = false;
    pageInfo.textContent = '第 ' + state.page + ' / ' + totalPages + ' 页';
    prevPage.disabled = state.page <= 1;
    nextPage.disabled = state.page >= totalPages;
  }

  function syncOpenChips() {
    var buttons = openChips.querySelectorAll('button[data-open-source]');
    Array.prototype.forEach.call(buttons, function (btn) {
      var active = (btn.getAttribute('data-open-source') || '') === state.openSource;
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
      btn.classList.toggle('is-active', active);
    });
  }

  function syncSourceChips() {
    var buttons = sourceChips.querySelectorAll('button[data-source]');
    Array.prototype.forEach.call(buttons, function (btn) {
      var active = (btn.getAttribute('data-source') || '') === state.source;
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
      btn.classList.toggle('is-active', active);
    });
  }

  /* ------------------------------------------------------------------ *
   * 15. 数据加载
   * ------------------------------------------------------------------ */
  async function loadMeta(options) {
    var seq = ++state.seq.meta;
    var meta = await requestJson('/api/meta');
    if (seq !== state.seq.meta) return null;
    if (!meta || typeof meta !== 'object' || Array.isArray(meta)) {
      throw new ApiError('元数据格式错误', 0);
    }
    state.meta = meta;
    clearLoadError('meta');
    applyMeta(options && options.initial);
    return meta;
  }

  async function loadStats() {
    var seq = ++state.seq.stats;
    try {
      var data = await requestJson('/api/stats?days=' + encodeURIComponent(String(state.days)));
      if (seq !== state.seq.stats) return;
      if (!data || typeof data !== 'object' || Array.isArray(data)) {
        throw new ApiError('统计数据格式错误', 0);
      }
      state.stats = data;
      clearLoadError('stats');
      renderStats();
      renderStatsCharts();
    } catch (err) {
      if (seq !== state.seq.stats) return;
      state.stats = null;
      setLoadError('stats', err.message);
      renderStatsUnavailable();
      renderChartsUnavailable();
    }
  }

  async function loadRuns() {
    var seq = ++state.seq.runs;
    try {
      var data = await requestJson('/api/runs?limit=' + RUN_LIMIT);
      if (seq !== state.seq.runs) return;
      state.runs = data && Array.isArray(data.items) ? data.items : [];
    } catch (err) {
      if (seq !== state.seq.runs) return;
      state.runs = [];
    }
    renderRuns();
  }

  async function loadRecent30() {
    var seq = ++state.seq.recent30;
    try {
      var data = await requestJson('/api/papers?days=30&page=1&page_size=1');
      if (seq !== state.seq.recent30) return;
      var total = data ? finiteNumber(data.total) : null;
      state.recent30 = total === null ? null : toCount(total);
    } catch (err) {
      if (seq !== state.seq.recent30) return;
      state.recent30 = null;
    }
    renderRecentStat();
  }

  async function loadPapers(options) {
    var opts = options || {};
    var seq = ++state.seq.papers;
    var useSkeleton = opts.mode === 'skeleton' || state.view === 'loading';
    if (useSkeleton) {
      showListSkeleton();
    } else {
      resultsRegion.classList.add('is-updating');
    }

    var params = new URLSearchParams();
    if (state.q) params.set('q', state.q);
    if (state.openSource) params.set('open_source', state.openSource);
    if (state.source) params.set('source', state.source);
    params.set('days', String(state.days));
    params.set('sort', state.sort);
    params.set('page', String(state.page));
    params.set('page_size', String(state.pageSize));

    try {
      var data = await requestJson('/api/papers?' + params.toString());
      if (seq !== state.seq.papers) return;
      if (!data || typeof data !== 'object') throw new ApiError('文献数据格式错误', 0);

      state.items = Array.isArray(data.items) ? data.items : [];
      state.total = finiteNumber(data.total) === null ? state.items.length : toCount(data.total);
      if (typeof data.page === 'number' && data.page >= 1) state.page = data.page;
      if (data.page_size >= 1 && data.page_size <= 50) state.pageSize = data.page_size;

      clearLoadError('papers');
      updateResultsMeta();
      renderResults();
      renderPagination();
      if (opts.scroll) scrollToList();
    } catch (err) {
      if (seq !== state.seq.papers) return;
      state.items = [];
      state.total = 0;
      setLoadError('papers', err.message);
      renderResultsError();
    } finally {
      if (seq === state.seq.papers) resultsRegion.classList.remove('is-updating');
    }
  }

  async function refreshAllData() {
    await Promise.allSettled([
      loadStats(),
      loadRuns(),
      loadRecent30(),
      loadPapers({ mode: 'skeleton' })
    ]);
  }

  /* ------------------------------------------------------------------ *
   * 16. 交互动作
   * ------------------------------------------------------------------ */
  async function reloadAll() {
    if (state.loadingAll) return;
    state.loadingAll = true;
    clearAllErrors();
    showPageSkeleton();
    try {
      await loadMeta({ initial: state.meta === null });
      await refreshAllData();
    } catch (err) {
      setLoadError('meta', err.message || '未知错误');
      renderSourceChips();
      renderResultsError();
      renderStatsUnavailable();
      renderChartsUnavailable();
      chartEmpty(chartRuns, '暂无抓取记录');
    } finally {
      state.loadingAll = false;
    }
  }

  async function doRefresh() {
    if (state.refreshing) return;
    setRefreshBusy(true);
    var payload = {
      days: state.days > 0 ? state.days : DEFAULT_DAYS,
      limit: 20,
      extract: true
    };

    try {
      var result = await requestJson('/api/refresh', {
        method: 'POST',
        body: payload,
        timeout: REFRESH_TIMEOUT
      });

      var status = result && result.status;
      if (status === 'error') {
        var errors = result && Array.isArray(result.errors) ? result.errors : [];
        var reason = errors.length ? String(errors[0]) : '所有数据源均不可用';
        showToast('抓取失败：' + reason, true);
      } else {
        showToast('已更新：新增 ' + toCount(result && result.inserted) +
          ' 篇，提取 ' + toCount(result && result.extracted) + ' 篇');
      }

      try {
        await loadMeta({ initial: false });
      } catch (err) {
        setLoadError('meta', err.message || '元数据刷新失败');
      }
      state.page = 1;
      await refreshAllData();
    } catch (err) {
      showToast('抓取失败：' + (err.message || '未知错误'), true);
    } finally {
      setRefreshBusy(false);
    }
  }

  function applySearchNow() {
    clearTimeout(searchTimer);
    var value = normalizeText(searchInput.value);
    if (value === state.q) return;
    state.q = value;
    state.page = 1;
    loadPapers({ mode: 'quiet' });
  }

  function clearFilters() {
    var hasFilters = !!(state.q || state.openSource || state.source);
    state.q = '';
    state.openSource = '';
    state.source = '';
    state.page = 1;
    searchInput.value = '';
    syncOpenChips();
    syncSourceChips();
    if (hasFilters) loadPapers({ mode: 'quiet' });
    else reloadAll();
  }

  function goToPage(next) {
    if (next < 1 || next === state.page) return;
    var totalPages = getTotalPages();
    if (totalPages > 0 && next > totalPages) return;
    state.page = next;
    loadPapers({ mode: 'quiet', scroll: true });
  }

  function selectDays(days) {
    if (days === state.days) return;
    state.days = days;
    state.page = 1;
    syncDays();
    showPageSkeleton();
    Promise.allSettled([
      loadStats(),
      loadRuns(),
      loadRecent30(),
      loadPapers({ mode: 'skeleton' })
    ]);
  }

  /* ------------------------------------------------------------------ *
   * 17. 事件绑定
   * ------------------------------------------------------------------ */
  function bindEvents() {
    daysControl.addEventListener('click', function (event) {
      var btn = event.target.closest('button[data-days]');
      if (!btn || btn.disabled) return;
      var days = parseInt(btn.getAttribute('data-days'), 10);
      if (!Number.isFinite(days)) return;
      selectDays(days);
    });

    refreshBtn.addEventListener('click', doRefresh);
    retryBtn.addEventListener('click', reloadAll);

    searchInput.addEventListener('input', function () {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(applySearchNow, SEARCH_DEBOUNCE);
    });

    searchInput.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' && !event.isComposing) {
        event.preventDefault();
        applySearchNow();
      }
    });

    openChips.addEventListener('click', function (event) {
      var btn = event.target.closest('button[data-open-source]');
      if (!btn || btn.disabled) return;
      var value = btn.getAttribute('data-open-source') || '';
      if (value === state.openSource) return;
      state.openSource = value;
      state.page = 1;
      syncOpenChips();
      loadPapers({ mode: 'quiet' });
    });

    sourceChips.addEventListener('click', function (event) {
      var btn = event.target.closest('button[data-source]');
      if (!btn || btn.disabled) return;
      var value = btn.getAttribute('data-source') || '';
      if (value === state.source) return;
      state.source = value;
      state.page = 1;
      syncSourceChips();
      loadPapers({ mode: 'quiet' });
    });

    sortSelect.addEventListener('change', function () {
      state.sort = sortSelect.value || 'date_desc';
      state.page = 1;
      loadPapers({ mode: 'quiet' });
    });

    prevPage.addEventListener('click', function () {
      goToPage(state.page - 1);
    });

    nextPage.addEventListener('click', function () {
      goToPage(state.page + 1);
    });

    resultsRegion.addEventListener('click', function (event) {
      var btn = event.target.closest('[data-action]');
      if (!btn) return;
      var action = btn.getAttribute('data-action');
      if (action === 'refresh') doRefresh();
      else if (action === 'clear-filters') clearFilters();
      else if (action === 'retry') reloadAll();
    });
  }

  /* ------------------------------------------------------------------ *
   * 18. 启动
   * ------------------------------------------------------------------ */
  function init() {
    bindEvents();
    syncDays();
    syncOpenChips();
    renderSourceChips();
    reloadAll();
  }

  init();
})();
