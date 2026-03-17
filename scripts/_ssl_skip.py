"""可选跳过 SSL 校验：仅当 GUIHUA_SKIP_SSL_VERIFY=1 时生效，用于本地跑 release suite 时证书链不完整。"""

import os
import ssl
import urllib.request


def maybe_disable_ssl_verify():
    if os.environ.get("GUIHUA_SKIP_SSL_VERIFY") != "1":
        return
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    handler = urllib.request.HTTPSHandler(context=ctx)
    urllib.request.install_opener(urllib.request.build_opener(handler))


def https_handler_for_opener():
    """返回用于 build_opener 的 HTTPSHandler（当 skip 时用不校验的 context）。"""
    if os.environ.get("GUIHUA_SKIP_SSL_VERIFY") != "1":
        return urllib.request.HTTPSHandler()
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return urllib.request.HTTPSHandler(context=ctx)
