import base64
import os
import time
from io import BytesIO
from dataclasses import dataclass
from typing import Any, Optional

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

    def recognize(self, image_path: str, location_hint: Optional[str] = None, time_hint: Optional[str] = None) -> BirdSpeciesResult:
        svc = self._resolve_service()
        try:
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

            svc = str(SettingsManager().get("recognizer/service", "doubao") or "doubao").strip().lower()
        except Exception:
            svc = "doubao"
        return svc if svc in ("doubao", "dongniao") else "doubao"

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
