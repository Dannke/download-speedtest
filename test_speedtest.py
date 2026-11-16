import http.server
import threading
import unittest

import speedtest

PAYLOAD = b"x" * 300_000


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(PAYLOAD)))
        self.end_headers()
        self.wfile.write(PAYLOAD)

    def log_message(self, format, *args):  # noqa: A002 — сигнатура базового класса
        pass


class MeasureTest(unittest.TestCase):
    def test_ten_full_downloads(self):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            times, total = speedtest.measure(f"http://127.0.0.1:{server.server_port}/")
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(len(times), 10)
        self.assertEqual(total, 10 * len(PAYLOAD))
        self.assertTrue(all(t > 0 for t in times))


if __name__ == "__main__":
    unittest.main()
