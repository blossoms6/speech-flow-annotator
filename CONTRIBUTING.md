# 参与贡献

感谢你关注 Speech Flow Annotator。欢迎提交错误报告、功能建议和代码改进。

## 提交 Issue

请先搜索现有 Issue，避免重复。错误报告应尽量包含：

- 操作系统、Python 版本和浏览器版本
- 使用的是“音频分析”还是“只有文稿”模式
- 可复现问题的最小示例和操作步骤
- 预期结果与实际结果
- 已去除私人音频、账号信息和其他敏感内容的日志

安全漏洞不要提交到公开 Issue，请按照 [SECURITY.md](SECURITY.md) 私下报告。

## 本地开发

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8765
```

Linux 或 macOS 请将 `.\.venv\Scripts\python.exe` 替换为 `.venv/bin/python`。

## Pull Request

1. 从 `main` 创建一个范围清晰的分支。
2. 保持改动聚焦，不要提交 `.env.production`、数据库、音频、任务目录或日志。
3. 为行为变化增加或更新测试。
4. 在提交前运行 `python -m pytest`。
5. 在 PR 描述中说明改动内容、原因、用户影响和验证方法。

语流分析属于辅助学习功能。涉及算法判断时，请说明依据、置信度和已知限制，不要把启发式候选描述为确定的语音学事实。
