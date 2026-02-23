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
      crop_size: [
        +document.getElementById('roi_w').value,
        +document.getElementById('roi_h').value,
      ],
      recognition_fps: +document.getElementById('recognition_fps').value,
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
    ['db_save_day', 'error_win', 'correct_win', 'BUF_SIZE', 'HISTORY_LEN', 'model_threshold', 'recognition_fps'].forEach((k) => { document.getElementById(k).value = data[k]; });
    document.getElementById('roi_w').value = (data.crop_size || [40,40])[0];
    document.getElementById('roi_h').value = (data.crop_size || [40,40])[1];
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

  document.getElementById('changePasswordBtn').addEventListener('click', async () => {
    const oldPassword = document.getElementById('oldPassword').value.trim();
    const newPassword = document.getElementById('newPassword').value.trim();
    if (!oldPassword || !newPassword) {
      setMsg('请填写原密码和新密码', true);
      return;
    }
    try {
      const resp = await fetch('/api/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
      });
      const data = await resp.json().catch(() => ({}));
      setMsg(resp.ok ? '密码修改成功' : `密码修改失败：${data.message || data.error || resp.status}`, !resp.ok);
    } catch (e) {
      setMsg(`密码修改失败: ${e}`, true);
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
