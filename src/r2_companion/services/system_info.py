import psutil


class SystemInfo:
    def __init__(self, source=psutil):
        self.source = source
        self.primed = False

    def prime(self) -> None:
        self.source.cpu_percent(interval=None)
        self.primed = True

    def sample(self, battery: bool = False) -> dict:
        result = {"cpu": None, "ram": None}
        try:
            value = self.source.cpu_percent(interval=None)
            if self.primed:
                result["cpu"] = value
            self.primed = True
        except (OSError, psutil.Error):
            pass
        try:
            result["ram"] = self.source.virtual_memory().percent
        except (OSError, psutil.Error):
            pass
        if battery:
            try:
                value = self.source.sensors_battery()
                result["battery"] = None if value is None else value.percent
            except (OSError, psutil.Error, NotImplementedError):
                result["battery"] = None
        return result
