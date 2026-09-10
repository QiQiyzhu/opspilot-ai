import time
import httpx

if __name__ == "__main__":
    for _ in range(120):
        try:
            if httpx.get("http://127.0.0.1:8003/api/health", timeout=2).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(1)
    else:
        raise SystemExit("API did not become healthy within 120 seconds")
