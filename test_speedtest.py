import http.server
import threading
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest import mock

import speedtest

PAYLOAD = b"x" * 300_000


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive, как у реальных серверов
    connections = 0
    hits = 0

    def setup(self):
        super().setup()
        Handler.connections += 1

    def do_GET(self):
        Handler.hits += 1
        if self.path == "/redirect":
            return self.reply(302, extra=(("Location", "/"),))
        if self.path == "/busy" and Handler.hits % 2:
            return self.reply(429, extra=(("Retry-After", "0"),))
        if self.path == "/cut":
            # обещает больше байт, чем отдаёт, и закрывает соединение — обрыв посреди тела
            self.close_connection = True
            return self.reply(200, PAYLOAD, length=len(PAYLOAD) + 100)
        self.reply(200, PAYLOAD)

    def reply(self, status, body=b"", extra=(), length=None):
        self.send_response(status)
        self.send_header("Content-Length", str(len(body) if length is None else length))
        for name, value in extra:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A002 — сигнатура базового класса
        pass


class MeasureTest(unittest.TestCase):
    def setUp(self):
        Handler.connections = Handler.hits = 0
        patcher = mock.patch.object(speedtest, "RETRY_BASE", 0)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_warmup_plus_ten_downloads_over_one_connection(self):
        ok, failed = speedtest.measure(self.base + "/")
        self.assertEqual((len(ok), failed), (10, 0))
        self.assertEqual(sum(size for *_, size in ok), 10 * len(PAYLOAD))
        self.assertTrue(all(sec >= body_sec > 0 for sec, body_sec, _ in ok))
        self.assertEqual((Handler.hits, Handler.connections), (11, 1))

    def test_redirect_is_followed(self):
        ok, failed = speedtest.measure(self.base + "/redirect")
        self.assertEqual((len(ok), failed), (10, 0))
        self.assertEqual((Handler.hits, Handler.connections), (22, 1))

    def test_429_is_retried(self):
        ok, failed = speedtest.measure(self.base + "/busy")
        self.assertEqual((len(ok), failed), (10, 0))
        self.assertEqual(Handler.hits, 22)

    def test_broken_connection_is_retried_then_counted(self):
        ok, failed = speedtest.measure(self.base + "/cut")
        self.assertEqual((len(ok), failed), (0, 10))
        self.assertEqual(Handler.hits, 11 * (speedtest.MAX_RETRIES + 1))


class RetryDelayTest(unittest.TestCase):
    def test_retry_after_forms(self):
        self.assertEqual(speedtest.retry_delay("5", 0), 5)
        self.assertEqual(speedtest.retry_delay("9999", 0), speedtest.MAX_WAIT)
        self.assertEqual(speedtest.retry_delay(None, 2), speedtest.RETRY_BASE * 4)
        self.assertEqual(speedtest.retry_delay("мусор", 0), speedtest.RETRY_BASE)
        in_10s = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=10), usegmt=True)
        self.assertAlmostEqual(speedtest.retry_delay(in_10s, 0), 10, delta=1.5)


if __name__ == "__main__":
    unittest.main()
