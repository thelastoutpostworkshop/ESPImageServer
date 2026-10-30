"""Check the installed CUDA wheel and perform a small computation during setup.

Keep this in a file: Windows PowerShell 5.1 does not preserve quoted Python
source reliably when passing it as a native ``python -c`` argument.
Exit codes distinguish package loading, wheel selection, GPU availability,
and computation failures so setup can give the right recovery advice.
"""

import sys


def fail(code: int, message: str) -> int:
    print(message, file=sys.stderr)
    return code


def main() -> int:
    try:
        import torch
    except Exception as error:
        return fail(
            10,
            "PyTorch could not be loaded. Check the installed Python/PyTorch "
            "packages and the Microsoft Visual C++ x64 runtime. "
            f"Details: {type(error).__name__}: {error}",
        )

    if not torch.version.cuda:
        return fail(11, "CPU-only PyTorch was installed; setup requires a CUDA-enabled wheel.")

    try:
        available = torch.cuda.is_available()
    except Exception as error:
        return fail(12, f"Unable to check NVIDIA GPU availability: {type(error).__name__}: {error}")
    if not available:
        return fail(12, "PyTorch cannot access a compatible NVIDIA GPU.")

    try:
        values = torch.ones((16, 16), device="cuda")
        result = values @ values
        torch.cuda.synchronize()
        if not bool((result == 16).all().item()):
            return fail(13, "CUDA computation returned an incorrect result.")
        gpu = torch.cuda.get_device_properties(0)
        print(
            f"CUDA computation passed: {gpu.name}, "
            f"{gpu.total_memory / (1024 ** 3):.1f} GiB total graphics memory, "
            f"PyTorch {torch.__version__}"
        )
    except Exception as error:
        return fail(13, f"CUDA computation failed: {type(error).__name__}: {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
