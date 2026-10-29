import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('controller', ROOT / 'controller/nvidia_fan_controller.py')
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.raw = {
            'devices': [{'uuid': 'GPU-example-one', 'pci_bus_id': '00000000:01:00.0',
                         'x_gpu': 0, 'fans': [0]},
                        {'uuid': 'GPU-example-two', 'pci_bus_id': '00000000:02:00.0',
                         'x_gpu': 1, 'fans': [1, 2]}],
            'curve': [[40,30],[42,33],[44,36],[46,40],[48,44],[50,48],[52,52],
                      [54,56],[56,60],[58,65],[60,70],[62,78],[65,88],[70,100]],
            'options': {'poll_seconds': 2, 'idle_seconds': 120}}
        self.devices, self.curve, self.options = controller.validate_config(self.raw)

    def test_curve_and_identity(self):
        self.assertEqual(len(self.curve), 14)
        self.assertEqual(controller.tier(59, self.curve), 65)
        self.assertEqual(controller.tier(70, self.curve), 100)
        self.assertEqual(len(self.devices), 2)

    def test_hysteresis_and_time(self):
        self.assertEqual(controller.next_speed(54, 65, 5, self.curve, 3, 30), 65)
        self.assertEqual(controller.next_speed(54, 65, 31, self.curve, 3, 30), 60)
        self.assertEqual(controller.next_speed(70, 30, 0, self.curve, 3, 30), 100)

    def test_duplicate_fan_rejected(self):
        self.raw['devices'][1]['fans'] = [0]
        with self.assertRaises(ValueError):
            controller.validate_config(self.raw)

    def test_hot_curve_rejected(self):
        self.raw['curve'][-1] = [75, 100]
        with self.assertRaises(ValueError):
            controller.validate_config(self.raw)

    def test_unknown_option_rejected(self):
        self.raw['options']['magic'] = 1
        with self.assertRaises(ValueError):
            controller.validate_config(self.raw)

    def test_duplicate_device_rejected(self):
        self.raw['devices'][1]['uuid'] = self.raw['devices'][0]['uuid']
        with self.assertRaises(ValueError):
            controller.validate_config(self.raw)


if __name__ == '__main__':
    unittest.main()
