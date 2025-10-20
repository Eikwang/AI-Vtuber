"""
表情符号检测和处理工具类
提供统一的表情符号检测、过滤功能
"""
import unicodedata
import re
from typing import List, Optional
from utils.my_log import logger


class EmojiUtils:
    """表情符号检测和处理工具类"""
    
    # 表情符号Unicode范围定义
    EMOJI_RANGES = [
        (0x1F600, 0x1F64F),  # 表情符号
        (0x1F300, 0x1F5FF),  # 符号和象形文字
        (0x1F680, 0x1F6FF),  # 交通和地图符号
        (0x1F1E0, 0x1F1FF),  # 国旗
        (0x2600, 0x26FF),    # 杂项符号
        (0x2700, 0x27BF),    # 装饰符号
        (0x1F900, 0x1F9FF),  # 补充符号和象形文字
        (0x1FA00, 0x1FA6F),  # 扩展-A
        (0x1FA70, 0x1FAFF),  # 符号和象形文字扩展-A
        (0x1F004, 0x1F0CF),  # 麻将牌、扑克牌等
        (0x1F170, 0x1F251),  # 字母符号等
    ]
    
    # 表情相关关键词
    EMOJI_KEYWORDS = [
        'FACE', 'SMILE', 'HEART', 'HAND', 'THUMBS', 'FIRE', 'STAR',
        'GAME', 'VIDEO', 'CONTROLLER', 'JOYSTICK', 'PARTY', 'GLOBE', 'EARTH'
    ]
    
    @classmethod
    def is_emoji(cls, char: str) -> bool:
        """判断字符是否为表情符号
        
        Args:
            char (str): 单个字符
            
        Returns:
            bool: 是否为表情符号
        """
        try:
            code_point = ord(char)
            
            # 检查是否在表情符号范围内
            for start, end in cls.EMOJI_RANGES:
                if start <= code_point <= end:
                    return True
            
            # 检查Unicode名称是否包含表情相关关键词
            try:
                name = unicodedata.name(char, '')
                if any(keyword in name for keyword in cls.EMOJI_KEYWORDS):
                    return True
            except:
                pass
                
            return False
        except:
            return False
    
    @classmethod
    def remove_emojis(cls, text: str) -> str:
        """从文本中移除表情符号
        
        Args:
            text (str): 原始文本
            
        Returns:
            str: 移除表情符号后的文本
        """
        try:
            if not text:
                return text
                
            # 过滤掉表情符号
            processed_text = ''.join(char for char in text if not cls.is_emoji(char))
            return processed_text.strip()
        except Exception as e:
            logger.error(f"移除表情符号时出错: {e}")
            return text
    
    @classmethod
    def remove_bracket_emojis(cls, text: str) -> str:
        """移除括号格式的表情符号（如[表情名]）
        
        Args:
            text (str): 原始文本
            
        Returns:
            str: 移除括号表情后的文本
        """
        try:
            if not text:
                return text
            
            # 移除[xxx]格式的表情
            cleaned_text = re.sub(r'\[.*?\]', '', text)
            return cleaned_text.strip()
        except Exception as e:
            logger.error(f"移除括号表情符号时出错: {e}")
            return text
    
    @classmethod
    def clean_text(cls, text: str, remove_unicode_emojis: bool = True, remove_bracket_emojis: bool = True) -> str:
        """清理文本中的表情符号
        
        Args:
            text (str): 原始文本
            remove_unicode_emojis (bool): 是否移除Unicode表情符号
            remove_bracket_emojis (bool): 是否移除括号格式表情符号
            
        Returns:
            str: 清理后的文本
        """
        if not text:
            return text
            
        cleaned_text = text
        
        # 移除Unicode表情符号
        if remove_unicode_emojis:
            cleaned_text = cls.remove_emojis(cleaned_text)
        
        # 移除括号格式表情符号
        if remove_bracket_emojis:
            cleaned_text = cls.remove_bracket_emojis(cleaned_text)
            
        return cleaned_text.strip()