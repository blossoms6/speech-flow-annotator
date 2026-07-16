const state = { jobId: null, result: null, selectedWord: null, selectedRange: null, loop: false, transcriptionAvailable: false, uploadFile: null, inputMode: "audio" };
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);
}
function formatTime(seconds) {
  const minutes = Math.floor(seconds / 60); const rest = (seconds % 60).toFixed(2).padStart(5, "0"); return `${minutes}:${rest}`;
}
function annotationName(type) {
  return ({pause:"停顿",phrase_boundary:"边界",prominence:"重音",rhythm:"节奏",intonation:"语调",weak_form:"弱读",linking:"连读",unreleased_stop:"失爆"})[type] || type;
}

async function checkHealth() {
  try {
    const response = await fetch("/api/health"); const data = await response.json();
    state.transcriptionAvailable = data.transcription_available;
    const status = $("#engineStatus");
    status.textContent = data.transcription_available ? `转写引擎就绪 · ${data.default_model}` : "基础分析就绪 · 自动转写未安装";
    status.classList.add("ready");
    if (data.transcription_available) $("#autoTranscribe").checked = true;
  } catch { $("#engineStatus").textContent = "无法连接本地分析服务"; }
}

function setFile(file) {
  if (!file) return;
  state.uploadFile = file;
  $("#fileLabel").textContent = file.name;
  $("#fileMeta").textContent = `${(file.size / 1024 / 1024).toFixed(1)} MB · 已准备分析`;
  $("#dropZone").classList.add("has-file");
}

function setInputMode(mode) {
  state.inputMode = mode;
  $$(".mode-button").forEach(button => button.classList.toggle("active", button.dataset.mode === mode));
  $("#uploadCard").classList.toggle("text-mode", mode === "text");
  $("#uploadCard .step-title h2").textContent = mode === "text" ? "准备英文文稿" : "准备音频";
  $("#uploadCard .step-title p").textContent = mode === "text" ? "不需要音频，生成标准朗读建议与合成参考音" : "支持 MP3、WAV、M4A、FLAC、MP4 和 WebM";
  $("#transcriptLabel").innerHTML = mode === "text" ? "英文文稿 <span>必填 · 可输入句子、段落或短文</span>" : "英文原文 <span>可选，但提供后更容易校正</span>";
  $("#transcript").placeholder = mode === "text" ? "Paste the English passage to generate a standard reading guide…" : "Paste the English transcript here…";
  $("#analyzeButtonLabel").textContent = mode === "text" ? "生成朗读稿＋参考音频" : "开始分析";
}

async function submitJob() {
  const file = state.uploadFile || $("#audioFile").files[0]; const transcript = $("#transcript").value.trim(); const auto = $("#autoTranscribe").checked;
  const error = $("#formError"); error.hidden = true;
  if (state.inputMode === "text" && !transcript) { error.textContent = "请输入需要生成标准朗读稿的英文文稿。"; error.hidden = false; return; }
  if (state.inputMode === "audio" && !file) { error.textContent = "请先选择英文音频。"; error.hidden = false; return; }
  if (state.inputMode === "audio" && !transcript && !auto) { error.textContent = "请粘贴英文原文，或开启自动转写。"; error.hidden = false; return; }
  if (state.inputMode === "audio" && auto && !state.transcriptionAvailable) { error.textContent = "自动转写组件未安装。请运行 install-transcription.ps1，或者关闭自动转写并提供原文。"; error.hidden = false; return; }
  const form = new FormData(); if (file && state.inputMode === "audio") form.append("audio", file); form.append("transcript", transcript); form.append("input_mode", state.inputMode); form.append("auto_transcribe", state.inputMode === "audio" && auto); form.append("model_name", $("#modelName").value); form.append("accent", $("#accent").value); form.append("tts_engine", $("#ttsEngine").value); form.append("device", "auto");
  $("#analyzeButton").disabled = true; $("#progressCard").hidden = false; $("#resultSection").hidden = true; $("#progressCard").scrollIntoView({behavior:"smooth", block:"center"});
  try {
    const response = await fetch("/api/jobs", {method:"POST", body:form}); const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "提交失败"); state.jobId = data.id; await pollJob();
  } catch (reason) { showFailure(reason.message); }
}

