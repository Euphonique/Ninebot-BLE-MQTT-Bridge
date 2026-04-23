"""Ninebot BLE crypto implementation (Python port of NinebotCrypto)."""

import hashlib
import struct
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

FW_DATA = bytes([0x97, 0xCF, 0xB8, 0x02, 0x84, 0x41, 0x43, 0xDE,
                 0x56, 0x00, 0x2B, 0x3B, 0x34, 0x78, 0x0A, 0x5D])


class NinebotCrypto:
    def __init__(self, device_name: str):
        self.name_data = device_name.encode('ascii').ljust(16, b'\x00')[:16]
        self.ble_data = bytes(16)
        self.app_data = bytes(16)
        self.sha1_key = bytes(16)
        self.msg_it = 0

        self._calc_sha1_key(self.name_data, FW_DATA)

    def _aes_ecb_encrypt(self, data: bytes, key: bytes) -> bytes:
        cipher = Cipher(algorithms.AES(key), modes.ECB())
        enc = cipher.encryptor()
        return enc.update(data) + enc.finalize()

    def _calc_sha1_key(self, key1: bytes, key2: bytes):
        sha_data = key1[:16].ljust(16, b'\x00') + key2[:16].ljust(16, b'\x00')
        sha_hash = hashlib.sha1(sha_data).digest()
        self.sha1_key = sha_hash[:16]

    def _crypto_first(self, src: bytes) -> bytes:
        aes_key = self._aes_ecb_encrypt(FW_DATA, self.sha1_key)
        dst = bytearray(len(src))
        idx = 0
        remaining = len(src)
        while remaining > 0:
            chunk = min(remaining, 16)
            for i in range(chunk):
                dst[idx + i] = src[idx + i] ^ aes_key[i]
            remaining -= chunk
            idx += chunk
        return bytes(dst)

    def _crypto_next(self, src: bytes, msg_it: int) -> bytes:
        aes_enc_data = bytearray(16)
        aes_enc_data[0] = 1
        aes_enc_data[1] = (msg_it >> 24) & 0xFF
        aes_enc_data[2] = (msg_it >> 16) & 0xFF
        aes_enc_data[3] = (msg_it >> 8) & 0xFF
        aes_enc_data[4] = msg_it & 0xFF
        aes_enc_data[5:13] = self.ble_data[0:8]

        dst = bytearray(len(src))
        idx = 0
        remaining = len(src)
        while remaining > 0:
            aes_enc_data[15] += 1
            aes_key = self._aes_ecb_encrypt(bytes(aes_enc_data), self.sha1_key)
            chunk = min(remaining, 16)
            for i in range(chunk):
                dst[idx + i] = src[idx + i] ^ aes_key[i]
            remaining -= chunk
            idx += chunk
        return bytes(dst)

    def _calc_crc_first(self, src: bytes) -> int:
        s = sum(src) & 0xFFFF
        return s ^ 0xFFFF

    def _calc_crc_next(self, full_src: bytes, msg_it: int) -> bytes:
        aes_enc_data = bytearray(16)
        aes_enc_data[0] = 0x59
        aes_enc_data[1] = (msg_it >> 24) & 0xFF
        aes_enc_data[2] = (msg_it >> 16) & 0xFF
        aes_enc_data[3] = (msg_it >> 8) & 0xFF
        aes_enc_data[4] = msg_it & 0xFF
        aes_enc_data[5:13] = self.ble_data[0:8]
        payload_len = len(full_src) - 3
        aes_enc_data[13] = (payload_len >> 16) & 0xFF
        aes_enc_data[14] = (payload_len >> 8) & 0xFF
        aes_enc_data[15] = payload_len & 0xFF

        aes_key = self._aes_ecb_encrypt(bytes(aes_enc_data), self.sha1_key)

        xor_data = bytearray(16)
        xor_data[0:3] = full_src[0:3]
        xor_data = bytes(a ^ b for a, b in zip(xor_data, aes_key))
        aes_key = self._aes_ecb_encrypt(xor_data, self.sha1_key)

        remaining = payload_len
        idx = 3
        while remaining > 0:
            chunk = min(remaining, 16)
            xor_data = bytearray(16)
            xor_data[0:chunk] = full_src[idx:idx + chunk]
            xor_data = bytes(a ^ b for a, b in zip(xor_data, aes_key))
            aes_key = self._aes_ecb_encrypt(xor_data, self.sha1_key)
            remaining -= chunk
            idx += chunk

        aes_enc_data[0] = 1
        aes_enc_data[15] = 0
        aes_key2 = self._aes_ecb_encrypt(bytes(aes_enc_data), self.sha1_key)

        crc = bytes(a ^ b for a, b in zip(aes_key2[:4], aes_key[:4]))
        return crc

    def encrypt(self, src: bytes) -> bytes:
        header = src[0:3]
        payload = src[3:]

        if self.msg_it == 0:
            crc = self._calc_crc_first(payload)
            encrypted_payload = self._crypto_first(payload)
            self.msg_it += 1
            result = header + encrypted_payload + bytes(2) + struct.pack("<H", crc) + bytes(2)
            return result
        else:
            self.msg_it += 1
            crc = self._calc_crc_next(src, self.msg_it)
            encrypted_payload = self._crypto_next(payload, self.msg_it)
            counter_bytes = bytes([(self.msg_it >> 8) & 0xFF, self.msg_it & 0xFF])
            result = header + encrypted_payload + crc + counter_bytes
            return result

    def decrypt(self, src: bytes) -> bytes:
        header = src[0:3]

        new_msg_it = self.msg_it
        if (new_msg_it & 0x8000) > 0 and (src[-2] >> 7) == 0:
            new_msg_it += 0x10000
        new_msg_it = (new_msg_it & 0xFFFF0000) + (src[-2] << 8) + src[-1]

        payload_len = len(src) - 9

        if new_msg_it == 0:
            decrypted = self._crypto_first(src[3:3 + payload_len])
            result = header + decrypted

            # Check for PRE_COMM response: 5A A5 1E 21 3E 5B
            if (result[0:3] == bytes([0x5A, 0xA5, 0x1E]) and
                    len(result) > 6 and result[3] == 0x21 and
                    result[4] == 0x3E and result[5] == 0x5B):
                self.ble_data = result[7:23]
                self._calc_sha1_key(self.name_data, self.ble_data)
        else:
            decrypted = self._crypto_next(src[3:3 + payload_len], new_msg_it)
            result = header + decrypted

            # Check for SET_PWD accepted: 5A A5 00 21 3E 5C 01
            if (len(result) >= 7 and result[3] == 0x21 and
                    result[4] == 0x3E and result[5] == 0x5C and
                    result[6] == 0x01):
                self._calc_sha1_key(self.app_data, self.ble_data)

            self.msg_it = new_msg_it

        return result

    def set_app_data(self, data: bytes):
        self.app_data = data[:16].ljust(16, b'\x00')
