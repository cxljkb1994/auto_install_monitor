
# 使用 Python 作为基础镜像
FROM docker.rainbond.cc/python:3.10-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    openssh-client sshpass \
    && rm -rf /var/lib/apt/lists/*

# 复制requirements.txt并安装Python依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt  -i http://172.16.0.184:8081/repository/pypi/simple --trusted-host 172.16.0.184

# 创建日志目录
RUN mkdir -p /app/logs && \
    chmod 777 /app/logs

# 复制应用代码
COPY . ./

# # 设置默认环境变量
ENV ANSIBLE_HOST_KEY_CHECKING=False 


# 设置容器的日志目录
VOLUME ["/app/logs"]

# 暴露Flask应用端口


# 运行Flask应用
CMD ["python", "deploy.py"]