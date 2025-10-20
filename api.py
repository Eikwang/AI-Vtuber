import requests

# 确保替换为有效的 sessionid
sessionid = 123456  # 应从创建会话的响应中获取
response = requests.post(
    "http://127.0.0.1:8082/is_speaking",
    json={"sessionid": sessionid}  # 使用 json 参数自动设置 Content-Type
)