async function pollJob() {
  while (true) {
    const response = await fetch(`/api/jobs/${state.jobId}`); const job = await response.json();
    $("#progressStage").textContent = job.stage === "loading_model" ? "正在加载转写模型" : job.stage === "transcribing" ? "正在转写音频" : job.stage === "text_planning" ? "正在规划标准朗读" : job.stage === "synthesizing" ? "正在生成参考音频" : job.stage === "annotation" ? "正在生成语流标注" : job.stage === "rendering" ? "正在整理结果" : state.inputMode === "text" ? "正在生成朗读稿" : "正在分析音频";
    $("#progressMessage").textContent = job.message; $("#progressBar").style.width = `${job.progress}%`; $("#progressPercent").textContent = `${job.progress}%`;
    if (job.status === "failed") { showFailure(job.error || "分析失败"); return; }
    if (job.status === "completed") { await loadResult(); return; }
    await new Promise(resolve => setTimeout(resolve, 900));
  }
}

function showFailure(message) {
  $("#progressCard").hidden = true; $("#analyzeButton").disabled = false; $("#formError").textContent = message; $("#formError").hidden = false; $("#uploadCard").scrollIntoView({behavior:"smooth"});
}

async function loadResult() {
  const response = await fetch(`/api/jobs/${state.jobId}/result`); state.result = await response.json();
  if (new URLSearchParams(location.search).get("job") !== state.jobId) {
    history.replaceState(null, "", `/?job=${state.jobId}`);
  }
  const textMode = state.result.input_mode === "text" || state.result.transcript_source === "text-standard";
  const hasAudio = Boolean(state.result.audio);
  state.inputMode = textMode ? "text" : "audio";
  setInputMode(state.inputMode);
  $("#progressCard").hidden = true; $("#analyzeButton").disabled = false; $("#resultSection").hidden = false;
  $("#playerCard").hidden = !hasAudio;
  if (hasAudio) {
    $("#audioPlayer").src = `/api/jobs/${state.jobId}/audio`; $("#audioName").textContent = state.result.audio.original_name;
    const speechKind = state.result.summary.speech_online ? "在线神经参考音" : "本地基础参考音";
    $("#audioStats").textContent = textMode ? `${formatTime(state.result.audio.duration)} · ${state.result.summary.word_count} 词 · ${speechKind}` : `${formatTime(state.result.audio.duration)} · ${state.result.summary.word_count} 词 · 对齐质量 ${Math.round(state.result.alignment_quality*100)}%`;
    const badge = $("#qualityBadge"); badge.textContent = textMode ? (state.result.summary.speech_online ? "自然参考音" : "本地参考音") : (({good:"音质良好",fair:"音质一般",poor:"音质较差"})[state.result.audio.quality] || state.result.audio.quality);
  }
  $("#correctionHint").textContent = textMode ? "修改后会重新生成朗读建议和参考音频" : "修改后重新分析；关闭自动转写时会使用能量估计时间轴";
  $("#summaryHeading").textContent = textMode ? "生成摘要" : "检测摘要";
  $("#emptyDetail p").textContent = textMode ? (state.result.summary.speech_online ? "点击文稿中的单词，播放神经语音返回的对应片段，并查看标准发音、词重音、弱读与连读建议。" : "点击文稿中的单词，播放估算片段并查看标准发音、词重音、弱读与连读建议。") : "点击文稿中的单词，查看时间、声学特征、语流判断与置信度。";
  $("#correctedTranscript").value = state.result.transcript; setupExportLinks(); renderTranscript(); renderPhrases(); renderSummary(); renderLimitations(); if (hasAudio) drawContours();
  $("#resultSection").scrollIntoView({behavior:"smooth",block:"start"});
}

function annotationMaps() {
  const starts = {}, ends = {}, covering = {};
  state.result.annotations.forEach(item => {
    (starts[item.start_word] ??= []).push(item); (ends[item.end_word] ??= []).push(item);
    for (let i=item.start_word; i<=item.end_word; i++) (covering[i] ??= []).push(item);
  }); return {starts, ends, covering};
}

