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

  const recorders = new Map();
  const AUTO_DOWNLOAD_MS = 10 * 60 * 1000;

  function setMsg(text, err = false) {
    homeMsg.textContent = text;
    homeMsg.style.color = err ? '#f87171' : '#9ca3af';
  }

  function openModal(title, bodyHtml) {
    modalTitle.textContent = title;
    modalBody.innerHTML = bodyHtml;
    modalMask.classList.remove('hidden');
  }

  function closeModal() {
    modalMask.classList.add('hidden');
    modalBody.innerHTML = '';
    modalOkBtn.onclick = null;
    modalCancelBtn.onclick = null;
  }

  function askPassword() {
    return new Promise((resolve) => {
      openModal('密码验证', '<label>密码 <input id="modalPassword" type="password" autocomplete="off" /></label>');
      modalCancelBtn.onclick = () => { closeModal(); resolve(null); };
      modalOkBtn.onclick = async () => {
        const password = (document.getElementById('modalPassword')?.value || '').trim();
        if (!password) return;
        const vr = await fetch('/api/verify-password', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password }),
        });
        const vd = await vr.json();
        if (!vd.ok) {
          setMsg('密码错误', true);
          return;
        }
        closeModal();
        resolve(password);
      };
    });
  }

  function askRecordDrawOption() {
    return new Promise((resolve) => {
      openModal('录制选项', `
        <label class="inline-check"><input name="recordDraw" type="radio" value="1" checked /> 录制时绘制识别框</label>
        <label class="inline-check"><input name="recordDraw" type="radio" value="0" /> 录制时不绘制识别框</label>
      `);
      modalCancelBtn.onclick = () => { closeModal(); resolve(null); };
      modalOkBtn.onclick = () => {
        const selected = document.querySelector('input[name="recordDraw"]:checked');
        closeModal();
        resolve(selected?.value === '1');
      };
    });
  }

  function askAddCameraPayload() {
    return new Promise((resolve) => {
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
    });
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

  function setActiveId() {
    document.querySelectorAll('#videoTable tbody tr').forEach((tr) => {
      const id = Number(tr.dataset.id);
      tr.classList.toggle('active-row', id === currentVideoId);
    });
    previewTitle.textContent = currentVideoId > 0 ? `预览 ${currentVideoId}` : '预览';
  }

  function drawBoxes(ctx, width, height, recognition) {
    if (!recognition) return;
    const srcW = recognition.frame_width || width || 1;
    const srcH = recognition.frame_height || height || 1;
    for (const p of recognition.points || []) {
      const x = p.x1 / srcW * width;
      const y = p.y1 / srcH * height;
      const w = (p.x2 - p.x1) / srcW * width;
      const h = (p.y2 - p.y1) / srcH * height;
      ctx.strokeStyle = p.is_light ? '#22c55e' : '#ef4444';
      ctx.lineWidth = 1;
      ctx.strokeRect(x, y, w, h);
    }
  }

  function redraw() {
    fctx.clearRect(0, 0, frameCanvas.width, frameCanvas.height);
    octx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
    if (!latestFrame) return;

    fctx.drawImage(latestFrame, 0, 0, frameCanvas.width, frameCanvas.height);
    if (!drawToggle.checked || !latestRecognition) return;
    drawBoxes(octx, overlayCanvas.width, overlayCanvas.height, latestRecognition);
  }

  async function fetchFrame(videoId) {
    const resp = await fetch(`/api/video/${videoId}/frame`);
    if (!resp.ok) return null;
    const data = await resp.json();
    const img = new Image();
    img.src = `data:image/png;base64,${data.image}`;
    await img.decode();
    return { ...data, img };
  }

  async function fetchRecognition(videoId) {
    const resp = await fetch(`/api/video/${videoId}/recognition`);
    if (!resp.ok) return null;
    return resp.json();
  }

  async function pollPreview() {
    if (currentVideoId < 0) return;
    try {
      const data = await fetchFrame(currentVideoId);
      if (!data) return;
      if (frameCanvas.width !== data.width || frameCanvas.height !== data.height) {
        syncSize(data.width, data.height);
      }
      latestFrame = data.img;
      redraw();
    } catch (_e) {}
  }

  async function pollRecognition() {
    if (currentVideoId < 0) return;
    try {
      latestRecognition = await fetchRecognition(currentVideoId);
      redraw();
    } catch (_e) {}
  }

  function flushRecorder(rec) {
    if (!rec.chunks.length) return;
    const blob = new Blob(rec.chunks, { type: 'video/webm' });
    rec.chunks = [];
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `video_${rec.videoId}_${Date.now()}.webm`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  function startRecording(videoId, btn, drawRecognition) {
    const cvs = document.createElement('canvas');
    const cctx = cvs.getContext('2d');
    const stream = cvs.captureStream(5);
    const mediaRecorder = new MediaRecorder(stream, { mimeType: 'video/webm' });
    const rec = { videoId, drawRecognition, chunks: [], mediaRecorder, frameTimer: null, chunkTimer: null, flushTimer: null, recognitionTimer: null, latestRecognition: null, active: true };

    mediaRecorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) rec.chunks.push(e.data);
    };
    mediaRecorder.start(1000);

    rec.chunkTimer = setInterval(() => {
      if (mediaRecorder.state === 'recording') mediaRecorder.requestData();
    }, 1000);

    rec.flushTimer = setInterval(() => {
      flushRecorder(rec);
      setMsg(`录制 ${videoId} 自动分片下载（10分钟）`);
    }, AUTO_DOWNLOAD_MS);

    if (rec.drawRecognition) {
      rec.recognitionTimer = setInterval(async () => {
        if (!rec.active) return;
        try {
          rec.latestRecognition = await fetchRecognition(videoId);
        } catch (_e) {}
      }, 300);
    }

    rec.frameTimer = setInterval(async () => {
      if (!rec.active) return;
      try {
        const data = await fetchFrame(videoId);
        if (!data) return;
        if (cvs.width !== data.width || cvs.height !== data.height) {
          cvs.width = data.width;
          cvs.height = data.height;
        }
        cctx.clearRect(0, 0, cvs.width, cvs.height);
        cctx.drawImage(data.img, 0, 0, cvs.width, cvs.height);
        if (rec.drawRecognition) {
          drawBoxes(cctx, cvs.width, cvs.height, rec.latestRecognition);
        }
      } catch (_e) {}
    }, 250);

    recorders.set(videoId, rec);
    btn.textContent = '结束录制';
  }

  function stopRecording(videoId, btn) {
    const rec = recorders.get(videoId);
    if (!rec) return;
    rec.active = false;
    clearInterval(rec.frameTimer);
    clearInterval(rec.chunkTimer);
    clearInterval(rec.flushTimer);
    clearInterval(rec.recognitionTimer);

    if (rec.mediaRecorder.state === 'recording') {
      rec.mediaRecorder.requestData();
      rec.mediaRecorder.stop();
    }
    flushRecorder(rec);
    recorders.delete(videoId);
    btn.textContent = '开始录制';
  }

  async function openSettingsPage() {
    const password = await askPassword();
    if (!password) return;
    window.location.href = `/settings?password=${encodeURIComponent(password)}`;
  }

  async function openAnnotatePage(videoId) {
    const password = await askPassword();
    if (!password) return;
    const drawRecognition = await askRecordDrawOption();
    if (drawRecognition === null) return;
    window.location.href = `/annotate/${videoId}?password=${encodeURIComponent(password)}&draw_recognition=${drawRecognition ? 1 : 0}`;
  }

  async function addCamera() {
    const password = await askPassword();
    if (!password) return;
    const cameraPayload = await askAddCameraPayload();
    if (!cameraPayload) return;

    try {
      const resp = await fetch('/api/camera', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password, ...cameraPayload }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        setMsg(`添加失败: ${data.error || resp.status}`, true);
        return;
      }
      setMsg('添加摄像头成功，正在刷新...');
      setTimeout(() => window.location.reload(), 800);
    } catch (e) {
      setMsg(`添加失败: ${e}`, true);
    }
  }

  document.getElementById('openSettingsBtn').addEventListener('click', openSettingsPage);
  document.getElementById('addCameraBtn').addEventListener('click', addCamera);

  document.getElementById('videoTable').addEventListener('click', async (e) => {
    const id = Number(e.target.dataset.id);
    if (!id) return;

    if (e.target.classList.contains('id-btn')) {
      currentVideoId = id;
      latestFrame = null;
      latestRecognition = null;
      setActiveId();
      return;
    }

    if (e.target.classList.contains('annotate-btn')) {
      await openAnnotatePage(id);
      return;
    }

    if (e.target.classList.contains('record-btn')) {
      if (recorders.has(id)) {
        stopRecording(id, e.target);
      } else {
        const drawRecognition = await askRecordDrawOption();
        if (drawRecognition === null) return;
        startRecording(id, e.target, drawRecognition);
      }
    }
  });

  drawToggle.addEventListener('change', redraw);
  modalMask.addEventListener('click', (e) => {
    if (e.target === modalMask) closeModal();
  });

  window.addEventListener('beforeunload', () => {
    for (const [vid] of recorders.entries()) stopRecording(vid, { textContent: '' });
  });

  setActiveId();
  setInterval(pollPreview, 250);
  setInterval(pollRecognition, 250);
  pollPreview();
  pollRecognition();
})();
