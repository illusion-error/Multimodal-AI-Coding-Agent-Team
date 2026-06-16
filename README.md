# Multimodal AI Coding Agent Team

多模态代码生成 Agent 项目，支持编程题文本输入、题目截图上传、阿里云百炼 API 调用、Python 代码生成、本地执行、兜底输出和项目报告下载。

## 主要文件

- `ai_coding_agent_bailian.py`：单文件可运行版项目主程序。
- `多模态代码生成Agent项目精简升级方案与分工.docx`：精简版项目升级方案、四人分工和量化验收标准。
- `多模态代码生成Agent项目升级功能文档.docx`：长版功能设计文档。

## 运行方式

```powershell
pip install streamlit
streamlit run ai_coding_agent_bailian.py
```

## 百炼 API 配置

可以在页面侧边栏直接输入 API Key，也可以提前设置环境变量：

```powershell
$env:DASHSCOPE_API_KEY="你的阿里云百炼API Key"
streamlit run ai_coding_agent_bailian.py
```

默认接口地址：

```text
https://dashscope.aliyuncs.com/compatible-mode/v1
```

默认模型：

- 文本模型：`qwen-plus`
- 视觉模型：`qwen3-vl-plus`

## 兜底机制

如果没有填写 API Key、余额不足、网络失败或模型调用异常，系统会自动生成兜底代码和报告，保证页面始终有输出，方便答辩演示。
