from abc import ABC, abstractmethod

DISCLAIMER = "Bu sistem yatırım tavsiyesi değildir.\nKarar-destek ve paper trading amaçlıdır."


class Notifier(ABC):
    @abstractmethod
    async def send(self, message: str) -> bool: ...


class MockTelegramNotifier(Notifier):
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send(self, message: str) -> bool:
        self.messages.append(f"{message}\n\n{DISCLAIMER}\nPaper Trading Mode")
        return True
