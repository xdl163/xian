(() => {
  const msg = document.getElementById('msg');
  const password = window.SETTINGS_PASSWORD || '';

  function setMsg(text, err = false) {
    msg.textContent = text;
    msg.style.color = err ? '#f87171' : '#9ca3af';
  }

  function readSettings() {
    return {
      password,
      save: document.getElementById('save').checked,
      save_csv: document.getElementById('save_csv').checked,
      save_img: document.getElementById('save_img').checked,
      db_save_day: +document.getElementById('db_save_day').value,
      error_win: +document.getElementById('error_win').value,
      correct_win: +document.getElementById('correct_win').value,
      BUF_SIZE: +document.getElementById('BUF_SIZE').value,
      HISTORY_LEN: +document.getElementById('HISTORY_LEN').value,
      model_threshold: +document.getElementById('model_threshold').value,
    };
  }

  async function loadSettings() {
    const resp = await fetch(`/api/settings?password=${encodeURIComponent(password)}`);
    if (!resp.ok) {
      setMsg('密码校验失败，请返回重新进入', true);
      return;
    }
    const data = await resp.json();
    ['save', 'save_csv', 'save_img'].forEach((k) => { document.getElementById(k).checked = !!data[k]; });
    ['db_save_day', 'error_win', 'correct_win', 'BUF_SIZE', 'HISTORY_LEN', 'model_threshold'].forEach((k) => { document.getElementById(k).value = data[k]; });
  }

  document.getElementById('saveBtn').addEventListener('click', async () => {
    try {
      const resp = await fetch('/api/settings', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(readSettings()),
      });
      setMsg(resp.ok ? '保存成功并已应用' : '保存失败', !resp.ok);
    } catch (e) {
      setMsg(`保存失败: ${e}`, true);
    }
  });

  document.getElementById('uploadModelBtn').addEventListener('click', async () => {
    const input = document.getElementById('modelFile');
    if (!input.files || !input.files[0]) {
      setMsg('请先选择模型文件', true);
      return;
    }
    const fd = new FormData();
    fd.append('password', password);
    fd.append('model_file', input.files[0]);

    try {
      const resp = await fetch('/api/model/upload', { method: 'POST', body: fd });
      const data = await resp.json().catch(() => ({}));
      setMsg(resp.ok ? `模型上传成功：${data.model_path || ''}` : `上传失败：${data.error || resp.status}`, !resp.ok);
    } catch (e) {
      setMsg(`上传失败: ${e}`, true);
    }
  });

  document.getElementById('restartBtn').addEventListener('click', async () => {
    if (!confirm('确认重启后端并重载视频吗？')) return;
    try {
      const resp = await fetch('/api/restart', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password }),
      });
      setMsg(resp.ok ? '重启成功' : '重启失败', !resp.ok);
      if (resp.ok) setTimeout(() => { window.location.href = '/'; }, 1000);
    } catch (e) {
      setMsg(`重启失败: ${e}`, true);
    }
  });

  loadSettings();
})();