function renderTranscript() {
  const {starts, ends} = annotationMaps(); const root = $("#annotatedTranscript"); root.innerHTML = "";
  const phraseEnds = new Set(state.result.phrases.map(p => p.end_word));
  state.result.words.forEach((word, index) => {
    const startAnnotations = starts[index] || []; const endAnnotations = ends[index] || [];
    const button = document.createElement("button"); button.className = "word"; button.dataset.index = index;
    if (startAnnotations.some(item => item.type === "prominence")) button.classList.add("stress");
    button.textContent = word.text + word.punctuation_after; button.title = `${formatTime(word.start)}–${formatTime(word.end)}`; button.onclick = () => selectWord(index); root.append(button);
    const weak = startAnnotations.find(item => item.type === "weak_form"); if (weak) root.insertAdjacentHTML("beforeend", `<span class="weak-mark ${weak.confidence<.6?'confidence-low':''}">${escapeHtml(weak.symbol)}</span>`);
    const stop = startAnnotations.find(item => item.type === "unreleased_stop"); if (stop) root.insertAdjacentHTML("beforeend", `<sup class="stop-mark ${stop.confidence<.6?'confidence-low':''}">${escapeHtml(stop.symbol)}</sup>`);
    const link = startAnnotations.find(item => item.type === "linking"); if (link) root.insertAdjacentHTML("beforeend", `<span class="link-mark ${link.confidence<.6?'confidence-low':''}">‿</span>`); else root.append(" ");
    const tone = endAnnotations.find(item => item.type === "intonation"); if (tone) root.insertAdjacentHTML("beforeend", `<span class="tone-mark">${escapeHtml(tone.symbol)}</span>`);
    const pause = endAnnotations.find(item => item.type === "pause" || item.type === "phrase_boundary"); if (pause) root.insertAdjacentHTML("beforeend", `<span class="pause-mark">${escapeHtml(pause.symbol)}</span>`);
    if (phraseEnds.has(index)) root.append(document.createElement("br"));
  });
}

function selectWord(index) {
  state.selectedWord = index; $$(".word").forEach(item => item.classList.toggle("selected", Number(item.dataset.index)===index));
  const word = state.result.words[index]; const hasAudio = Boolean(state.result.audio);
  state.selectedRange = hasAudio ? {start:Math.max(0,word.start-.08), end:Math.min(state.result.audio.duration,word.end+.16)} : null;
  if (hasAudio) $("#selectionLabel").textContent = `${word.text} · ${formatTime(word.start)}–${formatTime(word.end)}`; renderWordDetail(index);
  if (!hasAudio) return;
  const audio = $("#audioPlayer");
  try {
    audio.currentTime = state.selectedRange.start;
    const playAttempt = audio.play();
    if (playAttempt) playAttempt.catch(() => {});
  } catch { /* Word inspection remains available while media metadata loads. */ }
}

