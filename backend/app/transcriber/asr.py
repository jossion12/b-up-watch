"""Qwen3-ASR 模型懒加载（单例，复用）。

- 首次调用时加载模型（一般 1-3 分钟）
- 模型句柄进程内复用，避免每条视频都重新加载
- 缺包或缺路径时降级为 None；调用方需要先检查可用性
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Optional

log = logging.getLogger(__name__)

_model: Optional[Any] = None
_model_lock = threading.Lock()
_load_error: Optional[str] = None


def _configure_transformers_import() -> None:
    """规避全局环境里 tensorflow/jax 与 numpy 版本冲突导致 transformers 导入失败。

    transformers 会在初始化时根据环境变量决定是否导入 tf/jax；qwen_asr 又依赖
    transformers，因此必须在 transformers 任何子模块被加载前强制禁用它们。
    """
    # 强制禁用 TensorFlow / JAX，防止 transformers 自动导入后触发 numpy 版本冲突
    os.environ["USE_TF"] = "0"
    os.environ["USE_FLAX"] = "0"
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    try:
        import transformers.utils.import_utils as _import_utils

        _import_utils._tf_available = False
        _import_utils._flax_available = False
    except Exception:
        pass


def _resolve_dtype(device: str):
    """根据 device 自动选 dtype（cuda 用 bf16，cpu 用 fp32）。"""
    try:
        import torch
    except ImportError:
        return None
    if device.startswith("cuda"):
        return torch.bfloat16
    return torch.float32


def load_model(model_path: str, device: str = "cpu", max_new_tokens: int = 4096) -> Any:
    """加载 Qwen3-ASR 模型（单例）。失败抛 RuntimeError。"""
    global _model, _load_error
    if _model is not None:
        return _model

    with _model_lock:
        if _model is not None:
            return _model
        try:
            # 抑制 transformers 的啰嗦输出
            os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
            _configure_transformers_import()
            from qwen_asr import Qwen3ASRModel  # 自定义包，未必安装
            import torch
        except ImportError as e:
            _load_error = f"qwen_asr 未安装: {e}"
            raise RuntimeError(_load_error) from e

        if not model_path:
            _load_error = "未配置 QWEN_ASR_MODEL_PATH"
            raise RuntimeError(_load_error)

        requested_device = device or "cpu"
        if requested_device.lower().startswith("cuda") and not torch.cuda.is_available():
            log.warning(
                "requested ASR device %s but CUDA is not available, falling back to cpu",
                requested_device,
            )
            requested_device = "cpu"

        log.info("loading Qwen3-ASR model from %s on %s ...", model_path, requested_device)
        dtype = _resolve_dtype(requested_device)
        kwargs: dict[str, Any] = {
            "dtype": dtype,
            "device_map": requested_device,
            "max_new_tokens": max_new_tokens,
            "local_files_only": True,
        }
        try:
            m = Qwen3ASRModel.from_pretrained(model_path, **kwargs)
        except Exception as e:
            _load_error = f"模型加载失败: {e}"
            raise RuntimeError(_load_error) from e

        _model = m
        log.info("Qwen3-ASR model loaded")
        return _model


def reset_for_test() -> None:
    """仅供测试：清空单例缓存。"""
    global _model, _load_error
    _model = None
    _load_error = None


def is_available(model_path: str) -> bool:
    """快速检查 ASR 是否可用（不真加载模型）。"""
    if not model_path:
        return False
    try:
        _configure_transformers_import()
        import qwen_asr  # noqa: F401
    except ImportError:
        return False
    return True


# 导入本模块时即预处理 transformers 环境，避免后续加载 qwen_asr 时触发 tf/jax 冲突
_configure_transformers_import()