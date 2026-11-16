"""Измеряет скорость скачивания: прогрев + 10 последовательных запросов к одному URL по одному соединению."""
import http.client
import statistics
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit

REQUESTS = 10
CHUNK = 64 * 1024
TIMEOUT = 60
MAX_REDIRECTS = 5
MAX_RETRIES = 3
RETRY_BASE = 1.0  # с; без Retry-After пауза перед повтором растёт как 1, 2, 4
MAX_WAIT = 60
# ponytail: http.client не читает HTTP(S)_PROXY, через прокси скрипт не ходит; понадобится — добавить conn.set_tunnel
HEADERS = {"Cache-Control": "no-cache", "User-Agent": "speedtest/1.0"}


class HTTPStatusError(http.client.HTTPException):
    def __init__(self, status, reason, retry_after):
        super().__init__(f"HTTP {status} {reason}")
        self.status, self.retry_after = status, retry_after


def is_http_url(url):
    try:
        parts = urlsplit(url)
        parts.port  # бросает ValueError на кривом порте
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def fetch(conns, url):
    """Один GET с редиректами по постоянным соединениям conns. Возвращает (время запроса, время тела, байты)."""
    start = time.perf_counter()
    for _ in range(MAX_REDIRECTS + 1):
        if not is_http_url(url):
            raise http.client.HTTPException(f"неподдерживаемый адрес: {url}")
        parts = urlsplit(url)
        conn = conns.get(parts[:2])
        if conn is None:
            cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
            conn = conns[parts[:2]] = cls(parts.hostname, parts.port, timeout=TIMEOUT)
        try:
            conn.request("GET", (parts.path or "/") + (f"?{parts.query}" if parts.query else ""), headers=HEADERS)
            resp = conn.getresponse()
            # заголовки получены: DNS, соединение, TLS и ожидание сервера уже позади
            body_start = time.perf_counter()
            if 300 <= resp.status < 400 and resp.getheader("Location"):
                resp.read()
                url = urljoin(url, resp.getheader("Location"))
                continue
            if not 200 <= resp.status < 300:
                raise HTTPStatusError(resp.status, resp.reason, resp.getheader("Retry-After"))
            size = 0
            while chunk := resp.read(CHUNK):
                size += len(chunk)
            # read(amt) при обрыве молча отдаёт неполные данные, поэтому сверяем с Content-Length
            expected = resp.getheader("Content-Length")
            if expected and expected.isdigit() and size != int(expected):
                raise ConnectionResetError(f"соединение оборвалось: получено {size} из {expected} байт")
        except Exception:
            conn.close()  # соединение в неизвестном состоянии: следующий запрос откроет новое
            raise
        end = time.perf_counter()
        return end - start, end - body_start, size
    raise http.client.HTTPException(f"больше {MAX_REDIRECTS} редиректов")


def retry_delay(retry_after, attempt):
    """Пауза перед повтором: из Retry-After (секунды или HTTP-дата), иначе экспоненциальная."""
    if retry_after:
        if retry_after.strip().isdigit():
            return min(int(retry_after), MAX_WAIT)
        try:
            wait = (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds()
            return min(max(wait, 0), MAX_WAIT)
        except (TypeError, ValueError):
            pass
    return RETRY_BASE * 2 ** attempt


def fetch_with_retries(conns, url):
    """fetch с повторами на 429/503 и на обрыв соединения."""
    for attempt in range(MAX_RETRIES):
        try:
            return fetch(conns, url)
        except HTTPStatusError as e:
            if e.status not in (429, 503):
                raise
            delay, reason = retry_delay(e.retry_after, attempt), e
        except (ConnectionError, http.client.IncompleteRead) as e:
            # обрыв: моргнула сеть или сервер закрыл keep-alive; отказ в подключении повторять бессмысленно
            if isinstance(e, ConnectionRefusedError):
                raise
            delay, reason = retry_delay(None, attempt), e
        print(f"         повтор через {delay:.1f} с: {reason}")
        time.sleep(delay)
    return fetch(conns, url)  # последняя попытка: ошибка уходит наверх


def measure(url, n=REQUESTS):
    """Прогрев + n запросов. Возвращает (успешные (время, время тела, байты), число ошибок); прогрев не учитывается."""
    conns, ok, failed = {}, [], 0
    try:
        for i in range(n + 1):
            label = f"#{i:>2}" if i else "прогрев"
            try:
                sec, body_sec, size = fetch_with_retries(conns, url)
            except (OSError, http.client.HTTPException) as e:  # таймаут и ошибки сокета — подклассы OSError
                if i:
                    failed += 1
                print(f"{label:>7}: ошибка: {e}")
                continue
            if i:
                ok.append((sec, body_sec, size))
            print(f"{label:>7}: {size / 1e6:8.2f} MB за {sec:6.3f} с" + ("" if i else "  (не учитывается)"))
    finally:
        for conn in conns.values():
            conn.close()
    return ok, failed


def stats_row(name, values):
    spread = statistics.stdev(values) if len(values) > 1 else 0.0
    cols = (statistics.mean(values), statistics.median(values), min(values), max(values), spread)
    return f"{name:<16}" + "".join(f"{v:>9.3f}" for v in cols)


def main():
    if len(sys.argv) != 2 or not is_http_url(sys.argv[1]):
        sys.exit("Использование: python speedtest.py <http(s)://адрес>")
    ok, failed = measure(sys.argv[1])
    if not ok:
        sys.exit(f"\nВсе {failed} запросов завершились ошибкой")
    total = sum(size for _, _, size in ok)
    body_time = sum(body_sec for _, body_sec, _ in ok)
    speed = total / body_time / 1e6 if body_time else 0.0
    speeds = [size / body_sec / 1e6 for _, body_sec, size in ok if body_sec > 0]

    print(f"\nУспешных запросов: {len(ok)} из {len(ok) + failed}\n")
    print(" " * 16 + "".join(f"{h:>9}" for h in ("среднее", "медиана", "мин", "макс", "ст.откл")))
    print(stats_row("Время запроса, с", [sec for sec, _, _ in ok]))
    if speeds:
        print(stats_row("Скорость, MB/s", speeds))
    print(f"\nСреднее время запроса: {sum(sec for sec, _, _ in ok) / len(ok):.3f} с")
    print(f"Всего скачано:         {total / 1e6:.2f} MB")
    print(f"Скорость скачивания:   {speed:.2f} MB/s ({speed * 8:.2f} Mbit/s)")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
