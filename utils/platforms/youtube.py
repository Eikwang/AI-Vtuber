import pytchat
import time
import re
import traceback
import os

from utils.my_log import logger
import utils.my_global as my_global

def start_listen(config, common, my_handle, platform: str):
    def get_video_id():
        try:
            return config.get("room_display_id")
        except Exception as e:
            logger.error("获取直播间号失败！\n{0}".format(e))
            return None

    def process_chat(live):
        while live.is_alive():
            try:
                for c in live.get().sync_items():
                    # 过滤表情包
                    chat_raw = re.sub(r":[^\s]+:", "", c.message)
                    chat_raw = chat_raw.replace("#", "")
                    if chat_raw != "":
                        # 闲时计数清零
                        my_global.idle_time_auto_clear(config, "comment")

                        content = chat_raw  # 获取弹幕内容
                        username = c.author.name  # 获取发送弹幕的用户昵称

                        logger.info(f"[{username}]: {content}")

                        data = {
                            "platform": platform,
                            "username": username,
                            "content": content,
                        }

                        my_handle.process_data(data, "comment")

                    # time.sleep(1)
            except Exception as e:
                logger.error(traceback.format_exc())
                logger.error("Error receiving chat: {0}".format(e))
                my_handle.abnormal_alarm_handle("platform")
                break  # 退出内部while循环以触发重连机制

    try:
        reconnect_attempts = 0
        last_reconnect_time = None

        while True:
            video_id = get_video_id()
            if video_id is None:
                break

            live = pytchat.create(video_id=video_id)
            process_chat(live)

            current_time = time.time()
            # 如果重连间隔只有30s内，那就只有3次，如果间隔大于30s，那就无限重连
            if last_reconnect_time and (current_time - last_reconnect_time < 30):
                reconnect_attempts += 1
                if reconnect_attempts >= 3:
                    logger.error("重连失败次数已达上限，退出程序...")
                    break
                logger.warning(
                    f"连接已关闭，间隔小于30秒，尝试重新连接 ({reconnect_attempts}/3)..."
                )
            else:
                reconnect_attempts = 0  # 重置重连次数
                logger.warning("连接已关闭，尝试重新连接...")

            last_reconnect_time = current_time

    except KeyboardInterrupt:
        logger.warning("程序被强行退出")

    finally:
        logger.warning("关闭连接...")
        os._exit(0)