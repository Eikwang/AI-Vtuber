import os
import asyncio
import websockets
import json
import sys
import logging
import time
import warnings
from aiohttp import web
from aiohttp.web import json_response
from aiohttp_cors import setup as cors_setup, ResourceOptions
from url_manager import URLManager
from monitor_manager import MonitorManager, MonitorStatus
from browser_manager import BrowserManager
from live_companion_client import LiveCompanionClient
from douyin_barrage_parser import DouyinBarrageParser
from websocket_client import AIVtuberWebSocketClient

import aiohttp
from typing import Optional, Dict, Any
import traceback
import platform

from optimized_websocket_management import OptimizedWebSocketManager
from restart_config import get_restart_api

connected_clients = set()  # 保留用于兼容性，但主要使用OptimizedWebSocketManager
blocked_keywords = []
BLOCKED_KEYWORDS_FILE = 'blocked_keywords.json'
CONFIG_FILE = 'config.json'

# 全局配置
CONFIG = {}
AI_VTUBER_CONFIG = {}
WEBSOCKET_CLIENT_CONFIG = {}

# 优化的WebSocket管理器
optimized_ws_manager = None

# API转发统计
api_stats = {
    "total_sent": 0,
    "success_count": 0,
    "error_count": 0,
    "last_error": None
}

# 初始化管理器
url_manager = URLManager()
monitor_manager = MonitorManager()
browser_manager = None  # 将在main函数中初始化
live_companion_client = None  # 直播伴侣客户端
douyin_parser = DouyinBarrageParser()  # 抖音消息解析器
websocket_client = None  # AI-VTUBER WebSocket客户端

def load_config():
    """加载配置文件"""
    global CONFIG, AI_VTUBER_CONFIG, WEBSOCKET_CLIENT_CONFIG, optimized_ws_manager
    try:
        config_path = os.path.join(os.path.dirname(__file__), CONFIG_FILE)
        with open(config_path, 'r', encoding='utf-8') as f:
            CONFIG = json.load(f)
        
        # 提取API转发配置
        AI_VTUBER_CONFIG.update(CONFIG.get('api_forwarding', {
            "enabled": False,
            "host": "localhost",
            "port": 9880,
            "endpoint": "/api/danmaku/receive",
            "timeout": 5,
            "retry_count": 3,
            "retry_delay": 1
        }))
        
        # 提取WebSocket客户端配置
        WEBSOCKET_CLIENT_CONFIG.update(CONFIG.get('websocket_client', {
            "enabled": True,
            "host": "127.0.0.1",
            "port": 8765,
            "path": "/danmaku",
            "auto_reconnect": True,
            "reconnect_interval": 5,
            "max_reconnect_attempts": 10,
            "connection_timeout": 10
        }))
        
        # 初始化优化的WebSocket管理器
        websocket_config = CONFIG.get('websocket', {})
        max_clients = websocket_config.get('max_clients', 20)
        message_queue_size = websocket_config.get('message_queue_size', 100)
        enable_batching = websocket_config.get('enable_batching', True)
        
        optimized_ws_manager = OptimizedWebSocketManager(
            max_clients=max_clients,
            message_queue_size=message_queue_size,
            enable_batching=enable_batching
        )
        
        logging.info(f"配置文件加载成功: {config_path}")
        logging.info(f"API转发配置: {AI_VTUBER_CONFIG}")
        logging.info(f"WebSocket客户端配置: {WEBSOCKET_CLIENT_CONFIG}")
        logging.info(f"优化WebSocket管理器已初始化: 最大连接{max_clients}，队列大小{message_queue_size}，批处理{'启用' if enable_batching else '禁用'}")
        
        # 检查浏览器配置
        browser_config = CONFIG.get('browser', {})
        # 规范化配置中的 headless_mode，并默认使用有头模式（False）
        def _to_bool(v, default=False):
            if isinstance(v, bool):
                return v
            if v is None:
                return default
            if isinstance(v, str):
                s = v.strip().lower()
                if s in ("true", "1", "yes", "y", "on"):
                    return True
                if s in ("false", "0", "no", "n", "off"):
                    return False
                return default
            if isinstance(v, (int, float)):
                try:
                    return bool(int(v))
                except Exception:
                    return default
            return default

        global_headless = _to_bool(browser_config.get('headless_mode', browser_config.get('headless', False)), False)
        logging.info(f"浏览器模式初始化判定: 来源=全局配置, headless={global_headless}")
        if global_headless:
            logging.info("已启用headless模式，将大幅减少内存占用")
        else:
            logging.info("使用有头模式，可见浏览器窗口")
        
    except FileNotFoundError:
        logging.warning(f"配置文件不存在: {CONFIG_FILE}，使用默认配置")
        # 使用默认配置
        CONFIG = {
            "server": {"host": "localhost", "port": 8765, "debug": False},
            "browser": {"headless_mode": False, "max_pages": 3},
            "api_forwarding": {"enabled": False}
        }
        AI_VTUBER_CONFIG = {
            "enabled": False,
            "host": "localhost",
            "port": 9880,
            "endpoint": "/api/danmaku/receive",
            "timeout": 5,
            "retry_count": 3,
            "retry_delay": 1
        }
    except Exception as e:
        logging.error(f"加载配置文件失败: {e}")
        # 使用默认配置
        CONFIG = {
            "server": {"host": "localhost", "port": 8765, "debug": False},
            "browser": {"headless_mode": False, "max_pages": 3},
            "api_forwarding": {"enabled": False}
        }
        AI_VTUBER_CONFIG = {
            "enabled": False,
            "host": "localhost",
            "port": 9880,
            "endpoint": "/api/danmaku/receive",
            "timeout": 5,
            "retry_count": 3,
            "retry_delay": 1
        }

def load_blocked_keywords():
    """Loads blocked keywords from the JSON file."""
    global blocked_keywords
    try:
        with open(BLOCKED_KEYWORDS_FILE, 'r') as f:
            blocked_keywords = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        blocked_keywords = []

def save_blocked_keywords():
    """Saves the current list of blocked keywords to the JSON file."""
    with open(BLOCKED_KEYWORDS_FILE, 'w') as f:
        json.dump(blocked_keywords, f, indent=4)

# 加载消息格式配置
MESSAGE_FORMAT_CONFIG = None

def load_message_format_config():
    """加载消息格式配置文件"""
    global MESSAGE_FORMAT_CONFIG
    try:
        config_path = os.path.join(os.path.dirname(__file__), 'message_format_config.json')
        with open(config_path, 'r', encoding='utf-8') as f:
            MESSAGE_FORMAT_CONFIG = json.load(f)
        logging.info("消息格式配置加载成功")
    except Exception as e:
        logging.error(f"加载消息格式配置失败: {e}")
        # 使用默认配置
        MESSAGE_FORMAT_CONFIG = {
            "message_format_mapping": {
                "mappings": {
                    "danmaku": {"ai_vtuber_type": "comment"},
                    "gift": {"ai_vtuber_type": "gift"},
                    "entrance": {"ai_vtuber_type": "entrance"},
                    "follow": {"ai_vtuber_type": "follow"},
                    "like": {"ai_vtuber_type": "like"},
                    "super_chat": {"ai_vtuber_type": "super_chat"}
                }
            },
            "default_values": {
                "platform": "unknown",
                "timestamp": None,
                "user_id": "",
                "avatar": "",
                "content": ""
            }
        }

def format_message_for_ai_vtuber(danmaku_data: Dict[str, Any]) -> Dict[str, Any]:
    """将DanmakuListener消息格式转换为AI-VTUBER格式"""
    try:
        # 确保配置已加载
        if MESSAGE_FORMAT_CONFIG is None:
            load_message_format_config()
        
        data = danmaku_data.get("data", {})
        
        # 获取消息类型
        msg_type = data.get("messageType", "comment")
        
        # 获取映射配置
        mappings = MESSAGE_FORMAT_CONFIG.get('message_format_mapping', {}).get('mappings', {})
        default_values = MESSAGE_FORMAT_CONFIG.get('default_values', {})
        
        # 获取对应的映射规则
        mapping_rule = mappings.get(msg_type, mappings.get('danmaku', {}))
        ai_vtuber_type = mapping_rule.get('ai_vtuber_type', 'comment')
        field_mapping = mapping_rule.get('field_mapping', {})
        
        # 构建AI-VTUBER格式的消息
        ai_vtuber_message = {
            "type": ai_vtuber_type,
            "platform": data.get("platform", default_values.get('platform', 'unknown')),
            "username": data.get("username", ""),
            "content": data.get("content", default_values.get('content', '')),
            "timestamp": int(data.get("timestamp", time.time()) * 1000),
            "metadata": {
                "room_id": data.get("room_id", ""),
                "user_id": data.get("user_id", ""),
                "gift_name": data.get("gift_name", ""),
                "gift_count": data.get("gift_count", 0),
                "gift_price": data.get("gift_price", 0),
                "user_level": data.get("user_level", 0)
            }
        }
        
        # 根据字段映射添加其他字段
        for source_field, target_field in field_mapping.items():
            if source_field in data and source_field not in ['messageType', 'platform', 'username', 'content']:
                ai_vtuber_message[target_field] = data[source_field]
            elif target_field in default_values:
                ai_vtuber_message[target_field] = default_values[target_field]
        
        return ai_vtuber_message
        
    except Exception as e:
        logging.error(f"消息格式转换失败: {e}")
        # 返回原始格式作为备用
        data = danmaku_data.get("data", {})
        return {
            "type": data.get("messageType", "comment"),
            "platform": data.get("platform", "unknown"),
            "username": data.get("username", ""),
            "content": data.get("content", ""),
            "timestamp": int(data.get("timestamp", time.time()) * 1000),
            "metadata": {
                "room_id": data.get("room_id", ""),
                "user_id": data.get("user_id", ""),
                "gift_name": data.get("gift_name", ""),
                "gift_count": data.get("gift_count", 0),
                "gift_price": data.get("gift_price", 0),
                "user_level": data.get("user_level", 0)
            }
        }

