# Deployment and recovery

This is an operator checklist, intentionally not a one-command installer. Do not use a new controller on a critical machine before verifying its physical mapping and recovery path.

1. Inventory the GPUs and fan states, record driver/kernel versions, and identify every software component currently changing fans.
2. Verify the intended configuration against UUID/PCI addresses and the physical fan test log.
3. Preserve a SHA-256 verified, root-owned backup of any existing controller *and* its systemd service file. Record the known-good rollback procedure.
4. Install the new Python script and JSON config to **new staging paths**, root-owned and not writable by regular users.
5. Confirm Python syntax, JSON parsing, tests, and `--monitor-only` work in a supervised test with fans on AUTO.
6. Schedule a maintenance window after inference ends; stop the old service, verify it stopped and restored AUTO, then stage the new service. Never run two live fan controllers concurrently.
7. Start without enabling boot, verify one card at a time with safe workloads and watch actual RPM, temperatures, and mode states.
8. Test per-card inactivity and AUTO recovery; verify error-handling behavior using mocks, not deliberate thermal emergencies on expensive hardware.
9. Enable at boot only after hardware validation and a cold-start test.

The included service template expects `/usr/local/sbin/nvidia_fan_controller.py` and `/etc/nvidia-fan-controller/config.json`. **No installer is supplied** because portable detection and rollback automation are not yet sufficiently verified.

Recovery: stop only the new service, confirm no other controller is driving the same fans, then restore AUTO with a known-good vendor command or the preserved old script. Restore the backup service and code if the upgrade failed. Do not delete backups until a complete boot/inference/cooldown cycle succeeds.
