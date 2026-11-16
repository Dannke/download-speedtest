"""Измеряет скорость скачивания: 10 последовательных запросов к одному URL."""
import sys
import time
import urllib.error
import urllib.request

REQUESTS = 10
CHUNK = 64 * 1024


def fetch(url):
    """Скачивает ответ целиком, возвращает (секунды, байты)."""
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "User-Agent": "speedtest/1.0"})
    start = time.perf_counter()
    size = 0
    with urllib.request.urlopen(req, timeout=60) as resp:
        while chunk := resp.read(CHUNK):
            size += len(chunk)
    return time.perf_counter() - start, size


def measure(url, n=REQUESTS):
    times, total = [], 0
    for i in range(1, n + 1):
        sec, size = fetch(url)
        times.append(sec)
        total += size
        print(f"#{i:>2}: {size / 1e6:8.2f} MB за {sec:6.3f} с")
    return times, total


def main():
    if len(sys.argv) != 2 or not sys.argv[1].startswith(("http://", "https://")):
        sys.exit("Использование: python speedtest.py <http(s)://адрес>")
    try:
        times, total = measure(sys.argv[1])
    except (urllib.error.URLError, OSError) as e:
        sys.exit(f"Ошибка запроса: {e}")
    elapsed = sum(times)
    speed = total / elapsed / 1e6 if elapsed else 0.0
    print(f"\nСреднее время запроса: {elapsed / len(times):.3f} с")
    print(f"Всего скачано:         {total / 1e6:.2f} MB")
    print(f"Скорость скачивания:   {speed:.2f} MB/s ({speed * 8:.2f} Mbit/s)")


if __name__ == "__main__":
    main()