async def forward_to_ai_vtuber(message: str) -> bool:
    """转发消息到AI-VTUBER，仅使用WebSocket，避免重复处理"""
    global websocket_client
    
    try:
        # 解析消息
        data = json.loads(message) if isinstance(message, str) else message
        
        # 转发所有支持的消息类型
        supported_types = ['danmaku', 'comment', 'gift', 'follow', 'like', 'entrance', 'super_chat']
        if data.get("type") not in supported_types:
            return True
        
        # 检查是否为空消息
        if data.get("type") == 'comment' or data.get("type") == 'danmaku':
            # 获取username和content，考虑嵌套在data中的情况
            username = data.get('username', '')
            content = data.get('content', '')
            if 'data' in data:
                username = data['data'].get('username', username)
                content = data['data'].get('content', content)
            
            # 忽略空消息
            if username == '' and content == '':
                logging.debug("忽略空消息，不转发到AI-VTUBER")
                return True
        
        # 仅使用WebSocket转发，避免重复处理
        if websocket_client and WEBSOCKET_CLIENT_CONFIG.get("enabled", False):
            # 直接传递原始数据，避免重复格式转换
            success = await websocket_client.send_message(data)
            
            if success:
                logging.info(f"消息已成功转发到AI-VTUBER: {data.get('type', 'unknown')}")
                return True
            else:
                logging.error("WebSocket转发失败，消息丢弃以避免重复处理")
                return False
        else:
            logging.warning("WebSocket客户端未启用或不可用，消息丢弃")
            return False
        
    except Exception as e:
        logging.error(f"转发消息到AI-VTUBER异常: {e}")
        return False

async def _forward_to_ai_vtuber_api(data: dict) -> bool:
    """通过API转发消息到AI-VTUBER（回退方案）"""
    if not AI_VTUBER_CONFIG["enabled"]:
        return True
        
    try:
        # 转换为AI-VTUBER兼容格式
        formatted_message = format_message_for_ai_vtuber(data)
        
        # 发送HTTP请求（带重试机制）
        url = f"http://{AI_VTUBER_CONFIG['host']}:{AI_VTUBER_CONFIG['port']}{AI_VTUBER_CONFIG['endpoint']}"
        
        api_stats["total_sent"] += 1
        
        # 重试逻辑
        for attempt in range(AI_VTUBER_CONFIG['retry_count'] + 1):
            try:
                timeout = aiohttp.ClientTimeout(total=AI_VTUBER_CONFIG['timeout'])
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(url, json=formatted_message) as response:
                        if response.status == 200:
                            result = await response.json()
                            api_stats["success_count"] += 1
                            if attempt > 0:
                                logging.info(f"API转发成功 (重试第{attempt}次): {result.get('message', '')}")
                            else:
                                logging.info(f"API转发成功: {result.get('message', '')}")
                            return True
                        else:
                            error_msg = f"HTTP {response.status}"
                            if attempt < AI_VTUBER_CONFIG['retry_count']:
                                logging.warning(f"API转发失败 (第{attempt + 1}次尝试): {error_msg}，{AI_VTUBER_CONFIG['retry_delay']}秒后重试")
                                await asyncio.sleep(AI_VTUBER_CONFIG['retry_delay'])
                                continue
                            else:
                                api_stats["error_count"] += 1
                                api_stats["last_error"] = error_msg
                                logging.error(f"API转发最终失败: {error_msg}")
                                return False
                                
            except (asyncio.TimeoutError, aiohttp.ClientConnectorError) as e:
                error_type = "请求超时" if isinstance(e, asyncio.TimeoutError) else "连接失败"
                if attempt < AI_VTUBER_CONFIG['retry_count']:
                    logging.warning(f"API转发{error_type} (第{attempt + 1}次尝试)，{AI_VTUBER_CONFIG['retry_delay']}秒后重试")
                    await asyncio.sleep(AI_VTUBER_CONFIG['retry_delay'])
                    continue
                else:
                    api_stats["error_count"] += 1
                    api_stats["last_error"] = error_type
                    logging.error(f"API转发最终失败: {error_type}")
                    return False
                    
    except Exception as e:
        api_stats["error_count"] += 1
        api_stats["last_error"] = str(e)
        logging.error(f"API转发异常: {e}")
        return False

async def handle_live_companion_message(raw_message: Dict[str, Any]):
    """
    处理来自直播伴侣客户端的消息
    """
    try:
        # 使用解析器转换消息格式
        parsed_message = douyin_parser.parse_message(raw_message)
        if not parsed_message:
            print(f"直播伴侣消息解析失败: {raw_message}")
            return
        
        msg_type = parsed_message.get("type")
        username = parsed_message.get("username", "")
        content = parsed_message.get("content", "")
        platform = parsed_message.get("platform", "douyin_live_companion")
        
        print(f"处理直播伴侣消息: 类型={msg_type}, 用户={username}, 内容={content}, 平台={platform}")
        
        # 对弹幕类消息进行关键词过滤
        if msg_type in ['danmaku', 'comment'] and content:
            if any(keyword in content for keyword in blocked_keywords if keyword):
                print(f"直播伴侣弹幕被屏蔽: {username}: {content}")
                return
        
        # 构建广播消息
        message_to_broadcast = {
            "type": msg_type,
            "data": {
                "username": username,
                "content": content,
                "platform": platform,
                "timestamp": parsed_message.get("timestamp", asyncio.get_event_loop().time()),
                "user_id": parsed_message.get("user_id", ""),
                "avatar": parsed_message.get("avatar", ""),
                "room_id": parsed_message.get("room_id", ""),
                "room_title": parsed_message.get("room_title", "")
            }
        }
        
        # 根据消息类型添加特定字段
        if msg_type == 'gift':
            message_to_broadcast["data"].update({
                "giftName": parsed_message.get("gift_name", ""),
                "giftCount": parsed_message.get("gift_count", 1),
                "giftPrice": parsed_message.get("gift_price", 0),
                "diamondCount": parsed_message.get("diamond_count", 0)
            })
        elif msg_type == 'like':
            message_to_broadcast["data"].update({
                "likeCount": parsed_message.get("like_count", 1),
                "totalLikes": parsed_message.get("total_likes", 0)
            })
        elif msg_type == 'entrance':
            message_to_broadcast["data"].update({
                "currentCount": parsed_message.get("current_count", 0),
                "enterTipType": parsed_message.get("enter_tip_type", 0)
            })
        elif msg_type == 'stats':
            message_to_broadcast["data"].update({
                "onlineUserCount": parsed_message.get("online_user_count", 0),
                "totalUserCount": parsed_message.get("total_user_count", 0),
                "onlineUserCountStr": parsed_message.get("online_user_count_str", "0"),
                "totalUserCountStr": parsed_message.get("total_user_count_str", "0")
            })
        
        # 广播消息
        await broadcast(json.dumps(message_to_broadcast))
        print(f"直播伴侣消息已广播: 类型={msg_type}, 用户={username}")
        
    except Exception as e:
        print(f"处理直播伴侣消息异常: {e}")
        import traceback
        traceback.print_exc()

async def broadcast(message):
    """
    优化的消息广播函数 - 使用OptimizedWebSocketManager
    """
    global optimized_ws_manager
    
    # 异步转发到AI-VTUBER（不阻塞WebSocket广播）
    asyncio.create_task(forward_to_ai_vtuber(message))
    
    # 使用优化的WebSocket管理器进行广播
    if optimized_ws_manager:
        await optimized_ws_manager.broadcast_optimized(message)
    else:
        # 回退到原有逻辑（兼容性）
        if not connected_clients:
            return
        
        clients_to_remove = set()
        
        for client in connected_clients.copy():
            try:
                if client.closed or client._writer is None or client._writer.transport is None:
                    clients_to_remove.add(client)
                    continue
                
                if hasattr(client._writer.transport, 'is_closing') and client._writer.transport.is_closing():
                    clients_to_remove.add(client)
                    continue
                else:
                    await client.send_str(message)
            except Exception as e:
                error_msg = str(e)
                if any(err in error_msg.lower() for err in ['connection', 'reset', 'closed', 'transport']):
                    pass
                else:
                    print(f"Error sending message to client: {e}")
                clients_to_remove.add(client)
        
        for client in clients_to_remove:
            connected_clients.discard(client)

