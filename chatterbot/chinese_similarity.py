#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
中文语义相似度计算器
专为ChatterBot优化，解决中文匹配问题
"""

import re
import jieba
from difflib import SequenceMatcher

class ChineseSemanticSimilarity:
    """专为中文设计的语义相似度计算器"""
    
    def __init__(self):
        # 初始化jieba分词
        jieba.initialize()
        
        # 同义词映射表
        self.synonyms = {
            # 时间询问类
            "什么时候": ["啥时候", "啥时", "何时", "几时", "什么时间", "多会儿"],
            "怎么": ["为什么", "为啥", "咋", "咋样", "怎样"],
            
            # 状态询问类
            "发货了吗": ["发货没有", "发货了没", "发了吗", "发出来了吗", "寄出来了吗"],
            "还没": ["还不", "还没有", "没有", "没"],
            "发货": ["寄货", "出货", "发送", "邮寄", "寄送"],
            
            # 语气词
            "吗": ["没", "呢", ""],
            "呀": ["啊", ""],
        }
        
        # 停用词（对匹配意义不大的词）
        self.stop_words = {"的", "了", "吗", "?", "？", "!", "！", "。", "，", ","}
    
    def normalize_text(self, text):
        """文本标准化处理"""
        # 去除标点符号和空格
        text = re.sub(r'[^\w]', '', text)
        return text.lower()
    
    def extract_keywords(self, text):
        """提取关键词"""
        # 分词
        words = jieba.lcut(text)
        # 过滤停用词
        keywords = [word for word in words if word not in self.stop_words and len(word) > 0]
        return keywords
    
    def expand_synonyms(self, text):
        """扩展同义词"""
        expanded_forms = [text]
        
        for original, synonyms in self.synonyms.items():
            if original in text:
                for synonym in synonyms:
                    expanded_forms.append(text.replace(original, synonym))
            
            # 反向扩展
            for synonym in synonyms:
                if synonym in text:
                    expanded_forms.append(text.replace(synonym, original))
        
        return list(set(expanded_forms))  # 去重
    
    def calculate_similarity(self, text1, text2):
        """计算两个文本的相似度"""
        # 1. 完全匹配
        if text1 == text2:
            return 1.0
        
        # 2. 标准化后匹配
        norm1 = self.normalize_text(text1)
        norm2 = self.normalize_text(text2)
        if norm1 == norm2:
            return 0.95
        
        # 3. 同义词扩展匹配
        expanded1 = self.expand_synonyms(text1)
        expanded2 = self.expand_synonyms(text2)
        
        max_similarity = 0.0
        for exp1 in expanded1:
            for exp2 in expanded2:
                if exp1 == exp2:
                    return 0.9
                # 使用SequenceMatcher计算字符串相似度
                similarity = SequenceMatcher(None, exp1, exp2).ratio()
                max_similarity = max(max_similarity, similarity)
        
        # 4. 关键词匹配
        keywords1 = set(self.extract_keywords(text1))
        keywords2 = set(self.extract_keywords(text2))
        
        if keywords1 and keywords2:
            # 计算关键词交集比例
            intersection = len(keywords1 & keywords2)
            union = len(keywords1 | keywords2)
            keyword_similarity = intersection / union if union > 0 else 0
            
            # 综合相似度
            max_similarity = max(max_similarity, keyword_similarity * 0.8)
        
        return max_similarity