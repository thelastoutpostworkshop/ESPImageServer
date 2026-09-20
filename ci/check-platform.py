"""Fail CI if the interpreter does not match the intended native target."""

import platform
import struct
import sys

expected_platform, expected_arch = sys.argv[1:]
machine = platform.machine().lower()
architecture = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine, machine)
assert sys.platform == expected_platform, (sys.platform, expected_platform)
assert architecture == expected_arch, (architecture, expected_arch)
assert struct.calcsize("P") == 8, "A 64-bit Python interpreter is required"
print(f"Python target verified: {sys.platform} {architecture}")
