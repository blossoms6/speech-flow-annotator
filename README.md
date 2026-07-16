# Speech Flow Annotator 1.0

一个本地运行的英语音频语流标注器。上传英文音频后，应用会生成可点击播放的文稿，并分析：

- 主要重音和次重音
- 停顿与意群
- 强弱节奏和语速
- 升调、降调与延续调
- 实验性的弱读、连读和词尾塞音失爆候选

所有判断都带置信度和声学证据。弱读、连读与失爆在 1.0 中属于实验功能，界面会明确提示用户结合原音复核。

应用同时支持“只有文稿”模式：无需上传音频，系统会根据 CMU 标准发音词典、词重音、句型和自然朗读规则生成标准英语朗读稿。默认使用 Microsoft Edge 在线神经语音生成更自然、连贯的参考音并取得逐词边界；网络不可用时自动退回 Windows 本地英语声音。文本模式的结果会明确标明声音来源，不会冒充真人原音检测。

## 快速开始

### 方式一：基础模式

基础模式不下载语音识别模型，上传音频时需要同时粘贴英文原文。

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

浏览器打开：<http://127.0.0.1:8765>

首次打开会直接以游客身份进入分析台，可以正常分析、播放和导出，不强制注册。页面右上角提供“登录 / 注册”按钮，点击后进入独立的 `/login` 页面。用户名支持英文字母、数字和下划线，长度为 3–32 位，密码长度为 8–128 位。

也可以直接运行：

```powershell
.\run.ps1
```

### 云服务器部署

项目已经提供 `Dockerfile`、`compose.yaml`、`Caddyfile` 和生产环境模板。Ubuntu 服务器的完整安装、HTTPS、管理员创建、更新与备份步骤见 [DEPLOY.md](DEPLOY.md)。2 核 2 GB 服务器建议先不安装 Whisper 自动转写，并使用默认的单任务线程和 10 分钟音频限制。

### 方式二：自动转写模式

安装本地 faster-whisper：

```powershell
.\install-transcription.ps1
```

然后运行：

```powershell
.\run.ps1
```

首次选择模型时会从 Hugging Face 下载模型。默认 `tiny.en` 体积较小；`base.en` 和 `small.en` 通常更准确，但需要更多下载时间和内存。

## 使用流程

1. 直接以游客身份使用，或选择注册、登录本机账户。
2. 上传 MP3、WAV、M4A、FLAC、MP4 或 WebM。
3. 粘贴英文原文，或者开启自动转写。
4. 点击“开始分析”。
5. 点击文稿中的任意单词播放对应片段。
6. 查看重音、弱读、连读、失爆、停顿、节奏和语调。
7. 如果文稿有误，在页面下方修改后重新分析。
8. 导出 PDF、HTML、Markdown、SRT 或 JSON。

如果只有英文文稿：

1. 选择“只有文稿”。
2. 粘贴英文句子、段落或短文。
3. 选择“自然神经音”（推荐、需联网）或“Windows 基础音”（离线）。
4. 点击“生成朗读稿＋参考音频”。
5. 播放标准参考音，或点击单词播放对应片段。
6. 查看逐词对齐的音节点、词重音、句子重音、弱读、连读、停顿和建议语调。

## 1.0 分析方法

应用首先使用 FFmpeg 把音频转换为 16 kHz 单声道 WAV，然后计算逐帧音量、语音区间和 F0 音高。自动转写开启时，faster-whisper 提供文本和逐词时间戳；只有原文时，应用根据有效语音区间估计单词时间轴。

停顿直接来自单词间隔；重音综合音高、音量、音长和功能词先验；语调依据意群末段的半音变化和斜率；节奏依据音节数和重音间隔。弱读、连读和失爆使用文本环境、韵律特征、边界能量与高频爆破指标生成保守候选。

## 输出文件

- `speech-analysis.pdf`：适合打印和分享的 A4 静态学习稿
- `speech-analysis.html`：内嵌音频的独立交互学习稿
- `speech-analysis.md`：可编辑标注文稿
- `speech-analysis.srt`：按意群划分的字幕
- `speech-analysis.json`：完整单词、声学特征、标注、证据和置信度