async def send_blocked_keywords(websocket):
    """Sends the current list of blocked keywords to a specific client."""
    try:
        if not websocket.closed:
            await websocket.send_str(json.dumps({"type": "blocked_keywords", "data": blocked_keywords}))
    except Exception as e:
        print(f"Error sending blocked keywords: {e}")

async def websocket_handler(request):
    """
    优化的WebSocket连接处理器 - 使用OptimizedWebSocketManager
    """
    global optimized_ws_manager, blocked_keywords
    
    ws = web.WebSocketResponse(heartbeat=30, timeout=120, max_msg_size=16*1024*1024)
    try:
        await ws.prepare(request)
    except Exception as e:
        print(f"WebSocket准备失败: {e}")
        return web.Response(status=400, text=f"WebSocket preparation failed: {e}")
    
    # 获取客户端信息
    client_ip = request.remote
    user_agent = request.headers.get('User-Agent', 'Unknown')
    origin = request.headers.get('Origin', 'Unknown')
    referer = request.headers.get('Referer', 'Unknown')
    
    client_info = f"IP: {client_ip}, UA: {user_agent[:50]}..., Origin: {origin}, Referer: {referer}"
    
    # 使用优化的WebSocket管理器添加客户端
    if optimized_ws_manager:
        try:
            await optimized_ws_manager.add_client(ws, client_ip, user_agent)
            print(f"\n=== 优化WebSocket 连接建立 ===")
            print(f"客户端信息: {client_info}")
            stats = optimized_ws_manager.get_statistics()
            print(f"当前连接数: {stats['current_connections']}")
            print("=" * 40)
        except ConnectionError as e:
            print(f"连接被拒绝: {e}")
            return web.Response(status=503, text=str(e))
    else:
        # 回退到原有逻辑
        connected_clients.add(ws)
        print(f"\n=== WebSocket 连接建立 ===")
        print(f"客户端信息: {client_info}")
        print(f"当前连接数: {len(connected_clients)}")
        print("=" * 40)
    
    try:
        await send_blocked_keywords(ws)

        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                print(f"Received message: {msg.data}")
                try:
                    data = json.loads(msg.data)
                    msg_type = data.get("type")
                    msg_data = data.get("data")

                    if msg_type == 'add_keyword' and isinstance(msg_data, str):
                        if msg_data not in blocked_keywords:
                            blocked_keywords.append(msg_data)
                            save_blocked_keywords()
                        await broadcast(json.dumps({"type": "blocked_keywords", "data": blocked_keywords}))

                    elif msg_type == 'remove_keyword' and isinstance(msg_data, str):
                        if msg_data in blocked_keywords:
                            blocked_keywords.remove(msg_data)
                            save_blocked_keywords()
                        await broadcast(json.dumps({"type": "blocked_keywords", "data": blocked_keywords}))

                    elif msg_type in ['comment', 'gift', 'like', 'danmaku', 'follow', 'enter']:
                        # Handle different types of messages from clients
                        username = data.get('username', '')
                        content = data.get('content', '')
                        platform = data.get('platform', '未知平台')
                        
                        print(f"处理消息: 类型={msg_type}, 用户={username}, 内容={content}, 平台={platform}")
                        
                        # Skip empty comment messages
                        if msg_type == 'comment' and username == '' and content == '':
                            print("忽略空消息")
                            continue
                        
                        # For comment/danmaku messages, check blocked keywords
                        if msg_type in ['comment', 'danmaku']:
                            if any(keyword in content for keyword in blocked_keywords if keyword):
                                print(f"弹幕被屏蔽: {username}: {content}")
                                continue
                        
                        # Broadcast the message with its original type
                        message_to_broadcast = {
                            "type": msg_type,
                            "data": {
                                "username": username,
                                "content": content,
                                "platform": platform,
                                "timestamp": asyncio.get_event_loop().time()
                            }
                        }
                        
                        # Add additional fields for specific message types
                        if msg_type == 'gift':
                            message_to_broadcast["data"]["giftName"] = data.get('giftName', '')
                            message_to_broadcast["data"]["giftCount"] = data.get('giftCount', 1)
                        
                        await broadcast(json.dumps(message_to_broadcast))
                        print(f"消息已广播: 类型={msg_type}, 用户={username}")
                    
                    elif msg_type == 'info':
                        print(f"Info message: {data.get('content', '')}")

                    elif msg_type == 'log':
                        level = data.get('level', 'info').upper()
                        log_message = data.get('message', '')
                        log_data = data.get('data', {})
                        logging.info(f"[FRONTEND SCRIPT LOG - {level}] {log_message} | Data: {log_data}")
                    
                    else:
                        await broadcast(msg.data)

                except (json.JSONDecodeError, AttributeError) as e:
                    print(f"JSON decode error: {e}")
                    if not any(keyword in msg.data for keyword in blocked_keywords if keyword):
                        await broadcast(msg.data)
                except Exception as e:
                    print(f"Error processing message: {e}")
                    
            elif msg.type == web.WSMsgType.ERROR:
                print(f"WebSocket connection closed with exception {ws.exception()}")
                break
            elif msg.type == web.WSMsgType.CLOSE:
                print(f"WebSocket connection closed normally")
                break

    except asyncio.CancelledError:
        print(f"WebSocket连接被取消: {client_info}")
    except ConnectionResetError:
        print(f"WebSocket连接被重置: {client_info}")
    except Exception as e:
        # 过滤常见的连接错误，避免日志污染
        error_msg = str(e)
        error_type = type(e).__name__
        
        if any(err in error_msg.lower() for err in ['connection', 'reset', 'closed', 'transport']) or \
           error_type in ['ClientConnectionResetError', 'ConnectionResetError', 'ConnectionAbortedError']:
            pass
        else:
            print(f"\n=== WebSocket 连接异常 ===")
            print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"异常类型: {error_type}")
            print(f"异常信息: {e}")
            print(f"客户端信息: {client_info}")
            print("=" * 40)
    finally:
        # 使用优化管理器清理连接
        if optimized_ws_manager:
            await optimized_ws_manager.remove_client(ws)
            print(f"\n=== 优化WebSocket 连接断开 ===")
            print(f"客户端信息: {client_info}")
            stats = optimized_ws_manager.get_statistics()
            print(f"当前连接数: {stats['current_connections']}")
            print("=" * 40)
        else:
            # 回退到原有逻辑
            if not ws.closed:
                try:
                    await ws.close()
                except Exception as e:
                    print(f"关闭WebSocket时出错: {e}")
            
            if ws in connected_clients:
                connected_clients.remove(ws)
            print(f"\n=== WebSocket 连接断开 ===")
            print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"客户端信息: {client_info}")
            print(f"当前连接数: {len(connected_clients)}")
            print("=" * 40)

    return ws

async def index(request):
    # 使用绝对路径确保无论从哪个目录启动都能找到HTML文件
    html_path = os.path.join(os.path.dirname(__file__), 'index.html')
    resp = web.FileResponse(html_path)
    # 禁用缓存，确保外部浏览器不使用旧版HTML/脚本
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

async def monitor(request):
    # 使用绝对路径确保无论从哪个目录启动都能找到HTML文件
    html_path = os.path.join(os.path.dirname(__file__), 'monitor.html')
    resp = web.FileResponse(html_path)
    # 禁用缓存，确保外部浏览器不使用旧版HTML/脚本
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

# URL管理API接口
async def api_get_urls(request):
    """获取所有URL配置"""
    try:
        urls = url_manager.get_all_urls()
        return json_response({"success": True, "data": urls})
    except Exception as e:
        return json_response({"success": False, "error": str(e)}, status=500)

async def api_add_url(request):
    """添加新的URL配置"""
    try:
        data = await request.json()
        required_fields = ['name', 'url', 'platform']
        
        for field in required_fields:
            if field not in data:
                return json_response({"success": False, "error": f"Missing required field: {field}"}, status=400)
        
        # 验证URL格式
        if not url_manager.validate_url(data['url'], data['platform']):
            return json_response({"success": False, "error": "Invalid URL format for the specified platform"}, status=400)
        
        url_config = url_manager.add_url(
            name=data['name'],
            url=data['url'],
            platform=data['platform'],
            enabled=data.get('enabled', True),
            priority=data.get('priority', 1),
            headless_mode=data.get('headless_mode', False),
            auto_login=data.get('auto_login', False),
            login_required=data.get('login_required', False)
        )
        
        # 如果启用了监控，自动启动
        if data.get('enabled', True) and browser_manager:
            try:
                # 创建监控会话
                session = monitor_manager.create_session(url_config['id'])
                # 启动浏览器监控（后台任务）
                asyncio.create_task(browser_manager.start_monitoring(url_config['id'], False))
                print(f"自动启动监控: {url_config['name']} ({url_config['id']})")
            except Exception as e:
                print(f"自动启动监控失败: {e}")
        
        return json_response({"success": True, "data": url_config})
    except json.JSONDecodeError:
        return json_response({"success": False, "error": "Invalid JSON data"}, status=400)
    except Exception as e:
        return json_response({"success": False, "error": str(e)}, status=500)

