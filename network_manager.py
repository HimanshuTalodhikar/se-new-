import platform
from urllib.parse import urlparse, urlunparse

from config import settings


class NetworkManager:
    """Central camera URL resolver for native Linux/macOS, Windows Docker, and WSL2."""

    @staticmethod
    def _detected_os() -> str:
        if settings.host_os.lower() != "auto":
            return settings.host_os
        system = platform.system()
        if system == "Linux":
            try:
                version = open("/proc/version", "r", encoding="utf-8").read().lower()
                if "microsoft" in version or "wsl" in version:
                    return "Windows"
            except OSError:
                pass
        return system

    @staticmethod
    def _with_auth(camera_id: str, url: str) -> str:
        auth = settings.camera_auth.get(camera_id) or {}
        user = auth.get("username") or auth.get("user")
        password = auth.get("password")
        if not user or not password:
            return url

        parsed = urlparse(url)
        if "@" in parsed.netloc:
            return url
        return urlunparse(parsed._replace(netloc=f"{user}:{password}@{parsed.netloc}"))

    @staticmethod
    def get_camera_url(camera_id: str) -> str:
        raw_url = settings.cameras.get(camera_id)
        if not raw_url:
            raise KeyError(f"Unknown camera id: {camera_id}")

        raw_url = NetworkManager._with_auth(camera_id, raw_url)
        parsed = urlparse(raw_url)
        detected_os = NetworkManager._detected_os()

        # Windows/WSL2 Docker containers often need host.docker.internal for host-attached streams.
        if detected_os == "Windows" and settings.wsl_use_host_docker_internal:
            if parsed.hostname in {"localhost", "127.0.0.1", "0.0.0.0"}:
                port = f":{parsed.port}" if parsed.port else ""
                netloc = f"host.docker.internal{port}"
                if parsed.username:
                    password = f":{parsed.password}" if parsed.password else ""
                    netloc = f"{parsed.username}{password}@{netloc}"
                return urlunparse(parsed._replace(netloc=netloc))

        return raw_url

    @staticmethod
    def environment() -> dict[str, str]:
        return {"host_os": NetworkManager._detected_os(), "platform": platform.platform()}
