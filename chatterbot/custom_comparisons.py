#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
自定义ChatterBot比较器
集成中文语义相似度算法到ChatterBot框架中
"""

from chatterbot.comparisons import Comparator
from chinese_similarity import ChineseSemanticSimilarity

class ChineseSimilarityComparator(Comparator):
    """
    专为中文优化的ChatterBot比较器
    直接集成到ChatterBot框架中使用
    """
    
    def __init__(self, language=None):
        super().__init__(language)
        self.similarity_calculator = ChineseSemanticSimilarity()
    
    def compare(self, statement_a, statement_b):
        """
        比较两个Statement对象的相似度
        
        Args:
            statement_a: ChatterBot Statement对象
            statement_b: ChatterBot Statement对象
            
        Returns:
            float: 相似度分数 (0.0-1.0)
        """
        # 提取文本内容
        text_a = statement_a.text if hasattr(statement_a, 'text') else str(statement_a)
        text_b = statement_b.text if hasattr(statement_b, 'text') else str(statement_b)
        
        # 使用中文语义相似度计算
        return self.similarity_calculator.calculate_similarity(text_a, text_b)