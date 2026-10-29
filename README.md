# NVIDIA Linux Adaptive Fans

An experimental adaptive fan controller for Linux, NVIDIA GPUs and Xorg, with manually verified per-GPU fan mappings and a configurable temperature curve.

**Status:** v0.1.0 candidate, not hardware-tested in this portable form. **Do not use unattended on expensive hardware without confirming the fan-to-GPU mappings, recovery procedure, and firmware cooling behavior.**

## Features

- Independent GPU monitoring by NVIDIA UUID and PCI bus address.
- Explicit Xorg GPU/fan mappings; no assumptions that `nvidia-smi` and Xorg indices agree.
- Editable temperature curve, hysteresis and idle timeout.
- NVIDIA AUTO restoration after cooldown.
- `--monitor-only` mode for observing decisions without fan writes.
- Conservative fail-safe attempts on telemetry/control errors. These are best effort, not a replacement for firmware thermal protection.

## Requirements

- NVIDIA Linux drivers supporting fan adjustments via `/usr/bin/nvidia-settings` and `/usr/bin/nvidia-smi`.
- Xorg display with correctly enabled NVIDIA fan control, usually `:0`.
- Python 3.10+.
- Administrative privileges for fan writes.

No Wayland-only or X-less support is currently implemented.

## Setup

1. Read `docs/hardware-mapping.md` and `docs/deployment.md`.
2. Copy `config.example.json` and replace every placeholder with your own physically verified hardware identities and fan targets.
3. Run `python3 -m unittest discover -s tests -v`.
4. After all selected GPUs are in AUTO and other fan controllers have been stopped, run a supervised monitor-only test:

   ```bash
   python3 controller/nvidia_fan_controller.py --config /path/to/your-config.json --display :0 --monitor-only
   ```

5. Only after an attended hardware test, stage the controller with the service template. Do not overwrite any existing service during initial evaluation.

## Safety

This is independent software and is not endorsed by NVIDIA. Incorrect mapping or failed Xorg commands can leave fans at unintended speeds. A loss of telemetry cannot be solved by software alone. Do not run concurrent fan managers.

MIT licensed.
