# Trade Bot v2.0

## Overview
This project provides a simple cryptocurrency trading bot that interacts with Binance for trade execution and Telegram for notifications. The bot periodically checks market prices, screens recent news headlines for sentiment, and opens or closes positions based on a few rules. Trade history, open positions and balances are persisted locally in JSON files and an SQLite database stores recent price data.

## Required environment variables
Set the following variables in a `.env` file or your shell environment before running the bot:

- `TELEGRAM_TOKEN` – Telegram bot token used for sending notifications.
- `TELEGRAM_CHAT_ID` – chat or channel ID where messages will be delivered.
- `BINANCE_API_KEY` – API key for your Binance account.
- `BINANCE_SECRET_KEY` – corresponding Binance API secret.
- `NEWSAPI_KEY` – API key for [NewsAPI](https://newsapi.org/) to fetch headlines.

Export or define these variables in a file named `.env` in the project root so they can be loaded automatically.

## Installation
1. Clone this repository.
2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Provide the environment variables listed above.

## Running the bot
Execute the main script:
```bash
python main.py
```
The bot will start fetching prices and news, place orders (or simulate them) and send status updates to Telegram approximately every five minutes.

## Key configuration
Several constants in `main.py` control the bot's behaviour:

| Constant | Description |
|----------|-------------|
| `LIVE_MODE` | When `True`, real orders are submitted to Binance. Set to `False` to only simulate trades. |
| `START_BALANCE` | Starting USDT balance for tracking performance. |
| `DAILY_MAX_INVEST` | Maximum amount of USDT that can be invested each day. By default this is 20% of `START_BALANCE`. |
| `POSITION_FILE` | JSON file where open positions are stored. |
| `BALANCE_FILE` | JSON file used to persist current balance. |
| `TRADE_LOG_FILE` | JSON file logging all trades executed by the bot. |
| `TRADING_PAIRS` | List of trading pairs (e.g. `BTCUSDT`, `ETHUSDT`) that the bot will monitor and trade. |

Adjust these values in `main.py` as needed for your strategy.

## Disclaimer
This bot is for educational purposes only. Use at your own risk and consider running in simulation mode (`LIVE_MODE = False`) before trading with real funds.
