import http.server
import threading
import unittest

import speedtest

PAYLOAD = b"x" * 300_000


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        # /cut обещает больше байт, чем отдаёт, и закрывает соединение — обрыв посреди тела
        extra = 100 if self.path == "/cut" else 0
        self.send_header("Content-Length", str(len(PAYLOAD) + extra))
        self.end_headers()
        self.wfile.write(PAYLOAD)

    def log_message(self, format, *args):  # noqa: A002 — сигнатура базового класса
        pass


class MeasureTest(unittest.TestCase):
    def setUp(self):
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_ten_full_downloads(self):
        ok, failed = speedtest.measure(self.base + "/")
        self.assertEqual((len(ok), failed), (10, 0))
        self.assertEqual(sum(size for *_, size in ok), 10 * len(PAYLOAD))
        self.assertTrue(all(sec >= body_sec > 0 for sec, body_sec, _ in ok))

    def test_broken_connection_is_counted_not_raised(self):
        ok, failed = speedtest.measure(self.base + "/cut")
        self.assertEqual((len(ok), failed), (0, 10))


if __name__ == "__main__":
    unittest.main()
