# Multimodal AI Coding Agent Team

多模态代码生成 Agent 项目。系统支持输入编程题文本或上传题目截图，调用阿里云百炼大模型完成题意识别、解题思路生成、Python 代码生成、本地执行测试，并输出项目报告。

当前仓库版本是基于原版 `ai_coding_agent_o3.py` 改造的百炼版，不再强制依赖 OpenAI、Gemini 和 E2B 三个 API Key。

## 功能特点

- 支持文本编程题输入。
- 支持题目截图上传，并通过百炼视觉模型识别题意。
- 使用阿里云百炼 OpenAI 兼容接口调用大模型。
- 自动生成题意理解、解题思路、复杂度分析和 Python 代码。
- 自动提取 Python 代码块并在本地执行。
- 支持执行超时控制和危险调用检测。
- 支持 API 失败兜底输出，避免页面空白。
- 支持下载 Python 解法文件、项目报告和完整 JSON 结果。

## 项目文件

```text
Multimodal-AI-Coding-Agent-Team/
  ai_coding_agent_bailian.py        # 项目主程序，Streamlit 单文件可运行版
  requirements.txt                  # Python 依赖
  README.md                         # 项目说明
  多模态代码生成Agent项目升级功能文档.docx
  多模态代码生成Agent项目精简升级方案与分工.docx
```

## 如何运行

请按照以下步骤设置并运行应用程序。

### 1. 克隆仓库

```bash
git clone https://github.com/illusion-error/Multimodal-AI-Coding-Agent-Team.git
cd Multimodal-AI-Coding-Agent-Team
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

如果只运行当前百炼版主程序，核心依赖是 `streamlit`。仓库中的 `requirements.txt` 可能包含原版项目依赖，保留它们不影响运行。

### 3. 获取阿里云百炼 API Key

前往阿里云百炼控制台创建 API Key：

https://help.aliyun.com/zh/model-studio/get-api-key

当前项目使用的环境变量名：

```text
DASHSCOPE_API_KEY
```

### 4. 配置 API Key

方式一：在 Streamlit 页面侧边栏直接输入 API Key。

方式二：在终端中设置环境变量。

Windows PowerShell：

```powershell
$env:DASHSCOPE_API_KEY="你的阿里云百炼APIKey"
```

macOS / Linux：

```bash
export DASHSCOPE_API_KEY="你的阿里云百炼APIKey"
```

### 5. 运行 Streamlit 应用

```bash
streamlit run ai_coding_agent_bailian.py
```

启动后，浏览器会打开本地页面。一般地址类似：

```text
http://localhost:8501
```

## 默认模型配置

默认接口地址：

```text
https://dashscope.aliyuncs.com/compatible-mode/v1
```

默认模型：

```text
文本模型：qwen-plus
视觉模型：qwen3-vl-plus
```

这些配置可以在页面侧边栏中修改。

## 使用方式

1. 在页面左侧输入编程题文本，或上传编程题截图。
2. 如果上传截图，可以额外输入补充说明。
3. 点击“生成解法、执行代码并生成文档”。
4. 在页面中查看题意识别、解题说明、Python 代码和执行结果。
5. 在“下载”页签中下载 Python 解法、项目报告或完整 JSON 结果。

## 兜底机制

如果出现以下情况，系统会自动启用兜底输出：

- 未填写 API Key。
- API Key 欠费或无权限。
- 网络请求失败。
- 模型没有返回可提取的 Python 代码。
- 图片识别失败。

兜底模式下，页面仍会生成示例代码、执行结果和项目报告，方便课程答辩演示。

## 与原版项目的区别

原版项目需要：

- OpenAI API Key
- Google Gemini API Key
- E2B API Key

当前百炼版改为：

- 只需要阿里云百炼 API Key。
- 不强制使用 E2B，代码在本地临时环境中执行。
- 不强制使用 OpenAI SDK，接口调用使用百炼 OpenAI 兼容模式。
- 增加 API 失败兜底输出，保证页面始终有结果。

## 命令行测试

也可以不用打开页面，直接用命令行测试：

```bash
python ai_coding_agent_bailian.py --cli "两数之和：给定 nums 和 target，返回两个数的下标。"
```

如果没有配置 API Key，命令行会自动进入兜底模式，并输出可运行代码和执行结果。

## 后续升级方向

后续可以继续升级为完整工程化项目：

- Vue3 前端页面。
- FastAPI / Flask 后端接口。
- SQLite / MySQL 历史任务存储。
- Agent 工作流拆分。
- RAG 算法模板库。
- 自动测试和失败修复闭环。
- Docker Compose 一键部署。
