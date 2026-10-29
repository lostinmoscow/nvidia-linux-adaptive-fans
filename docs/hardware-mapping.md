# Mapping NVIDIA GPU IDs to Xorg fan IDs

`nvidia-smi` GPU index, NVIDIA UUID, Xorg `gpu:N`, and Xorg `fan:N` are separate namespaces. **Never assume index equality.**

Inventory commands (read-only):

```bash
nvidia-smi --query-gpu=index,name,uuid,pci.bus_id,temperature.gpu,fan.speed --format=csv,noheader
DISPLAY=:0 nvidia-settings -c :0 -q gpus
DISPLAY=:0 nvidia-settings -c :0 -q fans
DISPLAY=:0 nvidia-settings -c :0 -q GPUFanControlState
DISPLAY=:0 nvidia-settings -c :0 -q GPUCurrentFanSpeedRPM
```

The Xorg `[gpu:N.fan]` relationship can be missing or ambiguous. Some multi-GPU systems require a supervised *one-fan-at-a-time* experiment to establish physical ownership. Do that with an existing, trusted fan-control tool and a person watching physical cards. Require a second observer or independent telemetry where possible. Preserve a known-good AUTO restoration method before any manual test.

The portable controller will **refuse to start** when identities do not exactly match its configuration or a selected GPU isn't in AUTO. Configured fan indices must be distinct across cards. This does not prove fan ownership. Mapping must be established outside this controller.

The per-GPU AUTO state is `GPUFanControlState=0`; 0% fan *speed* is not the same as AUTO. Hardware may maintain a minimum 30% fan speed under AUTO, or allow zero RPM when cool.