function renderWordDetail(index) {
  const word = state.result.words[index]; const {covering} = annotationMaps(); const annotations = (covering[index]||[]).filter(item=>item.type!=="rhythm"&&item.type!=="phrase_boundary");
  $("#emptyDetail").hidden = true; const root = $("#wordDetail"); root.hidden = false;
  const hasAudio = Boolean(state.result.audio);
  const standardMode = state.result.input_mode === "text" || state.result.transcript_source === "text-standard";
  const metrics = !standardMode && hasAudio ? [{label:"时长",value:`${Math.round((word.end-word.start)*1000)} ms`},{label:"音高峰值",value:word.acoustic.f0_peak?`${word.acoustic.f0_peak} Hz`:"—"},{label:"平均音量",value:word.acoustic.intensity_mean?`${word.acoustic.intensity_mean} dB`:"—"},{label:"对齐置信度",value:`${Math.round(word.confidence*100)}%`}] : [{label:"音节数",value:word.syllables},{label:"词重音",value:(word.lexical_stress||[]).map(x=>x?"●":"·").join(" ")||"—"},{label:"CMU 发音",value:word.pronunciation||"词典未收录"},{label:"规则置信度",value:`${Math.round(word.confidence*100)}%`}];
  const actions = hasAudio ? `<div class="detail-actions"><button id="playWord">▶ 单词</button><button id="playContext">▶ 前后语境</button></div>` : "";
  root.innerHTML = `<div class="detail-word">${escapeHtml(word.text)}</div><div class="detail-time">${hasAudio?`${formatTime(word.start)}–${formatTime(word.end)}`:"标准朗读规划"} · ${escapeHtml(word.alignment_method)}</div>${actions}<div class="metrics">${metrics.map(x=>`<div class="metric"><b>${escapeHtml(x.value)}</b><span>${x.label}</span></div>`).join("")}</div><div>${annotations.length?annotations.map(item=>`<article class="detail-annotation"><header><b>${annotationName(item.type)} · ${escapeHtml(item.symbol)}</b><b>${Math.round(item.confidence*100)}%</b></header><small>${escapeHtml(item.label)}${item.experimental?' · 实验性候选':''}</small><div class="confidence-bar"><i style="width:${item.confidence*100}%"></i></div></article>`).join(""):'<p class="quality-note">该词没有额外的标准语流标注。</p>'}</div>`;
  if (hasAudio) { $("#playWord").onclick=()=>selectWord(index); $("#playContext").onclick=()=>{ const audio=$("#audioPlayer"); state.selectedRange={start:Math.max(0,word.start-1),end:Math.min(state.result.audio.duration,word.end+1)};try{audio.currentTime=state.selectedRange.start;const playAttempt=audio.play();if(playAttempt)playAttempt.catch(()=>{});}catch{} }; }
}

function renderPhrases() {
  $("#phraseList").innerHTML = state.result.phrases.map(phrase => {
    const beats = (phrase.rhythm_pattern || "").trim().split(/\s+/).filter(Boolean);
    let beatOffset = 0;
    const wordCells = state.result.words.slice(phrase.start_word, phrase.end_word + 1).map(word => {
      const wordBeats = beats.slice(beatOffset, beatOffset + Math.max(1, word.syllables));
      beatOffset += Math.max(1, word.syllables);
      while (wordBeats.length < Math.max(1, word.syllables)) wordBeats.push("·");
      const beatMarkup = wordBeats.map(beat => `<span class="rhythm-beat ${beat === "●" ? "strong" : "weak"}">${escapeHtml(beat)}</span>`).join("");
      return `<button class="rhythm-cell" data-rhythm-index="${word.index}" title="点击播放 ${escapeHtml(word.text)}"><span class="rhythm-word">${escapeHtml(word.text + word.punctuation_after)}</span><span class="rhythm-beats">${beatMarkup}</span></button>`;
    }).join("");
    return `<div class="phrase-item"><span class="phrase-number">${String(phrase.index + 1).padStart(2, "0")}</span><div class="phrase-rhythm-grid">${wordCells}</div><span class="phrase-tone" title="${escapeHtml(phrase.intonation)}">${escapeHtml(phrase.intonation_symbol)}</span></div>`;
  }).join("");
  $$(".rhythm-cell").forEach(cell => {
    cell.onclick = () => selectWord(Number(cell.dataset.rhythmIndex));
  });
  const rhythm=state.result.summary.rhythm; $("#rhythmSummary").textContent=`${rhythm.syllables_per_second} 音节/秒${rhythm.mean_stress_interval?` · 重音间隔 ${rhythm.mean_stress_interval}s`:''}`;
}

function renderSummary() {
  const counts=state.result.summary.counts||{}; const stats=[[state.result.summary.word_count,"单词"],[state.result.summary.phrase_count,"意群"],[counts.prominence||0,"重音"],[counts.weak_form||0,"弱读候选"],[counts.linking||0,"连读候选"],[counts.unreleased_stop||0,"失爆候选"],[counts.pause||0,"停顿"],[state.result.summary.rhythm.syllables_per_second,"音节/秒"]];
  $("#summaryGrid").className="summary-grid"; $("#summaryGrid").innerHTML=stats.map(([value,label])=>`<div class="summary-stat"><b>${value}</b><span>${label}</span></div>`).join("");
}
function renderLimitations() { const notes=[...(state.result.audio?.warnings||[]),...state.result.limitations]; $("#limitations").innerHTML=notes.map(note=>`<div class="quality-note">${escapeHtml(note)}</div>`).join(""); }
function setupExportLinks() { $$('[data-export]').forEach(link=>{link.href=`/api/jobs/${state.jobId}/export/${link.dataset.export}`;link.setAttribute('download','');}); }

