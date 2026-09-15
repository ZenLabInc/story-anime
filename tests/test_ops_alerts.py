import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import ops_alerts
from scripts import monitor_health


class OpsAlertTests(unittest.TestCase):
    def test_notify_uses_group_and_does_not_include_untrusted_full_body(self):
        values = {
            'SMTP_HOST': 'smtp.example.test',
            'OPS_ALERT_TO': 'alerts@example.test',
            'SMTP_PORT': '587',
            'SMTP_FROM': 'noreply@example.test',
            'SMTP_USER': 'smtp-user',
            'SMTP_PASSWORD': 'smtp-secret',
        }
        with patch('app.ops_alerts.settings.get', side_effect=lambda key, default='': values.get(key, default)), patch('app.ops_alerts.smtplib.SMTP') as smtp:
            self.assertTrue(ops_alerts.notify('障害', '短い本文'))
            message = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
            self.assertEqual(message['To'], 'alerts@example.test')
            self.assertNotIn('smtp-secret', message.as_string())

    def test_health_notification_is_transition_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'health.json'
            ok = {'ok': True, 'checked_at': 1}
            bad = {'ok': False, 'checked_at': 2, 'checks': {'health': {'error': 'down'}}}
            with patch('scripts.monitor_health.ops_alerts.notify', return_value=True) as notify:
                monitor_health.notify_on_transition(ok, state)
                monitor_health.notify_on_transition(ok, state)
                monitor_health.notify_on_transition(bad, state)
            self.assertEqual(notify.call_count, 2)
            self.assertFalse(json.loads(state.read_text())['ok'])


if __name__ == '__main__':
    unittest.main()
