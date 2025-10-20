# -*- coding: utf-8 -*-
"""
DH-LIVE管理器模块
职能：将助播流程的音频进行队列组织，通过API转发给DH-LIVE系统。等待DH-liveAPI响应后再将音频添加到audio.py的助播播放流程。
设计流程：
1. audio.py接收助播流程音频后，判断是否需要转发给DH-LIVE系统，若不需要，则直接加入助播播放队列。
2. 若需要转发，则进入dh_live_manager.py队列组织环节，将音频通过API发送至dh-live，等待DH-LIVE 200响应后执行设定的延迟，延迟结束将音频加入audio.py助播播放队列。
3. 添加audio.py播放队列的同时，启动一个计时器，计时的时长为当次转发音频的时长，在这个时间内收到的音频处于队列等待状态，不会进行转发，计时结束后再继续转发&添加播放。这样设计的目的是给DH-LIVE留出推理时间，确保口型与音频匹配。
"""

import asyncio
import threading
import queue
import time
import os
import aiohttp
import traceback
from urllib.parse import urljoin
from pydub import AudioSegment

from .my_log import logger


class DHLiveManager:
    """DH-LIVE管理器核心类"""
    
    def __init__(self, config_data):
        """初始化DH-LIVE管理器
        
        Args:
            config_data: 配置数据
        """
        self.config = config_data
        
        # 转发队列
        self.forward_queue = queue.Queue()
        self.forward_queue_lock = threading.Lock()
        self.forward_queue_not_empty = threading.Condition(lock=self.forward_queue_lock)
        
        # 等待队列（在计时器期间暂存音频）
        self.waiting_queue = queue.Queue()
        self.waiting_queue_lock = threading.Lock()
        
        # 计时器状态
        self.timer_active = False
        self.timer_lock = threading.Lock()
        self.current_timer = None
        
        # 关闭标志
        self.should_shutdown = False
        
        # 启动转发处理线程
        self._start_forward_thread()
        
        logger.info("DH-LIVE管理器初始化完成")
    
    def _start_forward_thread(self):
        """启动转发处理线程"""
        try:
            self.forward_thread = threading.Thread(
                target=lambda: asyncio.run(self.forward_processing_thread()),
                daemon=False,
                name="DHLiveForwardThread"
            )
            self.forward_thread.start()
            
            logger.info("DH-LIVE转发处理线程启动完成")
        except Exception as e:
            logger.error(f"启动DH-LIVE转发处理线程失败: {e}")
            logger.error(traceback.format_exc())
    
    async def forward_processing_thread(self):
        """转发处理线程"""
        logger.info("DH-LIVE转发处理线程启动")
        
        while not self.should_shutdown:
            try:
                # 等待转发队列非空
                with self.forward_queue_lock:
                    while self.forward_queue.empty() and not self.should_shutdown:
                        self.forward_queue_not_empty.wait(timeout=1.0)
                
                if self.should_shutdown:
                    break
                
                # 检查计时器状态或当前是否正在播放助播音频
                playing_now = False
                try:
                    from .audio import Audio
                    playing_now = bool(Audio.mixer_assistant and Audio.mixer_assistant.music.get_busy())
                except Exception:
                    playing_now = False
                with self.timer_lock:
                    timer_active_snapshot = self.timer_active
                if timer_active_snapshot:
                    # 计时器活跃期间，将音频移到等待队列，等待计时器结束后再处理
                    try:
                        audio_data = self.forward_queue.get(timeout=1.0)
                        with self.waiting_queue_lock:
                            self.waiting_queue.put(audio_data)
                        logger.debug("计时器活跃，音频已移至等待队列")
                        continue
                    except queue.Empty:
                        continue
                elif playing_now:
                    # 当前助播正在播放，暂缓处理（不取出队列项），稍后重试
                    await asyncio.sleep(0.2)
                    continue
                
                # 获取音频数据进行转发
                try:
                    audio_data = self.forward_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                
                # 在关闭时放弃处理，避免调度新任务
                if self.should_shutdown:
                    break

                # 避免重复转发：若已标记转发成功则直接丢弃本队列项
                try:
                    if isinstance(audio_data, dict) and audio_data.get('dh_live_forwarded'):
                        logger.debug("检测到已转发成功的音频项，跳过重复转发并从队列消费")
                        self.forward_queue.task_done()
                        continue
                except Exception:
                    pass
                
                # 处理音频转发
                await self._process_audio_forward(audio_data)
                
                # 标记任务完成
                self.forward_queue.task_done()
                
            except Exception as e:
                logger.error(f"DH-LIVE转发处理线程出错: {e}")
                logger.error(traceback.format_exc())
    
    async def _process_audio_forward(self, audio_data):
        """处理单个音频转发
        
        Args:
            audio_data: 音频数据
        """
        try:
            if self.should_shutdown:
                logger.info("DH-LIVE管理器正在关闭，放弃处理音频转发")
                return
            
            audio_path = audio_data.get('file_path')
            if not audio_path or not os.path.exists(audio_path):
                logger.error(f"音频文件不存在: {audio_path}")
                return
            
            logger.debug(f"开始转发音频到DH-LIVE: {audio_path}")

            # 标记已尝试转发，避免后续再次被判定需要转发
            try:
                if isinstance(audio_data, dict):
                    audio_data['dh_live_attempted'] = True
            except Exception:
                pass
            
            # 发送音频到DH-LIVE
            success = await self._send_audio_to_dh_live(audio_path)
            
            if success:
                # 标记转发成功，供播放流程短路避免再次进入转发
                try:
                    if isinstance(audio_data, dict):
                        audio_data['dh_live_forwarded'] = True
                except Exception:
                    pass
                
                # 获取音频时长
                audio_duration = self._get_audio_duration(audio_path)
                
                # 获取配置的延迟时间
                delay_time = self._get_delay_time()
                
                # 执行延迟
                if delay_time > 0:
                    logger.debug(f"DH-LIVE响应成功，等待延迟 {delay_time} 秒")
                    await asyncio.sleep(delay_time)
                
                # 将音频添加到助播播放队列
                await self._add_to_assistant_playback_queue(audio_data)
                
                # 启动计时器
                self._start_audio_timer(audio_duration)
                
                logger.info(f"音频转发完成: {audio_path}")
            else:
                logger.error(f"音频转发失败: {audio_path}")
                # 转发失败时，直接添加到播放队列
                await self._add_to_assistant_playback_queue(audio_data)
                
        except Exception as e:
            logger.error(f"处理音频转发时出错: {e}")
            logger.error(traceback.format_exc())
            # 出错时，直接添加到播放队列
            await self._add_to_assistant_playback_queue(audio_data)
    
    async def _send_audio_to_dh_live(self, audio_path):
        """发送音频到DH-LIVE系统
        
        Args:
            audio_path: 音频文件路径
            
        Returns:
            bool: 发送是否成功
        """
        # 在关闭期间立即放弃发送，避免在解释器关闭阶段调度新任务
        if self.should_shutdown:
            logger.info("DH-LIVE管理器正在关闭，放弃发送音频")
            return False

        max_retries = 3
        retry_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                # 获取DH-LIVE配置
                dh_live_config = self._get_dh_live_config()
                if not dh_live_config:
                    logger.error("DH-LIVE配置不存在")
                    return False
                
                api_ip_port = dh_live_config.get('api_ip_port', 'http://localhost:8051')
                url = urljoin(api_ip_port, "/receive_audio")
                
                # 检查文件大小
                if not os.path.exists(audio_path):
                    logger.error(f"音频文件不存在: {audio_path}")
                    return False
                    
                file_size = os.path.getsize(audio_path)
                if file_size == 0:
                    logger.error(f"音频文件为空: {audio_path}")
                    return False
                
                logger.debug(f"发送音频到DH-LIVE: URL={url}, 文件={audio_path}, 尝试 {attempt + 1}/{max_retries}")
                
                # 准备文件上传数据
                filename = os.path.basename(audio_path)
                
                # 设置超时时间
                timeout = aiohttp.ClientTimeout(total=10.0, connect=5.0)
                
                # 规范化URL，确保带有scheme
                if not api_ip_port.startswith("http://") and not api_ip_port.startswith("https://"):
                    api_ip_port = f"http://{api_ip_port}"
                    url = urljoin(api_ip_port, "/receive_audio")

                async with aiohttp.ClientSession(timeout=timeout) as session:
                    # 预读文件到内存，避免aiohttp内部在解释器关闭时调用run_in_executor
                    with open(audio_path, 'rb') as f:
                        file_bytes = f.read()
                    data = aiohttp.FormData()
                    data.add_field('audio_file', file_bytes, filename=filename, content_type='audio/wav')
                    
                    async with session.post(url, data=data) as response:
                            if response.status == 200:
                                response_json = await response.json()
                                logger.info(f"DH-LIVE发送成功，响应：{response_json} (尝试 {attempt + 1}/{max_retries})")
                                return True
                            else:
                                response_text = await response.text()
                                logger.warning(f"DH-LIVE发送失败，状态码：{response.status}，响应：{response_text} (尝试 {attempt + 1}/{max_retries})")
                                if self.should_shutdown:
                                    return False
                                if attempt < max_retries - 1:
                                    await asyncio.sleep(retry_delay * (attempt + 1))
                                    continue
                                else:
                                    logger.error(f"DH-LIVE发送失败，已达到最大重试次数")
                                    return False
                                
            except asyncio.TimeoutError:
                logger.warning(f"DH-LIVE发送超时: {audio_path} (尝试 {attempt + 1}/{max_retries})")
                if self.should_shutdown:
                    return False
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay * (attempt + 1))
                    continue
                else:
                    logger.error("DH-LIVE发送超时，已达到最大重试次数")
                    return False
            except aiohttp.ClientConnectorError:
                logger.warning(f"DH-LIVE连接失败: {audio_path} (尝试 {attempt + 1}/{max_retries})")
                if self.should_shutdown:
                    return False
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay * (attempt + 1))
                    continue
                else:
                    logger.error("DH-LIVE连接失败，已达到最大重试次数")
                    return False
            except Exception as e:
                logger.error(f"DH-LIVE发送音频时发生错误：{e} (尝试 {attempt + 1}/{max_retries})")
                if self.should_shutdown:
                    return False
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay * (attempt + 1))
                    continue
                else:
                    logger.error(traceback.format_exc())
                    return False
        
        return False
    
    def _get_audio_duration(self, audio_path):
        """获取音频时长
        
        Args:
            audio_path: 音频文件路径
            
        Returns:
            float: 音频时长（秒）
        """
        try:
            audio = AudioSegment.from_file(audio_path)
            duration = len(audio) / 1000.0  # 转换为秒
            logger.debug(f"音频时长: {duration} 秒")
            return duration
        except Exception as e:
            logger.error(f"获取音频时长失败: {e}")
            return 3.0  # 默认3秒
    
    def _get_delay_time(self):
        """获取配置的延迟时间
        
        Returns:
            float: 延迟时间（秒）
        """
        try:
            dh_live_config = self._get_dh_live_config()
            if dh_live_config:
                value = dh_live_config.get('play_delay')
                if value is None:
                    value = dh_live_config.get('delay_time', 1.0)
                return float(value)
            return 1.0
        except Exception as e:
            logger.error(f"获取延迟时间失败: {e}")
            return 1.0
    
    def _get_dh_live_config(self):
        """获取DH-LIVE配置
        
        Returns:
            dict: DH-LIVE配置
        """
        try:
            assistant_config = self.config.get("assistant_anchor", {})
            return assistant_config.get("dh_live", {})
        except Exception as e:
            logger.error(f"获取DH-LIVE配置失败: {e}")
            return {}
    
    async def _add_to_assistant_playback_queue(self, audio_data):
        """将音频添加到助播播放队列
        
        Args:
            audio_data: 音频数据
        """
        try:
            # 获取Audio实例
            from .audio import Audio
            
            if Audio.instance:
                Audio.instance._add_to_assistant_queue(audio_data)
                logger.debug(f"音频已添加到助播播放队列: {audio_data.get('file_path', 'unknown')}")
            else:
                logger.error("Audio实例不存在，无法添加到助播播放队列")
                
        except Exception as e:
            logger.error(f"添加音频到助播播放队列失败: {e}")
    
    def _start_audio_timer(self, duration):
        """启动音频计时器
        
        Args:
            duration: 计时时长（秒）
        """
        try:
            with self.timer_lock:
                # 如果已有计时器在运行，先取消
                if self.current_timer and self.current_timer.is_alive():
                    self.current_timer.cancel()
                    logger.debug("取消了之前的音频计时器")
                
                # 设置计时器状态
                self.timer_active = True
                
                # 创建新计时器
                self.current_timer = threading.Timer(duration, self._on_timer_finished)
                self.current_timer.daemon = True
                self.current_timer.start()
                
                logger.debug(f"音频计时器已启动，时长: {duration} 秒")
                
        except Exception as e:
            logger.error(f"启动音频计时器失败: {e}")
            # 异常时重置状态
            with self.timer_lock:
                self.timer_active = False
                self.current_timer = None
    
    def _on_timer_finished(self):
        """计时器结束回调"""
        try:
            with self.timer_lock:
                self.timer_active = False
                self.current_timer = None
                logger.debug("音频计时器结束")
            
            # 处理等待队列中的音频
            self._process_waiting_queue()
            
        except Exception as e:
            logger.error(f"计时器结束处理失败: {e}")
            # 异常时确保状态重置
            with self.timer_lock:
                self.timer_active = False
                self.current_timer = None
    
    def _process_waiting_queue(self):
        """处理等待队列中的音频"""
        processed_count = 0
        try:
            with self.timer_lock:
                # 检查计时器状态，确保不在活跃状态下处理
                if self.timer_active:
                    logger.debug("计时器仍在活跃状态，跳过等待队列处理")
                    return
            
            with self.waiting_queue_lock:
                while not self.waiting_queue.empty():
                    try:
                        audio_data = self.waiting_queue.get_nowait()
                        # 将等待的音频重新添加到转发队列
                        with self.forward_queue_lock:
                            self.forward_queue.put(audio_data)
                            self.forward_queue_not_empty.notify()
                        processed_count += 1
                        logger.debug(f"等待音频已重新加入转发队列: {audio_data.get('file_path', 'unknown')}")
                    except queue.Empty:
                        break
                    except Exception as e:
                        logger.error(f"处理单个等待队列项目失败: {e}")
                        continue
                
                if processed_count > 0:
                    logger.info(f"成功处理等待队列中的 {processed_count} 个音频")
                        
        except Exception as e:
            logger.error(f"处理等待队列失败: {e}")
            # 确保在异常情况下重置状态
            with self.timer_lock:
                if self.timer_active:
                    self.timer_active = False
                    if self.current_timer:
                        self.current_timer.cancel()
                        self.current_timer = None
    
    def add_to_forward_queue(self, audio_data):
        """添加音频到转发队列
        
        Args:
            audio_data: 音频数据
        """
        try:
            if self.should_shutdown:
                logger.info("DH-LIVE管理器正在关闭，拒绝新音频入队")
                return
            with self.forward_queue_lock:
                self.forward_queue.put(audio_data)
                self.forward_queue_not_empty.notify()
            # logger.debug(f"音频已添加到DH-LIVE转发队列: {audio_data.get('file_path', 'unknown')}")
        except Exception as e:
            logger.error(f"添加音频到转发队列失败: {e}")
    
    def is_dh_live_enabled(self):
        """检查DH-LIVE是否启用
        
        Returns:
            bool: 是否启用
        """
        try:
            dh_live_config = self._get_dh_live_config()
            return dh_live_config.get('enable', False)
        except Exception as e:
            logger.error(f"检查DH-LIVE启用状态失败: {e}")
            return False
    
    def get_queue_status(self):
        """获取队列状态
        
        Returns:
            dict: 队列状态信息
        """
        try:
            return {
                "forward_queue_size": self.forward_queue.qsize(),
                "waiting_queue_size": self.waiting_queue.qsize(),
                "timer_active": self.timer_active,
                "dh_live_enabled": self.is_dh_live_enabled()
            }
        except Exception as e:
            logger.error(f"获取队列状态失败: {e}")
            return {
                "forward_queue_size": 0,
                "waiting_queue_size": 0,
                "timer_active": False,
                "dh_live_enabled": False
            }
    
    def clear_queues(self):
        """清空所有队列
        
        Returns:
            bool: 清空是否成功
        """
        try:
            # 清空转发队列
            with self.forward_queue_lock:
                while not self.forward_queue.empty():
                    try:
                        self.forward_queue.get_nowait()
                    except queue.Empty:
                        break
            
            # 清空等待队列
            with self.waiting_queue_lock:
                while not self.waiting_queue.empty():
                    try:
                        self.waiting_queue.get_nowait()
                    except queue.Empty:
                        break
            
            logger.info("DH-LIVE管理器队列已清空")
            return True
            
        except Exception as e:
            logger.error(f"清空DH-LIVE管理器队列失败: {e}")
            return False
    
    def shutdown(self):
        """关闭DH-LIVE管理器
        
        Returns:
            bool: 关闭是否成功
        """
        try:
            logger.info("开始关闭DH-LIVE管理器...")
            
            # 设置关闭标志
            self.should_shutdown = True
            
            # 取消当前计时器
            with self.timer_lock:
                if self.current_timer and self.current_timer.is_alive():
                    self.current_timer.cancel()
                    logger.debug("已取消当前计时器")
                self.timer_active = False
                self.current_timer = None
            
            # 唤醒等待的线程
            with self.forward_queue_lock:
                self.forward_queue_not_empty.notify_all()
            
            # 清空队列
            self.clear_queues()

            # 等待转发线程优雅退出
            try:
                if hasattr(self, 'forward_thread') and self.forward_thread is not None:
                    self.forward_thread.join(timeout=5.0)
                    if self.forward_thread.is_alive():
                        logger.warning("DH-LIVE转发线程未在超时内退出，将在进程结束时强制终止")
                    else:
                        logger.info("DH-LIVE转发线程已退出")
            except Exception as e:
                logger.error(f"等待DH-LIVE转发线程退出时出错: {e}")
                logger.error(traceback.format_exc())
            
            logger.info("DH-LIVE管理器关闭完成")
            return True
            
        except Exception as e:
            logger.error(f"关闭DH-LIVE管理器时出错: {e}")
            logger.error(traceback.format_exc())
            return False
    
    def reload_config(self, config_data):
        """重载配置
        
        Args:
            config_data: 新的配置数据
        """
        try:
            self.config = config_data
            logger.info("DH-LIVE管理器配置重载完成")
        except Exception as e:
            logger.error(f"DH-LIVE管理器配置重载失败: {e}")
    
    def get_statistics(self):
        """获取统计信息
        
        Returns:
            dict: 统计信息
        """
        try:
            queue_status = self.get_queue_status()
            return {
                "status": "running" if not self.should_shutdown else "shutdown",
                "queue_status": queue_status,
                "config": {
                    "dh_live_enabled": self.is_dh_live_enabled(),
                    "api_ip_port": self._get_dh_live_config().get('api_ip_port', 'N/A'),
                    "delay_time": self._get_delay_time()
                }
            }
        except Exception as e:
            logger.error(f"获取DH-LIVE管理器统计信息失败: {e}")
            return {
                "status": "error",
                "queue_status": {},
                "config": {}
            }