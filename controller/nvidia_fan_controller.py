#!/usr/bin/env python3
"""Conservative X11/NVIDIA adaptive fan controller with explicit GPU mappings."""
import argparse
import csv
import io
import json
import logging
import signal
import subprocess
import time
from pathlib import Path

STOP = False


def run(argv):
    """Execute a vendor CLI with an enforced timeout and nonzero-exit checking."""
    return subprocess.run(argv, check=True, capture_output=True, text=True, timeout=12).stdout


def validate_config(raw):
    """Reject ambiguous fan ownership, invalid GPU identities, and unsafe curves."""
    if not isinstance(raw, dict):
        raise ValueError('Configuration must be an object')
    devices = raw.get('devices')
    curve = raw.get('curve')
    if not isinstance(devices, list) or not devices:
        raise ValueError('Nonempty devices list required')
    if not isinstance(curve, list) or len(curve) < 2:
        raise ValueError('At least two curve points required')
    uuids, buses, gpu_ids, fan_ids = set(), set(), set(), set()
    for d in devices:
        if not isinstance(d, dict) or set(d) != {'uuid', 'pci_bus_id', 'x_gpu', 'fans'}:
            raise ValueError('Each device needs uuid, pci_bus_id, x_gpu and fans')
        uuid, bus, x_gpu, fans = d['uuid'], d['pci_bus_id'], d['x_gpu'], d['fans']
        if not isinstance(uuid, str) or not uuid.startswith('GPU-') or not isinstance(bus, str):
            raise ValueError('Invalid GPU identity')
        if type(x_gpu) is not int or x_gpu < 0 or not isinstance(fans, list) or not fans:
            raise ValueError('Invalid X GPU or fans')
        if any(type(f) is not int or f < 0 for f in fans):
            raise ValueError('Fan indices must be nonnegative integers')
        if uuid in uuids or bus.upper() in buses or x_gpu in gpu_ids or fan_ids.intersection(fans):
            raise ValueError('GPU identity or fan ownership duplicated')
        if len(set(fans)) != len(fans):
            raise ValueError('Fan listed twice on one GPU')
        uuids.add(uuid)
        buses.add(bus.upper())
        gpu_ids.add(x_gpu)
        fan_ids.update(fans)
    previous_temp, previous_speed = -1, -1
    for point in curve:
        if (not isinstance(point, list) or len(point) != 2 or
                any(type(v) is not int for v in point)):
            raise ValueError('Curve points must be [integer Celsius, integer percent]')
        temp, speed = point
        if not 0 <= temp <= 110 or not 30 <= speed <= 100:
            raise ValueError('Curve temperatures/speeds outside safety bounds')
        if temp <= previous_temp or speed <= previous_speed:
            raise ValueError('Curve must increase strictly in temperature and speed')
        previous_temp, previous_speed = temp, speed
    if curve[-1][1] != 100 or curve[-1][0] > 70:
        raise ValueError('Curve must reach 100% by 70 Celsius')
    opts = raw.get('options', {})
    if not isinstance(opts, dict) or set(opts) - {'poll_seconds', 'idle_seconds', 'cool_return_c', 'hot_override_c', 'hysteresis_c', 'reduction_interval_seconds'}:
        raise ValueError('Unknown controller options')
    defaults = dict(poll_seconds=2, idle_seconds=120, cool_return_c=55,
                    hot_override_c=70, hysteresis_c=3, reduction_interval_seconds=30)
    defaults.update(opts)
    for key, value in defaults.items():
        if type(value) is not int or value < 0:
            raise ValueError(f'Invalid numeric option {key}')
    if not 1 <= defaults['poll_seconds'] <= 30 or not 30 <= defaults['idle_seconds'] <= 3600:
        raise ValueError('Polling/cooldown outside allowed range')
    if defaults['hot_override_c'] > 70 or defaults['cool_return_c'] >= defaults['hot_override_c']:
        raise ValueError('Unsafe thermal override/return values')
    return devices, [tuple(p) for p in curve], defaults


def tier(temp, curve):
    """Find the highest configured temperature breakpoint not above temp."""
    result = curve[0][1]
    for threshold, speed in curve:
        if temp >= threshold:
            result = speed
    return result


def next_speed(temp, previous, elapsed, curve, hysteresis, interval):
    """Rise immediately; lower only one tier after time and temperature hysteresis."""
    desired = tier(temp, curve)
    if previous is None or desired >= previous:
        return desired
    idx = next((i for i, (_, speed) in enumerate(curve) if speed == previous), None)
    if idx is None:
        raise ValueError('Previous speed not on configured curve')
    if elapsed < interval or temp > curve[idx][0] - hysteresis:
        return previous
    return curve[max(0, idx - 1)][1]


