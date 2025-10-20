import json, os
import aiohttp, requests, ssl, asyncio
from urllib.parse import urlencode
from gradio_client import Client
import traceback
import edge_tts
from urllib.parse import urljoin
import random, copy

from utils.common import Common
from utils.my_log import logger
from utils.config import Config

class MY_TTS:
    def __init__(self, config_path):
        self.common = Common()
        self.config = Config(config_path)

        # 创建一个不执行证书验证的 SSLContext 对象
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE

        # 获取 werkzeug 库的日志记录器
        # werkzeug_logger = logger.getLogger("werkzeug")
        # # 设置 httpx 日志记录器的级别为 WARNING
        # werkzeug_logger.setLevel(logger.WARNING)

        # 请求超时
        self.timeout = 60

        # 使用内部成员做配置
        self.use_class_config = False
        # 备份一下配置
        self.class_config = copy.copy(self.config)

        try:
            self.audio_out_path = self.config.get("play_audio", "out_path")

            if not os.path.isabs(self.audio_out_path):
                if not self.audio_out_path.startswith('./'):
                    self.audio_out_path = './' + self.audio_out_path
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error("请检查播放音频的音频输出路径配置！！！这将影响程序使用！")


    # 获取随机数，单数据就是原数值，有-则判断为范围性数据，随机一个数值，返回float数据
    def get_random_float(self, data):
        # 将非字符串的情况统一处理为长度相同的最小值和最大值
        if isinstance(data, str) and "-" in data:
            min, max = map(float, data.split("-"))
        else:
            min = max = float(data)
        
        # 返回指定范围内的随机浮点数
        return random.uniform(min, max)

    # 音频文件base64编码 传入文件路径
    def encode_audio_to_base64(self, file_path):
        import base64

        if file_path == "" or file_path is None:
            return None

    async def index_tts_api(self, data):
        """Index-tts API对接喵

        Args:
            data (dict): 传参数据喵

        Returns:
            str: 音频路径
        """
        try:
            url = f"{data['index_tts']['api_ip_port']}/tts"
            
            # 创建FormData对象用于multipart/form-data请求
            from aiohttp import FormData
            form_data = FormData()
            
            # 添加文本参数
            form_data.add_field('text', data["content"])
            
            # 添加温度参数
            form_data.add_field('temperature', str(data['index_tts']["temperature"]))
            
            # 添加音频文件
            form_data.add_field(
                'prompt_audio',
                open(data['index_tts']["prompt_audio"], 'rb'),
                filename=os.path.basename(data['index_tts']["prompt_audio"]),
                content_type='audio/wav'
            )
            
            logger.debug(f"Index-tts 请求参数: text={data['content']}, temperature={data['index_tts']['temperature']}")
            
            try:
                return await self.download_audio("index_tts", url, self.timeout, request_type="post", data=form_data)
            except Exception as e:
                logger.error(traceback.format_exc())
                logger.error(f'Index-tts API 错误，请检查您的 Index-tts API 是否启动/配置是否正确，报错内容: {e}')

            return None
            
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f'Index-tts未知错误，请检查您的Index-tts API是否启动/配置是否正确，报错内容: {e}')
        
        return None

    async def download_audio(self, type: str, file_url: str, timeout: int=30, request_type: str="get", data=None, json_data=None, audio_suffix: str="wav"):
        async with aiohttp.ClientSession() as session:
            try:
                if request_type == "get":
                    async with session.get(file_url, params=data, timeout=timeout) as response:
                        if response.status == 200:
                            content = await response.read()
                            # Use high-entropy timestamp to avoid filename collisions and ensure directory exists; retry on PermissionError
                            for attempt in range(3):
                                file_name = f"{type}_" + self.common.get_bj_time(7) + (f"_{attempt}" if attempt else "") + f".{audio_suffix}"
                                voice_tmp_path = self.common.get_new_audio_path(self.audio_out_path, file_name)
                                try:
                                    os.makedirs(os.path.dirname(voice_tmp_path), exist_ok=True)
                                    with open(voice_tmp_path, 'wb') as file:
                                        file.write(content)
                                    logger.debug(f"{type} 写入音频成功: {voice_tmp_path}")
                                    return voice_tmp_path
                                except PermissionError as e:
                                    logger.warning(f"{type} 写入音频被拒绝，重试第 {attempt+1} 次，路径: {voice_tmp_path}，错误: {e}")
                                    await asyncio.sleep(0.05)
                            logger.error(f"{type} 下载音频失败: 无法写入文件（权限被拒绝）")
                            return None
                        else:
                            logger.error(f'{type} 下载音频失败: {response.status}')
                            return None
                else:
                    async with session.post(file_url, data=data, json=json_data, timeout=timeout) as response:
                        if response.status == 200:
                            content = await response.read()
                            # Use high-entropy timestamp to avoid filename collisions and ensure directory exists; retry on PermissionError
                            for attempt in range(3):
                                file_name = f"{type}_" + self.common.get_bj_time(7) + (f"_{attempt}" if attempt else "") + f".{audio_suffix}"
                                voice_tmp_path = self.common.get_new_audio_path(self.audio_out_path, file_name)
                                try:
                                    os.makedirs(os.path.dirname(voice_tmp_path), exist_ok=True)
                                    with open(voice_tmp_path, 'wb') as file:
                                        file.write(content)
                                    logger.debug(f"{type} 写入音频成功: {voice_tmp_path}")
                                    return voice_tmp_path
                                except PermissionError as e:
                                    logger.warning(f"{type} 写入音频被拒绝，重试第 {attempt+1} 次，路径: {voice_tmp_path}，错误: {e}")
                                    await asyncio.sleep(0.05)
                            logger.error(f"{type} 下载音频失败: 无法写入文件（权限被拒绝）")
                            return None
                        else:
                            logger.error(f'{type} 下载音频失败: {response.status}')
                            return None
            except asyncio.TimeoutError:
                logger.error("{type} 下载音频超时")
                return None

    # 请求vits的api
    async def vits_api(self, data):
        try:
            logger.debug(f"data={data}")
            if data["type"] == "vits":
                # API地址 "http://127.0.0.1:23456/voice/vits"
                API_URL = urljoin(data["api_ip_port"], '/voice/vits')
                data_json = {
                    "text": data["content"],
                    "id": data["id"],
                    "format": data["format"],
                    "lang": "ja",
                    "length": data["length"],
                    "noise": data["noise"],
                    "noisew": data["noisew"],
                    "max": data["max"]
                }
                
                if data["lang"] == "中文" or data["lang"] == "汉语":
                    data_json["lang"] = "zh"
                elif data["lang"] == "英文" or data["lang"] == "英语":
                    data_json["lang"] = "en"
                elif data["lang"] == "韩文" or data["lang"] == "韩语":
                    data_json["lang"] = "ko"
                elif data["lang"] == "日文" or data["lang"] == "日语":
                    data_json["lang"] = "ja"
                elif data["lang"] == "自动":
                    data_json["lang"] = "auto"
                else:
                    data_json["lang"] = "auto"
            elif data["type"] == "bert_vits2":
                # API地址 "http://127.0.0.1:23456/voice/bert-vits2"
                API_URL = urljoin(data["api_ip_port"], '/voice/bert-vits2')

                data_json = {
                    "text": data["content"],
                    "id": data["id"],
                    "format": data["format"],
                    "lang": "ja",
                    "length": self.get_random_float(data["length"]),
                    "noise": self.get_random_float(data["noise"]),
                    "noisew": self.get_random_float(data["noisew"]),
                    "max": data["max"],
                    "sdp_radio": self.get_random_float(data["sdp_radio"])
                }
                
                if data["lang"] == "中文" or data["lang"] == "汉语":
                    data_json["lang"] = "zh"
                elif data["lang"] == "英文" or data["lang"] == "英语":
                    data_json["lang"] = "en"
                elif data["lang"] == "韩文" or data["lang"] == "韩语":
                    data_json["lang"] = "ko"
                elif data["lang"] == "日文" or data["lang"] == "日语":
                    data_json["lang"] = "ja"
                elif data["lang"] == "自动":
                    data_json["lang"] = "auto"
                else:
                    data_json["lang"] = "auto"
            elif data["type"] == "gpt_sovits":
                # 请求vits_simple_api的api gpt_sovits
                async def vits_simple_api_gpt_sovits_api(data):
                    try:
                        from aiohttp import FormData

                        logger.debug(f"data={data}")
                        url = urljoin(data["api_ip_port"], '/voice/gpt-sovits')


                        data_json = {
                            "text": data["content"],
                            "id": data["gpt_sovits"]["id"],
                            "format": data["gpt_sovits"]["format"],
                            "lang": data["gpt_sovits"]["lang"],
                            "segment_size": data["gpt_sovits"]["segment_size"],
                            "prompt_text": data["gpt_sovits"]["prompt_text"],
                            "prompt_lang": data["gpt_sovits"]["prompt_lang"],
                            "preset": data["gpt_sovits"]["preset"],
                            "top_k": data["gpt_sovits"]["top_k"],
                            "top_p": data["gpt_sovits"]["top_p"],
                            "temperature": data["gpt_sovits"]["temperature"]
                        }

                        # 创建 FormData 对象
                        form_data = FormData()
                        # 添加文本字段
                        for key, value in data_json.items():
                            form_data.add_field(key, str(value))

                        # 以二进制读取模式打开音频文件，并添加到表单数据中
                        # 'reference_audio' 是字段名称，应与服务器端接收的名称一致
                        form_data.add_field('reference_audio',
                                    open(data["gpt_sovits"]["reference_audio"], 'rb'),
                                    content_type='audio/mpeg')  # 内容类型根据文件类型修改
                            
                        logger.debug(f"data_json={data_json}")

                        logger.debug(f"url={url}")

                        return await self.download_audio("vits_simple_api", url, self.timeout, "post", form_data)
                    except aiohttp.ClientError as e:
                        logger.error(traceback.format_exc())
                        logger.error(f'vits_simple_api gpt_sovits请求失败，请检查您的vits_simple_api是否启动/配置是否正确，报错内容: {e}')
                    except Exception as e:
                        logger.error(traceback.format_exc())
                        logger.error(f'vits_simple_api gpt_sovits未知错误，请检查您的vits_simple_api是否启动/配置是否正确，报错内容: {e}')
                    
                    return None
                
                voice_tmp_path = await vits_simple_api_gpt_sovits_api(data)
                return voice_tmp_path
                
            # logger.info(f"data_json={data_json}")
            # logger.info(f"data={data}")

            logger.debug(f"API_URL={API_URL}")

            url = f"{API_URL}?{urlencode(data_json)}"

            return await self.download_audio("vits", url, self.timeout)
        except aiohttp.ClientError as e:
            logger.error(traceback.format_exc())
            logger.error(f'vits请求失败，请检查您的vits-simple-api是否启动/配置是否正确，报错内容: {e}')
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f'vits未知错误，请检查您的vits-simple-api是否启动/配置是否正确，报错内容: {e}')
        
        return None

    # 请求bert_vits2的api
    async def bert_vits2_api(self, data):
        try:
            logger.debug(f"data={data}")
            if data["type"] == "hiyori":
                # API地址 "http://127.0.0.1:5000/voice"
                API_URL = urljoin(data["api_ip_port"], '/voice')

                data_json = {
                    "text": data["content"],
                    "model_id": data["model_id"],
                    "speaker_name": data["speaker_name"],
                    "speaker_id": data["speaker_id"],
                    "language": data["language"],
                    "length": self.get_random_float(data["length"]),
                    "noise": self.get_random_float(data["noise"]),
                    "noisew": self.get_random_float(data["noisew"]),
                    "sdp_radio": self.get_random_float(data["sdp_radio"]),
                    "auto_translate": data["auto_translate"],
                    "auto_split": data["auto_split"],
                    "emotion": data["emotion"],
                    "style_text": data["style_text"],
                    "style_weight": self.get_random_float(data["style_weight"])
                }
                
                logger.debug(f"data_json={data_json}")
                # logger.info(f"data={data}")

                logger.debug(f"API_URL={API_URL}")

                url = f"{API_URL}?{urlencode(data_json)}"

                # logger.warning(f"url={url}")

                return await self.download_audio("bert_vits2", url, self.timeout)
            elif data["type"] == "刘悦-中文特化API":
                type = data["type"]
                # API地址 "http://127.0.0.1:5000/run/predict/"
                API_URL = urljoin(data[type]["api_ip_port"], '/tts_to_audio/')

                data_json = {
                    "text": data["content"],
                    "speaker": data[type]["speaker"],
                    "language": data["language"],
                    "length_scale": self.get_random_float(data[type]["length_scale"]),
                    "noise_scale": self.get_random_float(data[type]["noise_scale"]),
                    "noise_scale_w": self.get_random_float(data[type]["noise_scale_w"]),
                    "sdp_radio": self.get_random_float(data[type]["sdp_radio"]),
                    "cut_by_sent": data[type]["cut_by_sent"],
                    "interval_between_para": self.get_random_float(data[type]["interval_between_para"]),
                    "interval_between_sent": self.get_random_float(data[type]["interval_between_sent"]),
                    "emotion": data[type]["emotion"],
                    "style_text": data[type]["style_text"],
                    "style_weight": self.get_random_float(data[type]["style_weight"]),
                    "stream": data[type]["stream"]
                }

                logger.debug(f"data_json={data_json}")
                # logger.info(f"data={data}")

                logger.debug(f"API_URL={API_URL}")

                return await self.download_audio("bert_vits2", API_URL, self.timeout, "post", json_data=data_json)
        except aiohttp.ClientError as e:
            logger.error(traceback.format_exc())
            logger.error(f'bert_vits2请求失败，请检查您的bert_vits2 api是否启动/配置是否正确，报错内容: {e}')
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f'bert_vits2未知错误，请检查您的bert_vits2 api是否启动/配置是否正确，报错内容: {e}')
        
        return None
    
    # 请求VITS fast接口获取合成后的音频路径
    def vits_fast_api(self, data):
        try:
            # API地址
            API_URL = urljoin(data["api_ip_port"], '/run/predict/')

            data_json = {
                "fn_index":0,
                "data":[
                    "こんにちわ。",
                    "ikaros",
                    "日本語",
                    1
                ],
                "session_hash":"mnqeianp9th"
            }

            data_json["data"] = [data["content"], data["character"], data["language"], data["speed"]]

            logger.debug(f'data_json={data_json}')

            response = requests.post(url=API_URL, json=data_json, timeout=self.timeout)
            response.raise_for_status()  # 检查响应的状态码

            result = response.content
            ret = json.loads(result)

            file_path = ret["data"][1]["name"]

            new_file_path = self.common.move_file(file_path, os.path.join(self.audio_out_path, 'vits_fast_' + self.common.get_bj_time(7)), 'vits_fast_' + self.common.get_bj_time(7))

            return new_file_path
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f'vits-fast错误，请检查您的vits-fast推理程序是否启动/配置是否正确，报错内容: {e}')
            return None
    

    # 请求Edge-TTS接口获取合成后的音频路径
    async def edge_tts_api(self, data):
        import asyncio
        
        # 内部实现函数
        async def _perform_edge_tts_synthesis():
            import edge_tts
            
            # 检查是否正在关闭，避免在关闭时执行异步操作
            try:
                from utils.audio import Audio
                if hasattr(Audio, 'should_shutdown') and Audio.should_shutdown:
                    logger.info("系统正在关闭，跳过Edge TTS合成")
                    return None
            except (ImportError, AttributeError) as e:
                # 如果无法导入或访问should_shutdown，继续执行
                logger.debug(f"无法检查关闭状态: {e}")
                pass
            
            # 检查事件循环状态，避免在关闭后创建新的future
            try:
                loop = asyncio.get_running_loop()
                if loop.is_closed():
                    logger.warning("事件循环已关闭，无法执行Edge TTS合成")
                    return None
            except RuntimeError:
                # 没有运行中的事件循环，创建新的
                pass
                
            file_name = 'edge_tts_' + self.common.get_bj_time(7) + '.mp3'
            voice_tmp_path = self.common.get_new_audio_path(self.audio_out_path, file_name)
            data["content"] = data["content"].replace('"', '').replace("'", '')

            edge_tts_config = data.get("edge-tts", {})
            if not isinstance(edge_tts_config, dict):
                edge_tts_config = {}
            # 全局默认配置
            edge_tts_default = self.config.get("edge-tts") or {}
            # 若传入配置为空，则使用全局默认；否则将默认值与传入值合并（传入优先）
            if not edge_tts_config:
                edge_tts_config = edge_tts_default
            else:
                merged = dict(edge_tts_default)
                merged.update(edge_tts_config)
                edge_tts_config = merged
            
            proxy = edge_tts_config.get("proxy") or None

            # 再次检查关闭标志，避免在创建连接前被关闭
            try:
                from utils.audio import Audio
                if hasattr(Audio, 'should_shutdown') and Audio.should_shutdown:
                    logger.info("系统正在关闭，跳过Edge TTS合成")
                    return None
            except (AttributeError, NameError, ImportError):
                # 如果无法访问should_shutdown，继续执行
                pass

            communicate = edge_tts.Communicate(
                text=data["content"], 
                voice=edge_tts_config.get("voice", "zh-CN-XiaoyiNeural"), 
                rate=edge_tts_config.get("rate", "+0%"), 
                volume=edge_tts_config.get("volume", "+0%"), 
                proxy=proxy
            )
            
            # 在执行异步保存前最后一次检查关闭标志
            try:
                from utils.audio import Audio
                if hasattr(Audio, 'should_shutdown') and Audio.should_shutdown:
                    logger.info("系统正在关闭，跳过Edge TTS合成")
                    return None
            except (AttributeError, NameError, ImportError):
                # 如果无法访问should_shutdown，继续执行
                pass
                
            await communicate.save(voice_tmp_path)
            return voice_tmp_path
        
        try:
            # 检查当前事件循环状态
            try:
                loop = asyncio.get_running_loop()
                if loop.is_closed():
                    logger.warning("检测到事件循环已关闭，尝试创建新的事件循环")
                    raise RuntimeError("Event loop is closed")
            except RuntimeError:
                # 如果没有运行中的事件循环或事件循环已关闭，创建新的
                logger.info("创建新的事件循环用于Edge TTS合成")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
            return await _perform_edge_tts_synthesis()
            
        except RuntimeError as e:
            if "cannot schedule new futures after interpreter shutdown" in str(e):
                # 静默处理解释器关闭错误，直接使用命令行方式重新合成
                try:
                    # 强制重置Audio.should_shutdown状态
                    from utils.audio import Audio
                    if hasattr(Audio, 'should_shutdown'):
                        Audio.should_shutdown = False
                    
                    # 使用命令行方式重新合成，避免异步问题
                    import subprocess
                    import sys

                    file_name = 'edge_tts_' + self.common.get_bj_time(7) + '.mp3'
                    voice_tmp_path = self.common.get_new_audio_path(self.audio_out_path, file_name)
                    data["content"] = data["content"].replace('"', '').replace("'", '')

                    edge_tts_config = data.get("edge-tts", {})
                    if not isinstance(edge_tts_config, dict):
                        edge_tts_config = {}
                    # 全局默认配置
                    edge_tts_default = self.config.get("edge-tts") or {}
                    # 若传入配置为空，则使用全局默认；否则将默认值与传入值合并（传入优先）
                    if not edge_tts_config:
                        edge_tts_config = edge_tts_default
                    else:
                        merged = dict(edge_tts_default)
                        merged.update(edge_tts_config)
                        edge_tts_config = merged
                    
                    proxy = edge_tts_config.get("proxy")
                    
                    # 使用subprocess调用edge-tts CLI
                    command = [
                        sys.executable, "-m", "edge_tts",
                        "--text", data["content"],
                        "--voice", edge_tts_config.get("voice", "zh-CN-XiaoyiNeural"),
                        "--rate", edge_tts_config.get("rate", "+0%"),
                        "--volume", edge_tts_config.get("volume", "+0%"),
                        "--write-media", voice_tmp_path,
                    ]
                    if proxy:
                        command.extend(["--proxy", proxy])

                    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='ignore')

                    if result.returncode == 0:
                        return voice_tmp_path
                    else:
                        return None
                        
                except Exception as retry_e:
                    return None
            else:
                return None
        except Exception as e:
            # 静默处理Edge TTS错误，避免不必要的日志输出
            return None
        

    # 请求bark-gui的api
    def bark_gui_api(self, data):
        try:
            client = Client(data["api_ip_port"])
            result = client.predict(
                data["content"],	# str  in 'Input Text' Textbox component
                data["spk"],	# str (Option from: ['None', 'announcer', 'custom\\MeMyselfAndI', 'de_speaker_0', 'de_speaker_1', 'de_speaker_2', 'de_speaker_3', 'de_speaker_4', 'de_speaker_5', 'de_speaker_6', 'de_speaker_7', 'de_speaker_8', 'de_speaker_9', 'en_speaker_0', 'en_speaker_1', 'en_speaker_2', 'en_speaker_3', 'en_speaker_4', 'en_speaker_5', 'en_speaker_6', 'en_speaker_7', 'en_speaker_8', 'en_speaker_9', 'es_speaker_0', 'es_speaker_1', 'es_speaker_2', 'es_speaker_3', 'es_speaker_4', 'es_speaker_5', 'es_speaker_6', 'es_speaker_7', 'es_speaker_8', 'es_speaker_9', 'fr_speaker_0', 'fr_speaker_1', 'fr_speaker_2', 'fr_speaker_3', 'fr_speaker_4', 'fr_speaker_5', 'fr_speaker_6', 'fr_speaker_7', 'fr_speaker_8', 'fr_speaker_9', 'hi_speaker_0', 'hi_speaker_1', 'hi_speaker_2', 'hi_speaker_3', 'hi_speaker_4', 'hi_speaker_5', 'hi_speaker_6', 'hi_speaker_7', 'hi_speaker_8', 'hi_speaker_9', 'it_speaker_0', 'it_speaker_1', 'it_speaker_2', 'it_speaker_3', 'it_speaker_4', 'it_speaker_5', 'it_speaker_6', 'it_speaker_7', 'it_speaker_8', 'it_speaker_9', 'ja_speaker_0', 'ja_speaker_1', 'ja_speaker_2', 'ja_speaker_3', 'ja_speaker_4', 'ja_speaker_5', 'ja_speaker_6', 'ja_speaker_7', 'ja_speaker_8', 'ja_speaker_9', 'ko_speaker_0', 'ko_speaker_1', 'ko_speaker_2', 'ko_speaker_3', 'ko_speaker_4', 'ko_speaker_5', 'ko_speaker_6', 'ko_speaker_7', 'ko_speaker_8', 'ko_speaker_9', 'pl_speaker_0', 'pl_speaker_1', 'pl_speaker_2', 'pl_speaker_3', 'pl_speaker_4', 'pl_speaker_5', 'pl_speaker_6', 'pl_speaker_7', 'pl_speaker_8', 'pl_speaker_9', 'pt_speaker_0', 'pt_speaker_1', 'pt_speaker_2', 'pt_speaker_3', 'pt_speaker_4', 'pt_speaker_5', 'pt_speaker_6', 'pt_speaker_7', 'pt_speaker_8', 'pt_speaker_9', 'ru_speaker_0', 'ru_speaker_1', 'ru_speaker_2', 'ru_speaker_3', 'ru_speaker_4', 'ru_speaker_5', 'ru_speaker_6', 'ru_speaker_7', 'ru_speaker_8', 'ru_speaker_9', 'speaker_0', 'speaker_1', 'speaker_2', 'speaker_3', 'speaker_4', 'speaker_5', 'speaker_6', 'speaker_7', 'speaker_8', 'speaker_9', 'tr_speaker_0', 'tr_speaker_1', 'tr_speaker_2', 'tr_speaker_3', 'tr_speaker_4', 'tr_speaker_5', 'tr_speaker_6', 'tr_speaker_7', 'tr_speaker_8', 'tr_speaker_9', 'v2\\de_speaker_0', 'v2\\de_speaker_1', 'v2\\de_speaker_2', 'v2\\de_speaker_3', 'v2\\de_speaker_4', 'v2\\de_speaker_5', 'v2\\de_speaker_6', 'v2\\de_speaker_7', 'v2\\de_speaker_8', 'v2\\de_speaker_9', 'v2\\en_speaker_0', 'v2\\en_speaker_1', 'v2\\en_speaker_2', 'v2\\en_speaker_3', 'v2\\en_speaker_4', 'v2\\en_speaker_5', 'v2\\en_speaker_6', 'v2\\en_speaker_7', 'v2\\en_speaker_8', 'v2\\en_speaker_9', 'v2\\es_speaker_0', 'v2\\es_speaker_1', 'v2\\es_speaker_2', 'v2\\es_speaker_3', 'v2\\es_speaker_4', 'v2\\es_speaker_5', 'v2\\es_speaker_6', 'v2\\es_speaker_7', 'v2\\es_speaker_8', 'v2\\es_speaker_9', 'v2\\fr_speaker_0', 'v2\\fr_speaker_1', 'v2\\fr_speaker_2', 'v2\\fr_speaker_3', 'v2\\fr_speaker_4', 'v2\\fr_speaker_5', 'v2\\fr_speaker_6', 'v2\\fr_speaker_7', 'v2\\fr_speaker_8', 'v2\\fr_speaker_9', 'v2\\hi_speaker_0', 'v2\\hi_speaker_1', 'v2\\hi_speaker_2', 'v2\\hi_speaker_3', 'v2\\hi_speaker_4', 'v2\\hi_speaker_5', 'v2\\hi_speaker_6', 'v2\\hi_speaker_7', 'v2\\hi_speaker_8', 'v2\\hi_speaker_9', 'v2\\it_speaker_0', 'v2\\it_speaker_1', 'v2\\it_speaker_2', 'v2\\it_speaker_3', 'v2\\it_speaker_4', 'v2\\it_speaker_5', 'v2\\it_speaker_6', 'v2\\it_speaker_7', 'v2\\it_speaker_8', 'v2\\it_speaker_9', 'v2\\ja_speaker_0', 'v2\\ja_speaker_1', 'v2\\ja_speaker_2', 'v2\\ja_speaker_3', 'v2\\ja_speaker_4', 'v2\\ja_speaker_5', 'v2\\ja_speaker_6', 'v2\\ja_speaker_7', 'v2\\ja_speaker_8', 'v2\\ja_speaker_9', 'v2\\ko_speaker_0', 'v2\\ko_speaker_1', 'v2\\ko_speaker_2', 'v2\\ko_speaker_3', 'v2\\ko_speaker_4', 'v2\\ko_speaker_5', 'v2\\ko_speaker_6', 'v2\\ko_speaker_7', 'v2\\ko_speaker_8', 'v2\\ko_speaker_9', 'v2\\pl_speaker_0', 'v2\\pl_speaker_1', 'v2\\pl_speaker_2', 'v2\\pl_speaker_3', 'v2\\pl_speaker_4', 'v2\\pl_speaker_5', 'v2\\pl_speaker_6', 'v2\\pl_speaker_7', 'v2\\pl_speaker_8', 'v2\\pl_speaker_9', 'v2\\pt_speaker_0', 'v2\\pt_speaker_1', 'v2\\pt_speaker_2', 'v2\\pt_speaker_3', 'v2\\pt_speaker_4', 'v2\\pt_speaker_5', 'v2\\pt_speaker_6', 'v2\\pt_speaker_7', 'v2\\pt_speaker_8', 'v2\\pt_speaker_9', 'v2\\ru_speaker_0', 'v2\\ru_speaker_1', 'v2\\ru_speaker_2', 'v2\\ru_speaker_3', 'v2\\ru_speaker_4', 'v2\\ru_speaker_5', 'v2\\ru_speaker_6', 'v2\\ru_speaker_7', 'v2\\ru_speaker_8', 'v2\\ru_speaker_9', 'v2\\tr_speaker_0', 'v2\\tr_speaker_1', 'v2\\tr_speaker_2', 'v2\\tr_speaker_3', 'v2\\tr_speaker_4', 'v2\\tr_speaker_5', 'v2\\tr_speaker_6', 'v2\\tr_speaker_7', 'v2\\tr_speaker_8', 'v2\\tr_speaker_9', 'v2\\zh_speaker_0', 'v2\\zh_speaker_1', 'v2\\zh_speaker_2', 'v2\\zh_speaker_3', 'v2\\zh_speaker_4', 'v2\\zh_speaker_5', 'v2\\zh_speaker_6', 'v2\\zh_speaker_7', 'v2\\zh_speaker_8', 'v2\\zh_speaker_9', 'zh_speaker_0', 'zh_speaker_1', 'zh_speaker_2', 'zh_speaker_3', 'zh_speaker_4', 'zh_speaker_5', 'zh_speaker_6', 'zh_speaker_7', 'zh_speaker_8', 'zh_speaker_9']) in 'Voice' Dropdown component
                data["generation_temperature"],	# int | float (numeric value between 0.1 and 1.0) in 'Generation Temperature' Slider component
                data["waveform_temperature"],	# int | float (numeric value between 0.1 and 1.0) in 'Waveform temperature' Slider component
                data["end_of_sentence_probability"],	# int | float (numeric value between 0.0 and 0.5) in 'End of sentence probability' Slider component
                data["quick_generation"],	# bool  in 'Quick Generation' Checkbox component
                [],	# List[str]  in 'Detailed Generation Settings' Checkboxgroup component
                data["seed"],	# int | float  in 'Seed (default -1 = Random)' Number component
                data["batch_count"],	# int | float  in 'Batch count' Number component
                fn_index=3
            )

            new_file_path = self.common.move_file(result, os.path.join(self.audio_out_path, 'bark_gui_' + self.common.get_bj_time(7)), 'bark_gui_' + self.common.get_bj_time(7))

            return new_file_path
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f'bark_gui请求失败，请检查您的bark_gui是否启动/配置是否正确，报错内容: {e}')
            return None
    

    # 请求VALL-E-X的api
    def vall_e_x_api(self, data):
        try:
            client = Client(data["api_ip_port"])
            result = client.predict(
				data["content"],	# str in 'Text' Textbox component
				data["language"],	# str (Option from: ['auto-detect', 'English', '中文', '日本語', 'Mix']) in 'language' Dropdown component
				data["accent"],	# str (Option from: ['no-accent', 'English', '中文', '日本語']) in 'accent' Dropdown component
				data["voice_preset"],	# str (Option from: ['astraea', 'cafe', 'dingzhen', 'esta', 'ikaros', 'MakiseKurisu', 'mikako', 'nymph', 'rosalia', 'seel', 'sohara', 'sukata', 'tomoki', 'tomoko', 'yaesakura', '早见沙织', '神里绫华-日语']) in 'Voice preset' Dropdown component
				data["voice_preset_file_path"],	# str (filepath or URL to file) in 'parameter_46' File component
				fn_index=5
            )

            new_file_path = self.common.move_file(result[1], os.path.join(self.audio_out_path, 'vall_e_x_' + self.common.get_bj_time(7)), 'vall_e_x_' + self.common.get_bj_time(7))

            return new_file_path
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f'vall_e_x_api请求失败，请检查您的bark_gui是否启动/配置是否正确，报错内容: {e}')
            return None


    # 请求genshinvoice.top的api
    async def genshinvoice_top_api(self, text):
        url = 'https://genshinvoice.top/api'

        genshinvoice_top = self.config.get("genshinvoice_top")

        params = {
            'speaker': genshinvoice_top['speaker'],
            'text': text,
            'format': genshinvoice_top['format'],
            'length': genshinvoice_top['length'],
            'noise': genshinvoice_top['noise'],
            'noisew': genshinvoice_top['noisew'],
            'language': genshinvoice_top['language']
        }

        try:
            return await self.download_audio("genshinvoice_top", url, self.timeout, "get", params)
        except aiohttp.ClientError as e:
            logger.error(traceback.format_exc())
            logger.error(f'genshinvoice.top请求失败: {e}')
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f'genshinvoice.top未知错误: {e}')
        
        return None

    # 请求https://tts.ai-hobbyist.org/的api
    async def tts_ai_lab_top_api(self, text):
        url = 'https://tirs.ai-lab.top/api/ex/vits'

        tts_ai_lab_top = self.config.get("tts_ai_lab_top")

        params = {
            "token": tts_ai_lab_top['token'],
            "appid": tts_ai_lab_top['appid'],
            'lang': tts_ai_lab_top['lang'],
            'speaker': tts_ai_lab_top['speaker'],
            'text': text,
            'sdp_ratio': float(tts_ai_lab_top['sdp_ratio']),
            'length': float(tts_ai_lab_top['length']),
            'noise': float(tts_ai_lab_top['noise']),
            'noisew': float(tts_ai_lab_top['noisew'])
        }

        logger.debug(f"params={params}")

        

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=params, timeout=self.timeout) as response:
                    ret = await response.json()
                    logger.debug(ret)

                    url = ret["audio"]

                    if url is None:
                        logger.error(f'tts.ai-lab.top合成失败，错误信息: {ret["message"]}')
                        return None

                    return await self.download_audio("tts_ai_lab_top", url, self.timeout, "get", None)
        except aiohttp.ClientError as e:
            logger.error(traceback.format_exc())
            logger.error(f'tts.ai-lab.top请求失败: {e}')
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f'tts.ai-lab.top未知错误: {e}')
        
        return None

    # 请求OpenAI_TTS的api
    def openai_tts_api(self, data):
        try:
            if data["type"] == "huggingface":
                client = Client(data["api_ip_port"])
                result = client.predict(
                    data["content"],	# str in 'Text' Textbox component
                    data["model"],	# Literal[tts-1, tts-1-hd]  in 'Model' Dropdown component
                    data["voice"],	# Literal[alloy, echo, fable, onyx, nova, shimmer]  in 'Voice Options' Dropdown component
                    data["api_key"],	# str  in 'OpenAI API Key' Textbox component
                    api_name="/tts_enter_key"
                )

                new_file_path = self.common.move_file(result, os.path.join(self.audio_out_path, 'openai_tts_' + self.common.get_bj_time(7)), 'openai_tts_' + self.common.get_bj_time(7), "mp3")

                return new_file_path
            elif data["type"] == "api":
                from openai import OpenAI
                
                client = OpenAI(api_key=data["api_key"], base_url=data['api_ip_port'])

                response = client.audio.speech.create(
                    model=data["model"],
                    voice=data["voice"],
                    input=data["content"]
                )

                file_name = 'openai_tts_' + self.common.get_bj_time(7) + '.mp3'
                voice_tmp_path = self.common.get_new_audio_path(self.audio_out_path, file_name)

                response.stream_to_file(voice_tmp_path)

                return voice_tmp_path
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f'OpenAI_TTS请求失败: {e}')
            return None

    # 请求睿声AI的api
    async def reecho_ai_api(self, text):
        url = 'https://v1.reecho.cn/api/tts/simple-generate'

        reecho_ai = self.config.get("reecho_ai")
        
        headers = {  
            "Authorization": f"Bearer {reecho_ai['Authorization']}",  
            "Content-Type": "application/json"
        }

        params = {
            "model": reecho_ai['model'],
            'randomness': reecho_ai['randomness'],
            'stability_boost': reecho_ai['stability_boost'],
            'voiceId': reecho_ai['voiceId'],
            'text': text,
            "promptId": reecho_ai['promptId'],
            "probability_optimization": reecho_ai['probability_optimization'],
            "break_clone": reecho_ai['break_clone'],
            "flash": reecho_ai['flash'],
            "stream": False
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=params, timeout=self.timeout) as response:
                    ret = await response.json()
                    logger.debug(ret)

                    url = ret["data"]["audio"]

                    return await self.download_audio("reecho.ai", url, self.timeout, "get", None, audio_suffix="mp3")  

        except aiohttp.ClientError as e:
            logger.error(f'reecho.ai请求失败: {e}')
        except Exception as e:
            logger.error(f'reecho.ai未知错误: {e}')
        
        return None


    # 请求gradio的api
    def gradio_tts_api(self, data):
        def get_value_by_index(response, index):
            try:
                # 确保响应是元组或列表，并且索引在范围内
                if isinstance(response, (tuple, list)) and index < len(response):
                    return response[index]
                else:
                    return None
            except IndexError:
                logger.error(traceback.format_exc())
                # 索引超出范围
                return None

        def get_file_path(data):
            try:
                url = data.pop('url')  # 获取并移除URL
                fn_index = data.pop('fn_index')  # 获取并移除函数索引
                data_analysis = data.pop('data_analysis')

                client = Client(url)

                # data是一个字典，包含了所有需要的参数
                data_values = list(data.values())
                result = client.predict(fn_index=fn_index, *data_values)

                logger.debug(result)

                if isinstance(result, (tuple, list)):
                    # 获取索引为1的元素
                    file_path = get_value_by_index(result, int(data_analysis))

                    if file_path:
                        logger.debug(f"文件路径:{file_path}")
                        return file_path
                elif isinstance(result, str):
                    logger.debug(f"文件路径:{result}")
                    return result
                else:
                    logger.error("数据解析失败！Invalid index or response format.")
                    return None
            except Exception as e:
                logger.error(traceback.format_exc())
                # 索引超出范围
                return None

        logger.debug(f"data={data}")
        data_str = data["request_parameters"]
        formatted_data_str = data_str.format(content=data["content"])
        data_json = json.loads(formatted_data_str)

        file_path = get_file_path(data_json)

        new_file_path = self.common.move_file(file_path, os.path.join(self.audio_out_path, 'gradio_tts_' + self.common.get_bj_time(7)), 'gradio_tts_' + self.common.get_bj_time(7))

        return new_file_path


    async def gpt_sovits_api(self, data):
        import base64
        import mimetypes
        import websockets
        import asyncio

        def file_to_data_url(file_path):
            # 根据文件扩展名确定 MIME 类型
            mime_type, _ = mimetypes.guess_type(file_path)

            # 读取文件内容
            with open(file_path, "rb") as file:
                file_content = file.read()

            # 转换为 Base64 编码
            base64_encoded_data = base64.b64encode(file_content).decode('utf-8')

            # 构造完整的 Data URL
            return f"data:{mime_type};base64,{base64_encoded_data}"

        async def websocket_client(data_json):
            try:
                async with websockets.connect(data["ws_ip_port"]) as websocket:
                    # 设置最大连接时长（例如 30 秒）
                    return await asyncio.wait_for(websocket_client_logic(websocket, data_json), timeout=30)
            except asyncio.TimeoutError:
                logger.error("gpt_sovits WebSocket连接超时")
                return None

        async def websocket_client_logic(websocket, data_json):
            async for message in websocket:
                logger.debug(f"Received message: {message}")

                # 解析收到的消息
                data = json.loads(message)
                # 检查是否是预期的消息
                if "msg" in data:
                    if data["msg"] == "send_hash":
                        # 发送响应消息
                        response = json.dumps({"session_hash":"3obpzfqql7f","fn_index":3})
                        await websocket.send(response)
                        logger.debug(f"Sent message: {response}")
                    elif data["msg"] == "send_data":
                        # audio_path = "F:\\GPT-SoVITS\\raws\\ikaros\\1.wav"
                        audio_path = data_json["ref_audio_path"]

                        # 发送响应消息
                        response = json.dumps(
                            {
                                "session_hash":"3obpzfqql7f",
                                "fn_index":3,
                                "data":[
                                    {
                                        "data": file_to_data_url(audio_path),
                                        "name": os.path.basename(audio_path)
                                    },
                                    data_json["prompt_text"], 
                                    data_json["prompt_language"], 
                                    data_json["content"], 
                                    data_json["language"],
                                    data_json["cut"]
                                ]
                            }
                        )
                        await websocket.send(response)
                        logger.debug(f"Sent message: {response}")
                    elif data["msg"] == "process_completed":
                        return data["output"]["data"][0]["name"]
                    
        try:
            logger.debug(f"data={data}")
            
            if data["type"] == "gradio":
                # 调用函数并等待结果
                voice_tmp_path = await websocket_client(data)

                if voice_tmp_path:
                    new_file_path = self.common.move_file(voice_tmp_path, os.path.join(self.audio_out_path, 'gpt_sovits_' + self.common.get_bj_time(7)), 'gpt_sovits_' + self.common.get_bj_time(7))

                return new_file_path
            elif data["type"] == "gradio_0322":
                client = Client(data["gradio_ip_port"])
                voice_tmp_path = client.predict(
                    data["content"],	# str  in '需要合成的文本' Textbox component
                    data["api_0322"]["text_lang"],	# Literal['中文', '英文', '日文', '中英混合', '日英混合', '多语种混合']  in '需要合成的语种' Dropdown component
                    data["api_0322"]["ref_audio_path"],	# filepath  in '请上传3~10秒内参考音频，超过会报错！' Audio component
                    data["api_0322"]["prompt_text"],	# str  in '参考音频的文本' Textbox component
                    data["api_0322"]["prompt_lang"],	# Literal['中文', '英文', '日文', '中英混合', '日英混合', '多语种混合']  in '参考音频的语种' Dropdown component
                    data["api_0322"]["top_k"],	# float (numeric value between 1 and 100) in 'top_k' Slider component
                    data["api_0322"]["top_p"],	# float (numeric value between 0 and 1) in 'top_p' Slider component
                    data["api_0322"]["temperature"],	# float (numeric value between 0 and 1) in 'temperature' Slider component
                    data["api_0322"]["text_split_method"],	# Literal['不切', '凑四句一切', '凑50字一切', '按中文句号。切', '按英文句号.切', '按标点符号切']  in '怎么切' Radio component
                    int(data["api_0322"]["batch_size"]),	# float (numeric value between 1 and 200) in 'batch_size' Slider component
                    float(data["api_0322"]["speed_factor"]),	# float (numeric value between 0.25 and 4) in 'speed_factor' Slider component
                    data["api_0322"]["split_bucket"],	# bool  in '开启无参考文本模式。不填参考文本亦相当于开启。' Checkbox component
                    data["api_0322"]["return_fragment"],	# bool  in '数据分桶(可能会降低一点计算量,选就对了)' Checkbox component
                    data["api_0322"]["fragment_interval"],	# float (numeric value between 0.01 and 1) in '分段间隔(秒)' Slider component
                    api_name="/inference"
                )
                if voice_tmp_path:
                    new_file_path = self.common.move_file(voice_tmp_path, os.path.join(self.audio_out_path, 'gpt_sovits_' + self.common.get_bj_time(7)), 'gpt_sovits_' + self.common.get_bj_time(7))

                return new_file_path
            elif data["type"] == "api":
                try:
                    data_json = {
                        "refer_wav_path": data["ref_audio_path"],
                        "prompt_text": data["prompt_text"],
                        "prompt_language": data["prompt_language"],
                        "text": data["content"],
                        "text_language": data["language"]
                    }
                                        
                    return await self.download_audio("gpt_sovits", data["api_ip_port"], self.timeout, "post", None, data_json)
                except aiohttp.ClientError as e:
                    logger.error(traceback.format_exc())
                    logger.error(f'gpt_sovits请求失败: {e}')
                    return None
                except Exception as e:
                    logger.error(traceback.format_exc())
                    logger.error(f'gpt_sovits未知错误: {e}')
                    return None
            elif data["type"] == "api_0322":
                try:

                    data_json = {
                        "text": data["content"],
                        "text_lang": data["api_0322"]["text_lang"],
                        "ref_audio_path": data["api_0322"]["ref_audio_path"],
                        "prompt_text": data["api_0322"]["prompt_text"],
                        "prompt_lang": data["api_0322"]["prompt_lang"],
                        "top_k": data["api_0322"]["top_k"],
                        "top_p": data["api_0322"]["top_p"],
                        "temperature": data["api_0322"]["temperature"],
                        "text_split_method": data["api_0322"]["text_split_method"],
                        "batch_size":int(data["api_0322"]["batch_size"]),
                        "speed_factor":float(data["api_0322"]["speed_factor"]),
                        "split_bucket":data["api_0322"]["split_bucket"],
                        "return_fragment":data["api_0322"]["return_fragment"],
                        "fragment_interval":data["api_0322"]["fragment_interval"],
                    }
                                        
                    return await self.download_audio("gpt_sovits", data["api_ip_port"], self.timeout, "post", None, data_json)
                except aiohttp.ClientError as e:
                    logger.error(traceback.format_exc())
                    logger.error(f'gpt_sovits请求失败: {e}')
                    return None
                except Exception as e:
                    logger.error(traceback.format_exc())
                    logger.error(f'gpt_sovits未知错误: {e}')
                    return None
            elif data["type"] == "api_0706":
                try:

                    data_json = {
                        "text": data["content"],
                        "refer_wav_path": data["api_0706"]["refer_wav_path"],
                        "text_language": data["api_0706"]["text_language"],
                        "prompt_text": data["api_0706"]["prompt_text"],
                        "prompt_language": data["api_0706"]["prompt_language"],
                        "cut_punc": data["api_0706"]["cut_punc"],
                    }
                                        
                    return await self.download_audio("gpt_sovits", data["api_ip_port"], self.timeout, "post", None, data_json)
                except aiohttp.ClientError as e:
                    logger.error(traceback.format_exc())
                    logger.error(f'gpt_sovits请求失败: {e}')
                    return None
                except Exception as e:
                    logger.error(traceback.format_exc())
                    logger.error(f'gpt_sovits未知错误: {e}')
                    return None
            elif data["type"] == "v2_api_0821":
                try:
                    data_json = {
                        "text": data["content"],
                        "text_lang": data[data["type"]]["text_lang"],
                        "ref_audio_path": data[data["type"]]["ref_audio_path"],
                        "aux_ref_audio_paths": data[data["type"]]["aux_ref_audio_paths"],
                        "prompt_text": data[data["type"]]["prompt_text"],
                        "prompt_lang": data[data["type"]]["prompt_lang"],
                        "top_k": int(data[data["type"]]["top_k"]),
                        "top_p": float(data[data["type"]]["top_p"]),
                        "temperature": float(data[data["type"]]["temperature"]),
                        "text_split_method": data[data["type"]]["text_split_method"],
                        "batch_size": int(data[data["type"]]["batch_size"]),
                        "split_bucket": data[data["type"]]["split_bucket"],
                        "speed_factor": float(data[data["type"]]["speed_factor"]),
                        "fragment_interval": float(data[data["type"]]["fragment_interval"]),
                        "seed": int(data[data["type"]]["seed"]),
                        "media_type": data[data["type"]]["media_type"],
                        "streaming_mode": data[data["type"]]["streaming_mode"],
                        "parallel_infer": data[data["type"]]["parallel_infer"],
                        "repetition_penalty": float(data[data["type"]]["repetition_penalty"]),
                    }

                    API_URL = urljoin(data["api_ip_port"], '/tts')

                    return await self.download_audio("gpt_sovits", API_URL, self.timeout, "post", None, data_json)
                except aiohttp.ClientError as e:
                    logger.error(traceback.format_exc())
                    logger.error(f'gpt_sovits请求失败: {e}')
                    return None
                except Exception as e:
                    logger.error(traceback.format_exc())
                    logger.error(f'gpt_sovits未知错误: {e}')
                    return None
            
            elif data["type"] == "webtts":
                try:
                    # 使用字典推导式构建 params 字典，只包含非空字符串的值
                    params = {
                        key: value
                        for key, value in data["webtts"].items()
                        if value != ""
                        if key != "api_ip_port"
                    }

                    params["speed"] = self.get_random_float(params["speed"])
                    params["text"] = data["content"]

                    if params["version"] in ["1", "2"]:
                        return await self.download_audio("gpt_sovits", data["webtts"]["api_ip_port"], self.timeout, "get", params)
                    elif params["version"] == "1.4":
                        async with aiohttp.ClientSession() as session:
                            async with session.get(data["webtts"]["api_ip_port"], params=params, timeout=self.timeout) as response:
                                resp_json = await response.json()

                                url = urljoin(data["webtts"]["api_ip_port"], resp_json['url'])

                                return await self.download_audio("gpt_sovits", url, self.timeout, "get", params)
                except aiohttp.ClientError as e:
                    logger.error(traceback.format_exc())
                    logger.error(f'gpt_sovits请求失败: {e}')
                    return None
                except Exception as e:
                    logger.error(traceback.format_exc())
                    logger.error(f'gpt_sovits未知错误: {e}')
                    return None
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f'gpt_sovits未知错误，请检查您的gpt_sovits推理是否启动/配置是否正确，报错内容: {e}')
        
        return None


    async def clone_voice_api(self, data):
        API_URL = urljoin(data["api_ip_port"], '/tts')

        # voice=cn-nan.wav&text=%E4%BD%A0%E5%A5%BD&language=zh-cn&speed=1
        params = {
            "voice": data["voice"],
            "language": data["language"],
            "speed": data["speed"],
            "text": data["content"]
        }

        logger.debug(f"params={params}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(API_URL, data=params) as response:
                    ret = await response.json()
                    logger.debug(ret)

                    file_path = ret["filename"]

                    return file_path

        except aiohttp.ClientError as e:
            logger.error(traceback.format_exc())
            logger.error(f'clone_voice请求失败: {e}')
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f'clone_voice未知错误: {e}')
        
        return None


    def azure_tts_api(self, data):
        """调用Azure TTS API合成音频返回音频路径

        Args:
            data (dict): JSON数据

        Returns:
            str: 音频路径
        """
        try:
            import azure.cognitiveservices.speech as speechsdk

            file_name = 'azure_tts_' + self.common.get_bj_time(7) + '.wav'
            voice_tmp_path = self.common.get_new_audio_path(self.audio_out_path, file_name)
            
            # 创建语音配置对象，使用Azure订阅密钥和服务区域
            speech_config = speechsdk.SpeechConfig(subscription=self.config.get("azure_tts", "subscription_key"), region=self.config.get("azure_tts", "region"))
            speech_config.speech_synthesis_voice_name = self.config.get("azure_tts", "voice_name")

            # 创建音频配置对象，指定输出音频文件路径
            audio_config = speechsdk.audio.AudioOutputConfig(filename=voice_tmp_path)

            # 创建语音合成器对象
            speech_synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)

            # 执行文本到语音的转换
            result = speech_synthesizer.speak_text_async(data["content"]).get()

            # 检查结果
            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                logger.debug(f"音频已成功保存到: {voice_tmp_path}")
                return voice_tmp_path
            elif result.reason == speechsdk.ResultReason.Canceled:
                cancellation_details = result.cancellation_details
                logger.error(f"文本转语音取消: {str(cancellation_details.reason)}")
                if cancellation_details.reason == speechsdk.CancellationReason.Error:
                    if cancellation_details.error_details:
                        logger.error(f"错误详情: {str(cancellation_details.error_details)}")

                return None
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f'azure_tts未知错误: {e}')

            return None
        

    async def fish_speech_load_model(self, data):
        API_URL = urljoin(data["api_ip_port"], f'/v1/models/{data["model_name"]}')

        try:
            async with aiohttp.ClientSession() as session:
                async with session.put(API_URL, json=data["model_config"]) as response:
                    if response.status == 200:
                        ret = await response.json()
                        logger.debug(ret)

                        if ret["name"] == data["model_name"]:
                            logger.info(f'fish_speech模型加载成功: {ret["name"]}')
                            return ret
                    else: 
                        return None

        except aiohttp.ClientError as e:
            logger.error(f'fish_speech请求失败: {e}')
        except Exception as e:
            logger.error(f'fish_speech未知错误: {e}')
        
        return None

    async def fish_speech_api(self, data):
        try:
            def replace_empty_strings_with_none(input_dict):
                for key, value in input_dict.items():
                    if value == "":
                        input_dict[key] = None
                return input_dict
        
            if data["type"] == "api_0.2.0":
                url = urljoin(data["api_ip_port"], f'/v1/models/{data["model_name"]}/invoke')

                data["tts_config"] = replace_empty_strings_with_none(data["tts_config"])

                logger.debug(f"data={data}")

                try:
                    return await self.download_audio("fish_speech", url, self.timeout, "post", None, data["tts_config"])
                except aiohttp.ClientError as e:
                    logger.error(f'fish_speech请求失败: {e}')
                except Exception as e:
                    logger.error(f'fish_speech未知错误: {e}')
            elif data["type"] == "api_1.1.0":
                url = urljoin(data["api_ip_port"], f'/v1/invoke')

                data["api_1.1.0"]["reference_audio"] = self.encode_audio_to_base64(data["api_1.1.0"]["reference_audio"])

                data_json = replace_empty_strings_with_none(data["api_1.1.0"])

                
                logger.debug(f"data={data}")

                try:
                    return await self.download_audio("fish_speech", url, self.timeout, "post", None, data_json)
                except aiohttp.ClientError as e:
                    logger.error(f'fish_speech请求失败: {e}')
                except Exception as e:
                    logger.error(f'fish_speech未知错误: {e}')
            
            return None
        except Exception as e:
            logger.error(f'fish_speech未知错误: {e}')
            return None

    async def fish_speech_web_api(self, data):
        import websockets

        session_hash = self.common.generate_session_hash()

        async def websocket_client(data_json):
            try:
                async with websockets.connect("wss://fs.firefly.matce.cn/queue/join") as websocket:
                    # 设置最大连接时长（例如 30 秒）
                    return await asyncio.wait_for(websocket_client_logic(websocket, data_json), timeout=30)
            except asyncio.TimeoutError:
                logger.error("fish_speech WebSocket连接超时")
                return None

        async def websocket_client_logic(websocket, data_json):
            try:
                async for message in websocket:
                    logger.debug(f"ws收到数据: {message}")

                    # 解析收到的消息
                    data = json.loads(message)
                    # 检查是否是预期的消息
                    if "msg" in data:
                        if data["msg"] == "send_hash":
                            # 发送响应消息
                            response = json.dumps({"session_hash":session_hash,"fn_index":3})
                            await websocket.send(response)
                            logger.debug(f"Sent message: {response}")
                        elif data["msg"] == "send_data":
                            # 使用内部配置
                            if self.use_class_config == True:
                                data_json["ref_audio_path"] = self.class_config["fish_speech"]["web"]["ref_audio_path"]
                                data_json["ref_text"] = self.class_config["fish_speech"]["web"]["ref_text"]

                            # 发送响应消息
                            response = json.dumps(
                                {
                                    "data":[
                                        data_json["content"],
                                        data_json["enable_ref_audio"],
                                        {
                                            "name":data_json["ref_audio_path"],
                                            "data":f'https://fs.firefly.matce.cn/file={data_json["ref_audio_path"]}',
                                            "is_file":True,
                                            "orig_name":"audio.wav"
                                        },
                                        data_json["ref_text"],
                                        data_json["maximum_tokens_per_batch"],
                                        data_json["iterative_prompt_length"],
                                        data_json["top_p"],
                                        data_json["repetition_penalty"],
                                        data_json["temperature"],
                                        data_json["speaker"]
                                    ],
                                    "event_data":None,
                                    "fn_index":4,
                                    "session_hash":session_hash
                                }
                            )
                            await websocket.send(response)
                            logger.debug(f"Sent message: {response}")
                        elif data["msg"] == "process_completed":
                            if "data" in data["output"]:
                                return data["output"]["data"][0]["name"]
                            else:
                                logger.error(f"fish_speech 出错:{data['output']}。可能是参考音频已过期导致")

                                # 是否启用了自动更新参考音频
                                if self.class_config["fish_speech"]["web"]["enable_ref_audio_update"]:
                                    logger.info("fish_speech 即将自动更新参考音频")
                                    # 使用内部配置
                                    self.use_class_config = True 
                                    ref_data = await self.fish_speech_web_get_ref_data(data_json["speaker"])
                                    if ref_data is not None:
                                        self.class_config["fish_speech"]["web"]["ref_audio_path"] = ref_data["ref_audio_path"]
                                        self.class_config["fish_speech"]["web"]["ref_text"] = ref_data["ref_text"]
                                        logger.info("fish_speech 自动更新参考音频完毕，下次合成时将会使用新的参考音频")
                                return None
            except Exception as e:
                logger.error(traceback.format_exc())
                logger.error(f"fish_speech 出错:{e}")
                return None
                        
        voice_tmp_path = await websocket_client(data)
        if voice_tmp_path is not None:
            file_url = f"https://fs.firefly.matce.cn/file={voice_tmp_path}"
            logger.debug(file_url)
            voice_tmp_path = await self.download_audio("fish_speech", file_url, 30)

        return voice_tmp_path
    
    # fish speech 获取说话人数据
    async def fish_speech_web_get_ref_data(self, speaker):
        try:
            import websockets

            session_hash = self.common.generate_session_hash()

            async def websocket_client1(speaker):
                try:
                    async with websockets.connect("wss://fs.firefly.matce.cn/queue/join") as websocket:
                        # 设置最大连接时长（例如 30 秒）
                        return await asyncio.wait_for(websocket_client_logic1(websocket, speaker), timeout=30)
                except asyncio.TimeoutError:
                    logger.error("fish_speech WebSocket连接超时")
                    return None

            async def websocket_client_logic1(websocket, speaker):
                async for message in websocket:
                    logger.debug(f"ws收到数据: {message}")

                    # 解析收到的消息
                    data = json.loads(message)
                    # 检查是否是预期的消息
                    if "msg" in data:
                        if data["msg"] == "send_hash":
                            # 发送响应消息
                            response = json.dumps({"session_hash":session_hash,"fn_index":1})
                            await websocket.send(response)
                            logger.debug(f"Sent message: {response}")
                        elif data["msg"] == "send_data":
                            # 发送响应消息
                            response = json.dumps(
                                {
                                    "data":[
                                        speaker,
                                    ],
                                    "event_data":None,
                                    "fn_index":1,
                                    "session_hash":session_hash
                                }
                            )
                            await websocket.send(response)
                            logger.debug(f"Sent message: {response}")
                        elif data["msg"] == "process_completed":
                            return data["output"]["data"]
            
            async def websocket_client2(audio_tmp_path):
                try:
                    async with websockets.connect("wss://fs.firefly.matce.cn/queue/join") as websocket:
                        # 设置最大连接时长（例如 30 秒）
                        return await asyncio.wait_for(websocket_client_logic2(websocket, audio_tmp_path), timeout=30)
                except asyncio.TimeoutError:
                    logger.error("fish_speech WebSocket连接超时")
                    return None

            async def websocket_client_logic2(websocket, audio_tmp_path):
                async for message in websocket:
                    logger.debug(f"ws收到数据: {message}")

                    # 解析收到的消息
                    data = json.loads(message)
                    # 检查是否是预期的消息
                    if "msg" in data:
                        if data["msg"] == "send_hash":
                            # 发送响应消息
                            response = json.dumps({"session_hash":session_hash,"fn_index":2})
                            await websocket.send(response)
                            logger.debug(f"Sent message: {response}")
                        elif data["msg"] == "send_data":
                            # 发送响应消息
                            response = json.dumps(
                                {
                                    "data":[
                                        audio_tmp_path,
                                    ],
                                    "event_data":None,
                                    "fn_index":2,
                                    "session_hash":session_hash
                                }
                            )
                            await websocket.send(response)
                            logger.debug(f"Sent message: {response}")
                        elif data["msg"] == "process_completed":
                            return data["output"]["data"][0]["name"]

            voice_data_list = await websocket_client1(speaker)
            if voice_data_list is None:
                return None

            voice_tmp_path = await websocket_client2(voice_data_list[0])
            if voice_tmp_path is None:
                return None
            
            return {"ref_audio_path": voice_tmp_path, "ref_text": voice_data_list[1]}
        except Exception as e:
            logger.error(f'fish_speech未知错误: {e}')
            return None


    # ChatTTS （gradio_client-0.16.4，版本太低没法用喵）
    async def chattts_api(self, data):
        """ChatTTS Gradio的API对接喵

        Args:
            data (dict): 传参数据喵

        Returns:
            str: 音频路径
        """
        try:
            if data["type"] == "gradio":
                client = Client(data["gradio_ip_port"])
                result = client.predict(
                    data["content"],	# str  in '需要合成的文本' Textbox component
                    data["temperature"], # 越大越发散，越小越保守
                    data["audio_seed_input"], # 声音种子,-1随机，1女生,4女生,8男生
                    api_name="/generate_audio"
                )

                new_file_path = None

                if result:
                    voice_tmp_path = result[0]
                    new_file_path = self.common.move_file(voice_tmp_path, os.path.join(self.audio_out_path, 'chattts_' + self.common.get_bj_time(7)), 'chattts_' + self.common.get_bj_time(7))

                return new_file_path
            elif data["type"] == "gradio_0621":
                client = Client(data["gradio_ip_port"])
                
                result = client.predict(
                    text=data["content"], # str  in '需要合成的文本' Textbox component
                    temperature=data["temperature"], # 越大越发散，越小越保守
                    top_P=data["top_p"],
                    top_K=data["top_k"],
                    audio_seed_input=int(data["audio_seed_input"]), # 声音种子
                    text_seed_input=int(data["text_seed_input"]),
                    refine_text_flag=data["refine_text_flag"],
                    api_name="/generate_audio"
                )

                new_file_path = None

                if result:
                    voice_tmp_path = result[0]
                    new_file_path = self.common.move_file(voice_tmp_path, os.path.join(self.audio_out_path, 'chattts_' + self.common.get_bj_time(7)), 'chattts_' + self.common.get_bj_time(7))

                return new_file_path
            elif data["type"] == "api":
                params = {
                    "text": data["content"],
                    "media_type": data["api"]["media_type"],
                    "seed": data["api"]["seed"],
                    "streaming": data["api"]["streaming"],
                }

                try:
                    return await self.download_audio("ChatTTS", data["api_ip_port"], self.timeout, "post", json_data=params)
                except aiohttp.ClientError as e:
                    logger.error(traceback.format_exc())
                    logger.error(f'ChatTTS请求失败: {e}')
                except Exception as e:
                    logger.error(traceback.format_exc())
                    logger.error(f'ChatTTS未知错误: {e}')
                
                return None
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f'ChatTTS未知错误，请检查您的ChatTTS WebUI是否启动/配置是否正确，报错内容: {e}')
        
        return None

    # CosyVoice （gradio_client-0.16.4，版本太低没法用喵）
    async def cosyvoice_api(self, data):
        """CosyVoice Gradio的API对接喵

        Args:
            data (dict): 传参数据喵

        Returns:
            str: 音频路径
        """
        try:
            if data["type"] == "gradio_0707":
                from gradio_client import Client, file

                client = Client(data["gradio_ip_port"])

                if data["gradio_0707"]["prompt_wav_upload"] == "":
                    prompt_wav_upload = None
                else:
                    prompt_wav_upload = file(data["gradio_0707"]["prompt_wav_upload"])

                result = client.predict(
                    tts_text=data["content"] + "。",
                    mode_checkbox_group=data["gradio_0707"]["mode_checkbox_group"],
                    sft_dropdown=data["gradio_0707"]["sft_dropdown"],
                    prompt_text=data["gradio_0707"]["prompt_text"],
                    prompt_wav_upload=prompt_wav_upload,
                    prompt_wav_record=None,
                    instruct_text=data["gradio_0707"]["instruct_text"],
                    seed=int(data["gradio_0707"]["seed"]),
                    api_name="/generate_audio"
                )

                new_file_path = None

                if result:
                    voice_tmp_path = result
                    new_file_path = self.common.move_file(voice_tmp_path, os.path.join(self.audio_out_path, 'cosyvoice_' + self.common.get_bj_time(7)), 'cosyvoice_' + self.common.get_bj_time(7))

                return new_file_path
            elif data["type"] == "api_0819":
                url = data["api_ip_port"]

                params = {
                    "text": data["content"],
                    "speaker": data["api_0819"]["speaker"],
                    'new': int(data["api_0819"]["new"]),
                    'speed': float(data["api_0819"]["speed"]),
                    'streaming': int(data["api_0819"]["streaming"])
                }

                logger.debug(f"params={params}")

                try:
                    return await self.download_audio("cosyvoice", url, self.timeout, request_type="post", json_data=params)
                except Exception as e:
                    logger.error(traceback.format_exc())
                    logger.error(f'cosyvoice未知错误，请检查您的CosyVoice API是否启动/配置是否正确，报错内容: {e}')
                
                return None
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f'CosyVoice未知错误，请检查您的CosyVoice WebUI是否启动/配置是否正确，报错内容: {e}')
        
        return None

    # F5-TTS （gradio_client-1.4.2，版本太低没法用喵）
    async def f5_tts_api(self, data):
        """F5-TTS Gradio的API对接喵

        Args:
            data (dict): 传参数据喵

        Returns:
            str: 音频路径
        """
        try:
            if data["type"] == "gradio_1023":
                from gradio_client import Client, handle_file

                client = Client(data["gradio_ip_port"])

                result = client.predict(
                    ref_audio_orig=handle_file(data["ref_audio_orig"]),
                    ref_text=data["ref_text"],
                    gen_text=data["content"],
                    model=data["model"],
                    remove_silence=data["remove_silence"],
                    cross_fade_duration=float(data["cross_fade_duration"]),
                    speed=float(data["speed"]),
                    api_name="/infer"
                )

                new_file_path = None

                if result:
                    voice_tmp_path = result[0]
                    new_file_path = self.common.move_file(voice_tmp_path, os.path.join(self.audio_out_path, 'f5_tts_' + self.common.get_bj_time(7)), 'f5_tts_' + self.common.get_bj_time(7))

                return new_file_path
            
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f'F5-TTS未知错误，请检查您的F5-TTS WebUI是否启动/配置是否正确，报错内容: {e}')
        
        return None

    async def multitts_api(self, data):
        try:
            # http://127.0.0.1:8774/forward
            API_URL = urljoin(data["multitts"]["api_ip_port"], "/forward")

            data_json = {
                "text": data["content"],
                "speed": int(data["multitts"]["speed"]),
                "volume": int(data["multitts"]["volume"]),
                "pitch": int(data["multitts"]["pitch"])
            }

            if data["multitts"]["voice"] != "":
                data_json["voice"] = data["multitts"]["voice"]
                
            logger.debug(f"data_json={data_json}")
            logger.debug(f"url={API_URL}")

            return await self.download_audio("multitts", API_URL, self.timeout, "get", data_json)
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f'MultiTTS未知错误，请检查您的MultiTTS 接口服务是否启动/配置/网络是否正确，报错内容: {e}')
        
        return None

    
    async def melotts_api(self, data):
        try:
            API_URL = urljoin(data["melotts"]["api_ip_port"], "/tts")

            data_json = {
                "text": data["content"],
                "speaker_id": int(data["melotts"]["speaker_id"]),
                "sdp_ratio": float(data["melotts"]["sdp_ratio"]),
                "noise_scale": float(data["melotts"]["noise_scale"]),
                "noise_scale_w": float(data["melotts"]["noise_scale_w"]),
                "speed": float(data["melotts"]["speed"]),
            }
                
            logger.debug(f"data_json={data_json}")
            logger.debug(f"url={API_URL}")

            return await self.download_audio("melotts", API_URL, self.timeout, "post", json_data=data_json)
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f'MeloTTS未知错误，请检查您的MeloTTS 接口服务是否启动/配置/网络是否正确，报错内容: {e}')
        
        return None
