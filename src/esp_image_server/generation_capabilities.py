"""Generation policy, independent of host OS and model download code.

CPU is the management-only device marker. CPU offload is a CUDA memory strategy,
not permission to run generation on a CPU. MPS remains unsupported.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPolicy:
    precision: str
    vae_precision: str | None = None
    cpu_offload: bool = False


_CUDA_POLICIES = {
    "image": ModelPolicy("float16"),
    "ltx": ModelPolicy("bfloat16"),
    "wan": ModelPolicy("bfloat16", vae_precision="float32", cpu_offload=True),
}


@dataclass(frozen=True)
class GenerationCapabilities:
    device: str

    def supports(self, family: str) -> bool:
        return self.device == "cuda" and family in _CUDA_POLICIES

    def policy(self, family: str) -> ModelPolicy:
        if not self.supports(family):
            raise RuntimeError("Generation requires a working NVIDIA GPU with CUDA and a supported model; CPU generation is not supported. Apple GPU generation is not enabled.")
        return _CUDA_POLICIES[family]

    def place_pipeline(self, pipeline, family: str):
        policy = self.policy(family)
        if policy.cpu_offload:
            pipeline.enable_model_cpu_offload()
            return pipeline
        return pipeline.to(self.device)

    def seeded_generator(self, torch, seed: int | None, family: str = "image"):
        self.policy(family)
        return torch.Generator(device=self.device).manual_seed(seed) if seed is not None else None


def detect_generation_device() -> str:
    """Probe allocation as well as availability, before downloading any models."""
    try:
        import torch
        if torch.cuda.is_available():
            torch.empty(1, device="cuda")
            torch.cuda.synchronize()
            return "cuda"
    except (ImportError, RuntimeError, OSError):
        pass
    return "cpu"


def clear_generation_cache() -> None:
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass
