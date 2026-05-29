from drivers.interfaces.telegram.telegram_driver import TelegramDriver


def test_telegram_driver_send_response_accepts_model_info():
    driver = TelegramDriver.__new__(TelegramDriver)
    driver.bot = None

    # Should be a no-op with no bot, but must accept the extra metadata argument.
    driver.send_response("hello", target="telegram_123", model_info={"model": "gemini"})
