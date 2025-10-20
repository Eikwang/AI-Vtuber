# -*- coding: UTF-8 -*-
"""
@Project : AI-Vtuber 
@File    : chatterbot.py
@Author  : HildaM
@Email   : Hilda_quan@163.com
@Date    : 2025/09/26 下午 11:47 
@Description : Chatterbot模型类
"""

import os
import traceback
from utils.my_log import logger

# Chatterbot集成
try:
    from chatterbot import ChatBot
    from chatterbot.trainers import ListTrainer
    CHATTERBOT_AVAILABLE = True
except ImportError:
    CHATTERBOT_AVAILABLE = False
    logger.warning("Chatterbot 未安装，请先安装依赖: pip install chatterbot chatterbot_corpus")


class ChatterBot:
    def __init__(self, config):
        """
        初始化Chatterbot模型
        
        Args:
            config (dict): 配置信息，包含name、db_path等
        """
        self.config_data = config
        self.chatbot_instance = None
        
        if not CHATTERBOT_AVAILABLE:
            logger.error("Chatterbot 依赖未安装，无法初始化")
            return
        
        self._initialize_chatbot()
    
    def _initialize_chatbot(self):
        """初始化Chatterbot实例并进行训练"""
        try:
            # 使用配置中的数据库路径
            db_path = self.config_data.get("db_path", "chatterbot/db.sqlite3")
            # 确保路径格式正确
            if "\\" in db_path:
                db_path = db_path.replace("\\", "/")
            database_uri = f'sqlite:///{db_path}'
            
            # 创建ChatBot实例
            self.chatbot_instance = ChatBot(
                self.config_data.get("name", "AI-Vtuber-Chatterbot"),
                storage_adapter='chatterbot.storage.SQLStorageAdapter',
                database_uri=database_uri,
                logic_adapters=[
                    'chatterbot.logic.BestMatch'
                ]
            )
            
            # 训练模型（如果方法存在）
            if hasattr(self, '_train_chatbot'):
                self._train_chatbot()
            else:
                logger.info("Chatterbot训练已跳过，使用预训练模型")
            
            logger.info("Chatterbot模型初始化完成")
            
        except Exception as e:
            logger.error(f"Chatterbot初始化失败: {e}")
            logger.error(traceback.format_exc())
    
    # def _train_chatbot(self):
    #     """使用本地数据训练Chatterbot"""
    #     if not self.chatbot_instance:
    #         return
        
    #     try:
    #         trainer = ListTrainer(self.chatbot_instance)
    #         total_qa_pairs = 0
            
    #         # 训练数据文件列表
    #         training_files = [
    #             'chatterbot/data/db.txt',           # 主要技术问答数据
    #             'chatterbot/data/basic_conversation.txt'  # 基础对话数据
    #         ]
            
    #         for local_data_path in training_files:
    #             if os.path.exists(local_data_path):
    #                 with open(local_data_path, 'r', encoding='utf-8') as f:
    #                     content = f.read()
                    
    #                 # 解析问答对格式
    #                 qa_pairs = []
    #                 lines = content.split('\n')
    #                 current_question = None
                    
    #                 for line in lines:
    #                     line = line.strip()
    #                     if not line:
    #                         continue
                        
    #                     if line.startswith('问：'):
    #                         current_question = line[2:].strip()
    #                     elif line.startswith('答：') and current_question:
    #                         answer = line[2:].strip()
    #                         qa_pairs.extend([current_question, answer])
    #                         current_question = None
                    
    #                 if qa_pairs:
    #                     trainer.train(qa_pairs)
    #                     file_qa_count = len(qa_pairs) // 2
    #                     total_qa_pairs += file_qa_count
    #                     logger.info(f"从 {local_data_path} 训练完成，共{file_qa_count}个问答对")
    #                 else:
    #                     # 如果没有问答对格式，尝试直接按行读取作为对话对
    #                     lines = [line.strip() for line in content.split('\n') if line.strip()]
    #                     if lines:
    #                         trainer.train(lines)
    #                         file_line_count = len(lines)
    #                         total_qa_pairs += file_line_count
    #                         logger.info(f"从 {local_data_path} 使用对话格式训练完成，共{file_line_count}行数据")
    #                     else:
    #                         logger.warning(f"训练数据文件为空: {local_data_path}")
    #             else:
    #                 logger.warning(f"训练数据文件不存在: {local_data_path}")
            
    #         logger.info(f"Chatterbot训练完成，总共使用{total_qa_pairs}个训练数据")
                
        except Exception as e:
            logger.error(f"Chatterbot训练失败: {e}")
            logger.error(traceback.format_exc())
    
    def get_resp(self, prompt, stream=False):
        """
        获取Chatterbot的回复
        
        Args:
            prompt (str): 输入文本
            stream (bool): 是否流式输出（Chatterbot不支持流式）
            
        Returns:
            str: 回复内容
        """
        if not self.chatbot_instance:
            return "[Chatterbot未初始化]"
        
        try:
            response = self.chatbot_instance.get_response(prompt)
            return str(response)
            
        except Exception as e:
            logger.error(f"Chatterbot推理失败: {e}")
            logger.error(traceback.format_exc())
            return "[Chatterbot推理失败]"
    
    def chat(self, text):
        """
        聊天接口（兼容旧版调用方式）
        
        Args:
            text (str): 输入文本
            
        Returns:
            str: 回复内容
        """
        return self.get_resp(text)