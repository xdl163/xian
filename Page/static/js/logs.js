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

  let total = 0;
  let offset = 0;
  let limit = Number(limitSelect.value || 20);
  let autoRefreshTimer = null;
  let statusPollTimer = null;

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
  restartAutoRefresh();
  queryLogs();
  queryStatus();

  window.addEventListener('beforeunload', () => {
    if (autoRefreshTimer) clearInterval(autoRefreshTimer);
    if (statusPollTimer) clearInterval(statusPollTimer);
  });
})();
