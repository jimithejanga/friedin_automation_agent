import asyncio
import signal
import sys
import structlog

from app.config import get_settings
from app.platform.telemetry import setup_telemetry


logger = structlog.get_logger("cmr.worker")


class CMRWorker:
    def __init__(self):
        self.is_running = True

    def stop(self, *args):
        logger.info("worker_shutdown_signal_received")
        self.is_running = False

    async def run(self):
        setup_telemetry()
        settings = get_settings()
        logger.info(
            "cmr_worker_started",
            app_name=settings.APP_NAME,
            environment=settings.ENVIRONMENT,
            redis_url=settings.REDIS_URL,
        )

        # Register signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.stop)
            except NotImplementedError:
                # Windows fallback
                signal.signal(sig, self.stop)

        while self.is_running:
            await asyncio.sleep(1)

        logger.info("cmr_worker_stopped_cleanly")


def main():
    worker = CMRWorker()
    try:
        asyncio.run(worker.run())
    except (KeyboardInterrupt, SystemExit):
        logger.info("cmr_worker_exited")


if __name__ == "__main__":
    main()
