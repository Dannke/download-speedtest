"""Измеряет скорость скачивания: 10 последовательных запросов к одному URL."""
import http.client
import sys
import time
import urllib.request

REQUESTS = 10
CHUNK = 64 * 1024


def fetch(url):
    """Скачивает ответ целиком, возвращает (время запроса, время скачивания тела, байты)."""
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "User-Agent": "speedtest/1.0"})
    start = time.perf_counter()
    size = 0
    with urllib.request.urlopen(req, timeout=60) as resp:
        # заголовки получены: DNS, соединение, TLS и ожидание сервера уже позади
        body_start = time.perf_counter()
        while chunk := resp.read(CHUNK):
            size += len(chunk)
        # read(amt) при обрыве молча отдаёт неполные данные, поэтому сверяем с Content-Length
        expected = resp.headers.get("Content-Length")
        if expected and expected.isdigit() and size != int(expected):
            raise ConnectionError(f"соединение оборвалось: получено {size} из {expected} байт")
    end = time.perf_counter()
    return end - start, end - body_start, size


def measure(url, n=REQUESTS):
    """Возвращает (список успешных (время, время тела, байты), число ошибок)."""
    ok, failed = [], 0
    for i in range(1, n + 1):
        try:
            sec, body_sec, size = fetch(url)
        except (OSError, http.client.HTTPException) as e:  # URLError/HTTPError/таймаут — подклассы OSError
            failed += 1
            print(f"#{i:>2}: ошибка: {e}")
            continue
        ok.append((sec, body_sec, size))
        print(f"#{i:>2}: {size / 1e6:8.2f} MB за {sec:6.3f} с")
    return ok, failed


def main():
    if len(sys.argv) != 2 or not sys.argv[1].startswith(("http://", "https://")):
        sys.exit("Использование: python speedtest.py <http(s)://адрес>")
    ok, failed = measure(sys.argv[1])
    if not ok:
        sys.exit(f"\nВсе {failed} запросов завершились ошибкой")
    total = sum(size for _, _, size in ok)
    body_time = sum(body_sec for _, body_sec, _ in ok)
    speed = total / body_time / 1e6 if body_time else 0.0
    print(f"\nУспешных запросов:     {len(ok)} из {len(ok) + failed}")
    print(f"Среднее время запроса: {sum(sec for sec, _, _ in ok) / len(ok):.3f} с")
    print(f"Всего скачано:         {total / 1e6:.2f} MB")
    print(f"Скорость скачивания:   {speed:.2f} MB/s ({speed * 8:.2f} Mbit/s)")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
