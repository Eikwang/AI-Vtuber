import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime

class DouyinBarrageParser:
    """
    DouyinBarrageGrab消息格式解析器
    将直播伴侣的WS消息转换为DanmakuListener标准格式
    """
    
    # 消息类型映射：直播伴侣Type -> DanmakuListener type
    MESSAGE_TYPE_MAPPING = {
        1: "danmaku",      # 弹幕消息
        2: "like",        # 点赞消息
        3: "entrance",    # 进直播间消息
        4: "follow",      # 关注消息
        5: "gift",        # 礼物消息
        6: "stats",       # 直播间统计消息
        7: "fan_club",    # 粉丝团消息
        8: "share",       # 直播间分享消息
        9: "live_end"     # 下播消息
    }
    
    def __init__(self):
        self.logger = logging.getLogger("DouyinBarrageParser")
        
    def parse_message(self, raw_message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        解析直播伴侣消息为DanmakuListener标准格式
        
        Args:
            raw_message: 直播伴侣原始消息
            
        Returns:
            解析后的标准格式消息，解析失败返回None
        """
        try:
            message_type = raw_message.get("Type")
            process_name = raw_message.get("ProcessName", "")
            data_str = raw_message.get("Data", "{}")
            
            if message_type is None:
                self.logger.warning("消息缺少Type字段")
                return None
            
            # 解析Data字段
            try:
                data = json.loads(data_str) if isinstance(data_str, str) else data_str
            except json.JSONDecodeError as e:
                self.logger.error(f"Data字段JSON解析失败: {e}")
                return None
            
            # 获取标准消息类型
            standard_type = self.MESSAGE_TYPE_MAPPING.get(message_type)
            if not standard_type:
                self.logger.warning(f"未知的消息类型: {message_type}")
                return None
            
            # 根据消息类型进行具体解析
            if message_type == 1:  # 弹幕消息
                return self._parse_danmaku_message(data, raw_message)
            elif message_type == 2:  # 点赞消息
                return self._parse_like_message(data, raw_message)
            elif message_type == 3:  # 进直播间消息
                return self._parse_entrance_message(data, raw_message)
            elif message_type == 4:  # 关注消息
                return self._parse_follow_message(data, raw_message)
            elif message_type == 5:  # 礼物消息
                return self._parse_gift_message(data, raw_message)
            elif message_type == 6:  # 统计消息
                return self._parse_stats_message(data, raw_message)
            elif message_type == 7:  # 粉丝团消息
                return self._parse_fan_club_message(data, raw_message)
            elif message_type == 8:  # 分享消息
                return self._parse_share_message(data, raw_message)
            elif message_type == 9:  # 下播消息
                return self._parse_live_end_message(data, raw_message)
            else:
                return self._parse_generic_message(data, raw_message, standard_type)
                
        except Exception as e:
            self.logger.error(f"消息解析异常: {e}")
            return None
    
    def _extract_user_info(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """提取用户信息"""
        user_data = data.get("User", {})
        return {
            "user_id": str(user_data.get("Id", "")),
            "username": user_data.get("Nickname", ""),
            "display_id": user_data.get("DisplayId", ""),
            "level": user_data.get("Level", 0),
            "pay_level": user_data.get("PayLevel", 0),
            "gender": user_data.get("Gender", 0),
            "avatar": user_data.get("HeadImgUrl", ""),
            "sec_uid": user_data.get("SecUid", ""),
            "is_admin": user_data.get("IsAdmin", False),
            "is_anchor": user_data.get("IsAnchor", False),
            "follower_count": user_data.get("FollowerCount", 0),
            "following_count": user_data.get("FollowingCount", 0),
            "follow_status": user_data.get("FollowStatus", 0)
        }
    
    def _extract_room_info(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """提取直播间信息"""
        return {
            "room_id": data.get("RoomId", ""),
            "web_room_id": data.get("WebRoomId", ""),
            "room_title": data.get("RoomTitle", ""),
            "app_id": data.get("Appid", "")
        }
    
    def _parse_danmaku_message(self, data: Dict[str, Any], raw_message: Dict[str, Any]) -> Dict[str, Any]:
        """解析弹幕消息"""
        user_info = self._extract_user_info(data)
        room_info = self._extract_room_info(data)
        
        return {
            "type": "danmaku",
            "platform": "douyin_live_companion",
            "username": user_info["username"],
            "content": data.get("Content", ""),
            "timestamp": datetime.now().timestamp(),
            "user_id": user_info["user_id"],
            "avatar": user_info["avatar"],
            "user_level": user_info["level"],
            "is_admin": user_info["is_admin"],
            "is_vip": user_info["pay_level"] > 0,
            "room_id": room_info["room_id"],
            "room_title": room_info["room_title"],
            "raw_data": raw_message
        }
    
    def _parse_like_message(self, data: Dict[str, Any], raw_message: Dict[str, Any]) -> Dict[str, Any]:
        """解析点赞消息"""
        user_info = self._extract_user_info(data)
        room_info = self._extract_room_info(data)
        
        return {
            "type": "like",
            "platform": "douyin_live_companion",
            "username": user_info["username"],
            "content": data.get("Content", "点赞"),
            "timestamp": datetime.now().timestamp(),
            "user_id": user_info["user_id"],
            "avatar": user_info["avatar"],
            "like_count": data.get("Count", 1),
            "total_likes": data.get("Total", 0),
            "room_id": room_info["room_id"],
            "room_title": room_info["room_title"],
            "raw_data": raw_message
        }
    
    def _parse_entrance_message(self, data: Dict[str, Any], raw_message: Dict[str, Any]) -> Dict[str, Any]:
        """解析进入直播间消息"""
        user_info = self._extract_user_info(data)
        room_info = self._extract_room_info(data)
        
        return {
            "type": "entrance",
            "platform": "douyin_live_companion",
            "username": user_info["username"],
            "content": data.get("Content", "来了"),
            "timestamp": datetime.now().timestamp(),
            "user_id": user_info["user_id"],
            "avatar": user_info["avatar"],
            "current_count": data.get("CurrentCount", 0),
            "enter_tip_type": data.get("EnterTipType", 0),
            "room_id": room_info["room_id"],
            "room_title": room_info["room_title"],
            "raw_data": raw_message
        }
    
    def _parse_follow_message(self, data: Dict[str, Any], raw_message: Dict[str, Any]) -> Dict[str, Any]:
        """解析关注消息"""
        user_info = self._extract_user_info(data)
        room_info = self._extract_room_info(data)
        
        return {
            "type": "follow",
            "platform": "douyin_live_companion",
            "username": user_info["username"],
            "content": data.get("Content", "关注了主播"),
            "timestamp": datetime.now().timestamp(),
            "user_id": user_info["user_id"],
            "avatar": user_info["avatar"],
            "room_id": room_info["room_id"],
            "room_title": room_info["room_title"],
            "raw_data": raw_message
        }
    
    def _parse_gift_message(self, data: Dict[str, Any], raw_message: Dict[str, Any]) -> Dict[str, Any]:
        """解析礼物消息"""
        user_info = self._extract_user_info(data)
        room_info = self._extract_room_info(data)
        
        return {
            "type": "gift",
            "platform": "douyin_live_companion",
            "username": user_info["username"],
            "content": data.get("Content", "送出礼物"),
            "timestamp": datetime.now().timestamp(),
            "user_id": user_info["user_id"],
            "avatar": user_info["avatar"],
            "gift_id": data.get("GiftId", 0),
            "gift_name": data.get("GiftName", ""),
            "gift_count": data.get("GiftCount", 1),
            "repeat_count": data.get("RepeatCount", 1),
            "diamond_count": data.get("DiamondCount", 0),
            "gift_price": data.get("DiamondCount", 0),  # 使用钻石数作为价格
            "combo": data.get("Combo", False),
            "gift_img_url": data.get("ImgUrl", ""),
            "room_id": room_info["room_id"],
            "room_title": room_info["room_title"],
            "raw_data": raw_message
        }
    
    def _parse_stats_message(self, data: Dict[str, Any], raw_message: Dict[str, Any]) -> Dict[str, Any]:
        """解析统计消息"""
        room_info = self._extract_room_info(data)
        
        return {
            "type": "stats",
            "platform": "douyin_live_companion",
            "content": "直播间统计更新",
            "timestamp": datetime.now().timestamp(),
            "online_user_count": data.get("OnlineUserCount", 0),
            "total_user_count": data.get("TotalUserCount", 0),
            "online_user_count_str": data.get("OnlineUserCountStr", "0"),
            "total_user_count_str": data.get("TotalUserCountStr", "0"),
            "room_id": room_info["room_id"],
            "room_title": room_info["room_title"],
            "raw_data": raw_message
        }
    
    def _parse_fan_club_message(self, data: Dict[str, Any], raw_message: Dict[str, Any]) -> Dict[str, Any]:
        """解析粉丝团消息"""
        user_info = self._extract_user_info(data)
        room_info = self._extract_room_info(data)
        
        return {
            "type": "fan_club",
            "platform": "douyin_live_companion",
            "username": user_info["username"],
            "content": data.get("Content", "粉丝团相关"),
            "timestamp": datetime.now().timestamp(),
            "user_id": user_info["user_id"],
            "avatar": user_info["avatar"],
            "fan_club_type": data.get("Type", 0),
            "fan_club_level": data.get("Level", 0),
            "room_id": room_info["room_id"],
            "room_title": room_info["room_title"],
            "raw_data": raw_message
        }
    
    def _parse_share_message(self, data: Dict[str, Any], raw_message: Dict[str, Any]) -> Dict[str, Any]:
        """解析分享消息"""
        user_info = self._extract_user_info(data)
        room_info = self._extract_room_info(data)
        
        return {
            "type": "share",
            "platform": "douyin_live_companion",
            "username": user_info["username"],
            "content": data.get("Content", "分享了直播间"),
            "timestamp": datetime.now().timestamp(),
            "user_id": user_info["user_id"],
            "avatar": user_info["avatar"],
            "share_type": data.get("ShareType", 0),
            "room_id": room_info["room_id"],
            "room_title": room_info["room_title"],
            "raw_data": raw_message
        }
    
    def _parse_live_end_message(self, data: Dict[str, Any], raw_message: Dict[str, Any]) -> Dict[str, Any]:
        """解析下播消息"""
        room_info = self._extract_room_info(data)
        
        return {
            "type": "live_end",
            "platform": "douyin_live_companion",
            "content": data.get("Content", "直播已结束"),
            "timestamp": datetime.now().timestamp(),
            "room_id": room_info["room_id"],
            "room_title": room_info["room_title"],
            "raw_data": raw_message
        }
    
    def _parse_generic_message(self, data: Dict[str, Any], raw_message: Dict[str, Any], msg_type: str) -> Dict[str, Any]:
        """解析通用消息格式"""
        user_info = self._extract_user_info(data)
        room_info = self._extract_room_info(data)
        
        return {
            "type": msg_type,
            "platform": "douyin_live_companion",
            "username": user_info.get("username", ""),
            "content": data.get("Content", ""),
            "timestamp": datetime.now().timestamp(),
            "user_id": user_info.get("user_id", ""),
            "avatar": user_info.get("avatar", ""),
            "room_id": room_info["room_id"],
            "room_title": room_info["room_title"],
            "raw_data": raw_message
        }