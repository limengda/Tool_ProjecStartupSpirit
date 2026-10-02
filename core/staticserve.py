# -*- coding: utf-8 -*-
"""内置静态服务器（docs/03 §3.8）。

精灵自己进程里的 http.server 线程，绑定 127.0.0.1（免防火墙弹窗），
服务 PWA/静态项目时不产生外部进程。
"""
from __future__ import annotations

import functools
import http.server
import os
import threading
from typing import Optional

from . import portman


class ServedDir:
    """一个已被托管的目录。"""

    def __init__(self, port: int, server: http.server.ThreadingHTTPServer,
                 thread: threading.Thread, path: str):
        self.port = port
        self.server = server
        self.thread = thread
        self.path = path
        self.url = "http://localhost:{}/".format(port)

    def stop(self) -> None:
        threading.Thread(target=self._shutdown, daemon=True).start()

    def _shutdown(self) -> None:
        try:
            self.server.shutdown()
            self.server.server_close()
        except OSError:
            pass


def serve_dir(path: str, port_hint: Optional[int] = None) -> ServedDir:
    """托管一个目录；port_hint 被占则顺延找空闲口。"""
    handler = functools.partial(
        _QuietHandler, directory=os.path.abspath(path))
    port = port_hint or 8765
    if portman.in_use(port):
        port = portman.find_free(port + 1)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    t = threading.Thread(target=server.serve_forever, daemon=True,
                         name="staticserve-{}".format(port))
    t.start()
    return ServedDir(port=port, server=server, thread=t, path=path)


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """不往控制台刷访问日志（精灵是 GUI 程序，stderr 无人看）。"""

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass
