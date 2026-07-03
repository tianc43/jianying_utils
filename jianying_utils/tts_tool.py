"""TTS 工具 — 基于 Edge-TTS 的文本转语音

免费调用微软 Edge 语音合成接口，无需 API Key。
中文发音人 20+ 种，效果等同 Azure Neural TTS。

适用于 Dify 工作流的代码节点。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.request
from typing import Dict, Any, List, Optional

from . import _context

# Edge-TTS 支持的常用中文发音人
VOICES = {
    "zh-CN-XiaoxiaoNeural":    {"name": "晓晓",  "gender": "Female", "style": "标准女声，活泼清晰"},
    "zh-CN-XiaoyiNeural":      {"name": "晓伊",  "gender": "Female", "style": "温柔女声"},
    "zh-CN-YunjianNeural":     {"name": "云健",  "gender": "Male",   "style": "运动阳光男声"},
    "zh-CN-YunxiNeural":       {"name": "云希",  "gender": "Male",   "style": "温润男声，讲故事感"},
    "zh-CN-YunxiaNeural":      {"name": "云夏",  "gender": "Male",   "style": "活泼可爱男童"},
    "zh-CN-YunyangNeural":     {"name": "云扬",  "gender": "Male",   "style": "专业新闻播报男声"},
    "zh-CN-liaoning-XiaobeiNeural": {"name": "小北", "gender": "Female", "style": "东北话方言"},
    "zh-TW-HsiaoChenNeural":   {"name": "晓臻",  "gender": "Female", "style": "台湾女声"},
    "zh-TW-YunJheNeural":      {"name": "雲哲",  "gender": "Male",   "style": "台湾男声"},
    "zh-HK-HiuGaaiNeural":     {"name": "曉佳",  "gender": "Female", "style": "粤语香港女声"},
    "zh-HK-HiuMaanNeural":     {"name": "曉曼",  "gender": "Female", "style": "粤语香港女声"},
    "zh-HK-WanLungNeural":     {"name": "雲龍",  "gender": "Male",   "style": "粤语香港男声"},
    # 多语言
    "ja-JP-NanamiNeural":      {"name": "Nanami", "gender": "Female", "style": "日语标准女声"},
    "en-US-AriaNeural":        {"name": "Aria",   "gender": "Female", "style": "美式英语女声"},
    "en-US-GuyNeural":         {"name": "Guy",    "gender": "Male",   "style": "美式英语男声"},
}

# 输出音频目录（可通过环境变量配置）
_OUTPUT_DIR = os.environ.get("JIANYING_TTS_DIR", tempfile.gettempdir())


class TTSTool:
    """文本转语音工具类

    基于 Edge-TTS（微软免费接口），提供合成、发音人列表查询。
    所有方法返回统一的 dict 格式。
    """

    @staticmethod
    @_context.catch_errors("语音合成")
    def synthesize(
        text: str,
        voice: str = "zh-CN-XiaoxiaoNeural",
        rate: str = "+0%",
        pitch: str = "+0Hz",
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """文本合成语音

        Args:
            text: 要合成的文本（支持 SSML 标签如 <prosody> 控制语速/音调）
            voice: 发音人 ShortName，默认 "zh-CN-XiaoxiaoNeural"（晓晓）
            rate: 语速，如 "+20%" 加快 20%，"-10%" 减慢 10%
            pitch: 音调，如 "+5Hz" 升高，"-5Hz" 降低
            output_path: 输出文件路径（可选，默认保存到临时目录）

        Returns:
            dict: {
                "success": bool,
                "message": str,
                "audio_path": str,        # 音频文件路径
                "duration_seconds": float  # 合成耗时
            }
        """
        if not text or not text.strip():
            return _context.make_result(False, "文本内容为空")

        try:
            import edge_tts
        except ImportError:
            return _context.make_result(False, "edge-tts 未安装，请执行: pip install edge-tts")

        import time

        # 确定输出路径
        if not output_path:
            fname = f"tts_{hash(text.strip()) & 0x7FFFFFFF:08x}.mp3"
            output_path = os.path.join(_OUTPUT_DIR, fname)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        start = time.time()

        async def _run():
            communicate = edge_tts.Communicate(
                text=text.strip(),
                voice=voice,
                rate=rate,
                pitch=pitch,
            )
            await communicate.save(output_path)

        # 在新事件循环中运行
        try:
            loop = asyncio.get_running_loop()
            # 已有运行中的事件循环，用线程池
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, _run())
                future.result(timeout=120)
        except RuntimeError:
            asyncio.run(_run())

        elapsed = round(time.time() - start, 2)

        # 获取音频实际时长（ms 精度），非合成耗时
        audio_duration_sec = elapsed  # fallback
        try:
            from pymediainfo import MediaInfo
            mi = MediaInfo.parse(output_path)
            for track in mi.tracks:
                if track.track_type == "General" and track.duration:
                    # track.duration 是毫秒，精确除以 1000 保留 3 位小数
                    audio_duration_sec = round(float(track.duration) / 1000.0, 3)
                    break
        except Exception:
            pass  # 使用合成耗时作为 fallback

        return _context.make_result(
            True,
            f"合成完成 ({elapsed}s)",
            audio_path=output_path,
            duration_seconds=audio_duration_sec,
            voice=voice,
        )

    @staticmethod
    @_context.catch_errors("Fish Audio 语音合成")
    def synthesize_fish(
        text: str,
        api_key: Optional[str] = None,
        model: str = "s2-pro",
        output_path: Optional[str] = None,
        reference_id: Optional[Any] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        prosody: Optional[Dict[str, Any]] = None,
        chunk_length: Optional[int] = None,
        normalize: Optional[bool] = None,
        format: str = "mp3",
        sample_rate: Optional[int] = None,
        mp3_bitrate: Optional[int] = None,
        opus_bitrate: Optional[int] = None,
        latency: Optional[str] = None,
        max_new_tokens: Optional[int] = None,
        repetition_penalty: Optional[float] = None,
        min_chunk_length: Optional[int] = None,
        condition_on_previous_chunks: Optional[bool] = None,
        early_stop_threshold: Optional[float] = None,
    ) -> Dict[str, Any]:
        """使用 Fish Audio /v1/tts 合成语音。

        Fish Audio 的鉴权优先使用传入的 api_key，其次读取 FISH_API_KEY。
        """
        if not text or not text.strip():
            return _context.make_result(False, "文本内容为空")

        token = api_key or os.environ.get("FISH_API_KEY", "")
        if not token:
            return _context.make_result(False, "缺少 Fish Audio API Key，请设置 FISH_API_KEY")

        audio_format = (format or "mp3").lower()
        if audio_format not in {"wav", "pcm", "mp3", "opus"}:
            return _context.make_result(False, "format 仅支持 wav/pcm/mp3/opus")

        import time

        if not output_path:
            digest = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:12]
            output_path = os.path.join(_OUTPUT_DIR, f"fish_tts_{digest}.{audio_format}")
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        payload = {
            "text": text.strip(),
            "reference_id": reference_id,
            "temperature": temperature,
            "top_p": top_p,
            "prosody": prosody,
            "chunk_length": chunk_length,
            "normalize": normalize,
            "format": audio_format,
            "sample_rate": sample_rate,
            "mp3_bitrate": mp3_bitrate,
            "opus_bitrate": opus_bitrate,
            "latency": latency,
            "max_new_tokens": max_new_tokens,
            "repetition_penalty": repetition_penalty,
            "min_chunk_length": min_chunk_length,
            "condition_on_previous_chunks": condition_on_previous_chunks,
            "early_stop_threshold": early_stop_threshold,
        }
        payload = {key: value for key, value in payload.items() if value is not None}

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            "https://api.fish.audio/v1/tts",
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "model": model,
            },
        )

        start = time.time()
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                audio_bytes = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return _context.make_result(False, f"Fish Audio 请求失败: HTTP {exc.code} {detail}")
        except urllib.error.URLError as exc:
            return _context.make_result(False, f"Fish Audio 网络请求失败: {exc.reason}")

        if not audio_bytes:
            return _context.make_result(False, "Fish Audio 返回空音频")

        with open(output_path, "wb") as output:
            output.write(audio_bytes)

        elapsed = round(time.time() - start, 2)
        audio_duration_sec = elapsed
        try:
            from pymediainfo import MediaInfo
            mi = MediaInfo.parse(output_path)
            for track in mi.tracks:
                if track.track_type == "General" and track.duration:
                    audio_duration_sec = round(float(track.duration) / 1000.0, 3)
                    break
        except Exception:
            pass

        return _context.make_result(
            True,
            f"Fish Audio 合成完成 ({elapsed}s)",
            audio_path=output_path,
            duration_seconds=audio_duration_sec,
            voice=reference_id or "",
            model=model,
            format=audio_format,
        )

    @staticmethod
    def list_voices() -> Dict[str, Any]:
        """列出可用的中文发音人

        Returns:
            dict: {"success": bool, "message": str, "voices": list[dict], "count": int}
        """
        voice_list = [
            {
                "ShortName": k,
                "DisplayName": v["name"],
                "Gender": v["gender"],
                "Style": v["style"],
            }
            for k, v in VOICES.items()
        ]
        return _context.make_result(
            True,
            f"共 {len(voice_list)} 个发音人",
            voices=voice_list,
            count=len(voice_list),
        )
