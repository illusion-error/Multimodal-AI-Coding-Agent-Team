FROM python:3.10-slim

WORKDIR /app

# 安装编译依赖，避免第三方库安装失败
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# 1. 复制【项目根目录】的依赖文件（关键修复点）
COPY requirements.txt ./

# 清华源加速安装依赖
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 2. 复制根目录核心代码、评测文件
COPY ai_coding_agent_bailian.py ./
COPY backend/database.py ./
COPY benchmark_data.json ./
COPY sandbox/ ./sandbox/

# 3. 复制整个backend后端代码文件夹
COPY backend/ ./backend/

# 统一Python模块搜索路径，解决导入报错
ENV PYTHONPATH=/app

EXPOSE 8000

# 启动命令不变，无需修改
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]