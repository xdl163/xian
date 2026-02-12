(() => {
  const logsMsg = document.getElementById('logsMsg');
  const logsTableBody = document.querySelector('#logsTable tbody');
  const cameraIdInput = document.getElementById('cameraIdInput');
  const limitSelect = document.getElementById('limitSelect');
  const pageInfo = document.getElementById('pageInfo');
  const prevBtn = document.getElementById('prevBtn');
  const nextBtn = document.getElementById('nextBtn');

  const imageModal = document.getElementById('imageModal');
  const imageViewer = document.getElementById('imageViewer');

  let total = 0;
  let offset = 0;
  let limit = Number(limitSelect.value || 20);
  let lastRows = [];

  const imageCache = new Map(); // key: event_id, value: { version, src }

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

  function buildCachedImagesPayload() {
    const payload = {};
    for (const [eventId, entry] of imageCache.entries()) {
      payload[String(eventId)] = entry.version;
    }
    return payload;
  }

  async function queryLogs() {
    try {
      setMsg('查询中...');
      limit = Number(limitSelect.value || 20);
      const cameraId = cameraIdInput.value.trim();
      const resp = await fetch('/api/logs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          limit,
          offset,
          camera_id: cameraId,
          cached_images: buildCachedImagesPayload(),
        }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        setMsg(`查询失败: ${data.error || resp.status}`, true);
        return;
      }
      total = Number(data.total || 0);
      lastRows = data.rows || [];
      hydrateImageCache(lastRows);
      renderRows(lastRows);
      updatePager();
      setMsg(`已加载 ${lastRows.length} 条，共 ${total} 条`);
    } catch (e) {
      setMsg(`查询异常: ${e}`, true);
    }
  }

  function hydrateImageCache(rows) {
    for (const row of rows) {
      const info = row.image || {};
      const version = info.version || '';
      if (!version) continue;
      if (!info.cached && info.data) {
        imageCache.set(row.id, {
          version,
          src: `data:image/jpeg;base64,${info.data}`,
        });
      }
    }
  }

  function renderRows(rows) {
    const html = rows.map((row) => {
      const cache = imageCache.get(row.id);
      const hasImg = Boolean(cache?.src);
      const previewHtml = hasImg
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

  function updatePager() {
    const page = Math.floor(offset / limit) + 1;
    const pages = Math.max(1, Math.ceil(total / limit));
    pageInfo.textContent = `第 ${page} / ${pages} 页`;
    prevBtn.disabled = offset <= 0;
    nextBtn.disabled = offset + limit >= total;
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
  document.getElementById('refreshBtn').addEventListener('click', () => queryLogs());
  prevBtn.addEventListener('click', () => {
    offset = Math.max(0, offset - limit);
    queryLogs();
  });
  nextBtn.addEventListener('click', () => {
    offset += limit;
    queryLogs();
  });

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

  queryLogs();
})();
