(() => {
  const videoId = Number(window.REC_VIDEO_ID);
  const tbody = document.querySelector('#recTable tbody');
  const msg = document.getElementById('msg');
  function setMsg(t, err = false) { msg.textContent = t; msg.style.color = err ? '#f87171' : '#9ca3af'; }

  async function load() {
    const resp = await fetch(`/api/video/${videoId}/recordings`);
    const data = await resp.json();
    tbody.innerHTML = '';
    (data.rows || []).forEach((r) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${r.name}</td><td><button class="dl" data-name="${r.name}">下载</button> <button class="del" data-name="${r.name}">删除</button></td>`;
      tbody.appendChild(tr);
    });
  }

  async function waitDownloadReady(name) {
    const timeoutMs = 10 * 60 * 1000;
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      const statusResp = await fetch(`/api/video/${videoId}/recordings/${encodeURIComponent(name)}/download/status`);
      const statusData = await statusResp.json().catch(() => ({}));
      if (!statusResp.ok) {
        throw new Error(statusData.error || 'status_failed');
      }
      if (statusData.ready) return;
      if (statusData.status === 'error') throw new Error(statusData.error || 'compress_failed');
      setMsg(`压缩中... (${statusData.status || 'running'})`);
      await new Promise((r) => setTimeout(r, 1000));
    }
    throw new Error('compress_timeout');
  }

  tbody.addEventListener('click', async (e) => {
    const name = e.target.dataset.name;
    if (!name) return;
    if (e.target.classList.contains('dl')) {
      e.target.disabled = true;
      try {
        setMsg('开始压缩...');
        const prepareResp = await fetch(`/api/video/${videoId}/recordings/${encodeURIComponent(name)}/download/prepare`, { method: 'POST' });
        const prepareData = await prepareResp.json().catch(() => ({}));
        if (!prepareResp.ok) throw new Error(prepareData.error || 'prepare_failed');
        await waitDownloadReady(name);
        setMsg('压缩完成，开始下载');
        window.location.href = `/api/video/${videoId}/recordings/${encodeURIComponent(name)}/download`;
      } catch (err) {
        setMsg(`下载失败: ${err}`, true);
      } finally {
        e.target.disabled = false;
      }
      return;
    }
    if (e.target.classList.contains('del')) {
      if (!confirm(`确认删除 ${name} ?`)) return;
      document.body.style.pointerEvents = 'none';
      setMsg('删除中...');
      const resp = await fetch(`/api/video/${videoId}/recordings/${encodeURIComponent(name)}`, { method: 'DELETE' });
      document.body.style.pointerEvents = '';
      if (!resp.ok) { setMsg('删除失败', true); return; }
      setMsg('删除成功');
      await load();
    }
  });

  load();
})();
