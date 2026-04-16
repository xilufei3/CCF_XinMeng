import hashlib


def hash_device_id(device_id: str, salt: str) -> str:
    raw = f"{salt}:{device_id}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_thread_id(device_id_hash: str, process_id: str) -> str:
    return f"{device_id_hash}:{process_id}"
