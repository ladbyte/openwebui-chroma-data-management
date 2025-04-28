# Chroma 展示项目

## 项目背景

本项目是一个专门用于查看已部署OpenWebUI向量数据库数据的工具。通过本项目，用户可以方便地连接和浏览OpenWebUI使用的Chroma向量数据库，查看Collections信息、检索向量数据内容以及重建原始文件内容。

## 功能描述

- **初始化Chroma客户端**：快速连接本地或远程Chroma数据库
- **管理Collections**：创建、删除、查询Collections
- **批量处理Collections**：高效处理大量Collections，支持多线程
- **文件名与Collection映射**：自动建立文件名与Collection的映射关系
- **文件内容重建**：从Collection中提取并重建原始文件内容

## 配置说明

1. **安装依赖**：
```bash
pip install -r requirements.txt
```

2. **配置数据库路径**：
在初始化`ChromaClient`时直接传入数据库路径参数。例如：
```python
# 初始化客户端时指定数据库路径
client = ChromaClient(path="./chroma_db")
```

或者通过环境变量配置：
```python
import os
# 从环境变量读取数据库路径
db_path = os.getenv("CHROMA_DB_PATH", "./chroma_db")
client = ChromaClient(path=db_path)
```

3. **日志配置**：
日志文件默认存储在`logs`目录下，按时间戳命名。日志级别为DEBUG，同时输出到控制台和日志文件。


## Web界面

本项目使用Gradio构建可视化Web界面，提供以下功能：

- **数据库状态查看**：实时显示Collections数量和基本信息
- **内容检索**：通过关键词搜索Collection内容
- **文件重建**：从Collection重建原始文件内容

### 启动方式

```bash
python chroma_show.py
```

启动后默认访问地址：http://localhost:7860

## 注意事项

- 确保指定的数据库目录可写
- 批量处理时注意内存使用情况
- 定期清理不再使用的Collections以节省空间
- 建议在生产环境中配置合适的日志级别