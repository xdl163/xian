(() => {
  const { videoId } = window.PREVIEW_CONFIG;
  const img = document.getElementById('previewImg');
  const canvas = document.getElementById('previewOverlay');
  const ctx = canvas.getContext('2d');

  function syncSize() {
    canvas.width = img.clientWidth;
    canvas.height = img.clientHeight;
    canvas.style.width = `${img.clientWidth}px`;
    canvas.style.height = `${img.clientHeight}px`;
  }

  function draw(result) {
    if (!result) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const srcW = result.frame_width || 1;
    const srcH = result.frame_height || 1;

    for (const p of result.points || []) {
      const x = p.x1 / srcW * canvas.width;
      const y = p.y1 / srcH * canvas.height;
      const w = (p.x2 - p.x1) / srcW * canvas.width;
      const h = (p.y2 - p.y1) / srcH * canvas.height;
      ctx.strokeStyle = p.is_light ? '#22c55e' : '#ef4444';
      ctx.lineWidth = 1;
      ctx.strokeRect(x, y, w, h);
    }
  }

  async function poll() {
    try {
      const resp = await fetch(`/api/video/${videoId}/recognition`);
      if (resp.ok) {
        const data = await resp.json();
        draw(data);
      }
    } catch (_e) {
      // ignore
    }
  }

  img.addEventListener('load', syncSize);
  window.addEventListener('resize', syncSize);
  syncSize();
  setInterval(poll, 250);
})();