async def api_update_url(request):
    """更新URL配置"""
    try:
        url_id = request.match_info['url_id']
        data = await request.json()
        
        # 如果更新URL和平台，需要验证格式
        if 'url' in data and 'platform' in data:
            if not url_manager.validate_url(data['url'], data['platform']):
                return json_response({"success": False, "error": "Invalid URL format for the specified platform"}, status=400)
        
        success = url_manager.update_url(url_id, **data)
        
        if success:
            updated_url = url_manager.get_url(url_id)
            
            # 如果更新后启用了监控，且当前没有运行，自动启动
            if data.get('enabled', False) and browser_manager:
                current_session = monitor_manager.get_session(url_id)
                if not current_session or current_session.get('status') not in ['running', 'starting']:
                    try:
                        # 创建监控会话
                        session = monitor_manager.create_session(url_id)
                        # 启动浏览器监控（后台任务）
                        asyncio.create_task(browser_manager.start_monitoring(url_id, False))
                        print(f"自动启动监控: {updated_url['name']} ({url_id})")
                    except Exception as e:
                        print(f"自动启动监控失败: {e}")
            
            return json_response({"success": True, "data": updated_url})
        else:
            return json_response({"success": False, "error": "URL not found"}, status=404)
    except json.JSONDecodeError:
        return json_response({"success": False, "error": "Invalid JSON data"}, status=400)
    except Exception as e:
        return json_response({"success": False, "error": str(e)}, status=500)

async def api_delete_url(request):
    """删除URL配置"""
    try:
        url_id = request.match_info['url_id']
        
        # 检查是否正在监控中
        session = monitor_manager.get_session(url_id)
        if session and session['status'] == MonitorStatus.RUNNING.value:
            # 检查是否真的在浏览器中运行
            if browser_manager and url_id in browser_manager.pages:
                return json_response({"success": False, "error": "Cannot delete URL while monitoring is active"}, status=400)
            else:
                # 如果状态是RUNNING但实际没有在浏览器中运行，清理状态
                print(f"清理僵尸RUNNING状态: {url_id}")
                monitor_manager.update_session_status(url_id, MonitorStatus.STOPPED)
        
        success = url_manager.delete_url(url_id)
        
        if success:
            # 同时清理监控状态
            monitor_manager.remove_session(url_id)
            return json_response({"success": True, "message": "URL deleted successfully"})
        else:
            return json_response({"success": False, "error": "URL not found"}, status=404)
    except Exception as e:
        return json_response({"success": False, "error": str(e)}, status=500)

async def api_get_url(request):
    """获取单个URL配置"""
    try:
        url_id = request.match_info['url_id']
        url_config = url_manager.get_url(url_id)
        
        if url_config:
            return json_response({"success": True, "data": url_config})
        else:
            return json_response({"success": False, "error": "URL not found"}, status=404)
    except Exception as e:
        return json_response({"success": False, "error": str(e)}, status=500)

# 监控状态API接口
async def api_get_monitor_status(request):
    """获取所有监控状态"""
    try:
        sessions = monitor_manager.get_all_sessions()
        stats = monitor_manager.get_session_statistics()
        
        # 构建状态映射，前端需要的格式
        status_map = {}
        for url_id, session in sessions.items():
            if 'status' in session:
                status_map[url_id] = session['status']
        
        return json_response({"success": True, "status": status_map, "data": {"sessions": sessions, "statistics": stats}})
    except Exception as e:
        return json_response({"success": False, "error": str(e)}, status=500)

async def api_get_session_status(request):
    """获取单个会话状态"""
    try:
        url_id = request.match_info['url_id']
        session = monitor_manager.get_session(url_id)
        
        if session:
            return json_response({"success": True, "data": session})
        else:
            return json_response({"success": False, "error": "Session not found"}, status=404)
    except Exception as e:
        return json_response({"success": False, "error": str(e)}, status=500)

async def api_start_monitor(request):
    """启动监控"""
    global browser_manager
    try:
        data = await request.json()
        url_id = data.get('url_id')
        # 规范化 force_headed
        force_headed_raw = data.get('force_headed', False)
        def _to_bool2(v, default=False):
            if isinstance(v, bool):
                return v
            if v is None:
                return default
            if isinstance(v, str):
                s = v.strip().lower()
                if s in ("true", "1", "yes", "y", "on"):
                    return True
                if s in ("false", "0", "no", "n", "off"):
                    return False
                return default
            if isinstance(v, (int, float)):
                try:
                    return bool(int(v))
                except Exception:
                    return default
            return default
        force_headed = _to_bool2(force_headed_raw, False)
        
        if not url_id:
            return json_response({"success": False, "error": "Missing url_id"}, status=400)
        
        # 检查URL是否存在
        url_config = url_manager.get_url(url_id)
        if not url_config:
            return json_response({"success": False, "error": "URL not found"}, status=404)
        
        # 检查是否已在监控中
        session = monitor_manager.get_session(url_id)
        if session and session['status'] in [MonitorStatus.RUNNING.value, MonitorStatus.STARTING.value]:
            # 如果状态是STARTING但实际没有在浏览器中运行，清理状态
            if session['status'] == MonitorStatus.STARTING.value and browser_manager and url_id not in browser_manager.pages:
                print(f"清理僵尸STARTING状态: {url_id}")
                monitor_manager.update_session_status(url_id, MonitorStatus.STOPPED)
            else:
                return json_response({"success": False, "error": "Monitor already running or starting"}, status=400)
        
        # 创建监控会话
        session = monitor_manager.create_session(url_id)
        
        # 启动浏览器监控（后台任务）
        if browser_manager:
            asyncio.create_task(browser_manager.start_monitoring(url_id, force_headed))
            return json_response({"success": True, "data": session, "message": "正在后台启动监控..."})
        else:
            return json_response({"success": False, "error": "Browser manager not initialized"}, status=500)
        
    except json.JSONDecodeError:
        return json_response({"success": False, "error": "Invalid JSON data"}, status=400)
    except Exception as e:
        return json_response({"success": False, "error": str(e)}, status=500)

async def api_stop_monitor(request):
    """停止监控"""
    global browser_manager
    try:
        data = await request.json()
        url_id = data.get('url_id')
        
        if not url_id:
            return json_response({"error": "Missing url_id"}, status=400)
        
        # 检查会话是否存在
        session = monitor_manager.get_session(url_id)
        
        # 停止浏览器监控
        if browser_manager:
            success = await browser_manager.stop_monitoring(url_id)
            if success:
                # 确保会话状态被更新为停止
                if session:
                    monitor_manager.update_session_status(url_id, MonitorStatus.STOPPED)
                return json_response({"message": "监控已停止"})
            else:
                # 即使浏览器停止失败，也更新会话状态
                if session:
                    monitor_manager.update_session_status(url_id, MonitorStatus.STOPPED)
                return json_response({"message": "监控已停止"})
        else:
            # 如果浏览器管理器不可用，至少更新状态
            if session:
                monitor_manager.update_session_status(url_id, MonitorStatus.STOPPED)
            return json_response({"message": "监控已停止 (browser manager not available)"})
        
    except Exception as e:
        return json_response({"error": str(e)}, status=500)

async def api_restart_monitor(request):
    """重启监控"""
    global browser_manager
    try:
        data = await request.json()
        url_id = data.get('url_id')

        if not url_id:
            return json_response({"success": False, "error": "Missing url_id"}, status=400)

        # 检查URL是否存在
        url_config = url_manager.get_url(url_id)
        if not url_config:
            return json_response({"success": False, "error": "URL not found"}, status=404)

        if browser_manager:
            # 使用后台任务重启，避免阻塞请求
            asyncio.create_task(browser_manager.restart_monitoring(url_id))
            return json_response({"success": True, "message": "正在后台重启监控..."})
        else:
            return json_response({"success": False, "error": "Browser manager not initialized"}, status=500)

    except Exception as e:
        return json_response({"success": False, "error": str(e)}, status=500)

# 脚本配置管理API
async def api_get_scripts(request):
    """获取可用脚本列表API"""
    try:
        scripts = browser_manager.get_available_scripts()
        current_script_info = browser_manager.get_current_script_info()
        
        return json_response({
            'success': True,
            'scripts': scripts,
            'current_script': current_script_info
        })
    except Exception as e:
        print(f"获取脚本列表API错误: {e}")
        return json_response({
            'success': False,
            'message': f'获取脚本列表失败: {str(e)}'
        }, status=500)

