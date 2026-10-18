"""企业微信回调加解密与验签工具模块。

严格按照企业微信开放平台加解密算法实现：
- AES-256-CBC 加解密（PKCS#7 填充）
- SHA1 签名比对与生成
"""
from __future__ import annotations

import base64
import hashlib
import struct
from typing import Tuple

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class WeComCryptoError(Exception):
    pass


def verify_signature(token: str, timestamp: str, nonce: str, encrypt: str, msg_signature: str) -> bool:
    """验证企业微信回调请求签名。"""
    if not (token and timestamp and nonce and encrypt and msg_signature):
        return False
    items = sorted([token, str(timestamp), str(nonce), str(encrypt)])
    calc = hashlib.sha1("".join(items).encode("utf-8")).hexdigest()
    return calc.lower() == msg_signature.lower()


def decrypt_message(aes_key: str, encrypt_b64: str) -> Tuple[str, str]:
    """解密企业微信报文。

    返回: (明文文本, receive_id)
    """
    try:
        key_bytes = base64.b64decode(aes_key + "=")
    except Exception as exc:
        raise WeComCryptoError(f"无效的 EncodingAESKey: {exc}") from exc

    try:
        cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(key_bytes[:16]))
        decryptor = cipher.decryptor()
        raw = decryptor.update(base64.b64decode(encrypt_b64)) + decryptor.finalize()
    except Exception as exc:
        raise WeComCryptoError(f"AES 解密失败: {exc}") from exc

    # 去除 PKCS#7 补位
    pad_len = raw[-1]
    if pad_len < 1 or pad_len > 32:
        raise WeComCryptoError("无效的 PKCS#7 填充")
    content = raw[:-pad_len]

    # 16字节随机串 + 4字节明文长度 + 明文 + receive_id
    if len(content) < 20:
        raise WeComCryptoError("解密内容长度不足")

    msg_len = struct.unpack("!I", content[16:20])[0]
    msg = content[20:20 + msg_len].decode("utf-8", errors="replace")
    receive_id = content[20 + msg_len:].decode("utf-8", errors="replace")
    return msg, receive_id


def encrypt_message(aes_key: str, plain_text: str, receive_id: str) -> str:
    """加密明文，返回 Base64 编码的密文。"""
    key_bytes = base64.b64decode(aes_key + "=")
    plain_bytes = plain_text.encode("utf-8")
    rec_bytes = receive_id.encode("utf-8")
    random_bytes = b"0123456789abcdef"  # 16字节随机串

    buf = random_bytes + struct.pack("!I", len(plain_bytes)) + plain_bytes + rec_bytes
    pad_len = 32 - (len(buf) % 32)
    if pad_len == 0:
        pad_len = 32
    buf += bytes([pad_len] * pad_len)

    cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(key_bytes[:16]))
    encryptor = cipher.encryptor()
    encrypted = encryptor.update(buf) + encryptor.finalize()
    return base64.b64encode(encrypted).decode("utf-8")
