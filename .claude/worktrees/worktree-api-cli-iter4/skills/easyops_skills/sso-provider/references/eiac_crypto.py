# coding=utf-8
import hashlib
import base64
import logging
from Crypto.Cipher import DES3
from utils.tools import b2s


def generate_digest(str_to_be_digest):
    sha1 = hashlib.sha1()  # 调用sha1加密
    sha1.update(str_to_be_digest.encode('utf-8'))
    output = sha1.digest()
    return base64.b64encode(output)


def encrypt(str_to_encrypted, hex_key, byte_iv):
    if byte_iv == "":
        byte_iv = b'\x01\x02\x03\x04\x05\x06\x07\x08'
    BS = 8
    pad = lambda s: s + (BS - len(s) % BS) * chr(BS - len(s) % BS).encode()
    unpad = lambda s: s[0:-ord(s[-1])]

    # text也需要encode成bytearray
    plaintext = pad(str_to_encrypted.encode())
    str_key = hex_key.decode("hex")
    # 使用MODE_CBC创建cipher
    cipher = DES3.new(str_key, DES3.MODE_CBC, byte_iv)
    result = cipher.encrypt(plaintext)
    # base64 encode
    result = base64.b64encode(result)
    return str(result).replace('\n', '')


def create_authenticator(IASID, time_stamp, return_url, IAS_key, byte_iv):
    original_authenticator = IASID + str(time_stamp) + return_url
    try:
        authenticator_digest = generate_digest(original_authenticator)
        str_to_encrypted = authenticator_digest + original_authenticator
        strencrypted = encrypt(str_to_encrypted, IAS_key, byte_iv)
    except Exception as e:
        logging.error("create authenticator error: %s" % b2s(e.message))
        raise Exception("create authenticator error: %s" % b2s(e.message))
    return strencrypted


def validate_authenticator(IASID, tims_stamp, user_account, result, error_description, IAS_key, authenticator, byte_iv):
    original_authenticator = IASID + str(tims_stamp) + user_account + str(result) + error_description
    try:
        authenticator_digest = generate_digest(original_authenticator)
        str_to_encrypted = authenticator_digest + original_authenticator
        new_authenticator = encrypt(str_to_encrypted, IAS_key, byte_iv)
    except Exception as e:
        logging.error("validate authenticator error: %s" % b2s(e.message))
        return False
    return new_authenticator == authenticator


