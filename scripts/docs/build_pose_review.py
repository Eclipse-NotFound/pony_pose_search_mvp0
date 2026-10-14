"""Build an offline, real-query review of the matching changes (not an eval score)."""
import base64
import copy
import hashlib
import html
import importlib.util
import io
import json
from pathlib import Path
import sys
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "experiments/schema_review_20261011"
sys.path.insert(0, str(ROOT / "scripts/common"))
sys.path.insert(0, str(ROOT / "scripts/m08"))
import search_similar_poses as current
from pose_matching import search_records
from pose_record import EDGES, finite_xy


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def embed(path):
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((420, 340))
        stream = io.BytesIO()
        im.save(stream, format="JPEG", quality=87)
    return "data:image/jpeg;base64," + base64.b64encode(stream.getvalue()).decode()


def query_diagram(query):
    """Draw retained reference geometry; never pretend this is a recovered image."""
    points = query["reference_points"]
    colors = {"head": "#673a9e", "neck": "#673a9e", "body": "#205b9b",
              "front": "#a63d14", "hind": "#13716d", "tail": "#885414"}
    elements = []
    for name, (start, end) in EDGES.items():
        a, b = points.get(start), points.get(end)
        if not finite_xy(a) or not finite_xy(b):
            continue
        color = colors[name.split(".")[0]]
        elements.append(f'<line x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}" stroke="{color}" stroke-width="3" marker-end="url(#arrow)"/>')
    for point in points.values():
        if finite_xy(point):
            elements.append(f'<circle cx="{point[0]}" cy="{point[1]}" r="2.5" fill="#172336"/>')
    width, height = query["coordinates"]["image_size"]
    return (f'<svg role="img" aria-label="根据查询002留存点位重画的方向示意，原图不可用" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">'
            '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="4" markerHeight="4" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#46505f"/></marker></defs>'
            + ''.join(elements) + '</svg>')


