# 标准消息格式示例

以下为各类 WS 转发消息的完整 JSON 格式示例，字段均参考 BarrageMsgPack 及其相关消息类型定义。

---

## 1. 弹幕消息（Type: 1）
```json
{
  "Type": 1,
  "ProcessName": "DouyinLive",
  "Data": "{\"MsgId\":123456,\"User\":{\"Id\":111,\"Nickname\":\"用户A\",\"IsAdmin\":false,\"IsAnchor\":false,\"ShortId\":222,\"DisplayId\":\"A001\",\"Level\":5,\"PayLevel\":2,\"Gender\":1,\"HeadImgUrl\":\"http://img.com/a.jpg\",\"SecUid\":\"sec123\",\"FansClub\":{\"ClubName\":\"铁粉团\",\"Level\":3},\"FollowerCount\":1000,\"FollowStatus\":1,\"FollowingCount\":50},\"Owner\":{\"UserId\":\"8888\",\"SecUid\":\"sec8888\",\"Nickname\":\"主播A\",\"HeadUrl\":\"http://img.com/anchor.jpg\",\"FollowStatus\":1},\"Content\":\"弹幕内容\",\"RoomId\":\"8888\",\"WebRoomId\":\"web8888\",\"RoomTitle\":\"直播间标题\",\"IsAnonymous\":false,\"Appid\":\"1128\"}"
}
```

## 2. 点赞消息（Type: 2）
```json
{
  "Type": 2,
  "ProcessName": "DouyinLive",
  "Data": "{\"MsgId\":123457,\"User\":{...},\"Content\":\"点赞\",\"RoomId\":\"8888\",\"WebRoomId\":\"web8888\",\"RoomTitle\":\"直播间标题\",\"IsAnonymous\":false,\"Appid\":\"1128\",\"Count\":10,\"Total\":100}"
}
```

## 3. 进直播间消息（Type: 3）
```json
{
  "Type": 3,
  "ProcessName": "DouyinLive",
  "Data": "{\"MsgId\":123458,\"User\":{...},\"Content\":\"来了\",\"RoomId\":\"8888\",\"WebRoomId\":\"web8888\",\"RoomTitle\":\"直播间标题\",\"IsAnonymous\":false,\"Appid\":\"1128\",\"CurrentCount\":200,\"EnterTipType\":0}"
}
```

## 4. 关注消息（Type: 4）
```json
{
  "Type": 4,
  "ProcessName": "DouyinLive",
  "Data": "{\"MsgId\":123459,\"User\":{...},\"Content\":\"关注了主播\",\"RoomId\":\"8888\",\"WebRoomId\":\"web8888\",\"RoomTitle\":\"直播间标题\",\"IsAnonymous\":false,\"Appid\":\"1128\"}"
}
```

## 5. 礼物消息（Type: 5）
```json
{
  "Type": 5,
  "ProcessName": "DouyinLive",
  "Data": "{\"MsgId\":123460,\"User\":{...},\"Content\":\"送出礼物\",\"RoomId\":\"8888\",\"WebRoomId\":\"web8888\",\"RoomTitle\":\"直播间标题\",\"IsAnonymous\":false,\"Appid\":\"1128\",\"GiftId\":1001,\"GiftName\":\"小心心\",\"GroupId\":1,\"GiftCount\":1,\"RepeatCount\":1,\"DiamondCount\":10,\"Combo\":false,\"ImgUrl\":\"http://img.com/gift.jpg\",\"ToUser\":{...}}"
}
```

## 6. 直播间统计消息（Type: 6）
```json
{
  "Type": 6,
  "ProcessName": "DouyinLive",
  "Data": "{\"MsgId\":123461,\"User\":{...},\"Content\":\"统计信息\",\"RoomId\":\"8888\",\"WebRoomId\":\"web8888\",\"RoomTitle\":\"直播间标题\",\"IsAnonymous\":false,\"Appid\":\"1128\",\"OnlineUserCount\":150,\"TotalUserCount\":5000,\"TotalUserCountStr\":\"5000\",\"OnlineUserCountStr\":\"150\"}"
}
```

## 7. 粉丝团消息（Type: 7）
```json
{
  "Type": 7,
  "ProcessName": "DouyinLive",
  "Data": "{\"MsgId\":123462,\"User\":{...},\"Content\":\"加入粉丝团\",\"RoomId\":\"8888\",\"WebRoomId\":\"web8888\",\"RoomTitle\":\"直播间标题\",\"IsAnonymous\":false,\"Appid\":\"1128\",\"Type\":2,\"Level\":3}"
}
```

## 8. 直播间分享消息（Type: 8）
```json
{
  "Type": 8,
  "ProcessName": "DouyinLive",
  "Data": "{\"MsgId\":123463,\"User\":{...},\"Content\":\"分享直播间\",\"RoomId\":\"8888\",\"WebRoomId\":\"web8888\",\"RoomTitle\":\"直播间标题\",\"IsAnonymous\":false,\"Appid\":\"1128\",\"ShareType\":1}"
}
```

## 9. 下播消息（Type: 9）
```json
{
  "Type": 9,
  "ProcessName": "DouyinLive",
  "Data": "{\"MsgId\":123464,\"Content\":\"直播已结束\",\"RoomId\":\"8888\",\"WebRoomId\":\"web8888\",\"RoomTitle\":\"直播间标题\",\"IsAnonymous\":false,\"Appid\":\"1128\"}"
}
```

---

> 说明：
> - User、Owner、ToUser 等对象字段可参考 BarrageMessages.cs 的详细定义。
> - 所有 Data 字段均为 JSON 字符串，实际内容会根据消息类型和业务场景动态生成。
> - 示例中的 "..." 表示可展开的完整字段。
