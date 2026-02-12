(() => {
  const frameCanvas = document.getElementById('previewFrameCanvas');
  const overlayCanvas = document.getElementById('previewOverlay');
  const fctx = frameCanvas.getContext('2d');
  const octx = overlayCanvas.getContext('2d');
  const previewTitle = document.getElementById('previewTitle');
  const drawToggle = document.getElementById('toggleDraw');
  const homeMsg = document.getElementById('homeMsg');

  let currentVideoId = Number(window.INIT_VIDEO_ID || -1);
  let latestFrame = null;
  let latestRecognition = null;

  const recorders = new Map();
  const AUTO_DOWNLOAD_MS = 10 * 60 * 1000;

  function setMsg(text, err = false) {
    homeMsg.textContent = text;
    homeMsg.style.color = err ? '#f87171' : '#9ca3af';
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

  async function fetchFrame(videoId) {
    const resp = await fetch(`/api/video/${videoId}/frame`);
    if (!resp.ok) return null;
    const data = await resp.json();
    const img = new Image();
    img.src = `data:image/png;base64,${data.image}`;
    await img.decode();
    return { ...data, img };
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
      const resp = await fetch(`/api/video/${currentVideoId}/recognition`);
      if (!resp.ok) return;
      latestRecognition = await resp.json();
      redraw();
    } catch (_e) {}
  }

  async function verifyAndOpen(path) {
    const password = prompt('请输入密码');
    if (!password) return;
    const vr = await fetch('/api/verify-password', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password }),
    });
    const vd = await vr.json();
    if (!vd.ok) {
      alert('密码错误');
      return;
    }
    window.location.href = `${path}?password=${encodeURIComponent(password)}`;
  }

  function flushRecorder(rec, force = false) {
    if (!rec.chunks.length) return;
    if (!force && rec.chunks.length < 2) return;
    const blob = new Blob(rec.chunks, { type: 'video/webm' });
    rec.chunks = [];
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `video_${rec.videoId}_${Date.now()}.webm`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  function startRecording(videoId, btn) {
    const cvs = document.createElement('canvas');
    const cctx = cvs.getContext('2d');
    const stream = cvs.captureStream(5);
    const mediaRecorder = new MediaRecorder(stream, { mimeType: 'video/webm' });
    const rec = {
      videoId,
      chunks: [],
      mediaRecorder,
      frameTimer: null,
      chunkTimer: null,
      flushTimer: null,
      active: true,
    };

    mediaRecorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) rec.chunks.push(e.data);
    };

    mediaRecorder.start(1000);

    rec.chunkTimer = setInterval(() => {
      if (mediaRecorder.state === 'recording') mediaRecorder.requestData();
    }, 1000);

    rec.flushTimer = setInterval(() => {
      flushRecorder(rec, true);
      setMsg(`录制 ${videoId} 自动分片下载（10分钟）`);
    }, AUTO_DOWNLOAD_MS);

    rec.frameTimer = setInterval(async () => {
      if (!rec.active) return;
      try {
        const data = await fetchFrame(videoId);
        if (!data) return;
        if (cvs.width !== data.width || cvs.height !== data.height) {
          cvs.width = data.width;
          cvs.height = data.height;
        }
        cctx.drawImage(data.img, 0, 0, cvs.width, cvs.height);
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

    if (rec.mediaRecorder.state === 'recording') {
      rec.mediaRecorder.requestData();
      rec.mediaRecorder.stop();
    }
    flushRecorder(rec, true);
    recorders.delete(videoId);
    btn.textContent = '开始录制';
  }

  document.getElementById('openSettingsBtn').addEventListener('click', () => {
    verifyAndOpen('/settings');
  });

  document.getElementById('videoTable').addEventListener('click', (e) => {
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
      verifyAndOpen(`/annotate/${id}`);
      return;
    }

    if (e.target.classList.contains('record-btn')) {
      if (recorders.has(id)) {
        stopRecording(id, e.target);
      } else {
        startRecording(id, e.target);
      }
    }
  });

  drawToggle.addEventListener('change', redraw);

  window.addEventListener('beforeunload', () => {
    for (const [vid, rec] of recorders.entries()) {
      const fakeBtn = { textContent: '' };
      stopRecording(vid, fakeBtn);
    }
  });
  setActiveId();
  setInterval(pollPreview, 250);
  setInterval(pollRecognition, 250);
  pollPreview();
  pollRecognition();
})();
