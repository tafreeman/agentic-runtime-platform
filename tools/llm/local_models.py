"""Central local model catalog used by LLM clients and discovery tools."""

from __future__ import annotations

LOCAL_MODELS: dict[str, str] = {
    # PHI-4
    "phi4": "microsoft--Phi-4-mini-instruct-onnx",
    "phi4mini": "microsoft--Phi-4-mini-instruct-onnx",
    "phi4-cpu": "microsoft--Phi-4-mini-instruct-onnx/main/cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4",
    "phi4-gpu": "microsoft--Phi-4-mini-instruct-onnx/main/gpu/gpu-int4-rtn-block-32",
    # PHI-3.5
    "phi3.5": "microsoft--Phi-3.5-mini-instruct-onnx",
    "phi3.5-cpu": "microsoft--Phi-3.5-mini-instruct-onnx/main/cpu_and_mobile/cpu-int4-awq-block-128-acc-level-4",
    "phi3.5-vision": "microsoft--Phi-3.5-vision-instruct-onnx/main/cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4",
    # PHI-3 MINI
    "phi3": "microsoft--Phi-3-mini-4k-instruct-onnx",
    "phi3-cpu": "microsoft--Phi-3-mini-4k-instruct-onnx/main/cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4",
    "phi3-cpu-acc1": "microsoft--Phi-3-mini-4k-instruct-onnx/main/cpu_and_mobile/cpu-int4-rtn-block-32",
    "phi3-dml": "microsoft--Phi-3-mini-4k-instruct-onnx/main/directml/directml-int4-awq-block-128",
    "phi3-vision": "microsoft--Phi-3-vision-128k-instruct-onnx/main/cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4",
    # PHI-3 MEDIUM
    "phi3-medium": "microsoft--Phi-3-medium-4k-instruct-onnx-cpu",
    "phi3-medium-cpu": "microsoft--Phi-3-medium-4k-instruct-onnx-cpu/main/cpu-int4-rtn-block-32-acc-level-4",
    "phi3-medium-dml": "microsoft--Phi-3-medium-4k-instruct-onnx-directml/main/directml-int4-awq-block-128",
    # MISTRAL 7B
    "mistral": "microsoft--mistral-7b-instruct-v0.2-ONNX",
    "mistral-7b": "microsoft--mistral-7b-instruct-v0.2-ONNX",
    "mistral-cpu": "microsoft--mistral-7b-instruct-v0.2-ONNX/main/onnx/cpu_and_mobile/mistral-7b-instruct-v0.2-cpu-int4-rtn-block-32-acc-level-4",
    "mistral-cpu-acc1": "microsoft--mistral-7b-instruct-v0.2-ONNX/main/onnx/cpu_and_mobile/mistral-7b-instruct-v0.2-cpu-int4-rtn-block-32",
    "mistral-dml": "microsoft--mistral-7b-instruct-v0.2-ONNX/main/onnx/directml/mistralai_Mistral-7B-Instruct-v0.2",
    # EMBEDDING MODELS
    "minilm-l6": "sentence-transformers--all-MiniLM-L6-v2",
    "minilm-l12": "sentence-transformers--all-MiniLM-L12-v2",
    # WHISPER
    "whisper-tiny": "khmyznikov--whisper-int8-cpu-ort.onnx",
    "whisper-small": "khmyznikov--whisper-int8-cpu-ort.onnx",
    "whisper-medium": "khmyznikov--whisper-int8-cpu-ort.onnx",
    "whisper": "khmyznikov--whisper-int8-cpu-ort.onnx",
    # IMAGE MODELS
    "stable-diffusion": "CompVis--stable-diffusion-v1-4",
    "esrgan": "microsoft--dml-ai-hub-models",
}
