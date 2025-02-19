import requests

class TelegramNotifier:
    """
    A class to send notifications to a Telegram bot.
    """
    def __init__(self, bot_token, chat_id):
        """
        Initialize the TelegramNotifier with the bot token and chat ID.

        :param bot_token: str, the token of the Telegram bot.
        :param chat_id: str, the chat ID where notifications will be sent.
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

    def send_message(self, message):
        """
        Send a message to the Telegram chat.

        :param message: str, the message to send.
        """
        try:
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "Markdown"
            }
            response = requests.post(self.base_url, json=payload)
            if response.status_code == 200:
                print("✅ Telegram notification sent successfully.")
            else:
                print(f"⚠️ Failed to send Telegram notification: {response.text}")
        except Exception as e:
            print(f"⚠️ Error sending Telegram notification: {e}")

if __name__ == "__main__":
    # Replace these with your actual bot token and chat ID
    BOT_TOKEN = ""
    CHAT_ID = ""

    # Create an instance of TelegramNotifier
    notifier = TelegramNotifier(BOT_TOKEN, CHAT_ID)

    # Send a test message
    test_message = "Hello, this is a test notification from the TelegramNotifier class!"
    notifier.send_message(test_message)