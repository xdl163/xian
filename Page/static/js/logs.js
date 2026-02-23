(() => {
  const logsMsg = document.getElementById('logsMsg');
  const logsTableBody = document.querySelector('#logsTable tbody');
  const statusTableBody = document.querySelector('#statusTable tbody');

  const cameraIdInput = document.getElementById('cameraIdInput');
  const cameraAreaInput = document.getElementById('cameraAreaInput');
  const lineNumberInput = document.getElementById('lineNumberInput');
  const eventTypeInput = document.getElementById('eventTypeInput');
  const startTimeInput = document.getElementById('startTimeInput');
  const endTimeInput = document.getElementById('endTimeInput');

  const limitSelect = document.getElementById('limitSelect');
  const autoRefreshSelect = document.getElementById('autoRefreshSelect');
  const pageInfo = document.getElementById('pageInfo');
  const prevBtn = document.getElementById('prevBtn');
  const nextBtn = document.getElementById('nextBtn');

  const imageModal = document.getElementById('imageModal');
  const imageViewer = document.getElementById('imageViewer');
  const perfCanvas = document.getElementById('processorPerfCanvas');
  const perfCtx = perfCanvas ? perfCanvas.getContext('2d') : null;

  let total = 0;
  let offset = 0;
  let limit = Number(limitSelect.value || 20);
  let autoRefreshTimer = null;
  let statusPollTimer = null;
  let perfPollTimer = null;
  let perfValues = [];
  let perfHoverIndex = null;

  const imageCache = new Map(); // event_id -> {version, src}

  function setMsg(text, err = false) {
    logsMsg.textContent = text;
    logsMsg.style.color = err ? '#f87171' : '#9ca3af';
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');
  }

  function datetimeLocalToSql(value) {
    if (!value) return '';
    return `${value.replace('T', ' ')}:00`;
  }

  function buildCachedImagesPayload() {
    const payload = {};
    for (const [eventId, entry] of imageCache.entries()) {
      payload[String(eventId)] = entry.version;
    }
    return payload;
  }

  function currentFilterPayload() {
    return {
      camera_id: cameraIdInput.value.trim(),
      camera_area: cameraAreaInput.value.trim(),
      line_number: lineNumberInput.value.trim(),
      event_type: eventTypeInput.value.trim(),
      start_time: datetimeLocalToSql(startTimeInput.value),
      end_time: datetimeLocalToSql(endTimeInput.value),
    };
  }

  async function queryLogs() {
    try {
      limit = Number(limitSelect.value || 20);
      const resp = await fetch('/api/logs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          limit,
          offset,
          ...currentFilterPayload(),
          cached_images: buildCachedImagesPayload(),
        }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        setMsg(`日志查询失败: ${data.error || resp.status}`, true);
        return;
      }
      total = Number(data.total || 0);
      hydrateImageCache(data.rows || []);
      renderLogRows(data.rows || []);
      updatePager();
      setMsg(`日志已加载 ${(data.rows || []).length} 条，共 ${total} 条`);
    } catch (e) {
      setMsg(`日志查询异常: ${e}`, true);
    }
  }

  function hydrateImageCache(rows) {
    for (const row of rows) {
      const info = row.image || {};
      if (!info.version) continue;
      if (!info.cached && info.data) {
        imageCache.set(row.id, {
          version: info.version,
          src: `data:image/jpeg;base64,${info.data}`,
        });
      }
    }
  }

  function renderLogRows(rows) {
    const html = rows.map((row) => {
      const cache = imageCache.get(row.id);
      const previewHtml = cache?.src
        ? `<img class="log-thumb" src="${cache.src}" data-full="${cache.src}" alt="event-${row.id}" />`
        : '<span class="tip">无图片</span>';

      return `
        <tr>
          <td>${escapeHtml(row.id)}</td>
          <td>${escapeHtml(row.time)}</td>
          <td>${escapeHtml(row.camera_id)}</td>
          <td>${escapeHtml(row.camera_area)}</td>
          <td>${escapeHtml(row.line_number)}</td>
          <td>${escapeHtml(row.event_type)}</td>
          <td>${previewHtml}</td>
        </tr>
      `;
    }).join('');

    logsTableBody.innerHTML = html || '<tr><td colspan="7" class="tip">暂无数据</td></tr>';
  }

  function renderLineStatus(lineStatus) {
    const s = String(lineStatus || '');
    if (!s) return '<span class="tip">-</span>';
    const points = [...s].map((ch, idx) => {
      const ok = ch === '1';
      return `<span class="line-dot ${ok ? 'line-dot-ok' : 'line-dot-bad'}" title="点${idx + 1}: ${ok ? '正常' : '异常'}"></span>`;
    }).join('');
    return `<div class="line-dots-wrap">${points}</div><div class="line-raw">${escapeHtml(s)}</div>`;
  }

  async function queryStatus() {
    try {
      const resp = await fetch('/api/logs/status');
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        setMsg(`状态查询失败: ${data.error || resp.status}`, true);
        return;
      }
      const rows = data.rows || [];
      const html = rows.map((row) => `
        <tr>
          <td>${escapeHtml(row.id)}</td>
          <td>${escapeHtml(row.video_id)}</td>
          <td>${escapeHtml(row.camera_area)}</td>
          <td>${escapeHtml(row.ip)}</td>
          <td>${escapeHtml(row.broken_count)}</td>
          <td>${renderLineStatus(row.line_status)}</td>
          <td>${escapeHtml(row.status)}</td>
          <td>${escapeHtml(row.update_time)}</td>
        </tr>
      `).join('');
      statusTableBody.innerHTML = html || '<tr><td colspan="8" class="tip">暂无状态数据</td></tr>';
    } catch (e) {
      setMsg(`状态查询异常: ${e}`, true);
    }
  }


  function perfPointXY(i, len, value, minV, span, w, h) {
    const x = 40 + (i / Math.max(1, len - 1)) * (w - 50);
    const y = (h - 25) - ((value - minV) / span) * (h - 40);
    return { x, y };
  }

  function renderPerf(values, hoverIndex = null) {
    if (!perfCtx || !perfCanvas) return;
    const w = perfCanvas.width;
    const h = perfCanvas.height;
    perfCtx.clearRect(0, 0, w, h);
    perfCtx.fillStyle = '#0b1220';
    perfCtx.fillRect(0, 0, w, h);

    if (!values || !values.length) {
      perfCtx.fillStyle = '#9ca3af';
      perfCtx.fillText('暂无耗时数据', 12, 20);
      return;
    }

    const minV = Math.min(...values);
    const maxV = Math.max(...values);
    const span = Math.max(0.001, maxV - minV);

    perfCtx.strokeStyle = '#1f2937';
    perfCtx.beginPath();
    perfCtx.moveTo(40, 10);
    perfCtx.lineTo(40, h - 25);
    perfCtx.lineTo(w - 10, h - 25);
    perfCtx.stroke();

    perfCtx.strokeStyle = '#22c55e';
    perfCtx.beginPath();
    values.forEach((v, i) => {
      const pt = perfPointXY(i, values.length, v, minV, span, w, h);
      if (i === 0) perfCtx.moveTo(pt.x, pt.y);
      else perfCtx.lineTo(pt.x, pt.y);
    });
    perfCtx.stroke();

    perfCtx.fillStyle = '#9ca3af';
    perfCtx.fillText(`min: ${minV.toFixed(4)}s`, 45, 15);
    perfCtx.fillText(`max: ${maxV.toFixed(4)}s`, 180, 15);
    perfCtx.fillText(`points: ${values.length}`, 320, 15);

    if (hoverIndex !== null && hoverIndex >= 0 && hoverIndex < values.length) {
      const val = values[hoverIndex];
      const pt = perfPointXY(hoverIndex, values.length, val, minV, span, w, h);

      perfCtx.fillStyle = '#f59e0b';
      perfCtx.beginPath();
      perfCtx.arc(pt.x, pt.y, 4, 0, Math.PI * 2);
      perfCtx.fill();

      const tip1 = `idx: ${hoverIndex + 1}/${values.length}`;
      const tip2 = `elapsed: ${val.toFixed(4)}s`;
      const textW = Math.max(perfCtx.measureText(tip1).width, perfCtx.measureText(tip2).width) + 14;
      const tipX = Math.min(w - textW - 6, Math.max(6, pt.x + 10));
      const tipY = Math.max(6, pt.y - 36);

      perfCtx.fillStyle = 'rgba(15,23,42,0.92)';
      perfCtx.fillRect(tipX, tipY, textW, 30);
      perfCtx.strokeStyle = '#334155';
      perfCtx.strokeRect(tipX, tipY, textW, 30);
      perfCtx.fillStyle = '#e5e7eb';
      perfCtx.fillText(tip1, tipX + 6, tipY + 12);
      perfCtx.fillText(tip2, tipX + 6, tipY + 25);
    }
  }

  async function queryPerf() {
    if (!perfCanvas) return;
    try {
      const resp = await fetch('/api/perf/processor');
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) return;
      perfValues = Array.isArray(data.values) ? data.values : [];
      if (perfHoverIndex !== null && perfHoverIndex >= perfValues.length) perfHoverIndex = perfValues.length - 1;
      renderPerf(perfValues, perfHoverIndex);
    } catch (_e) {}
  }

  function updatePager() {
    const page = Math.floor(offset / limit) + 1;
    const pages = Math.max(1, Math.ceil(total / limit));
    pageInfo.textContent = `第 ${page} / ${pages} 页`;
    prevBtn.disabled = offset <= 0;
    nextBtn.disabled = offset + limit >= total;
  }

  function restartAutoRefresh() {
    if (autoRefreshTimer) {
      clearInterval(autoRefreshTimer);
      autoRefreshTimer = null;
    }
    const ms = Number(autoRefreshSelect.value || 0);
    if (ms > 0) {
      autoRefreshTimer = setInterval(() => {
        queryLogs();
      }, ms);
    }
  }

  function openImage(src) {
    imageViewer.src = src;
    imageModal.classList.remove('hidden');
  }

  function closeImage() {
    imageViewer.src = '';
    imageModal.classList.add('hidden');
  }

  document.getElementById('backBtn').addEventListener('click', () => {
    window.location.href = '/';
  });

  document.getElementById('queryBtn').addEventListener('click', () => {
    offset = 0;
    queryLogs();
  });

  document.getElementById('refreshBtn').addEventListener('click', () => {
    queryLogs();
    queryStatus();
  });

  prevBtn.addEventListener('click', () => {
    offset = Math.max(0, offset - limit);
    queryLogs();
  });

  nextBtn.addEventListener('click', () => {
    offset += limit;
    queryLogs();
  });

  autoRefreshSelect.addEventListener('change', restartAutoRefresh);

  logsTableBody.addEventListener('click', (e) => {
    const target = e.target;
    if (target instanceof HTMLImageElement && target.classList.contains('log-thumb')) {
      openImage(target.dataset.full || target.src);
    }
  });

  imageModal.addEventListener('click', (e) => {
    if (e.target === imageModal) closeImage();
  });

  document.getElementById('closeImageBtn').addEventListener('click', closeImage);

  statusPollTimer = setInterval(queryStatus, 1000);
  perfPollTimer = setInterval(queryPerf, 1000);
  restartAutoRefresh();
  queryLogs();
  queryStatus();
  queryPerf();


  if (perfCanvas) {
    perfCanvas.addEventListener('mousemove', (e) => {
      if (!perfValues.length) return;
      const rect = perfCanvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const w = perfCanvas.width;
      const idx = Math.max(0, Math.min(perfValues.length - 1, Math.round(((x - 40) / Math.max(1, (w - 50))) * Math.max(1, perfValues.length - 1))));
      perfHoverIndex = idx;
      renderPerf(perfValues, perfHoverIndex);
    });
    perfCanvas.addEventListener('mouseleave', () => {
      perfHoverIndex = null;
      renderPerf(perfValues, null);
    });
  }

  window.addEventListener('beforeunload', () => {
    if (autoRefreshTimer) clearInterval(autoRefreshTimer);
    if (statusPollTimer) clearInterval(statusPollTimer);
    if (perfPollTimer) clearInterval(perfPollTimer);
  });
})();
