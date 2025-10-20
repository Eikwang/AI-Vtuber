import websocket
import json
import aiohttp
import random
import traceback
import string
import requests
from typing import Optional

from utils.my_log import logger
import utils.my_global as my_global
from utils.config import Config

# 配置文件路径
config_path = "config.json"
config = None

def start_listen(new_config, common, my_handle, platform: str, schedule_thread):
    global config
    config = new_config

    def on_message(ws, message):
        global config
        
        message_json = json.loads(message)
        # logger.debug(message_json)
        if "Type" in message_json:
            type = message_json["Type"]
            data_json = json.loads(message_json["Data"])

            if type == 1:
                # 闲时计数清零
                my_global.idle_time_auto_clear(config, "comment")

                username = data_json["User"]["Nickname"]
                content = data_json["Content"]

                logger.info(f"[📧直播间弹幕消息] [{username}]：{content}")

                data = {
                    "platform": platform,
                    "username": username,
                    "content": content,
                }

                my_handle.process_data(data, "comment")

                pass

            elif type == 2:
                username = data_json["User"]["Nickname"]
                count = data_json["Count"]

                logger.info(f"[👍直播间点赞消息] {username} 点了{count}赞")

            elif type == 3:
                my_global.idle_time_auto_clear(config, "entrance")

                username = data_json["User"]["Nickname"]

                logger.info(f"[🚹🚺直播间成员加入消息] 欢迎 {username} 进入直播间")

                data = {
                    "platform": platform,
                    "username": username,
                    "content": "进入直播间",
                }

                # 添加用户名到最新的用户名列表（移至entrance_handle中统一处理）
                # my_global.add_username_to_last_username_list(username)

                my_handle.process_data(data, "entrance")

            elif type == 4:
                my_global.idle_time_auto_clear(config, "follow")

                username = data_json["User"]["Nickname"]

                logger.info(
                    f'[➕直播间关注消息] 感谢 {data_json["User"]["Nickname"]} 的关注'
                )

                data = {"platform": platform, "username": username}

                my_handle.process_data(data, "follow")

                pass

            elif type == 5:
                my_global.idle_time_auto_clear(config, "gift")

                gift_name = data_json["GiftName"]
                username = data_json["User"]["Nickname"]
                # 礼物数量
                num = data_json["GiftCount"]
                # 礼物重复数量
                repeat_count = data_json["RepeatCount"]

                try:
                    # 暂时是写死的
                    data_path = "data/抖音礼物价格表.json"

                    # 读取JSON文件
                    with open(data_path, "r", encoding="utf-8") as file:
                        # 解析JSON数据
                        data_json = json.load(file)

                    if gift_name in data_json:
                        # 单个礼物金额 需要自己维护礼物价值表
                        discount_price = data_json[gift_name]
                    else:
                        logger.warning(
                            f"数据文件：{data_path} 中，没有 {gift_name} 对应的价值，请手动补充数据"
                        )
                        discount_price = 1
                except Exception as e:
                    logger.error(traceback.format_exc())
                    discount_price = 1

                # 总金额
                combo_total_coin = repeat_count * discount_price

                logger.info(
                    f"[🎁直播间礼物消息] 用户：{username} 赠送 {num} 个 {gift_name}，单价 {discount_price}抖币，总计 {combo_total_coin}抖币"
                )

                data = {
                    "platform": platform,
                    "gift_name": gift_name,
                    "username": username,
                    "num": num,
                    "unit_price": discount_price / 10,
                    "total_price": combo_total_coin / 10,
                }

                my_handle.process_data(data, "gift")

            elif type == 6:
                logger.info(f'[直播间数据] {data_json["Content"]}')
                # {'OnlineUserCount': 50, 'TotalUserCount': 22003, 'TotalUserCountStr': '2.2万', 'OnlineUserCountStr': '50',
                # 'MsgId': 7260517442466662207, 'User': None, 'Content': '当前直播间人数 50，累计直播间人数 2.2万', 'RoomId': 7260415920948906807}
                # logger.info(f"data_json={data_json}")

                my_global.last_liveroom_data = data_json

                # 当前在线人数
                OnlineUserCount = data_json["OnlineUserCount"]

                try:
                    # 是否开启了动态配置功能
                    if config.get("trends_config", "enable"):
                        for path_config in config.get("trends_config", "path"):
                            online_num_min = int(
                                path_config["online_num"].split("-")[0]
                            )
                            online_num_max = int(
                                path_config["online_num"].split("-")[1]
                            )

                            # 判断在线人数是否在此范围内
                            if (
                                OnlineUserCount >= online_num_min
                                and OnlineUserCount <= online_num_max
                            ):
                                logger.debug(f"当前配置文件：{path_config['path']}")
                                # 如果配置文件相同，则跳过
                                if config_path == path_config["path"]:
                                    break

                                config_path = path_config["path"]
                                config = Config(config_path)

                                my_handle.reload_config(config_path)

                                logger.info(f"切换配置文件：{config_path}")

                                break
                except Exception as e:
                    logger.error(traceback.format_exc())

                pass

            elif type == 8:
                logger.info(
                    f'[分享直播间] 感谢 {data_json["User"]["Nickname"]} 分享了直播间'
                )

                pass

    def on_error(ws, error):
        logger.error(f"Error:{error}")

    def on_close(ws, close_status_code, close_msg):
        logger.debug("WebSocket connection closed")

    def on_open(ws):
        logger.debug("WebSocket connection established")

    try:
        # WebSocket连接URL
        ws_url = "ws://127.0.0.1:8888"

        logger.info(f"监听地址：{ws_url}")

        # 不设置日志等级
        websocket.enableTrace(False)
        # 创建WebSocket连接
        ws = websocket.WebSocketApp(
            ws_url,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open,
        )

        # 运行WebSocket连接
        ws.run_forever()
    except KeyboardInterrupt:
        logger.warning("程序被强行退出")
    finally:
        logger.warning(
            "关闭ws连接...请确认您是否启动了抖音弹幕监听程序，ws服务正常运行！\n监听程序启动成功后，请重新运行程序进行对接使用！"
        )
        # os._exit(0)

    # 等待子线程结束
    schedule_thread.join()