import os, sys, threading, json, random, time
import difflib
from datetime import datetime
import traceback
import importlib
import asyncio
import queue

import copy
import re
from functools import partial

from asyncio import Queue

# 定义一个全局队列用于异步处理助播信息
assistant_anchor_queue = Queue()

async def process_assistant_anchor_queue():
    """异步处理助播信息队列"""
    while True:
        try:
            message = await assistant_anchor_queue.get()
            if message is None:  # 退出信号
                break
            # 执行TTS合成和音频存储
            My_handle.audio.audio_synthesis(message)
            logger.info(f"助播信息处理完成: {message}")
        except Exception as e:
            logger.error(f"处理助播信息时发生错误: {e}")


from .config import Config
from .common import Common
from .audio import Audio
from .gpt_model.gpt import GPT_MODEL
from .my_log import logger
from .db import SQLiteDB
from .my_translate import My_Translate


from .luoxi_project.live_comment_assistant import send_msg_to_live_comment_assistant
from .danmaku_websocket_server import get_danmaku_websocket_server


# 助播管理器类
class AssistantAnchorManager:
    """助播功能统一管理类"""
    
    def __init__(self, config):
        self.config = config
        
        # 安全地获取配置项，如果不存在则使用默认值
        assistant_anchor_config = config.get("assistant_anchor")
        if assistant_anchor_config is None:
            # 如果assistant_anchor配置不存在，使用默认值
            self.enabled = False
            self.supported_types = []
            self.username = "助播"
            self.audio_synthesis_type = "edge-tts"
            self.local_qa_enabled = False
            self.local_qa_format = "json"
            self.local_qa_file_path = ""
            self.local_qa_similarity = 0.8
        else:
            # 如果配置存在，安全地获取各项配置
            self.enabled = assistant_anchor_config.get("enable", False)
            self.supported_types = assistant_anchor_config.get("type", [])
            self.username = assistant_anchor_config.get("username", "助播")
            self.audio_synthesis_type = assistant_anchor_config.get("audio_synthesis_type", "edge-tts")
            
            # 助播本地问答库配置
            local_qa_config = assistant_anchor_config.get("local_qa", {})
            if local_qa_config:
                text_config = local_qa_config.get("text", {})
                self.local_qa_enabled = text_config.get("enable", False)
                self.local_qa_format = text_config.get("format", "json")
                self.local_qa_file_path = text_config.get("file_path", "")
                self.local_qa_similarity = text_config.get("similarity", 0.8)

                audio_config = local_qa_config.get("audio", {})
                self.local_qa_audio_enabled = audio_config.get("enable", False)
                self.local_qa_audio_format = audio_config.get("format", "相似度匹配")
                self.local_qa_audio_file_path = audio_config.get("file_path", "")
                self.local_qa_audio_similarity = audio_config.get("similarity", 0.8)
            else:
                self.local_qa_enabled = False
                self.local_qa_format = "json"
                self.local_qa_file_path = ""
                self.local_qa_similarity = 0.8
                self.local_qa_audio_enabled = False
                self.local_qa_audio_format = "相似度匹配"
                self.local_qa_audio_file_path = ""
                self.local_qa_audio_similarity = 0.8
    
    def should_handle(self, data_type):
        """判断是否应该由助播处理"""
        return self.enabled and data_type in self.supported_types
    
    def process(self, data, data_type, my_handle):
        """统一的助播处理入口
        
        Args:
            data: 数据信息
            data_type: 数据类型
            my_handle: My_handle实例，用于调用相关方法
            
        Returns:
            (是否已处理, 处理结果, 是否继续全局处理)
        """
        try:
            if not self.should_handle(data_type):
                return False, None, True
            
            logger.debug(f'助播处理开始: {data_type} - {data}')
            
            # 1、特定类型直接由助播TTS处理（入场、礼物、关注等）
            if data_type in ["entrance", "gift", "follow", "integral"]:
                result = self._process_specific_type(data, data_type, my_handle)
                if result:
                    logger.info(f"助播处理{data_type}类型，由助播TTS处理")
                    asyncio.run(assistant_anchor_queue.put(result))
                    return True, result, False  # 已处理，不继续全局处理
            
            # 2、念弹幕类型直接使用助播TTS
            if data_type == "read_comment":
                result = self._create_read_comment_message(data)
                logger.info(f"助播处理念弹幕，由助播TTS处理")
                asyncio.run(assistant_anchor_queue.put(result))
                return True, result, False  # 已处理，不继续全局处理
            
            # 3、对于定时任务和闲时任务类型，如果助播支持处理，标记使用助播TTS，继续后续处理
            if data_type in ["schedule", "idle_time_task"]:
                assistant_anchor_config = My_handle.config.get("assistant_anchor")
                # 检查助播是否启用，并且任务类型在助播处理类型列表中
                if assistant_anchor_config and assistant_anchor_config.get("enable") and data_type in assistant_anchor_config.get("type", []):
                    # 标记使用助播TTS，让后续处理使用助播TTS
                    data["_use_assistant_anchor_tts"] = True
                    logger.info(f"{data_type}标记使用助播TTS，继续全局处理")
                    logger.debug(f"{data_type}数据更新后: {data}")
                    return False, None, True  # 未处理，继续全局处理，但使用助播TTS
            
            # 4、其他类型，如果配置了助播处理，继续后续处理但不标记为助播TTS
            if data_type in self.supported_types:
                # 这里可以根据需要添加其他类型的处理逻辑
                logger.debug(f"助播支持处理{data_type}类型，但当前无特殊处理逻辑，继续全局处理")
                return False, None, True
            
            return False, None, True
            
        except Exception as e:
            logger.error(f"助播处理异常: {traceback.format_exc()}")
            return False, None, True
    
    def _process_local_qa_text(self, data, data_type, my_handle):
        """处理本地问答库文本匹配"""
        if not self.config.get("assistant_anchor", "local_qa", "text", "enable"):
            return None
            
        try:
            # 检查data是否包含content字段
            if not isinstance(data, dict) or "content" not in data:
                return None
                
            # 根据助播配置，执行不同的问答匹配算法
            assistant_qa_format = self.config.get("assistant_anchor", "local_qa", "text", "format")
            assistant_qa_file_path = self.config.get("assistant_anchor", "local_qa", "text", "file_path")
            assistant_qa_similarity = self.config.get("assistant_anchor", "local_qa", "text", "similarity")
            
            if assistant_qa_format == "text":
                tmp = my_handle.find_answer(
                    data["content"], 
                    assistant_qa_file_path, 
                    assistant_qa_similarity
                )
            else:
                tmp = my_handle.find_similar_answer(
                    data["content"], 
                    assistant_qa_file_path, 
                    assistant_qa_similarity
                )
            
            if tmp is not None:
                logger.info(f'触发助播 本地问答库-文本 [{self.username}]: {data["content"]}')
                
                # 变量替换
                variables = {
                    'cur_time': my_handle.common.get_bj_time(5),
                    'username': self.username
                }
                
                if any(var in tmp for var in variables):
                    tmp = tmp.format(**{var: value for var, value in variables.items() if var in tmp})
                
                # 括号语法随机化
                tmp = my_handle.common.brackets_text_randomize(tmp)
                
                logger.info(f"助播 本地问答库-文本回答为: {tmp}")
                
                # 记录到日志
                my_handle.write_to_comment_log(tmp, {"username": self.username, "content": data["content"]})
                
                # 创建消息
                message = {
                    "type": "assistant_anchor_text",
                    "tts_type": self.audio_synthesis_type,
                    "data": My_handle.config.get(self.audio_synthesis_type) or {},
                    "config": My_handle.config.get("filter"),
                    "username": self.username,
                    "content": tmp
                }
                
                if "insert_index" in data:
                    message["insert_index"] = data["insert_index"]
                
                return message
        
        except Exception as e:
            logger.error(f"助播本地问答库文本处理异常: {e}")
        
        return None
    
    def _process_local_qa_audio(self, data, data_type, my_handle):
        """处理本地问答库音频匹配"""
        if not self.config.get("assistant_anchor", "local_qa", "audio", "enable"):
            return None
        
        try:
            # 获取本地问答音频库文件夹内所有的音频文件名
            local_qa_audio_filename_list = my_handle.audio.get_dir_audios_filename(
                self.config.get("assistant_anchor", "local_qa", "audio", "file_path"), 
                type=1
            )
            local_qa_audio_list = my_handle.audio.get_dir_audios_filename(
                self.config.get("assistant_anchor", "local_qa", "audio", "file_path"), 
                type=0
            )
            
            local_qv_audio_filename = None
            
            if self.config.get("assistant_anchor", "local_qa", "audio", "format") == "相似度匹配":
                # 相似度匹配
                local_qv_audio_filename = my_handle.common.find_best_match(
                    data["content"], 
                    local_qa_audio_filename_list, 
                    self.config.get("assistant_anchor", "local_qa", "audio", "similarity")
                )
            elif self.config.get("assistant_anchor", "local_qa", "audio", "format") == "包含关系":
                # 包含关系匹配 - 检查音频文件名是否包含在用户输入中
                local_qv_audio_filename = None
                for filename in local_qa_audio_filename_list:
                    if filename in data["content"]:
                        local_qv_audio_filename = filename
                        break
            
            # 找到了匹配的结果
            if local_qv_audio_filename is not None:
                logger.info(f'触发 助播 本地问答库-语音 [{self.username}]: {data["content"]}')
                
                # 补上扩展名
                local_qv_audio_filename = my_handle.common.find_best_match(
                    local_qv_audio_filename, 
                    local_qa_audio_list, 
                    0
                )
                
                # 寻找对应的文件
                resp_content = my_handle.audio.search_files(
                    self.config.get("assistant_anchor", "local_qa", "audio", "file_path"), 
                    local_qv_audio_filename
                )
                
                if resp_content:
                    logger.debug(f"匹配到的音频原相对路径：{resp_content[0]}")
                    
                    # 拼接音频文件路径
                    audio_path = f'{self.config.get("assistant_anchor", "local_qa", "audio", "file_path")}/{resp_content[0]}'
                    logger.info(f"匹配到的音频路径：{audio_path}")
                    
                    # 助播本地问答音频由助播流程处理，不需要经过metahuman_stream
                    message = {
                        "type": "assistant_anchor_audio",
                        "tts_type": self.audio_synthesis_type,
                        "data": My_handle.config.get(self.audio_synthesis_type) or {},
                        "config": My_handle.config.get("filter"),
                        "username": self.username,
                        "content": data["content"],
                        "file_path": audio_path
                    }
                    
                    if "insert_index" in data:
                        message["insert_index"] = data["insert_index"]
                    
                    return message
        
        except Exception as e:
            logger.error(f"助播本地问答库音频处理异常: {e}")
        
        return None
    
    def _process_specific_type(self, data, data_type, my_handle):
        """处理特定类型（入场、礼物、关注等）"""
        if data_type not in ["entrance", "gift", "follow", "schedule", "integral"]:
            return None
        
        try:
            if data_type == "entrance" and self.config.get("thanks", "entrance_enable"):
                # 直接调用统一的entrance_handle方法，避免重复逻辑
                return my_handle.entrance_handle(data)
            elif data_type == "gift" and self.config.get("thanks", "gift_enable"):
                return self._process_gift(data, my_handle)
            elif data_type == "follow" and self.config.get("thanks", "follow_enable"):
                return self._process_follow(data, my_handle)
        
        except Exception as e:
            logger.error(f"助播特定类型处理异常: {e}")
        
        return None
    
    # _process_entrance方法已删除，统一使用entrance_handle方法处理入场逻辑
    
    def _process_gift(self, data, my_handle):
        """处理礼物感谢"""
        try:
            if self.config.get("thanks", "gift_random"):
                resp_content = random.choice(self.config.get("thanks", "gift_copy")).format(
                    username=data["username"], 
                    gift_name=data.get("gift_name", ""), 
                    price=data.get("price", 0)
                )
            else:
                if len(my_handle.thanks_gift_copy) == 0:
                    if len(self.config.get("thanks", "gift_copy")) == 0:
                        logger.warning("礼物文案为空，跳过处理")
                        return None
                    my_handle.thanks_gift_copy = copy.copy(self.config.get("thanks", "gift_copy"))
                resp_content = my_handle.thanks_gift_copy.pop(0).format(
                    username=data["username"], 
                    gift_name=data.get("gift_name", ""), 
                    price=data.get("price", 0)
                )
            
            resp_content = my_handle.common.brackets_text_randomize(resp_content)
            
            message = {
                "type": "assistant_anchor_gift",
                "tts_type": self.audio_synthesis_type,
                "data": My_handle.config.get(self.audio_synthesis_type) or {},
                "config": My_handle.config.get("filter"),
                "username": data["username"],
                "content": resp_content
            }
            
            return message
        
        except Exception as e:
            logger.error(f"助播礼物处理异常: {e}")
            return None
    
    def _process_follow(self, data, my_handle):
        """处理关注感谢"""
        try:
            if self.config.get("thanks", "follow_enable"):
                if self.config.get("thanks", "follow_random"):
                    resp_content = random.choice(self.config.get("thanks", "follow_copy")).format(username=data["username"])
                else:
                    if len(my_handle.thanks_follow_copy) == 0:
                        if len(self.config.get("thanks", "follow_copy")) == 0:
                            logger.warning("关注文案为空，跳过处理")
                            return None
                        my_handle.thanks_follow_copy = copy.copy(self.config.get("thanks", "follow_copy"))
                    resp_content = my_handle.thanks_follow_copy.pop(0).format(username=data["username"])
                
                resp_content = my_handle.common.brackets_text_randomize(resp_content)
                
                message = {
                    "type": "assistant_anchor_follow",
                    "tts_type": self.audio_synthesis_type,
                    "data": My_handle.config.get(self.audio_synthesis_type) or {},
                    "config": My_handle.config.get("filter"),
                    "username": data["username"],
                    "content": resp_content
                }
                
                return message
        
        except Exception as e:
            logger.error(f"助播关注处理异常: {e}")
            return None


    def _create_read_comment_message(self, data):
        """创建念弹幕消息"""
        # 确保念弹幕信息包含完整的用户名和内容格式
        username = data.get("username", "未知用户")
        content = data.get("content", "")
        
        # 构建完整的念弹幕内容：用户名说:内容
        full_content = f"{username}说:{content}"
        
        return {
            "type": "assistant_anchor_read_comment",
            "tts_type": self.audio_synthesis_type,
            "data": My_handle.config.get(self.audio_synthesis_type) or {},
            "config": My_handle.config.get("filter"),
            "username": username,
            "content": full_content
        }

    def enqueue_message(self, message):
        """将消息放入队列"""
        try:
            # 使用 run_coroutine_threadsafe 将协程安全地提交到事件循环
            asyncio.run_coroutine_threadsafe(assistant_anchor_queue.put(message), My_handle.loop)
            logger.info(f"助播消息已入队: {message['type']}")
        except Exception as e:
            logger.error(f"助播消息入队失败: {e}")

    
    def create_audio_message(self, data, message_type, content, username=None):
        """创建音频合成消息"""
        if username is None:
            username = data.get("username", self.username)
        
        message = {
            "type": message_type,
            "tts_type": self.audio_synthesis_type,
            "data": My_handle.config.get(self.audio_synthesis_type) or {},
            "config": My_handle.config.get("filter"),
            "username": username,
            "content": content
        }
        
        # 复制其他可能需要的字段
        for key in ["insert_index", "file_path", "gift_info"]:
            if key in data:
                message[key] = data[key]
        
        return message


"""
	___ _                       
	|_ _| | ____ _ _ __ ___  ___ 
	 | || |/ / _` | '__/ _ \/ __|
	 | ||   < (_| | | | (_) \__ \
	|___|_|\_\__,_|_|  \___/|___/

"""
class SingletonMeta(type):
    _instances = {}
    _lock = threading.Lock()

    def __call__(cls, *args, **kwargs):
        with cls._lock:
            if cls not in cls._instances:
                cls._instances[cls] = super(SingletonMeta, cls).__call__(*args, **kwargs)
            return cls._instances[cls]


