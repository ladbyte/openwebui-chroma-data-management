import os
import gradio as gr
import chromadb
import numpy as np
import pandas as pd
from chromadb.config import Settings
import json
from collections import defaultdict
import concurrent.futures
import threading
from typing import Dict, List
import time
import logging
from datetime import datetime

# 配置日志系统
def setup_logging():
    """设置日志系统，创建日志目录和文件，同时输出到控制台"""
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    log_filename = os.path.join(log_dir, f"chroma_client_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s [%(levelname)s] %(name)s:%(funcName)s - %(message)s',
        handlers=[
            logging.FileHandler(log_filename, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

class ChromaClient:
    def __init__(self, path):
        """初始化ChromaClient，设置数据库路径和日志"""
        self.logger = setup_logging()
        self.logger.info("正在初始化ChromaClient")
        
        settings_dict = {"allow_reset": True, "anonymized_telemetry": False}
        try:
            self.client = chromadb.PersistentClient(path=path, settings=Settings(**settings_dict))
            self.filename_to_collections = defaultdict(list)
            self.is_mapping_initialized = False
            self._lock = threading.Lock()
            self.progress = {"current": 0, "total": 0, "status": ""}
            self.last_update_time = 0  # 用于缓存刷新时间戳
            self.logger.info(f"ChromaClient初始化成功，数据库路径: {path}")
        except Exception as e:
            self.logger.error(f"ChromaClient初始化失败: {str(e)}")
            raise

    def list_collections(self):
        """获取所有Collection名称"""
        self.logger.info("获取Collection列表")
        try:
            collections = self.client.list_collections()
            result = [col.name for col in collections] if collections else ["没有找到任何Collection"]
            self.logger.debug(f"找到 {len(result)} 个Collection")
            return result
        except Exception as e:
            self.logger.error(f"获取Collection列表失败: {str(e)}")
            return ["获取Collection列表出错"]

    def process_collection_batch(self, collections):
        """批量处理Collection，获取文件名和Collection映射"""
        self.logger.debug(f"处理 {len(collections)} 个Collection批次")
        results = []
        for col in collections:
            try:
                result = col.get(limit=1, include=["metadatas"])  # 只获取元数据，减少数据量
                if result['metadatas'] and result['metadatas'][0]:
                    filename = result['metadatas'][0].get('name', '')
                    if filename:
                        results.append((filename, col.name))
                        self.logger.debug(f"处理Collection {col.name}，关联文件名: {filename}")
            except Exception as e:
                self.logger.error(f"处理Collection {col.name} 失败: {str(e)}")
        return results

    def lazy_update_filename_mapping(self, force_refresh=False) -> str:
        """延迟更新文件名到Collection的映射，使用多线程加速，并支持缓存"""
        current_time = time.time()
        if self.is_mapping_initialized and not force_refresh and (current_time - self.last_update_time < 300):  # 缓存5分钟
            self.logger.info("文件名映射已初始化且未过期，跳过更新")
            return "文件列表已加载（使用缓存）"

        self.logger.info("开始更新文件名映射")
        try:
            collections = self.client.list_collections()
            total = len(collections)
            if total == 0:
                self.logger.warning("未找到任何Collection")
                return "没有找到任何Collection"

            self.progress = {"current": 0, "total": total, "status": "开始加载..."}
            start_time = time.time()

            # 分批处理Collection，调整批次大小
            batch_size = 100  # 增大批次大小，减少线程开销
            collection_batches = [collections[i:i + batch_size] for i in range(0, total, batch_size)]

            # 使用线程池并行处理，动态调整worker数量
            max_workers = min(20, max(1, os.cpu_count() or 1))  # 根据CPU核心数动态调整
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_batch = {executor.submit(self.process_collection_batch, batch): i 
                                  for i, batch in enumerate(collection_batches)}

                self.filename_to_collections.clear()

                for future in concurrent.futures.as_completed(future_to_batch):
                    batch_results = future.result()
                    batch_index = future_to_batch[future]
                    
                    with self._lock:
                        for filename, col_name in batch_results:
                            self.filename_to_collections[filename].append(col_name)
                        processed = min((batch_index + 1) * batch_size, total)
                        self.progress["current"] = processed
                        percentage = (processed / total) * 100
                        self.progress["status"] = f"已处理: {processed}/{total} ({percentage:.1f}%)"

            end_time = time.time()
            duration = end_time - start_time
            total_files = len(self.filename_to_collections)
            total_mappings = sum(len(cols) for cols in self.filename_to_collections.values())
            
            self.is_mapping_initialized = True
            self.last_update_time = current_time
            self.logger.info(f"文件名映射更新完成，处理 {total} 个Collection，找到 {total_files} 个文件，{total_mappings} 个映射，用时 {duration:.2f} 秒")
            return (f"加载完成! 处理了 {total} 个collections, "
                    f"找到 {total_files} 个唯一文件名, "
                    f"共 {total_mappings} 个映射, "
                    f"用时 {duration:.2f} 秒")
        except Exception as e:
            self.logger.error(f"更新文件名映射失败: {str(e)}")
            return f"更新文件名映射出错: {str(e)}"

    def get_loading_progress(self) -> str:
        """获取当前加载进度"""
        progress = self.progress["status"]
        self.logger.debug(f"查询加载进度: {progress}")
        return progress

    def list_filenames(self):
        """获取所有原始文件名"""
        filenames = sorted(list(self.filename_to_collections.keys()))
        self.logger.info(f"获取文件名列表，共 {len(filenames)} 个文件")
        return filenames

    def get_collections_by_filename(self, filename):
        """通过文件名获取相关的Collection"""
        collections = self.filename_to_collections.get(filename, [])
        self.logger.debug(f"查询文件名 {filename} 的Collection，找到 {len(collections)} 个")
        return collections

    def get_collection_content(self, collection_name: str):
        """获取Collection内容并记录操作，展示所有分段"""
        if not collection_name or collection_name in ["没有找到任何Collection", "获取Collection列表出错"]:
            self.logger.warning("无效的Collection名称")
            return "请选择有效的Collection"
        
        self.logger.info(f"获取Collection {collection_name} 的内容")
        try:
            collection = self.client.get_collection(name=collection_name)
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                metadata_future = executor.submit(lambda: collection.get(limit=1))
                count_future = executor.submit(collection.count)
                result = metadata_future.result()
                count = count_future.result()

            if not result['ids']:
                self.logger.warning(f"Collection {collection_name} 为空")
                return "Collection为空"

            file_info = {}
            embedding_config = None
            for metadata in result['metadatas']:
                if metadata.get('file_id') and metadata.get('name'):
                    file_info['file_id'] = metadata.get('file_id')
                    file_info['filename'] = metadata.get('name')
                    file_info['hash'] = metadata.get('hash')
                    file_info['source'] = metadata.get('source')
                    if metadata.get('embedding_config'):
                        try:
                            embedding_config = json.loads(metadata.get('embedding_config'))
                        except:
                            pass
                    break

            info = "文件信息:\n"
            info += f"文件名: {file_info.get('filename', '未知')}\n"
            info += f"文件ID: {file_info.get('file_id', '未知')}\n"
            info += f"文件哈希: {file_info.get('hash', '未知')}\n"
            info += f"文件路径: {file_info.get('source', '未知')}\n"
            
            if embedding_config:
                info += f"\n嵌入模型配置:\n"
                info += f"引擎: {embedding_config.get('engine', '未知')}\n"
                info += f"模型: {embedding_config.get('model', '未知')}\n"
            
            info += f"\nCollection统计:\n"
            info += f"文档总数: {count}\n"
            if result['embeddings']:
                info += f"向量维度: {len(result['embeddings'][0])}\n"

            # 分批获取所有分段
            batch_size = 500
            num_batches = (count + batch_size - 1) // batch_size
            all_segments = []

            self.logger.info(f"开始获取 {count} 个分段，分为 {num_batches} 批")
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = [
                    executor.submit(
                        lambda offset: collection.get(
                            limit=batch_size,
                            offset=offset,
                            include=["documents", "metadatas"]  # 修复：移除 'ids'
                        ),
                        i * batch_size
                    )
                    for i in range(num_batches)
                ]

                for future in concurrent.futures.as_completed(futures):
                    batch_data = future.result()
                    for id_, doc, metadata in zip(
                        batch_data['ids'],  # ids 自动包含在返回结果中
                        batch_data['documents'],
                        batch_data['metadatas']
                    ):
                        all_segments.append((id_, doc, metadata))

            # 按分段索引排序（可选）
            all_segments.sort(key=lambda x: x[2].get('start_index', 0))

            # 格式化所有分段
            info += "\n文档分段（全部）:\n"
            for i, (id_, doc, metadata) in enumerate(all_segments):
                info += f"\n分段 #{i+1}:\n"
                info += f"分段ID: {id_}\n"
                info += f"起始索引: {metadata.get('start_index', '未知')}\n"
                info += f"内容: {doc[:200]}...\n"
                info += "-" * 50 + "\n"
            
            self.logger.debug(f"成功获取Collection {collection_name} 的全部 {len(all_segments)} 个分段")
            return info
        except Exception as e:
            self.logger.error(f"获取Collection {collection_name} 内容失败: {str(e)}")
            return f"获取Collection内容出错: {str(e)}"

    def get_raw_file_content(self, collection_name: str):
        """获取并重建完整文件内容"""
        if not collection_name or collection_name in ["没有找到任何Collection", "获取Collection列表出错"]:
            self.logger.warning("无效的Collection名称")
            return "请选择有效的Collection"
        
        self.logger.info(f"获取Collection {collection_name} 的原始文件内容")
        try:
            collection = self.client.get_collection(name=collection_name)
            count = collection.count()
            if count == 0:
                self.logger.warning(f"Collection {collection_name} 为空")
                return "Collection为空"

            batch_size = 500
            num_batches = (count + batch_size - 1) // batch_size
            all_segments = []

            with concurrent.futures.ThreadPoolExecutor(max_workers=500) as executor:
                futures = [executor.submit(lambda o: collection.get(limit=batch_size, offset=o), i * batch_size) 
                           for i in range(num_batches)]
                for future in concurrent.futures.as_completed(futures):
                    result = future.result()
                    for i, doc in enumerate(result['documents']):
                        start_index = result['metadatas'][i].get('start_index', 0)
                        all_segments.append((start_index, doc))

            if not all_segments:
                self.logger.warning(f"Collection {collection_name} 无内容")
                return "Collection为空"

            all_segments.sort(key=lambda x: x[0])
            content = "完整文件内容:\n" + "="*50 + "\n\n" + "\n".join(seg[1] for seg in all_segments) + "\n\n" + "="*50
            self.logger.debug(f"成功重建Collection {collection_name} 的文件内容")
            return content
        except Exception as e:
            self.logger.error(f"获取原始文件内容失败: {str(e)}")
            return f"获取原始文件内容出错: {str(e)}"

    def delete_collections_by_filename(self, filename) -> str:
        """删除与文件名相关的所有Collection"""
        if not filename:
            self.logger.warning("未选择文件名")
            return "请选择要删除的文件"
        
        collections = self.filename_to_collections.get(filename, [])
        if not collections:
            self.logger.warning(f"文件名 {filename} 无关联Collection")
            return "未找到与此文件名相关的Collection"
        
        self.logger.info(f"开始删除文件名 {filename} 的 {len(collections)} 个Collection")
        try:
            deleted_count = 0
            for col_name in collections:
                try:
                    self.client.delete_collection(col_name)
                    deleted_count += 1
                    self.logger.debug(f"成功删除Collection {col_name}")
                except Exception as e:
                    self.logger.error(f"删除Collection {col_name} 失败: {str(e)}")
            
            if deleted_count > 0:
                del self.filename_to_collections[filename]
                self.logger.info(f"已从映射中移除文件名 {filename}")
            
            self.logger.info(f"删除完成，成功删除 {deleted_count}/{len(collections)} 个Collection")
            return f"成功删除了 {deleted_count}/{len(collections)} 个collections"
        except Exception as e:
            self.logger.error(f"删除Collection失败: {str(e)}")
            return f"删除出错: {str(e)}"

def create_interface():
    """创建Gradio界面"""
    client = ChromaClient("path/to/data/vector_db")  # OpenWebui的向量库路径
    client.logger.info("创建Gradio界面")
    
    with gr.Blocks(title="ChromaDB 文件查看器") as app:
        gr.Markdown("## 📊 ChromaDB 文件查看器")
        
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### 按Collection ID查看")
                collection_dropdown = gr.Dropdown(choices=client.list_collections(), label="选择Collection", interactive=True)
                refresh_btn = gr.Button("🔄 刷新Collection列表")
            
            with gr.Column(scale=1):
                gr.Markdown("### 按文件名查看")
                filename_dropdown = gr.Dropdown(choices=[], label="选择文件名", interactive=True)
                with gr.Row():
                    refresh_files_btn = gr.Button("🔄 加载/刷新文件列表")
                    delete_btn = gr.Button("🗑️ 删除选中文件", variant="stop")

        with gr.Row(visible=False) as confirm_dialog:
            confirm_text = gr.Textbox(label="确认信息", interactive=False)
            with gr.Row():
                confirm_btn = gr.Button("确认删除", variant="stop")
                cancel_btn = gr.Button("取消")

        progress_display = gr.Textbox(label="状态信息", interactive=False, value="准备就绪")
        
        with gr.Tabs():
            with gr.TabItem("文件信息"):
                info_display = gr.Textbox(label="文件详细信息", interactive=False, lines=25)
            with gr.TabItem("原始文件内容"):
                content_display = gr.Textbox(label="完整文件内容", interactive=False, lines=30)

        def refresh_filenames_with_progress():
            """异步刷新文件名列表并记录操作"""
            client.logger.info("刷新文件名列表")
            try:
                if not client.is_mapping_initialized:
                    status = client.lazy_update_filename_mapping()
                filenames = client.list_filenames()
                client.logger.debug(f"文件名列表刷新完成，找到 {len(filenames)} 个文件")
                return [gr.update(choices=filenames, value=filenames[0] if filenames else None), "文件列表已更新"]
            except Exception as e:
                client.logger.error(f"刷新文件名列表失败: {str(e)}")
                return [gr.update(choices=[]), f"加载文件列表时出错: {str(e)}"]

        def on_filename_select(filename):
            if not filename:
                client.logger.warning("未选择文件名")
                return [gr.update(), "请选择文件名", "请选择文件名"]
            collections = client.get_collections_by_filename(filename)
            if not collections:
                client.logger.warning(f"文件名 {filename} 无关联Collection")
                return [gr.update(), "未找到与此文件名相关的Collection", "未找到与此文件名相关的Collection"]
            collection_name = collections[0]
            content = client.get_collection_content(collection_name)
            raw_content = client.get_raw_file_content(collection_name)
            client.logger.debug(f"文件名 {filename} 选择完成，关联Collection: {collection_name}")
            return [gr.update(value=collection_name), content, raw_content]

        def on_collection_select(collection_name):
            if not collection_name or collection_name in ["没有找到任何Collection", "获取Collection列表出错"]:
                client.logger.warning("无效的Collection选择")
                return ["请选择有效的Collection", "请选择有效的Collection"]
            content = client.get_collection_content(collection_name)
            raw_content = client.get_raw_file_content(collection_name)
            client.logger.debug(f"Collection {collection_name} 内容加载完成")
            return [content, raw_content]

        def show_confirm(filename):
            if not filename:
                client.logger.warning("未选择文件名")
                return ["请先选择要删除的文件", gr.update(visible=False), ""]
            collections = client.get_collections_by_filename(filename)
            confirm_msg = f"确定要删除文件 '{filename}' 相关的 {len(collections)} 个collections吗？"
            client.logger.debug(f"显示删除确认，涉及 {len(collections)} 个Collection")
            return ["请确认是否删除", gr.update(visible=True), confirm_msg]

        def hide_confirm():
            client.logger.info("取消删除操作")
            return [gr.update(visible=False), "操作已取消"]

        def delete_file(filename):
            client.logger.info(f"执行删除文件名 {filename} 的Collection")
            try:
                if not filename:
                    client.logger.warning("未选择文件名")
                    return ["请先选择要删除的文件", gr.update(visible=False), gr.update(), gr.update(), "", ""]
                status = client.delete_collections_by_filename(filename)
                remaining_files = client.list_filenames()
                remaining_collections = client.list_collections()
                client.logger.debug(f"删除操作完成，剩余 {len(remaining_files)} 个文件")
                return [status, gr.update(visible=False), gr.update(choices=remaining_files, value=None), 
                        gr.update(choices=remaining_collections, value=None), "", ""]
            except Exception as e:
                client.logger.error(f"删除文件 {filename} 失败: {str(e)}")
                return [f"删除文件时出错: {str(e)}", gr.update(visible=False), gr.update(), gr.update(), "", ""]

        refresh_btn.click(fn=lambda: gr.update(choices=client.list_collections()), outputs=collection_dropdown)
        refresh_files_btn.click(fn=refresh_filenames_with_progress, outputs=[filename_dropdown, progress_display])
        collection_dropdown.change(fn=on_collection_select, inputs=[collection_dropdown], outputs=[info_display, content_display])
        filename_dropdown.change(fn=on_filename_select, inputs=[filename_dropdown], outputs=[collection_dropdown, info_display, content_display])
        delete_btn.click(fn=show_confirm, inputs=[filename_dropdown], outputs=[progress_display, confirm_dialog, confirm_text])
        confirm_btn.click(fn=delete_file, inputs=[filename_dropdown], outputs=[progress_display, confirm_dialog, filename_dropdown, collection_dropdown, info_display, content_display])
        cancel_btn.click(fn=hide_confirm, outputs=[confirm_dialog, progress_display])
        
    return app

if __name__ == "__main__":
    app = create_interface()
    app.queue()
    app.launch(server_name="0.0.0.0", share=False)