def main():
    spec = importlib.util.spec_from_file_location("m08_before_review", OUT / "before/search_similar_poses.py")
    before = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(before)
    query = read(OUT / "migrated/queries/query_002.json")
    records = [json.loads(line) for line in (OUT / "migrated/official_records.jsonl").read_text(encoding="utf-8").splitlines()]
    legacy_query = read(ROOT / "queries/twilight_unicorn/query_002/query_pose_vector_v2.json")
    items = []
    for episode in ("s01e15", "s01e24"):
        document = read(ROOT / f"poses/twilight_unicorn/s01/pose_vectors_twilight_unicorn_{episode}_v2.json")
        for row in document["items"]:
            row["_episode_id"] = episode
            items.append(row)
    database = {"character_id": "twilight_unicorn", "items": items}
    rules = read(ROOT / "data/meta/keypoint_schemas.json")["schemas"][legacy_query["keypoint_schema_id"]]["vector_rules"]
    options = read(ROOT / "config/runtime_settings.json")["m08"]
    for group, weights in options.get("direction_weight_overrides", {}).items():
        rules[group]["direction_weights"].update(weights)
    common = {"part_weights": options["part_weights"], "sample_missing_penalty": options["sample_missing_penalty"]}
    a = before.search(copy.deepcopy(legacy_query), copy.deepcopy(database), rules, version="v2", top_n=6, **common)
    b = current.search(copy.deepcopy(legacy_query), copy.deepcopy(database), rules, version="v2", top_n=6, **common)
    c = search_records(query, records, top_n=6, **common)
    d = search_records(query, records, top_n=6, allow_mirror=True, **common)
    evidence = {"query": query["record_id"], "same_candidate_count": len(items),
                "before": a, "fixed_directions": b, "context_default": c, "context_mirrored": d,
                "query_image_status": "constant_color_image; retained points shown as a schematic",
                "note": "Same 49 records for all variants; a descriptive review of retained query geometry, not a human relevance benchmark."}
    (OUT / "ranking-comparison.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def cards(rows, modern=False):
        chunks = []
        for rank, row in enumerate(rows, 1):
            image_path = row["source"]["image_path"] if modern else row["crop_path"]
            score = row["score"] if modern else row["similarity_score"]
            badge = '<span class="badge">需要左右翻转</span>' if row.get("mirrored") else ''
            extra = (f'<p>方向 {row["direction_score"]:.3f} · 视角扣分 {row["view_penalty"]:.3f} · 位置扣分 {row["layout_penalty"]:.3f}</p>'
                     f'<p>比较视角 {row["compared_views"]} 项，位置 {row["compared_layout_anchors"]} 项</p>') if modern else ''
            # Originals remain visible as originals; the badge explains a transformed match.
            chunks.append(f'<article><div class="rank">#{rank}　得分 {score:.3f} {badge}</div><img alt="候选角色原始裁剪" src="{embed(ROOT / image_path)}"><p class="id">{html.escape(row["sample_id"])}</p>{extra}</article>')
        return ''.join(chunks)

    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>姿态检索复盘 · 排序对照</title>
<style>*{box-sizing:border-box}body{margin:0;background:#f3f4f6;color:#172336;font:16px/1.65 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1420px;margin:auto;padding:32px}h1{font-size:32px;margin:0 0 12px}h2{font-size:21px;margin:0 0 12px}.intro,.query{background:#fff;padding:22px;border-radius:16px;margin-bottom:20px}.query{display:flex;gap:24px;align-items:center}.query img{width:240px;max-height:270px;object-fit:contain}.columns{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px}article{background:white;border:1px solid #dde2ea;border-radius:12px;padding:12px;margin:12px 0}article img{width:100%;height:240px;object-fit:contain;background:#eee;border-radius:7px}.rank{font-weight:700}.id{font-size:12px;overflow-wrap:anywhere}article p{font-size:13px;margin:7px 0}.badge{background:#fff0cd;color:#754900;padding:2px 7px;border-radius:6px;font-size:12px}button{font:inherit;border:1px solid #8b8ecb;background:#fff;border-radius:8px;padding:8px 12px;cursor:pointer}button[aria-pressed=true]{background:#484394;color:#fff}.note{color:#525f72}.hidden{display:none}@media(max-width:820px){main{padding:18px}.columns{grid-template-columns:1fr}.query{display:block}.query img{max-width:100%}h1{font-size:26px}}</style>
<main><div class="intro"><p>2026-10-11 · 实际查询002 · 复盘用</p><h1>同一个目标姿态，排序发生了什么变化</h1><p>三栏使用同一批49条原有记录（其中1条全空），便于观察算法差异。这里没有重新训练模型，也没有人为选出“正确答案”。</p><p class="note">分数不是准确率。先观察结果是否更符合你的需要，再决定辅助参数；不能凭这一页宣布整体效果提高。</p></div>
<div class="query"><div style="width:280px;max-width:100%;flex-shrink:0;background:#f3f5f8;border-radius:12px;padding:12px">QUERY_DIAGRAM<p class="note" style="font-size:12px">留存点位示意 · 紫：头颈，蓝：躯干<br>橙：前腿，绿：后腿，棕：尾巴初始方向</p></div><div><h2>查询姿态（按留存点位重画）</h2><p><strong>查询002的图片是纯色底图，原姿态无法看图复核。</strong>这里只能比较留存方向在各算法下的排序，不是恢复了原图。</p><p>方向是主要依据，左右翻转默认关闭。新格式复用已有点计算少量相对位置。历史资料没有视角标签，本页的视角比较为0项。</p><p class="note">所有候选展示原图；启用翻转时，对应结果明确标记“需要左右翻转”。</p></div></div>
<div class="columns"><section><h2>① 修复前的方向算法</h2><p>旧实现忽略腿组权重，部分腿配对受编号影响。</p>BEFORE</section><section><h2>② 修复后的方向算法</h2><p>相同查询、相同样本及参数，修正权重与配对。</p>FIXED</section><section><h2>③ 新格式与辅助位置</h2><p>方向为主，视角最多扣0.10、位置最多扣0.05；这是待评估的初始参数。</p><button id="mirror" aria-pressed="false" type="button">左右翻转：关闭</button><div id="strict">CONTEXT</div><div id="flipped" class="hidden">FLIPPED</div></section></div>
<div class="intro"><h2>尚未验证的部分</h2><p>这不是独立盲测，也不是新模型成绩。公主形态和工程完整角色的处理目前通过合成用例验证；尚未取得经核对的真实 FLA 方向标签。旧查询001的原图缺失，因此未用于此画面对照。</p></div></main>
<script>const toggle=document.getElementById('mirror');toggle.addEventListener('click',()=>{const on=toggle.getAttribute('aria-pressed')!=='true';toggle.setAttribute('aria-pressed',String(on));toggle.textContent='左右翻转：'+(on?'开启':'关闭');document.getElementById('strict').classList.toggle('hidden',on);document.getElementById('flipped').classList.toggle('hidden',!on)});</script></html>'''
    for key, value in {"QUERY_DIAGRAM": query_diagram(query), "BEFORE": cards(a),
                       "FIXED": cards(b), "CONTEXT": cards(c, True), "FLIPPED": cards(d, True)}.items():
        page = page.replace(key, value)
    (OUT / "review.html").write_text(page, encoding="utf-8")
    print(f"Wrote {OUT / 'review.html'} ({len(page.encode()):,} bytes)")


if __name__ == "__main__":
    main()
