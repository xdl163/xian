import hashlib
import threading
import time
from typing import Any

import cv2
import yaml
from flask import Flask, Response, jsonify, request

import settings


app = Flask(__name__)
_state_lock = threading.Lock()


def _video_by_id(video_id: int):
    for video in settings.video_list:
        if int(video.id) == int(video_id):
            return video
    return None


def _read_yaml(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _annotation_from_yaml(video):
    data = _read_yaml(video.yaml_path)
    width = max(1, int(video.frame_width))
    height = max(1, int(video.frame_height))

    anns = []
    for idx, coord in (data.get("yarn", {}) or {}).items():
        try:
            x, y = coord
            if x <= 1 and y <= 1:
                x, y = int(x * width), int(y * height)
            anns.append({"type": "yarn", "id": str(idx), "coords": [int(x), int(y)]})
        except Exception:
            continue

    for coord in (data.get("laser_emitter", []) or []):
        try:
            x, y = coord
            if x <= 1 and y <= 1:
                x, y = int(x * width), int(y * height)
            anns.append({"type": "laser_emitter", "id": "1", "coords": [int(x), int(y)]})
        except Exception:
            continue

    for coord in (data.get("laser_wall", []) or []):
        try:
            x, y = coord
            if x <= 1 and y <= 1:
                x, y = int(x * width), int(y * height)
            anns.append({"type": "laser_wall", "id": "1", "coords": [int(x), int(y)]})
        except Exception:
            continue

    hsv_range = data.get("hsv_range", getattr(video, "hsv_range", {
        "h_min": 0, "h_max": 179,
        "s_min": 0, "s_max": 255,
        "v_min": 178, "v_max": 255,
    }))

    return {
        "meta": {
            "video_id": data.get("video_id", ""),
            "add_type": data.get("add_type", ""),
            "id": data.get("id", ""),
            "video_type": data.get("video_type", ""),
            "video_url": data.get("video_url", ""),
            "hsv_range": hsv_range,
        },
        "annotations": anns,
    }


def _save_annotation(video, payload: dict[str, Any]) -> None:
    width = max(1, int(video.frame_width))
    height = max(1, int(video.frame_height))
    data_to_save = _read_yaml(video.yaml_path)

    hsv_range = payload.get("meta", {}).get("hsv_range", getattr(video, "hsv_range", {}))
    video.hsv_range = hsv_range.copy()

    yarn_data = {}
    laser_emitter_data = []
    laser_wall_data = []
    video.xian_points = {}
    video.laser_emitter = []
    video.laser_wall = []

    for item in payload.get("annotations", []):
        x, y = item.get("coords", [0, 0])
        x = max(0, min(int(x), width - 1))
        y = max(0, min(int(y), height - 1))
        x1 = max(x - settings.crap_w * 2, 0)
        y1 = max(y - settings.crap_h * 2, 0)
        x2 = min(x + settings.crap_w * 2, width - 1)
        y2 = min(y + settings.crap_h * 2, height - 1)

        if item.get("type") == "yarn":
            ann_id = str(item.get("id", ""))
            if not ann_id:
                continue
            video.xian_points[ann_id] = (x, y, x1, y1, x2, y2)
            yarn_data[ann_id] = [x / width, y / height]
        elif item.get("type") == "laser_emitter":
            video.laser_emitter.append([x, y, x1, y1, x2, y2])
            laser_emitter_data.append([x / width, y / height])
        elif item.get("type") == "laser_wall":
            video.laser_wall.append([x, y, x1, y1, x2, y2])
            laser_wall_data.append([x / width, y / height])

    meta = payload.get("meta", {})
    video.video_id = str(meta.get("video_id", ""))
    video.add_type = str(meta.get("add_type", ""))
    video.id = str(meta.get("id", video.id))

    data_to_save["yarn"] = yarn_data
    data_to_save["laser_emitter"] = laser_emitter_data
    data_to_save["laser_wall"] = laser_wall_data
    data_to_save["video_id"] = video.video_id
    data_to_save["add_type"] = video.add_type
    data_to_save["id"] = video.id
    data_to_save["video_type"] = meta.get("video_type", "")
    data_to_save["video_url"] = meta.get("video_url", "")
    data_to_save["hsv_range"] = hsv_range

    with open(video.yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data_to_save, f, allow_unicode=True)


@app.get("/")
def index():
    rows = []
    for v in settings.video_list:
        rows.append(f"<tr><td>{v.id}</td><td><a href='/preview/{v.id}'>预览</a></td><td><a href='/annotate/{v.id}'>标注</a></td></tr>")
    html = f"""
    <html><head><meta charset='utf-8'><title>断线检测</title></head>
    <body>
      <h2>断线检测（Web）</h2>
      <p>可通过局域网访问： http://服务器IP:5000</p>
      <table border='1' cellpadding='6'><tr><th>Video ID</th><th>预览</th><th>标注</th></tr>{''.join(rows)}</table>
    </body></html>
    """
    return Response(html, mimetype="text/html")


@app.get('/preview/<int:video_id>')
def preview_page(video_id: int):
    return Response(f"""
    <html><head><meta charset='utf-8'><title>预览 {video_id}</title></head>
    <body><h3>预览 {video_id}</h3><img src='/stream/{video_id}' style='max-width:100%;border:1px solid #ccc'/><p><a href='/'>返回</a></p></body></html>
    """, mimetype='text/html')


@app.get('/stream/<int:video_id>')
def stream(video_id: int):
    video = _video_by_id(video_id)
    if video is None:
        return Response("not found", status=404)

    def gen():
        while True:
            frame = getattr(video, 'this_frame', None)
            if frame is None:
                time.sleep(0.2)
                continue
            ok, buf = cv2.imencode('.jpg', frame)
            if not ok:
                time.sleep(0.05)
                continue
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n')
            time.sleep(0.15)

    return Response(gen(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.get('/api/video/<int:video_id>/annotation')
def get_annotation(video_id: int):
    video = _video_by_id(video_id)
    if video is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(_annotation_from_yaml(video))


@app.post('/api/video/<int:video_id>/annotation')
def save_annotation(video_id: int):
    video = _video_by_id(video_id)
    if video is None:
        return jsonify({"error": "not found"}), 404
    payload = request.get_json(force=True, silent=True) or {}
    with _state_lock:
        _save_annotation(video, payload)
    return jsonify({"ok": True})


@app.post('/api/change-password')
def change_password():
    payload = request.get_json(force=True, silent=True) or {}
    old_pwd = str(payload.get('old_password', ''))
    new_pwd = str(payload.get('new_password', ''))
    if hashlib.sha256(old_pwd.encode('utf-8')).hexdigest() != settings.passwd:
        return jsonify({"ok": False, "message": "原密码错误"}), 400
    settings.passwd = hashlib.sha256(new_pwd.encode('utf-8')).hexdigest()
    if settings.license_data:
        from activate import save_license_file
        settings.license_data['passwd'] = settings.passwd
        save_license_file(settings.license_data)
    return jsonify({"ok": True})


@app.get('/annotate/<int:video_id>')
def annotate_page(video_id: int):
    video = _video_by_id(video_id)
    if video is None:
        return Response("not found", status=404)
    return Response(f"""
<html><head><meta charset='utf-8'><title>标注 {video_id}</title>
<style>body{{font-family:Arial;margin:16px}} #board{{position:relative;display:inline-block}} #layer{{position:absolute;left:0;top:0}} table td,th{{padding:4px 8px}}</style>
</head><body>
<h3>标注视频 {video_id}</h3>
<div id='board'><img id='img' src='/stream/{video_id}' width='960'/><canvas id='layer'></canvas></div>
<div>
  类型:
  <select id='annType'><option value='yarn'>纱线</option><option value='laser_emitter'>激光发射器</option><option value='laser_wall'>激光墙壁</option></select>
  点编号:<input id='pointId' placeholder='可重命名' />
  <button onclick='renamePoint()'>重命名选中点</button>
  <button onclick='removeSelected()'>删除选中点</button>
</div>
<div>
  HSV: Hmin<input id='h_min' size='3'/> Hmax<input id='h_max' size='3'/> Smin<input id='s_min' size='3'/> Smax<input id='s_max' size='3'/> Vmin<input id='v_min' size='3'/> Vmax<input id='v_max' size='3'/>
</div>
<div>
 video_id<input id='video_id'/> add_type<input id='add_type'/> id<input id='meta_id'/> video_type<input id='video_type'/> video_url<input id='video_url' size='40'/>
</div>
<p><button onclick='saveAll()'>保存</button> <a href='/'>返回</a></p>
<table border='1'><thead><tr><th>#</th><th>类型</th><th>坐标</th></tr></thead><tbody id='rows'></tbody></table>
<script>
let annotations=[]; let selected=-1;
const img=document.getElementById('img'); const c=document.getElementById('layer'); const ctx=c.getContext('2d');
function syncSize(){{ c.width=img.clientWidth; c.height=img.clientHeight; c.style.width=img.clientWidth+'px'; c.style.height=img.clientHeight+'px'; draw(); }}
img.onload=syncSize; window.onresize=syncSize;
function draw(){{ctx.clearRect(0,0,c.width,c.height); annotations.forEach((a,i)=>{{ const x=a.coords[0]/{video.frame_width}*c.width; const y=a.coords[1]/{video.frame_height}*c.height; ctx.strokeStyle=i===selected?'#f00':'#0f0'; ctx.strokeRect(x-8,y-8,16,16); ctx.fillStyle='#fff'; ctx.fillText(a.id,x+10,y-10); }}); renderRows(); }}
function renderRows(){{ const rows=document.getElementById('rows'); rows.innerHTML=''; annotations.forEach((a,i)=>{{ const tr=document.createElement('tr'); tr.innerHTML=`<td>${{a.id}}</td><td>${{a.type}}</td><td>${{a.coords[0]}},${{a.coords[1]}}</td>`; tr.onclick=()=>{{selected=i;document.getElementById('pointId').value=a.id;draw();}}; rows.appendChild(tr); }}); }}
c.onclick=(e)=>{{ const rect=c.getBoundingClientRect(); const x=(e.clientX-rect.left)/c.width*{video.frame_width}; const y=(e.clientY-rect.top)/c.height*{video.frame_height}; const t=document.getElementById('annType').value; if(t==='yarn'){{ let pid=document.getElementById('pointId').value.trim(); if(!pid) pid=String(Date.now()).slice(-4); const idx=annotations.findIndex(a=>a.type==='yarn'&&a.id===pid); if(idx>=0) annotations[idx].coords=[Math.round(x),Math.round(y)]; else annotations.push({{type:'yarn',id:pid,coords:[Math.round(x),Math.round(y)]}}); }} else {{ const idx=annotations.findIndex(a=>a.type===t); if(idx>=0) annotations[idx].coords=[Math.round(x),Math.round(y)]; else annotations.push({{type:t,id:'1',coords:[Math.round(x),Math.round(y)]}}); }} draw(); }}
function renamePoint(){{ if(selected<0) return; const name=document.getElementById('pointId').value.trim(); if(!name) return; annotations[selected].id=name; draw(); }}
function removeSelected(){{ if(selected<0) return; annotations.splice(selected,1); selected=-1; draw(); }}
function getMeta(){{return{{video_id:document.getElementById('video_id').value,add_type:document.getElementById('add_type').value,id:document.getElementById('meta_id').value,video_type:document.getElementById('video_type').value,video_url:document.getElementById('video_url').value,hsv_range:{{h_min:+h_min.value,h_max:+h_max.value,s_min:+s_min.value,s_max:+s_max.value,v_min:+v_min.value,v_max:+v_max.value}}}}}}
async function saveAll(){{ const res=await fetch('/api/video/{video_id}/annotation',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{meta:getMeta(),annotations}})}}); alert(res.ok?'保存成功':'保存失败'); }}
(async()=>{{ const data=await (await fetch('/api/video/{video_id}/annotation')).json(); annotations=data.annotations||[]; const m=data.meta||{{}}; video_id.value=m.video_id||''; add_type.value=m.add_type||''; meta_id.value=m.id||''; video_type.value=m.video_type||''; video_url.value=m.video_url||''; const h=m.hsv_range||{{}}; ['h_min','h_max','s_min','s_max','v_min','v_max'].forEach(k=>window[k].value=(h[k]??0)); draw(); }})();
</script>
</body></html>
    """, mimetype='text/html')


def run_web_server(host: str = '0.0.0.0', port: int = 5000):
    app.run(host=host, port=port, threaded=True)