function drawContours() {
  if (!state.result.audio || !state.result.contours.times.length) return;
  const canvas=$("#contourCanvas"), ratio=window.devicePixelRatio||1, rect=canvas.getBoundingClientRect(); canvas.width=rect.width*ratio;canvas.height=190*ratio;const ctx=canvas.getContext("2d");ctx.scale(ratio,ratio);const width=rect.width,height=190;ctx.clearRect(0,0,width,height);ctx.strokeStyle="#e5dfd3";ctx.lineWidth=1;for(let y=30;y<180;y+=40){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(width,y);ctx.stroke();}
  const {times,f0_hz,intensity_db}=state.result.contours,duration=state.result.audio.duration;const voiced=f0_hz.filter(x=>x>0),minF=voiced.length?Math.min(...voiced):70,maxF=voiced.length?Math.max(...voiced):300,minI=Math.min(...intensity_db),maxI=Math.max(...intensity_db);
  function plot(values,color,map,skipZero=false){ctx.beginPath();ctx.strokeStyle=color;ctx.lineWidth=1.7;let drawing=false;values.forEach((v,i)=>{if(skipZero&&v<=0){drawing=false;return;}const x=times[i]/duration*width,y=map(v);if(!drawing){ctx.moveTo(x,y);drawing=true}else ctx.lineTo(x,y)});ctx.stroke();}
  plot(intensity_db,"#246f8e",v=>165-(v-minI)/Math.max(1,maxI-minI)*65); plot(f0_hz,"#d65235",v=>88-(v-minF)/Math.max(1,maxF-minF)*65,true);
}

async function reanalyze() {
  const transcript=$("#correctedTranscript").value.trim();if(!transcript)return;$("#resultSection").hidden=true;$("#progressCard").hidden=false;$("#progressBar").style.width="0%";
  const response=await fetch(`/api/jobs/${state.jobId}/reanalyze`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({transcript,accent:$("#accent").value})});if(!response.ok){const data=await response.json();showFailure(data.detail||"重新分析失败");return;}await pollJob();
}

$("#dropZone").onclick=()=>$("#audioFile").click(); $("#dropZone").onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();$("#audioFile").click();}}; $("#audioFile").onchange=event=>setFile(event.target.files[0]);
['dragenter','dragover'].forEach(name=>$("#dropZone").addEventListener(name,event=>{event.preventDefault();$("#dropZone").classList.add('dragover')})); ['dragleave','drop'].forEach(name=>$("#dropZone").addEventListener(name,event=>{event.preventDefault();$("#dropZone").classList.remove('dragover')})); $("#dropZone").addEventListener('drop',event=>setFile(event.dataTransfer.files[0]));
$("#analyzeButton").onclick=submitJob; $("#reanalyzeButton").onclick=reanalyze; $("#playbackRate").onchange=event=>$("#audioPlayer").playbackRate=Number(event.target.value); $("#loopButton").onclick=()=>{state.loop=!state.loop;$("#loopButton").classList.toggle('active',state.loop);};
$$(".mode-button").forEach(button => button.onclick = () => setInputMode(button.dataset.mode));
$("#audioPlayer").addEventListener('timeupdate',event=>{if(state.loop&&state.selectedRange&&event.target.currentTime>=state.selectedRange.end)event.target.currentTime=state.selectedRange.start;});
$$('[data-feature]').forEach(input=>input.onchange=()=>document.body.classList.toggle(`hide-${input.dataset.feature}`,!input.checked)); window.addEventListener('resize',()=>{if(state.result)drawContours()});

async function boot() {
  await checkHealth();
  const jobId = new URLSearchParams(location.search).get("job");
  if (jobId && /^[a-f0-9]{32}$/.test(jobId)) {
    state.jobId = jobId;
    try { await loadResult(); } catch { /* The normal upload screen remains available. */ }
  }
}
boot();
