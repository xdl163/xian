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

  tbody.addEventListener('click', async (e) => {
    const name = e.target.dataset.name;
    if (!name) return;
    if (e.target.classList.contains('dl')) {
      window.location.href = `/api/video/${videoId}/recordings/${encodeURIComponent(name)}/download`;
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