class My_handle(metaclass=SingletonMeta):
    common = None
    config = None
    audio = None
    my_translate = None
    
    # 是否在数据处理中
    is_handleing = 0
    
    # 全局关闭标志 - 用于优雅关闭所有定时器和异步任务
    should_shutdown = False

    # 异常报警数据
    abnormal_alarm_data = {
        "platform": {
            "error_count": 0
        },
        "llm": {
            "error_count": 0
        },
        "tts": {
            "error_count": 0
        },
        "svc": {
            "error_count": 0
        },
        "visual_body": {
            "error_count": 0
        },
        "other": {
            "error_count": 0
        }
    }

    # 直播消息存储(入场、礼物、弹幕)，用于限定时间内的去重
    live_data = {
        "comment": [],
        "gift": [],
        "entrance": [],
    }

    # 各个任务运行数据缓存 暂时用于 限定任务周期性触发
    task_data = {
        "read_comment": {
            "data": [],
            "time": 0
        },
        "local_qa": {
            "data": [],
            "time": 0
        },
        "thanks": {
            "gift": {
                "data": [],
                "time": 0
            },
            "entrance": {
                "data": [],
                "time": 0
            },
            "follow": {
                "data": [],
                "time": 0
            },
        }
    }

    # 答谢板块文案数据临时存储
    thanks_entrance_copy = []
    thanks_gift_copy = []
    thanks_follow_copy = []

    def __init__(self, config_path):
        logger.info("初始化My_handle...")

        try:
            if My_handle.common is None:
                My_handle.common = Common()
            if My_handle.config is None:
                My_handle.config = Config(config_path)
            if My_handle.audio is None:
                try:
                    My_handle.audio = Audio(config_path)
                except Exception as e:
                    logger.error(f"Audio初始化失败: {e}")
                    logger.error(traceback.format_exc())
                    My_handle.audio = None
            if My_handle.my_translate is None:
                My_handle.my_translate = My_Translate(config_path)

            self.proxy = None
            # self.proxy = {
            #     "http": "http://127.0.0.1:10809",
            #     "https": "http://127.0.0.1:10809"
            # }
            
            # 数据丢弃部分相关的实现
            self.data_lock = threading.Lock()
            self.timers = {}

            self.db = None

            # 设置会话初始值
            self.session_config = None
            self.sessions = {}
            self.current_key_index = 0

            # 点歌模块
            self.choose_song_song_lists = None

            """
            新增LLM后，这边先定义下各个变量，下面会用到
            """
            self.chatgpt = None
            self.chat_with_file = None
            self.text_generation_webui = None
            self.sparkdesk = None
            self.langchain_chatchat = None
            self.zhipu = None
            self.bard_api = None
            self.tongyi = None
            self.tongyixingchen = None
            self.my_wenxinworkshop = None
            self.gemini = None
            self.koboldcpp = None
            self.anythingllm = None
            self.gpt4free = None
            self.custom_llm = None
            self.llm_tpu = None
            self.dify = None
            self.volcengine = None

            self.image_recognition_model = None

            self.chat_type_list = ["chatgpt", "chat_with_file", "text_generation_webui", \
                    "sparkdesk",  "langchain_chatchat", "zhipu", "bard", "tongyi", \
                    "tongyixingchen", "my_wenxinworkshop", "gemini", "koboldcpp", "anythingllm", "gpt4free", \
                    "custom_llm", "llm_tpu", "dify", "volcengine", "chatterbot"]

            # 配置加载
            self.config_load()

            logger.info(f"配置数据加载成功。")

            # 初始化助播管理器
            self.assistant_anchor_manager = AssistantAnchorManager(My_handle.config)


            # 初始化多平台组件
            self.__init_multi_platform_components()

            # 确保Audio.should_shutdown状态正确，防止Edge TTS被错误阻塞
            try:
                if not hasattr(Audio, 'should_shutdown'):
                    Audio.should_shutdown = False
                    logger.debug("My_handle初始化时设置Audio.should_shutdown为False")
                elif Audio.should_shutdown:
                    logger.warning("My_handle初始化时发现Audio.should_shutdown为True，重置为False")
                    Audio.should_shutdown = False
                else:
                    logger.debug("My_handle初始化时Audio.should_shutdown状态正常")
            except Exception as e:
                logger.warning(f"My_handle初始化时无法访问Audio.should_shutdown: {e}")

            # 初始化消息去重缓存
            self.message_dedup_cache = {}
            self.message_dedup_timeout = 30  # 30秒内的重复消息将被过滤
            
            # 启动定时器
            self.start_timers()
            
            # 启动助播队列处理任务
            self._start_assistant_anchor_queue_processor()
        except Exception as e:
            logger.error(traceback.format_exc())     

    def _start_assistant_anchor_queue_processor(self):
        """启动助播队列处理任务"""
        try:
            # 检查是否已有事件循环在运行
            try:
                loop = asyncio.get_running_loop()
                # 如果有运行中的事件循环，使用create_task
                loop.create_task(process_assistant_anchor_queue())
                logger.info("助播队列处理任务已在现有事件循环中启动")
            except RuntimeError:
                # 没有运行中的事件循环，在新线程中启动
                def run_queue_processor():
                    try:
                        asyncio.run(process_assistant_anchor_queue())
                    except Exception as e:
                        logger.error(f"助播队列处理任务异常: {e}")
                        logger.error(traceback.format_exc())
                
                queue_thread = threading.Thread(target=run_queue_processor, daemon=True)
                queue_thread.start()
                logger.info("助播队列处理任务已在新线程中启动")
        except Exception as e:
            logger.error(f"启动助播队列处理任务失败: {e}")
            logger.error(traceback.format_exc())

    # 清空 待合成消息队列|待播放音频队列
    def clear_queue(self, type: str="message_queue"):
        """清空 待合成消息队列|待播放音频队列

        Args:
            type (str, optional): 队列类型. Defaults to "message_queue".

        Returns:
            bool: 清空结果
        """
        try:
            if My_handle.audio is None:
                logger.warning("Audio对象未初始化，无法清空队列")
                return False
            return My_handle.audio.clear_queue(type)
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f"清空{type}队列失败：{e}")
            return False
        
    # 停止音频播放
    def stop_audio(self, type: str="pygame", mixer_normal: bool=True, mixer_copywriting: bool=True):
        try:
            return My_handle.audio.stop_audio(type, mixer_normal, mixer_copywriting)
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f"停止音频播放失败：{e}")
            return False

    # 周期性触发数据处理，每秒执行一次，进行计时
    def periodic_trigger_data_handle(self):
        def get_last_n_items(data_list: list, num: int):
            # 返回最后的 n 个元素，如果不足 n 个则返回实际元素个数
            return data_list[-num:] if num > 0 else []
        
        
        # 安全地检查read_comment配置
        read_comment_config = My_handle.config.get("read_comment")
        if read_comment_config and read_comment_config.get("periodic_trigger", {}).get("enable"):
            type = "read_comment"
            # 计时+1
            My_handle.task_data[type]["time"] += 1
            
            periodic_trigger_config = read_comment_config.get("periodic_trigger", {})
            periodic_time_min = int(periodic_trigger_config.get("periodic_time_min", 20))
            periodic_time_max = int(periodic_trigger_config.get("periodic_time_max", 40))
            # 生成触发周期值
            periodic_time = random.randint(periodic_time_min, periodic_time_max)
            logger.debug(f"type={type}, periodic_time={periodic_time}, My_handle.task_data={My_handle.task_data}")

            # 计时时间是否超过限定的触发周期
            if My_handle.task_data[type]["time"] >= periodic_time:
                # 计时清零
                My_handle.task_data[type]["time"] = 0

                trigger_num_min = int(periodic_trigger_config.get("trigger_num_min", 1))
                trigger_num_max = int(periodic_trigger_config.get("trigger_num_max", 2))
                # 生成触发个数
                trigger_num = random.randint(trigger_num_min, trigger_num_max)
                # 获取数据
                data_list = get_last_n_items(My_handle.task_data[type]["data"], trigger_num)
                logger.debug(f"type={type}, trigger_num={trigger_num}")

                if data_list != []:
                    # 遍历数据 进行webui数据回传 和 音频合成播放
                    for data in data_list:
                        self.audio_synthesis_handle(data)

                # 数据清空
                My_handle.task_data[type]["data"] = []
        

        # 安全地检查local_qa配置
        local_qa_config = My_handle.config.get("local_qa")
        if local_qa_config and local_qa_config.get("periodic_trigger", {}).get("enable"):
            type = "local_qa"
            # 计时+1
            My_handle.task_data[type]["time"] += 1
            
            periodic_trigger_config = local_qa_config.get("periodic_trigger", {})
            periodic_time_min = int(periodic_trigger_config.get("periodic_time_min", 20))
            periodic_time_max = int(periodic_trigger_config.get("periodic_time_max", 40))
            # 生成触发周期值
            periodic_time = random.randint(periodic_time_min, periodic_time_max)
            logger.debug(f"type={type}, periodic_time={periodic_time}, My_handle.task_data={My_handle.task_data}")

            # 计时时间是否超过限定的触发周期
            if My_handle.task_data[type]["time"] >= periodic_time:
                # 计时清零
                My_handle.task_data[type]["time"] = 0

                trigger_num_min = int(periodic_trigger_config.get("trigger_num_min", 1))
                trigger_num_max = int(periodic_trigger_config.get("trigger_num_max", 2))
                # 生成触发个数
                trigger_num = random.randint(trigger_num_min, trigger_num_max)
                # 获取数据
                data_list = get_last_n_items(My_handle.task_data[type]["data"], trigger_num)
                logger.debug(f"type={type}, trigger_num={trigger_num}")

                if data_list != []:
                    # 遍历数据 进行webui数据回传 和 音频合成播放
                    for data in data_list:
                        if data["type"] == "local_qa_audio":
                            self.webui_show_chat_log_callback("本地问答-音频", data, data["file_path"])
                        else:
                            self.webui_show_chat_log_callback("本地问答-文本", data, data["content"])

                        self.audio_synthesis_handle(data)

                # 数据清空
                My_handle.task_data[type]["data"] = []
        
        # 安全地检查thanks.gift配置
        thanks_config = My_handle.config.get("thanks")
        if thanks_config and thanks_config.get("gift", {}).get("periodic_trigger", {}).get("enable"):
            type = "thanks"
            type2 = "gift"

            # 计时+1
            My_handle.task_data[type][type2]["time"] += 1

            periodic_trigger_config = thanks_config.get("gift", {}).get("periodic_trigger", {})
            periodic_time_min = int(periodic_trigger_config.get("periodic_time_min", 20))
            periodic_time_max = int(periodic_trigger_config.get("periodic_time_max", 40))
            # 生成触发周期值
            periodic_time = random.randint(periodic_time_min, periodic_time_max)
            logger.debug(f"type={type}, periodic_time={periodic_time}, My_handle.task_data={My_handle.task_data}")

            # 计时时间是否超过限定的触发周期
            if My_handle.task_data[type][type2]["time"] >= periodic_time:
                # 计时清零
                My_handle.task_data[type][type2]["time"] = 0

                trigger_num_min = int(periodic_trigger_config.get("trigger_num_min", 1))
                trigger_num_max = int(periodic_trigger_config.get("trigger_num_max", 2))
                # 生成触发个数
                trigger_num = random.randint(trigger_num_min, trigger_num_max)
                # 获取数据
                data_list = get_last_n_items(My_handle.task_data[type][type2]["data"], trigger_num)
                logger.debug(f"type={type}, trigger_num={trigger_num}")

                if data_list != []:
                    # 遍历数据 进行webui数据回传 和 音频合成播放
                    for data in data_list:
                        self.audio_synthesis_handle(data)

                # 数据清空
                My_handle.task_data[type][type2]["data"] = []
        
        # 安全地检查thanks.entrance配置
        if thanks_config and thanks_config.get("entrance", {}).get("periodic_trigger", {}).get("enable"):
            type = "thanks"
            type2 = "entrance"

            # 计时+1
            My_handle.task_data[type][type2]["time"] += 1

            periodic_trigger_config = thanks_config.get("entrance", {}).get("periodic_trigger", {})
            periodic_time_min = int(periodic_trigger_config.get("periodic_time_min", 20))
            periodic_time_max = int(periodic_trigger_config.get("periodic_time_max", 40))
            # 生成触发周期值
            periodic_time = random.randint(periodic_time_min, periodic_time_max)
            logger.debug(f"type={type}, periodic_time={periodic_time}, My_handle.task_data={My_handle.task_data}")

            # 计时时间是否超过限定的触发周期
            if My_handle.task_data[type][type2]["time"] >= periodic_time:
                # 计时清零
                My_handle.task_data[type][type2]["time"] = 0

                trigger_num_min = int(periodic_trigger_config.get("trigger_num_min", 1))
                trigger_num_max = int(periodic_trigger_config.get("trigger_num_max", 2))
                # 生成触发个数
                trigger_num = random.randint(trigger_num_min, trigger_num_max)
                # 获取数据
                data_list = get_last_n_items(My_handle.task_data[type][type2]["data"], trigger_num)
                logger.debug(f"type={type}, trigger_num={trigger_num}")

                if data_list != []:
                    # 遍历数据 进行webui数据回传 和 音频合成播放
                    for data in data_list:
                        self.audio_synthesis_handle(data)

                # 数据清空
                My_handle.task_data[type][type2]["data"] = []

        # 安全地检查thanks.follow配置
        if thanks_config and thanks_config.get("follow", {}).get("periodic_trigger", {}).get("enable"):
            type = "thanks"
            type2 = "follow"

            # 计时+1
            My_handle.task_data[type][type2]["time"] += 1

            periodic_trigger_config = thanks_config.get("follow", {}).get("periodic_trigger", {})
            periodic_time_min = int(periodic_trigger_config.get("periodic_time_min", 20))
            periodic_time_max = int(periodic_trigger_config.get("periodic_time_max", 40))
            # 生成触发周期值
            periodic_time = random.randint(periodic_time_min, periodic_time_max)
            logger.debug(f"type={type}, periodic_time={periodic_time}, My_handle.task_data={My_handle.task_data}")

            # 计时时间是否超过限定的触发周期
            if My_handle.task_data[type][type2]["time"] >= periodic_time:
                # 计时清零
                My_handle.task_data[type][type2]["time"] = 0

                trigger_num_min = int(periodic_trigger_config.get("trigger_num_min", 1))
                trigger_num_max = int(periodic_trigger_config.get("trigger_num_max", 2))
                # 生成触发个数
                trigger_num = random.randint(trigger_num_min, trigger_num_max)
                # 获取数据
                data_list = get_last_n_items(My_handle.task_data[type][type2]["data"], trigger_num)
                logger.debug(f"type={type}, trigger_num={trigger_num}")

                if data_list != []:
                    # 遍历数据 进行webui数据回传 和 音频合成播放
                    for data in data_list:
                        self.audio_synthesis_handle(data)

                # 数据清空
                My_handle.task_data[type][type2]["data"] = []


        self.periodic_trigger_timer = threading.Timer(1, partial(self.periodic_trigger_data_handle))
        self.periodic_trigger_timer.start()

    # 清空live_data直播数据
    def clear_live_data(self, type: str=""):
        if type != "" and type is not None:
            My_handle.live_data[type] = []

        if type == "comment":
            self.comment_check_timer = threading.Timer(int(My_handle.config.get("filter", "limited_time_deduplication", "comment")), partial(self.clear_live_data, "comment"))
            self.comment_check_timer.start()
        elif type == "gift":
            self.gift_check_timer = threading.Timer(int(My_handle.config.get("filter", "limited_time_deduplication", "gift")), partial(self.clear_live_data, "gift"))
            self.gift_check_timer.start()
        elif type == "entrance":
            self.entrance_check_timer = threading.Timer(int(My_handle.config.get("filter", "limited_time_deduplication", "entrance")), partial(self.clear_live_data, "entrance"))
            self.entrance_check_timer.start()

    # 启动定时器
    def start_timers(self):
        
        if My_handle.config.get("filter", "limited_time_deduplication", "enable"):

            # 设置定时器，每隔n秒执行一次
            self.comment_check_timer = threading.Timer(int(My_handle.config.get("filter", "limited_time_deduplication", "comment")), partial(self.clear_live_data, "comment"))
            self.comment_check_timer.start()

            self.gift_check_timer = threading.Timer(int(My_handle.config.get("filter", "limited_time_deduplication", "gift")), partial(self.clear_live_data, "gift"))
            self.gift_check_timer.start()

            self.entrance_check_timer = threading.Timer(int(My_handle.config.get("filter", "limited_time_deduplication", "entrance")), partial(self.clear_live_data, "entrance"))
            self.entrance_check_timer.start()

            logger.info("启动 限定时间直播数据去重 定时器")

        self.periodic_trigger_timer = threading.Timer(1, partial(self.periodic_trigger_data_handle))
        self.periodic_trigger_timer.start()
        logger.info("启动 周期性触发 定时器")
        

    # 是否位于数据处理状态
    def is_handle_empty(self):
        return My_handle.is_handleing


    # 音频队列、播放相关情况
    def is_audio_queue_empty(self):
        if My_handle.audio is None:
            logger.warning("Audio对象未初始化，返回True")
            return True
        return My_handle.audio.is_audio_queue_empty()

    # 判断 等待合成消息队列|待播放音频队列 数是否小于或大于某个值，就返回True
    def is_queue_less_or_greater_than(self, type: str="message", less: int=None, greater: int=None):
        """判断 等待合成消息队列|待播放音频队列 数是否小于或大于某个值

        Args:
            type (str, optional): _description_. Defaults to "message_queue" | voice_tmp_path_queue.
            less (int, optional): _description_. Defaults to None.
            greater (int, optional): _description_. Defaults to None.

        Returns:
            bool: 是否小于或大于某个值
        """
        if My_handle.audio is None:
            logger.warning("Audio对象未初始化，返回False")
            return False
        return My_handle.audio.is_queue_less_or_greater_than(type, less, greater)

    # 获取音频类信息
    def get_audio_info(self):
        if My_handle.audio is None:
            logger.warning("Audio对象未初始化，返回空字典")
            return {}
        return My_handle.audio.get_audio_info()

    def get_chat_model(self, chat_type, config):
        if chat_type in ["chatterbot", "chat_with_file"]:
            # 对这些类型做特殊处理
            if chat_type == "chatterbot":
                # chatterbot需要初始化配置
                GPT_MODEL.set_model_config(chat_type, config.get(chat_type, {}))
            else:
                GPT_MODEL.set_model_config(chat_type, config.get(chat_type))
        else:
            GPT_MODEL.set_model_config(chat_type, config.get(chat_type))
        
        # 获取模型实例
        model_instance = GPT_MODEL.get(chat_type)
        self.__dict__[chat_type] = model_instance
        
        # 特殊处理：如果chatterbot实例为None，记录警告
        if chat_type == "chatterbot" and model_instance is None:
            logger.warning("Chatterbot实例初始化失败，请检查chatterbot依赖是否安装")

    def get_vision_model(self, chat_type, config):
        GPT_MODEL.set_vision_model_config(chat_type, config)
        self.image_recognition_model = GPT_MODEL.get(chat_type)

    def handle_chat_type(self):
        chat_type = My_handle.config.get("chat_type")
        self.get_chat_model(chat_type, My_handle.config)
        # 其他类型特殊处理
        if chat_type == "chat_with_file":
            from utils.chat_with_file.chat_with_file import Chat_with_file
            self.chat_with_file = Chat_with_file(My_handle.config.get("chat_with_file"))
        elif chat_type == "game":
            self.game = importlib.import_module("game." + My_handle.config.get("game", "module_name"))

    # 配置加载
    def config_load(self):
        self.session_config = {'msg': [{"role": "system", "content": My_handle.config.get('chatgpt', 'preset')}]}

        # 设置GPT_Model全局模型列表
        GPT_MODEL.set_model_config("openai", My_handle.config.get("openai"))
        GPT_MODEL.set_model_config("chatgpt", My_handle.config.get("chatgpt"))

        # 聊天相关类实例化
        self.handle_chat_type()

        # 判断是否使能了SD
        if My_handle.config.get("sd")["enable"]:
            from utils.sd import SD

            self.sd = SD(My_handle.config.get("sd"))
        # 特殊：在SD没有使能情况下，判断图片映射是否使能
        elif My_handle.config.get("key_mapping", "img_path_trigger_type") != "不启用":
            # 沿用SD的虚拟摄像头来展示图片
            from utils.sd import SD

            self.sd = SD({"enable": False, "visual_camera": My_handle.config.get("sd", "visual_camera")})

        # 日志文件路径
        self.log_file_path = "./log/log-" + My_handle.common.get_bj_time(1) + ".txt"
        if os.path.isfile(self.log_file_path):
            logger.info(f'{self.log_file_path} 日志文件已存在，跳过')
        else:
            with open(self.log_file_path, 'w') as f:
                f.write('')
                logger.info(f'{self.log_file_path} 日志文件已创建')

        # 生成弹幕文件
        self.comment_file_path = "./log/comment-" + My_handle.common.get_bj_time(1) + ".txt"
        if os.path.isfile(self.comment_file_path):
            logger.info(f'{self.comment_file_path} 弹幕文件已存在，跳过')
        else:
            with open(self.comment_file_path, 'w') as f:
                f.write('')
                logger.info(f'{self.comment_file_path} 弹幕文件已创建')

        """                                                                                                                
                                                                                                                                        
            .............  '>)xcn)I                                                                                 
            }}}}}}}}}}}}](v0kaaakad\..                                                                              
            ++++++~~++<_xpahhhZ0phah>                                                                               
            _________+(OhhkamuCbkkkh+                                                                               
            ?????????nbhkhkn|makkkhQ^                                                                               
            [[[[[[[}UhkbhZ]fbhkkkhb<                                                                                
            1{1{1{1ChkkaXicohkkkhk]                                                                                 
            ))))))JhkkhrICakkkkap-                                                                                  
            \\\\|ckkkat;0akkkka0>                                                                                   
            ttt/fpkka/;Oakhhaku"                                                                                    
            jjjjUmkau^QabwQX\< '!<++~>iI       .;>++++<>I'     :+}}{?;                                              
            xxxcpdkO"capmmZ/^ +Y-;,,;-Lf     ItX/+l:",;>1cx>  .`"x#d>`        .`.                                   
            uuvqwkh+1ahaaL_  'Zq;     ;~   '/bQ!         "uhc: . 1oZ'         "vj.     ^'                           
            ccc0kaz!kawX}'   .\hbv?:      .jop;           .C*L^  )oO`        .':I^. ."_L!^^.    ':;,'               
            XXXXph_cU_"        >rZhbC\!   "qaC...          faa~  )oO`        ;-jqj .l[mb1]_'  ^(|}\Ow{              
            XXXz00i+             '!1Ukkc, 'JoZ` .          uop;  )oO'          >ou   .Lp"  . ,0j^^>Yvi              
            XXXzLn. .        ^>      lC#(  lLot.          _kq- . 1o0'          >on   .Qp,    }*|><i^  .             
            YYYXQ|           ,O]^.   "XQI . `10c~^.    '!t0f:   .t*q;....'l1. ._#c.. .Qkl`I_"Iw0~"`,<|i.            
            (|((f1           ^t1]++-}(?`      '>}}}/rrx1]~^    ^?jvv/]--]{r) .i{x/+;  ]Xr1_;. :(vnrj\i.             
                '1..             .''.   .         .Itq*Z}`             ..                                           
                 +; .                                "}XmQf-i!;.                                                    
                  .                                     ';><iI"                                                     
                                                                                                                                        
                                                                                                                                                                                                                                                     
        """
        try:
            # 数据库
            self.db = SQLiteDB(My_handle.config.get("database", "path"))
            logger.info(f'创建数据库:{My_handle.config.get("database", "path")}')

            # 创建弹幕表
            create_table_sql = '''
            CREATE TABLE IF NOT EXISTS danmu (
                username TEXT NOT NULL,
                content TEXT NOT NULL,
                ts DATETIME NOT NULL
            )
            '''
            self.db.execute(create_table_sql)
            logger.debug('创建danmu（弹幕）表')

            create_table_sql = '''
            CREATE TABLE IF NOT EXISTS entrance (
                username TEXT NOT NULL,
                ts DATETIME NOT NULL
            )
            '''
            self.db.execute(create_table_sql)
            logger.debug('创建entrance（入场）表')

            create_table_sql = '''
            CREATE TABLE IF NOT EXISTS gift (
                username TEXT NOT NULL,
                gift_name TEXT NOT NULL,
                gift_num INT NOT NULL,
                unit_price REAL NOT NULL,
                total_price REAL NOT NULL,
                ts DATETIME NOT NULL
            )
            '''
            self.db.execute(create_table_sql)
            logger.debug('创建gift（礼物）表')

            create_table_sql = '''
            CREATE TABLE IF NOT EXISTS integral (
                platform TEXT NOT NULL,
                username TEXT NOT NULL,
                uid TEXT NOT NULL,
                integral INT NOT NULL,
                view_num INT NOT NULL,
                sign_num INT NOT NULL,
                last_sign_ts DATETIME NOT NULL,
                total_price INT NOT NULL,
                last_ts DATETIME NOT NULL
            )
            '''
            self.db.execute(create_table_sql)
            logger.debug('创建integral（积分）表')
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f'数据库 {My_handle.config.get("database", "path")} 创建失败，请查看日志排查问题！！！')

        # 初始化弹幕WebSocket服务器
        try:
            danmaku_ws_config = My_handle.config.get("danmaku_websocket", {})
            if danmaku_ws_config.get("enabled", False):
                self.danmaku_websocket_server = get_danmaku_websocket_server()
                # 设置消息处理器
                self.danmaku_websocket_server.set_message_handler(self.handle_danmaku_websocket_message)
                logger.info("弹幕WebSocket服务器初始化完成")
                # 标记需要启动WebSocket服务器
                self._need_start_websocket_server = True
            else:
                self.danmaku_websocket_server = None
                logger.info("弹幕WebSocket服务器未启用")
        except Exception as e:
            logger.error(f"弹幕WebSocket服务器初始化失败: {e}")
            self.danmaku_websocket_server = None


    # 重载config
    def reload_config(self, config_path):
        My_handle.config = Config(config_path)
        My_handle.audio.reload_config(config_path)
        My_handle.my_translate.reload_config(config_path)

        self.config_load()


    # 回传给webui，用于聊天内容显示
    def webui_show_chat_log_callback(self, data_type: str, data: dict, resp_content: str):
        """回传给webui，用于聊天内容显示

        Args:
            data_type (str): 数据内容的类型（多指LLM）
            data (dict): 数据JSON
            resp_content (str): 显示的聊天内容的文本
        """
        try:
            if My_handle.config.get("talk", "show_chat_log") == True: 
                if "ori_username" not in data:
                    data["ori_username"] = data["username"]
                if "ori_content" not in data:
                    data["ori_content"] = data["content"]
                    
                # 返回给webui的数据
                return_webui_json = {
                    "type": "llm",
                    "data": {
                        "type": data_type,
                        "username": data["ori_username"], 
                        "content_type": "answer",
                        "content": f"错误：{data_type}无返回，请查看日志" if resp_content is None else resp_content,
                        "timestamp": My_handle.common.get_bj_time(0)
                    }
                }

                webui_ip = "127.0.0.1" if My_handle.config.get("webui", "ip") == "0.0.0.0" else My_handle.config.get("webui", "ip")
                tmp_json = My_handle.common.send_request(f'http://{webui_ip}:{My_handle.config.get("webui", "port")}/callback', "POST", return_webui_json, timeout=30)
        except Exception as e:
            logger.error(traceback.format_exc())

    # 获取房间号
    def get_room_id(self):
        return My_handle.config.get("room_display_id")


    # 音频合成处理
    def audio_synthesis_handle(self, data_json):
        """音频合成处理

        Args:
            data_json (dict): 传递的json数据

            核心参数:
            type目前有
                reread_top_priority 最高优先级-复读
                talk 聊天（语音输入）
                comment 弹幕
                local_qa_text 本地问答文本
                local_qa_audio 本地问答音频
                song 歌曲
                reread 复读
                key_mapping 按键映射
                key_mapping_copywriting 按键映射-文案
                integral 积分
                read_comment 念弹幕
                gift 礼物
                entrance 用户入场
                follow 用户关注
                schedule 定时任务
                idle_time_task 闲时任务
                abnormal_alarm 异常报警
                image_recognition_schedule 图像识别定时任务

        """
        logger.debug(f"audio_synthesis_handle开始处理消息: {data_json.get('type', 'unknown')} - {data_json.get('content', '')}")
        logger.debug(f"消息完整数据: {data_json}")

        if "content" in data_json:
            if data_json['content']:
                # 替换文本内容中\n为空
                data_json['content'] = data_json['content'].replace('\n', '')

        # 如果虚拟身体-Unity，则发送数据到中转站
        if My_handle.config.get("visual_body") == "unity":
            # 判断 'config' 是否存在于字典中
            if 'config' in data_json:
                # 删除 'config' 对应的键值对
                data_json.pop('config')

            data_json["password"] = My_handle.config.get("unity", "password")

            resp_json = My_handle.common.send_request(My_handle.config.get("unity", "api_ip_port"), "POST", data_json)
            if resp_json:
                if resp_json["code"] == 200:
                    logger.info("请求unity中转站成功")
                else:
                    logger.info(f"请求unity中转站出错，{resp_json['message']}")
            else:
                logger.error("请求unity中转站失败")
        else:
            # 所有消息都通过消息队列处理，确保动态弹幕处理的队列长度判断有效
            logger.debug(f"将消息加入待合成消息队列: {data_json.get('type', 'unknown')} - {data_json.get('content', '')}")
            
            # 根据消息类型选择使用助播TTS还是全局TTS配置
            if self._is_assistant_anchor_message(data_json):
                # 助播消息，使用助播TTS配置
                logger.info(f"检测到助播消息，使用助播TTS配置: {data_json.get('type', 'unknown')}")
                logger.debug(f"助播消息TTS类型: {data_json.get('tts_type', 'unknown')}")
                data_json["is_assistant"] = True
            else:
                # 全局消息，使用全局TTS配置
                logger.debug(f"使用全局TTS配置进行音频合成: {data_json.get('type', 'unknown')}")
                data_json["is_assistant"] = False
            
            # 音频合成（edge-tts / vits_fast）并播放，通过消息队列处理
            My_handle.audio.audio_synthesis(data_json)
            
            logger.debug(f'data_json={data_json}')
    
    def _is_assistant_anchor_message(self, data_json):
        """判断是否为助播消息
        
        Args:
            data_json (dict): 消息数据
            
        Returns:
            bool: True表示助播消息，False表示全局消息
        """
        logger.debug(f"_is_assistant_anchor_message检查消息: {data_json.get('type', 'unknown')}")
        
        # 检查消息类型是否为助播相关
        message_type = data_json.get('type', '')
        if message_type.startswith('assistant_anchor_'):
            logger.debug(f"消息类型以assistant_anchor_开头，判定为助播消息: {message_type}")
            return True
        
        # 检查是否标记了使用助播TTS
        use_assistant_anchor_tts = data_json.get('_use_assistant_anchor_tts', False)
        logger.debug(f"消息_use_assistant_anchor_tts标记: {use_assistant_anchor_tts}")
        if use_assistant_anchor_tts:
            logger.debug(f"消息标记为使用助播TTS，判定为助播消息")
            return True
        
        logger.debug(f"消息未满足助播条件，判定为全局消息")
        return False

    # 从本地问答库中搜索问题的答案(文本数据是一问一答的单行格式)
    def find_answer(self, question, qa_file_path, similarity=1):
        """从本地问答库中搜索问题的答案(文本数据是一问一答的单行格式)

        Args:
            question (str): 问题文本
            qa_file_path (str): 问答库的路径
            similarity (float): 相似度

        Returns:
            str: 答案文本 或 None
        """

        with open(qa_file_path, 'r', encoding='utf-8') as file:
            lines = file.readlines()

        q_list = [lines[i].strip() for i in range(0, len(lines), 2)]
        q_to_answer_index = {q: i + 1 for i, q in enumerate(q_list)}

        q = My_handle.common.find_best_match(question, q_list, similarity)
        # print(f"q={q}")

        if q is not None:
            answer_index = q_to_answer_index.get(q)
            # print(f"answer_index={answer_index}")
            if answer_index is not None and answer_index < len(lines):
                return lines[answer_index * 2 - 1].strip()

        return None


    # 本地问答库 文本模式  根据相似度查找答案(文本数据是json格式)
    def find_similar_answer(self, input_str, qa_file_path, min_similarity=0.8):
        """本地问答库 文本模式  根据相似度查找答案(文本数据是json格式)

        Args:
            input_str (str): 输入的待查找字符串
            qa_file_path (str): 问答库的路径
            min_similarity (float, optional): 最低匹配相似度. 默认 0.8.

        Returns:
            response (str): 匹配到的结果，如果匹配不到则返回None
        """
        def load_data_from_file(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as file:
                    data = json.load(file)
                    return data
            except json.JSONDecodeError:
                logger.error(traceback.format_exc())
                logger.error(f"本地问答库 文本模式，JSON文件：{file_path}，加载失败，文件JSON格式出错，请进行修改匹配格式！")
                return None
            except FileNotFoundError:
                logger.error(traceback.format_exc())
                logger.error(f"本地问答库 文本模式，JSON文件：{file_path}不存在！")
                return None
            
        # 从文件加载数据
        data = load_data_from_file(qa_file_path)
        if data is None:
            return None

        # 存储相似度与回答的元组列表
        similarity_responses = []
        
        # 遍历json中的每个条目，找到与输入字符串相似的关键词
        for entry in data:
            for keyword in entry.get("关键词", []):
                similarity = difflib.SequenceMatcher(None, input_str, keyword).ratio()
                similarity_responses.append((similarity, entry.get("回答", [])))
        
        # 过滤相似度低于设定阈值的回答
        similarity_responses = [(similarity, response) for similarity, response in similarity_responses if similarity >= min_similarity]
        
        # 如果没有符合条件的回答，返回None
        if not similarity_responses:
            return None
        
        # 按相似度降序排序
        similarity_responses.sort(reverse=True, key=lambda x: x[0])
        
        # 获取相似度最高的回答列表
        top_response = similarity_responses[0][1]
        
        # 随机选择一个回答
        response = random.choice(top_response)
        
        return response


    # 本地问答库 处理
    def local_qa_handle(self, data):
        """本地问答库 处理

        Args:
            data (dict): 用户名 弹幕数据

        Returns:
            bool: 是否触发并处理
        """
        username = data["username"]
        content = data["content"]

        # 合并字符串末尾连续的*  主要针对获取不到用户名的情况
        username = My_handle.common.merge_consecutive_asterisks(username)

        # 最大保留的用户名长度
        username = username[:self.config.get("local_qa", "text", "username_max_len")]

        # 1、匹配本地问答库 触发后不执行后面的其他功能
        if My_handle.config.get("local_qa", "text", "enable"):
            # 根据类型，执行不同的问答匹配算法
            if My_handle.config.get("local_qa", "text", "type") == "text":
                tmp = self.find_answer(content, My_handle.config.get("local_qa", "text", "file_path"), My_handle.config.get("local_qa", "text", "similarity"))
            else:
                tmp = self.find_similar_answer(content, My_handle.config.get("local_qa", "text", "file_path"), My_handle.config.get("local_qa", "text", "similarity"))

            if tmp is not None:
                logger.info(f"触发本地问答库-文本 [{username}]: {content}")
                # 将问答库中设定的参数替换为指定内容，开发者可以自定义替换内容
                # 假设有多个未知变量，用户可以在此处定义动态变量
                variables = {
                    'cur_time': My_handle.common.get_bj_time(5),
                    'username': username
                }

                # 使用字典进行字符串替换
                if any(var in tmp for var in variables):
                    tmp = tmp.format(**{var: value for var, value in variables.items() if var in tmp})
                
                # [1|2]括号语法随机获取一个值，返回取值完成后的字符串
                tmp = My_handle.common.brackets_text_randomize(tmp)

                logger.info(f"本地问答库-文本回答为: {tmp}")

                """
                # 判断 回复模板 是否启用
                if My_handle.config.get("reply_template", "enable"):
                    # 根据模板变量关系进行回复内容的替换
                    # 假设有多个未知变量，用户可以在此处定义动态变量
                    variables = {
                        'username': data["username"][:self.config.get("reply_template", "username_max_len")],
                        'data': tmp,
                        'cur_time': My_handle.common.get_bj_time(5),
                    }

                    reply_template_copywriting = My_handle.common.get_list_random_or_default(self.config.get("reply_template", "copywriting"), "{data}")
                    # 使用字典进行字符串替换
                    if any(var in reply_template_copywriting for var in variables):
                        tmp = reply_template_copywriting.format(**{var: value for var, value in variables.items() if var in reply_template_copywriting})

                logger.debug(f"回复模板转换后: {tmp}")
                """

                resp_content = tmp
                # 将 AI 回复记录到日志文件中
                self.write_to_comment_log(resp_content, {"username": username, "content": content})
                
                # 检查是否为metahuman_stream模式
                if My_handle.config.get("visual_body") == "metahuman_stream":
                    # metahuman_stream模式下，使用全局TTS配置并标记发送给metahuman_stream
                    global_tts_type = My_handle.config.get("audio_synthesis_type")
                    global_tts_config = My_handle.config.get(global_tts_type)
                    if isinstance(global_tts_config, dict):
                        global_tts_data = global_tts_config
                    else:
                        global_tts_data = {}
                    
                    message = {
                        "type": "comment",
                        "tts_type": global_tts_type,
                        "data": global_tts_data,
                        "config": My_handle.config.get("filter"),
                        "username": username,
                        "content": resp_content,
                        "_use_metahuman_stream": True  # 标记需要发送给metahuman_stream
                    }
                    logger.info(f"本地问答库-文本 metahuman_stream模式，将发送给metahuman_stream处理")
                else:
                    # 非metahuman_stream模式，使用全局TTS配置
                    global_tts_type = My_handle.config.get("audio_synthesis_type")
                    global_tts_config = My_handle.config.get(global_tts_type)
                    if isinstance(global_tts_config, dict):
                        global_tts_data = global_tts_config
                    else:
                        global_tts_data = {}
                    
                    message = {
                        "type": "comment",
                        "tts_type": global_tts_type,
                        "data": global_tts_data,
                        "config": My_handle.config.get("filter"),
                        "username": username,
                        "content": resp_content
                    }
                    logger.debug(f"本地问答库-文本 使用全局TTS配置")

                # 洛曦 直播弹幕助手
                if My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "enable") and \
                    "comment_reply" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "type") and \
                    "消息产生时" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "trigger_position"):
                    asyncio.run(send_msg_to_live_comment_assistant(My_handle.config.get("luoxi_project", "Live_Comment_Assistant"), resp_content))

                # 是否启用了周期性触发功能，启用此功能后，数据会被缓存，之后周期到了才会触发
                if My_handle.config.get("local_qa", "periodic_trigger", "enable"):
                    My_handle.task_data["local_qa"]["data"].append(message)
                else:
                    self.webui_show_chat_log_callback("本地问答-文本", data, resp_content)
                    
                    self.audio_synthesis_handle(message)

                return True

        # 2、匹配本地问答音频库 触发后不执行后面的其他功能
        # 注意：助播优先处理已在调用处通过 assistant_anchor_handle 实现，这里不再因助播开启而跳过全局逻辑
        if My_handle.config.get("local_qa")["audio"]["enable"]:
            # 输出当前用户发送的弹幕消息
            # logger.info(f"[{username}]: {content}")
            # 获取本地问答音频库文件夹内所有的音频文件名
            local_qa_audio_filename_list = My_handle.audio.get_dir_audios_filename(My_handle.config.get("local_qa", "audio", "file_path"), type=1)
            local_qa_audio_list = My_handle.audio.get_dir_audios_filename(My_handle.config.get("local_qa", "audio", "file_path"), type=0)

            # 不含拓展名做查找
            local_qv_audio_filename = My_handle.common.find_best_match(content, local_qa_audio_filename_list, My_handle.config.get("local_qa", "audio", "similarity"))
            
            # print(f"local_qv_audio_filename={local_qv_audio_filename}")

            # 找到了匹配的结果
            if local_qv_audio_filename is not None:
                logger.info(f"触发本地问答库-语音 [{username}]: {content}")
                # 把结果从原文件名列表中在查找一遍，补上拓展名
                local_qv_audio_filename = My_handle.common.find_best_match(local_qv_audio_filename, local_qa_audio_list, 0)

                # 寻找对应的文件
                # 拼接音频文件路径
                resp_content = os.path.join(My_handle.config.get("local_qa", "audio", "file_path"), local_qv_audio_filename)
                
                # 检查文件是否存在
                if os.path.exists(resp_content):
                    logger.info(f"匹配到的音频路径：{resp_content}")
                    
                    # 全局音频直接根据visual_body决定处理方式
                    if My_handle.config.get("visual_body") == "metahuman_stream":
                        # metahuman_stream模式下使用全局TTS配置并标记发送给metahuman_stream
                        tts_type, tts_config = My_handle.config.get_safe_tts_config()
                        message = {
                            "type": "local_qa_audio",
                            "tts_type": tts_type,
                            "data": tts_config,
                            "config": My_handle.config.get("filter"),
                            "username": username,
                            "content": content,
                            "file_path": resp_content,
                            "_use_metahuman_stream": True
                        }
                        # 是否启用了周期性触发功能，启用此功能后，数据会被缓存，之后周期到了才会触发
                        if My_handle.config.get("local_qa", "periodic_trigger", "enable"):
                            My_handle.task_data["local_qa"]["data"].append(message)
                        else:
                            self.webui_show_chat_log_callback("本地问答-音频", data, resp_content)
                            self.audio.audio_synthesis_handle(message)
                    else:
                        # 非metahuman_stream模式下使用全局TTS配置
                        tts_type, tts_config = My_handle.config.get_safe_tts_config()
                        message = {
                            "type": "local_qa_audio",
                            "tts_type": tts_type,
                            "data": tts_config,
                            "config": My_handle.config.get("filter"),
                            "username": username,
                            "content": content,
                            "file_path": resp_content
                        }
                        logger.info(f"本地问答库音频 使用全局TTS配置")

                        # 是否启用了周期性触发功能，启用此功能后，数据会被缓存，之后周期到了才会触发
                        if My_handle.config.get("local_qa", "periodic_trigger", "enable"):
                            My_handle.task_data["local_qa"]["data"].append(message)
                        else:
                            self.webui_show_chat_log_callback("本地问答-音频", data, resp_content)

                            self.audio_synthesis_handle(message)

                    return True
            
        return False


    # 点歌模式 处理
    def choose_song_handle(self, data):
        """点歌模式 处理

        Args:
            data (dict): 用户名 弹幕数据

        Returns:
            bool: 是否触发并处理
        """
        username = data["username"]
        content = data["content"]

        

        # 合并字符串末尾连续的*  主要针对获取不到用户名的情况
        username = My_handle.common.merge_consecutive_asterisks(username)

        if My_handle.config.get("choose_song")["enable"] == True:
            start_cmd = My_handle.common.starts_with_any(content, My_handle.config.get("choose_song", "start_cmd"))
            stop_cmd = My_handle.common.starts_with_any(content, My_handle.config.get("choose_song", "stop_cmd"))
            random_cmd = My_handle.common.starts_with_any(content, My_handle.config.get("choose_song", "random_cmd"))

            
            # 判断随机点歌命令是否正确
            if random_cmd:
                resp_content = My_handle.common.random_search_a_audio_file(My_handle.config.get("choose_song", "song_path"))
                if resp_content is None:
                    return True
                
                logger.info(f"随机到的音频路径：{resp_content}")

                tts_type, tts_config = My_handle.config.get_safe_tts_config()
                message = {
                    "type": "song",
                    "tts_type": tts_type,
                    "data": tts_config,
                    "config": My_handle.config.get("filter"),
                    "username": username,
                    "content": resp_content
                }

                
                self.audio_synthesis_handle(message)

                self.webui_show_chat_log_callback("点歌", data, resp_content)

                return True
            # 判断点歌命令是否正确
            elif start_cmd:
                logger.info(f"[{username}]: {content}")

                # 获取本地音频文件夹内所有的音频文件名（不含拓展名）
                choose_song_song_lists = My_handle.audio.get_dir_audios_filename(My_handle.config.get("choose_song", "song_path"), 1)

                # 去除命令前缀
                content = content[len(start_cmd):]

                # 说明用户仅发送命令，没有发送歌名，说明用户不会用
                if content == "":
                    resp_content = f'点歌命令错误，命令为 {My_handle.config.get("choose_song", "start_cmd")}+歌名'
                    tts_type, tts_config = My_handle.config.get_safe_tts_config()
                    message = {
                        "type": "comment",
                        "tts_type": tts_type,
                        "data": tts_config,
                        "config": My_handle.config.get("filter"),
                        "username": username,
                        "content": resp_content
                    }

                    self.audio_synthesis_handle(message)

                    self.webui_show_chat_log_callback("点歌", data, resp_content)

                    return True

                # 判断是否有此歌曲
                song_filename = My_handle.common.find_best_match(content, choose_song_song_lists, similarity=My_handle.config.get("choose_song", "similarity"))
                if song_filename is None:
                    # resp_content = f"抱歉，我还没学会唱{content}"
                    # 根据配置的 匹配失败回复文案来进行合成
                    resp_content = My_handle.config.get("choose_song", "match_fail_copy").format(content=content)
                    logger.info(f"[AI回复{username}]：{resp_content}")

                    tts_type, tts_config = My_handle.config.get_safe_tts_config()
                    message = {
                        "type": "comment",
                        "tts_type": tts_type,
                        "data": tts_config,
                        "config": My_handle.config.get("filter"),
                        "username": username,
                        "content": resp_content
                    }

                    
                    self.audio_synthesis_handle(message)

                    self.webui_show_chat_log_callback("点歌", data, resp_content)

                    return True
                
                resp_content = My_handle.audio.search_files(My_handle.config.get('choose_song', 'song_path'), song_filename)
                if resp_content == []:
                    return True
                
                logger.debug(f"匹配到的音频原相对路径：{resp_content[0]}")

                # 拼接音频文件路径
                resp_content = f"{My_handle.config.get('choose_song', 'song_path')}/{resp_content[0]}"
                resp_content = os.path.abspath(resp_content)
                logger.info(f"点歌成功！匹配到的音频路径：{resp_content}")
                
                tts_type, tts_config = My_handle.config.get_safe_tts_config()
                message = {
                    "type": "song",
                    "tts_type": tts_type,
                    "data": tts_config,
                    "config": My_handle.config.get("filter"),
                    "username": username,
                    "content": resp_content
                }

                self.webui_show_chat_log_callback("点歌", data, resp_content)
                
                self.audio_synthesis_handle(message)

                return True
            # 判断取消点歌命令是否正确
            elif stop_cmd:
                My_handle.audio.stop_current_audio()

                return True
            

        return False


    """
    
         ]@@@@@               =@@       @@^              =@@@@@@].  .@@` ./@@@ ,@@@^                /@^                     
        @@^      @@*          =@@       @@^              =@@   ,@@\      =@@   @@^                                          
        \@@].  =@@@@@.=@@@@@` =@@@@@@@. @@^ ./@@@@\.     =@@    .@@^.@@.@@@@@@@@@@@.@@   @@^ /@@@@^ @@^ ./@@@@@]  @@/@@@@.  
          ,\@@\  @@*   .]]/@@ =@@.  =@\ @@^ @@\]]/@^     =@@     @@^.@@. =@@   @@^ .@@   @@^ @@\`   @@^ @@^   \@^ @@`  \@^  
             @@^ @@* ,@@` =@@ =@@   =@/ @@^ @@`          =@@   ./@/ .@@. =@@   @@^ .@@.  @@^   ,\@@ @@^ @@^   /@^ @@*  =@^  
       .@@@@@@/  \@@@.@@@@@@@ =@@@@@@/  @@^ .\@@@@@.     =@@@@@@/`  .@@. =@@   @@^  =@@@@@@^.@@@@@^ @@^ .\@@@@@`  @@*  =@^ 
    
    """

    # 画图模式 SD 处理
    def sd_handle(self, data):
        """画图模式 SD 处理

        Args:
            data (dict): 用户名 弹幕数据

        Returns:
            bool: 是否触发并处理
        """
        username = data["username"]
        content = data["content"]

        # 合并字符串末尾连续的*  主要针对获取不到用户名的情况
        username = My_handle.common.merge_consecutive_asterisks(username)

        if content.startswith(My_handle.config.get("sd", "trigger")):
            # 违禁检测
            content = self.prohibitions_handle(content)
            if content is None:
                return
        
            if My_handle.config.get("sd", "enable") == False:
                logger.info("您还未启用SD模式，无法使用画画功能")
                return True
            else:
                # 输出当前用户发送的弹幕消息
                logger.info(f"[{username}]: {content}")

                # 删除文本中的命令前缀
                content = content[len(My_handle.config.get("sd", "trigger")):]

                if My_handle.config.get("sd", "translate_type") != "none":
                    # 判断翻译类型 进行翻译工作
                    tmp = My_handle.my_translate.trans(content, My_handle.config.get("sd", "translate_type"))
                    if tmp:
                        content = tmp

                """
                根据聊天类型执行不同逻辑
                """ 
                chat_type = My_handle.config.get("sd", "prompt_llm", "type")
                if chat_type in self.chat_type_list:
                    content = My_handle.config.get("sd", "prompt_llm", "before_prompt") + \
                        content + My_handle.config.get("after_prompt")
                    
                    data_json = {
                        "username": username,
                        "content": content,
                        "ori_username": data["username"],
                        "ori_content": data["content"]
                    }
                    resp_content = self.llm_handle(chat_type, data_json)
                    if resp_content is not None:
                        logger.info(f"[AI回复{username}]：{resp_content}")
                    else:
                        resp_content = ""
                        logger.warning(f"警告：{chat_type}无返回")
                elif chat_type == "none" or chat_type == "reread" or chat_type == "game":
                    resp_content = content
                else:
                    resp_content = content

                logger.info(f"传给SD接口的内容：{resp_content}")

                self.sd.process_input(resp_content)
                return True
            
        return False


    # 弹幕格式检查和特殊字符替换和指定语言过滤
    def comment_check_and_replace(self, content):
        """弹幕格式检查和特殊字符替换和指定语言过滤

        Args:
            content (str): 待处理的弹幕内容

        Returns:
            str: 处理完毕后的弹幕内容/None
        """
        # 判断弹幕是否以xx起始，如果是则返回None
        if My_handle.config.get("filter", "before_filter_str") and any(
                content.startswith(prefix) for prefix in My_handle.config.get("filter", "before_filter_str")):
            return None

        # 判断弹幕是否以xx结尾，如果是则返回None
        if My_handle.config.get("filter", "after_filter_str") and any(
                content.endswith(prefix) for prefix in My_handle.config.get("filter", "after_filter_str")):
            return None

        # 判断弹幕是否以xx起始，如果不是则返回None
        if My_handle.config.get("filter", "before_must_str") and not any(
                content.startswith(prefix) for prefix in My_handle.config.get("filter", "before_must_str")):
            return None
        else:
            for prefix in My_handle.config.get("filter", "before_must_str"):
                if content.startswith(prefix):
                    content = content[len(prefix):]  # 删除匹配的开头
                    break

        # 判断弹幕是否以xx结尾，如果不是则返回None
        if My_handle.config.get("filter", "after_must_str") and not any(
                content.endswith(prefix) for prefix in My_handle.config.get("filter", "after_must_str")):
            return None
        else:
            for prefix in My_handle.config.get("filter", "after_must_str"):
                if content.endswith(prefix):
                    content = content[:-len(prefix)]  # 删除匹配的结尾
                    break

        # 全为标点符号
        if My_handle.common.is_punctuation_string(content):
            return None

        # 换行转为,
        content = content.replace('\n', ',')

        # 表情弹幕过滤
        if My_handle.config.get("filter", "emoji"):
            from utils.emoji_utils import EmojiUtils
            # 同时支持[]格式和Unicode表情符号过滤
            content = EmojiUtils.clean_text(content)
            logger.info(f"表情弹幕过滤后：{content}")

        # 语言检测
        if My_handle.common.lang_check(content, My_handle.config.get("need_lang")) is None:
            logger.warning("语言检测不通过，已过滤")
            return None

        return content


    # 违禁处理
    def prohibitions_handle(self, content):
        """违禁处理

        Args:
            content (str): 带判断的字符串内容

        Returns:
            str: 是：None 否返回：content
        """
        # 含有链接
        if My_handle.common.is_url_check(content):
            logger.warning(f"链接：{content}")
            return None
        
        # 违禁词检测
        if My_handle.config.get("filter", "badwords", "enable"):
            if My_handle.common.profanity_content(content):
                logger.warning(f"违禁词：{content}")
                return None
            
            bad_word = My_handle.common.check_sensitive_words2(My_handle.config.get("filter", "badwords", "path"), content)
            if bad_word is not None:
                logger.warning(f"命中本地违禁词：{bad_word}")

                # 是否丢弃
                if My_handle.config.get("filter", "badwords", "discard"):
                    return None
                
                # 进行违禁词替换
                content = content.replace(bad_word, My_handle.config.get("filter", "badwords", "replace"))

                logger.info(f"违禁词替换后：{content}")

                # 回调，多次进行违禁词过滤替换
                return self.prohibitions_handle(content)


            # 同拼音违禁词过滤
            if My_handle.config.get("filter", "badwords", "bad_pinyin_path") != "":
                if My_handle.common.check_sensitive_words3(My_handle.config.get("filter", "badwords", "bad_pinyin_path"), content):
                    logger.warning(f"同音违禁词：{content}")
                    return None

        return content


    # 直接复读
    def reread_handle(self, data, filter=False, type="reread"):
        """复读处理

        Args:
            data (dict): 包含用户名,弹幕内容
            filter (bool): 是否开启复读内容的过滤
            type (str): 复读数据的类型（reread | trends_copywriting）

        Returns:
            _type_: 寂寞
        """
        try:
            # 检查data是否包含必要的字段
            if not isinstance(data, dict) or "username" not in data or "content" not in data:
                logger.warning(f"弹幕数据格式错误，缺少必要字段: {data}")
                return None
                
            username = data["username"]
            content = data["content"]

            logger.info(f"复读内容：{content}")

            if filter:
                # 违禁处理
                content = self.prohibitions_handle(content)
                if content is None:
                    return
                
                # 弹幕格式检查和特殊字符替换和指定语言过滤
                content = self.comment_check_and_replace(content)
                if content is None:
                    return
                
                # 判断字符串是否全为标点符号，是的话就过滤
                if My_handle.common.is_punctuation_string(content):
                    logger.debug(f"用户:{username}]，发送纯符号的弹幕，已过滤")
                    return
            
            # 检查是否应该使用助播TTS
            use_assistant_tts = (data.get("_use_assistant_anchor_tts", False) or 
                               self.assistant_anchor_manager.should_handle("entrance"))
            
            if use_assistant_tts:
                # 使用助播TTS
                message = {
                    "type": type,
                    "tts_type": self.config.get("assistant_anchor", {}).get("audio_synthesis_type", "edge-tts"),
                    "data": self.config.get("assistant_anchor", {}).get("audio_synthesis_config", {}),
                    "config": My_handle.config.get("filter"),
                    "username": username,
                    "content": content,
                    "_use_assistant_anchor_tts": True
                }
            else:
                # 使用全局TTS
                tts_type, tts_config = My_handle.config.get_safe_tts_config()
                message = {
                    "type": type,
                    "tts_type": tts_type,
                    "data": tts_config,
                    "config": My_handle.config.get("filter"),
                    "username": username,
                    "content": content,
                    "_use_assistant_anchor_tts": False
                }

            # 音频插入的索引（适用于audio_player_v2）
            if "insert_index" in data:
                message["insert_index"] = data["insert_index"]

            logger.debug(message)

            # 洛曦 直播弹幕助手
            if My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "enable") and \
                "reread" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "type") and \
                "消息产生时" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "trigger_position"):
                asyncio.run(send_msg_to_live_comment_assistant(My_handle.config.get("luoxi_project", "Live_Comment_Assistant"), content))

            self.audio_synthesis_handle(message)
        except Exception as e:
            logger.error(traceback.format_exc())

    # 调教
    def tuning_handle(self, data_json):
        """调教LLM处理

        Args:
            data_json (dict): 包含用户名,弹幕内容

        Returns:
            _type_: 寂寞
        """
        try:
            logger.info(f"调教命令：{data_json['content']}")

            """
            根据聊天类型执行不同逻辑
            """ 
            chat_type = My_handle.config.get("chat_type")
            if chat_type in self.chat_type_list:
                data_json["ori_username"] = data_json["username"]
                data_json["ori_content"] = data_json["content"]
                resp_content = self.llm_handle(chat_type, data_json)
                if resp_content is not None:
                    logger.info(f"[AI回复{My_handle.config.get('talk', 'username')}]：{resp_content}")
                else:
                    logger.warning(f"警告：{chat_type}无返回")
        except Exception as e:
            logger.error(traceback.format_exc())

    # 弹幕日志记录
    def write_to_comment_log(self, resp_content: str, data: dict):
        try:
            # 将 AI 回复记录到日志文件中
            with open(self.comment_file_path, "r+", encoding="utf-8") as f:
                tmp_content = f.read()
                # 将指针移到文件头部位置（此目的是为了让直播中读取日志文件时，可以一直让最新内容显示在顶部）
                f.seek(0, 0)
                # 不过这个实现方式，感觉有点低效
                # 设置单行最大字符数，主要目的用于接入直播弹幕显示时，弹幕过长导致的显示溢出问题
                max_length = 20
                resp_content_substrings = [resp_content[i:i + max_length] for i in range(0, len(resp_content), max_length)]
                resp_content_joined = '\n'.join(resp_content_substrings)

                # 根据 弹幕日志类型进行各类日志写入
                if My_handle.config.get("comment_log_type") == "问答":
                    f.write(f"[{data['username']} 提问]:\n{data['content']}\n[AI回复{data['username']}]:{resp_content_joined}\n" + tmp_content)
                elif My_handle.config.get("comment_log_type") == "问题":
                    f.write(f"[{data['username']} 提问]:\n{data['content']}\n" + tmp_content)
                elif My_handle.config.get("comment_log_type") == "回答":
                    f.write(f"[AI回复{data['username']}]:\n{resp_content_joined}\n" + tmp_content)
        except Exception as e:
            logger.error(traceback.format_exc())

    """

                 .@@@@@@@@@@@                    .@@@@@@@@@@@                    .@@@@@@@@@@@@@@^         /@@@@@@@@@@@@@@              
                 .@@@@@@@@@@@                    .@@@@@@@@@@@                    .@@@@@@@@@@@@@@@        ,@@@@@@@@@@@@@@@              
                 .@@@@@@@@@@@                    .@@@@@@@@@@@                    .@@@@@@@@@@@@@@@^       /@@@@@@@@@@@@@@@              
                 .@@@@@@@@@@@                    .@@@@@@@@@@@                    .@@@@@@@@@@@@@@@@.     ,@@@@@@@@@@@@@@@@              
                 .@@@@@@@@@@@                    .@@@@@@@@@@@                    .@@@@@@@@@@@@@@@@^     /@@@@@@@@@@@@@@@@              
                 .@@@@@@@@@@@                    .@@@@@@@@@@@                    .@@@@@@@@@=@@@@@@@.   ,@@@@@@@^@@@@@@@@@              
                 .@@@@@@@@@@@                    .@@@@@@@@@@@                    .@@@@@@@@@.@@@@@@@^   @@@@@@@@.@@@@@@@@@              
                 .@@@@@@@@@@@                    .@@@@@@@@@@@                    .@@@@@@@@@ =@@@@@@@. =@@@@@@@^.@@@@@@@@@              
                 .@@@@@@@@@@@                    .@@@@@@@@@@@                    .@@@@@@@@@ .@@@@@@@^ @@@@@@@@ .@@@@@@@@@              
                 .@@@@@@@@@@@                    .@@@@@@@@@@@                    .@@@@@@@@@  =@@@@@@@=@@@@@@@^ .@@@@@@@@@              
                 .@@@@@@@@@@@                    .@@@@@@@@@@@                    .@@@@@@@@@  .@@@@@@@@@@@@@@@  .@@@@@@@@@              
                 .@@@@@@@@@@@                    .@@@@@@@@@@@                    .@@@@@@@@@   =@@@@@@@@@@@@@^  .@@@@@@@@@              
                 .@@@@@@@@@@@                    .@@@@@@@@@@@                    .@@@@@@@@@   .@@@@@@@@@@@@/   .@@@@@@@@@              
                 .@@@@@@@@@@@@@@@@@@@@@@@@@@@^   .@@@@@@@@@@@@@@@@@@@@@@@@@@@^   .@@@@@@@@@    =@@@@@@@@@@@`   .@@@@@@@@@              
                 .@@@@@@@@@@@@@@@@@@@@@@@@@@@^   .@@@@@@@@@@@@@@@@@@@@@@@@@@@^   .@@@@@@@@@    .@@@@@@@@@@/    .@@@@@@@@@              
                 .@@@@@@@@@@@@@@@@@@@@@@@@@@@^   .@@@@@@@@@@@@@@@@@@@@@@@@@@@^   .@@@@@@@@@     =@@@@@@@@@`    .@@@@@@@@@              
                 .@@@@@@@@@@@@@@@@@@@@@@@@@@@^   .@@@@@@@@@@@@@@@@@@@@@@@@@@@^   .@@@@@@@@@     .@@@@@@@@/     .@@@@@@@@@  

    """


    # LLM处理
    def llm_handle(self, chat_type, data, type="chat", webui_show=True):
        """LLM统一处理

        Args:
            chat_type (str): 聊天类型
            data (str): dict，含用户名和内容
            type (str): 调用的类型（chat / vision）
            webui_show (bool): 是否在webui上显示

        Returns:
            str: LLM返回的结果
        """
        try:
            # 判断弹幕是否以xx起始，如果不是则返回None 不触发LLM
            if My_handle.config.get("filter", "before_must_str_for_llm") != []:
                if any(data["ori_content"].startswith(prefix) for prefix in My_handle.config.get("filter", "before_must_str_for_llm")):
                    pass
                else:
                    return None
            
            # 判断弹幕是否以xx结尾，如果不是则返回None
            if My_handle.config.get("filter", "after_must_str_for_llm") != []:
                if any(data["ori_content"].endswith(prefix) for prefix in My_handle.config.get("filter", "after_must_str_for_llm")):
                    pass
                else:
                    return None

            resp_content = None
            
            logger.debug(f"chat_type={chat_type}, data={data}")

            if type == "chat":
                # 使用 getattr 来动态获取属性
                if getattr(self, chat_type, None) is None:
                    self.get_chat_model(chat_type, My_handle.config)
                # 新增LLM需要在这里追加
                chat_model_methods = {
                    "chatgpt": lambda: self.chatgpt.get_gpt_resp(data["username"], data["content"]),
                    "chatterbot": lambda: self.chatterbot.get_resp(data["content"]) if hasattr(self, 'chatterbot') and self.chatterbot else GPT_MODEL.chat("chatterbot", data["content"]),
                    "chat_with_file": lambda: self.chat_with_file.get_model_resp(data["content"]),
                    "text_generation_webui": lambda: self.text_generation_webui.get_resp(data["content"]),
                    "sparkdesk": lambda: self.sparkdesk.get_resp(data["content"]),
                    "langchain_chatchat": lambda: self.langchain_chatchat.get_resp(data["content"]),
                    "zhipu": lambda: self.zhipu.get_resp(data["content"]),
                    "bard": lambda: self.bard_api.get_resp(data["content"]),
                    "tongyi": lambda: self.tongyi.get_resp(data["content"]),
                    "tongyixingchen": lambda: self.tongyixingchen.get_resp(data["content"]),
                    "my_wenxinworkshop": lambda: self.my_wenxinworkshop.get_resp(data["content"]),
                    "gemini": lambda: self.gemini.get_resp(data["content"]),
                    "koboldcpp": lambda: self.koboldcpp.get_resp({"prompt": data["content"]}),
                    "anythingllm": lambda: self.anythingllm.get_resp({"prompt": data["content"]}),
                    "gpt4free": lambda: self.gpt4free.get_resp({"prompt": data["content"]}),
                    "custom_llm": lambda: self.custom_llm.get_resp({"prompt": data["content"]}),
                    "llm_tpu": lambda: self.llm_tpu.get_resp({"prompt": data["content"]}),
                    "dify": lambda: self.dify.get_resp({"prompt": data["content"]}),
                    "volcengine": lambda: self.volcengine.get_resp({"prompt": data["content"]}),
                    "reread": lambda: data["content"]
                }
            elif type == "vision":
                # 使用 getattr 来动态获取属性
                if getattr(self, chat_type, None) is None:
                    self.get_vision_model(chat_type, My_handle.config.get("image_recognition", chat_type))
                
                # 新增LLM需要在这里追加
                chat_model_methods = {
                    "gemini": lambda: self.image_recognition_model.get_resp_with_img(data["content"], data["img_data"]),
                    "zhipu": lambda: self.image_recognition_model.get_resp_with_img(data["content"], data["img_data"]),
                }

            # 使用字典映射的方式来获取响应内容
            resp_content = chat_model_methods.get(chat_type, lambda: data["content"])()

            if resp_content is not None:
                resp_content = resp_content.strip()
                # 替换 \n换行符 \n字符串为空
                resp_content = re.sub(r'\\n|\n', '', resp_content)

                # 初始化过滤状态
                filter_state = {
                    'is_filtering': False,
                    'current_tag': None,
                    'buffer': ''
                }
                # 过滤<></>标签内容 主要针对deepseek返回
                resp_content = My_handle.common.llm_resp_content_filter_tags(resp_content, filter_state)

            # 判断 回复模板 是否启用
            if My_handle.config.get("reply_template", "enable"):
                # 根据模板变量关系进行回复内容的替换
                # 假设有多个未知变量，用户可以在此处定义动态变量
                variables = {
                    'username': data["username"][:self.config.get("reply_template", "username_max_len")],
                    'data': resp_content,
                    'cur_time': My_handle.common.get_bj_time(5),
                }

                reply_template_copywriting = My_handle.common.get_list_random_or_default(self.config.get("reply_template", "copywriting"), "{data}")
                # 使用字典进行字符串替换
                if any(var in reply_template_copywriting for var in variables):
                    resp_content = reply_template_copywriting.format(**{var: value for var, value in variables.items() if var in reply_template_copywriting})


            logger.debug(f"resp_content={resp_content}")

            # 返回为空，触发异常报警
            if resp_content is None:
                self.abnormal_alarm_handle("llm")
                logger.warning("LLM没有正确返回数据，请排查配置、网络等是否正常。如果排查后都没有问题，可能是接口改动导致的兼容性问题，可以前往官方仓库提交issue，传送门：https://github.com/Ikaros-521/AI-Vtuber/issues")
            
            # 是否启用webui回显
            if webui_show and resp_content:
                self.webui_show_chat_log_callback(chat_type, data, resp_content)

            return resp_content
        except Exception as e:
            logger.error(traceback.format_exc())

        return None

    # 流式LLM处理 + 音频合成
    def llm_stream_handle_and_audio_synthesis(self, chat_type, data, type="chat", webui_show=True):
        """LLM统一处理

        Args:
            chat_type (str): 聊天类型
            data (str): dict，含用户名和内容
            type (str): 调用的类型（chat / vision）
            webui_show (bool): 是否在webui上显示

        Returns:
            str: LLM返回的结果
        """
        try:
            # 判断弹幕是否以xx起始，如果不是则返回None 不触发LLM
            if My_handle.config.get("filter", "before_must_str_for_llm") != []:
                if any(data["ori_content"].startswith(prefix) for prefix in My_handle.config.get("filter", "before_must_str_for_llm")):
                    pass
                else:
                    return None
            
            # 判断弹幕是否以xx结尾，如果不是则返回None
            if My_handle.config.get("filter", "after_must_str_for_llm") != []:
                if any(data["ori_content"].endswith(prefix) for prefix in My_handle.config.get("filter", "after_must_str_for_llm")):
                    pass
                else:
                    return None

            # 最终返回的整个llm响应内容
            resp_content = ""

            # 备份一下传给LLM的内容，用于上下文记忆
            content_bak = data["content"]
            
            logger.debug(f"chat_type={chat_type}, data={data}")

            if type == "chat":
                # 使用 getattr 来动态获取属性
                if getattr(self, chat_type, None) is None:
                    self.get_chat_model(chat_type, My_handle.config)
                    # setattr(self, chat_type, GPT_MODEL.get(chat_type))
            
                # 新增LLM需要在这里追加
                chat_model_methods = {
                    "chatgpt": lambda: self.chatgpt.get_gpt_resp(data["username"], data["content"], stream=True),
                    "zhipu": lambda: self.zhipu.get_resp(data["content"], stream=True),
                    "tongyi": lambda: self.tongyi.get_resp(data["content"], stream=True),
                    "tongyixingchen": lambda: self.tongyixingchen.get_resp(data["content"], stream=True),
                    "my_wenxinworkshop": lambda: self.my_wenxinworkshop.get_resp(data["content"], stream=True),
                    "volcengine": lambda: self.volcengine.get_resp({"prompt": data["content"]}, stream=True),
                    "dify": lambda: self.dify.get_resp({"prompt": data["content"]}, stream=True),
                }
            elif type == "vision":
                pass

            # 使用字典映射的方式来获取响应内容
            resp = chat_model_methods.get(chat_type, lambda: data["content"])()
            
            def split_by_chinese_punctuation(s):
                # 定义中文标点符号集合
                chinese_punctuation = "。、，；！？"
                
                # 遍历字符串中的每一个字符
                for i, char in enumerate(s):
                    if char in chinese_punctuation:
                        # 找到第一个中文标点符号，进行切分
                        return {"ret": True, "content1": s[:i+1], "content2": s[i+1:].lstrip()}
                
                # 如果没有找到中文标点符号，返回原字符串和空字符串
                return {"ret": False, "content1": s, "content2": ""}

            if resp is not None:
                # 流式开始拼接文本内容时，初始的临时文本存储变量
                tmp = ""

                # 判断 回复模板 是否启用
                if My_handle.config.get("reply_template", "enable"):
                    # 根据模板变量关系进行回复内容的替换
                    # 假设有多个未知变量，用户可以在此处定义动态变量
                    variables = {
                        'username': data["username"][:self.config.get("reply_template", "username_max_len")],
                        'data': "",
                        'cur_time': My_handle.common.get_bj_time(5),
                    }

                    reply_template_copywriting = My_handle.common.get_list_random_or_default(self.config.get("reply_template", "copywriting"), "")
                    # 使用字典进行字符串替换
                    if any(var in reply_template_copywriting for var in variables):
                        tmp = reply_template_copywriting.format(**{var: value for var, value in variables.items() if var in reply_template_copywriting})


                # 已经切掉的字符长度，针对一些特殊llm的流式输出，需要去掉前面的字符
                cut_len = 0

                # 智谱 智能体情况特殊处理
                if chat_type == "zhipu" and My_handle.config.get("zhipu", "model") == "智能体":
                    resp = resp.iter_lines()

                # 初始化过滤状态
                filter_state = {
                    'is_filtering': False,
                    'current_tag': None,
                    'buffer': ''
                }

                buffer = b""

                def tmp_handle(resp_json: dict, tmp: str, cut_len: int=0):
                    if resp_json["ret"]:
                        # 切出来的句子
                        tmp_content = resp_json["content1"]
                        
                        #logger.warning(f"句子生成：{tmp_content}")

                        if chat_type in ["chatgpt", "zhipu", "tongyixingchen", "my_wenxinworkshop", "volcengine", "dify"]:
                            # 智谱 智能体情况特殊处理
                            if chat_type == "zhipu" and My_handle.config.get("zhipu", "model") == "智能体":
                                # 记录 并追加切出的文本长度
                                cut_len += len(tmp_content)
                            else:
                                # 标点符号后的内容包留，用于之后继续追加内容
                                tmp = resp_json["content2"]
                        elif chat_type in ["tongyi"]:
                            # 记录 并追加切出的文本长度
                            cut_len += len(tmp_content)
                            
                        """
                        双重过滤，为您保驾护航
                        """
                        tmp_content = tmp_content.strip()

                        tmp_content = tmp_content.replace('\n', '。')

                        # 替换 \n换行符 \n字符串为空
                        tmp_content = re.sub(r'\\n|\n', '', tmp_content)
                        
                        # LLM回复的内容进行违禁判断
                        tmp_content = self.prohibitions_handle(tmp_content)
                        if tmp_content is None:
                            return tmp, cut_len

                        # logger.info("tmp_content=" + tmp_content)

                        # 回复内容是否进行翻译
                        if My_handle.config.get("translate", "enable") and (My_handle.config.get("translate", "trans_type") == "回复" or \
                            My_handle.config.get("translate", "trans_type") == "弹幕+回复"):
                            tmp = My_handle.my_translate.trans(tmp_content)
                            if tmp:
                                tmp_content = tmp

                        self.write_to_comment_log(tmp_content, data)

                        # 判断按键映射触发类型
                        if My_handle.config.get("key_mapping", "type") == "回复" or My_handle.config.get("key_mapping", "type") == "弹幕+回复":
                            # 替换内容
                            data["content"] = tmp_content
                            # 按键映射 触发后不执行后面的其他功能
                            if self.key_mapping_handle("回复", data):
                                pass

                        # 判断自定义命令触发类型
                        if My_handle.config.get("custom_cmd", "type") == "回复" or My_handle.config.get("custom_cmd", "type") == "弹幕+回复":
                            # 替换内容
                            data["content"] = tmp_content
                            # 自定义命令 触发后不执行后面的其他功能
                            if self.custom_cmd_handle("回复", data):
                                pass
                            

                        # 音频合成时需要用到的重要数据
                        # 检查是否应该使用助播TTS配置
                        if self._is_assistant_anchor_message(data):
                            # 使用助播TTS配置
                            assistant_anchor_config = My_handle.config.get("assistant_anchor")
                            message = {
                                "type": "comment",
                                "tts_type": assistant_anchor_config.get("audio_synthesis_type"),
                                "data": My_handle.config.get(assistant_anchor_config.get("audio_synthesis_type") or "edge-tts") or {},
                                "config": My_handle.config.get("filter"),
                                "username": data['username'],
                                "content": tmp_content,
                                "_use_assistant_anchor_tts": True
                            }
                        else:
                            # 使用全局TTS配置
                            message = {
                                "type": "comment",
                                "tts_type": My_handle.config.get("audio_synthesis_type"),
                                "data": My_handle.config.get(My_handle.config.get("audio_synthesis_type") or "edge-tts") or {},
                                "config": My_handle.config.get("filter"),
                                "username": data['username'],
                                "content": tmp_content
                            }

                        # 洛曦 直播弹幕助手
                        if My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "enable") and \
                            "comment_reply" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "type") and \
                            "消息产生时" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "trigger_position"):
                            asyncio.run(send_msg_to_live_comment_assistant(My_handle.config.get("luoxi_project", "Live_Comment_Assistant"), tmp_content))

                        self.audio_synthesis_handle(message)

                        return tmp, cut_len

                    return tmp, cut_len


                for chunk in resp:
                    # logger.warning(chunk)
                    if chunk is None:
                        continue

                    if chat_type in ["chatgpt", "zhipu"]:
                        # 智谱 智能体情况特殊处理
                        if chat_type == "zhipu" and My_handle.config.get("zhipu", "model") == "智能体":
                            decoded_line = chunk.decode('utf-8')
                            if decoded_line.startswith('data:'):
                                data_dict = json.loads(decoded_line[5:])
                                message = data_dict.get("message")
                                if len(message) > 0:
                                    content = message.get("content")
                                    if len(content) > 0:
                                        response_type = content.get("type")
                                        if response_type == "text":
                                            text = content.get("text", "")
                                            #logger.warning(f"cut_len={cut_len},智谱返回内容：{text}")
                                            # 这个是一直输出全部的内容，所以要切分掉已经处理的文本长度
                                            tmp = text[cut_len:]
                                            resp_content = text
                                        else:
                                            continue
                                    else:
                                        continue
                                else:
                                    continue
                            else:
                                continue
                        else:
                            if chunk.choices[0].delta.content:
                                # 过滤<></>标签内容 主要针对deepseek返回
                                chunk.choices[0].delta.content = My_handle.common.llm_resp_content_filter_tags(chunk.choices[0].delta.content, filter_state)

                                # 流式的内容是追加形式的
                                tmp += chunk.choices[0].delta.content
                                resp_content += chunk.choices[0].delta.content
                    elif chat_type in ["tongyi"]:
                        # 这个是一直输出全部的内容，所以要切分掉已经处理的文本长度
                        tmp = chunk.output.choices[0].message.content[cut_len:]
                        resp_content = chunk.output.choices[0].message.content
                    elif chat_type in ["tongyixingchen"]:
                        # 流式的内容是追加形式的
                        tmp += chunk.data.choices[0].messages[0].content
                        resp_content += chunk.data.choices[0].messages[0].content
                    elif chat_type in ["volcengine"]:
                        tmp += chunk.choices[0].delta.content
                        resp_content += chunk.choices[0].delta.content
                    elif chat_type in ["my_wenxinworkshop"]:
                        tmp += chunk
                        resp_content += chunk
                    elif chat_type in ["dify"]:
                        # 将新的数据添加到缓冲区
                        buffer += chunk
                        
                        # 初始化resp_json
                        resp_json = {"ret": False, "content1": "", "content2": ""}
                        
                        # 尝试按行分割数据
                        while b"\n" in buffer:
                            # 获取一个完整的行
                            line, buffer = buffer.split(b"\n", 1)
                            line = line.strip()
                            
                            # 跳过空行
                            if not line:
                                continue
                                
                            # 处理data:前缀
                            if line.startswith(b"data: "):
                                try:
                                    # 解析JSON数据
                                    data_chunk = json.loads(line[6:].decode('utf-8'))
                                    
                                    # 处理不同类型的事件
                                    if "event" in data_chunk:
                                        if data_chunk["event"] == "message":
                                            answer = data_chunk.get("answer", "")

                                            # 过滤<></>标签内容 主要针对deepseek返回
                                            answer = My_handle.common.llm_resp_content_filter_tags(answer, filter_state)

                                            tmp += answer
                                            resp_content += answer

                                            resp_json = split_by_chinese_punctuation(tmp)
                                            #logger.warning(f"resp_json={resp_json}")
                                            tmp, cut_len = tmp_handle(resp_json, tmp, cut_len)
                                        elif data_chunk["event"] == "message_end":
                                            self.dify.add_assistant_msg_to_session(data_chunk["conversation_id"])
                                            resp_json = split_by_chinese_punctuation(tmp)
                                            if not resp_json['ret']:
                                                resp_json['ret'] = True
                                                logger.warning(f"resp_json={resp_json}")
                                                tmp, cut_len = tmp_handle(resp_json, tmp, cut_len)
                                            logger.info(f"[{chat_type}] 流式接收完毕")
                                            break
                                        elif data_chunk["event"] == "error":
                                            logger.error(f"Dify返回错误: {data_chunk}")
                                            break
                                except json.JSONDecodeError as e:
                                    logger.error(f"JSON解析错误: {e}. 原始数据: {line}")
                                    continue
                            else:
                                logger.debug(f"跳过非data:开头的行: {line}")
                                continue

                    if chat_type not in ["dify"]:
                        # 用于切分，根据中文标点符号切分语句
                        resp_json = split_by_chinese_punctuation(tmp)
                        #logger.warning(f"resp_json={resp_json}")
                        tmp, cut_len = tmp_handle(resp_json, tmp, cut_len)
                        #logger.warning(f"cut_len={cut_len}, tmp={tmp}")

                    if chat_type in ["chatgpt", "zhipu"]:
                        # logger.info(chunk)
                        # 智谱 智能体情况特殊处理
                        if chat_type == "zhipu" and My_handle.config.get("zhipu", "model") == "智能体":
                            decoded_line = chunk.decode('utf-8')
                            if decoded_line.startswith('data:'):
                                data_dict = json.loads(decoded_line[5:])
                                status = data_dict.get("status")
                                if len(status) > 0 and status == "finish":
                                    resp_json['ret'] = True
                                    tmp, cut_len = tmp_handle(resp_json, tmp, cut_len)

                                    logger.info(f"[{chat_type}] 流式接收完毕")
                                    break
                        else:
                            if chunk.choices[0].finish_reason == "stop":
                                if not resp_json['ret']:
                                    resp_json['ret'] = True
                                    tmp, cut_len = tmp_handle(resp_json, tmp, cut_len)

                                logger.info(f"[{chat_type}] 流式接收完毕")
                                break
                    elif chat_type in ["tongyi"]:
                        if chunk.output.choices[0].finish_reason == "stop":
                            if not resp_json['ret']:
                                resp_json['ret'] = True
                                tmp, cut_len = tmp_handle(resp_json, tmp, cut_len)

                            logger.info(f"[{chat_type}] 流式接收完毕")
                            break


            # 返回为空，触发异常报警
            else:
                self.abnormal_alarm_handle("llm")
                logger.warning("LLM没有正确返回数据，请排查配置、网络等是否正常。如果排查后都没有问题，可能是接口改动导致的兼容性问题，可以前往官方仓库提交issue，传送门：https://github.com/Ikaros-521/AI-Vtuber/issues")
            
            # 是否启用webui回显
            if webui_show:
                # 去除resp_content字符串最开始无用的空格和换行
                resp_content = resp_content.lstrip()

                self.webui_show_chat_log_callback(chat_type, data, resp_content)

            # 添加返回到上下文记忆
            if type == "chat":
                # TODO：兼容更多流式LLM
                # 新增流式LLM需要在这里追加
                chat_model_methods = {
                    "chatgpt": lambda: self.chatgpt.add_assistant_msg_to_session(data["username"], resp_content),
                    "zhipu": lambda: self.zhipu.add_assistant_msg_to_session(content_bak, resp_content),
                    "tongyi": lambda: self.tongyi.add_assistant_msg_to_session(content_bak, resp_content),
                    "tongyixingchen": lambda: self.tongyixingchen.add_assistant_msg_to_session(content_bak, resp_content),
                    "my_wenxinworkshop": lambda: self.my_wenxinworkshop.add_assistant_msg_to_session(content_bak, resp_content),
                    "volcengine": lambda: self.volcengine.add_assistant_msg_to_session(content_bak, resp_content),
                }
            elif type == "vision":
                pass

            # 使用字典映射的方式来获取响应内容
            func = chat_model_methods.get(chat_type, resp_content)

            if callable(func):
                # 如果 func 是一个可调用对象（函数），则执行它
                resp = func()
            elif isinstance(func, str):
                # 如果 func 是字符串，跳过执行
                pass
            else:
                # 如果 func 既不是函数也不是字符串，处理其他情况
                pass

            return resp_content
        except Exception as e:
            logger.error(traceback.format_exc())

        return None

    # 积分处理
    def integral_handle(self, type, data):
        """积分处理

        Args:
            type (str): 消息数据类型（comment/gift/entrance）
            data (dict): 平台侧传入的data数据，直接拿来做解析

        Returns:
            bool: 是否正常触发了积分事件，是True 否False
        """
        username = data["username"]
        
        if My_handle.config.get("integral", "enable"):
            # 根据消息类型进行对应处理
            if "comment" == type:
                content = data["content"]

                # 是否开启了签到功能
                if My_handle.config.get("integral", "sign", "enable"):
                    # 判断弹幕内容是否是命令
                    if content in My_handle.config.get("integral", "sign", "cmd"):
                        # 查询数据库中是否有当前用户的积分记录（缺个UID）
                        common_sql = '''
                        SELECT * FROM integral WHERE username =?
                        '''
                        integral_data = self.db.fetch_all(common_sql, (username,))

                        logger.debug(f"integral_data={integral_data}")

                        # 获取文案并合成语音，传入签到天数自动检索
                        def get_copywriting_and_audio_synthesis(sign_num):
                            # 判断当前签到天数在哪个签到数区间内，根据不同的区间提供不同的文案回复
                            for integral_sign_copywriting in My_handle.config.get("integral", "sign", "copywriting"):
                                # 在此区间范围内，所以你的配置一定要对，不然这里就崩溃了！！！
                                if int(integral_sign_copywriting["sign_num_interval"].split("-")[0]) <= \
                                    sign_num <= \
                                    int(integral_sign_copywriting["sign_num_interval"].split("-")[1]):
                                    # 匹配文案
                                    resp_content = random.choice(integral_sign_copywriting["copywriting"])
                                    
                                    logger.debug(f"resp_content={resp_content}")

                                    data_json = {
                                        "username": data["username"],
                                        "get_integral": int(My_handle.config.get("integral", "sign", "get_integral")),
                                        "sign_num": sign_num + 1
                                    } 

                                    resp_content = My_handle.common.dynamic_variable_replacement(resp_content, data_json)
                                    
                                    # 括号语法替换
                                    resp_content = My_handle.common.brackets_text_randomize(resp_content)
                                    
                                    # 检查是否使用助播TTS
                                    if data.get("_use_assistant_anchor_tts", False):
                                        # 使用助播TTS
                                        message = {
                                            "type": "integral",
                                            "tts_type": self.config.get("assistant_anchor", {}).get("audio_synthesis_type", "edge-tts"),
                                            "data": self.config.get("assistant_anchor", {}).get("audio_synthesis_config", {}),
                                            "config": My_handle.config.get("filter"),
                                            "username": username,
                                            "content": resp_content,
                                            "_use_assistant_anchor_tts": True
                                        }
                                    else:
                                        # 使用全局TTS
                                        tts_type, tts_config = My_handle.config.get_safe_tts_config()
                                        message = {
                                            "type": "integral",
                                            "tts_type": tts_type,
                                            "data": tts_config,
                                            "config": My_handle.config.get("filter"),
                                            "username": username,
                                            "content": resp_content,
                                            "_use_assistant_anchor_tts": False
                                        }

                                    # 助播功能优先处理积分签到
                                    integral_data = {
                                        "username": username,
                                        "content": resp_content
                                    }
                                    
                                    if self.assistant_anchor_handle(integral_data, "integral"):
                                        # 助播已处理，跳过后续处理
                                        pass
                                    else:
                                        # 助播未处理，使用全局TTS
                                        # 洛曦 直播弹幕助手
                                        if My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "enable") and \
                                            "integral" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "type") and \
                                            "消息产生时" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "trigger_position"):
                                            asyncio.run(send_msg_to_live_comment_assistant(My_handle.config.get("luoxi_project", "Live_Comment_Assistant"), resp_content))
                                        
                                        self.audio_synthesis_handle(message)

                        if integral_data == []:
                            # 积分表中没有该用户，插入数据
                            insert_data_sql = '''
                            INSERT INTO integral (platform, username, uid, integral, view_num, sign_num, last_sign_ts, total_price, last_ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            '''
                            self.db.execute(insert_data_sql, (
                                data["platform"], 
                                username, 
                                username, 
                                My_handle.config.get("integral", "sign", "get_integral"), 
                                1,
                                1,
                                datetime.now(),
                                0,
                                datetime.now())
                            )

                            logger.info(f"integral积分表 新增 用户：{username}")

                            get_copywriting_and_audio_synthesis(0)

                            return True
                        else:
                            integral_data = integral_data[0]
                            # 积分表中有该用户，更新数据

                            # 先判断last_sign_ts是否是今天，如果是，则说明已经打卡过了，不能重复打卡
                            # 获取日期时间字符串字段，此处是个坑点，一旦数据库结构发生改变或者select语句改了，就会关联影响！！！
                            date_string = integral_data[6]

                            # 获取日期部分（前10个字符），并与当前日期字符串比较
                            if date_string[:10] == datetime.now().date().strftime("%Y-%m-%d"):
                                resp_content = f"{username}您今天已经签到过了，不能重复打卡哦~"
                                message = {
                                    "type": "integral",
                                    "tts_type": My_handle.config.get("audio_synthesis_type"),
                                    "data": My_handle.config.get(My_handle.config.get("audio_synthesis_type") or "edge-tts") or {},
                                    "config": My_handle.config.get("filter"),
                                    "username": username,
                                    "content": resp_content,
                                    "_use_assistant_anchor_tts": True  # 标记为使用助播TTS
                                }

                                # 洛曦 直播弹幕助手
                                if My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "enable") and \
                                    "integral" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "type") and \
                                    "消息产生时" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "trigger_position"):
                                    asyncio.run(send_msg_to_live_comment_assistant(My_handle.config.get("luoxi_project", "Live_Comment_Assistant"), resp_content))
                                
                                self.audio_synthesis_handle(message)

                                return True

                            # 更新下用户数据
                            update_data_sql = '''
                            UPDATE integral SET integral=?, view_num=?, sign_num=?, last_sign_ts=?, last_ts=? WHERE username =?
                            '''
                            self.db.execute(update_data_sql, (
                                # 此处是个坑点，一旦数据库结构发生改变或者select语句改了，就会关联影响！！！
                                integral_data[3] + My_handle.config.get("integral", "sign", "get_integral"), 
                                integral_data[4] + 1,
                                integral_data[5] + 1,
                                datetime.now(),
                                datetime.now(),
                                username
                                )
                            )

                            logger.info(f"integral积分表 更新 用户：{username}")

                            get_copywriting_and_audio_synthesis(integral_data[5] + 1)

                            return True
            elif "gift" == type:
                # 是否开启了礼物功能
                if My_handle.config.get("integral", "gift", "enable"):
                    # 查询数据库中是否有当前用户的积分记录（缺个UID）
                    common_sql = '''
                    SELECT * FROM integral WHERE username =?
                    '''
                    integral_data = self.db.fetch_all(common_sql, (username,))

                    logger.debug(f"integral_data={integral_data}")

                    get_integral = int(float(My_handle.config.get("integral", "gift", "get_integral_proportion")) * data["total_price"])

                    # 获取文案并合成语音，传入总礼物金额自动检索
                    def get_copywriting_and_audio_synthesis(total_price):
                        # 判断当前礼物金额在哪个礼物金额区间内，根据不同的区间提供不同的文案回复
                        for integral_gift_copywriting in My_handle.config.get("integral", "gift", "copywriting"):
                            # 在此区间范围内，所以你的配置一定要对，不然这里就崩溃了！！！
                            if float(integral_gift_copywriting["gift_price_interval"].split("-")[0]) <= \
                                total_price <= \
                                float(integral_gift_copywriting["gift_price_interval"].split("-")[1]):
                                # 匹配文案
                                resp_content = random.choice(integral_gift_copywriting["copywriting"])
                                
                                logger.debug(f"resp_content={resp_content}")

                                data_json = {
                                    "username": data["username"],
                                    "gift_name": data["gift_name"],
                                    "get_integral": get_integral,
                                    'gift_num': data["num"],
                                    'unit_price': data["unit_price"],
                                    'total_price': data["total_price"],
                                    'cur_time': My_handle.common.get_bj_time(5),
                                } 

                                # 括号语法替换
                                resp_content = My_handle.common.brackets_text_randomize(resp_content)

                                # 动态变量替换
                                resp_content = My_handle.common.dynamic_variable_replacement(resp_content, data_json)
                                
                                # 检查是否使用助播TTS
                                if data.get("_use_assistant_anchor_tts", False):
                                    # 使用助播TTS
                                    message = {
                                        "type": "integral",
                                        "tts_type": self.config.get("assistant_anchor", {}).get("audio_synthesis_type", "edge-tts"),
                                        "data": self.config.get("assistant_anchor", {}).get("audio_synthesis_config", {}),
                                        "config": My_handle.config.get("filter"),
                                        "username": username,
                                        "content": resp_content,
                                        "_use_assistant_anchor_tts": True
                                    }
                                else:
                                    # 使用全局TTS
                                    tts_type, tts_config = My_handle.config.get_safe_tts_config()
                                    message = {
                                        "type": "integral",
                                        "tts_type": tts_type,
                                        "data": tts_config,
                                        "config": My_handle.config.get("filter"),
                                        "username": username,
                                        "content": resp_content,
                                        "_use_assistant_anchor_tts": False
                                    }

                                # 洛曦 直播弹幕助手
                                if My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "enable") and \
                                    "integral" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "type") and \
                                    "消息产生时" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "trigger_position"):
                                    asyncio.run(send_msg_to_live_comment_assistant(My_handle.config.get("luoxi_project", "Live_Comment_Assistant"), resp_content))
                                

                                self.audio_synthesis_handle(message)

                    # TODO：此处有计算bug！！！ 总礼物价值计算不对，后期待优化
                    if integral_data == []:
                        # 积分表中没有该用户，插入数据
                        insert_data_sql = '''
                        INSERT INTO integral (platform, username, uid, integral, view_num, sign_num, last_sign_ts, total_price, last_ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        '''
                        self.db.execute(insert_data_sql, (
                            data["platform"], 
                            username, 
                            username, 
                            get_integral, 
                            1,
                            1,
                            datetime.now(),
                            data["total_price"],
                            datetime.now())
                        )

                        logger.info(f"integral积分表 新增 用户：{username}")

                        get_copywriting_and_audio_synthesis(data["total_price"])

                        return True
                    else:
                        integral_data = integral_data[0]
                        # 积分表中有该用户，更新数据

                        # 更新下用户数据
                        update_data_sql = '''
                        UPDATE integral SET integral=?, total_price=?, last_ts=? WHERE username =?
                        '''
                        self.db.execute(update_data_sql, (
                            # 此处是个坑点，一旦数据库结构发生改变或者select语句改了，就会关联影响！！！
                            integral_data[3] + get_integral, 
                            integral_data[7] + data["total_price"],
                            datetime.now(),
                            username
                            )
                        )

                        logger.info(f"integral积分表 更新 用户：{username}")

                        get_copywriting_and_audio_synthesis(data["total_price"])

                        return True
            elif "entrance" == type:
                # 是否开启了入场功能
                if My_handle.config.get("integral", "entrance", "enable"):
                    # 查询数据库中是否有当前用户的积分记录（缺个UID）
                    common_sql = '''
                    SELECT * FROM integral WHERE username =?
                    '''
                    integral_data = self.db.fetch_all(common_sql, (username,))

                    logger.debug(f"integral_data={integral_data}")

                    # 获取文案并合成语音，传入观看天数自动检索
                    def get_copywriting_and_audio_synthesis(view_num):
                        # 判断当前签到天数在哪个签到数区间内，根据不同的区间提供不同的文案回复
                        for integral_entrance_copywriting in My_handle.config.get("integral", "entrance", "copywriting"):
                            # 在此区间范围内，所以你的配置一定要对，不然这里就崩溃了！！！
                            if int(integral_entrance_copywriting["entrance_num_interval"].split("-")[0]) <= \
                                view_num <= \
                                int(integral_entrance_copywriting["entrance_num_interval"].split("-")[1]):

                                if len(integral_entrance_copywriting["copywriting"]) <= 0:
                                    return False

                                # 匹配文案
                                resp_content = random.choice(integral_entrance_copywriting["copywriting"])
                                
                                logger.debug(f"resp_content={resp_content}")

                                data_json = {
                                    "username": data["username"],
                                    "get_integral": int(My_handle.config.get("integral", "entrance", "get_integral")),
                                    "entrance_num": view_num + 1
                                } 

                                resp_content = My_handle.common.dynamic_variable_replacement(resp_content, data_json)
                                
                                # 括号语法替换
                                resp_content = My_handle.common.brackets_text_randomize(resp_content)

                                # 检查是否使用助播TTS
                                if data.get("_use_assistant_anchor_tts", False):
                                    # 使用助播TTS
                                    message = {
                                        "type": "integral",
                                        "tts_type": self.config.get("assistant_anchor", {}).get("audio_synthesis_type", "edge-tts"),
                                        "data": self.config.get("assistant_anchor", {}).get("audio_synthesis_config", {}),
                                        "config": My_handle.config.get("filter"),
                                        "username": username,
                                        "content": resp_content,
                                        "_use_assistant_anchor_tts": True
                                    }
                                else:
                                    # 使用全局TTS
                                    tts_type, tts_config = My_handle.config.get_safe_tts_config()
                                    message = {
                                        "type": "integral",
                                        "tts_type": tts_type,
                                        "data": tts_config,
                                        "config": My_handle.config.get("filter"),
                                        "username": username,
                                        "content": resp_content,
                                        "_use_assistant_anchor_tts": False
                                    }

                                # 洛曦 直播弹幕助手
                                if My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "enable") and \
                                    "integral" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "type") and \
                                    "消息产生时" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "trigger_position"):
                                    asyncio.run(send_msg_to_live_comment_assistant(My_handle.config.get("luoxi_project", "Live_Comment_Assistant"), resp_content))
                                
                                
                                self.audio_synthesis_handle(message)

                    if integral_data == []:
                        # 积分表中没有该用户，插入数据
                        insert_data_sql = '''
                        INSERT INTO integral (platform, username, uid, integral, view_num, sign_num, last_sign_ts, total_price, last_ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        '''
                        self.db.execute(insert_data_sql, (
                            data["platform"], 
                            username, 
                            username, 
                            My_handle.config.get("integral", "entrance", "get_integral"), 
                            1,
                            0,
                            datetime.now(),
                            0,
                            datetime.now())
                        )

                        logger.info(f"integral积分表 新增 用户：{username}")

                        get_copywriting_and_audio_synthesis(1)

                        return True
                    else:
                        integral_data = integral_data[0]
                        # 积分表中有该用户，更新数据

                        # 先判断last_ts是否是今天，如果是，则说明已经观看过了，不能重复记录
                        # 获取日期时间字符串字段，此处是个坑点，一旦数据库结构发生改变或者select语句改了，就会关联影响！！！
                        date_string = integral_data[8]

                        # 获取日期部分（前10个字符），并与当前日期字符串比较
                        if date_string[:10] == datetime.now().date().strftime("%Y-%m-%d"):
                            return False

                        # 更新下用户数据
                        update_data_sql = '''
                        UPDATE integral SET integral=?, view_num=?, last_ts=? WHERE username =?
                        '''
                        self.db.execute(update_data_sql, (
                            # 此处是个坑点，一旦数据库结构发生改变或者select语句改了，就会关联影响！！！
                            integral_data[3] + My_handle.config.get("integral", "entrance", "get_integral"), 
                            integral_data[4] + 1,
                            datetime.now(),
                            username
                            )
                        )

                        logger.info(f"integral积分表 更新 用户：{username}")

                        get_copywriting_and_audio_synthesis(integral_data[4] + 1)

                        return True
            elif "crud" == type:
                content = data["content"]
                
                # 是否开启了查询功能
                if My_handle.config.get("integral", "crud", "query", "enable"):
                    # 判断弹幕内容是否是命令
                    if content in My_handle.config.get("integral", "crud", "query", "cmd"):
                        # 查询数据库中是否有当前用户的积分记录（缺个UID）
                        common_sql = '''
                        SELECT * FROM integral WHERE username =?
                        '''
                        integral_data = self.db.fetch_all(common_sql, (username,))

                        logger.debug(f"integral_data={integral_data}")

                        # 获取文案并合成语音，传入积分总数自动检索
                        def get_copywriting_and_audio_synthesis(total_integral):
                            # 匹配文案
                            resp_content = random.choice(My_handle.config.get("integral", "crud", "query", "copywriting"))
                            
                            logger.debug(f"resp_content={resp_content}")

                            data_json = {
                                "username": data["username"],
                                "integral": total_integral
                            }

                            resp_content = My_handle.common.dynamic_variable_replacement(resp_content, data_json)

                            # 如果积分为0，则返回个没积分的回复。不过这个基本没可能，除非有bug
                            if total_integral == 0:
                                resp_content = data["username"] + "，查询到您无积分。"
                            
                            # 括号语法替换
                            resp_content = My_handle.common.brackets_text_randomize(resp_content)

                            # 检查是否使用助播TTS
                            if data.get("_use_assistant_anchor_tts", False):
                                # 使用助播TTS
                                message = {
                                    "type": "integral",
                                    "tts_type": self.config.get("assistant_anchor", {}).get("audio_synthesis_type", "edge-tts"),
                                    "data": self.config.get("assistant_anchor", {}).get("audio_synthesis_config", {}),
                                    "config": My_handle.config.get("filter"),
                                    "username": username,
                                    "content": resp_content,
                                    "_use_assistant_anchor_tts": True
                                }
                            else:
                                # 使用全局TTS
                                tts_type, tts_config = My_handle.config.get_safe_tts_config()
                                message = {
                                    "type": "integral",
                                    "tts_type": tts_type,
                                    "data": tts_config,
                                    "config": My_handle.config.get("filter"),
                                    "username": username,
                                    "content": resp_content,
                                    "_use_assistant_anchor_tts": False
                                }

                            # 洛曦 直播弹幕助手
                            if My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "enable") and \
                                "integral" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "type") and \
                                "消息产生时" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "trigger_position"):
                                asyncio.run(send_msg_to_live_comment_assistant(My_handle.config.get("luoxi_project", "Live_Comment_Assistant"), resp_content))
                            
                            
                            self.audio_synthesis_handle(message)

                        if integral_data == []:
                            logger.info(f"integral积分表 查询不到 用户：{username}")

                            get_copywriting_and_audio_synthesis(0)

                            return True
                        else:
                            integral_data = integral_data[0]
                            # 积分表中有该用户

                            # 获取日期时间字符串字段，此处是个坑点，一旦数据库结构发生改变或者select语句改了，就会关联影响！！！
                            date_string = integral_data[3]

                            logger.info(f"integral积分表 用户：{username}，总积分：{date_string}")

                            get_copywriting_and_audio_synthesis(int(date_string))

                            return True
        return False


    # 按键映射处理
    def key_mapping_handle(self, type, data):
        """按键映射处理

        Args:
            type (str): 数据来源类型（弹幕/回复）
            data (dict): 平台侧传入的data数据，直接拿来做解析

        Returns:
            bool: 是否正常触发了按键映射事件，是True 否False
        """
        flag = False

        # 获取一个文案并传递给音频合成函数进行音频合成
        def get_a_copywriting_and_audio_synthesis(key_mapping_config, data):
            try:
                # 随机获取一个文案
                tmp = random.choice(key_mapping_config["copywriting"])

                # 括号语法替换
                tmp = My_handle.common.brackets_text_randomize(tmp)
                
                # 动态变量替换
                data_json = {
                    "username": data["username"],
                    "gift_name": data["gift_name"],
                    'gift_num': data["num"],
                    'unit_price': data["unit_price"],
                    'total_price': data["total_price"],
                    'cur_time': My_handle.common.get_bj_time(5),
                } 
                tmp = My_handle.common.dynamic_variable_replacement(tmp, data_json)

                # 检查是否使用助播TTS
                if data.get("_use_assistant_anchor_tts", False):
                    # 使用助播TTS
                    message = {
                        "type": "key_mapping",
                        "tts_type": self.config.get("assistant_anchor", {}).get("audio_synthesis_type", "edge-tts"),
                        "data": self.config.get("assistant_anchor", {}).get("audio_synthesis_config", {}),
                        "config": My_handle.config.get("filter"),
                        "username": data["username"],
                        "content": tmp,
                        "_use_assistant_anchor_tts": True
                    }
                else:
                    # 使用全局TTS
                    tts_type, tts_config = My_handle.config.get_safe_tts_config()
                    message = {
                        "type": "key_mapping",
                        "tts_type": tts_type,
                        "data": tts_config,
                        "config": My_handle.config.get("filter"),
                        "username": data["username"],
                        "content": tmp,
                        "_use_assistant_anchor_tts": False
                    }

                logger.info(f'【触发按键映射】触发文案：{tmp}')

                # 洛曦 直播弹幕助手
                if My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "enable") and \
                    "key_mapping_copywriting" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "type") and \
                    "消息产生时" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "trigger_position"):
                    asyncio.run(send_msg_to_live_comment_assistant(My_handle.config.get("luoxi_project", "Live_Comment_Assistant"), tmp))

                # TODO: 播放时的转发没有实现，因为类型定义没有这么细化
                self.audio_synthesis_handle(message)
            except Exception as e:
                logger.error(traceback.format_exc())

        # 获取一个本地音频并传递给音频合成函数进行音频播放
        def get_a_local_audio_and_audio_play(key_mapping_config, data):
            try:
                # 随机获取一个文案
                if len(key_mapping_config["local_audio"]) <= 0:
                    return
                
                tmp = random.choice(key_mapping_config["local_audio"])

                # 检查是否使用助播TTS
                if data.get("_use_assistant_anchor_tts", False):
                    # 使用助播TTS
                    message = {
                        "type": "key_mapping",
                        "tts_type": self.config.get("assistant_anchor", {}).get("audio_synthesis_type", "edge-tts"),
                        "data": self.config.get("assistant_anchor", {}).get("audio_synthesis_config", {}),
                        "config": My_handle.config.get("filter"),
                        "username": data["username"],
                        "content": tmp,
                        "file_path": tmp,
                        "_use_assistant_anchor_tts": True
                    }
                else:
                    # 使用全局TTS
                    tts_type, tts_config = My_handle.config.get_safe_tts_config()
                    message = {
                        "type": "key_mapping",
                        "tts_type": tts_type,
                        "data": tts_config,
                        "config": My_handle.config.get("filter"),
                        "username": data["username"],
                        "content": tmp,
                        "file_path": tmp,
                        "_use_assistant_anchor_tts": False
                    }

                logger.info(f'【触发映射】播放本地音频：{tmp}')

                self.audio_synthesis_handle(message)
            except Exception as e:
                logger.error(traceback.format_exc())

        # 随机获取一个串口发送数据 内容
        def get_a_serial_send_data_and_send(key_mapping_config, data):
            try:
                async def connect_serial_and_send_data(serial_name, baudrate, serial_data_type, data):
                    from utils.serial_manager_instance import get_serial_manager

                    serial_manager = get_serial_manager()
                    # 关闭串口 单例没啥用啊，醉了
                    # resp_json = await serial_manager.disconnect(serial_name)
                    # 打开串口
                    resp_json = await serial_manager.connect(serial_name, int(baudrate))
                
                    # 发送数据到串口
                    resp_json = await serial_manager.send_data(serial_name, tmp, serial_data_type)

                    return resp_json
                    
                # 随机获取一个文案
                tmp = random.choice(key_mapping_config["serial_send_data"])

                # 括号语法替换
                tmp = My_handle.common.brackets_text_randomize(tmp)
                
                # 动态变量替换
                data_json = {
                    "username": data.get("username", ""),
                    "gift_name": data.get("gift_name", ""),
                    "gift_num": data.get("num", ""),
                    "unit_price": data.get("unit_price", ""),
                    "total_price": data.get("total_price", ""),
                    "cur_time": My_handle.common.get_bj_time(5),
                }
                tmp = My_handle.common.dynamic_variable_replacement(tmp, data_json)

                # 定义一个函数，通过 serial_name 获取 对应的config配置
                def get_serial_config(serial_name: str):
                    for config in My_handle.config.get("serial", "config"):
                        if config["serial_name"] == serial_name:
                            return config
                    return None  # 如果未找到匹配的 serial_name，返回 None

                serial_name = key_mapping_config["serial_name"]
                tmp_config = get_serial_config(serial_name)
                if tmp_config:
                    baudrate = tmp_config["baudrate"]
                    resp_json = asyncio.run(connect_serial_and_send_data(serial_name, baudrate, tmp_config["serial_data_type"], data))
                    
                    logger.info(f'【触发按键映射】触发串口：{tmp}，{resp_json["msg"]}')

                    return tmp
                
                logger.error(f"获取串口名：{serial_name} 的配置信息失败，请到 串口 页面检查配置是否正确！")
            
                return None
            except Exception as e:
                logger.error(traceback.format_exc())
                return None

        # 获取一个本地图片路径并传递给虚拟摄像头显示
        def get_a_img_path_and_send(key_mapping_config, data):
            try:
                # 随机获取一个图片路径
                if len(key_mapping_config["img_path"]) <= 0:
                    return
                
                tmp = random.choice(key_mapping_config["img_path"])

                self.sd.set_new_img(tmp)
            except Exception as e:
                logger.error(traceback.format_exc())


        try:
            import pyautogui

            # 关键词触发的内容统一到此函数进行处理
            def keyword_handle_trigger(trigger_type, keyword, key_mapping_config, data, flag):
                try:
                    if My_handle.config.get("key_mapping", trigger_type) in ["关键词", "关键词+礼物"]:
                        if trigger_type == "key_trigger_type":
                            logger.info(f'【触发按键映射】关键词：{keyword} 按键：{key_mapping_config["keys"]}')
                            for key in key_mapping_config["keys"]:
                                pyautogui.keyDown(key)
                            for key in key_mapping_config["keys"]:
                                pyautogui.keyUp(key)
                        elif trigger_type == "copywriting_trigger_type":
                            logger.info(f'【触发按键映射】关键词：{keyword} ，触发文案')
                            get_a_copywriting_and_audio_synthesis(key_mapping_config, data)
                        elif trigger_type == "local_audio_trigger_type":
                            logger.info(f'【触发按键映射】关键词：{keyword} ，触发本地音频')
                            get_a_local_audio_and_audio_play(key_mapping_config, data)
                        elif trigger_type == "serial_trigger_type":
                            logger.info(f'【触发按键映射】关键词：{keyword} ，触发串口')
                            get_a_serial_send_data_and_send(key_mapping_config, data)
                        elif trigger_type == "img_path_trigger_type":
                            logger.info(f'【触发按键映射】关键词：{keyword} ，触发图片')
                            get_a_img_path_and_send(key_mapping_config, data)
                        
                        flag = True
                        
                    single_sentence_trigger_once_enable = My_handle.config.get("key_mapping", f"{trigger_type.split('_')[0]}_single_sentence_trigger_once_enable")
                    return {"trigger_once_enable": single_sentence_trigger_once_enable, "flag": flag}
                except Exception as e:
                    logger.error(f"【触发按键映射】异常：{e}")
                    return {"trigger_once_enable": False, "flag": False}
                
            
            # 礼物触发的内容统一到此函数进行处理
            def gift_handle_trigger(trigger_type, gift_name, key_mapping_config, data, flag):
                try:
                    if My_handle.config.get("key_mapping", trigger_type) in ["礼物", "关键词+礼物"]:
                        if trigger_type == "key_trigger_type":
                            logger.info(f'【触发按键映射】礼物：{gift_name} 按键：{key_mapping_config["keys"]}')
                            for key in key_mapping_config["keys"]:
                                pyautogui.keyDown(key)
                            for key in key_mapping_config["keys"]:
                                pyautogui.keyUp(key)
                        elif trigger_type == "copywriting_trigger_type":
                            logger.info(f'【触发按键映射】礼物：{gift_name} ，触发文案')
                            get_a_copywriting_and_audio_synthesis(key_mapping_config, data)
                        elif trigger_type == "local_audio_trigger_type":
                            logger.info(f'【触发按键映射】礼物：{gift_name} ，触发本地音频')
                            get_a_local_audio_and_audio_play(key_mapping_config, data)
                        elif trigger_type == "serial_trigger_type":
                            logger.info(f'【触发按键映射】礼物：{gift_name} ，触发串口')
                            get_a_serial_send_data_and_send(key_mapping_config, data)
                        elif trigger_type == "img_path_trigger_type":
                            logger.info(f'【触发按键映射】礼物：{gift_name} ，触发图片')
                            get_a_img_path_and_send(key_mapping_config, data)

                        flag = True
                        
                    single_sentence_trigger_once_enable = My_handle.config.get("key_mapping", f"{trigger_type.split('_')[0]}_single_sentence_trigger_once_enable")
                    return {"trigger_once_enable": single_sentence_trigger_once_enable, "flag": flag}
                except Exception as e:
                    logger.error(f"【触发按键映射】异常：{e}")
                    return {"trigger_once_enable": False, "flag": False}
            
            # 官方文档：https://pyautogui.readthedocs.io/en/latest/keyboard.html#keyboard-keys
            if My_handle.config.get("key_mapping", "enable"):
                # 判断传入的数据是否包含gift_name键值，有的话则是礼物数据
                if "gift_name" in data:
                    # 获取key_mapping 所有 config数据
                    key_mapping_configs = My_handle.config.get("key_mapping", "config")

                    # 遍历key_mapping_configs
                    for key_mapping_config in key_mapping_configs:
                        # 遍历单个配置中所有礼物名
                        for gift in key_mapping_config["gift"]:
                            # 判断礼物名是否相同
                            if gift == data["gift_name"]:
                                """
                                不同的触发类型 都会进行独立的执行判断
                                """

                                for trigger in ["key_trigger_type", "copywriting_trigger_type", "local_audio_trigger_type", "serial_trigger_type"]:
                                    resp_json = gift_handle_trigger(trigger, gift, key_mapping_config, data, flag)
                                    if resp_json["trigger_once_enable"]:
                                        return resp_json["flag"]  
                else:
                    content = data["content"]
                    # 判断命令头是否匹配
                    start_cmd = My_handle.config.get("key_mapping", "start_cmd")
                    if start_cmd != "" and content.startswith(start_cmd):
                        # 删除命令头部
                        content = content[len(start_cmd):]

                    key_mapping_configs = My_handle.config.get("key_mapping", "config")
                    
                    for key_mapping_config in key_mapping_configs:
                        similarity = float(key_mapping_config["similarity"])
                        for keyword in key_mapping_config["keywords"]:
                            if type == "弹幕":
                                # 判断相似度
                                ratio = difflib.SequenceMatcher(None, content, keyword).ratio()
                                if ratio >= similarity:
                                    """
                                    不同的触发类型 都会进行独立的执行判断
                                    """
                                    
                                    for trigger in ["key_trigger_type", "copywriting_trigger_type", "local_audio_trigger_type", "serial_trigger_type", \
                                                    "img_path_trigger_type"]:
                                        resp_json = keyword_handle_trigger(trigger, keyword, key_mapping_config, data, flag)
                                        if resp_json["trigger_once_enable"]:
                                            return resp_json["flag"]  
                                        
                            elif type == "回复":
                                logger.debug(f"keyword={keyword}, content={content}")
                                if keyword in content:
                                    for trigger in ["key_trigger_type", "copywriting_trigger_type", "local_audio_trigger_type", "serial_trigger_type", \
                                                    "img_path_trigger_type"]:
                                        resp_json = keyword_handle_trigger(trigger, keyword, key_mapping_config, data, flag)
                                        if resp_json["trigger_once_enable"]:
                                            return resp_json["flag"]
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f'【触发按键映射】错误：{e}')

        return flag


    # 自定义命令处理
    def custom_cmd_handle(self, type, data):
        """自定义命令处理

        Args:
            type (str): 数据来源类型（弹幕/回复）
            data (dict): 平台侧传入的data数据，直接拿来做解析

        Returns:
            bool: 是否正常触发了自定义命令事件，是True 否False
        """
        flag = False


        try:
            if My_handle.config.get("custom_cmd", "enable"):
                # 判断传入的数据是否包含gift_name键值，有的话则是礼物数据
                if "gift_name" in data:
                    pass
                else:
                    username = data["username"]
                    content = data["content"]
                    custom_cmd_configs = My_handle.config.get("custom_cmd", "config")

                    for custom_cmd_config in custom_cmd_configs:
                        similarity = float(custom_cmd_config["similarity"])
                        for keyword in custom_cmd_config["keywords"]:
                            if type == "弹幕":
                                # 判断相似度
                                ratio = difflib.SequenceMatcher(None, content, keyword).ratio()
                                if ratio >= similarity:
                                    resp = My_handle.common.send_request(
                                        custom_cmd_config["api_url"], 
                                        custom_cmd_config["api_type"],
                                        resp_data_type=custom_cmd_config["resp_data_type"]
                                    )

                                    # 使用 eval() 执行字符串表达式并获取结果
                                    resp_content = eval(custom_cmd_config["data_analysis"])

                                    # 将字符串中的换行符替换为句号
                                    resp_content = resp_content.replace('\n', '。')

                                    logger.debug(f"resp_content={resp_content}")

                                    # 违禁词处理
                                    resp_content = self.prohibitions_handle(resp_content)
                                    if resp_content is None:
                                        return flag

                                    variables = {
                                        'keyword': keyword,
                                        'cur_time': My_handle.common.get_bj_time(5),
                                        'username': username,
                                        'data': resp_content
                                    }

                                    tmp = custom_cmd_config["resp_template"]

                                    # 使用字典进行字符串替换
                                    if any(var in tmp for var in variables):
                                        resp_content = tmp.format(**{var: value for var, value in variables.items() if var in tmp})
                                    
                                    # 检查是否使用助播TTS
                                    if data.get("_use_assistant_anchor_tts", False):
                                        # 使用助播TTS
                                        message = {
                                            "type": "custom_cmd",
                                            "tts_type": self.config.get("assistant_anchor", {}).get("audio_synthesis_type", "edge-tts"),
                                            "data": self.config.get("assistant_anchor", {}).get("audio_synthesis_config", {}),
                                            "config": My_handle.config.get("filter"),
                                            "username": username,
                                            "content": resp_content,
                                            "_use_assistant_anchor_tts": True
                                        }
                                    else:
                                        # 使用全局TTS
                                        tts_type, tts_config = My_handle.config.get_safe_tts_config()
                                        message = {
                                            "type": "custom_cmd",
                                            "tts_type": tts_type,
                                            "data": tts_config,
                                            "config": My_handle.config.get("filter"),
                                            "username": username,
                                            "content": resp_content,
                                            "_use_assistant_anchor_tts": False
                                        }

                                    logger.debug(message)
                                    
                                    logger.info(f'【触发 自定义命令】关键词：{keyword} 返回内容：{resp_content}')

                                    self.audio_synthesis_handle(message)

                                    self.webui_show_chat_log_callback("自定义命令", data, resp_content)

                                    flag = True
                                    
                            
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f'【触发自定义命令】错误：{e}')

        return flag


    # 黑名单处理
    def blacklist_handle(self, data):
        """黑名单处理

        Args:
            data (dict): 包含用户名,弹幕内容

        Returns:
            bool: True是黑名单用户，False不是黑名单用户
        """
        try:
            if My_handle.config.get("filter", "blacklist", "enable"):
                username_blacklist = My_handle.config.get("filter", "blacklist", "username")
                if len(username_blacklist) == 0:
                    return False
                
                username = data.get("username", "")
                
                # 检查用户名是否在黑名单中
                for blacklist_user in username_blacklist:
                    if blacklist_user in username:
                        logger.info(f"用户 {username} 在黑名单中，已过滤")
                        return True
                        
                return False
            else:
                return False
                
        except Exception as e:
            logger.error(f"黑名单处理出错: {e}")
            logger.error(traceback.format_exc())
            return False
    
    # ==================== 弹幕客户端管理方法 ====================
    
    def __init_multi_platform_components(self):
        """初始化多平台组件"""
        if not hasattr(self, 'platform_queues'):
            self.platform_queues = {}  # 每个平台独立队列
        if not hasattr(self, 'platform_stats'):
            self.platform_stats = {}  # 平台统计信息
        if not hasattr(self, 'duplicate_filter'):
            self.duplicate_filter = {}  # 去重过滤器
        if not hasattr(self, 'rate_limiters'):
            self.rate_limiters = {}  # 每平台限流器
    

    

    

    
    def update_platform_stats(self, platform: str, message_count: int = 1):
        """更新平台统计信息
        
        Args:
            platform (str): 平台名称
            message_count (int): 消息数量，默认为1
        """
        try:
            self.__init_multi_platform_components()
            
            if platform not in self.platform_stats:
                self.platform_stats[platform] = {
                    'message_count': 0,
                    'last_message_time': 0,
                    'status': 'active',
                    'error_count': 0,
                    'priority': 999,
                    'room_id': ''
                }
            
            stats = self.platform_stats[platform]
            # 确保message_count是整数类型
            if isinstance(message_count, str):
                try:
                    message_count = int(message_count)
                except (ValueError, TypeError):
                    message_count = 1
                    # 静默处理类型错误
            
            # 确保stats['message_count']是整数类型
            if not isinstance(stats['message_count'], int):
                try:
                    stats['message_count'] = int(stats['message_count'])
                except (ValueError, TypeError):
                    stats['message_count'] = 0
                    # 静默处理类型错误
            
            stats['message_count'] += message_count
            stats['last_message_time'] = time.time()
            stats['status'] = 'active'
            
        except Exception as e:
            logger.error(f"更新平台统计失败: {platform}, 错误: {e}")
    
    def is_duplicate_danmaku(self, danmaku_data: dict, window_size: int = 5000) -> bool:
        """检测是否为重复弹幕
        
        Args:
            danmaku_data (dict): 弹幕数据
            window_size (int): 时间窗口大小(毫秒)
            
        Returns:
            bool: 是否为重复弹幕
        """
        try:
            self.__init_multi_platform_components()
            
            content = danmaku_data.get('content', '')
            timestamp = danmaku_data.get('send_time', int(time.time() * 1000))
            platform = danmaku_data.get('platform', '')
            
            # 生成唯一键
            key = f"{content}_{platform}"
            
            # 检查时间窗口内是否存在相同内容
            if key in self.duplicate_filter:
                last_time = self.duplicate_filter[key]
                if timestamp - last_time < window_size:
                    return True
            
            # 更新缓存
            self.duplicate_filter[key] = timestamp
            
            # 清理过期缓存（每100次检查清理一次）
            if len(self.duplicate_filter) % 100 == 0:
                current_time = timestamp
                expired_keys = [k for k, v in self.duplicate_filter.items() 
                              if current_time - v > window_size * 2]
                for k in expired_keys:
                    del self.duplicate_filter[k]
            
            return False
            
        except Exception as e:
            logger.error(f"检测重复弹幕失败: {e}")
            return False
     

    # 判断限定时间段内数据是否重复
    def is_data_repeat_in_limited_time(self, type: str=None, data: dict=None):
        """判断限定时间段内数据是否重复

        Args:
            type (str): 判断的数据类型（comment|gift|entrance)
            data (dict): 包含用户名,弹幕内容

        Returns:
            dict: 传递给音频合成的JSON数据
        """
        if My_handle.config.get("filter", "limited_time_deduplication", "enable"):
            logger.debug(f"限定时间段内数据重复 My_handle.live_data={My_handle.live_data}")
                        
            if type is not None and type != "" and data is not None:
                if type == "comment":
                    # 如果存在重复数据，返回True
                    for tmp in My_handle.live_data[type]:
                        if tmp['username'] == data['username'] and tmp['content'] == data['content']:
                            logger.debug(f"限定时间段内数据重复 type={type},data={data}")
                            return True
                elif type == "gift":
                    # 如果存在重复数据，返回True
                    for tmp in My_handle.live_data[type]:
                        if tmp['username'] == data['username']:
                            logger.debug(f"限定时间段内数据重复 type={type},data={data}")
                            return True
                elif type == "entrance":   
                    # 如果存在重复数据，返回True
                    for tmp in My_handle.live_data[type]:
                        if tmp['username'] == data['username']:
                            logger.debug(f"限定时间段内数据重复 type={type},data={data}")
                            return True
                
                # 不存在则插入，返回False
                My_handle.live_data[type].append(data)
        return False

    # 判断是否进行联网搜索，返回处理后的结果
    def search_online_handle(self, content: str):
        try:
            if My_handle.config.get("search_online", "enable"):
                # 是否启用了关键词命令
                if My_handle.config.get("search_online", "keyword_enable"):
                    # 没有命中关键词 直接返回
                    if My_handle.config.get("search_online", "before_keyword") and not any(content.startswith(prefix) for prefix in \
                        My_handle.config.get("search_online", "before_keyword")):
                        return content
                    else:
                        for prefix in My_handle.config.get("search_online", "before_keyword"):
                            if content.startswith(prefix):
                                content = content[len(prefix):]  # 删除匹配的开头
                                break
            
                from .search_engine import search_online

                if My_handle.config.get("search_online", "http_proxy") == "" and My_handle.config.get("search_online", "https_proxy") == "":
                    proxies = None
                else:
                    proxies = {
                        "http": My_handle.config.get("search_online", "http_proxy"),
                        "https": My_handle.config.get("search_online", "https_proxy")
                    }
                summaries = search_online(
                    content, 
                    engine=My_handle.config.get("search_online", "engine"), 
                    engine_id=int(My_handle.config.get("search_online", "engine_id")), 
                    count=int(My_handle.config.get("search_online", "count")), 
                    proxies=proxies
                )
                if summaries != []:
                    # 追加索引编号
                    indexed_summaries = [f"参考资料{i+1}. {summary}" for i, summary in enumerate(summaries)]
                    
                    # 替换掉内容中的多余换行符
                    cleaned_summaries = [summary.replace('\n', ' ') for summary in indexed_summaries]

                    variables = {
                        'summary': cleaned_summaries,
                        'cur_time': My_handle.common.get_bj_time(5),
                        'data': content
                    }

                    tmp = My_handle.config.get("search_online", "resp_template")

                    # 使用字典进行字符串替换
                    if any(var in tmp for var in variables):
                        content = tmp.format(**{var: value for var, value in variables.items() if var in tmp})

            return content
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f"联网搜索报错: {e}")
            return content

    """                                                              
                                                                           
                                                         ,`                
                             @@@@`               =@@\`   /@@/              
                ,/@@] =@@@`  @@@/                 =@@\/@@@@@@@@@[          
           .\@@/[@@@@` ,@@@ =@/.             ,[[[[.=@^ ,@@@@\`             
                *@@^,`  .]]]@@@@@@\`          ,@@@@@@[[[. =@@@@.           
           .]]]]/@@`\@@/ *@@^  =@@@/           ,@@@@@@@@/`@@@`             
            =@@*    .@@@@@@@@/`@@@^             ,@@\]]/@@@@@.              
            =@@      =@@*.@@\]/@@^               ,\@@\   ,]]@@@@]          
          ,/@@@@@@@^  \@/[@@^               .@@@@@@@@@[[[\@\.              
          ,@/. .@@@      .@@\]/@@@@@@`          ,@@@,@@@.,]@@@`            
               .@@/@@@@@/[@@/                  /@@\]@@@@@@@@@@@@@]         
               =@@^      .@@^                ]@@@@@^ @@@  @@@ ,@@@@@@\].   
           ,]]/@@@`      .@@^             ./@/` .@@^.@@@/@@@/              
             \@@@`       .@@^                       .@@@ .[[               
                         .@@`                        @@^                   
                                                                                                                                          

    """

    # 弹幕处理 直播间的弹幕消息会统一到此函数进行处理
    def comment_handle(self, data):
        """弹幕处理 直播间的弹幕消息会统一到此函数进行处理

        Args:
            data (dict): 包含用户名,弹幕内容

        Returns:
            dict: 传递给音频合成的JSON数据
        """

        try:
            username = data["username"]
            content = data["content"]

            # 输出当前用户发送的弹幕消息
            logger.debug(f"[{username}]: {content}")

            # 限定时间数据去重
            if self.is_data_repeat_in_limited_time("comment", data):
                return None

            # 黑名单过滤
            if self.blacklist_handle(data):
                return None
            
            # 添加用户名到最新的用户名列表（在过滤之后，避免添加被过滤的用户名）
            import utils.my_global as my_global
            my_global.add_username_to_last_username_list(username)
            
            # 助播功能已在 process_last_data 中处理，这里不再重复处理
            
            # 弹幕数据经过基本初步筛选后，通过 洛曦直播弹幕助手，可以进行转发。
            # 洛曦 直播弹幕助手
            if My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "enable") and \
                "comment" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "type") and \
                "消息产生时" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "trigger_position"):
                asyncio.run(send_msg_to_live_comment_assistant(My_handle.config.get("luoxi_project", "Live_Comment_Assistant"), content))


            # 返回给webui的聊天记录
            if My_handle.config.get("talk", "show_chat_log"):
                if "ori_username" not in data:
                    data["ori_username"] = data["username"]
                if "ori_content" not in data:
                    data["ori_content"] = data["content"]
                if "user_face" not in data:
                    data["user_face"] = 'https://robohash.org/ui'

                # 返回给webui的数据
                return_webui_json = {
                    "type": "llm",
                    "data": {
                        "type": "弹幕信息",
                        "username": data["ori_username"],
                        "user_face": data["user_face"],
                        "content_type": "question",
                        "content": data["ori_content"],
                        "timestamp": My_handle.common.get_bj_time(0)
                    }
                }
                webui_ip = "127.0.0.1" if My_handle.config.get("webui", "ip") == "0.0.0.0" else My_handle.config.get("webui", "ip")
                tmp_json = My_handle.common.send_request(f'http://{webui_ip}:{My_handle.config.get("webui", "port")}/callback', "POST", return_webui_json, timeout=10)
            

            # 记录数据库
            if My_handle.config.get("database", "comment_enable"):
                insert_data_sql = '''
                INSERT INTO danmu (username, content, ts) VALUES (?, ?, ?)
                '''
                self.db.execute(insert_data_sql, (username, content, datetime.now()))



            # 合并字符串末尾连续的*  主要针对获取不到用户名的情况
            username = My_handle.common.merge_consecutive_asterisks(username)

            # 0、积分机制运转
            if self.integral_handle("comment", data):
                return
            if self.integral_handle("crud", data):
                return

            """
            用户名也得过滤一下，防止炸弹人
            """
            # 用户名以及弹幕违禁判断
            username = self.prohibitions_handle(username)
            if username is None:
                return
            
            content = self.prohibitions_handle(content)
            if content is None:
                return
            
            # 弹幕格式检查和特殊字符替换和指定语言过滤
            content = self.comment_check_and_replace(content)
            if content is None:
                return
            
            # 判断字符串是否全为标点符号，是的话就过滤
            if My_handle.common.is_punctuation_string(content):
                logger.debug(f"用户:{username}]，发送纯符号的弹幕，已过滤")
                return
            
            # 判断按键映射触发类型
            if My_handle.config.get("key_mapping", "type") == "弹幕" or My_handle.config.get("key_mapping", "type") == "弹幕+回复":
                # 按键映射 触发后不执行后面的其他功能
                if self.key_mapping_handle("弹幕", data):
                    return
                
            # 判断自定义命令触发类型
            if My_handle.config.get("custom_cmd", "type") == "弹幕" or My_handle.config.get("custom_cmd", "type") == "弹幕+回复":
                # 自定义命令 触发后不执行后面的其他功能
                if self.custom_cmd_handle("弹幕", data):
                    return
            
            try:
                # 念弹幕
                if My_handle.config.get("read_comment", "enable"):
                    logger.debug(f"念弹幕 content:{content}")

                    # 检查是否应该使用助播TTS进行念弹幕
                    use_assistant_tts_for_read_comment = self.assistant_anchor_manager.should_handle("read_comment")

                    if use_assistant_tts_for_read_comment:
                        # 使用助播TTS配置
                        message = {
                            "type": "assistant_anchor_read_comment",  # 使用助播类型标识
                            "tts_type": self.assistant_anchor_manager.audio_synthesis_type,
                            "data": self.config.get(self.assistant_anchor_manager.audio_synthesis_type) or {},
                            "config": My_handle.config.get("filter"),
                            "username": username,
                            "content": content
                        }
                        logger.info(f"弹幕使用助播TTS配置进行念弹幕")
                    else:
                        # 使用全局TTS配置
                        message = {
                            "type": "read_comment",
                            "tts_type": My_handle.config.get("audio_synthesis_type"),
                            "data": My_handle.config.get(My_handle.config.get("audio_synthesis_type") or "edge-tts") or {},
                            "config": My_handle.config.get("filter"),
                            "username": username,
                            "content": content
                        }
                        logger.debug(f"弹幕使用全局TTS配置进行念弹幕")

                    # 判断是否需要念用户名 (这部分逻辑对两种TTS都适用)
                    if My_handle.config.get("read_comment", "read_username_enable"):
                        # 将用户名中特殊字符替换为空
                        message['username'] = My_handle.common.replace_special_characters(message['username'], "！!@#￥$%^&*_-+/——=()（）【】}|{:;<>~`\\")
                        message['username'] = message['username'][:self.config.get("read_comment", "username_max_len")]

                        # 将用户名字符串中的数字转换成中文
                        if My_handle.config.get("filter", "username_convert_digits_to_chinese"):
                            message["username"] = My_handle.common.convert_digits_to_chinese(message["username"])
                            logger.debug(f"用户名字符串中的数字转换成中文：{message['username']}")

                        if len(self.config.get("read_comment", "read_username_copywriting")) > 0:
                            tmp_content = random.choice(self.config.get("read_comment", "read_username_copywriting"))
                            if "{username}" in tmp_content:
                                message['content'] = tmp_content.format(username=message['username']) + message['content']

                    # 是否启用了周期性触发功能，启用此功能后，数据会被缓存，之后周期到了才会触发
                    if My_handle.config.get("read_comment", "periodic_trigger", "enable"):
                        My_handle.task_data["read_comment"]["data"].append(message)
                    else:
                        self.audio_synthesis_handle(message)
            except Exception as e:
                logger.error(traceback.format_exc())

            # 1、本地问答库 处理
            # 然后尝试使用助播处理其他类型（包括助播本地问答文本）
            if self.assistant_anchor_handle(data, "comment"):
                return  # 助播已处理

            # 如果助播未处理，则尝试系统本地问答
            if self.local_qa_handle(data):
                return  # 系统本地问答已处理

            # 2、点歌模式 触发后不执行后面的其他功能
            if self.choose_song_handle(data):
                return

            # 3、画图模式 触发后不执行后面的其他功能
            if self.sd_handle(data):
                return
        
            # 4、弹幕内容是否进行翻译
            if My_handle.config.get("translate", "enable") and (My_handle.config.get("translate", "trans_type") == "弹幕" or \
                My_handle.config.get("translate", "trans_type") == "弹幕+回复"):
                tmp = My_handle.my_translate.trans(content)
                if tmp:
                    content = tmp
                    # logger.info(f"翻译后：{content}")

            # 5、联网搜索
            content = self.search_online_handle(content)

            data_json = {
                "username": username,
                "content": content,
                "ori_username": data["username"],
                "ori_content": data["content"]
            }

            """
            根据聊天类型执行不同逻辑
            """ 
            chat_type = My_handle.config.get("chat_type")
            if chat_type in self.chat_type_list:
                data_json["content"] = My_handle.config.get("before_prompt")
                # 是否启用弹幕模板
                if self.config.get("comment_template", "enable"):
                    # 假设有多个未知变量，用户可以在此处定义动态变量
                    variables = {
                        'username': username,
                        'comment': content,
                        'cur_time': My_handle.common.get_bj_time(5),
                    }

                    comment_template_copywriting = self.config.get("comment_template", "copywriting")
                    # 使用字典进行字符串替换
                    if any(var in comment_template_copywriting for var in variables):
                        content = comment_template_copywriting.format(**{var: value for var, value in variables.items() if var in comment_template_copywriting})

                data_json["content"] += content + My_handle.config.get("after_prompt")

                logger.debug(f"data_json={data_json}")
                
                # 当前选用的LLM类型是否支持stream，并且启用stream
                if "stream" in self.config.get(chat_type) and self.config.get(chat_type, "stream"):
                    logger.warning("使用流式推理LLM")
                    resp_content = self.llm_stream_handle_and_audio_synthesis(chat_type, data_json)
                    return resp_content
                else:
                    resp_content = self.llm_handle(chat_type, data_json)
                    if resp_content is not None:
                        logger.info(f"[AI回复{username}]：{resp_content}")
                    else:
                        resp_content = ""
                        logger.warning(f"警告：{chat_type}无返回")
            elif chat_type == "game":
                if My_handle.config.get("game", "enable"):
                    self.game.parse_keys_and_simulate_keys_press(content.split(), 2)
                return
            elif chat_type == "none":
                return
            elif chat_type == "reread":
                resp_content = self.llm_handle(chat_type, data_json)
            else:
                resp_content = content

            # 空数据结束
            if resp_content == "" or resp_content is None:
                return

            """
            双重过滤，为您保驾护航
            """
            resp_content = resp_content.strip()

            resp_content = resp_content.replace('\n', '。')
            
            # LLM回复的内容进行违禁判断
            resp_content = self.prohibitions_handle(resp_content)
            if resp_content is None:
                return None

            # logger.info("resp_content=" + resp_content)

            # 回复内容是否进行翻译
            if My_handle.config.get("translate", "enable") and (My_handle.config.get("translate", "trans_type") == "回复" or \
                My_handle.config.get("translate", "trans_type") == "弹幕+回复"):
                tmp = My_handle.my_translate.trans(resp_content)
                if tmp:
                    resp_content = tmp

            self.write_to_comment_log(resp_content, {"username": username, "content": content})

            # 判断按键映射触发类型
            if My_handle.config.get("key_mapping", "type") == "回复" or My_handle.config.get("key_mapping", "type") == "弹幕+回复":
                # 替换内容
                data["content"] = resp_content
                # 按键映射 触发后不执行后面的其他功能
                if self.key_mapping_handle("回复", data):
                    pass

            # 判断自定义命令触发类型
            if My_handle.config.get("custom_cmd", "type") == "回复" or My_handle.config.get("custom_cmd", "type") == "弹幕+回复":
                # 替换内容
                data["content"] = resp_content
                # 自定义命令 触发后不执行后面的其他功能
                if self.custom_cmd_handle("回复", data):
                    pass
                    

            # 当助播功能启用且包含comment类型时，LLM回复应该使用助播TTS
            use_assistant_tts = data.get("_use_assistant_anchor_tts", False)
            
            if use_assistant_tts:
                assistant_anchor_config = My_handle.config.get("assistant_anchor")
                assistant_tts_type = assistant_anchor_config.get("audio_synthesis_type")
                if isinstance(assistant_tts_type, str):
                    message = {
                        "type": "comment",
                        "tts_type": assistant_tts_type,
                        "data": My_handle.config.get(assistant_tts_type) or {},
                        "config": My_handle.config.get("filter"),
                        "username": username,
                        "content": resp_content,
                        "_use_assistant_anchor_tts": True
                    }
                    logger.info(f"弹幕LLM回复使用助播TTS配置: {assistant_tts_type}")
                else:
                    # 如果助播TTS类型配置无效，使用默认值
                    logger.warning(f"助播TTS类型配置无效: {assistant_tts_type}，使用默认值 edge-tts")
                    message = {
                        "type": "comment",
                        "tts_type": "edge-tts",
                        "data": My_handle.config.get("edge-tts") or {},
                        "config": My_handle.config.get("filter"),
                        "username": username,
                        "content": resp_content,
                        "_use_assistant_anchor_tts": True
                    }
            else:
                global_tts_type = My_handle.config.get("audio_synthesis_type")
                if isinstance(global_tts_type, str):
                    message = {
                        "type": "comment",
                        "tts_type": global_tts_type,
                        "data": My_handle.config.get(global_tts_type) or {},
                        "config": My_handle.config.get("filter"),
                        "username": username,
                        "content": resp_content
                    }
                    logger.debug(f"弹幕LLM回复使用全局TTS配置: {global_tts_type}")
                else:
                    # 如果全局TTS类型配置无效，使用默认值
                    logger.warning(f"全局TTS类型配置无效: {global_tts_type}，使用默认值 edge-tts")
                    message = {
                        "type": "comment",
                        "tts_type": "edge-tts",
                        "data": My_handle.config.get("edge-tts") or {},
                        "config": My_handle.config.get("filter"),
                        "username": username,
                        "content": resp_content
                    }

            # 洛曦 直播弹幕助手
            if My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "enable") and \
                "comment_reply" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "type") and \
                "消息产生时" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "trigger_position"):
                asyncio.run(send_msg_to_live_comment_assistant(My_handle.config.get("luoxi_project", "Live_Comment_Assistant"), resp_content))

            # 检查是否需要优先级插队处理
            if data.get("_need_priority_insert", False):
                # 弹幕已经经过完整处理流程，现在进行优先级插队
                logger.info(f"弹幕经过完整处理后进行优先级插队: {resp_content}")
                # 设置高优先级以便插队
                message["priority"] = 8  # 高优先级
                # 使用优先级插队方法
                result = My_handle.audio.priority_insert_message(message, force_insert=False)
                if result["code"] == 200:
                    logger.info(f"弹幕优先级插队成功: {resp_content}")
                else:
                    logger.warning(f"弹幕优先级插队失败，使用常规合成: {result['msg']}")
                    self.audio_synthesis_handle(message)
            else:
                # 正常音频合成
                self.audio_synthesis_handle(message)

            return message
        except Exception as e:
            logger.error(traceback.format_exc())
            return None


    # 礼物处理
    def gift_handle(self, data):
        try:
            # 限定时间数据去重
            if self.is_data_repeat_in_limited_time("gift", data):
                return None
            
            # 添加用户名到最新的用户名列表（在过滤之后，避免添加被过滤的用户名）
            import utils.my_global as my_global
            my_global.add_username_to_last_username_list(data.get('username', ''))
            
            # 记录数据库
            if My_handle.config.get("database", "gift_enable"):
                insert_data_sql = '''
                INSERT INTO gift (username, gift_name, gift_num, unit_price, total_price, ts) VALUES (?, ?, ?, ?, ?, ?)
                '''
                self.db.execute(insert_data_sql, (
                    data['username'], 
                    data['gift_name'], 
                    data['num'], 
                    data['unit_price'], 
                    data['total_price'],
                    datetime.now())
                )

            # 按键映射 触发后仍然执行后面的其他功能
            self.key_mapping_handle("弹幕", data)
            # 自定义命令触发
            self.custom_cmd_handle("弹幕", data)
            
            # 违禁处理
            data['username'] = self.prohibitions_handle(data['username'])
            if data['username'] is None:
                return None
            
            # 积分处理
            if self.integral_handle("gift", data):
                return None

            # 合并字符串末尾连续的*  主要针对获取不到用户名的情况
            data['username'] = My_handle.common.merge_consecutive_asterisks(data['username'])
            # 删除用户名中的特殊字符
            data['username'] = My_handle.common.replace_special_characters(data['username'], "！!@#￥$%^&*_-+/——=()（）【】}|{:;<>~`\\")  

            data['username'] = data['username'][:self.config.get("thanks", "username_max_len")]

            # 将用户名字符串中的数字转换成中文
            if My_handle.config.get("filter", "username_convert_digits_to_chinese"):
                data["username"] = My_handle.common.convert_digits_to_chinese(data["username"])

            # logger.debug(f"[{data['username']}]: {data}")
        
            if not My_handle.config.get("thanks")["gift_enable"]:
                return None

            # 如果礼物总价低于设置的礼物感谢最低值
            if data["total_price"] < My_handle.config.get("thanks")["lowest_price"]:
                return None

            if My_handle.config.get("thanks", "gift_random"):
                resp_content = random.choice(My_handle.config.get("thanks", "gift_copy"))
            else:
                # 类变量list中是否有数据，没有就拷贝下数据再顺序取出首个数据
                if len(My_handle.thanks_gift_copy) == 0:
                    if len(My_handle.config.get("thanks", "gift_copy")) == 0:
                        logger.warning("你把礼物的文案删了，还触发个der礼物感谢？不用别启用不就得了，删了搞啥")
                        return None
                resp_content = My_handle.thanks_gift_copy.pop(0)

            
            # 括号语法替换
            resp_content = My_handle.common.brackets_text_randomize(resp_content)
            
            # 动态变量替换
            data_json = {
                "username": data["username"],
                "gift_name": data["gift_name"],
                'gift_num': data["num"],
                'unit_price': data["unit_price"],
                'total_price': data["total_price"],
                'cur_time': My_handle.common.get_bj_time(5),
            } 
            resp_content = My_handle.common.dynamic_variable_replacement(resp_content, data_json)


            # 检查是否应该使用助播TTS
            use_assistant_tts = (data.get("_use_assistant_anchor_tts", False) or 
                               self.assistant_anchor_manager.should_handle("gift"))
            
            if use_assistant_tts:
                logger.info(f"礼物感谢标记为使用助播TTS: {data.get('_use_assistant_anchor_tts')}")
                # 使用助播TTS配置
                assistant_anchor_config = My_handle.config.get("assistant_anchor")
                if assistant_anchor_config and isinstance(assistant_anchor_config, dict):
                    audio_synthesis_type = assistant_anchor_config.get("audio_synthesis_type", "edge-tts")
                    # 安全获取TTS配置数据
                    tts_config = My_handle.config.get(audio_synthesis_type)
                    if isinstance(tts_config, dict):
                        tts_data = tts_config
                    else:
                        tts_data = {}
                    
                    message = {
                        "type": "gift",
                        "tts_type": audio_synthesis_type,
                        "data": tts_data,
                        "config": My_handle.config.get("filter"),
                        "username": data["username"],
                        "content": resp_content,
                        "gift_info": data,
                        "_use_assistant_anchor_tts": True
                    }
                    logger.info(f"礼物感谢使用助播TTS配置: {audio_synthesis_type}")
                    logger.debug(f"创建的助播TTS消息: {message}")
                else:
                    # 如果助播配置无效，回退到全局TTS配置
                    global_tts_type = My_handle.config.get("audio_synthesis_type")
                    global_tts_config = My_handle.config.get(global_tts_type)
                    if isinstance(global_tts_config, dict):
                        global_tts_data = global_tts_config
                    else:
                        global_tts_data = {}
                    
                    message = {
                        "type": "gift",
                        "tts_type": global_tts_type,
                        "data": global_tts_data,
                        "config": My_handle.config.get("filter"),
                        "username": data["username"],
                        "content": resp_content,
                        "gift_info": data,
                        "_use_assistant_anchor_tts": False
                    }
                    logger.warning(f"助播配置无效，礼物感谢使用全局TTS配置: {global_tts_type}")
                    logger.debug(f"创建的全局TTS消息: {message}")
            else:
                logger.info(f"礼物感谢未标记为使用助播TTS，使用全局TTS配置")
                # 使用全局TTS配置
                global_tts_type = My_handle.config.get("audio_synthesis_type")
                global_tts_config = My_handle.config.get(global_tts_type)
                if isinstance(global_tts_config, dict):
                    global_tts_data = global_tts_config
                else:
                    global_tts_data = {}
                
                message = {
                    "type": "gift",
                    "tts_type": global_tts_type,
                    "data": global_tts_data,
                    "config": My_handle.config.get("filter"),
                    "username": data["username"],
                    "content": resp_content,
                    "gift_info": data,
                    "_use_assistant_anchor_tts": False
                }
                logger.debug(f"礼物感谢使用全局TTS配置: {global_tts_type}")
                logger.debug(f"创建的全局TTS消息: {message}")

            # 助播功能已在 process_last_data 中统一处理，这里直接进行音频合成
            # 洛曦 直播弹幕助手
            if My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "enable") and \
                "gift_reply" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "type") and \
                "消息产生时" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "trigger_position"):
                asyncio.run(send_msg_to_live_comment_assistant(My_handle.config.get("luoxi_project", "Live_Comment_Assistant"), resp_content))
            

            # 是否启用了周期性触发功能，启用此功能后，数据会被缓存，之后周期到了才会触发
            if My_handle.config.get("thanks", "gift", "periodic_trigger", "enable"):
                My_handle.task_data["thanks"]["gift"]["data"].append(message)
            else:
                self.audio_synthesis_handle(message)

            return message
        except Exception as e:
            logger.error(traceback.format_exc())
            return None


    # 入场处理
    def entrance_handle(self, data):
        try:
            # 限定时间数据去重
            if self.is_data_repeat_in_limited_time("entrance", data):
                return None
            
            # 添加用户名到最新的用户名列表（在过滤之后，避免添加被过滤的用户名）
            import utils.my_global as my_global
            my_global.add_username_to_last_username_list(data.get('username', ''))
            
            # 记录数据库
            if My_handle.config.get("database", "entrance_enable"):
                insert_data_sql = '''
                INSERT INTO entrance (username, ts) VALUES (?, ?)
                '''
                self.db.execute(insert_data_sql, (data['username'], datetime.now()))

            # 违禁处理
            data['username'] = self.prohibitions_handle(data['username'])
            if data['username'] is None:
                return None
            
            if self.integral_handle("entrance", data):
                return None

            # 合并字符串末尾连续的*  主要针对获取不到用户名的情况
            data['username'] = My_handle.common.merge_consecutive_asterisks(data['username'])
            # 删除用户名中的特殊字符
            data['username'] = My_handle.common.replace_special_characters(data['username'], "！!@#￥$%^&*_-+/——=()（）【】}|{:;<>~`\\")

            data['username'] = data['username'][:self.config.get("thanks", "username_max_len")]

            # 将用户名字符串中的数字转换成中文
            if My_handle.config.get("filter", "username_convert_digits_to_chinese"):
                data["username"] = My_handle.common.convert_digits_to_chinese(data["username"])

            # logger.debug(f"[{data['username']}]: {data['content']}")
        
            if not My_handle.config.get("thanks")["entrance_enable"]:
                return None

            if My_handle.config.get("thanks", "entrance_random"):
                resp_content = random.choice(My_handle.config.get("thanks", "entrance_copy")).format(username=data["username"])
            else:
                # 类变量list中是否有数据，没有就拷贝下数据再顺序取出首个数据
                if len(My_handle.thanks_entrance_copy) == 0:
                    if len(My_handle.config.get("thanks", "entrance_copy")) == 0:
                        logger.warning("你把入场的文案删了，还触发个der入场感谢？不用别启用不就得了，删了搞啥")
                        return None
                    My_handle.thanks_entrance_copy = copy.copy(My_handle.config.get("thanks", "entrance_copy"))
                resp_content = My_handle.thanks_entrance_copy.pop(0).format(username=data["username"])

            # 括号语法替换
            resp_content = My_handle.common.brackets_text_randomize(resp_content)

            # 检查是否应该使用助播TTS
            use_assistant_tts = (data.get("_use_assistant_anchor_tts", False) or 
                               self.assistant_anchor_manager.should_handle("entrance"))
            
            if use_assistant_tts:
                # 使用助播TTS
                assistant_config = self.config.get("assistant_anchor", {})
                tts_type = assistant_config.get("audio_synthesis_type", "edge-tts")
                
                # 获取基础TTS配置（从根级别获取，与全局获取方式保持一致）
                base_tts_config = My_handle.config.get(tts_type, {})
                
                # 获取助播覆盖配置
                assistant_override_config = assistant_config.get("audio_synthesis_config", {}).get(tts_type, {})
                
                # 合并配置（助播覆盖优先，支持嵌套字段的深合并）
                import copy
                def _deep_merge(a: dict, b: dict):
                    res = copy.deepcopy(a) if isinstance(a, dict) else {}
                    for k, v in (b or {}).items():
                        if isinstance(v, dict) and isinstance(res.get(k), dict):
                            res[k] = _deep_merge(res[k], v)
                        else:
                            res[k] = v
                    return res
                final_tts_config = _deep_merge(base_tts_config, assistant_override_config)

                # 针对 gpt_sovits，若未显式指定 type，则尽量从子配置推断；否则给出安全默认
                if tts_type == "gpt_sovits" and "type" not in final_tts_config:
                    if "api_0322" in final_tts_config:
                        final_tts_config["type"] = "api_0322"
                    elif "api_0706" in final_tts_config:
                        final_tts_config["type"] = "api_0706"
                    elif "v2_api_0821" in final_tts_config:
                        final_tts_config["type"] = "v2_api_0821"
                    elif "webtts" in final_tts_config:
                        final_tts_config["type"] = "webtts"
                    else:
                        final_tts_config["type"] = "api_0322"

                message = {
                    "type": "assistant_anchor_entrance",
                    "tts_type": tts_type,
                    "data": final_tts_config,
                    "config": My_handle.config.get("filter"),
                    "username": data['username'],
                    "content": resp_content,
                    "_use_assistant_anchor_tts": True
                }
                logger.info(f"入场感谢使用助播TTS配置")
            else:
                # 使用全局TTS
                tts_type, tts_config = My_handle.config.get_safe_tts_config()
                message = {
                    "type": "entrance",
                    "tts_type": tts_type,
                    "data": tts_config,
                    "config": My_handle.config.get("filter"),
                    "username": data['username'],
                    "content": resp_content,
                    "_use_assistant_anchor_tts": False
                }
                logger.info(f"入场感谢使用全局TTS配置")

            # 洛曦 直播弹幕助手
            if My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "enable") and \
                "entrance_reply" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "type") and \
                "消息产生时" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "trigger_position"):
                asyncio.run(send_msg_to_live_comment_assistant(My_handle.config.get("luoxi_project", "Live_Comment_Assistant"), resp_content))
            
            # 是否启用了周期性触发功能，启用此功能后，数据会被缓存，之后周期到了才会触发
            if My_handle.config.get("thanks", "entrance", "periodic_trigger", "enable"):
                My_handle.task_data["thanks"]["entrance"]["data"].append(message)
            else:
                self.audio_synthesis_handle(message)

            return message
        except Exception as e:
            logger.error(traceback.format_exc())
            return None


    # 关注处理
    def follow_handle(self, data):
        try:
            # 合并字符串末尾连续的*  主要针对获取不到用户名的情况
            data['username'] = My_handle.common.merge_consecutive_asterisks(data['username'])
            # 删除用户名中的特殊字符
            data['username'] = My_handle.common.replace_special_characters(data['username'], "！!@#￥$%^&*_-+/——=()（）【】}|{:;<>~`\\")

            data['username'] = data['username'][:self.config.get("thanks", "username_max_len")]

            # 违禁处理
            data['username'] = self.prohibitions_handle(data['username'])
            if data['username'] is None:
                return None

            # 将用户名字符串中的数字转换成中文
            if My_handle.config.get("filter", "username_convert_digits_to_chinese"):
                data["username"] = My_handle.common.convert_digits_to_chinese(data["username"])

            # logger.debug(f"[{data['username']}]: {data['content']}")
        
            if not My_handle.config.get("thanks")["follow_enable"]:
                return None

            if My_handle.config.get("thanks", "follow_random"):
                resp_content = random.choice(My_handle.config.get("thanks", "follow_copy")).format(username=data["username"])
            else:
                # 类变量list中是否有数据，没有就拷贝下数据再顺序取出首个数据
                if len(My_handle.thanks_follow_copy) == 0:
                    if len(My_handle.config.get("thanks", "follow_copy")) == 0:
                        logger.warning("你把关注的文案删了，还触发个der关注感谢？不用别启用不就得了，删了搞啥")
                        return None
                    My_handle.thanks_follow_copy = copy.copy(My_handle.config.get("thanks", "follow_copy"))
                resp_content = My_handle.thanks_follow_copy.pop(0).format(username=data["username"])
            
            # 括号语法替换
            resp_content = My_handle.common.brackets_text_randomize(resp_content)

            # 检查是否使用助播TTS
            if data.get("_use_assistant_anchor_tts", False):
                # 使用助播TTS
                message = {
                    "type": "follow",
                    "tts_type": self.config.get("assistant_anchor", {}).get("audio_synthesis_type", "edge-tts"),
                    "data": self.config.get("assistant_anchor", {}).get("audio_synthesis_config", {}),
                    "config": My_handle.config.get("filter"),
                    "username": data['username'],
                    "content": resp_content,
                    "_use_assistant_anchor_tts": True
                }
                logger.info(f"关注感谢使用助播TTS配置")
            else:
                # 使用全局TTS
                tts_type, tts_config = My_handle.config.get_safe_tts_config()
                message = {
                    "type": "follow",
                    "tts_type": tts_type,
                    "data": tts_config,
                    "config": My_handle.config.get("filter"),
                    "username": data['username'],
                    "content": resp_content,
                    "_use_assistant_anchor_tts": False
                }
                logger.info(f"关注感谢使用全局TTS配置")

            # 助播功能已在 process_last_data 中统一处理，这里直接进行音频合成
            # 洛曦 直播弹幕助手
            if My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "enable") and \
                "follow_reply" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "type") and \
                "消息产生时" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "trigger_position"):
                asyncio.run(send_msg_to_live_comment_assistant(My_handle.config.get("luoxi_project", "Live_Comment_Assistant"), resp_content))
            

            # 是否启用了周期性触发功能，启用此功能后，数据会被缓存，之后周期到了才会触发
            if My_handle.config.get("thanks", "follow", "periodic_trigger", "enable"):
                My_handle.task_data["thanks"]["follow"]["data"].append(message)
            else:
                self.audio_synthesis_handle(message)

            return message
        except Exception as e:
            logger.error(traceback.format_exc())
            return None

    # 定时处理
    def schedule_handle(self, data):
        try:
            content = data["content"]
            logger.debug(f"schedule_handle开始处理定时任务: {content}")
            logger.debug(f"定时任务数据: {data}")

            # 检查是否标记了使用助播TTS
            if data.get("_use_assistant_anchor_tts", False):
                logger.info(f"定时任务标记为使用助播TTS: {data.get('_use_assistant_anchor_tts')}")
                # 使用助播TTS配置
                assistant_anchor_config = My_handle.config.get("assistant_anchor")
                if assistant_anchor_config and isinstance(assistant_anchor_config, dict):
                    audio_synthesis_type = assistant_anchor_config.get("audio_synthesis_type", "edge-tts")
                    # 安全获取TTS配置数据
                    tts_config = My_handle.config.get(audio_synthesis_type)
                    if isinstance(tts_config, dict):
                        tts_data = tts_config
                    else:
                        tts_data = {}
                    
                    message = {
                        "type": "schedule",
                        "tts_type": audio_synthesis_type,
                        "data": tts_data,
                        "config": My_handle.config.get("filter"),
                        "username": data['username'],
                        "content": content,
                        "_use_assistant_anchor_tts": True
                    }
                    logger.info(f"定时任务使用助播TTS配置: {audio_synthesis_type}")
                    logger.debug(f"创建的助播TTS消息: {message}")
                else:
                    # 如果助播配置无效，回退到全局TTS配置
                    global_tts_type = My_handle.config.get("audio_synthesis_type")
                    global_tts_config = My_handle.config.get(global_tts_type)
                    if isinstance(global_tts_config, dict):
                        global_tts_data = global_tts_config
                    else:
                        global_tts_data = {}
                    
                    message = {
                        "type": "schedule",
                        "tts_type": global_tts_type,
                        "data": global_tts_data,
                        "config": My_handle.config.get("filter"),
                        "username": data['username'],
                        "content": content,
                        "_use_assistant_anchor_tts": False
                    }
                    logger.warning(f"助播配置无效，定时任务使用全局TTS配置: {global_tts_type}")
                    logger.debug(f"创建的全局TTS消息: {message}")
            else:
                logger.info(f"定时任务未标记为使用助播TTS，使用全局TTS配置")
                # 使用全局TTS配置
                global_tts_type = My_handle.config.get("audio_synthesis_type")
                global_tts_config = My_handle.config.get(global_tts_type)
                if isinstance(global_tts_config, dict):
                    global_tts_data = global_tts_config
                else:
                    global_tts_data = {}
                
                message = {
                    "type": "schedule",
                    "tts_type": global_tts_type,
                    "data": global_tts_data,
                    "config": My_handle.config.get("filter"),
                    "username": data['username'],
                    "content": content,
                    "_use_assistant_anchor_tts": False
                }
                logger.debug(f"定时任务使用全局TTS配置: {global_tts_type}")
                logger.debug(f"创建的全局TTS消息: {message}")

            # 助播功能已在 process_last_data 中统一处理，这里直接进行音频合成
            # 洛曦 直播弹幕助手
            if My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "enable") and \
                "schedule" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "type") and \
                "消息产生时" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "trigger_position"):
                asyncio.run(send_msg_to_live_comment_assistant(My_handle.config.get("luoxi_project", "Live_Comment_Assistant"), content))
            
            logger.info(f"定时任务准备调用audio_synthesis_handle，消息类型: {message.get('type')}, TTS类型: {message.get('tts_type')}")
            self.audio_synthesis_handle(message)

            return message
        except Exception as e:
            logger.error(traceback.format_exc())
            return None

    """
.....................................................................................................................
..............:*.....................................-*=........:+-......................-*+.........................
..............:*%+.:#%%%%%%%%%%%%*..:+++++++-........=@+........+%=-++++++***##%%=......=%@*+++++++++++:.............
.............--.-+:............-@*..=%#+++*@*........=@+.......+%+.:=+++=+%#-:........-#%%%+-------=#%#:.............
.............%#.......+#.......-@*..=%+...-@*+@@@@@@@@@@@@+...=%*:.......-#*:.......:*%*:.+%*-...-*%*-...............
.............%#..::::-*#-:::::.-@*..=%+...-@*........=@+.....+%@+........-#*:.......+*:.....*%@%%%*..................
.............%#.-****#@%*****+.-%*..=%*:::=@*.-*=....=@+....+%%%+........-##:..........:-*%%%%+-*%%%%#+-::...........
.............%#.....:@@#:......-%*..=%*---+@*.:*%=...=@+...+@==#+.+%@@@@@@@@@@@@@@**%@@#=...#@:.......=*%%...........
.............%#....+%+*%#%*:...-%*..=%+...-@*..-#%=..=@+......=#+........-##:........+******%%#********:.............
.............%#..-%#:.*#:.=%#=.-%*..=%+...-@*...:-:..=@+......=#+........-#*:........::::::*%=-::::::#%:.............
.............%#-#%-...*#....=+:-%*..=%*---+@*........=@+......=#+........-#*:.............=%*:.......#@..............
.............%#.:.....+#.......-%*..=%#+++*@*........=@+......=#+........-#*:...........-#%+.........#@..............
.............%#.......::..:====*%+..-*=...:*=...-*++*%#-......=#+..+##############-.-=*%#+:...=++==+%%-..............
.............*+...........:****+:...............:----:........-*=...................=*=........--==-:................
.....................................................................................................................
    """
    # 闲时任务处理
    def idle_time_task_handle(self, data):
        try:
            type = data["type"]
            content = data["content"]
            username = data["username"]

            # 将用户名字符串中的数字转换成中文
            if My_handle.config.get("filter", "username_convert_digits_to_chinese"):
                username = My_handle.common.convert_digits_to_chinese(username)

            if type == "reread":
                # 输出当前用户发送的弹幕消息
                logger.info(f"[{username}]: {content}")

                # 弹幕格式检查和特殊字符替换和指定语言过滤
                content = self.comment_check_and_replace(content)
                if content is None:
                    return None
                
                # 判断按键映射触发类型
                if My_handle.config.get("key_mapping", "type") == "弹幕" or My_handle.config.get("key_mapping", "type") == "弹幕+回复":
                    # 按键映射 触发后不执行后面的其他功能
                    if self.key_mapping_handle("弹幕", data):
                        return None
                    
                # 判断自定义命令触发类型
                if My_handle.config.get("custom_cmd", "type") == "弹幕" or My_handle.config.get("custom_cmd", "type") == "弹幕+回复":
                    # 自定义命令 触发后不执行后面的其他功能
                    if self.custom_cmd_handle("弹幕", data):
                        return None

                # 音频合成时需要用到的重要数据
                # 检查是否应该使用助播TTS
                use_assistant_anchor_tts = data.get("_use_assistant_anchor_tts", False)
                
                if use_assistant_anchor_tts:
                    # 使用助播TTS配置
                    assistant_anchor_config = My_handle.config.get("assistant_anchor")
                    if assistant_anchor_config and isinstance(assistant_anchor_config, dict):
                        tts_type = assistant_anchor_config.get("audio_synthesis_type", "edge-tts")
                        tts_config = My_handle.config.get(tts_type, {})
                        logger.info(f"闲时任务使用助播TTS配置: {tts_type}")
                    else:
                        # 助播配置无效，回退到全局配置
                        tts_type = My_handle.config.get("audio_synthesis_type")
                        tts_config = My_handle.config.get(tts_type, {})
                        use_assistant_anchor_tts = False
                        logger.warning(f"助播配置无效，闲时任务回退到全局TTS配置: {tts_type}")
                else:
                    # 使用全局TTS配置
                    tts_type = My_handle.config.get("audio_synthesis_type")
                    tts_config = My_handle.config.get(tts_type, {})
                    logger.info(f"闲时任务使用全局TTS配置: {tts_type}")
                
                if isinstance(tts_config, dict):
                    tts_data = tts_config
                else:
                    tts_data = {}
                
                message = {
                    "type": "idle_time_task",
                    "tts_type": tts_type,
                    "data": tts_data,
                    "config": My_handle.config.get("filter"),
                    "username": username,
                    "content": content,
                    "content_type": type,
                    "_use_assistant_anchor_tts": use_assistant_anchor_tts
                }

                # 洛曦 直播弹幕助手
                if My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "enable") and \
                    "idle_time_task" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "type") and \
                    "消息产生时" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "trigger_position"):
                    asyncio.run(send_msg_to_live_comment_assistant(My_handle.config.get("luoxi_project", "Live_Comment_Assistant"), content))

                
                self.audio_synthesis_handle(message)

                return message
            elif type == "comment":
                # 记录数据库
                if My_handle.config.get("database", "comment_enable"):
                    insert_data_sql = '''
                    INSERT INTO danmu (username, content, ts) VALUES (?, ?, ?)
                    '''
                    self.db.execute(insert_data_sql, (username, content, datetime.now()))

                # 输出当前用户发送的弹幕消息
                logger.info(f"[{username}]: {content}")

                # 弹幕格式检查和特殊字符替换和指定语言过滤
                content = self.comment_check_and_replace(content)
                if content is None:
                    return None
                
                # 判断按键映射触发类型
                if My_handle.config.get("key_mapping", "type") == "弹幕" or My_handle.config.get("key_mapping", "type") == "弹幕+回复":
                    # 按键映射 触发后不执行后面的其他功能
                    if self.key_mapping_handle("弹幕", data):
                        return None
                    
                # 判断自定义命令触发类型
                if My_handle.config.get("custom_cmd", "type") == "弹幕" or My_handle.config.get("custom_cmd", "type") == "弹幕+回复":
                    # 自定义命令 触发后不执行后面的其他功能
                    if self.custom_cmd_handle("弹幕", data):
                        return None
                
                # 检查助播配置是否包含idle_time_task类型
                assistant_anchor_config = My_handle.config.get("assistant_anchor")
                if assistant_anchor_config and assistant_anchor_config.get("enable") and "idle_time_task" in assistant_anchor_config.get("type", []):
                    # 助播配置包含idle_time_task，优先尝试使用助播处理
                    data["content_type"] = type
                    if self.assistant_anchor_handle(data, "comment"):
                        return None
                
                # 如果助播未处理或不包含idle_time_task，继续全局流程
                if self.local_qa_handle(data):
                    return None

                # 2、点歌模式 触发后不执行后面的其他功能
                if self.choose_song_handle(data):
                    return None

                # 3、画图模式 触发后不执行后面的其他功能
                if self.sd_handle(data):
                    return None

                """
                根据聊天类型执行不同逻辑
                """ 
                chat_type = My_handle.config.get("chat_type")
                if chat_type == "game":
                    if My_handle.config.get("game", "enable"):
                        self.game.parse_keys_and_simulate_keys_press(content.split(), 2)
                    return None
                elif chat_type == "none":
                    return None
                else:
                    # 通用的data_json构造
                    data_json = {
                        "username": username,
                        "content": My_handle.config.get("before_prompt") + content + My_handle.config.get("after_prompt") if chat_type != "reread" else content,
                        "ori_username": data["username"],
                        "ori_content": data["content"]
                    }

                    logger.debug("data_json={data_json}")
                    
                    # 调用LLM统一接口，获取返回内容
                    resp_content = self.llm_handle(chat_type, data_json) if chat_type != "game" else ""

                    if resp_content:
                        logger.info(f"[AI回复{username}]：{resp_content}")
                    else:
                        logger.warning(f"警告：{chat_type}无返回")
                        resp_content = ""

                """
                双重过滤，为您保驾护航
                """
                resp_content = resp_content.replace('\n', '。')
                
                # LLM回复的内容进行违禁判断
                resp_content = self.prohibitions_handle(resp_content)
                if resp_content is None:
                    return None

                # logger.info("resp_content=" + resp_content)

                self.write_to_comment_log(resp_content, {"username": username, "content": content})

                # 判断按键映射触发类型
                if My_handle.config.get("key_mapping", "type") == "回复" or My_handle.config.get("key_mapping", "type") == "弹幕+回复":
                    # 替换内容
                    data["content"] = resp_content
                    # 按键映射 触发后不执行后面的其他功能
                    if self.key_mapping_handle("回复", data):
                        pass

                # 判断自定义命令射触发类型
                if My_handle.config.get("custom_cmd", "type") == "回复" or My_handle.config.get("custom_cmd", "type") == "弹幕+回复":
                    # 替换内容
                    data["content"] = resp_content
                    # 自定义命令 触发后不执行后面的其他功能
                    if self.custom_cmd_handle("回复", data):
                        pass
                    
                # 检查是否使用助播TTS
                if data.get("_use_assistant_anchor_tts", False):
                    # 使用助播TTS配置
                    assistant_anchor_config = My_handle.config.get("assistant_anchor")
                    if assistant_anchor_config and isinstance(assistant_anchor_config, dict):
                        audio_synthesis_type = assistant_anchor_config.get("audio_synthesis_type", "edge-tts")
                        # 安全获取TTS配置数据
                        tts_config = My_handle.config.get(audio_synthesis_type)
                        if isinstance(tts_config, dict):
                            tts_data = tts_config
                        else:
                            tts_data = {}
                        
                        message = {
                            "type": "idle_time_task",
                            "tts_type": audio_synthesis_type,
                            "data": tts_data,
                            "config": My_handle.config.get("filter"),
                            "username": username,
                            "content": resp_content,
                            "content_type": type,
                            "_use_assistant_anchor_tts": True
                        }
                        logger.info(f"闲时任务使用助播TTS配置: {audio_synthesis_type}")
                    else:
                        # 如果助播配置无效，回退到全局TTS配置
                        global_tts_type = My_handle.config.get("audio_synthesis_type")
                        global_tts_config = My_handle.config.get(global_tts_type)
                        if isinstance(global_tts_config, dict):
                            global_tts_data = global_tts_config
                        else:
                            global_tts_data = {}
                        
                        message = {
                            "type": "idle_time_task",
                            "tts_type": global_tts_type,
                            "data": global_tts_data,
                            "config": My_handle.config.get("filter"),
                            "username": username,
                            "content": resp_content,
                            "content_type": type,
                            "_use_assistant_anchor_tts": False
                        }
                        logger.warning(f"助播配置无效，闲时任务使用全局TTS配置: {global_tts_type}")
                else:
                    # 使用全局TTS配置
                    global_tts_type = My_handle.config.get("audio_synthesis_type")
                    global_tts_config = My_handle.config.get(global_tts_type)
                    if isinstance(global_tts_config, dict):
                        global_tts_data = global_tts_config
                    else:
                        global_tts_data = {}
                    
                    message = {
                        "type": "idle_time_task",
                        "tts_type": global_tts_type,
                        "data": global_tts_data,
                        "config": My_handle.config.get("filter"),
                        "username": username,
                        "content": resp_content,
                        "content_type": type,
                        "_use_assistant_anchor_tts": False
                    }
                    logger.info(f"闲时任务未标记为使用助播TTS，使用全局TTS配置: {global_tts_type}")

                # 洛曦 直播弹幕助手
                if My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "enable") and \
                    "idle_time_task" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "type") and \
                    "消息产生时" in My_handle.config.get("luoxi_project", "Live_Comment_Assistant", "trigger_position"):
                    asyncio.run(send_msg_to_live_comment_assistant(My_handle.config.get("luoxi_project", "Live_Comment_Assistant"), resp_content))

                
                self.audio_synthesis_handle(message)

                return message
            elif type == "local_audio":
                logger.info(f'[{username}]: {data["file_path"]}')

                message = {
                    "type": "idle_time_task",
                    "tts_type": My_handle.config.get("audio_synthesis_type"),
                    "data": My_handle.config.get(My_handle.config.get("audio_synthesis_type")),
                    "config": My_handle.config.get("filter"),
                    "username": username,
                    "content": content,
                    "content_type": type,
                    "file_path": os.path.abspath(data["file_path"])
                }

                self.audio_synthesis_handle(message)

                return message
        except Exception as e:
            logger.error(traceback.format_exc())
            return None



    # 图像识别 定时任务
    def image_recognition_schedule_handle(self, data):
        try:
            username = data["username"]
            content = My_handle.config.get("image_recognition", "prompt")
            # 区分图片源类型
            type = data["type"]

            # 将用户名字符串中的数字转换成中文
            if My_handle.config.get("filter", "username_convert_digits_to_chinese"):
                username = My_handle.common.convert_digits_to_chinese(username)

            if type == "窗口截图":
                # 根据窗口名截图
                screenshot_path = My_handle.common.capture_window_by_title(My_handle.config.get("image_recognition", "img_save_path"), My_handle.config.get("image_recognition", "screenshot_window_title"))
            elif type == "摄像头截图":
                # 根据摄像头索引截图
                screenshot_path = My_handle.common.capture_image(My_handle.config.get("image_recognition", "img_save_path"), int(My_handle.config.get("image_recognition", "cam_index")))

            # 通用的data_json构造
            data_json = {
                "username": username,
                "content": content,
                "img_data": screenshot_path,
                "ori_username": data["username"],
                "ori_content": content
            }
            
            # 调用LLM统一接口，获取返回内容
            resp_content = self.llm_handle(My_handle.config.get("image_recognition", "model"), data_json, type="vision")

            if resp_content:
                logger.info(f"[AI回复{username}]：{resp_content}")
            else:
                logger.warning(f'警告：{My_handle.config.get("image_recognition", "model")}无返回')
                resp_content = ""

            """
            双重过滤，为您保驾护航
            """
            resp_content = resp_content.replace('\n', '。')
            
            # LLM回复的内容进行违禁判断
            resp_content = self.prohibitions_handle(resp_content)
            if resp_content is None:
                return

            # logger.info("resp_content=" + resp_content)

            self.write_to_comment_log(resp_content, {"username": username, "content": content})

            # 判断按键映射触发类型
            if My_handle.config.get("key_mapping", "type") == "回复" or My_handle.config.get("key_mapping", "type") == "弹幕+回复":
                # 替换内容
                data["content"] = resp_content
                # 按键映射 触发后不执行后面的其他功能
                if self.key_mapping_handle("回复", data):
                    pass

            # 判断自定义命令触发类型
            if My_handle.config.get("custom_cmd", "type") == "回复" or My_handle.config.get("custom_cmd", "type") == "弹幕+回复":
                # 替换内容
                data["content"] = resp_content
                # 自定义命令 触发后不执行后面的其他功能
                if self.custom_cmd_handle("回复", data):
                    pass
                

            # 检查是否标记了使用助播TTS
            if data.get("_use_assistant_anchor_tts", False):
                # 使用助播TTS配置
                message = {
                    "type": "image_recognition_schedule",
                    "tts_type": self.assistant_anchor_manager.audio_synthesis_type,
                    "data": self.config.get(self.assistant_anchor_manager.audio_synthesis_type),
                    "config": My_handle.config.get("filter"),
                    "username": username,
                    "content": resp_content
                }
                logger.info(f"图像识别定时任务使用助播TTS配置")
            else:
                # 使用全局TTS配置
                message = {
                    "type": "image_recognition_schedule",
                    "tts_type": My_handle.config.get("audio_synthesis_type"),
                                            "data": My_handle.config.get(My_handle.config.get("audio_synthesis_type") or "edge-tts") or {},
                        "config": My_handle.config.get("filter"),
                        "username": username,
                        "content": resp_content
                }
                logger.debug(f"图像识别定时任务使用全局TTS配置")

            
            self.audio_synthesis_handle(message)
        except Exception as e:
            logger.error(traceback.format_exc())


    # 聊天处理（语音输入）
    def talk_handle(self, data):
        """聊天处理（语音输入）

        Args:
            data (dict): 包含用户名,弹幕内容

        Returns:
            dict: 传递给音频合成的JSON数据
        """

        try:
            username = data["username"]
            content = data["content"]

            # 输出当前用户发送的弹幕消息
            logger.debug(f"[{username}]: {content}")

            if My_handle.config.get("talk", "show_chat_log"):
                if "ori_username" not in data:
                    data["ori_username"] = data["username"]
                if "ori_content" not in data:
                    data["ori_content"] = data["content"]
                if "user_face" not in data:
                    data["user_face"] = 'https://robohash.org/ui'

                # 返回给webui的数据
                return_webui_json = {
                    "type": "llm",
                    "data": {
                        "type": "弹幕信息",
                        "username": data["ori_username"],
                        "user_face": data["user_face"],
                        "content_type": "question",
                        "content": data["ori_content"],
                        "timestamp": My_handle.common.get_bj_time(0)
                    }
                }
                webui_ip = "127.0.0.1" if My_handle.config.get("webui", "ip") == "0.0.0.0" else My_handle.config.get("webui", "ip")
                tmp_json = My_handle.common.send_request(f'http://{webui_ip}:{My_handle.config.get("webui", "port")}/callback', "POST", return_webui_json, timeout=10)
            

            # 记录数据库
            if My_handle.config.get("database", "comment_enable"):
                insert_data_sql = '''
                INSERT INTO danmu (username, content, ts) VALUES (?, ?, ?)
                '''
                self.db.execute(insert_data_sql, (username, content, datetime.now()))

            # 0、积分机制运转
            if self.integral_handle("comment", data):
                return
            if self.integral_handle("crud", data):
                return

            """
            用户名也得过滤一下，防止炸弹人
            """
            # 用户名以及弹幕违禁判断
            username = self.prohibitions_handle(username)
            if username is None:
                return
            
            content = self.prohibitions_handle(content)
            if content is None:
                return
            
            # 弹幕格式检查和特殊字符替换和指定语言过滤
            content = self.comment_check_and_replace(content)
            if content is None:
                return
            
            # 判断字符串是否全为标点符号，是的话就过滤
            if My_handle.common.is_punctuation_string(content):
                logger.debug(f"用户:{username}]，发送纯符号的弹幕，已过滤")
                return
            
            # 判断按键映射触发类型
            if My_handle.config.get("key_mapping", "type") == "弹幕" or My_handle.config.get("key_mapping", "type") == "弹幕+回复":
                # 按键映射 触发后不执行后面的其他功能
                if self.key_mapping_handle("弹幕", data):
                    return
                
            # 判断自定义命令触发类型
            if My_handle.config.get("custom_cmd", "type") == "弹幕" or My_handle.config.get("custom_cmd", "type") == "弹幕+回复":
                # 自定义命令 触发后不执行后面的其他功能
                if self.custom_cmd_handle("弹幕", data):
                    return
            

            # 1、本地问答库 处理
            # 优先尝试使用助播处理
            if self.assistant_anchor_handle(data, "comment"):
                return
            if self.local_qa_handle(data):
                return

            # 2、点歌模式 触发后不执行后面的其他功能
            if self.choose_song_handle(data):
                return

            # 3、画图模式 触发后不执行后面的其他功能
            if self.sd_handle(data):
                return
            
            # 4、弹幕内容是否进行翻译
            if My_handle.config.get("translate", "enable") and (My_handle.config.get("translate", "trans_type") == "弹幕" or \
                My_handle.config.get("translate", "trans_type") == "弹幕+回复"):
                tmp = My_handle.my_translate.trans(content)
                if tmp:
                    content = tmp
                    # logger.info(f"翻译后：{content}")

            # 5、联网搜索
            content = self.search_online_handle(content)

            data_json = {
                "username": username,
                "content": content,
                "ori_username": data["username"],
                "ori_content": data["content"]
            }

            """
            根据聊天类型执行不同逻辑
            """ 
            chat_type = My_handle.config.get("chat_type")
            if chat_type in self.chat_type_list:
                

                data_json["content"] = My_handle.config.get("before_prompt")
                # 是否启用弹幕模板
                if self.config.get("comment_template", "enable"):
                    # 假设有多个未知变量，用户可以在此处定义动态变量
                    variables = {
                        'username': username,
                        'comment': content,
                        'cur_time': My_handle.common.get_bj_time(5),
                    }

                    comment_template_copywriting = self.config.get("comment_template", "copywriting")
                    # 使用字典进行字符串替换
                    if any(var in comment_template_copywriting for var in variables):
                        content = comment_template_copywriting.format(**{var: value for var, value in variables.items() if var in comment_template_copywriting})

                data_json["content"] += content + My_handle.config.get("after_prompt")

                logger.debug(f"data_json={data_json}")
                
                # 当前选用的LLM类型是否支持stream，并且启用stream
                if "stream" in self.config.get(chat_type) and self.config.get(chat_type, "stream"):
                    logger.warning("使用流式推理LLM")
                    resp_content = self.llm_stream_handle_and_audio_synthesis(chat_type, data_json)
                    return resp_content
                else:
                    resp_content = self.llm_handle(chat_type, data_json)
                    if resp_content is not None:
                        logger.info(f"[AI回复{username}]：{resp_content}")
                    else:
                        resp_content = ""
                        logger.warning(f"警告：{chat_type}无返回")
            elif chat_type == "game":
                if My_handle.config.get("game", "enable"):
                    self.game.parse_keys_and_simulate_keys_press(content.split(), 2)
                return
            elif chat_type == "none":
                return
            elif chat_type == "reread":
                resp_content = self.llm_handle(chat_type, data_json)
            else:
                resp_content = content

            # 空数据结束
            if resp_content == "" or resp_content is None:
                return

            """
            双重过滤，为您保驾护航
            """
            resp_content = resp_content.strip()

            resp_content = resp_content.replace('\n', '。')
            
            # LLM回复的内容进行违禁判断
            resp_content = self.prohibitions_handle(resp_content)
            if resp_content is None:
                return None

            # logger.info("resp_content=" + resp_content)

            # 回复内容是否进行翻译
            if My_handle.config.get("translate", "enable") and (My_handle.config.get("translate", "trans_type") == "回复" or \
                My_handle.config.get("translate", "trans_type") == "弹幕+回复"):
                tmp = My_handle.my_translate.trans(resp_content)
                if tmp:
                    resp_content = tmp

            self.write_to_comment_log(resp_content, {"username": username, "content": content})

            # 判断按键映射触发类型
            if My_handle.config.get("key_mapping", "type") == "回复" or My_handle.config.get("key_mapping", "type") == "弹幕+回复":
                # 替换内容
                data["content"] = resp_content
                # 按键映射 触发后不执行后面的其他功能
                if self.key_mapping_handle("回复", data):
                    pass

            # 判断自定义命令触发类型
            if My_handle.config.get("custom_cmd", "type") == "回复" or My_handle.config.get("custom_cmd", "type") == "弹幕+回复":
                # 替换内容
                data["content"] = resp_content
                # 自定义命令 触发后不执行后面的其他功能
                if self.custom_cmd_handle("回复", data):
                    pass
                

            # 音频合成时需要用到的重要数据
            # 助播功能已在 process_last_data 中统一处理，这里直接进行音频合成
            message = {
                "type": "talk",
                "tts_type": My_handle.config.get("audio_synthesis_type"),
                "data": My_handle.config.get(My_handle.config.get("audio_synthesis_type") or "edge-tts") or {},
                "config": My_handle.config.get("filter"),
                "username": username,
                "content": resp_content
            }

            self.audio_synthesis_handle(message)

            return message
        except Exception as e:
            logger.error(traceback.format_exc())
            return None


    """
    数据丢弃部分
    增加新的处理事件时，需要进行这块部分的内容追加
    """
    def process_data(self, data, timer_flag):
        with self.data_lock:
            # 在数据处理流程的最早期进行预处理（表情清除和用户名数字转换）
            if timer_flag == "comment":
                data = self.preprocess_danmaku_data(data)
            
            # 多平台弹幕处理：先进行平台统计和去重检查
            if timer_flag == "comment":
                try:
                    # 1. 更新平台统计信息
                    platform = data.get('platform', 'unknown')
                    self.update_platform_stats(platform, 'received')
                    
                    # 2. 检查是否为重复弹幕
                    if self.is_duplicate_danmaku(data):
                        # logger.debug(f"检测到重复弹幕，已过滤: {data.get('content', '')}")
                        self.update_platform_stats(platform, 'filtered')
                        return
                    
                    # 3. 更新处理统计
                    self.update_platform_stats(platform, 'processed')
                    
                    # 获取当前待合成消息队列长度
                    current_queue_length = My_handle.audio.message_queue.qsize()
                    logger.debug(f"当前待合成消息队列长度: {current_queue_length}")
                    
                    # 智能三层队列处理策略（考虑优先级分布）
                    queue_pressure_info = self._analyze_queue_pressure_with_priority(data, current_queue_length)
                    
                    if queue_pressure_info["should_process"]:
                        # 根据优先级分析决定处理
                        logger.info(f"{queue_pressure_info['pressure_level']}(队列长度={current_queue_length})，弹幕进入处理流程: {data['content']}")
                        My_handle.is_handleing = 1
                        
                        # **修复：弹幕必须经过完整的处理流程，不能直接跳过本地知识库和LLM处理**
                        # 中压力且需要优先级插队时，在comment_handle内部进行插队
                        if (queue_pressure_info["pressure_level"] == "中压力-优先级处理" and 
                            queue_pressure_info["new_msg_priority"] >= 30):
                            data["_need_priority_insert"] = True
                            # logger.info(f"弹幕将在处理完成后进行优先级插队: {data['content']}")
                        
                        # 弹幕必须经过完整的comment_handle流程（本地知识库、LLM等）
                        try:
                            self.comment_handle(data)
                        except Exception as e:
                            logger.error(f"弹幕处理错误: {e}")
                            logger.error(traceback.format_exc())
                        finally:
                            My_handle.is_handleing = 0
                        return
                    elif queue_pressure_info.get("should_store_cyclically", False):
                        # 中压力或高压力：使用周期性储存
                        logger.info(f"{queue_pressure_info['pressure_level']}(队列长度={current_queue_length})，弹幕周期性储存: {data['content']}")
                        # 继续执行定时器逻辑，将弹幕储存等待周期处理
                    else:
                        # 异常情况，不应该到达这里
                        logger.warning(f"未知的队列压力处理结果: {queue_pressure_info}")
                        return
                except Exception as e:
                    # 静默处理多平台弹幕异常，回退到原有逻辑
                    logger.error(f"弹幕队列处理异常: {e}")
                    pass
            else:
                # 非弹幕类型直接处理（不受队列压力限制）
                logger.debug(f"非弹幕类型 {timer_flag} 直接处理")
                My_handle.is_handleing = 1
                try:
                    if timer_flag == "gift":
                        self.gift_handle(data)
                    elif timer_flag == "entrance":
                        self.entrance_handle(data)
                    elif timer_flag == "follow":
                        self.follow_handle(data)
                    elif timer_flag == "talk":
                        self.talk_handle(data)
                    elif timer_flag == "schedule":
                        logger.debug(f"处理定时任务类型，调用schedule_handle")
                        self.schedule_handle(data)
                    elif timer_flag == "idle_time_task":
                        self.idle_time_task_handle(data)
                    elif timer_flag == "image_recognition_schedule":
                        self.image_recognition_schedule_handle(data)
                    elif timer_flag == "read_comment":
                        self.reread_handle(data, filter=False, type="read_comment")
                except Exception as e:
                    logger.error(f"处理{timer_flag}类型消息时发生错误: {e}")
                    logger.error(traceback.format_exc())
                finally:
                    My_handle.is_handleing = 0
                return
            
            # 定时器逻辑（中压力状态的comment类型或其他类型）
            if timer_flag not in self.timers or not self.timers[timer_flag].is_alive():
                self.timers[timer_flag] = threading.Timer(self.get_interval(timer_flag), self.process_last_data, args=(timer_flag,))
                self.timers[timer_flag].start()
                logger.debug(f"启动定时器处理 {timer_flag}，等待时间: {self.get_interval(timer_flag)}秒")

            # 使用self.last_data统一存储数据，而不是给Timer对象添加属性
            if not hasattr(self, 'last_data'):
                self.last_data = {}
            
            if timer_flag in self.last_data:
                self.last_data[timer_flag].append(data)
                # 保留数据数量配置
                reserve_num_key = timer_flag + "_forget_reserve_num"
                max_reserve = int(My_handle.config.get("filter", reserve_num_key, 1))
                if len(self.last_data[timer_flag]) > max_reserve:
                    self.last_data[timer_flag].pop(0)
                    logger.debug(f"队列已满，移除最旧数据，当前队列长度: {len(self.last_data[timer_flag])}")
            else:
                self.last_data[timer_flag] = [data]

    def process_last_data(self, timer_flag):
        with self.data_lock:
            # 确保last_data属性存在
            if not hasattr(self, 'last_data'):
                self.last_data = {}
            
            if timer_flag in self.last_data and self.last_data[timer_flag] is not None and self.last_data[timer_flag] != []:
                # 根据comment_forget_reserve_num配置保留指定数量的最新弹幕
                if timer_flag == "comment":
                    reserve_num = My_handle.config.get("filter", "comment_forget_reserve_num", 1)
                    if len(self.last_data[timer_flag]) > reserve_num:
                        # 只保留最新的N条弹幕
                        self.last_data[timer_flag] = self.last_data[timer_flag][-reserve_num:]
                        logger.debug(f"弹幕队列保留最新{reserve_num}条，当前处理数量: {len(self.last_data[timer_flag])}")
                
                logger.debug(f"预处理定时器触发 type={timer_flag}，data={self.last_data[timer_flag]}")

                My_handle.is_handleing = 1

                for data in self.last_data[timer_flag]:
                    # 使用助播管理器统一处理
                    handled, result, continue_global = self.assistant_anchor_manager.process(data, timer_flag, self)
                    
                    if handled and result:
                        # 助播已处理，直接进行音频合成
                        logger.info(f"助播处理完成，使用助播TTS进行音频合成")
                        self.audio_synthesis_handle(result)
                    elif continue_global:
                        # 助播未处理或需要继续全局处理
                        logger.debug(f"助播未处理，继续全局处理流程")
                        
                        # 检查是否标记了使用助播TTS
                        use_assistant_anchor_tts = data.get("_use_assistant_anchor_tts", False)
                        
                        # 如果助播本地问答库未匹配，确保不使用助播TTS
                        if timer_flag == "comment" and not use_assistant_anchor_tts:
                            # 弹幕类型且未标记使用助播TTS，由全局TTS处理
                            logger.debug(f"弹幕类型由全局TTS处理")
                        
                        if timer_flag == "comment":
                            self.comment_handle(data)
                        elif timer_flag == "gift":
                            self.gift_handle(data)
                        elif timer_flag == "entrance":
                            # 入场处理已通过统一流程处理，避免重复调用
                            pass
                        elif timer_flag == "follow":
                            self.follow_handle(data)
                        elif timer_flag == "talk":
                            # 聊天暂时共用弹幕处理逻辑
                            self.talk_handle(data)
                        elif timer_flag == "schedule":
                            # 定时任务处理
                            logger.debug(f"处理定时任务类型，调用schedule_handle")
                            self.schedule_handle(data)
                        elif timer_flag == "idle_time_task":
                            # 闲时任务处理
                            self.idle_time_task_handle(data)
                        elif timer_flag == "image_recognition_schedule":
                            # 图像识别定时任务处理
                            self.image_recognition_schedule_handle(data)
                        elif timer_flag == "read_comment":
                            # 念弹幕处理
                            self.reread_handle(data, filter=False, type="read_comment")
                    else:
                        logger.debug(f"助播已处理，无需继续全局处理")

                My_handle.is_handleing = 0

                # 清空数据
                self.last_data[timer_flag] = []


    def _analyze_queue_pressure_with_priority(self, new_data, current_queue_length):
        """智能分析队列压力，考虑优先级分布
        
        Args:
            new_data: 新到达的数据
            current_queue_length: 当前队列长度
            
        Returns:
            dict: 包含压力分析结果的字典
        """

        try:

            # 使用配置的动态阈值，支持场景自适应
            low_load_threshold = My_handle.config.get("filter", "queue_low_load_threshold", 2)
            medium_load_threshold = My_handle.config.get("filter", "queue_medium_load_threshold", 4)

            # 获取新消息的优先级
            priority_mapping = My_handle.config.get("filter", "priority_mapping", {})
            new_msg_type = new_data.get("type", "comment")
            new_msg_priority = int(priority_mapping.get(new_msg_type, 0))
        
            
            # **修复：正确的三层压力处理逻辑**
            pressure_analysis = {
                "total_queue_length": current_queue_length,
                "new_msg_priority": new_msg_priority,
                "new_msg_type": new_msg_type
            }
            
            # 三层压力处理策略
            should_process = False
            should_store_cyclically = False
            pressure_level = ""
            
            if current_queue_length < low_load_threshold:
                # 第一层：低压力 - 弹幕信息直接进入处理流程，并根据优先级插队
                should_process = True
                pressure_level = "低压力"
            elif current_queue_length <= medium_load_threshold:
                # 第二层：中压力 - 判断队列优先级决定是否处理或周期性储存
                # 这里需要检查队列中是否有比当前消息优先级更低的消息
                has_lower_priority_in_queue = self._check_queue_has_lower_priority(new_msg_priority)
                
                if has_lower_priority_in_queue:
                    # 队列中有优先级更低的消息，立刻进入处理流程（会进行插队）
                    should_process = True
                    pressure_level = "中压力-优先级处理"
                else:
                    # 队列中消息优先级都大于或等于当前消息，周期性储存
                    should_process = False
                    should_store_cyclically = True
                    pressure_level = "中压力-周期储存"
            else:
                # 第三层：高压力 - 只进行周期性储存，不处理
                should_process = False
                should_store_cyclically = True
                pressure_level = "高压力-仅储存"
            
            pressure_analysis.update({
                "should_process": should_process,
                "should_store_cyclically": should_store_cyclically,
                "pressure_level": pressure_level,
                "decision_reason": f"优先级{new_msg_priority}，队列{current_queue_length}条"
            })
            
            return pressure_analysis
            
        except Exception as e:
            logger.error(f"队列压力分析异常: {e}")
            # 异常情况下回退到简单的队列长度判断
            if current_queue_length <= 4:
                return {
                    "should_process": True,
                    "should_store_cyclically": False,
                    "pressure_level": "低压力(回退)",
                    "total_queue_length": current_queue_length,
                    "new_msg_priority": 0,
                    "decision_reason": "分析异常，回退到简单判断"
                }
            else:
                return {
                    "should_process": False,
                    "should_store_cyclically": True,
                    "pressure_level": "高压力(回退)",
                    "total_queue_length": current_queue_length,
                    "new_msg_priority": 0,
                    "decision_reason": "分析异常，回退到简单判断"
                }
    
    def _check_queue_has_lower_priority(self, current_priority):
        """检查队列中是否有比当前消息优先级更低的消息
        
        Args:
            current_priority: 当前消息的优先级
            
        Returns:
            bool: 队列中是否存在更低优先级的消息
        """
        try:
            medium_load_threshold = My_handle.config.get("filter", "queue_medium_load_threshold", 4)
            if not hasattr(My_handle.audio, 'message_queue'):
                return False
            
            # 估算方法：基于队列长度和优先级分布经验
            queue_length = My_handle.audio.message_queue.qsize()
            
            # 如果队列为空，返回False
            if queue_length == 0:
                return False
            
            # 如果当前消息是高优先级，很可能队列中有更低优先级的
            if current_priority >= 50:
                return True
            # 如果当前消息是中优先级，队列较长时可能有低优先级的
            elif current_priority >= 40 and queue_length >= medium_load_threshold:
                return True
            # 如果当前消息是低优先级(<5)，不太可能插队
            else:
                return False
                
        except Exception as e:
            logger.error(f"检查队列优先级失败: {e}")
            # 异常时保守返回False，不进行插队
            return False

    def preprocess_danmaku_data(self, data):
        """在数据处理流程的最早期进行弹幕数据预处理
        包括表情清除和用户名数字转换功能
        
        Args:
            data (dict): 原始弹幕数据
            
        Returns:
            dict: 预处理后的数据
        """
        try:
            # 创建数据副本，避免修改原始数据
            processed_data = copy.deepcopy(data)
            
            # 1. 表情清除功能
            if My_handle.config.get("filter", "emoji", False):
                content = processed_data.get("content", "")
                if content:
                    from utils.emoji_utils import EmojiUtils
                    
                    # 使用统一的表情符号检测工具
                    processed_content = EmojiUtils.clean_text(content)
                    
                    if processed_content != content:
                        processed_data["content"] = processed_content
                        # logger.info(f"弹幕表情清除: '{content}' -> '{processed_content}'")
            
            # 2. 用户名数字转换功能
            if My_handle.config.get("filter", "username_convert_digits_to_chinese", False):
                username = processed_data.get("username", "")
                if username:
                    # 数字到中文的映射
                    digit_to_chinese = {
                        "0": "零", "1": "一", "2": "二", "3": "三", "4": "四",
                        "5": "五", "6": "六", "7": "七", "8": "八", "9": "九"
                    }
                    
                    # 替换用户名中的数字
                    processed_username = username
                    for digit, chinese in digit_to_chinese.items():
                        processed_username = processed_username.replace(digit, chinese)
                    
                    if processed_username != username:
                        processed_data["username"] = processed_username
                        # logger.info(f"用户名数字转换: '{username}' -> '{processed_username}'")
            
            return processed_data
            
        except Exception as e:
            logger.error(f"弹幕数据预处理出错: {e}")
            # 出错时返回原始数据
            return data

    def get_interval(self, timer_flag):
        # 根据标志定义不同计时器的间隔
        intervals = {
            "comment": My_handle.config.get("filter", "comment_forget_duration"),
            "gift": My_handle.config.get("filter", "gift_forget_duration"),
            "entrance": My_handle.config.get("filter", "entrance_forget_duration"),
            "follow": My_handle.config.get("filter", "follow_forget_duration"),
            "talk": My_handle.config.get("filter", "talk_forget_duration"),
            "schedule": My_handle.config.get("filter", "schedule_forget_duration"),
            "idle_time_task": My_handle.config.get("filter", "idle_time_task_forget_duration"),
            "read_comment": My_handle.config.get("filter", "read_comment_forget_duration", 0.1)
            # 根据需要添加更多计时器及其间隔，记得添加config.json中的配置项
        }

        # 默认间隔为0.1秒
        return intervals.get(timer_flag, 0.1)


    """
    异常报警
    """ 
    def abnormal_alarm_handle(self, type):
        """异常报警

        Args:
            type (str): 报警类型

        Returns:
            bool: True/False
        """

        try:
            My_handle.abnormal_alarm_data[type]["error_count"] += 1

            if not My_handle.config.get("abnormal_alarm", type, "enable"):
                return True
            
            if My_handle.config.get("abnormal_alarm", type, "type") == "local_audio":
                # 是否错误数大于 自动重启错误数
                if My_handle.abnormal_alarm_data[type]["error_count"] >= My_handle.config.get("abnormal_alarm", type, "auto_restart_error_num"):
                    data = {
                        "type": "restart",
                        "api_type": "api",
                        "data": {
                            "config_path": "config.json"
                        }
                    }

                    webui_ip = "127.0.0.1" if My_handle.config.get("webui", "ip") == "0.0.0.0" else My_handle.config.get("webui", "ip")
                    My_handle.common.send_request(f'http://{webui_ip}:{My_handle.config.get("webui", "port")}/sys_cmd', "POST", data)

                # 是否错误数小于 开始报警错误数，是则不触发报警
                if My_handle.abnormal_alarm_data[type]["error_count"] < My_handle.config.get("abnormal_alarm", type, "start_alarm_error_num"):
                    return

                path_list = My_handle.common.get_all_file_paths(My_handle.config.get("abnormal_alarm", type, "local_audio_path"))

                # 随机选择列表中的一个元素
                audio_path = random.choice(path_list)

                message = {
                    "type": "abnormal_alarm",
                    "tts_type": My_handle.config.get("audio_synthesis_type"),
                    "data": My_handle.config.get(My_handle.config.get("audio_synthesis_type") or "edge-tts") or {},
                    "config": My_handle.config.get("filter"),
                    "username": "系统",
                    "content": os.path.join(My_handle.config.get("abnormal_alarm", type, "local_audio_path"), My_handle.common.extract_filename(audio_path, True))
                }

                logger.warning(f"【异常报警-{type}】 {My_handle.common.extract_filename(audio_path, False)}")

                self.audio_synthesis_handle(message)

        except Exception as e:
            logger.error(traceback.format_exc())

            return False

        return True

    def assistant_anchor_handle(self, data, data_type):
        """助播功能统一处理函数
        
        Args:
            data (dict): 数据信息
            data_type (str): 数据类型 (comment, entrance, gift, follow, schedule, integral, read_comment)
            
        Returns:
            bool: True表示助播已处理，False表示需要继续全局处理
        """
        try:
            # 安全地获取助播配置
            assistant_anchor_config = My_handle.config.get("assistant_anchor")
            if not assistant_anchor_config:
                return False
                
            # 检查助播功能是否开启
            if not assistant_anchor_config.get("enable"):
                return False
            
            # 对于comment类型，无论助播type是否包含comment，都要进行本地问答匹配
            if data_type == "comment":
                logger.info(f'助播处理 [{data_type}] 类型数据: {data}')
                
                # 1、优先匹配助播本地问答库（音频）
                local_qa_audio_config = assistant_anchor_config.get("local_qa", {}).get("audio", {})
                if local_qa_audio_config.get("enable"):
                    username = assistant_anchor_config.get("username", "助播")
                    logger.info(f'尝试助播 本地问答库-音频匹配 [{username}]: {data["content"]}')
                    
                    # 根据类型，执行不同的问答匹配算法
                    if local_qa_audio_config.get("format") == "text":
                        local_qv_audio_filename = self.find_answer(data["content"], local_qa_audio_config.get("file_path", ""), local_qa_audio_config.get("similarity", 0.8))
                    else:
                        # 获取音频文件名列表
                        local_qa_audio_filename_list = My_handle.audio.get_dir_audios_filename(local_qa_audio_config.get("file_path", ""), type=1)
                        local_qv_audio_filename = My_handle.common.find_best_match(data["content"], local_qa_audio_filename_list, local_qa_audio_config.get("similarity", 0.8))
                    
                    if local_qv_audio_filename is not None:
                        # 寻找对应的文件
                        resp_content = My_handle.audio.search_files(local_qa_audio_config.get("file_path", ""), local_qv_audio_filename)
                        if resp_content != []:
                            logger.debug(f"匹配到的音频原相对路径：{resp_content[0]}")

                            # 拼接音频文件路径
                            resp_content = f'{local_qa_audio_config.get("file_path", "")}/{resp_content[0]}'
                            logger.info(f"助播 本地问答库-音频匹配成功，音频路径：{resp_content}")
                            
                            audio_synthesis_type = assistant_anchor_config.get("audio_synthesis_type", "edge-tts")
                            # 安全获取TTS配置数据
                            tts_config = My_handle.config.get(audio_synthesis_type) if audio_synthesis_type else None
                            if isinstance(tts_config, dict):
                                tts_data = tts_config
                            else:
                                tts_data = {}
                            
                            message = {
                                "type": "assistant_anchor_audio",
                                "tts_type": audio_synthesis_type,
                                "data": tts_data,
                                "config": My_handle.config.get("filter", {}),
                                "username": username,
                                "content": data["content"],
                                "file_path": resp_content
                            }

                            if "insert_index" in data:
                                message["insert_index"] = data["insert_index"]

                            # 使用助播TTS进行音频合成
                            My_handle.audio.audio_synthesis(message)
                            return True
                
                # 2、助播本地问答库（文本）
                local_qa_text_config = assistant_anchor_config.get("local_qa", {}).get("text", {})
                if local_qa_text_config.get("enable"):
                # 根据类型，执行不同的问答匹配算法
                    if local_qa_text_config.get("format") == "text":
                        tmp = self.find_answer(data["content"], local_qa_text_config.get("file_path", ""), local_qa_text_config.get("similarity", 0.8))
                    else:
                        tmp = self.find_similar_answer(data["content"], local_qa_text_config.get("file_path", ""), local_qa_text_config.get("similarity", 0.8))

                if tmp is not None:
                    username = assistant_anchor_config.get("username", "助播")
                    logger.info(f'触发助播 本地问答库-文本 [{username}]: {data["content"]}')
                    # 将问答库中设定的参数替换为指定内容，开发者可以自定义替换内容
                    variables = {
                        'cur_time': My_handle.common.get_bj_time(5),
                        'username': username
                    }

                    # 使用字典进行字符串替换
                    if any(var in tmp for var in variables):
                        tmp = tmp.format(**{var: value for var, value in variables.items() if var in tmp})

                    # [1|2]括号语法随机获取一个值，返回取值完成后的字符串
                    tmp = My_handle.common.brackets_text_randomize(tmp)
                    
                    logger.info(f"助播 本地问答库-文本回答为: {tmp}")

                    resp_content = tmp
                    # 将 AI 回复记录到日志文件中
                    self.write_to_comment_log(resp_content, {"username": username, "content": data["content"]})
                    
                    audio_synthesis_type = assistant_anchor_config.get("audio_synthesis_type", "edge-tts")
                    # 安全获取TTS配置数据
                    tts_config = My_handle.config.get(audio_synthesis_type)
                    if isinstance(tts_config, dict):
                        tts_data = tts_config
                    else:
                        tts_data = {}
                    
                    message = {
                        "type": "assistant_anchor_text",
                        "tts_type": audio_synthesis_type,
                        "data": tts_data,
                        "config": My_handle.config.get("filter", {}),
                        "username": username,
                        "content": resp_content
                    }

                    if "insert_index" in data:
                        message["insert_index"] = data["insert_index"]

                    # 使用助播TTS进行音频合成
                    My_handle.audio.audio_synthesis(message)
                    return True
                
                # 如果助播本地问答都没有匹配成功，但助播type包含comment，则标记使用助播TTS
                if data_type in assistant_anchor_config.get("type", []):
                    data["_use_assistant_anchor_tts"] = True
                    return False
                else:
                    # 助播type不包含comment，不处理
                    return False
            
            # 对于非comment类型，检查是否在助播处理范围内
            if data_type not in assistant_anchor_config.get("type", []):
                return False
            
            logger.info(f'助播处理 [{data_type}] 类型数据: {data}')
            
            # 3、如果助播本地问答未触发，则根据数据类型进行助播TTS处理
            # 对于某些类型（如入场、礼物、关注等），直接使用助播TTS
            if data_type in ["entrance", "gift", "follow", "schedule", "integral"]:
                # 这些类型直接由助播TTS处理，不需要LLM
                if data_type == "entrance" and My_handle.config.get("thanks", "entrance_enable"):
                    # 入场感谢处理
                    if My_handle.config.get("thanks", "entrance_random"):
                        resp_content = random.choice(My_handle.config.get("thanks", "entrance_copy")).format(username=data["username"])
                    else:
                        if len(My_handle.thanks_entrance_copy) == 0:
                            if len(My_handle.config.get("thanks", "entrance_copy")) == 0:
                                logger.warning("入场文案为空，跳过处理")
                                return False
                            My_handle.thanks_entrance_copy = copy.copy(My_handle.config.get("thanks", "entrance_copy"))
                        resp_content = My_handle.thanks_entrance_copy.pop(0).format(username=data["username"])
                    
                    resp_content = My_handle.common.brackets_text_randomize(resp_content)
                    
                    audio_synthesis_type = assistant_anchor_config.get("audio_synthesis_type", "edge-tts")
                    if isinstance(audio_synthesis_type, str):
                        message = {
                            "type": "assistant_anchor_entrance",
                            "tts_type": audio_synthesis_type,
                            "data": My_handle.config.get(audio_synthesis_type, {}),
                            "config": My_handle.config.get("filter", {}),
                            "username": data["username"],
                            "content": resp_content
                        }
                    else:
                        # 如果助播TTS类型配置无效，使用默认值
                        logger.warning(f"助播TTS类型配置无效: {audio_synthesis_type}，使用默认值 edge-tts")
                        message = {
                            "type": "assistant_anchor_entrance",
                            "tts_type": "edge-tts",
                            "data": My_handle.config.get("edge-tts", {}),
                            "config": My_handle.config.get("filter", {}),
                            "username": data["username"],
                            "content": resp_content
                        }
                    
                    # 使用助播TTS进行音频合成
                    My_handle.audio.audio_synthesis(message)
                    return True
                
                elif data_type == "gift" and My_handle.config.get("thanks", "gift_enable"):
                    # 礼物感谢处理
                    if My_handle.config.get("thanks", "gift_random"):
                        resp_content = random.choice(My_handle.config.get("thanks", "gift_copy")).format(username=data["username"], gift_name=data.get("gift_name", ""), price=data.get("price", 0))
                    else:
                        if len(My_handle.thanks_gift_copy) == 0:
                            if len(My_handle.config.get("thanks", "gift_copy")) == 0:
                                logger.warning("礼物文案为空，跳过处理")
                                return False
                            My_handle.thanks_gift_copy = copy.copy(My_handle.config.get("thanks", "gift_copy"))
                        resp_content = My_handle.thanks_gift_copy.pop(0).format(username=data["username"], gift_name=data.get("gift_name", ""), price=data.get("price", 0))
                    
                    resp_content = My_handle.common.brackets_text_randomize(resp_content)
                    
                    audio_synthesis_type = assistant_anchor_config.get("audio_synthesis_type", "edge-tts")
                    if isinstance(audio_synthesis_type, str):
                        message = {
                            "type": "assistant_anchor_gift",
                            "tts_type": audio_synthesis_type,
                            "data": My_handle.config.get(audio_synthesis_type, {}),
                            "config": My_handle.config.get("filter", {}),
                            "username": data["username"],
                            "content": resp_content
                        }
                    else:
                        # 如果助播TTS类型配置无效，使用默认值
                        logger.warning(f"助播TTS类型配置无效: {audio_synthesis_type}，使用默认值 edge-tts")
                        message = {
                            "type": "assistant_anchor_gift",
                            "tts_type": "edge-tts",
                            "data": My_handle.config.get("edge-tts", {}),
                            "config": My_handle.config.get("filter", {}),
                            "username": data["username"],
                            "content": resp_content
                        }
                    
                    # 使用助播TTS进行音频合成
                    My_handle.audio.audio_synthesis(message)
                    return True
                
                elif data_type == "follow" and My_handle.config.get("thanks", "follow_enable"):
                    # 关注感谢处理
                    if My_handle.config.get("thanks", "follow_random"):
                        resp_content = random.choice(My_handle.config.get("thanks", "follow_copy")).format(username=data["username"])
                    else:
                        if len(My_handle.thanks_follow_copy) == 0:
                            if len(My_handle.config.get("thanks", "follow_copy")) == 0:
                                logger.warning("关注文案为空，跳过处理")
                                return False
                            My_handle.thanks_follow_copy = copy.copy(My_handle.config.get("thanks", "follow_copy"))
                        resp_content = My_handle.thanks_follow_copy.pop(0).format(username=data["username"])
                    
                    resp_content = My_handle.common.brackets_text_randomize(resp_content)
                    
                    audio_synthesis_type = assistant_anchor_config.get("audio_synthesis_type", "edge-tts")
                    if isinstance(audio_synthesis_type, str):
                        message = {
                            "type": "assistant_anchor_follow",
                            "tts_type": audio_synthesis_type,
                            "data": My_handle.config.get(audio_synthesis_type, {}),
                            "config": My_handle.config.get("filter", {}),
                            "username": data["username"],
                            "content": resp_content
                        }
                    else:
                        # 如果助播TTS类型配置无效，使用默认值
                        logger.warning(f"助播TTS类型配置无效: {audio_synthesis_type}，使用默认值 edge-tts")
                        message = {
                            "type": "assistant_anchor_follow",
                            "tts_type": "edge-tts",
                            "data": My_handle.config.get("edge-tts", {}),
                            "config": My_handle.config.get("filter", {}),
                            "username": data["username"],
                            "content": resp_content
                        }
                    
                    # 使用助播TTS进行音频合成
                    My_handle.audio.audio_synthesis(message)
                    return True
            
            # 4、对于弹幕类型，如果助播本地问答未触发，则继续后续处理（全局本地问答、LLM等）
            # 但需要标记使用助播TTS，因为助播包含了comment类型
            if data_type == "comment":
                # 弹幕类型需要继续处理，但标记为使用助播TTS
                data["_use_assistant_anchor_tts"] = True
                return False
            
            # 5、念弹幕类型直接使用助播TTS
            if data_type == "read_comment":
                audio_synthesis_type = assistant_anchor_config.get("audio_synthesis_type", "edge-tts")
                if isinstance(audio_synthesis_type, str):
                    message = {
                        "type": "assistant_anchor_read_comment",
                        "tts_type": audio_synthesis_type,
                        "data": My_handle.config.get(audio_synthesis_type, {}),
                        "config": My_handle.config.get("filter", {}),
                        "username": data["username"],
                        "content": data["content"]
                    }
                else:
                    # 如果助播TTS类型配置无效，使用默认值
                    logger.warning(f"助播TTS类型配置无效: {audio_synthesis_type}，使用默认值 edge-tts")
                    message = {
                        "type": "assistant_anchor_read_comment",
                        "tts_type": "edge-tts",
                        "data": My_handle.config.get("edge-tts", {}),
                        "config": My_handle.config.get("filter", {}),
                        "username": data["username"],
                        "content": data["content"]
                    }
                
                # 使用助播TTS进行音频合成
                My_handle.audio.audio_synthesis(message)
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"助播处理异常: {traceback.format_exc()}")
            return False


    

    
    def _on_danmaku_message_received(self, message_data: dict):
        """处理从WebSocket接收到的弹幕消息 - 已废弃，多平台处理已迁移至danmaku_server"""
        logger.info("弹幕WebSocket消息处理功能已废弃，多平台处理已迁移至danmaku_server")
        return
    

    
    async def process_danmaku_message(self, message_data: dict) -> bool:
        """处理从danmaku_server接收到的弹幕数据"""
        try:
            # 消息去重检查
            current_time = time.time()
            message_key = f"{message_data.get('username', '')}_{message_data.get('content', '')}_{message_data.get('platform', '')}"
            
            # 清理过期的缓存条目
            expired_keys = [key for key, timestamp in self.message_dedup_cache.items() 
                          if current_time - timestamp > self.message_dedup_timeout]
            for key in expired_keys:
                del self.message_dedup_cache[key]
            
            # 检查是否为重复消息
            if message_key in self.message_dedup_cache:
                time_diff = current_time - self.message_dedup_cache[message_key]
                logger.warning(f"检测到重复弹幕消息，忽略处理: {message_data.get('content', '')} (时间间隔: {time_diff:.2f}秒)")
                return False
            
            # 记录消息到缓存
            self.message_dedup_cache[message_key] = current_time
            
            # logger.info(f"处理弹幕数据: {message_data.get('content', '')}")
            
            # 检查消息类型
            message_type = message_data.get('type', 'comment')
            
            # 根据消息类型设置timer_flag
            if message_type in ['gift', 'entrance', 'follow', 'like', 'super_chat']:
                self.timer_flag = message_type
            else:
                self.timer_flag = 'comment'
            
            # 根据消息类型调用相应的处理方法
            if message_type == 'comment':
                # 确保数据格式符合process_data的要求
                comment_data = {
                    'username': message_data.get('username', ''),
                    'content': message_data.get('content', ''),
                    'platform': message_data.get('platform', 'unknown')
                }
                
                # 使用三层队列处理策略处理弹幕
                result = self.process_data(comment_data, 'comment')
                return True
            else:
                logger.warning(f"暂不支持的消息类型: {message_type}")
                return False
            
        except Exception as e:
            logger.error(f"处理弹幕数据失败: {e}")
            return False

    async def handle_danmaku_websocket_message(self, message_data: dict):
        """处理来自DanmakuListener的WebSocket弹幕消息"""
        try:
            logger.debug(f"收到WebSocket弹幕消息: {message_data}")
            
            # 验证消息格式
            if not isinstance(message_data, dict):
                logger.warning(f"无效的弹幕消息格式: {type(message_data)}")
                return
            
            message_type = message_data.get('type', 'unknown')
            data = message_data.get('data', {})
            
            # 根据消息类型处理
            if message_type == 'comment':
                # 弹幕消息
                await self._handle_comment_message(data)
            elif message_type == 'gift':
                # 礼物消息
                await self._handle_gift_message(data)
            elif message_type == 'entrance':
                # 入场消息
                await self._handle_entrance_message(data)
            elif message_type == 'follow':
                # 关注消息
                await self._handle_follow_message(data)
            elif message_type == 'like':
                # 点赞消息
                await self._handle_like_message(data)
            elif message_type == 'super_chat':
                # 超级聊天消息
                await self._handle_super_chat_message(data)
            else:
                logger.warning(f"未知的弹幕消息类型: {message_type}")
                
        except Exception as e:
            logger.error(f"处理WebSocket弹幕消息异常: {e}")
            logger.error(traceback.format_exc())
    
    def _process_global_qa_text(self, data):
        """处理全局本地问答库文本匹配"""
        if not My_handle.config.get("local_qa", "text", "enable"):
            return None
        
        try:
            content = data.get("content")
            if not content:
                return None

            file_path = My_handle.config.get("local_qa", "text", "file_path")
            similarity = My_handle.config.get("local_qa", "text", "similarity")
            qa_format = My_handle.config.get("local_qa", "text", "format")

            if qa_format == "text":
                answer = self.find_answer(content, file_path, similarity)
            else:
                answer = self.find_similar_answer(content, file_path, similarity)

            if answer:
                logger.info(f'触发全局本地问答库-文本: {content}')
                answer = My_handle.common.brackets_text_randomize(answer)
                logger.info(f"全局本地问答库-文本回答为: {answer}")
                self.write_to_comment_log(answer, {"username": "全局问答", "content": content})
                
                return self.create_audio_message(data, "global_qa_text", answer, username="全局问答")

        except Exception as e:
            logger.error(f"全局本地问答库文本处理异常: {e}")
        
        return None

    def _process_global_qa_audio(self, data):
        """处理全局本地问答库音频匹配"""
        if not My_handle.config.get("local_qa", "audio", "enable"):
            return None

        try:
            content = data.get("content")
            if not content:
                return None

            audio_path = My_handle.config.get("local_qa", "audio", "file_path")
            similarity = My_handle.config.get("local_qa", "audio", "similarity")
            match_format = My_handle.config.get("local_qa", "audio", "format")

            filename_list = My_handle.audio.get_dir_audios_filename(audio_path, type=1)
            audio_list = My_handle.audio.get_dir_audios_filename(audio_path, type=0)
            matched_filename = None

            if match_format == "相似度匹配":
                matched_filename = My_handle.common.find_best_match(content, filename_list, similarity)
            elif match_format == "包含关系":
                for filename in filename_list:
                    if filename in content:
                        matched_filename = filename
                        break
            
            if matched_filename:
                logger.info(f'触发全局本地问答库-语音: {content}')
                full_filename = My_handle.common.find_best_match(matched_filename, audio_list, 0)
                resp_content = My_handle.audio.search_files(audio_path, full_filename)

                if resp_content:
                    audio_file = f'{audio_path}/{resp_content[0]}'
                    logger.info(f"匹配到的音频路径：{audio_file}")
                    
                    return {
                        "type": "global_qa_audio",
                        "tts_type": "metahuman_stream", # 默认为 metahuman_stream
                        "data": {},
                        "config": My_handle.config.get("filter"),
                        "username": "全局问答",
                        "content": content,
                        "file_path": audio_file
                    }

        except Exception as e:
            logger.error(f"全局本地问答库音频处理异常: {e}")

        return None

    def _handle_llm_request(self, data):
        """处理LLM请求和响应"""
        # 根据助播是否处理comment类型，决定LLM响应由谁处理
        use_assistant_anchor = self.assistant_anchor_manager.should_handle("comment")
        if use_assistant_anchor:
            data["_use_assistant_anchor_tts"] = True
            logger.info("LLM请求将由助播处理")
        else:
            logger.info("LLM请求将由全局流程处理")
        
        # 调用原有的LLM处理逻辑
        try:
            # 构建LLM请求数据
            username = data.get("username", "")
            content = data.get("content", "")
            
            data_json = {
                "username": username,
                "content": content,
                "ori_username": data.get("username", ""),
                "ori_content": data.get("content", "")
            }
            
            # 添加prompt
            before_prompt = My_handle.config.get("before_prompt") or ""
            after_prompt = My_handle.config.get("after_prompt") or ""
            data_json["content"] = before_prompt + content + after_prompt
            
            chat_type = My_handle.config.get("chat_type")
            resp_content = None
            
            # 根据chat_type调用相应的LLM处理方法
            if chat_type in self.chat_type_list:
                # 检查是否支持流式处理
                if "stream" in self.config.get(chat_type, {}) and self.config.get(chat_type, {}).get("stream", False):
                    logger.info("使用流式推理LLM")
                    resp_content = self.llm_stream_handle_and_audio_synthesis(chat_type, data_json)
                else:
                    resp_content = self.llm_handle(chat_type, data_json)
                    if resp_content is not None:
                        logger.info(f"[AI回复{username}]：{resp_content}")
                        # 如果由助播处理，返回消息；否则直接处理音频合成
                        if use_assistant_anchor:
                            return self._create_audio_message(username, resp_content, data)
                        else:
                            self._create_and_send_audio_message(username, resp_content, data)
                    else:
                        logger.warning(f"警告：{chat_type}无返回")
            elif chat_type == "reread":
                resp_content = self.llm_handle(chat_type, data_json)
                if resp_content:
                    if use_assistant_anchor:
                        return self._create_audio_message(username, resp_content, data)
                    else:
                        self._create_and_send_audio_message(username, resp_content, data)
            else:
                logger.warning(f"未知的chat_type: {chat_type}")
                
        except Exception as e:
            logger.error(f"LLM请求处理异常: {e}")
            logger.error(traceback.format_exc())
        
        return None
    
    def _create_audio_message(self, username, resp_content, data):
        """创建音频合成消息（不直接发送）"""
        try:
            # 检查是否应该使用助播TTS配置
            use_assistant_tts = data.get("_use_assistant_anchor_tts", False)
            
            if use_assistant_tts:
                assistant_anchor_config = My_handle.config.get("assistant_anchor", {})
                assistant_tts_type = assistant_anchor_config.get("audio_synthesis_type")
                if isinstance(assistant_tts_type, str):
                    message = {
                        "type": "comment",
                        "tts_type": assistant_tts_type,
                        "data": My_handle.config.get(assistant_tts_type) or {},
                        "config": My_handle.config.get("filter"),
                        "username": username,
                        "content": resp_content,
                        "_use_assistant_anchor_tts": True
                    }
                    logger.info(f"弹幕LLM回复使用助播TTS配置: {assistant_tts_type}")
                else:
                    # 如果助播TTS类型配置无效，使用默认值
                    logger.warning(f"助播TTS类型配置无效: {assistant_tts_type}，使用默认值 edge-tts")
                    message = {
                        "type": "comment",
                        "tts_type": "edge-tts",
                        "data": My_handle.config.get("edge-tts") or {},
                        "config": My_handle.config.get("filter"),
                        "username": username,
                        "content": resp_content,
                        "_use_assistant_anchor_tts": True
                    }
            else:
                global_tts_type = My_handle.config.get("audio_synthesis_type")
                if isinstance(global_tts_type, str):
                    message = {
                        "type": "comment",
                        "tts_type": global_tts_type,
                        "data": My_handle.config.get(global_tts_type) or {},
                        "config": My_handle.config.get("filter"),
                        "username": username,
                        "content": resp_content
                    }
                    logger.debug(f"弹幕LLM回复使用全局TTS配置: {global_tts_type}")
                else:
                    # 如果全局TTS类型配置无效，使用默认值
                    logger.warning(f"全局TTS类型配置无效: {global_tts_type}，使用默认值 edge-tts")
                    message = {
                        "type": "comment",
                        "tts_type": "edge-tts",
                        "data": My_handle.config.get("edge-tts") or {},
                        "config": My_handle.config.get("filter"),
                        "username": username,
                        "content": resp_content
                    }
            
            return message
            
        except Exception as e:
            logger.error(f"创建音频消息异常: {e}")
            logger.error(traceback.format_exc())
            return None
    
    def _create_and_send_audio_message(self, username, resp_content, data):
        """创建并发送音频合成消息"""
        try:
            # 检查是否应该使用助播TTS配置
            use_assistant_tts = data.get("_use_assistant_anchor_tts", False)
            
            if use_assistant_tts:
                assistant_anchor_config = My_handle.config.get("assistant_anchor", {})
                assistant_tts_type = assistant_anchor_config.get("audio_synthesis_type")
                if isinstance(assistant_tts_type, str):
                    message = {
                        "type": "comment",
                        "tts_type": assistant_tts_type,
                        "data": My_handle.config.get(assistant_tts_type) or {},
                        "config": My_handle.config.get("filter"),
                        "username": username,
                        "content": resp_content,
                        "_use_assistant_anchor_tts": True
                    }
                    logger.info(f"弹幕LLM回复使用助播TTS配置: {assistant_tts_type}")
                else:
                    # 如果助播TTS类型配置无效，使用默认值
                    logger.warning(f"助播TTS类型配置无效: {assistant_tts_type}，使用默认值 edge-tts")
                    message = {
                        "type": "comment",
                        "tts_type": "edge-tts",
                        "data": My_handle.config.get("edge-tts") or {},
                        "config": My_handle.config.get("filter"),
                        "username": username,
                        "content": resp_content,
                        "_use_assistant_anchor_tts": True
                    }
            else:
                global_tts_type = My_handle.config.get("audio_synthesis_type")
                if isinstance(global_tts_type, str):
                    message = {
                        "type": "comment",
                        "tts_type": global_tts_type,
                        "data": My_handle.config.get(global_tts_type) or {},
                        "config": My_handle.config.get("filter"),
                        "username": username,
                        "content": resp_content
                    }
                    logger.debug(f"弹幕LLM回复使用全局TTS配置: {global_tts_type}")
                else:
                    # 如果全局TTS类型配置无效，使用默认值
                    logger.warning(f"全局TTS类型配置无效: {global_tts_type}，使用默认值 edge-tts")
                    message = {
                        "type": "comment",
                        "tts_type": "edge-tts",
                        "data": My_handle.config.get("edge-tts") or {},
                        "config": My_handle.config.get("filter"),
                        "username": username,
                        "content": resp_content
                    }
            
            # 合成音频
            self.audio_synthesis_handle(message)
            
        except Exception as e:
            logger.error(f"创建音频消息异常: {e}")
            logger.error(traceback.format_exc())

    def _handle_comment(self, data):
        """处理评论消息，根据优先级进行问答匹配
        优先级顺序：
        1. 助播本地音频
        2. 全局本地音频
        3. 助播本地文本
        4. 全局本地文本
        5. LLM回复
        """
        content = data.get("content")
        if not content:
            return

        # 优先级1: 助播本地音频
        if getattr(self.assistant_anchor_manager, "local_qa_audio_enabled", False):
            message = self.assistant_anchor_manager._process_local_qa_audio(data, "comment", self)
            if message:
                logger.info("匹配到助播本地音频，由助播处理")
                return message

        # 优先级2: 全局本地音频
        if My_handle.config.get("local_qa", "audio", "enable"):
            try:
                message = self._process_global_qa_audio(data)
            except Exception:
                # 兼容旧结构：如果方法不可用，则直接返回 None
                message = None
            if message:
                # 根据设计，若助播选择 local_qa_audio，则由助播处理
                if self.assistant_anchor_manager.should_handle("local_qa_audio"):
                    logger.info("匹配到全局本地音频，由助播处理")
                    message["tts_type"] = self.assistant_anchor_manager.audio_synthesis_type
                    message["data"] = My_handle.config.get(self.assistant_anchor_manager.audio_synthesis_type) or {}
                    return message
                else:
                    logger.info("匹配到全局本地音频，由全局流程处理")
                    if self.audio:
                        self.audio.audio_synthesis(message)
                return

        # 优先级3: 助播本地文本
        if getattr(self.assistant_anchor_manager, "local_qa_enabled", False):
            message = self.assistant_anchor_manager._process_local_qa_text(data, "comment", self)
            if message:
                logger.info("匹配到助播本地文本，由助播处理")
                return message

        # 优先级4: 全局本地文本
        if My_handle.config.get("local_qa", "text", "enable"):
            try:
                message = self._process_global_qa_text(data)
            except Exception:
                message = None
            if message:
                logger.info("匹配到全局本地文本，由全局流程处理")
                if self.audio:
                    self.audio.audio_synthesis(message)
                return

        # 所有本地问答未匹配，进入LLM流程
        logger.info("所有本地问答未匹配，请求LLM")
        try:
            return self._handle_llm_request(data)
        except Exception as e:
            logger.error(f"LLM请求处理失败: {e}")
            logger.error(traceback.format_exc())
            return None

    async def _handle_comment_message(self, data: dict):
        """处理弹幕消息"""
        try:
            # 直接调用统一的弹幕处理逻辑
            await self.process_danmaku_message(data)
        except Exception as e:
            logger.error(f"处理评论消息异常: {e}")
    
    async def _handle_gift_message(self, data: dict):
        """处理礼物消息"""
        try:
            username = data.get('username', '未知用户')
            gift_name = data.get('gift_name', '未知礼物')
            gift_num = data.get('gift_num', 1)
            platform = data.get('platform', 'unknown')
            
            logger.info(f"收到礼物: {username} 送出 {gift_name} x{gift_num}")
            
            # 调用礼物处理逻辑
            self.gift_handle(data)
            
        except Exception as e:
            logger.error(f"处理礼物消息异常: {e}")
    
    async def _handle_entrance_message(self, data: dict):
        """处理入场消息"""
        try:
            username = data.get('username', '未知用户')
            platform = data.get('platform', 'unknown')
            
            logger.info(f"用户入场: {username} ({platform})")
            
            # 调用入场处理逻辑
            self.entrance_handle(data)
            
        except Exception as e:
            logger.error(f"处理入场消息异常: {e}")
    
    async def _handle_follow_message(self, data: dict):
        """处理关注消息"""
        try:
            username = data.get('username', '未知用户')
            platform = data.get('platform', 'unknown')
            
            logger.info(f"新关注: {username} ({platform})")
            
            # 调用关注处理逻辑
            self.follow_handle(data)
            
        except Exception as e:
            logger.error(f"处理关注消息异常: {e}")
    
    async def _handle_like_message(self, data: dict):
        """处理点赞消息"""
        try:
            username = data.get('username', '未知用户')
            platform = data.get('platform', 'unknown')
            
            logger.debug(f"点赞: {username} ({platform})")
            # TODO: 调用点赞处理逻辑
            
        except Exception as e:
            logger.error(f"处理点赞消息异常: {e}")
    
    async def _handle_super_chat_message(self, data: dict):
        """处理超级聊天消息"""
        try:
            username = data.get('username', '未知用户')
            content = data.get('content', '')
            price = data.get('price', 0)
            platform = data.get('platform', 'unknown')
            
            logger.info(f"超级聊天: {username} 支付 {price} - {content}")
            # TODO: 调用超级聊天处理逻辑
            
        except Exception as e:
            logger.error(f"处理超级聊天消息异常: {e}")
    
    async def start_danmaku_websocket_server(self):
        """启动弹幕WebSocket服务器"""
        try:
            if self.danmaku_websocket_server and not self.danmaku_websocket_server.running:
                await self.danmaku_websocket_server.start()
                logger.info("弹幕WebSocket服务器启动成功")
            else:
                logger.warning("弹幕WebSocket服务器未初始化或已在运行")
        except Exception as e:
            logger.error(f"启动弹幕WebSocket服务器失败: {e}")
    
    async def stop_danmaku_websocket_server(self):
        """停止弹幕WebSocket服务器"""
        try:
            if self.danmaku_websocket_server and self.danmaku_websocket_server.running:
                await self.danmaku_websocket_server.stop()
                logger.info("弹幕WebSocket服务器已停止")
        except Exception as e:
            logger.error(f"停止弹幕WebSocket服务器失败: {e}")
    
    def get_danmaku_websocket_status(self):
        """获取弹幕WebSocket服务器状态"""
        if hasattr(self, 'danmaku_websocket_server') and self.danmaku_websocket_server:
            return self.danmaku_websocket_server.get_status()
        else:
            return {
                "running": False,
                "enabled": False,
                "message": "弹幕WebSocket服务器未初始化"
            }
