from __future__ import annotations

import base64
import html
import json
import shutil
import subprocess
from pathlib import Path

from app.config import settings


TYPE_NAMES = {
    "pause": "停顿",
    "phrase_boundary": "边界",
    "prominence": "重音",
    "rhythm": "节奏",
    "intonation": "语调",
    "weak_form": "弱读",
    "linking": "连读",
    "unreleased_stop": "失爆",
}


def _timestamp(seconds: float, separator: str = ",") -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def annotations_by_word(result: dict, use_end: bool = False) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = {}
    for annotation in result["annotations"]:
        key = annotation["end_word"] if use_end else annotation["start_word"]
        grouped.setdefault(key, []).append(annotation)
    return grouped


def render_marked_text(result: dict) -> str:
    grouped = annotations_by_word(result)
    ended = annotations_by_word(result, use_end=True)
    pieces: list[str] = []
    for word in result["words"]:
        index = word["index"]
        annotations = grouped.get(index, [])
        token = word["text"]
        if any(item["type"] == "prominence" for item in annotations):
            token = token.upper()
        weak = next((item for item in annotations if item["type"] == "weak_form"), None)
        if weak:
            token += f" {weak['symbol']}"
        stop = next((item for item in annotations if item["type"] == "unreleased_stop"), None)
        if stop:
            token += f"({stop['symbol']})"
        token += word.get("punctuation_after", "")
        pieces.append(token)
        linking = next((item for item in annotations if item["type"] == "linking"), None)
        if linking:
            pieces.append("‿")
        ending_annotations = ended.get(index, [])
        intonation = next((item for item in ending_annotations if item["type"] == "intonation"), None)
        if intonation:
            pieces.append(f" {intonation['symbol']} ")
        pause = next((item for item in ending_annotations if item["type"] in {"pause", "phrase_boundary"}), None)
        if pause:
            pieces.append(f" {pause['symbol']} ")
        elif not linking:
            pieces.append(" ")
    return "".join(pieces).strip()


def render_markdown(result: dict) -> str:
    audio = result.get("audio")
    lines = [
        "# 英语语流分析稿",
        "",
        f"- 输入：{audio['original_name'] if audio else '英文文稿（标准朗读建议）'}",
        f"- 时长：{audio['duration'] if audio else result['summary'].get('duration_seconds', '—')} 秒（{'音频' if audio else '建议朗读时长'}）",
        f"- 数据来源：{'音频声学分析' if audio else '标准发音词典与朗读规则'}",
        "",
        "## 语流标注文稿",
        "",
        render_marked_text(result),
        "",
        "## 意群与节奏",
        "",
    ]
    for phrase in result["phrases"]:
        lines.append(f"- {phrase['text']} {phrase['intonation_symbol']}  `{phrase['rhythm_pattern']}`")
    lines.extend(["", "## 标注详情", ""])
    for annotation in result["annotations"]:
        if annotation["type"] == "rhythm":
            continue
        start = result["words"][annotation["start_word"]]["text"]
        end = result["words"][annotation["end_word"]]["text"]
        span = start if start == end else f"{start} … {end}"
        lines.append(
            f"- **{TYPE_NAMES.get(annotation['type'], annotation['type'])}**：{span} — "
            f"{annotation['label']}（{round(annotation['confidence'] * 100)}%）"
        )
    lines.extend(["", "> 弱读、连读和失爆为1.0实验性候选，请结合原音复核。", ""])
    return "\n".join(lines)


def render_srt(result: dict) -> str:
    blocks: list[str] = []
    for index, phrase in enumerate(result["phrases"], start=1):
        blocks.append(
            f"{index}\n{_timestamp(phrase['start'])} --> {_timestamp(phrase['end'])}\n"
            f"{phrase['text']} {phrase['intonation_symbol']}"
        )
    return "\n\n".join(blocks) + "\n"


