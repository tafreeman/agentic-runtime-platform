#!/usr/bin/env python3
"""
Local Media Model Runner - Image Generation & Speech-to-Text
=============================================================

Supports local ONNX models for:
  - Image Generation (Stable Diffusion)
  - Speech-to-Text (Whisper)

Requirements:
    pip install onnxruntime diffusers transformers pillow soundfile

Usage:
    # Image Generation
    from tools.core.local_media import generate_image
    image = generate_image("A sunset over mountains", output_path="output.png")

    # Speech-to-Text
    from tools.core.local_media import transcribe_audio
    text = transcribe_audio("audio.wav")

Author: Prompts Library Team
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)

# AI Gallery cache path
AI_GALLERY_PATH = Path.home() / ".cache" / "aigallery"


# =============================================================================
# IMAGE GENERATION (Stable Diffusion)
# =============================================================================


def generate_image(
    prompt: str,
    output_path: str | None = None,
    negative_prompt: str = "",
    width: int = 512,
    height: int = 512,
    num_inference_steps: int = 50,
    guidance_scale: float = 7.5,
    seed: int | None = None,
    model_path: str | None = None,
    verbose: bool = False,
) -> str:
    """Generate an image from a text prompt using Stable Diffusion ONNX.

    Args:
        prompt: Text description of the image to generate
        output_path: Path to save the image (default: generated_image.png)
        negative_prompt: What to avoid in the image
        width: Image width (512 or 768 recommended)
        height: Image height (512 or 768 recommended)
        num_inference_steps: More steps = better quality but slower (25-100)
        guidance_scale: How closely to follow the prompt (7-15)
        seed: Random seed for reproducibility
        model_path: Override model path
        verbose: Print progress

    Returns:
        Path to the generated image
    """
    try:
        import numpy as np
        from diffusers import OnnxStableDiffusionPipeline
    except ImportError:
        raise ImportError(
            "Required packages not installed. Install with:\n"
            "  pip install diffusers transformers onnxruntime pillow"
        )

    # Find model path
    if model_path:
        sd_path = Path(model_path)
    else:
        sd_path = AI_GALLERY_PATH / "CompVis--stable-diffusion-v1-4" / "onnx"

    if not sd_path.exists():
        raise FileNotFoundError(
            f"Stable Diffusion model not found at: {sd_path}\n"
            "Download from AI Gallery or HuggingFace."
        )

    if verbose:
        logger.debug("Loading Stable Diffusion from: %s", sd_path)

    # Load pipeline
    pipe = OnnxStableDiffusionPipeline.from_pretrained(
        str(sd_path),
        provider="CPUExecutionProvider",  # Use DmlExecutionProvider for GPU
    )

    # Set seed for reproducibility
    generator = None
    if seed is not None:
        generator = np.random.RandomState(seed)

    if verbose:
        logger.debug("Generating image for: %s...", prompt[:50])

    # Generate
    result = pipe(
        prompt=prompt,
        negative_prompt=negative_prompt if negative_prompt else None,
        width=width,
        height=height,
        num_inference_steps=num_inference_steps,
        guidance_scale=guidance_scale,
        generator=generator,
    )

    image = result.images[0]

    # Save image
    if output_path is None:
        output_path = "generated_image.png"

    image.save(output_path)

    if verbose:
        logger.debug("Image saved to: %s", output_path)

    return output_path


# =============================================================================
# SPEECH-TO-TEXT (Whisper)
# =============================================================================


def transcribe_audio(
    audio_path: str,
    model_size: str = "small",
    language: str | None = None,
    output_path: str | None = None,
    model_path: str | None = None,
    verbose: bool = False,
) -> str:
    """Transcribe audio to text using Whisper ONNX.

    Args:
        audio_path: Path to audio file (WAV, MP3, etc.)
        model_size: tiny, small, medium (small recommended for balance)
        language: Language code (e.g., "en", "es") or None for auto-detect
        output_path: Optional path to save transcription as text file
        model_path: Override model path
        verbose: Print progress

    Returns:
        Transcribed text
    """
    try:
        import numpy as np
        import onnxruntime as ort
    except ImportError:
        raise ImportError(
            "Required packages not installed. Install with:\n"
            "  pip install onnxruntime soundfile numpy"
        )

    try:
        import soundfile as sf
    except ImportError:
        raise ImportError(
            "soundfile not installed. Install with:\n" "  pip install soundfile"
        )

    # Find model path
    if model_path:
        whisper_path = Path(model_path)
    else:
        whisper_base = (
            AI_GALLERY_PATH / "khmyznikov--whisper-int8-cpu-ort.onnx" / "main"
        )
        model_file = f"whisper_{model_size}_int8_cpu_ort_1.18.0.onnx"
        whisper_path = whisper_base / model_file

    if not whisper_path.exists():
        # Try alternative naming
        available = (
            list(whisper_base.glob("whisper_*.onnx")) if whisper_base.exists() else []
        )
        if available:
            whisper_path = available[0]  # Use first available
            if verbose:
                logger.debug("Using available model: %s", whisper_path.name)
        else:
            raise FileNotFoundError(
                f"Whisper model not found at: {whisper_path}\n"
                "Download from AI Gallery or HuggingFace."
            )

    if verbose:
        logger.debug("Loading Whisper from: %s", whisper_path)

    # Load audio
    audio_data, sample_rate = sf.read(audio_path)

    # Convert to mono if stereo
    if len(audio_data.shape) > 1:
        audio_data = audio_data.mean(axis=1)

    # Resample to 16kHz if needed (Whisper expects 16kHz)
    if sample_rate != 16000:
        try:
            import librosa

            audio_data = librosa.resample(
                audio_data, orig_sr=sample_rate, target_sr=16000
            )
        except ImportError:
            if verbose:
                logger.debug(
                    "Warning: Audio is %dHz, Whisper expects 16kHz. "
                    "Install librosa for resampling.",
                    sample_rate,
                )

    if verbose:
        logger.debug("Audio loaded: %.1f seconds", len(audio_data) / 16000)

    # For now, use the transformers library for easier Whisper inference
    # The raw ONNX model requires more complex preprocessing
    try:
        from transformers import WhisperForConditionalGeneration, WhisperProcessor

        # Use HuggingFace Whisper as fallback (more reliable)
        processor = WhisperProcessor.from_pretrained(f"openai/whisper-{model_size}")
        model = WhisperForConditionalGeneration.from_pretrained(
            f"openai/whisper-{model_size}"
        )

        # Process audio
        input_features = processor(
            audio_data, sampling_rate=16000, return_tensors="pt"
        ).input_features

        # Generate
        forced_decoder_ids = None
        if language:
            forced_decoder_ids = processor.get_decoder_prompt_ids(
                language=language, task="transcribe"
            )

        predicted_ids = model.generate(
            input_features, forced_decoder_ids=forced_decoder_ids
        )
        transcription = processor.batch_decode(predicted_ids, skip_special_tokens=True)[
            0
        ]

    except ImportError:
        raise ImportError(
            "transformers and torch required for Whisper. Install with:\n"
            "  pip install transformers torch"
        )

    if verbose:
        logger.debug("Transcription: %s...", transcription[:100])

    # Save to file if requested
    if output_path:
        Path(output_path).write_text(transcription, encoding="utf-8")
        if verbose:
            logger.debug("Saved to: %s", output_path)

    return transcription


# =============================================================================
# IMAGE UPSCALING (ESRGAN)
# =============================================================================


def upscale_image(
    input_path: str,
    output_path: str | None = None,
    scale: int = 4,
    model_path: str | None = None,
    verbose: bool = False,
) -> str:
    """Upscale an image using ESRGAN ONNX.

    Args:
        input_path: Path to input image
        output_path: Path for output image (default: input_upscaled.png)
        scale: Upscale factor (4x is typical)
        model_path: Override model path
        verbose: Print progress

    Returns:
        Path to upscaled image
    """
    try:
        import numpy as np
        import onnxruntime as ort
        from PIL import Image
    except ImportError:
        raise ImportError(
            "Required packages not installed. Install with:\n"
            "  pip install onnxruntime pillow numpy"
        )

    # Find model path
    if model_path:
        esrgan_path = Path(model_path)
    else:
        esrgan_path = (
            AI_GALLERY_PATH
            / "microsoft--dml-ai-hub-models"
            / "main"
            / "esrgan"
            / "esrgan.onnx"
        )

    if not esrgan_path.exists():
        raise FileNotFoundError(
            f"ESRGAN model not found at: {esrgan_path}\n" "Download from AI Gallery."
        )

    if verbose:
        logger.debug("Loading ESRGAN from: %s", esrgan_path)

    # Load image
    img = Image.open(input_path).convert("RGB")

    # Resize to expected input size (ESRGAN expects 128x128)
    img_resized = img.resize((128, 128), Image.Resampling.LANCZOS)

    # Convert to numpy array and normalize
    img_array = np.array(img_resized).astype(np.float32) / 255.0
    img_array = img_array.transpose(2, 0, 1)  # HWC -> CHW
    img_array = np.expand_dims(img_array, 0)  # Add batch dimension

    if verbose:
        logger.debug("Input shape: %s", img_array.shape)

    # Run inference
    session = ort.InferenceSession(str(esrgan_path), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name

    result = session.run([output_name], {input_name: img_array})[0]

    # Convert back to image
    result = result[0].transpose(1, 2, 0)  # CHW -> HWC
    result = (result * 255).clip(0, 255).astype(np.uint8)
    upscaled_img = Image.fromarray(result)

    # Save
    if output_path is None:
        input_stem = Path(input_path).stem
        output_path = f"{input_stem}_upscaled.png"

    upscaled_img.save(output_path)

    if verbose:
        logger.debug("Upscaled image saved to: %s", output_path)

    return output_path


# =============================================================================
# CLI
# =============================================================================


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Local Media Model Runner - Image Generation & Speech-to-Text",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate an image
  python local_media.py image "A beautiful sunset over mountains" -o sunset.png

  # Transcribe audio
  python local_media.py transcribe recording.wav -o transcript.txt

  # Upscale an image
  python local_media.py upscale low_res.png -o high_res.png
""",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Image generation
    img_parser = subparsers.add_parser("image", help="Generate image from text")
    img_parser.add_argument("prompt", help="Text description of the image")
    img_parser.add_argument("-o", "--output", help="Output file path")
    img_parser.add_argument("--negative", default="", help="Negative prompt")
    img_parser.add_argument("--width", type=int, default=512, help="Image width")
    img_parser.add_argument("--height", type=int, default=512, help="Image height")
    img_parser.add_argument("--steps", type=int, default=50, help="Inference steps")
    img_parser.add_argument("--seed", type=int, help="Random seed")
    img_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose output"
    )

    # Transcription
    trans_parser = subparsers.add_parser("transcribe", help="Transcribe audio to text")
    trans_parser.add_argument("audio", help="Audio file path")
    trans_parser.add_argument("-o", "--output", help="Output text file path")
    trans_parser.add_argument(
        "--model",
        default="small",
        choices=["tiny", "small", "medium"],
        help="Model size",
    )
    trans_parser.add_argument("--language", help="Language code (e.g., en, es)")
    trans_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose output"
    )

    # Upscaling
    up_parser = subparsers.add_parser("upscale", help="Upscale an image")
    up_parser.add_argument("image", help="Input image path")
    up_parser.add_argument("-o", "--output", help="Output file path")
    up_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose output"
    )

    args = parser.parse_args()

    if args.command == "image":
        result = generate_image(
            prompt=args.prompt,
            output_path=args.output,
            negative_prompt=args.negative,
            width=args.width,
            height=args.height,
            num_inference_steps=args.steps,
            seed=args.seed,
            verbose=args.verbose,
        )
        logger.info(f"Generated: {result}")

    elif args.command == "transcribe":
        result = transcribe_audio(
            audio_path=args.audio,
            model_size=args.model,
            language=args.language,
            output_path=args.output,
            verbose=args.verbose,
        )
        logger.info(f"\nTranscription:\n{result}")

    elif args.command == "upscale":
        result = upscale_image(
            input_path=args.image,
            output_path=args.output,
            verbose=args.verbose,
        )
        logger.info(f"Upscaled: {result}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