class Hardware:
    """Isolate NVIDIA CLI calls so policy can be tested without accessing GPUs."""
    def __init__(self, display):
        self.display = display

    def settings(self, *args):
        return run(['/usr/bin/nvidia-settings', '-c', self.display, *args])

    def states(self, devices):
        """Read per-Xorg-GPU fan control mode (0=AUTO; 1=manual)."""
        return {d['uuid']: self.settings('-t', '-q', f"[gpu:{d['x_gpu']}]/GPUFanControlState").strip()
                for d in devices}

    def telemetry(self, devices):
        """Read GPUs, refusing unexpected UUIDs or changed PCI bus assignments."""
        result = run(['/usr/bin/nvidia-smi', '--query-gpu=uuid,pci.bus_id,temperature.gpu,utilization.gpu,power.draw',
                      '--format=csv,noheader,nounits'])
        expected = {d['uuid']: d for d in devices}
        found = {}
        for row in csv.reader(io.StringIO(result)):
            if len(row) != 5:
                raise RuntimeError('Unexpected nvidia-smi columns')
            uuid, bus, temp, util, power = (x.strip() for x in row)
            if uuid not in expected or uuid in found or bus.upper() != expected[uuid]['pci_bus_id'].upper():
                raise RuntimeError(f'Unmapped GPU or PCI mismatch: {uuid} {bus}')
            t, u, p = int(temp), int(util), float(power)
            if not 0 <= t <= 120 or not 0 <= u <= 100 or not 0 <= p <= 1000:
                raise RuntimeError('Invalid telemetry range')
            found[uuid] = (t, u, p)
        if found.keys() != expected.keys():
            raise RuntimeError('GPU inventory does not exactly match configuration')
        return found

    def change(self, device, speed, devices):
        """Set one card to AUTO (None) or manual speed, verifying isolation."""
        before = self.states(devices)
        if set(before.values()) - {'0', '1'}:
            raise RuntimeError('Unknown manual control state')
        gpu, uuid = device['x_gpu'], device['uuid']
        if speed is None:
            self.settings('-a', f'[gpu:{gpu}]/GPUFanControlState=0')
        else:
            args = ['-a', f'[gpu:{gpu}]/GPUFanControlState=1']
            for fan in device['fans']:
                args.extend(['-a', f'[fan:{fan}]/GPUTargetFanSpeed={speed}'])
            self.settings(*args)
        after = self.states(devices)
        if after[uuid] != ('0' if speed is None else '1') or any(
                before[key] != after[key] for key in before if key != uuid):
            raise RuntimeError('Fan mode transition affected unexpected GPU')
        if speed is not None:
            for fan in device['fans']:
                actual = self.settings('-t', '-q', f'[fan:{fan}]/GPUTargetFanSpeed').strip()
                if actual != str(speed):
                    raise RuntimeError(f'Fan {fan} target verification failed: {actual}')


def on_stop(_signum, _frame):
    global STOP
    STOP = True


def main():
    """Poll every card independently, keeping manual mode through idle cooldown."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--display', default=':0')
    parser.add_argument('--monitor-only', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    log = logging.getLogger('nvidia-fan-controller')
    devices, curve, opts = validate_config(json.loads(args.config.read_text()))
    signal.signal(signal.SIGINT, on_stop)
    signal.signal(signal.SIGTERM, on_stop)
    hw = Hardware(args.display)
    readings = hw.telemetry(devices)
    if hw.states(devices) != {d['uuid']: '0' for d in devices}:
        raise RuntimeError('Refusing to start: configured GPUs are not all in AUTO')
    # The user must confirm the fan mapping; Xorg fan relationship queries can be wrong.
    state = {d['uuid']: dict(manual=False, speed=None, active_at=time.monotonic(),
                             streak=0, down_at=float('-inf')) for d in devices}
    log.info('Started; monitor_only=%s GPUs=%s', args.monitor_only, len(devices))
    try:
        while not STOP:
            try:
                readings = hw.telemetry(devices)
                now = time.monotonic()
                for d in devices:
                    uuid = d['uuid']
                    temp, util, power = readings[uuid]
                    s = state[uuid]
                    # Two samples suppress one-off utilization spikes. The power
                    # branch catches memory-heavy work with low sampled GPU util.
                    sample_active = (util >= 20 and power >= 60) or power >= 110
                    s['streak'] = s['streak'] + 1 if sample_active else 0
                    if sample_active:
                        s['active_at'] = now
                    hot = temp >= opts['hot_override_c']
                    # Once manual, remain in control while active/cooling down,
                    # or until temperature is below the safe AUTO return point.
                    needed = s['streak'] >= 2 or hot or (s['manual'] and (
                        now - s['active_at'] < opts['idle_seconds'] or temp >= opts['cool_return_c']))
                    desired = 100 if hot else next_speed(temp, s['speed'], now - s['down_at'],
                        curve, opts['hysteresis_c'], opts['reduction_interval_seconds'])
                    if args.monitor_only:
                        log.info('%s %sC %s%% %.1fW target=%s', uuid, temp, util, power,
                                 f'{desired}%' if needed else 'AUTO')
                    elif needed and (not s['manual'] or s['speed'] != desired):
                        prior = s['speed']
                        hw.change(d, desired, devices)
                        s['manual'], s['speed'] = True, desired
                        if prior is not None and desired < prior:
                            s['down_at'] = now
                        log.info('%s MANUAL %s%% temp=%sC', uuid, desired, temp)
                    elif not needed and s['manual']:
                        hw.change(d, None, devices)
                        s['manual'], s['speed'] = False, None
                        log.info('%s AUTO verified', uuid)
            except (ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                # Never silently accept failed telemetry or an unverified fan
                # write. Full speed is best-effort only if Xorg is reachable.
                log.critical('Control/telemetry failure: %s', exc)
                if not args.monitor_only:
                    for d in devices:
                        try:
                            hw.change(d, 100, devices)
                        except (RuntimeError, subprocess.SubprocessError) as secondary:
                            log.critical('FAILSAFE fan command failed for %s: %s', d['uuid'], secondary)
                    return 2
                return 2
            time.sleep(opts['poll_seconds'])
    finally:
        if not args.monitor_only:
            try:
                readings = hw.telemetry(devices)
                for d in devices:
                    if state[d['uuid']]['manual'] and readings[d['uuid']][0] < opts['hot_override_c']:
                        hw.change(d, None, devices)
                        log.info('%s AUTO verified at shutdown', d['uuid'])
            except (ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                log.critical('Shutdown restoration unavailable: %s', exc)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
