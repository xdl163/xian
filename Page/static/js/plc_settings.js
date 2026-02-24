(() => {
  const password = window.SETTINGS_PASSWORD || '';
  const msg = document.getElementById('msg');
  const tableBody = document.querySelector('#plcTable tbody');

  function setMsg(text, err = false) {
    msg.textContent = text;
    msg.style.color = err ? '#f87171' : '#9ca3af';
  }

  function rowHtml(row) {
    const plc = Array.isArray(row.plc) ? row.plc : [0, 0, 0, 0, 0, 0];
    return `
      <tr data-id="${row.id}">
        <td>${row.id}</td>
        <td>${row.video_id || ''}</td>
        <td>${row.add_type || ''}</td>
        <td><input type="number" class="plc-input" data-idx="0" value="${plc[0] ?? 0}" /></td>
        <td><input type="number" class="plc-input" data-idx="1" value="${plc[1] ?? 0}" /></td>
        <td><input type="number" class="plc-input" data-idx="2" value="${plc[2] ?? 0}" /></td>
        <td><input type="number" class="plc-input" data-idx="3" value="${plc[3] ?? 0}" /></td>
        <td><input type="number" class="plc-input" data-idx="4" value="${plc[4] ?? 0}" /></td>
        <td><input type="number" class="plc-input" data-idx="5" value="${plc[5] ?? 0}" /></td>
        <td><button type="button" class="save-row-btn">保存</button></td>
      </tr>
    `;
  }

  async function loadRows() {
    try {
      const resp = await fetch(`/api/plc/settings?password=${encodeURIComponent(password)}`);
      if (!resp.ok) {
        setMsg('读取PLC设置失败（密码可能失效）', true);
        return;
      }
      const data = await resp.json();
      tableBody.innerHTML = (data.rows || []).map(rowHtml).join('');
      setMsg(`已加载 ${(data.rows || []).length} 条摄像头配置`);
    } catch (e) {
      setMsg(`读取PLC设置失败: ${e}`, true);
    }
  }

  async function saveRow(tr) {
    const id = Number(tr.dataset.id);
    const plc = Array.from(tr.querySelectorAll('.plc-input'))
      .sort((a, b) => Number(a.dataset.idx) - Number(b.dataset.idx))
      .map((el) => Number(el.value || 0));

    const resp = await fetch('/api/plc/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password, id, plc }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      setMsg(`保存失败(id=${id}): ${data.error || resp.status}`, true);
      return;
    }
    setMsg(`保存成功(id=${id})`);
  }

  tableBody.addEventListener('click', async (e) => {
    if (!e.target.classList.contains('save-row-btn')) return;
    const tr = e.target.closest('tr');
    if (!tr) return;
    await saveRow(tr);
  });

  document.getElementById('reloadBtn').addEventListener('click', loadRows);

  loadRows();
})();
