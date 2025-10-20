import re
import threading
import asyncio
from copy import deepcopy
import aiohttp
import os, random
import copy
import traceback
import pygame
import queue
from queue import PriorityQueue
import time
from functools import wraps

from elevenlabs import generate, play, set_api_key
from pydub import AudioSegment

from utils.common import Common
from utils.logger import Configure_logger
from .config import Config
from utils.audio_handle.my_tts import MY_TTS
from utils.audio_handle.audio_player import AUDIO_PLAYER
from .dh_live_manager import DHLiveManager
from utils.language_utils import LanguageUtils
from utils.message_utils import MessageUtils


class Audio:
    """音频处理系统核心类"""
    
    # 类级别的单例实例
    instance = None
    
    # 全局关闭标志 - 用于优雅关闭所有音频线程
    should_shutdown = False
    
    # 文案播放标志 0手动暂停 1临时暂停 2循环播放
    copywriting_play_flag = -1
    
    # pygame.mixer实例
    mixer_normal = None
    mixer_copywriting = None
    mixer_assistant = None
    
    # 全局变量用于保存恢复文案播放计时器对象
    unpause_copywriting_play_timer = None
    
    # 音频播放器
    audio_player = None
    
    def __init__(self, config_path, type=1):
        """初始化音频处理系统
        
        Args:
            config_path: 配置文件路径
            type: 类型，1为正常模式，2为文案模式
        """
        self.config_path = config_path
        self.config = Config(config_path)
        
        # 初始化日志
        log_path = self.config.get("log", "log_path")
        if not log_path:
            log_path = "log/app.log"
        global logger
        logger = Configure_logger(log_path)
        
        self.common = Common()
        self.my_tts = MY_TTS(config_path)
        
        # 设置单例实例
        Audio.instance = self
        
        # 初始化队列系统
        self._init_queue_system()
        
        # 文案模式
        if type == 2:
            logger.info("文案模式的Audio初始化...")
            return
        
        # 初始化pygame mixer
        self._init_pygame_mixers()
        
        # 初始化音频播放器
        Audio.audio_player = AUDIO_PLAYER(self.config.get("audio_player"))

        # 初始化DH-LIVE管理器
        self.dh_live_manager = None
        try:
            assistant_cfg = self.config.get("assistant_anchor", {})
            dh_cfg = assistant_cfg.get("dh_live", {})
            if isinstance(dh_cfg, dict) and dh_cfg.get("enable", False):
                self.dh_live_manager = DHLiveManager(self.config)
                logger.info("DH-LIVE管理器已启用")
            else:
                logger.info("DH-LIVE管理器未启用")
        except Exception as e:
            logger.error(f"初始化DH-LIVE管理器失败: {e}")
            self.dh_live_manager = None
        
        # 启动音频处理线程
        self._start_audio_threads()
        
        logger.info("音频处理系统初始化完成")
    
    def is_queue_less_or_greater_than(self, queue_type, less=None, greater=None):
        """检查指定队列的长度是否小于或大于给定值"""
        queue_map = {
            "message": self.message_queue,
            "normal": self.global_audio_queue,
            "copywriting": self.copywriting_audio_queue,
            "assistant": self.assistant_audio_queue,
        }
        
        if queue_type not in queue_map:
            logger.warning(f"未知的队列类型: {queue_type}")
            return False
            
        queue_obj = queue_map[queue_type]
        queue_size = queue_obj.qsize()
        
        if less is not None and greater is not None:
            return less < queue_size < greater
        elif less is not None:
            return queue_size < less
        elif greater is not None:
            return queue_size > greater
            
        return False

    def get_dir_audios_filename(self, dir_path, type=0):
        """获取指定目录下的音频文件名列表
        
        Args:
            dir_path (str): 目录路径
            type (int): 返回类型，0表示返回完整文件名，1表示返回不含扩展名的文件名
            
        Returns:
            list: 音频文件名列表
        """
        if not os.path.exists(dir_path):
            logger.warning(f"目录不存在: {dir_path}")
            return []
            
        # 音频文件扩展名列表
        audio_extensions = ['.wav', '.mp3', '.ogg', '.flac']
        
        # 获取目录下所有文件
        files = os.listdir(dir_path)
        
        # 过滤出音频文件
        audio_files = [f for f in files if os.path.splitext(f)[1].lower() in audio_extensions]
        
        if type == 1:
            # 返回不含扩展名的文件名
            return [os.path.splitext(f)[0] for f in audio_files]
        else:
            # 返回完整文件名
            return audio_files

    def audio_synthesis(self, data_json):
        """音频合成入口方法
        
        Args:
            data_json (dict): 音频数据
        """
        try:
            if Audio.should_shutdown:
                logger.warning("音频系统已关闭，忽略合成请求")
                return
            
            # 标准化消息数据格式
            normalized_data = MessageUtils.normalize_message(data_json)
            if not MessageUtils.validate_message(normalized_data):
                logger.error("消息数据标准化失败")
                return
            
            logger.debug(f"音频合成请求: {normalized_data.get('type', 'unknown')} - {normalized_data.get('content', '')[:50]}...")
            # 检查是否为本地音频文件直接播放（如按键映射等）
            if "file_path" in normalized_data:
                logger.info(f"检测到本地音频文件，直接播放: {normalized_data['file_path']}")
                # 构造本地音频播放数据
                local_audio_data = {
                    "type": normalized_data.get('type', 'local_audio'),
                    "tts_type": "none",
                    "voice_path": normalized_data['file_path'],
                    "content": normalized_data.get("content", "")
                }
                
                if "insert_index" in normalized_data:
                    local_audio_data["insert_index"] = normalized_data["insert_index"]
                
                # 是否开启了音频播放
                if self.config.get("play_audio", "enable"):
                    # 直接添加到播放队列，不需要合成
                    self.data_priority_insert("voice_tmp_path", local_audio_data)
                return
            
            # 1. 预处理和切分消息
            message_fragments = self._preprocess_message_with_split(normalized_data)
            
            # 2. 将切分后的消息片段加入队列
            for fragment in message_fragments:
                try:
                    # 检查队列是否已满
                    if self.message_queue.qsize() >= self.message_queue.maxsize:
                        logger.warning("消息队列已满，丢弃最旧的消息")
                        try:
                            self.message_queue.get_nowait()
                        except queue.Empty:
                            pass
                    
                    # 创建优先级队列项 (priority, counter, message)
                    priority_mapping = self.config.get("filter", "priority_mapping")
                    msg_type = fragment.get("type")
                    mapping_priority = 0
                    if isinstance(priority_mapping, dict):
                        mapping_priority = priority_mapping.get(msg_type, 0)
                    try:
                        mapping_priority = int(mapping_priority)
                    except Exception:
                        mapping_priority = 0
                    # PriorityQueue数值越小越先出队，取负以保证“值越大优先级越高”
                    internal_priority = -mapping_priority
                    with self.message_queue_lock:
                        self.message_counter += 1
                        queue_item = (internal_priority, self.message_counter, fragment)
                    
                    # 添加到优先级队列
                    self.message_queue.put(queue_item, timeout=1.0)
                    logger.info(f"消息片段已加入合成队列，优先级(配置): {mapping_priority} -> 内部: {internal_priority}, 当前队列长度: {self.message_queue.qsize()}")
                    
                except queue.Full:
                    logger.warning("合成队列已满，无法添加新消息片段")
                except Exception as e:
                    logger.error(f"添加消息片段到队列时出错: {e}")

            # 3. 通知队列处理线程 (只需通知一次)
            with self.message_queue_lock:
                self.message_queue_not_empty.notify()

        except Exception as e:
            logger.error(f"音频合成处理失败: {e}")

    
    def _init_queue_system(self):
        """初始化队列系统"""
        # 从配置文件读取队列大小参数
        message_queue_max_len = self.config.get("filter", "message_queue_max_len")
        voice_tmp_path_queue_max_len = self.config.get("filter", "voice_tmp_path_queue_max_len")
        
        # 消息队列 - 存储待合成音频的json数据（优先级队列）
        self.message_queue = PriorityQueue(maxsize=message_queue_max_len)
        self.message_queue_lock = threading.Lock()
        self.message_queue_not_empty = threading.Condition(lock=self.message_queue_lock)
        self.message_counter = 0  # 用于保证相同优先级消息的FIFO顺序
        
        # 全局流程音频队列
        self.global_audio_queue = queue.Queue(maxsize=voice_tmp_path_queue_max_len)
        self.global_audio_queue_lock = threading.Lock()
        self.global_audio_queue_not_empty = threading.Condition(lock=self.global_audio_queue_lock)
        
        # 助播流程音频队列
        self.assistant_audio_queue = queue.Queue(maxsize=voice_tmp_path_queue_max_len)
        self.assistant_audio_queue_lock = threading.Lock()
        self.assistant_audio_queue_not_empty = threading.Condition(lock=self.assistant_audio_queue_lock)
        
        # 文案音频队列
        self.copywriting_audio_queue = queue.Queue(maxsize=voice_tmp_path_queue_max_len)
        self.copywriting_audio_queue_lock = threading.Lock()
        self.copywriting_audio_queue_not_empty = threading.Condition(lock=self.copywriting_audio_queue_lock)
        
        # 保持兼容性的旧队列（逐步迁移）- 改为list以支持len()和insert()操作
        self.voice_tmp_path_queue = []
        self.voice_tmp_path_queue_max_len = voice_tmp_path_queue_max_len
        self.voice_tmp_path_queue_lock = threading.Lock()
        self.voice_tmp_path_queue_not_empty = threading.Condition(lock=self.voice_tmp_path_queue_lock)
        
        # 播放状态控制锁
        self._play_locks = {
            'global': threading.Lock(),
            'assistant': threading.Lock(),
            'copywriting': threading.Lock(),
            'legacy': threading.Lock()
        }
        
        # 关闭状态锁
        self._shutdown_lock = threading.Lock()
        
        # 动态延时跟踪变量
        self.delay_tracking = {
            'global': {
                'next_delay_ms': 0,  # 下一条消息的延时时间(毫秒)
                'char_delay_rate': 180,  # 每个字符的延时时间(毫秒)
                'last_processed_time': 0  # 上次处理完成的时间戳
            },
            'assistant': {
                'next_delay_ms': 0,  # 下一条消息的延时时间(毫秒)
                'char_delay_rate': 120,
                'last_processed_time': 0  # 上次处理完成的时间戳
            }
        }
        
        # 异常报警数据
        self.abnormal_alarm_data = {
            "platform": {"error_count": 0},
            "llm": {"error_count": 0},
            "tts": {"error_count": 0},
            "svc": {"error_count": 0},
            "visual_body": {"error_count": 0},
            "other": {"error_count": 0}
        }
        
        # 播放队列状态标志
        self.voice_tmp_path_queue_not_empty_flag = False
        
        logger.info("音频队列系统初始化完成")
    
    def _init_pygame_mixers(self):
        """初始化pygame mixer实例"""
        if self.config.get("play_audio", "player") in ["pygame"]:
            import pygame
            
            # 初始化pygame
            pygame.mixer.pre_init(frequency=22050, size=-16, channels=2, buffer=512)
            pygame.mixer.init()
            
            # 初始化多个pygame.mixer实例
            Audio.mixer_normal = pygame.mixer
            Audio.mixer_copywriting = pygame.mixer
            Audio.mixer_assistant = pygame.mixer
            
            logger.info("pygame mixer初始化完成")
    
    
    def _start_audio_threads(self):
        """启动音频处理线程"""
        # 消息合成线程
        threading.Thread(
            target=lambda: asyncio.run(self.message_queue_thread()),
            daemon=True,
            name="MessageQueueThread"
        ).start()
        
        # 全局流程音频播放线程
        threading.Thread(
            target=lambda: asyncio.run(self.global_audio_playback_thread()),
            daemon=True,
            name="GlobalAudioThread"
        ).start()
        
        # 助播流程音频播放线程
        threading.Thread(
            target=lambda: asyncio.run(self.assistant_audio_playback_thread()),
            daemon=True,
            name="AssistantAudioThread"
        ).start()
        
        # 文案音频播放线程
        threading.Thread(
            target=lambda: asyncio.run(self.copywriting_audio_playback_thread()),
            daemon=True,
            name="CopywritingAudioThread"
        ).start()
        
        # 保持兼容性的旧播放线程（逐步迁移）
        threading.Thread(
            target=lambda: asyncio.run(self.legacy_audio_playback_thread()),
            daemon=True,
            name="LegacyAudioThread"
        ).start()
        
        logger.info("音频处理线程启动完成")
    
    async def message_queue_thread(self):
        """消息合成队列处理线程"""
        logger.info("消息合成队列线程启动")
        
        while not Audio.should_shutdown:
            try:
                # 获取消息（阻塞等待）
                try:
                    queue_item = self.message_queue.get(timeout=1.0)
                    # 从优先级队列项中提取消息 (priority, counter, message)
                    priority, counter, message = queue_item
                except queue.Empty:
                    continue
                
                # 日志中同时显示内部优先级与配置优先级（内部为负数，配置为其相反数）
                logger.debug(f"处理消息: {message.get('type', 'unknown')}, 优先级(内部): {priority}, 优先级(配置): {-priority}")
                
                # 在处理该消息前，仅对其所属流程应用动态延时（实现分流）
                try:
                    flow_type_for_message = "assistant" if self._is_assistant_anchor_message(message) else "global"
                    await self._apply_flow_specific_delay(flow_type_for_message)
                except Exception as _e:
                    logger.error(f"应用流程延时失败: {_e}")
                
                # 处理消息
                await self._process_message(message)
                
                # 根据当前消息内容为下一条消息计算延时
                flow_type, delay_ms = self._calculate_next_delay(message)
                if flow_type and delay_ms > 0:
                    current_time = time.time() * 1000
                    self.delay_tracking[flow_type]['next_delay_ms'] = delay_ms
                    self.delay_tracking[flow_type]['last_processed_time'] = current_time
                
                # 标记任务完成
                self.message_queue.task_done()
                
            except Exception as e:
                logger.error(f"消息队列处理出错: {e}")
                logger.error(traceback.format_exc())
    
    async def _process_message(self, message):
        """处理单个消息
        
        Args:
            message: 消息数据
        """
        try:
            # 判断消息类型和处理流程
            message_type = message.get('type', 'unknown')
            # logger.info(f"消息路由判断 - 类型: {message_type}")
            
            # 消息现在是预先切分好的片段，直接处理
            if self._should_use_metahuman_stream(message):
                # 使用metahuman_stream处理
                # logger.info(f"使用metahuman_stream处理消息片段: {message_type}")
                await self._process_metahuman_stream_message(message)
            elif self._is_assistant_anchor_message(message):
                # 助播流程处理
                # logger.info(f"使用助播流程处理消息片段: {message_type}")
                await self._process_assistant_message(message)
            elif self._is_copywriting_message(message):
                # 文案流程处理
                # logger.info(f"使用文案流程处理消息片段: {message_type}")
                await self._process_copywriting_message(message)
            else:
                # 全局流程处理
                # logger.info(f"使用全局流程处理消息片段: {message_type}")
                await self._process_global_message(message)
                
        except Exception as e:
            logger.error(f"处理消息出错: {e}")
            logger.error(traceback.format_exc())
    
    async def _apply_dynamic_delay(self):
        """应用基于上一条消息设置的动态延时"""
        try:
            current_time = time.time() * 1000  # 转换为毫秒
            
            # 检查全局流程延时
            global_delay = self.delay_tracking['global']
            if global_delay['next_delay_ms'] > 0:
                elapsed_time = current_time - global_delay['last_processed_time']
                remaining_delay = global_delay['next_delay_ms'] - elapsed_time
                
                if remaining_delay > 0:
                    delay_seconds = remaining_delay / 1000.0
                    logger.info(f"全局流程延时: {remaining_delay:.0f}ms")
                    await asyncio.sleep(delay_seconds)
                
                # 重置延时
                global_delay['next_delay_ms'] = 0
            
            # 检查助播流程延时
            assistant_delay = self.delay_tracking['assistant']
            if assistant_delay['next_delay_ms'] > 0:
                elapsed_time = current_time - assistant_delay['last_processed_time']
                remaining_delay = assistant_delay['next_delay_ms'] - elapsed_time
                
                if remaining_delay > 0:
                    delay_seconds = remaining_delay / 1000.0
                    logger.info(f"助播流程延时: {remaining_delay:.0f}ms")
                    await asyncio.sleep(delay_seconds)
                
                # 重置延时
                assistant_delay['next_delay_ms'] = 0
                
        except Exception as e:
            logger.error(f"应用动态延时出错: {e}")
            logger.error(traceback.format_exc())

    async def _apply_flow_specific_delay(self, flow_type: str):
        """仅对指定流程应用动态延时（global/assistant 分流）

        Args:
            flow_type: 流程类型，"global" 或 "assistant"
        """
        try:
            if flow_type not in ("global", "assistant"):
                return

            current_time = time.time() * 1000  # 毫秒
            delay_info = self.delay_tracking.get(flow_type, {})
            next_delay_ms = delay_info.get('next_delay_ms', 0)
            last_processed_time = delay_info.get('last_processed_time', 0)

            if next_delay_ms > 0:
                elapsed_time = current_time - last_processed_time
                remaining_delay = next_delay_ms - elapsed_time

                if remaining_delay > 0:
                    delay_seconds = remaining_delay / 1000.0
                    human_flow = "助播流程" if flow_type == "assistant" else "全局流程"
                    # logger.info(f"{human_flow}延时: {remaining_delay:.0f}ms")
                    await asyncio.sleep(delay_seconds)

                # 重置仅该流程的延时
                delay_info['next_delay_ms'] = 0
        except Exception as e:
            logger.error(f"应用{flow_type}流程延时出错: {e}")
            logger.error(traceback.format_exc())
    
    def _preprocess_message_with_split(self, message):
        """预处理消息，根据配置进行文本切分
        
        Args:
            message: 原始消息数据
            
        Returns:
            list: 处理后的消息片段列表
        """
        try:
            # 检查是否启用文本切分
            text_split_enabled = self.config.get("play_audio", "text_split_enable")
            # logger.info(f"文本切分配置状态: {text_split_enabled}")
            
            if not text_split_enabled:
                # 不切分，直接返回原消息
                return [message]
            
            content = message.get('content', '')
            if not content or len(content.strip()) == 0:
                return [message]
            
            # logger.info(f"开始文本切分预处理，原文本长度: {len(content)}字符")
            
            # 对文本进行切分
            sentences = self.common.split_sentences(content)
            # logger.info(f"文本切分完成，共{len(sentences)}个句子")
            
            # 为每个句子创建独立的消息片段
            message_fragments = []
            for i, sentence in enumerate(sentences):
                if not self.common.is_all_space_and_punct(sentence):
                    # 创建消息副本
                    message_copy = deepcopy(message)
                    message_copy["content"] = sentence
                    message_copy["fragment_index"] = i
                    message_copy["total_fragments"] = len(sentences)
                    message_copy["original_content"] = content
                    message_fragments.append(message_copy)
            
            # logger.info(f"生成{len(message_fragments)}个有效消息片段")
            return message_fragments if message_fragments else [message]
            
        except Exception as e:
            logger.error(f"文本切分预处理出错: {e}")
            return [message]
    
    def _calculate_next_delay(self, message):
        """计算下一条消息的延时

        Args:
            message: 已处理的消息
        
        Returns:
            (str, int): 计算出的延时类型 ('global' or 'assistant') 和延时毫秒数
        """
        try:
            content = message.get('content', '')
            if not content:
                return None, 0

            char_count = len(content)
            
            # 根据消息类型选择延时速率
            if self._is_assistant_anchor_message(message):
                delay_rate = self.delay_tracking['assistant']['char_delay_rate']
                flow_type = "assistant"
            else:
                delay_rate = self.delay_tracking['global']['char_delay_rate']
                flow_type = "global"

            # 计算延时
            delay_ms = char_count * delay_rate

            # 记录日志
            log_flow_type = "助播流程" if flow_type == "assistant" else "全局流程"
            if 'fragment_index' in message:
                fragment_info = f"片段{message['fragment_index']+1}/{message['total_fragments']}"
                # logger.info(f"{log_flow_type} - {fragment_info} 内容长度: {char_count}字符，计算延时: {delay_ms:.0f}ms")
            else:
                logger.info(f"{log_flow_type} - 消息内容长度: {char_count}字符，计算延时: {delay_ms:.0f}ms")
            
            return flow_type, delay_ms

        except Exception as e:
            logger.error(f"计算延时出错: {e}")
            logger.error(traceback.format_exc())
            return None, 0
    
    def _should_use_metahuman_stream(self, message):
        """判断是否应该使用metahuman_stream处理
        
        Args:
            message: 消息数据
            
        Returns:
            bool: 是否使用metahuman_stream
        """
        try:
            # 检查visual_body配置
            visual_body = self.config.get("visual_body")
            if visual_body != "metahuman_stream":
                return False
            
            # 检查是否明确标记使用metahuman_stream
            if message.get("_use_metahuman_stream", False):
                return True
            
            # 检查是否为助播功能明确标记的消息
            if self._is_assistant_anchor_message(message):
                return False
            
            # 检查是否为文案消息
            if self._is_copywriting_message(message):
                return False
            
            # 检查是否为纯音频类型（不需要metahuman_stream处理）
            # 注意：按照《系统逻辑设计说明》，全局流程应依据 visual_body 判断是否走 metahuman_stream，
            # 因此 idle_time_task 不应被视为纯音频而一刀切排除。
            audio_only_types = ['song', 'abnormal_alarm']  # 移除 'idle_time_task'
            if message.get('type', '') in audio_only_types:
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"判断metahuman_stream使用条件时出错: {e}")
            return False
    
    def _is_assistant_anchor_message(self, message):
        """判断是否为助播消息
        
        Args:
            message: 消息数据
            
        Returns:
            bool: 是否为助播消息
        """
        try:
            # 检查助播功能是否启用
            assistant_config = self.config.get("assistant_anchor")
            if not assistant_config or not assistant_config.get("enable", False):
                return False
            
            message_type = message.get('type', '')
            
            # 检查是否为助播类型
            if message_type.startswith("assistant_anchor_"):
                return True
            
            # 检查是否在助播支持的类型列表中
            supported_types = assistant_config.get("type", [])
            if message_type in supported_types:
                return True
            
            # 检查是否标记了使用助播TTS
            if message.get("_use_assistant_anchor_tts", False):
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"判断助播消息时出错: {e}")
            return False
    
    def _is_copywriting_message(self, message):
        """判断是否为文案消息
        
        Args:
            message: 消息数据
            
        Returns:
            bool: 是否为文案消息
        """
        message_type = message.get('type', '')
        copywriting_types = ['copywriting', 'copywriting2', 'copywriting3', 'copywriting4']
        return message_type in copywriting_types
    
    async def _process_metahuman_stream_message(self, message):
        """处理metahuman_stream消息
        
        Args:
            message: 消息数据
        """
        try:
            logger.debug(f"使用metahuman_stream处理消息: {message.get('type', 'unknown')}")
            
            # 发送到metahuman_stream进行完全托管
            await self._send_to_metahuman_stream(message)
            
        except Exception as e:
            logger.error(f"metahuman_stream处理出错: {e}")
            # 降级到全局流程处理
            await self._process_global_message(message)
    
    async def _process_assistant_message(self, message):
        """处理助播消息
        
        Args:
            message: 消息数据（已经过预处理切分）
        """
        try:
            logger.debug(f"使用助播流程处理消息: {message.get('type', 'unknown')}")
            
            # 特殊处理song类型消息 - 直接播放音频文件
            if message.get('type') == 'song':
                audio_path = message.get('content', '')
                if audio_path and os.path.exists(audio_path):
                    logger.info(f"直接播放音频文件: {audio_path}")
                    # 构造音频数据用于播放
                    audio_data = {
                        'type': 'song',
                        'file_path': audio_path,
                        'username': message.get('username', ''),
                        'content': message.get('content', ''),
                        'is_assistant': True
                    }
                    # 直接添加到助播队列播放
                    self._add_to_assistant_queue(audio_data)
                else:
                    logger.error(f"音频文件不存在: {audio_path}")
                return
            
            # 其他类型消息使用助播TTS合成音频
            audio_data = await self._synthesize_assistant_audio(message)
            
            if audio_data:
                # 判断是否需要转发给DH-LIVE
                if self._should_forward_to_dh_live(audio_data):
                    # 转发给DH-LIVE管理器
                    if self.dh_live_manager:
                        self.dh_live_manager.add_to_forward_queue(audio_data)
                    else:
                        # DH-LIVE管理器不可用，直接添加到助播队列
                        self._add_to_assistant_queue(audio_data)
                else:
                    # 直接添加到助播队列
                    self._add_to_assistant_queue(audio_data)
            
        except Exception as e:
            logger.error(f"助播消息处理出错: {e}")

    def _should_forward_to_dh_live(self, audio_data: dict) -> bool:
        """判断是否需要将音频转发至DH-LIVE
        
        条件：
        - 已初始化且启用DH-LIVE
        - 存在有效音频文件
        - 仅助播相关语音
        """
        try:
            if not getattr(self, "dh_live_manager", None):
                return False
            if not self.dh_live_manager.is_dh_live_enabled():
                return False
            if not isinstance(audio_data, dict):
                return False
            # 避免重复转发：若标记为已尝试或已成功转发，则不再转发
            if audio_data.get("dh_live_attempted") or audio_data.get("dh_live_forwarded"):
                return False
            audio_path = audio_data.get("file_path") or audio_data.get("audio_path")
            if not audio_path:
                return False
            try:
                import os
                if not os.path.exists(audio_path):
                    return False
            except Exception:
                return False
            if audio_data.get("is_assistant", False) or audio_data.get("type") in ("assistant", "song"):
                return True
            return False
        except Exception:
            return False
    
    async def _process_copywriting_message(self, message):
        """处理文案消息
        
        Args:
            message: 消息数据（已经过预处理切分）
        """
        try:
            logger.debug(f"使用文案流程处理消息: {message.get('type', 'unknown')}")
            
            # 合成文案音频
            audio_data = await self._synthesize_copywriting_audio(message)
            
            if audio_data:
                # 添加到文案队列
                self._add_to_copywriting_queue(audio_data)
            
        except Exception as e:
            logger.error(f"文案消息处理出错: {e}")
    
    async def _process_global_message(self, message):
        """处理全局消息
        
        Args:
            message: 消息数据（已经过预处理切分）
        """
        try:
            logger.debug(f"使用全局流程处理消息: {message.get('type', 'unknown')}")
            
            # 使用全局TTS合成音频
            audio_data = await self._synthesize_global_audio(message)
            
            if audio_data:
                # 添加到全局队列
                self._add_to_global_queue(audio_data)
            
        except Exception as e:
            logger.error(f"全局消息处理出错: {e}")
    
    async def global_audio_playback_thread(self):
        """全局流程音频播放线程"""
        logger.info("全局音频播放线程启动")
        
        while not Audio.should_shutdown:
            try:
                # 等待队列非空
                with self.global_audio_queue_lock:
                    while self.global_audio_queue.empty() and not Audio.should_shutdown:
                        self.global_audio_queue_not_empty.wait(timeout=1.0)
                
                if Audio.should_shutdown:
                    break
                
                # 获取音频数据
                try:
                    audio_data = self.global_audio_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                
                # 处理全局音频
                await self._process_global_audio(audio_data)
                
                # 标记任务完成
                self.global_audio_queue.task_done()
                
            except Exception as e:
                logger.error(f"全局音频播放线程出错: {e}")
                logger.error(traceback.format_exc())
    
    async def assistant_audio_playback_thread(self):
        """助播音频播放线程"""
        logger.info("助播音频播放线程启动")
        
        while not Audio.should_shutdown:
            try:
                # 等待队列非空
                with self.assistant_audio_queue_lock:
                    while self.assistant_audio_queue.empty() and not Audio.should_shutdown:
                        self.assistant_audio_queue_not_empty.wait(timeout=1.0)
                
                if Audio.should_shutdown:
                    break
                
                # 获取音频数据
                try:
                    audio_data = self.assistant_audio_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                
                # 等待当前助播音频播放完成
                if Audio.mixer_assistant and Audio.mixer_assistant.music.get_busy():
                    logger.debug("等待当前助播音频播放完成")
                    while Audio.mixer_assistant.music.get_busy() and not Audio.should_shutdown:
                        await asyncio.sleep(0.1)
                
                # 处理助播音频
                await self._process_assistant_audio(audio_data)
                
                # 标记任务完成
                self.assistant_audio_queue.task_done()
                
            except Exception as e:
                logger.error(f"助播音频播放线程出错: {e}")
                logger.error(traceback.format_exc())
    
    async def copywriting_audio_playback_thread(self):
        """文案音频播放线程"""
        logger.info("文案音频播放线程启动")
        
        while not Audio.should_shutdown:
            try:
                # 等待队列非空
                with self.copywriting_audio_queue_lock:
                    while self.copywriting_audio_queue.empty() and not Audio.should_shutdown:
                        self.copywriting_audio_queue_not_empty.wait(timeout=1.0)
                
                if Audio.should_shutdown:
                    break
                
                # 获取音频数据
                try:
                    audio_data = self.copywriting_audio_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                
                # 处理文案音频
                await self._process_copywriting_audio(audio_data)
                
                # 标记任务完成
                self.copywriting_audio_queue.task_done()
                
            except Exception as e:
                logger.error(f"文案音频播放线程出错: {e}")
                logger.error(traceback.format_exc())
    
    async def legacy_audio_playback_thread(self):
        """保持兼容性的旧播放线程（逐步迁移）"""
        logger.info("兼容性音频播放线程启动")
        
        while not Audio.should_shutdown:
            try:
                # 等待队列非空
                with self.voice_tmp_path_queue_lock:
                    while len(self.voice_tmp_path_queue) == 0 and not Audio.should_shutdown:
                        self.voice_tmp_path_queue_not_empty.wait(timeout=1.0)

                if Audio.should_shutdown:
                    break

                try:
                    # 从队列中获取音频数据
                    audio_data = self.voice_tmp_path_queue.pop(0) if self.voice_tmp_path_queue else None
                    if audio_data is None:
                        continue
                except Exception as e:
                    logger.error(f"获取音频数据时出错: {e}")
                    continue
                
                # 处理兼容性音频
                await self._process_legacy_audio(audio_data)
                
            except Exception as e:
                logger.error(f"兼容性音频播放线程出错: {e}")
                logger.error(traceback.format_exc())
    
    # 队列操作方法
    def priority_insert_message(self, message, force_insert=False):
        """优先级插队方法，允许高优先级消息直接插队到低优先级消息前面
        
        Args:
            message: 消息数据
            force_insert: 是否强制插队（不考虑队列是否已满）
            
        Returns:
            dict: 插入结果
        """
        try:
            # 检查系统是否正在关闭
            with self._shutdown_lock:
                if Audio.should_shutdown:
                    logger.warning("系统正在关闭，拒绝添加新消息")
                    return {"code": 1, "msg": "系统正在关闭"}
            
            # 验证消息数据
            if not isinstance(message, dict):
                logger.error(f"无效的消息数据类型: {type(message)}")
                return {"code": 1, "msg": "消息数据类型无效"}
            
            # 确保必要字段存在
            if "content" not in message:
                logger.error("消息缺少content字段")
                return {"code": 1, "msg": "消息缺少content字段"}
            
            # 设置默认优先级
            if "priority" not in message:
                message["priority"] = 5
            
            # 添加时间戳
            message["timestamp"] = time.time()
            
            # 获取优先级配置
            priority_mapping = self.config.get("filter", "priority_mapping", {})
            msg_type = message.get("type", "comment")
            mapping_priority = int(priority_mapping.get(msg_type, 0))
            
            with self.message_queue_lock:
                # 检查队列是否已满（除非强制插队）
                if not force_insert and self.message_queue.qsize() >= self.message_queue.maxsize:
                    logger.warning("消息队列已满，优先级插队失败")
                    return {"code": 1, "msg": "消息队列已满"}
                
                # 强制插队时，如果队列已满，移除最低优先级的消息
                if force_insert and self.message_queue.qsize() >= self.message_queue.maxsize:
                    # 从队列中找到优先级最低的消息并移除
                    temp_items = []
                    lowest_priority_item = None
                    lowest_config_priority = float('inf')
                    
                    # 获取所有项目进行分析
                    while not self.message_queue.empty():
                        try:
                            item = self.message_queue.get_nowait()
                            temp_items.append(item)
                            
                            if isinstance(item, tuple) and len(item) >= 3:
                                internal_priority, counter, msg_data = item
                                config_priority = -internal_priority
                                
                                # 找到优先级最低的消息
                                if config_priority < lowest_config_priority:
                                    lowest_config_priority = config_priority
                                    lowest_priority_item = item
                        except queue.Empty:
                            break
                    
                    # 移除优先级最低的消息
                    if lowest_priority_item:
                        temp_items.remove(lowest_priority_item)
                        logger.info(f"强制插队，移除低优先级消息，优先级: {lowest_config_priority}")
                    
                    # 将其余项目放回队列
                    for item in temp_items:
                        self.message_queue.put(item)
                
                # 创建优先级队列项
                internal_priority = -mapping_priority
                self.message_counter += 1
                queue_item = (internal_priority, self.message_counter, message)
                
                # 添加到优先级队列
                self.message_queue.put(queue_item, timeout=1.0)
                self.message_queue_not_empty.notify()
            
            logger.info(f"优先级插队成功，优先级(配置): {mapping_priority}, 当前队列长度: {self.message_queue.qsize()}")
            return {"code": 200, "msg": f"优先级插队成功，优先级: {mapping_priority}"}
            
        except queue.Full:
            logger.error("消息队列已满，优先级插队失败")
            return {"code": 1, "msg": "消息队列已满"}
        except Exception as e:
            logger.error(f"优先级插队失败: {e}")
            return {"code": 1, "msg": f"优先级插队失败: {str(e)}"}

    def add_message_to_queue(self, message):
        """添加消息到合成队列
        
        Args:
            message: 消息数据
        """
        try:
            # 检查系统是否正在关闭
            with self._shutdown_lock:
                if Audio.should_shutdown:
                    logger.warning("系统正在关闭，拒绝添加新消息")
                    return
            
            # 标准化消息数据格式
            normalized_data = MessageUtils.normalize_message(message)
            if not MessageUtils.validate_message(normalized_data):
                logger.warning("消息数据标准化失败")
                # 对于兼容性，仍然添加原始数据
                normalized_data = message
            
            with self.message_queue_lock:
                # 检查队列是否已满
                if self.message_queue.qsize() >= self.message_queue.maxsize:
                    logger.warning("消息队列已满，丢弃最旧的消息")
                    try:
                        old_queue_item = self.message_queue.get_nowait()
                        # 从元组中提取消息用于日志
                        if isinstance(old_queue_item, tuple) and len(old_queue_item) >= 3:
                            old_message = old_queue_item[2]
                            logger.debug(f"丢弃旧消息: {old_message.get('type', 'unknown')}")
                    except queue.Empty:
                        pass
                
                # 依据配置 priority_mapping 计算优先级（值越大优先级越高，队列内部取负）
                priority_mapping = self.config.get("filter", "priority_mapping")
                msg_type = normalized_data.get("type")
                mapping_priority = 0
                if isinstance(priority_mapping, dict):
                    mapping_priority = priority_mapping.get(msg_type, 0)
                try:
                    mapping_priority = int(mapping_priority)
                except Exception:
                    mapping_priority = 0
                internal_priority = -mapping_priority
                # 创建优先级队列项
                self.message_counter += 1
                queue_item = (internal_priority, self.message_counter, normalized_data)
                self.message_queue.put(queue_item, timeout=1.0)
                self.message_queue_not_empty.notify()
            logger.debug(f"消息已添加到合成队列: {message.get('type', 'unknown')}")
        except queue.Full:
            logger.error("消息队列已满，无法添加新消息")
        except Exception as e:
            logger.error(f"添加消息到队列失败: {e}")
    
    def _add_to_global_queue(self, audio_data):
        """添加音频到全局队列
        
        Args:
            audio_data: 音频数据
        """
        try:
            # 检查系统是否正在关闭
            with self._shutdown_lock:
                if Audio.should_shutdown:
                    logger.warning("系统正在关闭，拒绝添加新音频")
                    return
            
            # 标准化音频数据格式
            normalized_data = self._normalize_audio_data(audio_data)
            if not normalized_data:
                logger.warning("全局队列音频数据标准化失败")
                return
            
            with self.global_audio_queue_lock:
                # 检查队列是否已满
                if self.global_audio_queue.qsize() >= 50:
                    logger.warning("全局音频队列已满，丢弃最旧的音频")
                    try:
                        old_audio = self.global_audio_queue.get_nowait()
                        # 清理旧音频文件
                        self._cleanup_audio_file(old_audio.get('file_path'))
                    except queue.Empty:
                        pass
                
                self.global_audio_queue.put(normalized_data, timeout=1.0)
                self.global_audio_queue_not_empty.notify()
            logger.debug(f"音频已添加到全局队列: {normalized_data.get('file_path', 'unknown')}")
        except queue.Full:
            logger.error("全局音频队列已满，无法添加新音频")
        except Exception as e:
            logger.error(f"添加音频到全局队列失败: {e}")
    
    def _add_to_assistant_queue(self, audio_data):
        """添加音频到助播队列
        
        Args:
            audio_data: 音频数据
        """
        try:
            # 检查系统是否正在关闭
            with self._shutdown_lock:
                if Audio.should_shutdown:
                    logger.warning("系统正在关闭，拒绝添加新音频")
                    return
            
            # 标准化音频数据格式
            normalized_data = self._normalize_audio_data(audio_data)
            if not normalized_data:
                logger.warning("助播队列音频数据标准化失败")
                return
            
            with self.assistant_audio_queue_lock:
                # 检查队列是否已满
                if self.assistant_audio_queue.qsize() >= 50:
                    logger.warning("助播音频队列已满，丢弃最旧的音频")
                    try:
                        old_audio = self.assistant_audio_queue.get_nowait()
                        # 清理旧音频文件
                        self._cleanup_audio_file(old_audio.get('file_path'))
                    except queue.Empty:
                        pass
                
                self.assistant_audio_queue.put(normalized_data, timeout=1.0)
                self.assistant_audio_queue_not_empty.notify()
            logger.debug(f"音频已添加到助播队列: {normalized_data.get('file_path', 'unknown')}")
        except queue.Full:
            logger.error("助播音频队列已满，无法添加新音频")
        except Exception as e:
            logger.error(f"添加音频到助播队列失败: {e}")
    
    def _add_to_copywriting_queue(self, audio_data):
        """添加音频到文案队列
        
        Args:
            audio_data: 音频数据
        """
        try:
            # 检查系统是否正在关闭
            with self._shutdown_lock:
                if Audio.should_shutdown:
                    logger.warning("系统正在关闭，拒绝添加新音频")
                    return
            
            # 标准化音频数据格式
            normalized_data = self._normalize_audio_data(audio_data)
            if not normalized_data:
                logger.warning("文案队列音频数据标准化失败")
                return
            
            with self.copywriting_audio_queue_lock:
                # 检查队列是否已满
                if self.copywriting_audio_queue.qsize() >= 30:
                    logger.warning("文案音频队列已满，丢弃最旧的音频")
                    try:
                        old_audio = self.copywriting_audio_queue.get_nowait()
                        # 清理旧音频文件
                        self._cleanup_audio_file(old_audio.get('file_path'))
                    except queue.Empty:
                        pass
                
                self.copywriting_audio_queue.put(normalized_data, timeout=1.0)
                self.copywriting_audio_queue_not_empty.notify()
            logger.debug(f"音频已添加到文案队列: {normalized_data.get('file_path', 'unknown')}")
        except queue.Full:
            logger.error("文案音频队列已满，无法添加新音频")
        except Exception as e:
            logger.error(f"添加音频到文案队列失败: {e}")
    
    def _cleanup_audio_file(self, file_path):
        """清理音频文件
        
        Args:
            file_path: 音频文件路径
        """
        if not file_path or not isinstance(file_path, str):
            return
            
        try:
            import os
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.debug(f"已清理音频文件: {file_path}")
        except Exception as e:
            logger.warning(f"清理音频文件失败 {file_path}: {e}")
    
    def _normalize_audio_data(self, audio_data):
        """标准化音频数据格式
        
        Args:
            audio_data: 原始音频数据（可能是字符串路径或字典）
            
        Returns:
            dict: 标准化的音频数据格式
        """
        try:
            if not audio_data:
                return None
            
            # 如果是字符串，转换为标准格式
            if isinstance(audio_data, str):
                return {
                    "type": "legacy",
                    "audio_path": audio_data,
                    "file_path": audio_data,  # 兼容旧字段
                    "text": "",
                    "data_json": {},
                    "priority": 5,
                    "timestamp": time.time()
                }
            
            # 如果是字典，确保包含所有必要字段
            if isinstance(audio_data, dict):
                normalized = {
                    "type": audio_data.get("type", "unknown"),
                    "audio_path": audio_data.get("audio_path") or audio_data.get("file_path", "") or audio_data.get("voice_path", ""),
                    "file_path": audio_data.get("file_path") or audio_data.get("audio_path", "") or audio_data.get("voice_path", ""),  # 兼容性
                    "text": audio_data.get("text", audio_data.get("content", "")),
                    "data_json": audio_data.get("data_json", audio_data),
                    "priority": (audio_data.get("priority") if audio_data.get("priority") is not None else int((self.config.get("filter", "priority_mapping") or {}).get(audio_data.get("type"), 0))),
                    "timestamp": audio_data.get("timestamp", time.time())
                }
                
                # 保留其他字段
                for key, value in audio_data.items():
                    if key not in normalized:
                        normalized[key] = value
                
                return normalized
            
            logger.warning(f"不支持的音频数据格式: {type(audio_data)}")
            return None
            
        except Exception as e:
            logger.error(f"标准化音频数据异常: {e}")
            return None
    
    # 音频合成方法（占位符，需要实现具体逻辑）
    async def _synthesize_audio_with_config(self, message, audio_type, tts_config_path=None):
        """通用音频合成方法
        
        Args:
            message: 消息数据
            audio_type: 音频类型 (global/assistant/copywriting)
            tts_config_path: TTS配置路径 (可选)
            
        Returns:
            dict: 标准化的音频数据
        """
        try:
            logger.debug(f"开始合成{audio_type}音频: {message.get('content', '')}")
            
            # 备份原始TTS配置
            original_tts_config = None
            if tts_config_path:
                original_tts_config = self.my_tts.config.get("audio_synthesis")
                custom_tts_config = self.config
                for key in tts_config_path:
                    custom_tts_config = custom_tts_config.get(key, {})
                
                if custom_tts_config:
                    self.my_tts.config.config["audio_synthesis"] = custom_tts_config
            
            # 调用TTS处理方法进行音频合成
            result_message = await self.tts_handle(message)
            
            # 恢复原始TTS配置
            if original_tts_config:
                self.my_tts.config.config["audio_synthesis"] = original_tts_config
            
            # 检查合成结果
            if result_message and result_message.get("result", {}).get("code") == 200:
                audio_path = result_message["result"]["audio_path"]
                logger.info(f"{audio_type}音频合成成功: {audio_path}")
                audio_data = {
                    "type": audio_type,
                    "audio_path": audio_path,
                    "file_path": audio_path,  # 兼容性字段
                    "text": message.get("content", ""),
                    "data_json": message,
                    "priority": (message.get("priority") if message.get("priority") is not None else int((self.config.get("filter", "priority_mapping") or {}).get(audio_type, 0))),
                    "timestamp": time.time()
                }
                
                
                return self._normalize_audio_data(audio_data)
            else:
                logger.error(f"{audio_type}音频合成失败: {message.get('content', '')}")
                return None
                
        except Exception as e:
            logger.error(f"{audio_type}音频合成异常: {e}")
            logger.error(traceback.format_exc())
            return None
    
    async def _synthesize_global_audio(self, message):
        """合成全局音频
        
        Args:
            message: 消息数据
            
        Returns:
            dict: 音频数据
        """
        return await self._synthesize_audio_with_config(message, "global")
    
    async def _synthesize_assistant_audio(self, message):
        """合成助播音频
        
        Args:
            message: 消息数据
            
        Returns:
            dict: 音频数据（已标记 is_assistant=True，确保DH-LIVE转发判断成立）
        """
        # 获取助播TTS类型
        assistant_config = self.config.get("assistant_anchor", {})
        tts_type = assistant_config.get("audio_synthesis_type", "edge-tts")
        
        # 使用助播TTS类型对应的配置路径执行合成
        audio_data = await self._synthesize_audio_with_config(
            message,
            tts_type,
            ["audio_synthesis", tts_type]
        )
        
        # 标记为助播来源，满足 _should_forward_to_dh_live 判断
        if isinstance(audio_data, dict):
            try:
                audio_data["is_assistant"] = True
                # 记录助播所用的TTS类型，便于后续排查（不影响既有逻辑）
                audio_data.setdefault("assistant_tts_type", tts_type)
            except Exception:
                pass
        
        return audio_data
    
    async def _synthesize_copywriting_audio(self, message):
        """合成文案音频
        
        Args:
            message: 消息数据
            
        Returns:
            dict: 音频数据
        """
        return await self._synthesize_audio_with_config(
            message, 
            "copywriting", 
            ["copywriting", "audio_synthesis"]
        )
    
    # 根据本地配置，使用TTS进行音频合成，返回相关数据
    async def tts_handle(self, message):
        """根据本地配置，使用TTS进行音频合成，返回相关数据

        Args:
            message (dict): json数据，含tts配置，tts类型

        Returns:
            dict: json数据，含tts配置，tts类型，合成结果等信息
        """
        try:
            voice_tmp_path = None
            
            # 验证消息结构
            if not isinstance(message, dict):
                raise ValueError("message必须是字典类型")
            
            if "tts_type" not in message:
                raise ValueError("message缺少tts_type字段")
            
            if "content" not in message:
                raise ValueError("message缺少content字段")
            
            # 确保data字段存在
            if "data" not in message:
                message["data"] = {}
            
            # TTS预处理：表情清除和用户名数字转换
            message = self._preprocess_message_for_tts(message)
            
            # 检查消息是否已经包含file_path，如果有则直接返回
            if "file_path" in message and message["file_path"]:
                logger.debug(f"消息已包含file_path，直接返回: {message['file_path']}")
                return {
                    "result": {
                        "code": 200,
                        "audio_path": message["file_path"]
                    }
                }
            
            if message["tts_type"] == "vits":
                # 语言检测
                language = self.common.lang_check(message["content"])
                logger.debug(f"message['content']={message['content']}")
                
                # 使用统一的语言映射工具
                language = LanguageUtils.convert_language_for_tts("vits", language)
                
                data = {
                    "type": message["data"].get("type", ""),
                    "api_ip_port": message["data"].get("api_ip_port", ""),
                    "id": message["data"].get("id", 0),
                    "format": message["data"].get("format", "wav"),
                    "lang": language,
                    "length": message["data"].get("length", 1.0),
                    "noise": message["data"].get("noise", 0.667),
                    "noisew": message["data"].get("noisew", 0.8),
                    "max": message["data"].get("max", 50),
                    "sdp_radio": message["data"].get("sdp_radio", 0.2),
                    "content": message["content"],
                    "gpt_sovits": message["data"].get("gpt_sovits", {}),
                }
                
                # 调用接口合成语音
                voice_tmp_path = await self.my_tts.vits_api(data)
            
            elif message["tts_type"] == "bert_vits2":
                if message["data"].get("language", "auto") == "auto":
                    # 自动检测语言
                    language = self.common.lang_check(message["content"])
                    logger.debug(f'language={language}')
                    
                    # 使用统一的语言映射工具
                    language = LanguageUtils.convert_language_for_tts("bert_vits2", language)
                else:
                    language = message["data"].get("language", "ZH")
                
                data = {
                    "api_ip_port": message["data"].get("api_ip_port", ""),
                    "type": message["data"].get("type", ""),
                    "model_id": message["data"].get("model_id", 0),
                    "speaker_name": message["data"].get("speaker_name", ""),
                    "speaker_id": message["data"].get("speaker_id", 0),
                    "language": language,
                    "length": message["data"].get("length", 1.0),
                    "noise": message["data"].get("noise", 0.667),
                    "noisew": message["data"].get("noisew", 0.8),
                    "sdp_radio": message["data"].get("sdp_radio", 0.2),
                    "auto_translate": message["data"].get("auto_translate", False),
                    "auto_split": message["data"].get("auto_split", True),
                    "emotion": message["data"].get("emotion", "Happy"),
                    "style_text": message["data"].get("style_text", ""),
                    "style_weight": message["data"].get("style_weight", 0.7),
                    "刘悦-中文特化API": message["data"].get("刘悦-中文特化API", {}),
                    "content": message["content"]
                }
                
                # 调用接口合成语音
                voice_tmp_path = await self.my_tts.bert_vits2_api(data)
            
            elif message["tts_type"] == "vits_fast":
                if message["data"].get("language", "自动识别") == "自动识别":
                    # 自动检测语言
                    language = self.common.lang_check(message["content"])
                    logger.debug(f'language={language}')
                    
                    # 使用统一的语言映射工具
                    language = LanguageUtils.convert_language_for_tts("vits_fast", language)
                else:
                    language = message["data"].get("language", "简体中文")
                
                data = {
                    "api_ip_port": message["data"].get("api_ip_port", ""),
                    "character": message["data"].get("character", ""),
                    "speed": message["data"].get("speed", 1.0),
                    "language": language,
                    "content": message["content"]
                }
                
                # 调用接口合成语音
                voice_tmp_path = self.my_tts.vits_fast_api(data)
            
            elif message["tts_type"] == "edge-tts":
                # 使用 my_tts 内的全局 edge-tts 配置，仅传入内容文本；如需覆写，可在 my_tts.edge_tts_api 内合并外部传参
                data = {
                    "content": message["content"]
                }
                
                # 调用接口合成语音
                voice_tmp_path = await self.my_tts.edge_tts_api(data)
            
            elif message["tts_type"] == "openai_tts":
                data = {
                    "type": message["data"].get("type", ""),
                    "api_ip_port": message["data"].get("api_ip_port", ""),
                    "model": message["data"].get("model", "tts-1"),
                    "voice": message["data"].get("voice", "alloy"),
                    "api_key": message["data"].get("api_key", ""),
                    "content": message["content"]
                }
                
                # 调用接口合成语音
                voice_tmp_path = self.my_tts.openai_tts_api(data)
            
            elif message["tts_type"] == "gradio_tts":
                data = {
                    "request_parameters": message["data"].get("request_parameters", {}),
                    "content": message["content"]
                }
                
                voice_tmp_path = self.my_tts.gradio_tts_api(data)
            
            elif message["tts_type"] == "gpt_sovits":
                if message["data"].get("language", "自动识别") == "自动识别":
                    # 自动检测语言
                    language = self.common.lang_check(message["content"])
                    logger.debug(f'language={language}')
                    
                    # 使用统一的语言映射工具
                    language = LanguageUtils.convert_language_for_tts("gpt_sovits", language)
                else:
                    language = message["data"].get("language", "中文")
                
                # 确保api_0322字段存在
                if "api_0322" not in message["data"]:
                    message["data"]["api_0322"] = {}
                
                if message["data"]["api_0322"].get("text_lang", "自动识别") == "自动识别":
                    # 自动检测语言
                    detected_language = self.common.lang_check(message["content"])
                    logger.debug(f'language={detected_language}')
                    
                    # 使用统一的语言映射工具
                    message["data"]["api_0322"]["text_lang"] = LanguageUtils.convert_language_for_tts("gpt_sovits", detected_language)
                
                # 确保api_0706字段存在
                if "api_0706" not in message["data"]:
                    message["data"]["api_0706"] = {}
                
                if message["data"]["api_0706"].get("text_language", "自动识别") == "自动识别":
                    message["data"]["api_0706"]["text_language"] = "auto"
                
                data = {
                    "type": message["data"].get("type", ""),
                    "gradio_ip_port": message["data"].get("gradio_ip_port", ""),
                    "api_ip_port": message["data"].get("api_ip_port", ""),
                    "ref_audio_path": message["data"].get("ref_audio_path", ""),
                    "prompt_text": message["data"].get("prompt_text", ""),
                    "prompt_language": message["data"].get("prompt_language", ""),
                    "language": language,
                    "cut": message["data"].get("cut", ""),
                    "api_0322": message["data"].get("api_0322", {}),
                    "api_0706": message["data"].get("api_0706", {}),
                    "v2_api_0821": message["data"].get("v2_api_0821", {}),
                    "webtts": message["data"].get("webtts", {}),
                    "content": message["content"]
                }
                
                voice_tmp_path = await self.my_tts.gpt_sovits_api(data)
            
            elif message["tts_type"] == "azure_tts":
                # 使用 my_tts 内的全局 azure_tts 配置，仅传入内容文本
                data = {
                    "content": message["content"]
                }
                voice_tmp_path = self.my_tts.azure_tts_api(data)
            
            elif message["tts_type"] == "cosyvoice":
                logger.debug(message)
                data = {
                    "type": message["data"].get("type", ""),
                    "gradio_ip_port": message["data"].get("gradio_ip_port", ""),
                    "api_ip_port": message["data"].get("api_ip_port", ""),
                    "gradio_0707": message["data"].get("gradio_0707", {}),
                    "api_0819": message["data"].get("api_0819", {}),
                    "content": message["content"],
                }
                
                voice_tmp_path = await self.my_tts.cosyvoice_api(data)
            
            elif message["tts_type"] == "f5_tts":
                logger.debug(message)
                data = {
                    "type": message["data"].get("type", ""),
                    "gradio_ip_port": message["data"].get("gradio_ip_port", ""),
                    "ref_audio_orig": message["data"].get("ref_audio_orig", ""),
                    "ref_text": message["data"].get("ref_text", ""),
                    "model": message["data"].get("model", ""),
                    "remove_silence": message["data"].get("remove_silence", False),
                    "cross_fade_duration": message["data"].get("cross_fade_duration", 0.15),
                    "speed": message["data"].get("speed", 1.0),
                    "content": message["content"],
                }
                
                voice_tmp_path = await self.my_tts.f5_tts_api(data)
            
            elif message["tts_type"] == "multitts":
                data = {
                    "content": message["content"],
                    "multitts": message.get("data", {})
                }
                
                voice_tmp_path = await self.my_tts.multitts_api(data)
            
            elif message["tts_type"] == "melotts":
                data = {
                    "content": message["content"],
                    "melotts": message.get("data", {})
                }
                
                voice_tmp_path = await self.my_tts.melotts_api(data)
            
            elif message["tts_type"] == "index_tts":
                data = {
                    "content": message["content"],
                    "index_tts": message.get("data", {}),
                }
                
                voice_tmp_path = await self.my_tts.index_tts_api(data)
            
            elif message["tts_type"] == "none":
                voice_tmp_path = None
            
            # 封装合成结果
            if voice_tmp_path:
                return {
                    "result": {
                        "code": 200, 
                        "message": "合成成功", 
                        "audio_path": voice_tmp_path
                    }
                }
            else:
                return {
                    "result": {
                        "code": -1, 
                        "message": "合成失败", 
                        "audio_path": None
                    }
                }
        
        except Exception as e:
            logger.error(f"TTS合成异常: {e}")
            return {
                "result": {
                    "code": -1, 
                    "message": f"合成异常: {str(e)}", 
                    "audio_path": None
                }
            }
    
    # 音频播放方法（占位符，需要实现具体逻辑）
    async def _play_audio_with_mixer(self, audio_data, mixer, audio_type):
        """通用音频播放方法
        
        Args:
            audio_data: 标准化的音频数据字典
            mixer: pygame mixer对象
            audio_type: 音频类型（用于日志）
        """
        try:
            # 确保音频数据已标准化
            normalized_data = self._normalize_audio_data(audio_data)
            if not normalized_data:
                logger.error(f"{audio_type}音频数据标准化失败")
                return
            
            audio_path = normalized_data.get("audio_path")
            if not audio_path or not os.path.exists(audio_path):
                logger.error(f"{audio_type}音频文件不存在: {audio_path}")
                return
            
            # logger.info(f"开始播放{audio_type}音频: {audio_path}")
            
            # 记录播放信息
            text = normalized_data.get("text", "")
            if text:
                logger.debug(f"{audio_type}音频内容: {text[:50]}...")
            
            if mixer:
                mixer.music.load(audio_path)
                mixer.music.play()
                
                # 等待播放完成
                while mixer.music.get_busy():
                    if Audio.should_shutdown:
                        break
                    # 文案音频需要额外检查播放标志
                    if audio_type == "文案" and Audio.copywriting_play_flag == 0:
                        break
                    await asyncio.sleep(0.1)
            else:
                logger.error(f"{audio_type}mixer未初始化")
        except Exception as e:
            logger.error(f"{audio_type}音频播放异常: {e}")
            raise
    
    async def _process_global_audio(self, audio_data):
        """处理全局音频播放
        
        Args:
            audio_data: 音频数据
        """
        try:
            # 标准化音频数据格式
            normalized_data = self._normalize_audio_data(audio_data)
            if not normalized_data or not normalized_data.get("audio_path"):
                logger.warning("全局音频数据无效，跳过播放")
                return
            
            audio_path = normalized_data["audio_path"]
            # logger.info(f"开始播放全局音频: {audio_path}")
            
            # 检查是否需要发送给metahuman_stream
            if self._should_use_metahuman_stream(normalized_data.get("data_json", {})):
                await self._send_to_metahuman_stream(normalized_data)
            else:
                await self._play_audio_with_mixer(normalized_data, Audio.mixer_normal, "全局")
            
            # logger.info(f"全局音频播放完成: {audio_path}")
            
        except Exception as e:
            logger.error(f"全局音频播放异常: {e}")
            logger.error(traceback.format_exc())
    
    async def _process_assistant_audio(self, audio_data):
        """处理助播音频播放
        
        Args:
            audio_data: 音频数据
        """
        try:
            # 标准化音频数据格式
            normalized_data = self._normalize_audio_data(audio_data)
            if not normalized_data or not normalized_data.get("audio_path"):
                logger.warning("助播音频数据无效，跳过播放")
                return
            
            audio_path = normalized_data["audio_path"]
            # logger.info(f"开始播放助播音频: {audio_path}")
            
            # 检查是否需要转发给DH-LIVE
            if self._should_forward_to_dh_live(normalized_data):
                self.dh_live_manager.add_to_forward_queue(normalized_data)
                return
            else:
                await self._play_audio_with_mixer(normalized_data, Audio.mixer_assistant, "助播")
            
            # logger.info(f"助播音频播放完成: {audio_path}")
            
        except Exception as e:
            logger.error(f"助播音频播放异常: {e}")
            logger.error(traceback.format_exc())
    
    async def _process_copywriting_audio(self, audio_data):
        """处理文案音频播放
        
        Args:
            audio_data: 音频数据
        """
        try:
            # 标准化音频数据格式
            normalized_data = self._normalize_audio_data(audio_data)
            if not normalized_data or not normalized_data.get("audio_path"):
                logger.warning("文案音频数据无效，跳过播放")
                return
            
            audio_path = normalized_data["audio_path"]
            # logger.info(f"开始播放文案音频: {audio_path}")
            
            # 检查文案播放标志
            if Audio.copywriting_play_flag == 0:  # 手动暂停
                # logger.info("文案播放已手动暂停，跳过播放")
                return
            elif Audio.copywriting_play_flag == 1:  # 临时暂停
                # logger.info("文案播放临时暂停，等待恢复")
                # 可以在这里添加等待逻辑
                return
            
            await self._play_audio_with_mixer(normalized_data, Audio.mixer_copywriting, "文案")
            
            # 检查是否需要循环播放
            if Audio.copywriting_play_flag == 2:  # 循环播放
                self._add_to_copywriting_queue(normalized_data)
            
            # logger.info(f"文案音频播放完成: {audio_path}")
            
        except Exception as e:
            logger.error(f"文案音频播放异常: {e}")
            logger.error(traceback.format_exc())
    
    async def _process_legacy_audio(self, audio_data):
        """处理兼容性音频播放
        
        Args:
            audio_data: 音频数据
        """
        try:
            # 标准化音频数据格式
            normalized_data = self._normalize_audio_data(audio_data)
            if not normalized_data:
                logger.warning("兼容性音频数据无效，跳过播放")
                return
            
            audio_path = normalized_data.get("audio_path")
            if not audio_path or not os.path.exists(audio_path):
                logger.error(f"兼容性音频文件不存在: {audio_path}")
                return
            
            logger.info(f"开始播放兼容性音频: {audio_path}")
            
            # 直接播放音频，不再添加到队列避免循环调用
            if self.config.get("play_audio", "player") == "pygame":
                await self._play_audio_with_mixer(normalized_data, Audio.mixer_normal, "兼容性")
            else:
                # 使用音频播放器播放
                if hasattr(Audio, 'audio_player') and Audio.audio_player:
                    try:
                        Audio.audio_player.play({
                            "voice_path": audio_path,
                            "type": normalized_data.get("type", "local_audio")
                        })
                    except Exception as e:
                        logger.error(f"音频播放器播放失败: {e}")
                        # 降级到mixer播放
                        await self._play_audio_with_mixer(normalized_data, Audio.mixer_normal, "兼容性")
            
            # logger.info(f"兼容性音频播放完成: {audio_path}")
            
        except Exception as e:
            logger.error(f"兼容性音频播放异常: {e}")
            logger.error(traceback.format_exc())
    
    # 辅助方法
    async def _send_to_metahuman_stream(self, message):
        """发送消息到metahuman_stream
        
        Args:
            message: 消息数据
        """
        try:
            metahuman_config = self.config.get("visual_body")
            if metahuman_config != "metahuman_stream":
                logger.warning("metahuman_stream未启用，跳过发送")
                return
            
            # 获取metahuman_stream配置
            metahuman_stream_config = self.config.get("metahuman_stream", {})
            api_ip_port = metahuman_stream_config.get("api_ip_port")
            if not api_ip_port:
                logger.error("metahuman_stream API URL未配置")
                return
            
            # 构建完整的API URL
            api_url = f"{api_ip_port}/human"
            
            # 标准化消息数据
            normalized_message = self._normalize_audio_data(message)
            if not normalized_message:
                logger.error("消息数据标准化失败")
                return
            
            # 准备发送数据 - 使用正确的API格式
            send_data = {
                "type": "echo",
                "text": normalized_message.get("text", ""),
                "sessionid": 0  # 默认使用sessionid 0
            }
            
            # logger.info(f"发送数据到metahuman_stream: {send_data.get('content', send_data.get('text', 'unknown'))}")
            
            # 发送HTTP请求
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    api_url,
                    json=send_data,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        logger.info("metahuman_stream发送成功")
                    else:
                        logger.error(f"metahuman_stream发送失败: {response.status}")
            
        except Exception as e:
            logger.error(f"发送到metahuman_stream异常: {e}")
            logger.error(traceback.format_exc())
    
    # 数据根据优先级排队插入待合成音频队列
    def data_priority_insert(self, type:str="等待合成消息", data_json:dict=None):
        """
        数据根据优先级排队插入待合成音频队列

        type目前有
            reread_top_priority 最高优先级-复读
            talk 聊天（语音输入）
            comment 弹幕
            local_qa_audio 本地问答音频
            song 歌曲
            reread 复读
            key_mapping 按键映射
            integral 积分
            read_comment 念弹幕
            gift 礼物
            entrance 用户入场
            follow 用户关注
            schedule 定时任务
            idle_time_task 闲时任务
            abnormal_alarm 异常报警
            image_recognition_schedule 图像识别定时任务
            trends_copywriting 动态文案
            assistant_anchor_text 助播-文本
            assistant_anchor_audio 助播-音频
        """
        logger.debug(f"message_queue: {self.message_queue}")
        logger.debug(f"data_json: {data_json}")

        # 定义 type 到优先级的映射，相同优先级的 type 映射到相同的值，值越大优先级越高
        priority_mapping = self.config.get("filter", "priority_mapping")
        
        def get_priority_level(data_json):
            """根据 data_json 的 'type' 键返回优先级，未定义的 type 或缺失 'type' 键将返回 None"""
            # 检查 data_json 是否包含 'type' 键且该键的值在 priority_mapping 中
            audio_type = data_json.get("type")
            return priority_mapping.get(audio_type, None)

        # 查找插入位置
        new_data_priority = get_priority_level(data_json)

        if type == "等待合成消息":
            logger.info(f"{type} 优先级(配置): {new_data_priority} 内容：【{data_json['content']}】")

            # 检查队列是否已满
            if self.message_queue.full():
                logger.info(f"message_queue 已满，数据丢弃：【{data_json['content']}】")
                return {"code": 1, "msg": f"message_queue 已满，数据丢弃：【{data_json['content']}】"}

            # 获取线程锁，避免同时操作
            with self.message_queue_lock:
                # 使用优先级和计数器确保FIFO顺序；内部优先级为配置取负数
                mapping_priority = int(new_data_priority) if new_data_priority is not None else 0
                internal_priority = -mapping_priority
                # 使用计数器确保相同优先级的消息按FIFO顺序处理
                self.message_counter += 1
                # PriorityQueue使用(priority, counter, data)的元组格式
                queue_item = (internal_priority, self.message_counter, data_json)
                self.message_queue.put(queue_item)
                # 生产者通过notify()通知消费者列表中有新的消息
                self.message_queue_not_empty.notify()

            return {"code": 200, "msg": f"数据已插入到优先级队列，优先级(配置): {mapping_priority} -> 内部: {internal_priority}"}
        else:
            logger.info(f"{type} 优先级: {new_data_priority} 音频={data_json['voice_path']}")

            # 如果新数据没有 'type' 键或其类型不在 priority_mapping 中，直接插入到末尾
            if new_data_priority is None:
                insert_position = len(self.voice_tmp_path_queue)
            else:
                insert_position = 0  # 默认插入到列表开头
                # 从列表的最后一个元素开始，向前遍历列表，直到第一个元素
                for i in range(len(self.voice_tmp_path_queue) - 1, -1, -1):
                    priority_level = get_priority_level(self.voice_tmp_path_queue[i])
                    if priority_level is not None:
                        item_priority = int(priority_level)
                        # 确保比较时排除未定义类型的元素
                        if item_priority is not None and item_priority >= new_data_priority:
                            # 如果找到一个元素，其优先级小于或等于新数据，则将新数据插入到此元素之后
                            insert_position = i + 1
                            break
            
            # logger.debug(f"insert_position={insert_position}")

            # 数据队列数据量超长判断，插入位置索引大于最大数，则说明优先级低与队列中已存在数据，丢弃数据
            if insert_position >= self.voice_tmp_path_queue_max_len:
                # logger.info(f"voice_tmp_path_queue 已满，音频丢弃：【{data_json['voice_path']}】")
                return {"code": 1, "msg": f"voice_tmp_path_queue 已满，音频丢弃：【{data_json['voice_path']}】"}

            # 获取线程锁，避免同时操作
            with self.voice_tmp_path_queue_lock:
                # 在计算出的位置插入新数据
                self.voice_tmp_path_queue.insert(insert_position, data_json)

                # 待播放音频数量大于首次播放阈值 且 处于首次播放情况下：
                if len(self.voice_tmp_path_queue) >= int(self.config.get("filter", "voice_tmp_path_queue_min_start_play")) and \
                    self.voice_tmp_path_queue_not_empty_flag is False:
                    self.voice_tmp_path_queue_not_empty_flag = True
                    # 生产者通过notify()通知消费者列表中有新的消息
                    self.voice_tmp_path_queue_not_empty.notify()
                # 非首次触发情况下，有数据就触发消费者播放
                elif self.voice_tmp_path_queue_not_empty_flag:
                    # 生产者通过notify()通知消费者列表中有新的消息
                    self.voice_tmp_path_queue_not_empty.notify()

            return {"code": 200, "msg": f"音频已插入到位置 {insert_position}"}
    

    
    # 队列状态查询方法
    def is_queue_empty(self, queue_type="all"):
        """检查队列是否为空
        
        Args:
            queue_type: 队列类型
            
        Returns:
            bool: 队列是否为空
        """
        try:
            if queue_type == "message":
                return self.message_queue.empty()
            elif queue_type == "global":
                return self.global_audio_queue.empty()
            elif queue_type == "assistant":
                return self.assistant_audio_queue.empty()
            elif queue_type == "copywriting":
                return self.copywriting_audio_queue.empty()
            elif queue_type == "legacy":
                return len(self.voice_tmp_path_queue) == 0
            elif queue_type == "all":
                return (self.message_queue.empty() and 
                       self.global_audio_queue.empty() and 
                       self.assistant_audio_queue.empty() and 
                       self.copywriting_audio_queue.empty() and 
                       len(self.voice_tmp_path_queue) == 0)
            else:
                return True
        except Exception as e:
            logger.error(f"检查队列状态时出错: {e}")
            return True
    
    def clear_queue(self, queue_type="all"):
        """清空队列
        
        Args:
            queue_type: 队列类型
            
        Returns:
            bool: 清空是否成功
        """
        try:
            if queue_type == "message" or queue_type == "all":
                with self.message_queue_lock:
                    while not self.message_queue.empty():
                        try:
                            self.message_queue.get_nowait()
                        except queue.Empty:
                            break
            
            if queue_type == "global" or queue_type == "all":
                with self.global_audio_queue_lock:
                    while not self.global_audio_queue.empty():
                        try:
                            self.global_audio_queue.get_nowait()
                        except queue.Empty:
                            break
            
            if queue_type == "assistant" or queue_type == "all":
                with self.assistant_audio_queue_lock:
                    while not self.assistant_audio_queue.empty():
                        try:
                            self.assistant_audio_queue.get_nowait()
                        except queue.Empty:
                            break
            
            if queue_type == "copywriting" or queue_type == "all":
                with self.copywriting_audio_queue_lock:
                    while not self.copywriting_audio_queue.empty():
                        try:
                            self.copywriting_audio_queue.get_nowait()
                        except queue.Empty:
                            break
            
            if queue_type == "legacy" or queue_type == "all":
                with self.voice_tmp_path_queue_lock:
                    self.voice_tmp_path_queue.clear()
            
            logger.info(f"队列 {queue_type} 已清空")
            return True
            
        except Exception as e:
            logger.error(f"清空队列时出错: {e}")
            return False
    
    def stop_audio(self, mixer_type="all"):
        """停止音频播放
        
        Args:
            mixer_type: mixer类型
            
        Returns:
            bool: 停止是否成功
        """
        try:
            if self.config.get("play_audio", "player") in ["pygame"]:
                if mixer_type == "normal" or mixer_type == "all":
                    if Audio.mixer_normal:
                        Audio.mixer_normal.music.stop()
                        logger.info("停止普通音频播放")
                
                if mixer_type == "copywriting" or mixer_type == "all":
                    if Audio.mixer_copywriting:
                        Audio.mixer_copywriting.music.stop()
                        logger.info("停止文案音频播放")
                
                if mixer_type == "assistant" or mixer_type == "all":
                    if Audio.mixer_assistant:
                        Audio.mixer_assistant.music.stop()
                        logger.info("停止助播音频播放")
            
            return True
            
        except Exception as e:
            logger.error(f"停止音频播放失败: {e}")
            return False
    
    def shutdown(self):
        """优雅关闭Audio系统的所有线程和资源"""
        try:
            logger.info("开始关闭Audio系统...")
            
            # 设置关闭标志
            Audio.should_shutdown = True
            
            # 唤醒所有等待的线程
            with self.message_queue_lock:
                self.message_queue_not_empty.notify_all()
            
            with self.global_audio_queue_lock:
                self.global_audio_queue_not_empty.notify_all()
            
            with self.assistant_audio_queue_lock:
                self.assistant_audio_queue_not_empty.notify_all()
            
            with self.copywriting_audio_queue_lock:
                self.copywriting_audio_queue_not_empty.notify_all()
            
            with self.voice_tmp_path_queue_lock:
                self.voice_tmp_path_queue_not_empty.notify_all()
            
            # 停止所有音频播放
            self.stop_audio("all")
            
            # 关闭DH-LIVE管理器
            if self.dh_live_manager:
                self.dh_live_manager.shutdown()
            
            # 清空所有队列
            self.clear_queue("all")
            
            logger.info("Audio系统关闭完成")
            return True
            
        except Exception as e:
            logger.error(f"关闭Audio系统时出错: {e}")
            logger.error(traceback.format_exc())
            return False
    
    def reload_config(self, config_path):
        """重载配置
        
        Args:
            config_path: 配置文件路径
        """
        try:
            self.config = Config(config_path)
            self.my_tts = MY_TTS(config_path)

            # 处理DH-LIVE配置变更
            try:
                assistant_cfg = self.config.get("assistant_anchor", {})
                dh_cfg = assistant_cfg.get("dh_live", {})
                enabled = isinstance(dh_cfg, dict) and dh_cfg.get("enable", False)
                if enabled:
                    if getattr(self, "dh_live_manager", None):
                        self.dh_live_manager.reload_config(self.config)
                        logger.info("DH-LIVE管理器配置已重载")
                    else:
                        self.dh_live_manager = DHLiveManager(self.config)
                        logger.info("DH-LIVE管理器已创建并启用（重载后）")
                else:
                    if getattr(self, "dh_live_manager", None):
                        self.dh_live_manager.shutdown()
                        self.dh_live_manager = None
                        logger.info("DH-LIVE管理器已停用（重载后）")
            except Exception as e2:
                logger.error(f"重载DH-LIVE配置处理失败: {e2}")

            logger.info("配置重载完成")
        except Exception as e:
            logger.error(f"配置重载失败: {e}")
    
    def search_files(self, directory, file_name, audio_suffixes=None):
        """从指定路径下搜索音频文件
        
        Args:
            directory: 要搜索的目录
            file_name: 音频文件名（不含文件拓展名）
            audio_suffixes: 可能的音频文件后缀列表，如 ['wav', 'mp3', 'flac']。默认为 ['wav', 'mp3']。
            
        Returns:
            list: 找到的音频文件相对路径列表，如果没找到返回空列表
        """
        if audio_suffixes is None:
            audio_suffixes = ['wav', 'mp3']
        
        try:
            found_files = []
            for root, _, files in os.walk(directory):
                for suffix in audio_suffixes:
                    target_file = f"{file_name}.{suffix}"
                    if target_file in files:
                        file_path = os.path.join(root, target_file)
                        relative_path = os.path.relpath(file_path, directory)
                        relative_path = relative_path.replace("\\", "/")  # 将反斜杠替换为斜杠
                        found_files.append(relative_path)
            return found_files
        except Exception as e:
            logger.error(f"搜索音频文件时发生异常: {str(e)}")
            return []
    
    def _preprocess_message_for_tts(self, message):
        """TTS预处理：表情清除和用户名数字转换
        
        Args:
            message (dict): 原始消息数据
            
        Returns:
            dict: 预处理后的消息数据
        """
        try:
            # 创建消息副本，避免修改原始数据
            processed_message = deepcopy(message)
            
            # 1. 表情清除功能
            if self.config.get("filter", "emoji", False):
                content = processed_message.get("content", "")
                if content:
                    from utils.emoji_utils import EmojiUtils
                    
                    # 使用统一的表情符号检测工具
                    processed_content = EmojiUtils.clean_text(content)
                    processed_message["content"] = processed_content
                    # logger.info(f"表情清除: '{content}' -> '{processed_content}'")
            
            # 2. 用户名数字转换功能
            if self.config.get("filter", "username_convert_digits_to_chinese", False):
                username = processed_message.get("username", "")
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
                    
                    processed_message["username"] = processed_username
                    # logger.info(f"用户名数字转换: '{username}' -> '{processed_username}'")
            
            return processed_message
            
        except Exception as e:
            logger.error(f"TTS预处理出错: {e}")
            # 出错时返回原始消息
            return message