async def api_set_current_script(request):
    """设置当前脚本API"""
    try:
        data = await request.json()
        filename = data.get('filename')
        
        if not filename:
            return json_response({
                'success': False,
                'message': '缺少filename参数'
            }, status=400)
        
        success = browser_manager.set_current_script(filename)
        
        if success:
            return json_response({
                'success': True,
                'message': f'脚本已切换到: {filename}'
            })
        else:
            return json_response({
                'success': False,
                'message': f'切换脚本失败: {filename}'
            }, status=400)
            
    except Exception as e:
        print(f"设置当前脚本API错误: {e}")
        return json_response({
            'success': False,
            'message': f'设置脚本失败: {str(e)}'
        }, status=500)

async def api_add_script(request):
    """添加脚本API"""
    try:
        data = await request.json()
        name = data.get('name')
        filename = data.get('filename')
        path = data.get('path')
        description = data.get('description', '')
        
        if not all([name, filename, path]):
            return json_response({
                'success': False,
                'message': '缺少必要参数: name, filename, path'
            }, status=400)
        
        success = browser_manager.add_script(name, filename, path, description)
        
        if success:
            return json_response({
                'success': True,
                'message': f'脚本 {name} 添加成功'
            })
        else:
            return json_response({
                'success': False,
                'message': f'添加脚本失败: {name}'
            }, status=400)
            
    except Exception as e:
        print(f"添加脚本API错误: {e}")
        return json_response({
            'success': False,
            'message': f'添加脚本失败: {str(e)}'
        }, status=500)

async def api_remove_script(request):
    """移除脚本API"""
    try:
        data = await request.json()
        filename = data.get('filename')
        
        if not filename:
            return json_response({
                'success': False,
                'message': '缺少filename参数'
            }, status=400)
        
        success = browser_manager.remove_script(filename)
        
        if success:
            return json_response({
                'success': True,
                'message': f'脚本 {filename} 移除成功'
            })
        else:
            return json_response({
                'success': False,
                'message': f'移除脚本失败: {filename}'
            }, status=400)
            
    except Exception as e:
        print(f"移除脚本API错误: {e}")
        return json_response({
            'success': False,
            'message': f'移除脚本失败: {str(e)}'
        }, status=500)

# WebSocket连接池管理API
async def api_get_websocket_stats(request):
    """获取WebSocket连接池统计信息"""
    global optimized_ws_manager
    try:
        if optimized_ws_manager:
            stats = optimized_ws_manager.get_statistics()
            return json_response({
                'success': True,
                'data': stats
            })
        else:
            return json_response({
                'success': False,
                'message': 'WebSocket管理器未初始化'
            }, status=500)
    except Exception as e:
        return json_response({
            'success': False,
            'error': str(e)
        }, status=500)

async def api_cleanup_websocket_connections(request):
    """清理WebSocket死连接"""
    global optimized_ws_manager
    try:
        if optimized_ws_manager:
            # 强制清理死连接和空闲连接
            await optimized_ws_manager._cleanup_dead_connections()
            await optimized_ws_manager._cleanup_idle_connections()
            
            stats = optimized_ws_manager.get_statistics()
            return json_response({
                'success': True,
                'message': '连接清理完成',
                'data': stats
            })
        else:
            return json_response({
                'success': False,
                'message': 'WebSocket管理器未初始化'
            }, status=500)
    except Exception as e:
        return json_response({
            'success': False,
            'error': str(e)
        }, status=500)

async def api_scan_scripts(request):
    """扫描脚本API"""
    try:
        added_count = browser_manager.scan_for_scripts()
        
        return json_response({
            'success': True,
            'message': f'扫描完成，发现并添加了 {added_count} 个新脚本',
            'added_count': added_count
        })
        
    except Exception as e:
        print(f"扫描脚本API错误: {e}")
        return json_response({
            'success': False,
            'message': f'扫描脚本失败: {str(e)}'
        }, status=500)

async def api_get_forwarding_stats(request):
    """获取API转发统计信息"""
    try:
        return json_response({
            'success': True,
            'data': {
                'enabled': AI_VTUBER_CONFIG['enabled'],
                'stats': api_stats,
                'config': {
                    'host': AI_VTUBER_CONFIG['host'],
                    'port': AI_VTUBER_CONFIG['port'],
                    'endpoint': AI_VTUBER_CONFIG['endpoint']
                }
            }
        })
    except Exception as e:
        return json_response({
            'success': False,
            'message': f'获取统计信息失败: {str(e)}'
        }, status=500)

async def api_get_config(request):
    """获取完整的config.json内容"""
    try:
        return json_response({"success": True, "data": CONFIG})
    except Exception as e:
        return json_response({"success": False, "error": str(e)}, status=500)

async def api_update_config(request):
    """更新config.json内容"""
    try:
        data = await request.json()
        
        # 更新全局配置
        for key, value in data.items():
            CONFIG[key] = value
            
        save_config()
        
        return json_response({"success": True, "message": "配置更新成功"})
    except json.JSONDecodeError:
        return json_response({"success": False, "error": "Invalid JSON data"}, status=400)
    except Exception as e:
        return json_response({"success": False, "error": str(e)}, status=500)

def save_config():
    """保存当前配置到config.json"""
    try:
        config_path = os.path.join(os.path.dirname(__file__), CONFIG_FILE)
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(CONFIG, f, indent=4, ensure_ascii=False)
        logging.info(f"配置文件已保存: {config_path}")
    except Exception as e:
        logging.error(f"保存配置文件失败: {e}")

async def api_get_forwarding_config(request):
    """获取API转发配置"""
    try:
        return json_response({
            'success': True,
            'data': AI_VTUBER_CONFIG
        })
    except Exception as e:
        return json_response({
            'success': False,
            'message': f'获取配置失败: {str(e)}'
        }, status=500)

async def api_update_forwarding_config(request):
    """更新API转发配置"""
    try:
        data = await request.json()
        
        # 验证配置参数
        if 'enabled' in data:
            AI_VTUBER_CONFIG['enabled'] = bool(data['enabled'])
        if 'host' in data:
            AI_VTUBER_CONFIG['host'] = str(data['host'])
        if 'port' in data:
            AI_VTUBER_CONFIG['port'] = int(data['port'])
        if 'endpoint' in data:
            AI_VTUBER_CONFIG['endpoint'] = str(data['endpoint'])
        if 'timeout' in data:
            AI_VTUBER_CONFIG['timeout'] = int(data['timeout'])
        if 'retry_count' in data:
            AI_VTUBER_CONFIG['retry_count'] = int(data['retry_count'])
        if 'retry_delay' in data:
            AI_VTUBER_CONFIG['retry_delay'] = int(data['retry_delay'])
        
        return json_response({
            'success': True,
            'message': '配置更新成功',
            'data': AI_VTUBER_CONFIG
        })
        
    except Exception as e:
        return json_response({
            'success': False,
            'message': f'更新配置失败: {str(e)}'
        }, status=500)




async def api_test_forwarding(request):
    """测试API转发连接"""
    try:
        # 构造测试消息
        test_message = {
            "type": "danmaku",
            "data": {
                "messageType": "comment",
                "platform": "test",
                "username": "测试用户",
                "content": "API连接测试消息",
                "timestamp": time.time(),
                "room_id": "test_room",
                "user_id": "test_user"
            }
        }
        
        # 尝试转发
        success = await forward_to_ai_vtuber(json.dumps(test_message))
        
        if success:
            return json_response({
                'success': True,
                'message': 'API转发测试成功',
                'data': {
                    'test_result': 'success',
                    'stats': api_stats
                }
            })
        else:
            return json_response({
                'success': False,
                'message': 'API转发测试失败',
                'data': {
                    'test_result': 'failed',
                    'stats': api_stats
                }
            })
            
    except Exception as e:
        return json_response({
            'success': False,
            'message': f'测试失败: {str(e)}'
        }, status=500)

