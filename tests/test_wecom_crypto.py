import base64
import hashlib
import time
import unittest

import wecom_crypto


class TestWeComCrypto(unittest.TestCase):
    def setUp(self):
        # 43位标准 AES Key 与 Token
        self.aes_key = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
        self.token = "my_secret_token_123"
        self.corpid = "wx1234567890abcdef"

    def test_encrypt_and_decrypt(self):
        plain = "<xml><Content>测试消息-AllinSSL</Content></xml>"
        encrypted = wecom_crypto.encrypt_message(self.aes_key, plain, self.corpid)
        decrypted_msg, rec_id = wecom_crypto.decrypt_message(self.aes_key, encrypted)
        self.assertEqual(decrypted_msg, plain)
        self.assertEqual(rec_id, self.corpid)

    def test_verify_signature(self):
        timestamp = str(int(time.time()))
        nonce = "987654321"
        encrypt = "dummy_encrypted_string"
        items = sorted([self.token, timestamp, nonce, encrypt])
        sig = hashlib.sha1("".join(items).encode("utf-8")).hexdigest()

        self.assertTrue(wecom_crypto.verify_signature(self.token, timestamp, nonce, encrypt, sig))
        self.assertFalse(wecom_crypto.verify_signature("wrong_token", timestamp, nonce, encrypt, sig))


if __name__ == "__main__":
    unittest.main()
