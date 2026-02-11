(() => {
  const { videoId, frameWidth, frameHeight } = window.APP_CONFIG;

  let annotations = [];
  let selected = -1;

  const img = document.getElementById('img');
  const canvas = document.getElementById('layer');
  const ctx = canvas.getContext('2d');
  const rows = document.getElementById('rows');
  const msg = document.getElementById('msg');

  const annType = document.getElementById('annType');
  const pointId = document.getElementById('pointId');

  function $(id) { return document.getElementById(id); }

  function syncSize() {
    canvas.width = img.clientWidth;
    canvas.height = img.clientHeight;
    canvas.style.width = `${img.clientWidth}px`;
    canvas.style.height = `${img.clientHeight}px`;
    draw();
  }

  function setMsg(text, error = false) {
    msg.textContent = text;
    msg.style.color = error ? '#f87171' : '#9ca3af';
  }

  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
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
    renderRows();
  }

  function renderRows() {
    rows.innerHTML = '';
    annotations.forEach((ann, index) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${ann.id}</td><td>${ann.type}</td><td>${ann.coords[0]}, ${ann.coords[1]}</td>`;
      tr.onclick = () => {
        selected = index;
        pointId.value = ann.id;
        draw();
      };
      rows.appendChild(tr);
    });
  }

  function findYarnDup(newId, skipIndex) {
    return annotations.some((ann, index) => ann.type === 'yarn' && ann.id === newId && index !== skipIndex);
  }

  canvas.onclick = (e) => {
    const rect = canvas.getBoundingClientRect();
    const x = Math.round((e.clientX - rect.left) / canvas.width * frameWidth);
    const y = Math.round((e.clientY - rect.top) / canvas.height * frameHeight);
    const type = annType.value;

    if (type === 'yarn') {
      let id = pointId.value.trim();
      if (!id) {
        id = String(Date.now()).slice(-4);
      }
      const idx = annotations.findIndex((ann) => ann.type === 'yarn' && ann.id === id);
      if (idx >= 0) {
        annotations[idx].coords = [x, y];
      } else {
        annotations.push({ type: 'yarn', id, coords: [x, y] });
      }
    } else {
      const idx = annotations.findIndex((ann) => ann.type === type);
      if (idx >= 0) {
        annotations[idx].coords = [x, y];
      } else {
        annotations.push({ type, id: '1', coords: [x, y] });
      }
    }

    draw();
  };

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
    draw();
    setMsg('已重命名');
  };

  document.getElementById('removeBtn').onclick = () => {
    if (selected < 0) return;
    annotations.splice(selected, 1);
    selected = -1;
    pointId.value = '';
    draw();
  };

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

  async function init() {
    try {
      const data = await (await fetch(`/api/video/${videoId}/annotation`)).json();
      annotations = data.annotations || [];
      fillMeta(data.meta || {});
      draw();
    } catch (err) {
      setMsg(`加载失败: ${err}`, true);
    }
  }

  img.onload = syncSize;
  window.onresize = syncSize;
  init();
})();
