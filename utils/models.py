from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Dict, Any, Optional
    
class SetConfigMessage(BaseModel):
    config_path: str
    data: Dict[str, Any]
    
class SysCmdMessage(BaseModel):
    type: str
    api_type: Optional[str] = None
    data: Dict[str, Any]

class SendMessage(BaseModel):
    type: str
    data: Dict[str, Any]

class LLMMessage(BaseModel):
    type: str
    username: str
    content: str

class TTSMessage(BaseModel):
    type: str
    tts_type: str
    data: Dict[str, Any]
    username: str
    content: str

class CallbackMessage(BaseModel):
    type: str
    data: Dict[str, Any]

# 弹幕管理相关模型
class DanmakuConnectionConfig(BaseModel):
    platform: str
    room_id: str
    
class DanmakuManageMessage(BaseModel):
    action: str  # add, start, stop, delete
    connections: List[DanmakuConnectionConfig]

class DanmakuConnectionStatus(BaseModel):
    platform: str
    room_id: str
    status: str  # running, stopped, error
    error_message: Optional[str] = None

"""
通用
""" 
class CommonResult(BaseModel):
    code: int
    message: str
    data: Optional[Dict[str, Any]] = None
