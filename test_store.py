
import concurrent.futures
import requests

BASE_URL = "http://127.0.0.1:8080"


def put_value(i):
    response = requests.post(
        f"{BASE_URL}/shared",
        json={"value": i},
        timeout=10,
    )
    response.raise_for_status()
    return response.status_code


def get_value():
    response = requests.get(
        f"{BASE_URL}/shared",
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
    results = list(executor.map(put_value, range(100)))

print("Successful PUT requests:", len(results))
print("Final value:", get_value())
