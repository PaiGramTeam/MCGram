import base64
import datetime
import urllib.parse
import json
from dataclasses import dataclass
from typing import List, Dict
import hmac
from hashlib import sha1
import uuid


@dataclass
class EncryptedData:
    word: List[int]
    sigBytes: int


PUBLIC_PARAMS = {
    "SignatureMethod": "HMAC-SHA1",
    "SignatureVersion": "1.0",
    "Format": "JSON",
    "Version": "2017-03-21",
    "AccessKeyId": "",
    "Timestamp": "",
    "SignatureNonce": "",
}

PRIVATE_PARAMS = {
    "Action": "GetPlayInfo",
    "AuthTimeout": "7200",
    "Definition": "FD,LD,SD,HD",
    "PlayConfig": "{}",
    "ReAuthInfo": "{}",
    "AuthInfo": "",
    "SecurityToken": "",
    "VideoId": "",
}


def authkey_to_encrypt_data(key: str) -> dict:
    return json.loads(stringify(authKeyToEncryptData(key)))


def get_query_str(playAuth: dict) -> str:
    publicParam = {
        **PUBLIC_PARAMS,
        "AccessKeyId": playAuth["AccessKeyId"],
        "Timestamp": generateTimestamp(),
        "SignatureNonce": generateRandom(),
    }
    privateParam = {
        **PRIVATE_PARAMS,
        "AuthInfo": playAuth["AuthInfo"],
        "SecurityToken": playAuth["SecurityToken"],
        "VideoId": playAuth["VideoMeta"]["VideoId"],
    }
    allParams = getAllParams(publicParam, privateParam)
    cqs = getQueryStr(allParams)

    stringToSign = "GET" + "&" + percentEncode("/") + "&" + percentEncode(cqs)
    signature = hmacSHA1Signature(playAuth["AccessKeySecret"], stringToSign)
    return cqs + "&Signature=" + signature


def stringify(data: EncryptedData):
    temp = data.word
    ret = b""
    for i in range(0, data.sigBytes):
        ret += (temp[i >> 2] >> 24 - i % 4 * 8 & 255).to_bytes(1, byteorder="big")
    return ret


def authKeyToEncryptData(key: str) -> EncryptedData:
    keylen = len(key)
    table = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
    r = [0 for _ in range(256)]
    for i in range(len(table)):
        r[ord(table[i])] = i
    char_code = table[64]

    cIdx = key.find(char_code)
    if -1 != cIdx:
        keylen = cIdx

    result = [0 for _ in range(keylen * 2)]
    i = 0
    for j in range(0, keylen):
        if j % 4 != 0:
            a = r[ord(key[j - 1])] << j % 4 * 2
            s = r[ord(key[j])] >> 6 - j % 4 * 2
            result[i >> 2] |= (a | s) << 24 - i % 4 * 8
            i += 1

    return EncryptedData(result, i if i > 0 else len(result) * 4)


def percentEncode(val):
    try:
        urlencode_orignstr = urllib.parse.quote(val, safe="", encoding=None, errors=None)
        plus_replaced = urlencode_orignstr.replace("+", "%20")
        star_replaced = plus_replaced.replace("*", "%2A")
        wave_replaced = star_replaced.replace("%7E", "~")
        return wave_replaced
    except Exception as ex:
        print(ex)
    return val


def getAllParams(publicParams: Dict[str, str], privateParams: Dict[str, str]):
    encodeParams = list()
    if publicParams:
        for key in publicParams.keys():
            value = publicParams.get(key)
            encodeKey = percentEncode(key)
            encodeVal = percentEncode(value)
            encodeParams.append(encodeKey + "=" + encodeVal)
    if privateParams:
        for key in privateParams.keys():
            value = privateParams.get(key)
            encodeKey = percentEncode(key)
            encodeVal = percentEncode(value)
            encodeParams.append(encodeKey + "=" + encodeVal)
    return encodeParams


def getQueryStr(allParams: List[str]) -> str:
    allParams.sort()
    cqString = str()
    for index, params in enumerate(allParams):
        cqString += params
        if index != len(allParams) - 1:
            cqString += "&"
    return cqString


def hmacSHA1Signature(accessKeySecret, stringToSign) -> str:
    """
    对 code 进行 hmac 签名并且进行 base64 编码
    """
    hash_sha1 = hmac.new((accessKeySecret + "&").encode("utf8"), stringToSign.encode("utf8"), sha1)
    ret = base64.encodebytes(hash_sha1.digest())[:-1]
    return ret.decode("utf8")


def generateTimestamp():
    time_format_str = datetime.datetime.utcnow().isoformat()
    time_format_str = time_format_str.split(".")[0] + "Z"
    return time_format_str


def generateRandom():
    return str(uuid.uuid4())
