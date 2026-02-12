(() => {
  const { videoId, frameWidth, frameHeight } = window.APP_CONFIG;

  let annotations = [];
  let selected = -1;
  let drag = null;

  let equalMode = false;
  let equalStart = null;

  let frameBuffer = [];
  const maxFrames = 1000;
  let liveMode = true;
  let showFrameIndex = 0;
  let pollTimer = null;
  const frameCache = new Map();

  const canvas = document.getElementById('frameCanvas');
  const ctx = canvas.getContext('2d');
  ctx.imageSmoothingEnabled = true;
  const msg = document.getElementById('msg');
  const slider = document.getElementById('frameSlider');

  const annType = document.getElementById('annType');
  const pointId = document.getElementById('pointId');
  const autoNumber = document.getElementById('autoNumber');
  const returnBtn = document.getElementById('returnBtn');

  function $(id) { return document.getElementById(id); }

  function setMsg(text, error = false) {
    msg.textContent = text;
    msg.style.color = error ? '#f87171' : '#9ca3af';
  }

  function clamp(v, min, max) {
    return Math.max(min, Math.min(max, v));
  }

  function drawFrameAndAnnotations() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (frameBuffer.length > 0) {
      const idx = liveMode ? frameBuffer.length - 1 : clamp(showFrameIndex, 0, frameBuffer.length - 1);
      const frame = frameBuffer[idx];
      if (frame) {
        const img = frameCache.get(frame.ts);
        if (img) ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      }
    }

    annotations.forEach((ann, index) => {
      const x = ann.coords[0] / frameWidth * canvas.width;
      const y = ann.coords[1] / frameHeight * canvas.height;

      ctx.strokeStyle = index === selected ? '#ef4444' : '#22c55e';
      ctx.lineWidth = 1;
      ctx.strokeRect(x - 8, y - 8, 16, 16);

      ctx.fillStyle = '#ffffff';
      ctx.font = '12px sans-serif';
      ctx.fillText(String(ann.id), x + 10, y - 10);
    });

  }

  function frameToCanvas(e) {
    const rect = canvas.getBoundingClientRect();
    return {
      x: Math.round((e.clientX - rect.left) / rect.width * frameWidth),
      y: Math.round((e.clientY - rect.top) / rect.height * frameHeight),
    };
  }

  function findAnnByPixel(xPix, yPix) {
    const hitRadius = 10;
    for (let i = annotations.length - 1; i >= 0; i--) {
      const a = annotations[i];
      const dx = a.coords[0] - xPix;
      const dy = a.coords[1] - yPix;
      if (Math.abs(dx) <= hitRadius && Math.abs(dy) <= hitRadius) {
        return i;
      }
    }
    return -1;
  }

  function findYarnDup(newId, skipIndex) {
    return annotations.some((ann, index) => ann.type === 'yarn' && ann.id === newId && index !== skipIndex);
  }

  function nextAutoId() {
    const yarnIds = annotations
      .filter((a) => a.type === 'yarn' && /^\d+$/.test(String(a.id)))
      .map((a) => Number(a.id));

    let candidate = 1;
    if (yarnIds.length > 0) {
      const last = annotations
        .filter((a) => a.type === 'yarn' && /^\d+$/.test(String(a.id)))
        .slice(-1)[0];
      candidate = Number(last ? last.id : Math.max(...yarnIds)) + 1;
    }

    const used = new Set(annotations.filter((a) => a.type === 'yarn').map((a) => String(a.id)));
    while (used.has(String(candidate))) candidate += 1;
    return String(candidate);
  }

  function addOrMovePoint(x, y) {
    const type = annType.value;

    if (type === 'yarn') {
      let id = pointId.value.trim();
      if (autoNumber.checked || !id) {
        id = nextAutoId();
      }

      const idx = annotations.findIndex((ann) => ann.type === 'yarn' && ann.id === id);
      if (idx >= 0) {
        annotations[idx].coords = [x, y];
        selected = idx;
      } else {
        annotations.push({ type: 'yarn', id, coords: [x, y] });
        selected = annotations.length - 1;
      }
      pointId.value = id;
    } else {
      const idx = annotations.findIndex((ann) => ann.type === type);
      if (idx >= 0) {
        annotations[idx].coords = [x, y];
        selected = idx;
      } else {
        annotations.push({ type, id: '1', coords: [x, y] });
        selected = annotations.length - 1;
      }
    }
  }

  function addEqualDistancePoints(p1, p2) {
    const inputCount = prompt('请输入等距点数量（>=2）', '5');
    if (!inputCount) return;

    const count = Number(inputCount);
    if (!Number.isInteger(count) || count < 2) {
      setMsg('数量必须是 >=2 的整数', true);
      return;
    }

    const direction = prompt('编号方向：输入 L 表示从左到右，输入 R 表示从右到左', 'L');
    const dir = (direction || 'L').trim().toUpperCase() === 'R' ? 'R' : 'L';

    const pts = [];
    for (let i = 0; i < count; i++) {
      const t = i / (count - 1);
      pts.push([
        Math.round(p1.x + (p2.x - p1.x) * t),
        Math.round(p1.y + (p2.y - p1.y) * t),
      ]);
    }

    const sorted = pts
      .map((coords) => ({ coords }))
      .sort((a, b) => a.coords[0] - b.coords[0]);
    if (dir === 'R') sorted.reverse();

    sorted.forEach((item) => {
      const id = nextAutoId();
      annotations.push({ type: 'yarn', id, coords: item.coords });
    });

    selected = annotations.length - 1;
    drawFrameAndAnnotations();
    setMsg('等距标注完成');
  }

  function readMeta() {
    return {
      video_id: $('video_id').value,
      add_type: $('add_type').value,
      id: $('meta_id').value,
      video_type: $('video_type').value,
      video_url: $('video_url').value,
      hsv_range: {
        h_min: +$('h_min').value,
        h_max: +$('h_max').value,
        s_min: +$('s_min').value,
        s_max: +$('s_max').value,
        v_min: +$('v_min').value,
        v_max: +$('v_max').value,
      },
    };
  }

  function fillMeta(meta) {
    $('video_id').value = meta.video_id || '';
    $('add_type').value = meta.add_type || '';
    $('meta_id').value = meta.id || '';
    $('video_type').value = meta.video_type || '';
    $('video_url').value = meta.video_url || '';
    const hsv = meta.hsv_range || {};
    ['h_min', 'h_max', 's_min', 's_max', 'v_min', 'v_max'].forEach((k) => {
      $(k).value = hsv[k] ?? 0;
    });
  }

  async function fetchFrame() {
    try {
      const resp = await fetch(`/api/video/${videoId}/frame`);
      if (!resp.ok) return;
      const data = await resp.json();

      if (canvas.width !== data.width || canvas.height !== data.height) {
        canvas.width = data.width || frameWidth;
        canvas.height = data.height || frameHeight;
        fitCanvasToPage();
      }

      const img = new Image();
      img.src = `data:image/png;base64,${data.image}`;
      await img.decode();

      frameCache.set(data.ts, img);
      frameBuffer.push({ ts: data.ts });
      if (frameBuffer.length > maxFrames) {
        const removed = frameBuffer.shift();
        frameCache.delete(removed.ts);
      }

      slider.max = String(Math.max(0, frameBuffer.length - 1));
      if (liveMode) {
        slider.value = slider.max;
      }
      drawFrameAndAnnotations();
    } catch (_e) {
      // ignore transient frame errors
    }
  }

  function startFramePolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(fetchFrame, 350);
    fetchFrame();
  }

  function fitCanvasToPage() {
    if (!canvas.width || !canvas.height) return;
    const container = canvas.parentElement;
    if (!container) return;
    const maxW = Math.max(320, container.clientWidth - 4);
    const ratio = canvas.width / canvas.height;
    const viewW = Math.min(maxW, canvas.width);
    const viewH = Math.round(viewW / ratio);
    canvas.style.width = `${viewW}px`;
    canvas.style.height = `${viewH}px`;
  }

  function clearFrameCache() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
    frameBuffer = [];
    frameCache.clear();
  }

  function bindEvents() {
    if (returnBtn) {
      returnBtn.addEventListener('click', clearFrameCache);
    }

    canvas.addEventListener('mousedown', (e) => {
      const p = frameToCanvas(e);
      const hit = findAnnByPixel(p.x, p.y);

      if (hit >= 0) {
        selected = hit;
        pointId.value = annotations[hit].id;
        drag = { index: hit, dx: p.x - annotations[hit].coords[0], dy: p.y - annotations[hit].coords[1] };
        drawFrameAndAnnotations();
      }
    });

    canvas.addEventListener('dblclick', (e) => {
      const p = frameToCanvas(e);
      if (equalMode) {
        if (!equalStart) {
          equalStart = p;
          setMsg('已选第1个点，请双击第2个点');
        } else {
          addEqualDistancePoints(equalStart, p);
          equalStart = null;
          equalMode = false;
        }
        return;
      }

      addOrMovePoint(p.x, p.y);
      drawFrameAndAnnotations();
    });

    canvas.addEventListener('mousemove', (e) => {
      if (!drag) return;
      const p = frameToCanvas(e);
      const ann = annotations[drag.index];
      ann.coords[0] = clamp(p.x - drag.dx, 0, frameWidth - 1);
      ann.coords[1] = clamp(p.y - drag.dy, 0, frameHeight - 1);
      drawFrameAndAnnotations();
    });

    window.addEventListener('mouseup', () => { drag = null; });

    window.addEventListener('keydown', (e) => {
      if (selected < 0) return;
      const ann = annotations[selected];
      if (!ann) return;

      let moved = false;
      if (e.key === 'ArrowUp') { ann.coords[1] = clamp(ann.coords[1] - 1, 0, frameHeight - 1); moved = true; }
      if (e.key === 'ArrowDown') { ann.coords[1] = clamp(ann.coords[1] + 1, 0, frameHeight - 1); moved = true; }
      if (e.key === 'ArrowLeft') { ann.coords[0] = clamp(ann.coords[0] - 1, 0, frameWidth - 1); moved = true; }
      if (e.key === 'ArrowRight') { ann.coords[0] = clamp(ann.coords[0] + 1, 0, frameWidth - 1); moved = true; }
      if (moved) {
        e.preventDefault();
        drawFrameAndAnnotations();
      }
    });

    slider.addEventListener('input', () => {
      const idx = Number(slider.value);
      showFrameIndex = idx;
      liveMode = idx >= frameBuffer.length - 1;
      drawFrameAndAnnotations();
    });

    window.addEventListener('resize', fitCanvasToPage);

    document.getElementById('renameBtn').onclick = () => {
      if (selected < 0) return;
      const newId = pointId.value.trim();
      if (!newId) return;

      const ann = annotations[selected];
      if (ann.type === 'yarn' && findYarnDup(newId, selected)) {
        setMsg('重命名失败：纱线点编号重复', true);
        return;
      }
      ann.id = newId;
      drawFrameAndAnnotations();
      setMsg('已重命名');
    };

    document.getElementById('removeBtn').onclick = () => {
      if (selected < 0) return;
      annotations.splice(selected, 1);
      selected = -1;
      pointId.value = '';
      drawFrameAndAnnotations();
    };

    document.getElementById('removeAllBtn').onclick = () => {
      annotations = [];
      selected = -1;
      pointId.value = '';
      setMsg('已清空全部标注');
      drawFrameAndAnnotations();
    };

    document.getElementById('equalBtn').onclick = () => {
      equalMode = true;
      equalStart = null;
      setMsg('等距标注模式：请依次点击2个点');
    };

    document.getElementById('saveBtn').onclick = async () => {
      try {
        const resp = await fetch(`/api/video/${videoId}/annotation`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ meta: readMeta(), annotations }),
        });
        if (resp.ok) {
          setMsg('保存成功');
        } else {
          const data = await resp.json().catch(() => ({}));
          setMsg(`保存失败: ${data.error || resp.status}`, true);
        }
      } catch (err) {
        setMsg(`保存失败: ${err}`, true);
      }
    };
  }

  async function init() {
    try {
      const data = await (await fetch(`/api/video/${videoId}/annotation`)).json();
      annotations = data.annotations || [];
      fillMeta(data.meta || {});
      bindEvents();
      startFramePolling();
      drawFrameAndAnnotations();
    } catch (err) {
      setMsg(`加载失败: ${err}`, true);
    }
  }

  window.addEventListener('beforeunload', clearFrameCache);

  init();
})();