async def api_start_client_listener(request):
    """启动客户端监听器"""
    try:
        import subprocess
        import os
        import psutil
        import ctypes
        import time
        
        # 尝试多个可能的WssBarrageServer.exe路径
        possible_paths = [
            os.path.join(os.path.dirname(__file__), 'static', 'Release', 'WssBarrageServer.exe'),
            os.path.join(os.path.dirname(__file__), 'static', 'WssBarrageServer.exe'),
            os.path.join(os.path.dirname(__file__), 'WssBarrageServer.exe'),
            os.path.join(os.path.dirname(__file__), '..', 'WssBarrageServer.exe'),
            os.path.join(os.getcwd(), 'WssBarrageServer.exe')
        ]
        
        exe_path = None
        for path in possible_paths:
            if os.path.exists(path):
                exe_path = path
                logging.info(f'找到客户端监听器文件: {exe_path}')
                break
        
        # 如果所有路径都不存在，返回详细错误信息
        if not exe_path:
            logging.error('在所有可能路径中都未找到WssBarrageServer.exe')
            
            # 检查目录结构，帮助用户定位问题
            search_results = []
            for path in possible_paths:
                dir_path = os.path.dirname(path)
                if os.path.exists(dir_path):
                    files = [f for f in os.listdir(dir_path) if f.endswith('.exe')]
                    search_results.append({
                        'path': dir_path,
                        'exists': True,
                        'exe_files': files
                    })
                else:
                    search_results.append({
                        'path': dir_path,
                        'exists': False,
                        'exe_files': []
                    })
            
            return web.json_response({
                'success': False,
                'message': 'WssBarrageServer.exe文件未找到，请检查文件是否存在或路径是否正确',
                'details': {
                    'searched_paths': possible_paths,
                    'search_results': search_results,
                    'suggestion': '请确保WssBarrageServer.exe文件存在于以下任一路径中，或手动将文件放置到DanmakuListener目录下'
                }
            }, status=404)
        
        # 检查是否已有WssBarrageServer.exe在运行
        running_processes = []
        try:
            import psutil
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if proc.info['name'] == 'WssBarrageServer.exe':
                        running_processes.append({
                            'pid': proc.info['pid'],
                            'cmdline': proc.info.get('cmdline', [])
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
        except ImportError:
            logging.warning("psutil未安装，跳过进程检查")
        
        if running_processes:
            logging.info(f"发现已运行的WssBarrageServer.exe进程: {running_processes}")
            return web.json_response({
                'success': True,
                'message': f'客户端监听器已在运行中 (发现 {len(running_processes)} 个进程)',
                'running_processes': running_processes
            })
        
        # 检查当前进程是否具有管理员权限
        def is_admin():
            try:
                return ctypes.windll.shell32.IsUserAnAdmin()
            except:
                return False
        
        # 检测是否在webui环境中运行（检查父进程）
        def is_running_from_webui():
            try:
                import psutil
                current_proc = psutil.Process()
                
                # 检查当前进程的命令行参数
                current_cmdline = ' '.join(current_proc.cmdline())
                if 'DanmakuListener' in current_cmdline:
                    # 检查父进程
                    parent = current_proc.parent()
                    if parent:
                        parent_cmdline = ' '.join(parent.cmdline())
                        parent_name = parent.name().lower()
                        logging.info(f"父进程检测: 名称={parent_name}, 命令行={parent_cmdline}")
                        
                        # 检查是否通过webui或python解释器启动
                        if ('webui.py' in parent_cmdline or 
                            'webui' in parent_name or 
                            parent_name in ['python.exe', 'python3.exe', 'python'] and 'webui' in parent_cmdline):
                            return True
                        
                        # 检查祖父进程
                        grandparent = parent.parent()
                        if grandparent:
                            grandparent_cmdline = ' '.join(grandparent.cmdline())
                            grandparent_name = grandparent.name().lower()
                            logging.info(f"祖父进程检测: 名称={grandparent_name}, 命令行={grandparent_cmdline}")
                            
                            if ('webui.py' in grandparent_cmdline or 
                                'webui' in grandparent_name):
                                return True
                
                return False
            except Exception as e:
                logging.warning(f"检查webui环境时出错: {e}，假设为webui环境")
                # 如果检测失败，为了安全起见假设是webui环境
                return True
        
        is_admin_user = is_admin()
        from_webui = is_running_from_webui()
        
        logging.info(f"当前进程管理员权限: {is_admin_user}, 来自webui: {from_webui}")
        
        # 在Windows上启动进程
        if sys.platform.startswith('win'):
            success = False
            start_method = "未知"
            process_pid = None
            error_msg = None
            
            # 方法1: 优先尝试直接启动（大多数情况下有效）
            try:
                logging.info("尝试直接启动WssBarrageServer.exe")
                
                # 检查是否通过webui启动，如果是，尝试特殊的启动方式
                if from_webui:
                    logging.info("检测到webui环境，尝试通过explorer启动以绕过权限限制")
                    # 使用explorer.exe启动，可以绕过一些权限限制
                    process = subprocess.Popen(
                        ['explorer.exe', exe_path],
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    # explorer启动后会立即返回，所以我们等待一下看程序是否启动
                    time.sleep(3)
                    
                    # 检查进程是否启动
                    wss_running = False
                    try:
                        import psutil
                        for proc in psutil.process_iter(['name']):
                            try:
                                if proc.info['name'] == 'WssBarrageServer.exe':
                                    wss_running = True
                                    process_pid = proc.pid
                                    break
                            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                                pass
                    except ImportError:
                        pass
                    
                    if wss_running:
                        start_method = "explorer启动(webui环境)"
                        success = True
                        logging.info(f"通过explorer启动成功，WssBarrageServer.exe PID: {process_pid}")
                    else:
                        logging.warning("通过explorer启动失败，将尝试直接启动")
                        # 如果explorer方式失败，继续尝试直接启动
                        process = subprocess.Popen(
                            [exe_path],
                            cwd=os.path.dirname(exe_path),
                            creationflags=subprocess.CREATE_NO_WINDOW
                        )
                        process_pid = process.pid
                        start_method = "直接启动(webui环境)"
                        
                        time.sleep(2)
                        if process.poll() is None:
                            success = True
                            logging.info(f"直接启动成功，PID: {process_pid}")
                        else:
                            return_code = process.returncode
                            logging.warning(f"进程立即退出，返回码: {return_code}")
                            # 记录错误但继续尝试其他方法
                            error_msg = f"进程退出，返回码: {return_code}"
                else:
                    # 非webui环境，使用常规方式启动
                    process = subprocess.Popen(
                        [exe_path],
                        cwd=os.path.dirname(exe_path),
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    process_pid = process.pid
                    start_method = "直接启动"
                    
                    # 等待一小段时间检查进程是否成功启动
                    time.sleep(2)
                    if process.poll() is None:  # 进程仍在运行
                        success = True
                        logging.info(f"直接启动成功，PID: {process_pid}")
                    else:
                        return_code = process.returncode
                        logging.warning(f"进程立即退出，返回码: {return_code}")
                        # 即使进程退出，也记录为成功，因为可能是服务器模式
                        success = True
                        start_method = "直接启动(进程快速退出)"
                        
            except Exception as e:
                error_msg = str(e)
                logging.error(f"直接启动失败: {e}")
                success = False
            
            # 方法2: 如果直接启动失败且是权限问题，尝试UAC提升
            if not success and error_msg and ("740" in error_msg or "需要提升" in error_msg):
                try:
                    logging.info("检测到权限问题，尝试UAC权限提升启动")
                    
                    if from_webui:
                        # webui环境下，使用非阻塞式启动
                        powershell_cmd = f'Start-Process -FilePath "{exe_path}" -WorkingDirectory "{os.path.dirname(exe_path)}" -Verb RunAs'
                        logging.info(f'将执行PowerShell命令: {powershell_cmd}')
                        
                        process = subprocess.Popen(
                            ['powershell', '-Command', powershell_cmd],
                            creationflags=subprocess.CREATE_NO_WINDOW
                        )
                        process_pid = process.pid
                        start_method = "UAC权限提升(webui环境)"
                        success = True
                        logging.info(f"UAC权限提升命令已执行，PowerShell PID: {process_pid}")
                    else:
                        # 非webui环境下，使用同步启动
                        powershell_cmd = f'Start-Process -FilePath "{exe_path}" -WorkingDirectory "{os.path.dirname(exe_path)}" -Verb RunAs -Wait'
                        logging.info(f'将执行同步PowerShell命令: {powershell_cmd}')
                        
                        process = subprocess.Popen(
                            ['powershell', '-Command', powershell_cmd],
                            creationflags=subprocess.CREATE_NO_WINDOW
                        )
                        process_pid = process.pid
                        start_method = "UAC权限提升(独立环境)"
                        success = True
                        logging.info(f"UAC权限提升同步命令已执行，PowerShell PID: {process_pid}")
                        
                except Exception as e:
                    logging.error(f"UAC权限提升启动失败: {e}")
                    success = False
            
            if success:
                # 等待2秒后检查WssBarrageServer.exe是否真的启动了
                await asyncio.sleep(2)
                
                new_processes = []
                try:
                    import psutil
                    for proc in psutil.process_iter(['pid', 'name', 'create_time']):
                        try:
                            if proc.info['name'] == 'WssBarrageServer.exe':
                                new_processes.append({
                                    'pid': proc.info['pid'],
                                    'create_time': proc.info['create_time']
                                })
                        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                            pass
                except ImportError:
                    logging.warning("psutil未安装，无法检查进程状态")
                
                if new_processes:
                    logging.info(f"确认WssBarrageServer.exe已启动: {new_processes}")
                    message = f'客户端监听器启动成功 (方法: {start_method})'
                    if from_webui:
                        message += ' - 在webui环境中运行'
                else:
                    if "UAC" in start_method:
                        if from_webui:
                            message = f'''客户端监听器启动命令已执行 (方法: {start_method})。

⚠️ 检测到您在webui环境中运行，由于权限限制，UAC提示可能无法正常显示。

🛠️ 如果程序未启动，请尝试:
1. 关闭webui，以管理员身份运行 cmd，然后执行: python webui.py
2. 或右键点击"WssBarrageServer.exe"，选择"以管理员身份运行"
3. 或在Windows设置中降低UAC级别

📋 文件位置: D:\\AI\\AI-Vtuber\\DanmakuListener\\static\\Release\\WssBarrageServer.exe'''
                        else:
                            message = f'客户端监听器启动命令已执行 (方法: {start_method})，请检查是否需要用户确认UAC提示'
                    else:
                        message = f'客户端监听器启动命令已执行 (方法: {start_method})，但未检测到进程，请手动检查进程状态'
                
                return web.json_response({
                    'success': True,
                    'message': message,
                    'details': {
                        'start_method': start_method,
                        'command_pid': process_pid,
                        'is_admin': is_admin_user,
                        'from_webui': from_webui,
                        'detected_processes': new_processes,
                        'note': '根据环境自动选择最适合的启动方式'
                    }
                })
            else:
                return web.json_response({
                    'success': False,
                    'message': '启动客户端监听器失败',
                    'details': {
                        'is_admin': is_admin_user,
                        'from_webui': from_webui,
                        'error': error_msg or '未知错误',
                        'suggestion': '请尝试以管理员权限运行整个AI-Vtuber系统或手动启动WssBarrageServer.exe'
                    }
                }, status=500)
        
        else:
            # 非Windows系统的启动方式
            logging.info(f'在非Windows系统上启动: {exe_path}')
            process = subprocess.Popen(
                [exe_path],
                cwd=os.path.dirname(exe_path)
            )
            
            logging.info(f"客户端监听器启动命令已执行，PID: {process.pid}")
            
            return web.json_response({
                'success': True,
                'message': '客户端监听器启动成功',
                'pid': process.pid
            })
        
    except Exception as e:
        logging.error(f"启动客户端监听器失败: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return web.json_response({
            'success': False,
            'message': f'启动客户端监听器失败: {str(e)}'
        }, status=500)

async def api_stop_client_listener(request):
    """停止客户端监听器"""
    try:
        import subprocess
        import psutil
        
        # 查找并终止WssBarrageServer.exe进程
        terminated_count = 0
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if proc.info['name'] == 'WssBarrageServer.exe':
                    proc.terminate()
                    terminated_count += 1
                    logging.info(f"已终止客户端监听器进程，PID: {proc.info['pid']}")
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        
        if terminated_count > 0:
            return web.json_response({
                'success': True,
                'message': f'客户端监听器已停止，终止了 {terminated_count} 个进程'
            })
        else:
            return web.json_response({
                'success': True,
                'message': '没有找到运行中的客户端监听器进程'
            })
            
    except Exception as e:
        logging.error(f"停止客户端监听器失败: {e}")
        return web.json_response({
            'success': False,
            'message': f'停止客户端监听器失败: {str(e)}'
        }, status=500)

# 重启管理器API处理函数
async def api_get_restart_status(request):
    """获取重启管理器状态"""
    try:
        restart_api = get_restart_api()
        if restart_api is None:
            return web.json_response({
                'error': '重启管理器未初始化'
            }, status=503)
        
        status = await restart_api.get_status()
        return web.json_response(status)
    except Exception as e:
        logging.error(f"获取重启管理器状态失败: {e}")
        return web.json_response({
            'error': f'获取状态失败: {str(e)}'
        }, status=500)

async def api_trigger_restart(request):
    """手动触发重启"""
    try:
        restart_api = get_restart_api()
        if restart_api is None:
            return web.json_response({
                'error': '重启管理器未初始化'
            }, status=503)
        
        result = await restart_api.trigger_restart()
        return web.json_response({
            'message': result.get('message', '手动重启已触发')
        })
    except Exception as e:
        logging.error(f"手动触发重启失败: {e}")
        return web.json_response({
            'error': f'触发重启失败: {str(e)}'
        }, status=500)

async def api_pause_restart(request):
    """暂停自动重启"""
    try:
        restart_api = get_restart_api()
        if restart_api is None:
            return web.json_response({
                'error': '重启管理器未初始化'
            }, status=503)
        
        result = restart_api.pause_restart()
        return web.json_response({
            'message': result.get('message', '自动重启已暂停')
        })
    except Exception as e:
        logging.error(f"暂停重启失败: {e}")
        return web.json_response({
            'error': f'暂停重启失败: {str(e)}'
        }, status=500)

async def api_resume_restart(request):
    """恢复自动重启"""
    try:
        restart_api = get_restart_api()
        if restart_api is None:
            return web.json_response({
                'error': '重启管理器未初始化'
            }, status=503)
        
        result = restart_api.resume_restart()
        return web.json_response({
            'message': result.get('message', '自动重启已恢复')
        })
    except Exception as e:
        logging.error(f"恢复重启失败: {e}")
        return web.json_response({
            'error': f'恢复重启失败: {str(e)}'
        }, status=500)

async def api_get_restart_config(request):
    """获取重启管理器配置"""
    try:
        restart_api = get_restart_api()
        if restart_api is None:
            return web.json_response({
                'error': '重启管理器未初始化'
            }, status=503)
        
        config = restart_api.get_config()
        return web.json_response(config)
    except Exception as e:
        logging.error(f"获取重启管理器配置失败: {e}")
        return web.json_response({
            'error': f'获取配置失败: {str(e)}'
        }, status=500)

async def api_update_restart_config(request):
    """更新重启管理器配置"""
    try:
        restart_api = get_restart_api()
        if restart_api is None:
            return web.json_response({
                'error': '重启管理器未初始化'
            }, status=503)
        
        data = await request.json()
        # 解包data字典为关键字参数
        result = restart_api.update_config(**data)
        return web.json_response(result)
    except Exception as e:
        logging.error(f"更新重启管理器配置失败: {e}")
        return web.json_response({
            'error': f'更新配置失败: {str(e)}'
        }, status=500)

async def api_get_restart_performance(request):
    """获取重启管理器性能报告"""
    try:
        restart_api = get_restart_api()
        if restart_api is None:
            return web.json_response({
                'success': False,
                'message': '重启管理器未初始化'
            }, status=503)
        
        performance = restart_api.get_performance_report()
        return web.json_response({
            'success': True,
            'data': performance
        })
    except Exception as e:
        logging.error(f"获取重启管理器性能报告失败: {e}")
        return web.json_response({
            'success': False,
            'message': f'获取性能报告失败: {str(e)}'
        }, status=500)

async def api_get_restart_history(request):
    """获取重启历史记录"""
    try:
        restart_api = get_restart_api()
        if restart_api is None:
            return web.json_response({
                'success': False,
                'message': '重启管理器未初始化'
            }, status=503)
        
        history = restart_api.get_restart_history()
        return web.json_response({
            'success': True,
            'data': history
        })
    except Exception as e:
        logging.error(f"获取重启历史记录失败: {e}")
        return web.json_response({
            'success': False,
            'message': f'获取重启历史失败: {str(e)}'
        }, status=500)

async def main():
    """
    Main function to start the web server and WebSocket server.
    """
    global browser_manager, live_companion_client, douyin_parser
    
    load_blocked_keywords()
    
    # 设置监控管理器的广播回调
    async def status_broadcast(message):
        await broadcast(json.dumps(message))
    
    monitor_manager.set_broadcast_callback(status_broadcast)
    
    # 初始化浏览器管理器
    browser_manager = BrowserManager(url_manager, monitor_manager, CONFIG)
    # 统一初始浏览器模式为全局配置的 headless_mode
    try:
        browser_config = CONFIG.get('browser', {})
        def _to_bool(v, default=False):
            if isinstance(v, bool):
                return v
            if v is None:
                return default
            if isinstance(v, str):
                s = v.strip().lower()
                if s in ("true", "1", "yes", "y", "on"):
                    return True
                if s in ("false", "0", "no", "n", "off"):
                    return False
                return default
            if isinstance(v, (int, float)):
                try:
                    return bool(int(v))
                except Exception:
                    return default
            return default
        initial_headless = _to_bool(browser_config.get('headless_mode', browser_config.get('headless', False)), False)
        await browser_manager.initialize(headless=initial_headless)
    except Exception:
        # 如果读取或转换失败，回退到有头模式，确保可见性
        await browser_manager.initialize(headless=False)
    
    # 初始化直播伴侣客户端和解析器
    live_companion_config = CONFIG.get('live_companion', {})
    if live_companion_config.get('enabled', False):
        # douyin_parser已经在第52行初始化，无需重复初始化
        
        # 解析URI获取host和port
        uri = live_companion_config.get('uri', 'ws://127.0.0.1:8878')
        if uri.startswith('ws://'):
            uri = uri[5:]  # 移除ws://前缀
        host, port = uri.split(':') if ':' in uri else (uri, 8878)
        port = int(port)
        
        live_companion_client = LiveCompanionClient(host=host, port=port)
        live_companion_client.set_message_handler(handle_live_companion_message)
        
        # 设置重连参数
        live_companion_client.reconnect_interval = live_companion_config.get('reconnect_interval', 5)
        live_companion_client.max_reconnect_attempts = live_companion_config.get('max_reconnect_attempts', 10)
        
        # 启动直播伴侣客户端连接
        asyncio.create_task(live_companion_client.start())
        print(f"Live companion client enabled: ws://{host}:{port}")
    else:
        print("Live companion client disabled in config")
    
    # 初始化WebSocket客户端
    global websocket_client
    if WEBSOCKET_CLIENT_CONFIG.get('enabled', False):
        websocket_client = AIVtuberWebSocketClient(WEBSOCKET_CLIENT_CONFIG)
        # 启动WebSocket客户端连接
        asyncio.create_task(websocket_client.start())
        print(f"WebSocket client enabled: ws://{WEBSOCKET_CLIENT_CONFIG['host']}:{WEBSOCKET_CLIENT_CONFIG['port']}{WEBSOCKET_CLIENT_CONFIG['path']}")
    else:
        websocket_client = None
        print("WebSocket client disabled in config")
    
    app = web.Application()
    
    # 配置CORS
    cors = cors_setup(app, defaults={
        "*": ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*",
            allow_methods="*"
        )
    })
    
    app.router.add_get('/', monitor)
    app.router.add_get('/index', index)
    app.router.add_get('/monitor', monitor)
    app.router.add_get('/ws', websocket_handler)
    app.router.add_get('/danmaku', websocket_handler)  # 添加对/danmaku路径的支持，使弹幕能够正确转发给AI-VTUBER
    app.router.add_static('/static', os.path.join(os.path.dirname(__file__), 'static'))
    
    # API转发相关接口
    app.router.add_get('/api/forwarding/stats', api_get_forwarding_stats)
    app.router.add_get('/api/forwarding/config', api_get_forwarding_config)
    app.router.add_post('/api/forwarding/config', api_update_forwarding_config)
    app.router.add_post('/api/forwarding/test', api_test_forwarding)

    # 新增的配置管理API路由
    cors.add(app.router.add_get('/api/config', api_get_config))
    cors.add(app.router.add_post('/api/config', api_update_config))
    
    # URL管理API路由
    cors.add(app.router.add_get('/api/urls', api_get_urls))
    cors.add(app.router.add_post('/api/urls', api_add_url))
    cors.add(app.router.add_get('/api/urls/{url_id}', api_get_url))
    cors.add(app.router.add_put('/api/urls/{url_id}', api_update_url))
    cors.add(app.router.add_delete('/api/urls/{url_id}', api_delete_url))
    
    # 监控状态API路由
    cors.add(app.router.add_get('/api/monitor/status', api_get_monitor_status))
    cors.add(app.router.add_get('/api/monitor/status/{url_id}', api_get_session_status))
    cors.add(app.router.add_post('/api/monitor/start', api_start_monitor))
    cors.add(app.router.add_post('/api/monitor/stop', api_stop_monitor))
    cors.add(app.router.add_post('/api/monitor/restart', api_restart_monitor))
    
    # 脚本配置管理API路由
    cors.add(app.router.add_get('/api/scripts', api_get_scripts))
    cors.add(app.router.add_post('/api/scripts/set-current', api_set_current_script))
    cors.add(app.router.add_post('/api/scripts/add', api_add_script))
    cors.add(app.router.add_post('/api/scripts/remove', api_remove_script))
    cors.add(app.router.add_post('/api/scripts/scan', api_scan_scripts))
    
    # 客户端监听器API路由
    cors.add(app.router.add_post('/api/client-listener/start', api_start_client_listener))
    cors.add(app.router.add_post('/api/client-listener/stop', api_stop_client_listener))
    
    # WebSocket连接池管理API路由
    cors.add(app.router.add_get('/api/websocket/stats', api_get_websocket_stats))
    cors.add(app.router.add_post('/api/websocket/cleanup', api_cleanup_websocket_connections))
    
    # 重启管理器API路由
    cors.add(app.router.add_get('/api/restart/status', api_get_restart_status))
    cors.add(app.router.add_post('/api/restart/trigger', api_trigger_restart))
    cors.add(app.router.add_post('/api/restart/pause', api_pause_restart))
    cors.add(app.router.add_post('/api/restart/resume', api_resume_restart))
    cors.add(app.router.add_get('/api/restart/config', api_get_restart_config))
    cors.add(app.router.add_post('/api/restart/config', api_update_restart_config))
    cors.add(app.router.add_get('/api/restart/performance', api_get_restart_performance))
    cors.add(app.router.add_get('/api/restart/history', api_get_restart_history))
    

    
    # Configure server with better connection handling
    runner = web.AppRunner(app, 
                          keepalive_timeout=30,
                          client_timeout=60)
    await runner.setup()
    
    # 从配置文件获取服务器配置
    server_config = CONFIG.get('server', {'host': 'localhost', 'port': 8765})
    host = server_config.get('host', 'localhost')
    port = server_config.get('port', 8765)
    
    # Use SO_REUSEADDR to handle TIME_WAIT connections better
    site = web.TCPSite(runner, host, port, 
                      reuse_address=True)
    await site.start()
    
    print(f"Server started at http://{host}:{port}")
    print(f"WebSocket endpoint: ws://{host}:{port}/ws")
    print("Press Ctrl+C to stop the server")

    # 自动打开WEBUI前端页面
    import webbrowser
    import platform
    if platform.system() == "Windows":
        webbrowser.open(f"http://{host}:{port}")

    # Keep the server running
    try:
        await asyncio.Future()  # run forever
    except asyncio.CancelledError:
        print("Server shutdown requested")
        # 清理资源
        if browser_manager:
            await browser_manager.cleanup()
        await runner.cleanup()

def handle_exception(loop, context):
    """Enhanced exception handler to suppress common Windows connection errors"""
    exception = context.get('exception')
    message = context.get('message', '')
    
    # Suppress common Windows connection errors that don't affect functionality
    if isinstance(exception, (ConnectionResetError, ConnectionAbortedError, OSError)):
        # Check if it's a transport-level error
        if ('_call_connection_lost' in message or 
            'WinError 10054' in str(exception) or
            'WinError 10053' in str(exception)):
            return
    
    # Suppress SSL/TLS related errors that are common in development
    if isinstance(exception, Exception):
        error_str = str(exception).lower()
        if any(keyword in error_str for keyword in [
            'ssl', 'certificate', 'handshake', 'protocol error'
        ]):
            return
    
    # For other exceptions, use default handling
    loop.default_exception_handler(context)

if __name__ == "__main__":
    import platform
    
    # 配置日志
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    load_config()
    load_blocked_keywords()
    load_message_format_config()
    
    # Suppress common Windows connection warnings and errors
    warnings.filterwarnings("ignore", category=ResourceWarning)
    warnings.filterwarnings("ignore", message=".*WinError 10054.*")
    warnings.filterwarnings("ignore", message=".*ConnectionResetError.*")
    
    # Set asyncio logger to WARNING level to reduce noise
    asyncio_logger = logging.getLogger('asyncio')
    asyncio_logger.setLevel(logging.WARNING)
    
    if sys.platform == 'win32':
        # Set Windows-specific event loop policy to reduce ConnectionResetError noise
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        
        # Set custom exception handler to suppress ConnectionResetError
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.set_exception_handler(handle_exception)
        
        try:
            loop.run_until_complete(main())
        except KeyboardInterrupt:
            print("Server stopped.")
            # 清理优化的WebSocket管理器
            if optimized_ws_manager:
                loop.run_until_complete(optimized_ws_manager.cleanup_all())
            # 清理浏览器管理器资源
            if browser_manager:
                loop.run_until_complete(browser_manager.cleanup())
            # 清理直播伴侣客户端连接
            if live_companion_client:
                loop.run_until_complete(live_companion_client.disconnect())
            # 清理WebSocket客户端连接
            if websocket_client:
                loop.run_until_complete(websocket_client.stop())
        finally:
            loop.close()
    else:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            print("Server stopped.")
            # 清理优化的WebSocket管理器
            if optimized_ws_manager:
                asyncio.run(optimized_ws_manager.cleanup_all())
            # 清理浏览器管理器资源
            if browser_manager:
                asyncio.run(browser_manager.cleanup())
            # 清理直播伴侣客户端连接
            if live_companion_client:
                asyncio.run(live_companion_client.disconnect())
            # 清理WebSocket客户端连接
            if websocket_client:
                asyncio.run(websocket_client.stop())