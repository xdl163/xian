(() => {
  const frameCanvas = document.getElementById('previewFrameCanvas');
  const overlayCanvas = document.getElementById('previewOverlay');
  const fctx = frameCanvas.getContext('2d');
  const octx = overlayCanvas.getContext('2d');
  const previewTitle = document.getElementById('previewTitle');
  const settingsMsg = document.getElementById('settingsMsg');
  const drawToggle = document.getElementById('toggleDraw');

  let currentVideoId = window.INIT_VIDEO_ID;
  let latestFrame = null;
  let latestRecognition = null;

  const recorders = new Map();

  function setMsg(text, err = false) {
    settingsMsg.textContent = text;
    settingsMsg.style.color = err ? '#f87171' : '#9ca3af';
  }

  function syncSize(width, height) {
    if (!width || !height) return;
    frameCanvas.width = width;
    frameCanvas.height = height;
    overlayCanvas.width = width;
    overlayCanvas.height = height;
    frameCanvas.style.width = '100%';
    frameCanvas.style.height = 'auto';
    overlayCanvas.style.width = '100%';
    overlayCanvas.style.height = '100%';
  }

  function redraw() {
    fctx.clearRect(0, 0, frameCanvas.width, frameCanvas.height);
    octx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
    if (!latestFrame) return;

    fctx.drawImage(latestFrame, 0, 0, frameCanvas.width, frameCanvas.height);
    if (!drawToggle.checked || !latestRecognition) return;

    const srcW = latestRecognition.frame_width || frameCanvas.width || 1;
    const srcH = latestRecognition.frame_height || frameCanvas.height || 1;
    for (const p of latestRecognition.points || []) {
      const x = p.x1 / srcW * overlayCanvas.width;
      const y = p.y1 / srcH * overlayCanvas.height;
      const w = (p.x2 - p.x1) / srcW * overlayCanvas.width;
      const h = (p.y2 - p.y1) / srcH * overlayCanvas.height;
      octx.strokeStyle = p.is_light ? '#22c55e' : '#ef4444';
      octx.lineWidth = 1;
      octx.strokeRect(x, y, w, h);
    }
  }

  async function pollFrame() {
    if (currentVideoId < 0) return;
    try {
      const resp = await fetch(`/api/video/${currentVideoId}/frame`);
      if (!resp.ok) return;
      const data = await resp.json();
      if (frameCanvas.width !== data.width || frameCanvas.height !== data.height) {
        syncSize(data.width, data.height);
      }
      const img = new Image();
      img.src = `data:image/png;base64,${data.image}`;
      await img.decode();
      latestFrame = img;
      redraw();

      for (const rec of recorders.values()) {
        if (rec && rec.pushFrame) rec.pushFrame(img, data.width, data.height);
      }
    } catch (_e) {}
  }

  async function pollRecognition() {
    if (currentVideoId < 0) return;
    try {
      const resp = await fetch(`/api/video/${currentVideoId}/recognition`);
      if (!resp.ok) return;
      latestRecognition = await resp.json();
      redraw();
    } catch (_e) {}
  }

  async function loadSettings() {
    const data = await (await fetch('/api/settings')).json();
    ['save', 'save_csv', 'save_img'].forEach((k) => { document.getElementById(k).checked = !!data[k]; });
    ['db_save_day', 'error_win', 'correct_win', 'BUF_SIZE', 'HISTORY_LEN'].forEach((k) => { document.getElementById(k).value = data[k]; });
  }

  function readSettings() {
    return {
      save: document.getElementById('save').checked,
      save_csv: document.getElementById('save_csv').checked,
      save_img: document.getElementById('save_img').checked,
      db_save_day: +document.getElementById('db_save_day').value,
      error_win: +document.getElementById('error_win').value,
      correct_win: +document.getElementById('correct_win').value,
      BUF_SIZE: +document.getElementById('BUF_SIZE').value,
      HISTORY_LEN: +document.getElementById('HISTORY_LEN').value,
    };
  }

  function createRecorder(videoId) {
    const cvs = document.createElement('canvas');
    const cctx = cvs.getContext('2d');
    const stream = cvs.captureStream(6);
    const chunks = [];
    const mediaRecorder = new MediaRecorder(stream, { mimeType: 'video/webm' });
    mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
    mediaRecorder.onstop = () => {
      const blob = new Blob(chunks, { type: 'video/webm' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `video_${videoId}_${Date.now()}.webm`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    };
    mediaRecorder.start();

    return {
      mediaRecorder,
      pushFrame: (img, w, h) => {
        if (!w || !h) return;
        if (cvs.width !== w || cvs.height !== h) {
          cvs.width = w;
          cvs.height = h;
        }
        cctx.drawImage(img, 0, 0, w, h);
      },
    };
  }

  async function gotoAnnotate(videoId) {
    let password = localStorage.getItem('annotate_password') || '';
    if (!password) password = prompt('请输入标注密码') || '';
    if (!password) return;

    const vr = await fetch('/api/verify-password', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password }),
    });
    const vd = await vr.json();
    if (!vd.ok) {
      alert('密码错误');
      localStorage.removeItem('annotate_password');
      return;
    }
    localStorage.setItem('annotate_password', password);
    location.href = `/annotate/${videoId}`;
  }

  document.getElementById('videoTable').addEventListener('click', (e) => {
    const id = Number(e.target.dataset.id);
    if (!id) return;

    if (e.target.classList.contains('id-btn')) {
      currentVideoId = id;
      previewTitle.textContent = `预览 ${id}`;
      latestFrame = null;
      latestRecognition = null;
      return;
    }

    if (e.target.classList.contains('annotate-btn')) {
      gotoAnnotate(id);
      return;
    }

    if (e.target.classList.contains('record-btn')) {
      const btn = e.target;
      if (recorders.has(id)) {
        recorders.get(id).mediaRecorder.stop();
        recorders.delete(id);
        btn.textContent = '开始录制';
      } else {
        recorders.set(id, createRecorder(id));
        btn.textContent = '结束录制';
      }
    }
  });

  document.getElementById('saveSettingsBtn').addEventListener('click', async () => {
    try {
      const resp = await fetch('/api/settings', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(readSettings()),
      });
      setMsg(resp.ok ? '保存成功并已应用' : '保存失败', !resp.ok);
    } catch (e) {
      setMsg(`保存失败: ${e}`, true);
    }
  });

  document.getElementById('restartBtn').addEventListener('click', async () => {
    if (!confirm('确认重启后端并重载视频吗？')) return;
    try {
      const resp = await fetch('/api/restart', { method: 'POST' });
      setMsg(resp.ok ? '重启成功' : '重启失败', !resp.ok);
      if (resp.ok) setTimeout(() => location.reload(), 1000);
    } catch (e) {
      setMsg(`重启失败: ${e}`, true);
    }
  });

  drawToggle.addEventListener('change', redraw);
  setInterval(pollFrame, 250);
  setInterval(pollRecognition, 250);
  pollFrame();
  pollRecognition();
  loadSettings();
})();
