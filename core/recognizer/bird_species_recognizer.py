import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from io import BytesIO
from dataclasses import dataclass
from typing import Any, Optional
from pathlib import Path

import cv2
import numpy as np
import requests

from utils.log_manager import LogManager
from utils.system.stderr_suppressor import suppress_stderr_fd

class BirdRecognitionError(RuntimeError):
    pass

@dataclass(frozen=True)
class BirdSpeciesResult:
    text: str

class BirdSpeciesRecognizer:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://ark.cn-beijing.volces.com/api/v3",
        model: str = "doubao-seed-1-8-251228",
        timeout_s: int = 60,
        max_side_px: int = 450,
        max_bytes: int = 10 * 1024 * 1024,
    ):
        self._api_key = (api_key or "").strip()
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_s = int(timeout_s)
        self._max_side_px = int(max_side_px)
        self._max_bytes = int(max_bytes)

    def recognize(
        self,
        image_path: str,
        location_hint: Optional[str] = None,
        time_hint: Optional[str] = None,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        region_code: Optional[str] = None,
        apply_region_filter: bool = True
    ) -> BirdSpeciesResult:
        """
        识别鸟种
        
        Args:
            image_path: 图片路径
            location_hint: 地点提示（用于云端识别）
            time_hint: 时间提示（用于云端识别）
            lat: 纬度（用于本地识别的地域过滤）
            lon: 经度（用于本地识别的地域过滤）
            region_code: 区域代码（用于本地识别的地域过滤）
            apply_region_filter: 是否应用地域过滤
        
        Returns:
            BirdSpeciesResult 对象
        """
        svc = self._resolve_service()
        try:
            if svc == "local":
                return self._recognize_local_ipc(
                    image_path,
                    lat=lat,
                    lon=lon,
                    region_code=region_code,
                    apply_region_filter=apply_region_filter
                )
            if svc == "dongniao":
                return self._recognize_dongniao(image_path)
            return self._recognize_doubao(image_path, location_hint=location_hint, time_hint=time_hint)
        except Exception as e:
            try:
                import traceback

                LogManager.instance().error(f"Bird species recognize failed: service={svc} err={e}\n{traceback.format_exc()}")
            except Exception:
                pass
            raise

    def _resolve_service(self) -> str:
        try:
            from utils.setting.settings_manager import SettingsManager

            svc = str(SettingsManager().get("recognizer/service", "local") or "local").strip().lower()
        except Exception:
            svc = "local"
        return svc if svc in ("local", "doubao", "dongniao") else "local"

    def _recognize_local_ipc(
        self,
        image_path: str,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        region_code: Optional[str] = None,
        apply_region_filter: bool = True
    ) -> BirdSpeciesResult:
        """本地IPC识别，支持地域过滤"""
        client = _get_local_bird_ipc_client()
        ok = client.ensure_service()
        if not ok:
            raise BirdRecognitionError("本地识别服务启动失败")
        resp = client.predict(
            image_path=image_path,
            top_k=3,
            min_confidence=0.0,
            lat=lat,
            lon=lon,
            region_code=region_code,
            apply_region_filter=apply_region_filter
        )
        if not bool((resp or {}).get("success")):
            raise BirdRecognitionError(str((resp or {}).get("error") or "本地识别失败"))
        preds = (resp or {}).get("predictions")
        if not isinstance(preds, list) or not preds:
            return BirdSpeciesResult(text="无法识别")
        p0 = preds[0] if isinstance(preds[0], dict) else {}
        name = str(p0.get("chinese_name") or "").strip()
        return BirdSpeciesResult(text=name or "无法识别")

    def _recognize_doubao(self, image_path: str, location_hint: Optional[str] = None, time_hint: Optional[str] = None) -> BirdSpeciesResult:
        api_key = self._resolve_api_key()
        image_bytes = self._prepare_image_bytes(image_path)
        image_url = self._to_data_url(image_bytes, mime_type="image/jpeg")
        loc = str(location_hint or "").strip()
        t = str(time_hint or "").strip()
        if loc:
            loc = loc[:60]
        if t:
            t = t[:60]
        instruction = "用简体中文回答鸟的名字，只回答种名，不要输出任何思考过程。如果无法识别，回答\"无法识别\""
        if t or loc:
            if t and loc:
                prefix = f"这是在{t},{loc}拍的照片。"
            elif t:
                prefix = f"这是在{t}拍的照片。"
            else:
                prefix = f"这是在{loc}拍的照片。"
            instruction = prefix + instruction
        payload = {
            "model": self._model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_image", "image_url": image_url},
                        {
                            "type": "input_text",
                            "text": instruction,
                        },
                    ],
                }
            ],
        }

        url = f"{self._base_url}/responses"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=self._timeout_s)
        except Exception as e:
            raise BirdRecognitionError(f"请求识别服务失败: {e}") from e

        if resp.status_code >= 400:
            body = resp.text or ""
            if len(body) > 2000:
                body = body[:2000] + "..."
            raise BirdRecognitionError(f"识别服务返回错误({resp.status_code}): {body}")

        try:
            data = resp.json()
        except Exception as e:
            body = resp.text or ""
            if len(body) > 2000:
                body = body[:2000] + "..."
            raise BirdRecognitionError(f"解析识别服务响应失败: {e}; body={body}") from e

        text = (self._extract_text(data) or "").strip()
        if not text:
            text = "无法识别"
        return BirdSpeciesResult(text=text)

    def _dongniao_cooldown_remaining_s(self) -> int:
        try:
            from utils.setting.settings_manager import SettingsManager

            last_ts = float(SettingsManager().get("recognizer/dongniao_last_call_ts", 0) or 0)
        except Exception:
            last_ts = 0.0
        if last_ts <= 0:
            return 0
        remain = int(round((last_ts + 30.0) - float(time.time())))
        return int(max(0, remain))

    def _dongniao_mark_called(self):
        try:
            from utils.setting.settings_manager import SettingsManager

            sm = SettingsManager()
            sm.set("recognizer/dongniao_last_call_ts", float(time.time()))
            sm.sync()
        except Exception:
            pass

    def _recognize_dongniao(self, image_path: str) -> BirdSpeciesResult:
        remain = self._dongniao_cooldown_remaining_s()
        if remain > 0:
            raise BirdRecognitionError(f"懂鸟接口冷却中：{int(remain)} 秒后可再次调用")
        self._dongniao_mark_called()

        api_key = "4mcsVvrTjDlzTG9djGkQN0R0"
        endpoint = "https://ai.open.hhodata.com/api/v2/dongniao"

        img_bytes = self._prepare_image_bytes_with_limit(image_path, max_bytes=int(1.8 * 1024 * 1024))
        did = "11223344"

        try:
            resp = requests.post(
                endpoint,
                headers={"api_key": api_key},
                data={"upload": "1", "class": "B", "area": "CN", "did": did},
                files={"image": ("image.jpg", BytesIO(img_bytes), "image/jpeg")},
                timeout=self._timeout_s,
            )
        except Exception as e:
            raise BirdRecognitionError(f"请求懂鸟服务失败: {e}") from e

        try:
            data = resp.json()
        except Exception:
            raise BirdRecognitionError(f"懂鸟上传返回异常: HTTP {resp.status_code}, body={resp.text[:2000]}")
        code, _msg, payload = self._dongniao_extract_status_and_payload(data)
        if resp.status_code != 200 or str(code) != "1000":
            raise BirdRecognitionError(f"懂鸟上传失败: status={code} body={str(data)[:2000]}")
        rid = self._dongniao_extract_recognition_id(payload, data)
        if not rid:
            raise BirdRecognitionError(f"懂鸟返回缺少 recognitionId: {str(data)[:2000]}")

        poll_tries = 8
        time.sleep(1.1)
        last_body = None
        for _ in range(poll_tries):
            try:
                r2 = requests.post(endpoint, headers={"api_key": api_key}, files={"resultid": (None, str(rid))}, timeout=self._timeout_s)
            except Exception as e:
                raise BirdRecognitionError(f"请求懂鸟结果失败: {e}") from e
            try:
                b2 = r2.json()
            except Exception:
                last_body = r2.text
                time.sleep(1.2)
                continue
            last_body = b2
            code2, _msg2, payload2 = self._dongniao_extract_status_and_payload(b2)
            if str(code2) == "1000":
                name = self._dongniao_extract_bird_name(payload2)
                return BirdSpeciesResult(text=name or "无法识别")
            if str(code2) == "1001":
                time.sleep(1.2)
                continue
            raise BirdRecognitionError(f"懂鸟识别失败: status={code2} body={str(b2)[:2000]}")
        raise BirdRecognitionError(f"懂鸟识别超时: body={str(last_body)[:2000]}")

    def _dongniao_extract_status_and_payload(self, data: Any) -> tuple[Optional[str], Optional[str], Any]:
        if isinstance(data, dict):
            status = data.get("status")
            message = data.get("message")
            payload = data.get("data")
            if status is not None:
                s = str(status)
                if isinstance(payload, list) and payload and isinstance(payload[0], (int, str)) and str(payload[0]).isdigit() and not s.isdigit():
                    return str(payload[0]), str(message) if message is not None else None, payload[1] if len(payload) > 1 else None
                return s, str(message) if message is not None else None, payload
            raw = data.get("raw")
            if isinstance(raw, list) and raw:
                return str(raw[0]), str(raw[1]) if len(raw) > 1 and isinstance(raw[1], str) else None, raw[1] if len(raw) > 1 else None
        if isinstance(data, list) and data:
            return str(data[0]), str(data[1]) if len(data) > 1 and isinstance(data[1], str) else None, data[1] if len(data) > 1 else None
        return None, None, None

    def _dongniao_extract_recognition_id(self, payload: Any, raw: Any) -> Optional[str]:
        if isinstance(payload, str) and payload.strip():
            return payload.strip()
        if isinstance(payload, list) and payload:
            try:
                return str(payload[-1]).strip()
            except Exception:
                return None
        if isinstance(payload, dict):
            try:
                rid = payload.get("recognitionId")
                return str(rid).strip() if rid else None
            except Exception:
                return None
        if isinstance(raw, dict):
            d = raw.get("data")
            if isinstance(d, list) and d:
                try:
                    return str(d[-1]).strip()
                except Exception:
                    return None
        return None

    def _dongniao_extract_bird_name(self, payload: Any) -> str:
        if not isinstance(payload, list):
            return ""
        for item in payload:
            if not isinstance(item, dict):
                continue
            candidates = item.get("list")
            if not isinstance(candidates, list):
                continue
            for row in candidates:
                if not isinstance(row, list) or len(row) < 4:
                    continue
                try:
                    cls = str(row[3]).upper()
                except Exception:
                    cls = ""
                if cls and cls != "B":
                    continue
                try:
                    name = str(row[1] or "").strip()
                except Exception:
                    name = ""
                if not name:
                    continue
                try:
                    return (name.split("|", 1)[0] or "").strip()
                except Exception:
                    return name
        for item in payload:
            if not isinstance(item, dict):
                continue
            candidates = item.get("list")
            if not isinstance(candidates, list) or not candidates:
                continue
            row = candidates[0]
            if isinstance(row, list) and len(row) >= 2:
                try:
                    name = str(row[1] or "").strip()
                    return (name.split("|", 1)[0] or "").strip()
                except Exception:
                    return str(row[1] or "").strip()
        return ""

    def _prepare_image_bytes_with_limit(self, image_path: str, max_bytes: int) -> bytes:
        try:
            with open(image_path, "rb") as f:
                raw = f.read()
        except Exception as e:
            raise BirdRecognitionError(f"读取图片失败: {e}") from e

        with suppress_stderr_fd():
            img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if img is None:
            raise BirdRecognitionError("读取图片失败: 不支持的图片格式或文件已损坏")

        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        elif img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

        h, w = img.shape[:2]
        max_side = max(h, w)
        if max_side > self._max_side_px:
            scale = float(self._max_side_px) / float(max_side)
            new_w = max(1, int(round(w * scale)))
            new_h = max(1, int(round(h * scale)))
            img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

        data = self._encode_jpeg_with_limit(img, max_bytes=max_bytes)
        if len(data) > int(max_bytes):
            raise BirdRecognitionError("图片处理失败: 无法将图片压缩到限制以内")
        return data

    def _encode_jpeg_with_limit(self, img_bgr: np.ndarray, max_bytes: int) -> bytes:
        quality = 92
        data = b""
        for _ in range(40):
            ok, buf = cv2.imencode(".jpg", img_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
            if not ok:
                raise BirdRecognitionError("图片处理失败: JPEG 编码失败")
            data = bytes(buf)
            if len(data) <= int(max_bytes):
                return data
            if quality > 50:
                quality = max(50, quality - 5)
                continue
            h, w = img_bgr.shape[:2]
            if max(h, w) <= 64:
                return data
            img_bgr = cv2.resize(
                img_bgr,
                (max(1, int(round(w * 0.85))), max(1, int(round(h * 0.85)))),
                interpolation=cv2.INTER_AREA,
            )
            quality = 85
        return data

    def _resolve_api_key(self) -> str:
        if self._api_key:
            return self._api_key
        env_key = (
            (os.environ.get("ARK_API_KEY") or "").strip()
            or (os.environ.get("DOUBAO_API_KEY") or "").strip()
            or (os.environ.get("VOLC_ARK_API_KEY") or "").strip()
        )
        if env_key:
            return env_key

        try:
            from utils.setting.settings_manager import SettingsManager

            key = str(SettingsManager().get("recognizer/doubao_api_key", "") or "").strip()
            if key:
                return key
        except Exception:
            pass

        return "f76923ee-5662-4a65-9b7a-60a606098ef8"

    def _prepare_image_bytes(self, image_path: str) -> bytes:
        try:
            with open(image_path, "rb") as f:
                raw = f.read()
        except Exception as e:
            raise BirdRecognitionError(f"读取图片失败: {e}") from e

        with suppress_stderr_fd():
            img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if img is None:
            raise BirdRecognitionError("读取图片失败: 不支持的图片格式或文件已损坏")

        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        elif img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

        h, w = img.shape[:2]
        max_side = max(h, w)
        if max_side > self._max_side_px:
            scale = float(self._max_side_px) / float(max_side)
            new_w = max(1, int(round(w * scale)))
            new_h = max(1, int(round(h * scale)))
            img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

        jpg = self._encode_jpeg_with_limits(img)
        if len(jpg) > self._max_bytes:
            raise BirdRecognitionError("图片处理失败: 无法将图片压缩到 10MB 以内")
        return jpg

    def _encode_jpeg_with_limits(self, img_bgr: np.ndarray) -> bytes:
        quality = 92
        for _ in range(40):
            ok, buf = cv2.imencode(".jpg", img_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
            if not ok:
                raise BirdRecognitionError("图片处理失败: JPEG 编码失败")
            data = bytes(buf)
            if len(data) <= self._max_bytes:
                return data
            if quality > 50:
                quality = max(50, quality - 5)
                continue

            h, w = img_bgr.shape[:2]
            if max(h, w) <= 64:
                return data
            img_bgr = cv2.resize(
                img_bgr,
                (max(1, int(round(w * 0.85))), max(1, int(round(h * 0.85)))),
                interpolation=cv2.INTER_AREA,
            )
            quality = 85

        ok, buf = cv2.imencode(".jpg", img_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
        if not ok:
            raise BirdRecognitionError("图片处理失败: JPEG 编码失败")
        return bytes(buf)

    @staticmethod
    def _to_data_url(image_bytes: bytes, mime_type: str) -> str:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        return f"data:{mime_type};base64,{b64}"

    @staticmethod
    def _extract_text(data: Any) -> str:
        if isinstance(data, dict):
            v = data.get("output_text")
            if isinstance(v, str) and v.strip():
                return v

            output = data.get("output")
            if isinstance(output, list):
                texts: list[str] = []
                for item in output:
                    if not isinstance(item, dict):
                        continue
                    content = item.get("content")
                    if isinstance(content, list):
                        for c in content:
                            if not isinstance(c, dict):
                                continue
                            t = c.get("text")
                            if isinstance(t, str) and t.strip():
                                texts.append(t)
                    t2 = item.get("text")
                    if isinstance(t2, str) and t2.strip():
                        texts.append(t2)
                if texts:
                    return "\n".join(texts)

            choices = data.get("choices")
            if isinstance(choices, list) and choices:
                c0 = choices[0]
                if isinstance(c0, dict):
                    msg = c0.get("message")
                    if isinstance(msg, dict):
                        ct = msg.get("content")
                        if isinstance(ct, str):
                            return ct

        return ""


def recognize_bird_species(image_path: str, api_key: Optional[str] = None) -> str:
    try:
        return BirdSpeciesRecognizer(api_key=api_key).recognize(image_path).text
    except Exception:
        return "无法识别"


def run_local_bird_ipc_service():
    try:
        print("[BirdIPC] 启动本地识别服务...")
        svc = _LocalBirdIPCService()
        svc.start()
        print("[BirdIPC] 本地识别服务已停止")
    except Exception as e:
        print(f"[BirdIPC] 本地识别服务异常: {e}")
        import traceback
        traceback.print_exc()
        raise


_local_bird_ipc_client: "_LocalBirdIPCClient | None" = None
_local_bird_ipc_client_lock = threading.Lock()


def _get_local_bird_ipc_client() -> "_LocalBirdIPCClient":
    global _local_bird_ipc_client
    with _local_bird_ipc_client_lock:
        if _local_bird_ipc_client is None:
            _local_bird_ipc_client = _LocalBirdIPCClient()
        return _local_bird_ipc_client


class _LocalBirdModel:
    def __init__(self, opensource_dir: Path, device: str):
        self._opensource_dir = Path(opensource_dir)
        self._device = str(device or "cpu").strip().lower() or "cpu"
        self._bird_info: list[list[str]] = []
        self._model = None
        self._geo_index = None
        self._load_bird_info()
        self._load_model()
        self._init_geo_index()

    @property
    def bird_info(self) -> list[list[str]]:
        return self._bird_info

    @property
    def device(self) -> str:
        return self._device

    def _load_bird_info(self):
        p = self._opensource_dir / "bird_info.json"
        if not p.exists():
            raise BirdRecognitionError(f"缺少鸟种库文件: {p}")
        try:
            self._bird_info = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(self._bird_info, list):
                self._bird_info = []
        except Exception as e:
            raise BirdRecognitionError(f"读取鸟种库失败: {e}") from e

    def _load_model(self):
        print(f"[_LocalBirdModel] 加载模型，设备: {self._device}")
        model_path = self._opensource_dir / "model20240824.pth"
        print(f"[_LocalBirdModel] 模型路径: {model_path}")
        if not model_path.exists():
            raise BirdRecognitionError(f"缺少模型文件: {model_path}")
        print("[_LocalBirdModel] 模型文件存在")
        try:
            print("[_LocalBirdModel] 导入 torch...")
            import torch
            print(f"[_LocalBirdModel] torch 版本: {torch.__version__}")
            import torchvision.models as models
            import torch.nn as nn
            print("[_LocalBirdModel] torch 导入成功")
        except Exception as e:
            print(f"[_LocalBirdModel] 导入 torch 失败: {e}")
            import traceback
            traceback.print_exc()
            raise BirdRecognitionError(f"缺少依赖: {e}") from e

        try:
            print("[_LocalBirdModel] 初始化 ResNet34 模型...")
            net = models.resnet34(weights=None)
            try:
                in_features = int(getattr(net.fc, "in_features", 512) or 512)
            except Exception:
                in_features = 512
            net.fc = nn.Linear(in_features, 11000)
            print("[_LocalBirdModel] 模型初始化成功")
        except Exception as e:
            print(f"[_LocalBirdModel] 初始化模型失败: {e}")
            import traceback
            traceback.print_exc()
            raise BirdRecognitionError(f"初始化模型失败: {e}") from e

        try:
            print("[_LocalBirdModel] 加载模型权重...")
            sd = torch.load(str(model_path), map_location="cpu")
            if isinstance(sd, dict) and "state_dict" in sd and isinstance(sd.get("state_dict"), dict):
                sd = sd["state_dict"]
            if not isinstance(sd, dict):
                raise BirdRecognitionError("模型文件格式异常")
            net.load_state_dict(sd, strict=True)
            print("[_LocalBirdModel] 模型权重加载成功")
        except Exception as e:
            print(f"[_LocalBirdModel] 加载模型权重失败: {e}")
            import traceback
            traceback.print_exc()
            raise BirdRecognitionError(f"加载模型权重失败: {e}") from e

        net.eval()
        try:
            if self._device == "cuda":
                net.to("cuda")
            else:
                net.to("cpu")
        except Exception:
            self._device = "cpu"
            net.to("cpu")
        self._model = net

    def _init_geo_index(self):
        """初始化地理物种索引"""
        try:
            from core.recognizer.geo_filter import get_geo_index
            self._geo_index = get_geo_index()
        except Exception as e:
            try:
                LogManager.instance().debug(f"[LocalBirdModel] 地理索引初始化失败: {e}")
            except Exception:
                pass
            self._geo_index = None

    def _preprocess(self, image_path: str):
        try:
            import torch
        except Exception as e:
            raise BirdRecognitionError(f"缺少依赖: {e}") from e

        try:
            with open(image_path, "rb") as f:
                raw = f.read()
        except Exception as e:
            raise BirdRecognitionError(f"读取图片失败: {e}") from e

        with suppress_stderr_fd():
            img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if img is None:
            raise BirdRecognitionError("读取图片失败: 不支持的图片格式或文件已损坏")
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        elif img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w = img.shape[:2]
        if h <= 0 or w <= 0:
            raise BirdRecognitionError("读取图片失败: 图片尺寸异常")

        short = min(h, w)
        target_short = 256
        if short != target_short:
            scale = float(target_short) / float(short)
            new_w = max(1, int(round(w * scale)))
            new_h = max(1, int(round(h * scale)))
            img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

        h2, w2 = img.shape[:2]
        crop = 224
        y1 = max(0, int((h2 - crop) / 2))
        x1 = max(0, int((w2 - crop) / 2))
        y2 = min(h2, y1 + crop)
        x2 = min(w2, x1 + crop)
        img = img[y1:y2, x1:x2]
        if img.shape[0] != crop or img.shape[1] != crop:
            img = cv2.resize(img, (crop, crop), interpolation=cv2.INTER_AREA)

        arr = img.astype(np.float32) / 255.0
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        arr = (arr - mean) / std
        t = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0).contiguous()
        return t

    def predict(
        self,
        image_path: str,
        top_k: int = 5,
        region_code: Optional[str] = None,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        apply_region_filter: bool = True
    ) -> list[dict[str, Any]]:
        """
        执行鸟种识别预测
        
        Args:
            image_path: 图片路径
            top_k: 返回的候选数量
            region_code: 区域代码（如 "CN", "CN-44"）
            lat: 纬度
            lon: 经度
            apply_region_filter: 是否应用地域过滤
        
        Returns:
            预测结果列表
        """
        try:
            import torch
        except Exception as e:
            raise BirdRecognitionError(f"缺少依赖: {e}") from e

        if self._model is None:
            raise BirdRecognitionError("模型未加载")

        top_k = int(top_k) if int(top_k) > 0 else 5
        x = self._preprocess(image_path)
        try:
            if self._device == "cuda":
                x = x.to("cuda", non_blocking=True)
        except Exception:
            self._device = "cpu"

        with torch.inference_mode():
            logits = self._model(x)
            probs = torch.softmax(logits, dim=1)

        # 获取候选物种集合（用于地理过滤）
        species_set = None
        matched_region = None
        if apply_region_filter and self._geo_index:
            if lat is not None and lon is not None:
                species_set, matched_region = self._geo_index.query_by_location(lat, lon)
            if not species_set and region_code:
                species_set = self._geo_index.query_by_region(region_code)
                matched_region = region_code

        # 如果有地理过滤，扩大top_k以确保过滤后有足够结果
        search_k = top_k
        if species_set:
            search_k = min(top_k * 5, 100)

        try:
            k = min(search_k, int(probs.shape[1]))
        except Exception:
            k = search_k
        vals, idxs = torch.topk(probs, k=k, dim=1)
        vals = vals[0].detach().cpu().numpy().tolist()
        idxs = idxs[0].detach().cpu().numpy().tolist()

        results: list[dict[str, Any]] = []
        max_info = len(self._bird_info) if isinstance(self._bird_info, list) else 0
        for score, idx in zip(vals, idxs):
            try:
                ii = int(idx)
            except Exception:
                continue
            # 地域过滤：跳过不在候选集合中的物种
            if species_set and ii not in species_set:
                continue
            if ii < 0 or ii >= max_info:
                continue
            info = self._bird_info[ii] if isinstance(self._bird_info[ii], list) else []
            chinese = str(info[0] if len(info) > 0 else "").strip()
            english = str(info[1] if len(info) > 1 else "").strip()
            sci = str(info[2] if len(info) > 2 else "").strip()
            results.append(
                {
                    "id": ii,
                    "chinese_name": chinese,
                    "english_name": english,
                    "scientific_name": sci,
                    "confidence": float(score),
                }
            )
            if len(results) >= top_k:
                break
        return results

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        q = str(query or "").strip().lower()
        if not q:
            return []
        try:
            lim = int(limit)
        except Exception:
            lim = 10
        lim = max(1, min(1000, lim))
        results: list[dict[str, Any]] = []
        for idx, bird in enumerate(self._bird_info):
            if not isinstance(bird, list) or not bird:
                continue
            hit = False
            for field in bird:
                try:
                    if q in str(field or "").lower():
                        hit = True
                        break
                except Exception:
                    continue
            if not hit:
                continue
            results.append(
                {
                    "id": int(idx),
                    "chinese_name": str(bird[0] if len(bird) > 0 else "").strip(),
                    "english_name": str(bird[1] if len(bird) > 1 else "").strip(),
                    "scientific_name": str(bird[2] if len(bird) > 2 else "").strip(),
                }
            )
            if len(results) >= lim:
                break
        return results


def _resolve_opensource_dir() -> Path:
    try:
        from utils.paths import PathManager

        root = PathManager.instance().get_project_root()
        p = root / "opensource"
        if p.exists():
            return p
    except Exception:
        pass
    here = Path(__file__).resolve()
    for parent in [here.parent, here.parent.parent, here.parent.parent.parent]:
        p = parent / "opensource"
        if p.exists():
            return p
    return Path("opensource").resolve()


def _resolve_local_bird_ipc_dir() -> str:
    try:
        base = tempfile.gettempdir()
    except Exception:
        base = "."
    p = os.path.join(base, "bpm_bird_ipc_local")
    try:
        os.makedirs(p, exist_ok=True)
    except Exception:
        pass
    return p


class _LocalBirdIPCService:
    def __init__(self, ipc_dir: str | None = None):
        self._ipc_dir = str(ipc_dir or _resolve_local_bird_ipc_dir())
        self._request_file = os.path.join(self._ipc_dir, "request.json")
        self._response_file = os.path.join(self._ipc_dir, "response.json")
        self._lock_file = os.path.join(self._ipc_dir, "service.lock")
        self._running = False
        self._model: _LocalBirdModel | None = None

    def _is_locked(self) -> bool:
        return os.path.exists(self._lock_file)

    def _acquire_lock(self) -> bool:
        try:
            if self._is_locked():
                return False
            with open(self._lock_file, "w", encoding="utf-8") as f:
                f.write(str(os.getpid()))
            return True
        except Exception:
            return False

    def _release_lock(self):
        try:
            if os.path.exists(self._lock_file):
                os.remove(self._lock_file)
        except Exception:
            pass

    def _load_model(self):
        print("[BirdIPC] 正在加载模型...")
        opensource_dir = _resolve_opensource_dir()
        print(f"[BirdIPC] 开源目录: {opensource_dir}")
        device = "cpu"
        try:
            from utils.system.gpu_utils import is_torch_cuda_usable

            if bool(is_torch_cuda_usable()):
                device = "cuda"
                print("[BirdIPC] 使用 CUDA 设备")
            else:
                print("[BirdIPC] 使用 CPU 设备")
        except Exception as e:
            print(f"[BirdIPC] 检测 GPU 失败，使用 CPU: {e}")
            device = "cpu"
        try:
            self._model = _LocalBirdModel(opensource_dir=opensource_dir, device=device)
            print("[BirdIPC] 模型加载成功")
        except Exception as e:
            print(f"[BirdIPC] 模型加载失败: {e}")
            import traceback
            traceback.print_exc()
            raise

    def _read_request(self) -> dict[str, Any] | None:
        try:
            if not os.path.exists(self._request_file):
                return None
            with open(self._request_file, "r", encoding="utf-8") as f:
                req = json.load(f)
            try:
                os.remove(self._request_file)
            except Exception:
                pass
            return req if isinstance(req, dict) else None
        except Exception:
            try:
                os.remove(self._request_file)
            except Exception:
                pass
            return None

    def _write_response(self, resp: dict[str, Any]):
        try:
            resp["pid"] = int(os.getpid())
            resp["ts"] = float(time.time())
        except Exception:
            pass
        try:
            with open(self._response_file, "w", encoding="utf-8") as f:
                json.dump(resp, f, ensure_ascii=False)
        except Exception:
            pass

    def _handle_health(self) -> dict[str, Any]:
        return {"success": True, "status": "healthy", "model_loaded": self._model is not None}

    def _handle_info(self) -> dict[str, Any]:
        if self._model is None:
            return {"success": False, "error": "模型未加载"}
        return {
            "success": True,
            "model": {
                "device": str(self._model.device),
                "bird_info_count": int(len(self._model.bird_info)),
                "output_classes": 11000,
            },
        }

    def _handle_search(self, req: dict[str, Any]) -> dict[str, Any]:
        if self._model is None:
            return {"success": False, "error": "模型未加载"}
        query = str(req.get("query") or "").strip()
        limit = req.get("limit", 10)
        if not query:
            return {"success": False, "error": "Query is required"}
        try:
            lim = int(limit)
        except Exception:
            lim = 10
        results = self._model.search(query=query, limit=lim)
        return {"success": True, "query": query, "results": results, "total": int(len(results))}

    def _handle_predict(self, req: dict[str, Any]) -> dict[str, Any]:
        if self._model is None:
            return {"success": False, "error": "模型未加载"}
        image_path = str(req.get("image_path") or "").strip()
        try:
            image_path = os.path.abspath(image_path)
        except Exception:
            image_path = str(image_path or "").strip()
        if not image_path or not os.path.exists(image_path):
            return {"success": False, "error": "Invalid image path"}
        top_k = req.get("top_k", 5)
        min_confidence = req.get("min_confidence", 0.0)
        # 地域过滤参数
        region_code = req.get("region_code")
        lat = req.get("lat")
        lon = req.get("lon")
        apply_region_filter = bool(req.get("apply_region_filter", True))
        try:
            k = int(top_k)
        except Exception:
            k = 5
        try:
            mc = float(min_confidence)
        except Exception:
            mc = 0.0
        try:
            lat = float(lat) if lat is not None else None
        except Exception:
            lat = None
        try:
            lon = float(lon) if lon is not None else None
        except Exception:
            lon = None
        start = time.time()
        preds = self._model.predict(
            image_path=image_path,
            top_k=k,
            region_code=region_code,
            lat=lat,
            lon=lon,
            apply_region_filter=apply_region_filter
        )
        elapsed = time.time() - start
        preds = [p for p in preds if isinstance(p, dict) and float(p.get("confidence") or 0.0) >= mc]
        return {"success": True, "predictions": preds, "inference_time_ms": float(round(elapsed * 1000.0, 2))}

    def _process(self, req: dict[str, Any]) -> dict[str, Any]:
        try:
            action = str(req.get("action") or "").strip().lower()
        except Exception:
            action = ""
        if action == "health":
            return self._handle_health()
        if action == "info":
            return self._handle_info()
        if action == "search":
            return self._handle_search(req)
        if action == "predict":
            return self._handle_predict(req)
        if action == "shutdown":
            self._running = False
            return {"success": True, "status": "shutting_down"}
        return {"success": False, "error": f"Unknown action: {action}"}

    def start(self):
        if self._is_locked():
            return
        if not self._acquire_lock():
            return
        try:
            self._load_model()
        except Exception as e:
            try:
                self._write_response({"success": False, "error": str(e)})
            except Exception:
                pass
            self._release_lock()
            return
        self._running = True
        try:
            while self._running and self._is_locked():
                req = self._read_request()
                if req is not None:
                    resp = self._process(req)
                    self._write_response(resp)
                time.sleep(0.01)
        finally:
            self._release_lock()
            for fp in [self._request_file, self._response_file]:
                try:
                    if os.path.exists(fp):
                        os.remove(fp)
                except Exception:
                    pass


class _LocalBirdIPCClient:
    def __init__(self, ipc_dir: str | None = None, timeout_s: float = 90.0):
        self._ipc_dir = str(ipc_dir or _resolve_local_bird_ipc_dir())
        self._request_file = os.path.join(self._ipc_dir, "request.json")
        self._response_file = os.path.join(self._ipc_dir, "response.json")
        self._lock_file = os.path.join(self._ipc_dir, "service.lock")
        try:
            self._timeout_s = float(timeout_s)
        except Exception:
            self._timeout_s = 90.0
        self._proc: subprocess.Popen | None = None
        self._call_lock = threading.Lock()

    def is_running(self) -> bool:
        if not os.path.exists(self._lock_file):
            return False
        pid = None
        try:
            with open(self._lock_file, "r", encoding="utf-8") as f:
                txt = str(f.read() or "").strip()
            if txt.isdigit():
                pid = int(txt)
        except Exception:
            pid = None

        if not isinstance(pid, int) or pid <= 0:
            try:
                os.remove(self._lock_file)
            except Exception:
                pass
            return False

        alive = False
        try:
            import psutil

            alive = bool(psutil.pid_exists(int(pid)))
        except Exception:
            try:
                os.kill(int(pid), 0)
                alive = True
            except Exception:
                alive = False

        if alive:
            return True
        try:
            os.remove(self._lock_file)
        except Exception:
            pass
        return False

    def ensure_service(self) -> bool:
        if self.is_running():
            return True
        return self._start_service()

    def _start_service(self) -> bool:
        if self.is_running():
            return True
        try:
            from utils.paths import PathManager

            project_root = PathManager.instance().get_project_root()
        except Exception:
            project_root = Path(__file__).resolve().parents[2]
        try:
            if bool(getattr(sys, "frozen", False)):
                cmd = [sys.executable, "--bird-ipc-service"]
            else:
                cmd = [sys.executable, str(project_root / "main.py"), "--bird-ipc-service"]
        except Exception:
            cmd = [sys.executable, "--bird-ipc-service"]

        print(f"[BirdIPC] 启动服务进程，命令: {' '.join(cmd)}")
        print(f"[BirdIPC] 工作目录: {project_root}")
        print(f"[BirdIPC] 可执行文件: {sys.executable}")
        print(f"[BirdIPC] 是否打包: {getattr(sys, 'frozen', False)}")
        
        env = os.environ.copy()
        try:
            # Windows: 隐藏控制台窗口
            kwargs = {
                "cwd": str(project_root),
                "env": env,
                "stdout": subprocess.PIPE,  # 捕获标准输出
                "stderr": subprocess.PIPE,  # 捕获错误输出
            }
            if sys.platform == "win32":
                kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
            self._proc = subprocess.Popen(cmd, **kwargs)
            print(f"[BirdIPC] 服务进程已启动，PID: {self._proc.pid}")
        except Exception as e:
            print(f"[BirdIPC] 启动服务进程失败: {e}")
            import traceback
            traceback.print_exc()
            self._proc = None
            return False

        start = time.time()
        while time.time() - start < 60.0:
            if self.is_running():
                print("[BirdIPC] 服务进程已就绪")
                return True
            # 检查进程是否已退出
            if self._proc.poll() is not None:
                # 进程已退出，读取输出
                try:
                    stdout_output, stderr_output = self._proc.communicate(timeout=5)
                    if stdout_output:
                        print(f"[BirdIPC] 服务进程标准输出:\n{stdout_output.decode('utf-8', errors='ignore')}")
                    if stderr_output:
                        print(f"[BirdIPC] 服务进程错误输出:\n{stderr_output.decode('utf-8', errors='ignore')}")
                except Exception as e:
                    print(f"[BirdIPC] 读取服务进程输出失败: {e}")
                print(f"[BirdIPC] 服务进程异常退出，返回码: {self._proc.returncode}")
                self._proc = None
                return False
            time.sleep(0.2)
        print("[BirdIPC] 等待服务启动超时")
        return False

    def _send_request(self, req: dict[str, Any]) -> bool:
        try:
            if os.path.exists(self._response_file):
                try:
                    os.remove(self._response_file)
                except Exception:
                    pass
            with open(self._request_file, "w", encoding="utf-8") as f:
                json.dump(req, f, ensure_ascii=False)
            return True
        except Exception:
            return False

    def _wait_response(self) -> dict[str, Any] | None:
        start = time.time()
        while time.time() - start < self._timeout_s:
            try:
                if os.path.exists(self._response_file):
                    with open(self._response_file, "r", encoding="utf-8") as f:
                        resp = json.load(f)
                    try:
                        os.remove(self._response_file)
                    except Exception:
                        pass
                    return resp if isinstance(resp, dict) else {"success": False, "error": "响应格式异常"}
            except Exception:
                time.sleep(0.01)
                continue
            time.sleep(0.01)
        return {"success": False, "error": f"Timeout waiting for response ({self._timeout_s}s)"}

    def call(self, req: dict[str, Any]) -> dict[str, Any]:
        with self._call_lock:
            if not self.ensure_service():
                return {"success": False, "error": "Service not running"}
            if not self._send_request(req):
                return {"success": False, "error": "Failed to send request"}
            resp = self._wait_response()
            return resp if isinstance(resp, dict) else {"success": False, "error": "No response"}

    def health(self) -> dict[str, Any]:
        return self.call({"action": "health"})

    def info(self) -> dict[str, Any]:
        return self.call({"action": "info"})

    def search(self, query: str, limit: int = 10) -> dict[str, Any]:
        return self.call({"action": "search", "query": str(query or ""), "limit": int(limit)})

    def predict(
        self,
        image_path: str,
        top_k: int = 5,
        min_confidence: float = 0.0,
        region_code: Optional[str] = None,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        apply_region_filter: bool = True
    ) -> dict[str, Any]:
        """
        执行鸟种识别预测
        
        Args:
            image_path: 图片路径
            top_k: 返回的候选数量
            min_confidence: 最小置信度阈值
            region_code: 区域代码（如 "CN", "CN-44"）
            lat: 纬度
            lon: 经度
            apply_region_filter: 是否应用地域过滤
        
        Returns:
            识别结果字典
        """
        try:
            image_path = os.path.abspath(str(image_path or ""))
        except Exception:
            image_path = str(image_path or "")
        req = {
            "action": "predict",
            "image_path": str(image_path or ""),
            "top_k": int(top_k),
            "min_confidence": float(min_confidence),
            "apply_region_filter": bool(apply_region_filter),
        }
        if region_code:
            req["region_code"] = str(region_code)
        if lat is not None:
            req["lat"] = float(lat)
        if lon is not None:
            req["lon"] = float(lon)
        return self.call(req)

    def shutdown(self):
        try:
            self.call({"action": "shutdown"})
        except Exception:
            pass
        try:
            if self._proc is not None:
                try:
                    self._proc.terminate()
                except Exception:
                    pass
        finally:
            self._proc = None
