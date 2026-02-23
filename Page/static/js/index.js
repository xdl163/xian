(() => {
  const frameCanvas = document.getElementById('previewFrameCanvas');
  const overlayCanvas = document.getElementById('previewOverlay');
  const fctx = frameCanvas.getContext('2d');
  const octx = overlayCanvas.getContext('2d');
  const previewTitle = document.getElementById('previewTitle');
  const drawToggle = document.getElementById('toggleDraw');
  const homeMsg = document.getElementById('homeMsg');

  const modalMask = document.getElementById('modalMask');
  const modalTitle = document.getElementById('modalTitle');
  const modalBody = document.getElementById('modalBody');
  const modalOkBtn = document.getElementById('modalOkBtn');
  const modalCancelBtn = document.getElementById('modalCancelBtn');

  let currentVideoId = Number(window.INIT_VIDEO_ID || -1);
  let latestFrame = null;
  let latestRecognition = null;
  let previewTimer = null;
  let recognitionTimer = null;
  let recordBtnTimer = null;

  function setMsg(text, err = false) { homeMsg.textContent = text; homeMsg.style.color = err ? '#f87171' : '#9ca3af'; }
  function openModal(title, bodyHtml) { modalTitle.textContent = title; modalBody.innerHTML = bodyHtml; modalMask.classList.remove('hidden'); }
  function closeModal() { modalMask.classList.add('hidden'); modalBody.innerHTML = ''; modalOkBtn.onclick = null; modalCancelBtn.onclick = null; }

  function askPassword() { return new Promise((resolve) => {
    openModal('密码验证', '<label>密码 <input id="modalPassword" type="password" autocomplete="off" /></label>');
    modalCancelBtn.onclick = () => { closeModal(); resolve(null); };
    modalOkBtn.onclick = async () => {
      const password = (document.getElementById('modalPassword')?.value || '').trim();
      if (!password) return;
      const vr = await fetch('/api/verify-password', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password }) });
      const vd = await vr.json();
      if (!vd.ok) { setMsg('密码错误', true); return; }
      closeModal(); resolve(password);
    };
  }); }

  function askRecordOptions() { return new Promise((resolve) => {
    openModal('录制选项', `
      <label>名称 <input id="rec_name" type="text" /></label>
      <label class="inline-check">录制ROI <input id="rec_roi" type="checkbox" checked /></label>
      <label>每几帧保存一帧 <input id="rec_every" type="number" min="1" value="1" /></label>
      <label>每隔几分钟打包zip <input id="rec_zip" type="number" step="0.1" min="0" value="10" /></label>
      <label>最大录制时长(小时,可空) <input id="rec_maxh" type="number" step="0.1" min="0.1" /></label>
      <label class="inline-check">全视频时绘制识别框 <input id="rec_draw" type="checkbox" checked /></label>
    `);
    modalCancelBtn.onclick = () => { closeModal(); resolve(null); };
    modalOkBtn.onclick = () => {
      const name = (document.getElementById('rec_name')?.value || '').trim();
      if (!name) return;
      const maxRaw = (document.getElementById('rec_maxh')?.value || '').trim();
      closeModal();
      resolve({
        name,
        save_roi: !!document.getElementById('rec_roi')?.checked,
        every_n_frames: +(document.getElementById('rec_every')?.value || 1),
        zip_minutes: +(document.getElementById('rec_zip')?.value || 10),
        max_hours: maxRaw === '' ? null : +maxRaw,
        draw_boxes: !!document.getElementById('rec_draw')?.checked,
      });
    };
  }); }


  function askAddCameraPayload() { return new Promise((resolve) => {
    openModal('添加摄像头', `
      <label>video_id <input id="cam_video_id" type="text" /></label>
      <label>add_type <input id="cam_add_type" type="text" /></label>
      <label>id <input id="cam_id" type="text" /></label>
      <label>video_type <input id="cam_video_type" type="text" value="http" /></label>
      <label>video_url <input id="cam_video_url" type="text" /></label>
    `);
    modalCancelBtn.onclick = () => { closeModal(); resolve(null); };
    modalOkBtn.onclick = () => {
      const payload = {
        video_id: document.getElementById('cam_video_id')?.value?.trim() || '',
        add_type: document.getElementById('cam_add_type')?.value?.trim() || '',
        id: document.getElementById('cam_id')?.value?.trim() || '',
        video_type: document.getElementById('cam_video_type')?.value?.trim() || 'http',
        video_url: document.getElementById('cam_video_url')?.value?.trim() || '',
      };
      if (!payload.id || !payload.video_url) return;
      closeModal();
      resolve(payload);
    };
  }); }

  async function addCamera() {
    const password = await askPassword();
    if (!password) return;
    const cameraPayload = await askAddCameraPayload();
    if (!cameraPayload) return;
    const resp = await fetch('/api/camera', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password, ...cameraPayload }) });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) { setMsg(`添加失败: ${data.error || resp.status}`, true); return; }
    setMsg('添加摄像头成功，正在刷新...');
    setTimeout(() => window.location.reload(), 800);
  }
  function syncSize(width, height) { if (!width || !height) return; frameCanvas.width = width; frameCanvas.height = height; overlayCanvas.width = width; overlayCanvas.height = height; frameCanvas.style.width = '100%'; frameCanvas.style.height = 'auto'; overlayCanvas.style.width = '100%'; overlayCanvas.style.height = '100%'; }
  function setActiveId() { document.querySelectorAll('#videoTable tbody tr').forEach((tr) => { const id = Number(tr.dataset.id); tr.classList.toggle('active-row', id === currentVideoId); }); previewTitle.textContent = currentVideoId >= 0 ? `预览（ID: ${currentVideoId}）` : '预览'; }

  async function fetchFrame(id) { const resp = await fetch(`/api/video/${id}/frame`); if (!resp.ok) return null; const data = await resp.json(); const img = new Image(); await new Promise((resolve, reject) => { img.onload = resolve; img.onerror = reject; img.src = `data:image/png;base64,${data.image}`; }); return { ...data, img }; }
  async function fetchRecognition(id) { const resp = await fetch(`/api/video/${id}/recognition`); if (!resp.ok) return null; return resp.json(); }
  async function fetchRuntime() { const resp = await fetch(`/api/runtime`); if (!resp.ok) return null; return resp.json(); }
  async function fetchRecordingState(id) {
    const resp = await fetch(`/api/video/${id}/recordings`);
    if (!resp.ok) return null;
    const data = await resp.json();
    return !!data.recording;
  }

  function drawBoxes(ctx, w, h, rec) { if (!rec || !Array.isArray(rec.points)) return; for (const p of rec.points) { ctx.strokeStyle = p.is_light ? '#22c55e' : '#ef4444'; ctx.lineWidth = 2; ctx.strokeRect(p.x1, p.y1, p.x2 - p.x1, p.y2 - p.y1); } }
  function redraw() { if (!latestFrame) return; fctx.clearRect(0, 0, frameCanvas.width, frameCanvas.height); fctx.drawImage(latestFrame, 0, 0, frameCanvas.width, frameCanvas.height); octx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height); if (drawToggle.checked) drawBoxes(octx, overlayCanvas.width, overlayCanvas.height, latestRecognition); }

  async function pollPreview() { if (currentVideoId < 0) return; try { const data = await fetchFrame(currentVideoId); if (!data) return; if (frameCanvas.width !== data.width || frameCanvas.height !== data.height) syncSize(data.width, data.height); latestFrame = data.img; redraw(); } catch (_e) {} }
  async function pollRecognition() { if (currentVideoId < 0) return; try { latestRecognition = await fetchRecognition(currentVideoId); redraw(); } catch (_e) {} }
  async function syncRecordingButtonsFromBackend() {
    const buttons = Array.from(document.querySelectorAll('.record-btn'));
    await Promise.all(buttons.map(async (btn) => {
      const id = Number(btn.dataset.id);
      if (!id) return;
      try {
        const recording = await fetchRecordingState(id);
        if (recording === null) return;
        btn.textContent = recording ? '结束录制' : '开始录制';
      } catch (_e) {}
    }));
  }


  async function configurePollingByRuntime() {
    let fps = 3;
    try {
      const rt = await fetchRuntime();
      if (rt && Number(rt.recognition_fps) > 0) fps = Number(rt.recognition_fps);
    } catch (_e) {}

    const intervalMs = Math.max(100, Math.round(1000 / fps));
    if (previewTimer) clearInterval(previewTimer);
    if (recognitionTimer) clearInterval(recognitionTimer);
    if (recordBtnTimer) clearInterval(recordBtnTimer);

    previewTimer = setInterval(pollPreview, intervalMs);
    recognitionTimer = setInterval(pollRecognition, intervalMs);
    recordBtnTimer = setInterval(syncRecordingButtonsFromBackend, Math.max(500, intervalMs));
  }

  async function toggleRecognition(videoId, enabled) {
    const resp = await fetch(`/api/video/${videoId}/recognition-enabled`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }) });
    if (!resp.ok) setMsg('切换识别状态失败', true);
  }

  async function startRecording(videoId, btn) {
    const opts = await askRecordOptions();
    if (!opts) return;
    const resp = await fetch(`/api/video/${videoId}/recordings/start`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(opts) });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) { setMsg(`开始录制失败: ${data.error || resp.status}`, true); return; }
    btn.textContent = '结束录制';
    setMsg(`摄像头 ${videoId} 录制中`);
  }

  async function stopRecording(videoId, btn) {
    const resp = await fetch(`/api/video/${videoId}/recordings/stop`, { method: 'POST' });
    if (!resp.ok) { setMsg('结束录制失败', true); return; }
    btn.textContent = '开始录制';
    setMsg(`摄像头 ${videoId} 已结束录制`);
  }

  async function openSettingsPage() { const password = await askPassword(); if (!password) return; window.location.href = `/settings?password=${encodeURIComponent(password)}`; }
  function openLogsPage() { window.location.href = '/logs'; }
  async function openAnnotatePage(videoId) { const password = await askPassword(); if (!password) return; window.location.href = `/annotate/${videoId}?password=${encodeURIComponent(password)}`; }
  function openRecordingsPage(videoId) { window.location.href = `/recordings/${videoId}`; }

  document.getElementById('openSettingsBtn').addEventListener('click', openSettingsPage);
  document.getElementById('openLogsBtn').addEventListener('click', openLogsPage);
  document.getElementById('addCameraBtn').addEventListener('click', addCamera);

  document.getElementById('videoTable').addEventListener('click', async (e) => {
    const id = Number(e.target.dataset.id);
    if (!id) return;
    if (e.target.classList.contains('id-btn')) { currentVideoId = id; latestFrame = null; latestRecognition = null; setActiveId(); return; }
    if (e.target.classList.contains('annotate-btn')) return openAnnotatePage(id);
    if (e.target.classList.contains('record-list-btn')) return openRecordingsPage(id);
    if (e.target.classList.contains('record-btn')) {
      if (e.target.textContent.includes('结束')) await stopRecording(id, e.target); else await startRecording(id, e.target);
    }
  });

  document.querySelectorAll('.recognition-toggle').forEach((el) => {
    el.addEventListener('change', (e) => toggleRecognition(Number(e.target.dataset.id), !!e.target.checked));
  });

  drawToggle.addEventListener('change', redraw);
  modalMask.addEventListener('click', (e) => { if (e.target === modalMask) closeModal(); });
  setActiveId();
  syncRecordingButtonsFromBackend();
  configurePollingByRuntime();
  setInterval(configurePollingByRuntime, 5000);
  pollPreview(); pollRecognition();
})();