def render_print_html(result: dict) -> str:
    starts = annotations_by_word(result)
    ends = annotations_by_word(result, use_end=True)
    marked_words: list[str] = []
    for word in result["words"]:
        index = word["index"]
        annotations = starts.get(index, [])
        classes = "token stress" if any(item["type"] == "prominence" for item in annotations) else "token"
        marked_words.append(
            f'<span class="{classes}">{html.escape(word["text"] + word.get("punctuation_after", ""))}</span>'
        )
        weak = next((item for item in annotations if item["type"] == "weak_form"), None)
        if weak:
            marked_words.append(f'<span class="weak">{html.escape(weak["symbol"])}</span>')
        stop = next((item for item in annotations if item["type"] == "unreleased_stop"), None)
        if stop:
            marked_words.append(f'<sup class="stop">{html.escape(stop["symbol"])}</sup>')
        linking = next((item for item in annotations if item["type"] == "linking"), None)
        marked_words.append('<span class="link">‿</span>' if linking else " ")
        ending_annotations = ends.get(index, [])
        tone = next((item for item in ending_annotations if item["type"] == "intonation"), None)
        if tone:
            marked_words.append(f'<span class="tone">{html.escape(tone["symbol"])}</span>')
        pause = next(
            (item for item in ending_annotations if item["type"] in {"pause", "phrase_boundary"}), None
        )
        if pause:
            marked_words.append(f'<span class="pause">{html.escape(pause["symbol"])}</span> ')

    phrase_markup: list[str] = []
    for phrase in result["phrases"]:
        beats = phrase.get("rhythm_pattern", "").split()
        beat_offset = 0
        cells: list[str] = []
        for word in result["words"][phrase["start_word"] : phrase["end_word"] + 1]:
            syllables = max(1, int(word.get("syllables", 1)))
            word_beats = beats[beat_offset : beat_offset + syllables]
            beat_offset += syllables
            word_beats += ["·"] * (syllables - len(word_beats))
            beat_markup = "".join(
                f'<i class="{"strong" if beat == "●" else "weak-beat"}">{html.escape(beat)}</i>'
                for beat in word_beats
            )
            cells.append(
                '<span class="rhythm-cell">'
                f'<b>{html.escape(word["text"] + word.get("punctuation_after", ""))}</b>'
                f'<span class="beats">{beat_markup}</span></span>'
            )
        phrase_markup.append(
            '<section class="phrase">'
            f'<span class="phrase-number">{phrase["index"] + 1:02d}</span>'
            f'<div class="rhythm-grid">{"".join(cells)}</div>'
            f'<span class="phrase-tone">{html.escape(phrase["intonation_symbol"])}</span>'
            '</section>'
        )

    detail_rows: list[str] = []
    for annotation in result["annotations"]:
        if annotation["type"] in {"rhythm", "phrase_boundary"}:
            continue
        start_word = result["words"][annotation["start_word"]]["text"]
        end_word = result["words"][annotation["end_word"]]["text"]
        span = start_word if start_word == end_word else f"{start_word} … {end_word}"
        detail_rows.append(
            "<tr>"
            f'<td>{html.escape(TYPE_NAMES.get(annotation["type"], annotation["type"]))}</td>'
            f'<td>{html.escape(span)}</td>'
            f'<td>{html.escape(annotation["symbol"])}</td>'
            f'<td>{html.escape(annotation["label"])}</td>'
            f'<td>{round(annotation["confidence"] * 100)}%</td>'
            "</tr>"
        )

    summary = result.get("summary", {})
    audio = result.get("audio") or {}
    source = audio.get("original_name", "英文文稿（标准朗读建议）")
    duration = audio.get("duration", summary.get("duration_seconds", "—"))
    notes = "".join(f"<li>{html.escape(note)}</li>" for note in result.get("limitations", []))
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>英语语流标注稿</title>
<style>
@page{{size:A4;margin:14mm 13mm 16mm}}
*{{box-sizing:border-box}}body{{font-family:Arial,"Microsoft YaHei",sans-serif;color:#17202a;font-size:10.5pt;line-height:1.5;margin:0;-webkit-print-color-adjust:exact;print-color-adjust:exact}}
h1{{font:700 24pt Georgia,serif;margin:0 0 2mm}}h2{{font:700 15pt Georgia,"Microsoft YaHei",serif;margin:8mm 0 3mm;border-bottom:1px solid #d8d2c7;padding-bottom:1.5mm}}p{{margin:0}}
.meta{{color:#667085;margin-bottom:5mm}}.meta span{{margin-right:5mm}}.legend{{display:flex;gap:4mm;flex-wrap:wrap;background:#f3efe6;border-radius:3mm;padding:2.5mm 3mm;margin-bottom:4mm;font-size:9pt}}
.legend b{{color:#c8472c}}.annotated{{font:400 17pt Georgia,serif;line-height:2.05;border:1px solid #ded8cc;border-radius:4mm;padding:5mm;background:#fffdf8}}
.token{{white-space:nowrap}}.stress{{font-weight:800;color:#c8472c}}.weak{{font:9pt Arial,sans-serif;color:#65758b;margin-left:1mm}}.stop{{color:#8a5b38;font:8pt Arial,sans-serif}}.link{{color:#247ba0;font-weight:800;margin:0 .5mm}}.tone{{color:#d34d36;font-weight:800;margin-left:1mm}}.pause{{color:#725199;font-weight:800;margin-left:.5mm}}
.phrase{{display:grid;grid-template-columns:8mm 1fr 8mm;gap:2mm;align-items:start;padding:3mm 0;border-bottom:1px solid #ece7de;break-inside:avoid}}.phrase-number{{color:#8a8174;font:700 8pt Arial;padding-top:1.5mm}}.rhythm-grid{{display:flex;flex-wrap:wrap;gap:3mm 4mm;align-items:start}}.rhythm-cell{{display:inline-grid;grid-template-rows:auto auto;justify-items:center;min-width:max-content;break-inside:avoid}}.rhythm-cell b{{font:400 11.5pt Georgia,serif}}.beats{{display:flex;justify-content:space-evenly;width:100%;min-height:4mm}}.beats i{{font-style:normal;font-size:8pt;color:#9aa1aa}}.beats i.strong{{font-size:9pt;color:#65717c}}.phrase-tone{{font:700 15pt Georgia;color:#d34d36}}
table{{width:100%;border-collapse:collapse;font-size:8.5pt}}thead{{display:table-header-group}}th{{background:#eee9df;text-align:left}}th,td{{padding:1.7mm;border-bottom:1px solid #e3ded4;vertical-align:top}}tr{{break-inside:avoid}}.notes{{color:#5f6875;padding-left:5mm;font-size:8.5pt}}.footer-note{{margin-top:5mm;color:#7a746a;font-size:8pt}}
</style></head><body>
<h1>英语语流标注稿</h1>
<p class="meta"><span>来源：{html.escape(str(source))}</span><span>时长：{html.escape(str(duration))} 秒</span><span>单词：{summary.get("word_count", len(result["words"]))}</span><span>意群：{summary.get("phrase_count", len(result["phrases"]))}</span></p>
<div class="legend"><span><b>加粗红色</b> 重音</span><span>‿ 连读</span><span>/tə/ 弱读</span><span>t̚ 失爆</span><span>↗ ↘ 语调</span><span>/ // 停顿</span></div>
<h2>语流标注文稿</h2><div class="annotated">{"".join(marked_words)}</div>
<h2>意群与强弱节奏</h2>{"".join(phrase_markup)}
<h2>标注详情</h2><table><thead><tr><th>类型</th><th>范围</th><th>符号</th><th>说明</th><th>置信度</th></tr></thead><tbody>{"".join(detail_rows)}</tbody></table>
<h2>说明</h2><ul class="notes">{notes}</ul><p class="footer-note">Speech Flow Annotator 1.0 · PDF 为静态学习稿，不包含可播放音频。</p>
</body></html>"""


def _browser_executable() -> Path | None:
    candidates = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    discovered = (
        shutil.which("msedge")
        or shutil.which("chrome")
        or shutil.which("google-chrome")
        or shutil.which("chromium")
        or shutil.which("chromium-browser")
    )
    return Path(discovered) if discovered else None


def render_pdf(result: dict, output_path: Path) -> Path:
    browser = _browser_executable()
    if browser is None:
        raise RuntimeError("未找到 Microsoft Edge 或 Google Chrome，无法生成 PDF。")
    html_path = output_path.with_suffix(".print.html")
    html_path.write_text(render_print_html(result), encoding="utf-8")
    profile_dir = output_path.parent / ".pdf-browser-profile"
    command = [
        str(browser),
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        "--run-all-compositor-stages-before-draw",
        f"--user-data-dir={profile_dir}",
        f"--print-to-pdf={output_path}",
        html_path.resolve().as_uri(),
    ]
    if settings.chrome_no_sandbox:
        command.insert(1, "--no-sandbox")
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=90)
    if completed.returncode != 0 or not output_path.exists() or output_path.stat().st_size < 1000:
        detail = completed.stderr.strip() or completed.stdout.strip() or "浏览器打印没有生成文件。"
        raise RuntimeError(f"PDF 生成失败：{detail}")
    return output_path


def render_standalone_html(result: dict, audio_path: Path | None) -> str:
    audio_data = base64.b64encode(audio_path.read_bytes()).decode("ascii") if audio_path else ""
    result_json = json.dumps(result, ensure_ascii=False).replace("</", "<\\/")
    audio_info = result.get("audio")
    title = html.escape(audio_info["original_name"] if audio_info else "标准英语朗读稿")
    audio_markup = f'<audio id="audio" controls src="data:audio/wav;base64,{audio_data}"></audio>' if audio_path else '<p class="note">文本推导模式 · 无音频</p>'
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{title} · 英语语流分析</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:980px;margin:40px auto;padding:0 24px;background:#f5f2ea;color:#17202a}}
h1{{font-size:28px}} audio{{width:100%}} #text{{font-size:21px;line-height:1.85;background:white;padding:28px;border-radius:18px}}
.word{{cursor:pointer;border-radius:5px;padding:2px}} .word:hover{{background:#ffe8a3}} .stress{{font-weight:800;color:#c8472c}}
.weak{{color:#718096;font-size:.86em}} .link{{color:#247ba0;font-weight:800}} .pause{{color:#7a4fa3;font-weight:800}}
.note{{color:#667085}} table{{border-collapse:collapse;width:100%}} td,th{{padding:8px;border-bottom:1px solid #ddd;text-align:left}}
</style></head><body><h1>英语语流分析稿</h1><p class="note">{title}</p>
{audio_markup}<div id="text"></div>
<h2>意群与节奏</h2><div id="phrases"></div><p class="note">弱读、连读和失爆为1.0实验性候选，请结合原音复核。</p>
<script>const R={result_json}; const A=document.querySelector('#audio'); const grouped={{}};
R.annotations.forEach(x=>(grouped[x.start_word]??=[]).push(x)); const root=document.querySelector('#text');
R.words.forEach((w,i)=>{{const a=grouped[i]||[];const span=document.createElement('span');span.className='word '+(a.some(x=>x.type==='prominence')?'stress':'');span.textContent=w.text+w.punctuation_after;if(A)span.onclick=()=>{{A.currentTime=w.start;A.play()}};root.append(span);
const weak=a.find(x=>x.type==='weak_form');if(weak)root.insertAdjacentHTML('beforeend',` <span class="weak">${{weak.symbol}}</span>`);
const link=a.find(x=>x.type==='linking');if(link)root.insertAdjacentHTML('beforeend','<span class="link">‿</span>');else root.append(' ');
const tone=a.find(x=>x.type==='intonation');if(tone)root.insertAdjacentHTML('beforeend',` <span class="pause">${{tone.symbol}}</span> `);
const pause=a.find(x=>x.type==='pause'||x.type==='phrase_boundary');if(pause)root.insertAdjacentHTML('beforeend',` <span class="pause">${{pause.symbol}}</span> `);}});
document.querySelector('#phrases').innerHTML=R.phrases.map(p=>`<p><b>${{p.text}} ${{p.intonation_symbol}}</b><br><code>${{p.rhythm_pattern}}</code></p>`).join('');</script></body></html>"""
