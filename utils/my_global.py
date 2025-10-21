# 空闲时间计数器
global_idle_time = 0
last_username_list = ["家人们"]
last_liveroom_data = None

# 待播放音频数量（在使用 音频播放器 或者 metahuman-stream等不通过AI Vtuber播放音频的对接项目时，使用此变量记录是是否还有音频没有播放完）
wait_play_audio_num = 0
wait_synthesis_msg_num = 0

# 闲时任务计时自动清零
def idle_time_auto_clear(config, type: str):
    """闲时任务计时自动清零

    Args:
        type (str): 消息类型（comment/gift/entrance等）

    Returns:
        bool: 是否清零的结果
    """
    global global_idle_time

    # 触发的类型列表
    type_list = config.get("idle_time_task_config", "trigger_type")
    if type in type_list:
        global_idle_time = 0

        return True

    return False

# 添加用户名到最新的用户名列表
def add_username_to_last_username_list(data):
    """
    data(str): 用户名
    """
    global last_username_list
    
    # 如果列表未初始化或为空，初始化为默认值“家人们”
    if last_username_list is None:
        last_username_list = ["家人们"]

    # 数据为空时使用默认值“家人们”
    username = (data or "").strip() or "家人们"

    # 添加数据到 最新入场的用户名列表
    last_username_list.append(username)

    # 保留最新的1个数据
    last_username_list = last_username_list[-1:]