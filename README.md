# J-Bot Unlimited Model Routing

The dynamic model registry is `models_config.json`. Every dispatch reloads the file, so model changes take effect immediately. Multiple comma-separated API keys can be supplied through provider environment variables. Hosted providers fail over automatically, and Ollama is the local fallback.

Copy `.env.example` to `.env` and export the credentials in the process environment. Run `python model_switcher.py` to manage a primary model or `python model_switcher.py --ping` for live checks. Run `run_tests.bat` for the offline regression suite.