只有文稿时，HTML 导出也会内嵌生成的参考音频。自然神经音会把英文文稿发送至 Microsoft Edge 在线语音服务，并使用服务返回的逐词边界；离线模式依赖 Windows `System.Speech`，逐词时间按总时长估算。两种模式都不等同于音素级强制对齐。

运行数据保存在 `data/jobs/<任务ID>/`。音频分析和离线基础音不会主动上传内容；选择自然神经音时，英文文稿会发送到 Microsoft Edge 在线语音服务。自动转写模型下载是另一项可选网络行为。

## 账户与数据隔离

游客通过浏览器中的随机 `HttpOnly`、`SameSite=Strict` Cookie 获得彼此隔离的本机空间，无需在数据库中创建账户。游客可以完整使用分析、播放、重新分析和所有导出功能；之后登录或注册时，当前浏览器创建的游客任务会自动转移到该账户。

用户与登录会话保存在 `data/auth.db`（SQLite）中，密码使用 Argon2id 保存为不可逆哈希。登录会话同样使用 `HttpOnly`、`SameSite=Strict` 的随机 Cookie，数据库中保存的是会话令牌的 SHA-256 摘要而非原令牌。每个新任务都会记录创建者，任务状态、结果、音频和所有导出接口都会校验当前游客或账户身份；其他浏览器或账户访问同一任务链接时返回 404。

这是 1.0 账户系统，注册默认开放，暂不包含邮箱验证、找回密码或登录限流。不要直接把开发服务器暴露在公网。若通过 HTTPS 反向代理部署，请设置环境变量 `SFA_SECURE_COOKIES=true`，让会话 Cookie 同时启用 `Secure` 标志。可用 `SFA_AUTH_DB` 指定账户数据库路径。

升级前创建的旧任务没有账户归属，因此不会自动开放给任何新账户；文件仍保留在 `data/jobs/` 中。

## 管理员后台

项目提供独立的 `/admin` 管理后台。管理员可以查看用户、会话、任务状态、磁盘占用和服务配置；可以启停用户、授予或移除管理员权限、删除已经结束的任务，以及按保留天数清理游客任务。系统不允许管理员停用自己或移除自己的权限，并始终要求至少保留一个启用的管理员。

首次使用前，在项目根目录运行：

```powershell
.\.venv\Scripts\python.exe .\scripts\create-admin.py
```

按提示输入管理员用户名和密码。密码输入时不会显示在终端。也可以把已经注册的普通账户提升为管理员：

```powershell
.\.venv\Scripts\python.exe .\scripts\create-admin.py --username your_username
```

随后使用该账户在 `/login` 登录，分析台顶部会出现“管理后台”入口。管理员页面和 `/api/admin/*` 接口均在服务端校验管理员权限，普通账户不能通过直接输入地址访问。

## 项目结构

```text
app/
├── auth.py            # SQLite 用户、Argon2id 密码与会话管理
├── main.py            # FastAPI 接口与任务调度
├── pipeline.py        # 完整分析流程
├── audio.py           # 转换、音质和声学特征
├── transcription.py   # 转写与时间轴对齐
├── analyzers.py       # 七类语流分析器
├── tts.py             # 文稿模式的 Windows 本地参考音频
├── exports.py         # HTML/Markdown/SRT 导出
├── schemas.py         # 统一数据结构
└── store.py           # 本地任务存储
static/
├── admin.html
├── index.html
├── login.html
├── styles.css
├── admin.js
├── app.js
└── auth.js
tests/
```

生产容器使用 Linux Chromium 导出 PDF，并只提供 Edge 在线神经参考音；Windows `System.Speech` 离线声音会在 Linux 页面中自动标记为不可用。

## 测试

```powershell
python -m pip install -r requirements.txt
python -m pytest
```

测试使用程序生成的合成音频，不需要下载 Whisper 模型。

## 已知限制

- 1.0 主要针对清晰、单人英语音频。
- 关闭自动转写时的逐词时间轴是能量估计，不能用于严格音素研究。
- 1.0 尚未接入独立音素识别或 Montreal Forced Aligner，因此弱读、连读、失爆仅作为实验候选。
- 拼写规则无法完整覆盖英语方言、闪音、同化和实际音素变体。
- 强背景音乐、混响、多人重叠和低音量会显著降低可靠性。
- 账户系统暂不支持密码找回；忘记密码时需要由本机维护者重置账户数据库。
