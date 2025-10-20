"""
tiktok
"""
import asyncio
import traceback
import json

from TikTokLive import TikTokLiveClient
from TikTokLive.events import (
    CommentEvent,
    ConnectEvent,
    DisconnectEvent,
    JoinEvent,
    GiftEvent,
    FollowEvent,
)
# from TikTokLive.client.errors import LiveNotFound

from utils.my_log import logger
import utils.my_global as my_global

def start_listen(config, common, my_handle, platform: str):
    # 比如直播间是 https://www.tiktok.com/@username/live 那么room_id就是 username，其实就是用户唯一ID
    room_id = my_handle.get_room_id()

    proxys = {
        "http://": "http://127.0.0.1:10809",
        "https://": "http://127.0.0.1:10809",
    }

    proxys = None

    # 代理软件开启TUN模式进行代理，由于库的ws不走传入的代理参数，只能靠代理软件全代理了
    client: TikTokLiveClient = TikTokLiveClient(
        unique_id=f"@{room_id}", web_proxy=proxys, ws_proxy=proxys
    )

    def start_client():
        # Define how you want to handle specific events via decorator
        @client.on("connect")
        async def on_connect(_: ConnectEvent):
            logger.info(f"连接到 房间ID:{client.room_id}")

        @client.on("disconnect")
        async def on_disconnect(event: DisconnectEvent):
            logger.info("断开连接，10秒后重连")
            await asyncio.sleep(10)  # 等待一段时间后尝试重连，这里等待10秒
            start_client()  # 尝试重新连接

        @client.on("join")
        async def on_join(event: JoinEvent):
            my_global.idle_time_auto_clear(config, "entrance")

            username = event.user.nickname
            unique_id = event.user.unique_id

            logger.info(f"[🚹🚺直播间成员加入消息] 欢迎 {username} 进入直播间")

            data = {
                "platform": platform,
                "username": username,
                "content": "进入直播间",
            }

            # 添加用户名到最新的用户名列表（移至entrance_handle中统一处理）
            # my_global.add_username_to_last_username_list(username)

            my_handle.process_data(data, "entrance")

        # Notice no decorator?
        @client.on("comment")
        async def on_comment(event: CommentEvent):
            # 闲时计数清零
            my_global.idle_time_auto_clear(config, "comment")

            username = event.user.nickname
            content = event.comment

            logger.info(f"[📧直播间弹幕消息] [{username}]：{content}")

            data = {"platform": platform, "username": username, "content": content}

            my_handle.process_data(data, "comment")

        @client.on("gift")
        async def on_gift(event: GiftEvent):
            """
            This is an example for the "gift" event to show you how to read gift data properly.

            Important Note:

            Gifts of type 1 can have streaks, so we need to check that the streak has ended
            If the gift type isn't 1, it can't repeat. Therefore, we can go straight to logger.infoing

            """
            my_global.idle_time_auto_clear(config, "gift")

            # Streakable gift & streak is over
            if event.gift.streakable and not event.gift.streaking:
                # 礼物重复数量
                repeat_count = event.gift.count

            # Non-streakable gift
            elif not event.gift.streakable:
                # 礼物重复数量
                repeat_count = 1

            gift_name = event.gift.info.name
            username = event.user.nickname
            # 礼物数量
            num = 1

            try:
                # 暂时是写死的
                data_path = "data/tiktok礼物价格表.json"

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

        @client.on("follow")
        async def on_follow(event: FollowEvent):
            my_global.idle_time_auto_clear(config, "follow")

            username = event.user.nickname

            logger.info(f"[➕直播间关注消息] 感谢 {username} 的关注")

            data = {"platform": platform, "username": username}

            my_handle.process_data(data, "follow")

        try:
            client.stop()
            logger.info(f"连接{room_id}中...")
            client.run()

        except Exception as e:
            logger.info(f"用户ID: @{client.unique_id} 好像不在线捏, 1分钟后重试...")
            start_client()

    # 运行客户端
    start_client()