(() => {
  const { videoId } = window.PREVIEW_CONFIG;
  const frameCanvas = document.getElementById('previewFrameCanvas');
  const overlayCanvas = document.getElementById('previewOverlay');
  const fctx = frameCanvas.getContext('2d');
  const octx = overlayCanvas.getContext('2d');

  let latestFrame = null;
  let latestRecognition = null;

  function syncSize(width, height) {
    if (!width || !height) return;
    frameCanvas.width = width;
    frameCanvas.height = height;
    overlayCanvas.width = width;
    overlayCanvas.height = height;

    frameCanvas.style.width = '100%';
    frameCanvas.style.height = 'auto';
    overlayCanvas.style.width = frameCanvas.clientWidth ? `${frameCanvas.clientWidth}px` : '100%';
    overlayCanvas.style.height = frameCanvas.clientHeight ? `${frameCanvas.clientHeight}px` : 'auto';
  }

  function redraw() {
    if (!latestFrame) return;

    fctx.clearRect(0, 0, frameCanvas.width, frameCanvas.height);
    fctx.drawImage(latestFrame, 0, 0, frameCanvas.width, frameCanvas.height);

    octx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
    if (!latestRecognition) return;

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
    try {
      const resp = await fetch(`/api/video/${videoId}/frame`);
      if (!resp.ok) return;
      const data = await resp.json();

      if (!frameCanvas.width) syncSize(data.width, data.height);

      const img = new Image();
      img.src = `data:image/png;base64,${data.image}`;
      await img.decode();
      latestFrame = img;
      redraw();
    } catch (_e) {
      // ignore
    }
  }

  async function pollRecognition() {
    try {
      const resp = await fetch(`/api/video/${videoId}/recognition`);
      if (!resp.ok) return;
      latestRecognition = await resp.json();
      redraw();
    } catch (_e) {
      // ignore
    }
  }

  window.addEventListener('resize', () => {
    if (frameCanvas.width && frameCanvas.height) syncSize(frameCanvas.width, frameCanvas.height);
    redraw();
  });

  setInterval(pollFrame, 250);
  setInterval(pollRecognition, 250);
  pollFrame();
  pollRecognition();
})();
