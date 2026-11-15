import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from cc_up.config import Config, load_config


class ConfigTest(unittest.TestCase):
    def test_invalid_field_types_fail_before_database_or_network_access(self):
        config = Config(endpoint='https://example.workers.dev', token='A' * 43)
        invalid = {'database': None, 'device_id': 42, 'device_name': [], 'batch_size': True,
                   'statistics_offset_minutes': 1.5, 'daily_times': [None], 'endpoint': {}, 'token': 42}
        for field, value in invalid.items():
            with self.subTest(field=field), self.assertRaises(ValueError):
                replace(config, **{field: value}).validate()

    def test_malformed_ports_are_rejected_and_fractional_timezones_are_retained(self):
        config = Config(endpoint='https://example.workers.dev', token='A' * 43, statistics_offset_minutes=330)
        config.validate()
        self.assertEqual(config.statistics_offset_minutes, 330)
        for endpoint in ['https://example.workers.dev:bad', 'https://example.workers.dev:99999', 'https://example.workers.dev:0']:
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                replace(config, endpoint=endpoint).validate()

    def test_config_file_requires_an_object_and_valid_field_types(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            for value in [None, [], {'batch_size': '80'}, {'token_protected': 42}]:
                path.write_text(json.dumps(value), encoding='utf-8')
                with self.subTest(value=value), self.assertRaises(ValueError):
                    load_config(path)
