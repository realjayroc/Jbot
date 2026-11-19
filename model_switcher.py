"""Interactive provider/model status and hot-swap utility."""
import argparse
import json
import time
from omni_router import OmniRouter, RouterError


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect providers and change J-Bot's primary model")
    parser.add_argument("--ping", action="store_true")
    args = parser.parse_args()
    router = OmniRouter()
    config = router._config()
    choices = []
    print("Configured providers:")
    for number, (provider, info) in enumerate(router.providers_status().items(), 1):
        print(f"{number}. {provider}: configured={info['configured']} health={info['ok']} latency={info['latency_ms']} ms")
        for model in info["models"]:
            print(f"   - {model}")
            choices.append((provider, model))
    primary = config.get("primary", {})
    print(f"\nPrimary: {primary.get('provider')} / {primary.get('model')}")
    if args.ping:
        print("\nLive provider checks:")
        for provider, model in choices:
            try:
                result = router.dispatch("Reply with the single word OK.", override_provider=provider, override_model=model)
                print(f"PASS {provider}/{model}: {result['latency_ms']} ms")
            except (RouterError, ValueError) as exc:
                print(f"FAIL {provider}/{model}: {exc}")
        return 0
    if not choices:
        return 1
    print("\nSelect a primary model by number (Enter to cancel):")
    for number, (provider, model) in enumerate(choices, 1):
        print(f"{number}. {provider} / {model}")
    selection = input("> ").strip()
    if not selection:
        return 0
    try:
        provider, model = choices[int(selection) - 1]
        print("Primary updated:", json.dumps(router.hot_swap_primary(provider, model)))
    except (ValueError, IndexError):
        print("Invalid selection.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
