"""Personal mode must work without service credentials and never fall back."""
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from app import accounts, studio, local_runtime, membership, billing, gemini
from app.server import Handler

class LocalRuntimeTests(unittest.TestCase):
    def test_local_http_identity_ignores_stale_browser_cookie(self):
        request=SimpleNamespace(server=SimpleNamespace(local_mode=True,local_token='local-token'))
        with patch('app.server.accounts.authenticate',return_value={'id':'local-user'}) as authenticate:
            self.assertEqual(Handler.identity(request),{'id':'local-user'})
        authenticate.assert_called_once_with('local-token')

    def test_personal_identity_and_key_persist_without_service_credentials(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{'GEMINI_API_KEY':'operator-secret','STRIPE_MODE':'live','YOURSTORY_ALLOWED_EMAILS':'operator@example.test'}), patch.object(studio,'DATA',Path(tmp)/'studio'), patch.object(studio,'DB',Path(tmp)/'studio/studio.db'), patch.dict(membership.CONFIG):
            local_runtime.configure()
            self.assertEqual(os.environ['GEMINI_API_KEY'],'')
            self.assertFalse(billing.enabled())
            with self.assertRaises(ValueError):gemini.key()
            key=os.environ['BYOK_ENCRYPTION_KEY']
            studio.init()
            token=local_runtime.identity();user=accounts.authenticate(token)
            self.assertEqual(accounts.profile(user['id'])['provider'],'local')
            local_runtime.configure()
            self.assertEqual(key,os.environ['BYOK_ENCRYPTION_KEY'])
            token2=local_runtime.identity()
            self.assertEqual(user['id'],accounts.authenticate(token2)['id'])
            self.assertGreater(membership.CONFIG['free']['projects'],1)
