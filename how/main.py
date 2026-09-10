import sys
import os
import json
import threading
import time
import getpass
import platform
import shutil
import itertools
import logging
import concurrent.futures
import datetime
import requests
import pyperclip
import psutil
import questionary
from prompt_toolkit.styles import Style

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

CONFIG_DIR = os.path.join(os.getenv("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "how-cli")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
HISTORY_FILE = os.path.join(CONFIG_DIR, "history.log")
LEGACY_CONFIG_DIR = os.path.expanduser("~/.how-cli")
LEGACY_CONFIG_FILE = os.path.join(LEGACY_CONFIG_DIR, "config.json")
LEGACY_KEY_FILE = os.path.join(CONFIG_DIR, ".google_api_key")
LEGACY_KEY_FILE_OLD = os.path.join(LEGACY_CONFIG_DIR, ".google_api_key")

PROVIDERS = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "envs": ["DEEPSEEK_API_KEY"],
        "signup": "https://platform.deepseek.com/api_keys",
    },
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "deepseek/deepseek-chat",
        "envs": ["OPENROUTER_API_KEY"],
        "signup": "https://openrouter.ai/keys",
        "extra_headers": {
            "HTTP-Referer": "https://github.com/Ademking/how",
            "X-Title": "How-CLI",
        },
    },
}

DEFAULT_PROVIDER = "deepseek"
DEFAULT_TIMEOUT = 30

HOW_STYLE = Style.from_dict({
    "qmark": "fg:#2f6fb3 bold",
    "question": "bold",
    "answer": "fg:#2e8b57 bold",
    "pointer": "fg:#2f6fb3 bold",
    "highlighted": "reverse",
    "selected": "fg:#2e8b57",
    "separator": "fg:#888888",
    "instruction": "fg:#888888 italic",
    "text": "",
    "disabled": "fg:#888888 italic",
    "completion-menu.completion": "bg:#1a1b26 fg:#c0caf5",
    "completion-menu.completion.current": "bg:#2f6fb3 fg:#ffffff bold",
    "completion-menu.meta.completion": "bg:#1a1b26 fg:#888888",
    "completion-menu.meta.completion.current": "bg:#2f6fb3 fg:#ffffff",
    "scrollbar.background": "bg:#1a1b26",
    "scrollbar.button": "bg:#888888",
})


class ApiError(Exception): pass
class AuthError(ApiError): pass
class ContentError(ApiError): pass
class ApiTimeoutError(ApiError): pass


def header():
    print(
        "   __             \n"
        "  / /  ___ _    __\n"
        " / _ \\/ _ \\ |/|/ /\n"
        "/_//_/\\___/__,__/ \n"
    )
    print("Ask me how to do anything in your terminal!")


def clean_response(text: str) -> str:
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        first_line = text.split("\n", 1)[0]
        text = text[len(first_line):-3].strip() if len(first_line) > 3 else text[3:-3].strip()
    elif text.startswith("`") and text.endswith("`"):
        text = text[1:-1].strip()
    return text.strip()


def spinner(stop_event, message="Generating"):
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    for frame in itertools.cycle(frames):
        if stop_event.is_set():
            break
        sys.stdout.write(f"\r{frame} {message}")
        sys.stdout.flush()
        time.sleep(0.1)
    sys.stdout.write("\r" + " " * (len(message) + 2) + "\r")
    sys.stdout.flush()


def log_history(question: str, commands: list):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{timestamp}] Q: {question}\nCommands:\n")
            f.writelines(f"{cmd}\n" for cmd in commands)
            f.write("\n")
    except OSError as e:
        logger.warning(f"Failed to write history: {e}")


def show_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                print(f.read())
        except OSError as e:
            print(f"Error reading history file: {e}")
    else:
        print("No history found.")


def get_installed_tools() -> str:
    tools = [t for t in ["git", "npm", "node", "python", "docker", "pip", "go", "rustc", "cargo", "java", "mvn", "gradle"] if shutil.which(t)]
    return ", ".join(tools)


def get_current_terminal() -> str:
    try:
        parent_pid = os.getppid()
        parent_process = psutil.Process(parent_pid)
        return parent_process.name()
    except Exception:
        return "Unknown"


def load_config() -> dict:
    candidates = [CONFIG_FILE, LEGACY_CONFIG_FILE]
    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"Could not read config file {path}: {e}")
    for path in (LEGACY_KEY_FILE, LEGACY_KEY_FILE_OLD):
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                key = f.read().strip()
            if key:
                provider = PROVIDERS[DEFAULT_PROVIDER]
                return {
                    "provider": DEFAULT_PROVIDER,
                    "base_url": provider["base_url"],
                    "model": provider["model"],
                    "api_key": key,
                }
        except OSError as e:
            logger.warning(f"Could not read legacy key file {path}: {e}")
    return {}


def save_config(config: dict):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass


def env_api_key(provider_name: str):
    for name in PROVIDERS.get(provider_name, {}).get("envs", []):
        value = os.getenv(name)
        if value:
            return value
    return None


def config_from_env() -> dict:
    provider_name = os.getenv("HOW_PROVIDER", DEFAULT_PROVIDER)
    provider = PROVIDERS.get(provider_name, PROVIDERS[DEFAULT_PROVIDER])
    base_url = os.getenv("HOW_BASE_URL") or provider["base_url"]
    model = os.getenv("HOW_MODEL") or provider["model"]
    api_key = os.getenv("HOW_API_KEY") or env_api_key(provider_name)
    if not (base_url and model and api_key):
        return {}
    return {
        "provider": provider_name,
        "base_url": base_url,
        "model": model,
        "api_key": api_key,
        "extra_headers": provider.get("extra_headers"),
    }


def apply_provider_defaults(config: dict) -> dict:
    provider = PROVIDERS.get(config.get("provider", DEFAULT_PROVIDER), PROVIDERS[DEFAULT_PROVIDER])
    config.setdefault("base_url", provider["base_url"])
    config.setdefault("model", provider["model"])
    if provider.get("extra_headers") and not config.get("extra_headers"):
        config["extra_headers"] = provider["extra_headers"]
    return config


def request_headers(config: dict) -> dict:
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }
    headers.update(config.get("extra_headers") or {})
    return headers


def fetch_models(config: dict, timeout: int = DEFAULT_TIMEOUT) -> list:
    url = config["base_url"].rstrip("/") + "/models"
    headers = request_headers(config)
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
    except requests.exceptions.Timeout:
        raise ApiTimeoutError("Timed out while fetching models.")
    except requests.exceptions.RequestException as e:
        raise ApiError(f"{e} ({type(e).__name__})") from e

    if response.status_code in (401, 403):
        raise AuthError("Invalid API key or insufficient permissions.")
    if response.status_code >= 400:
        detail = ""
        try:
            body = response.json()
            detail = body.get("error", body) if isinstance(body, dict) else body
            if isinstance(detail, dict):
                detail = detail.get("message", detail)
        except ValueError:
            detail = response.text[:200]
        raise ApiError(f"Could not list models ({response.status_code}): {detail}")

    try:
        body = response.json()
    except ValueError as e:
        raise ApiError("Model list was not valid JSON.") from e

    raw = body.get("data") if isinstance(body, dict) else None
    if raw is None and isinstance(body, dict):
        raw = body.get("models")
    if not isinstance(raw, list):
        raise ApiError("Unexpected model list format.")

    models = []
    for item in raw:
        if isinstance(item, dict) and item.get("id"):
            models.append({"id": str(item["id"]), "name": str(item.get("name") or item["id"])})
        elif isinstance(item, str):
            models.append({"id": item, "name": item})

    deduped = {m["id"]: m for m in models}
    return sorted(deduped.values(), key=lambda m: m["id"].lower())


def verify_connection(config: dict, timeout: int = DEFAULT_TIMEOUT):
    try:
        generate_response(config, "Reply with the single word: OK", silent=True, max_retries=1, timeout=timeout)
        return True, ""
    except ApiError as e:
        return False, str(e)


def ask(question):
    answer = question.ask()
    if answer is None:
        raise AuthError("Setup cancelled.")
    return answer


def choose_provider() -> str:
    choices = [questionary.Choice(title=p["label"], value=name) for name, p in PROVIDERS.items()]
    return ask(questionary.select("Choose a provider", choices=choices, default=DEFAULT_PROVIDER, style=HOW_STYLE, instruction="(↑/↓ to move, enter to select)"))


def choose_model(provider_name: str, config: dict, models: list = None) -> str:
    provider = PROVIDERS.get(provider_name, PROVIDERS[DEFAULT_PROVIDER])
    default = provider["model"]

    if models is None:
        print("Fetching available models...")
        try:
            models = fetch_models(config)
        except ApiError as e:
            print(f"⚠ Could not fetch models: {e}")
            models = []

    if models:
        ids = [m["id"] for m in models]
        if default in ids:
            ids = [default] + [i for i in ids if i != default]

        return ask(questionary.autocomplete(
            f"Select a model — {len(ids)} available (type to filter)",
            choices=ids,
            default=default if default in ids else ids[0],
            match_middle=True,
            ignore_case=True,
            style=HOW_STYLE,
            validate=lambda text: True if text in ids else "Pick a model from the list (type to filter)",
        ))

    print("⚠ No model list available; enter the model name manually.")
    return ask(questionary.text("Model name", default=default, style=HOW_STYLE))


def onboard(reason: str = "") -> dict:
    if not sys.stdin.isatty():
        raise AuthError(
            "No provider configured and running non-interactively. "
            "Run `how --setup` in a terminal, or set HOW_API_KEY/HOW_BASE_URL/HOW_MODEL."
        )

    print()
    if reason:
        print(reason)
    print("Let's connect an API provider. It only takes a moment.\n")

    provider_name = choose_provider()
    provider = PROVIDERS[provider_name]
    if provider.get("signup"):
        print(f"Get an API key at: {provider['signup']}\n")

    while True:
        api_key = ask(questionary.password("Paste your API key (hidden)", style=HOW_STYLE))
        if not api_key:
            print("⚠ API key cannot be empty.")
            continue

        config = apply_provider_defaults({
            "provider": provider_name,
            "base_url": provider["base_url"],
            "api_key": api_key,
        })

        try:
            models = fetch_models(config)
        except AuthError as e:
            print(f"✗ {e}")
            if ask(questionary.confirm("Re-enter the API key?", default=True, style=HOW_STYLE)):
                continue
            raise AuthError(str(e))
        except ApiError as e:
            print(f"⚠ Could not fetch models: {e}")
            models = []

        config["model"] = choose_model(provider_name, config, models)

        print("Testing the connection...")
        ok, message = verify_connection(config)
        if ok:
            print("✓ Connection successful.")
            break

        print(f"⚠ Connection test failed: {message}")
        if ask(questionary.confirm("Re-enter the API key?", default=True, style=HOW_STYLE)):
            continue
        if ask(questionary.confirm("Save this configuration anyway?", default=False, style=HOW_STYLE)):
            break
        raise AuthError("Setup cancelled.")

    save_config(config)
    print(f"✓ Saved provider '{provider_name}' with model '{config['model']}' to {CONFIG_FILE}")
    return config


def build_config(opts: dict) -> dict:
    config = load_config()
    present = opts.get("_present", set())

    if "--provider" in present:
        provider_name = opts.get("provider") or ask(questionary.select(
            "Choose a provider",
            choices=[questionary.Choice(title=p["label"], value=name) for name, p in PROVIDERS.items()],
            default=config.get("provider", DEFAULT_PROVIDER),
            style=HOW_STYLE,
            instruction="(↑/↓ to move, enter to select)",
        ))
        if provider_name not in PROVIDERS:
            raise AuthError(f"Unknown provider '{provider_name}'. Options: {', '.join(PROVIDERS)}")
        config = dict(config)
        config["provider"] = provider_name
        config["base_url"] = PROVIDERS[provider_name]["base_url"]
        config.pop("model", None)

    if opts.get("base_url"):
        config = dict(config)
        config["base_url"] = opts["base_url"]
    if opts.get("api_key"):
        config = dict(config)
        config["api_key"] = opts["api_key"]
    if opts.get("model"):
        config = dict(config)
        config["model"] = opts["model"]

    if not config:
        config = config_from_env()

    if config:
        config = apply_provider_defaults(config)

    needs_model = "--model" in present and not opts.get("model")
    if config and (not config.get("model") or needs_model):
        if not sys.stdin.isatty():
            raise AuthError("Model not configured. Run `how --setup` or pass --model <name>.")
        provider_name = config.get("provider", DEFAULT_PROVIDER)
        config["model"] = choose_model(provider_name, config)

    if not config or not config.get("base_url") or not config.get("model") or not config.get("api_key"):
        config = onboard("No API provider is configured yet." if not config else "")

    if config and (present & {"--provider", "--model", "--api-key", "--base-url"}):
        try:
            save_config(config)
        except OSError as e:
            logger.warning(f"Could not save config: {e}")

    return config


def generate_response(config: dict, prompt: str, silent: bool = False, max_retries: int = 3, timeout: int = DEFAULT_TIMEOUT) -> str:
    url = config["base_url"].rstrip("/") + "/chat/completions"
    headers = request_headers(config)
    payload = {
        "model": config["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "stream": False,
    }

    stop_event = threading.Event()
    spinner_thread = None
    if not silent:
        spinner_thread = threading.Thread(target=spinner, args=(stop_event,), daemon=True)
        spinner_thread.start()

    try:
        for attempt in range(max_retries):
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=timeout)
                if response.status_code in (401, 403):
                    raise AuthError("Invalid API key or insufficient permissions.")
                if response.status_code == 404:
                    raise ApiError(f"Model '{config['model']}' or endpoint not found at {url}.")
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt == max_retries - 1:
                        raise ApiError("Rate limit exceeded." if response.status_code == 429 else f"Provider error {response.status_code}.")
                    time.sleep((2 ** attempt) + 1)
                    continue
                if response.status_code >= 400:
                    detail = ""
                    try:
                        body = response.json()
                        detail = body.get("error", body) if isinstance(body, dict) else body
                        if isinstance(detail, dict):
                            detail = detail.get("message", detail)
                    except ValueError:
                        detail = response.text[:200]
                    raise ApiError(f"API error {response.status_code}: {detail}")

                data = response.json()
                choices = data.get("choices") or []
                if not choices:
                    raise ContentError("Empty response from API.")
                text = (choices[0].get("message", {}).get("content") or "").strip()
                if not text:
                    raise ContentError("Empty response from API.")
                return text
            except requests.exceptions.Timeout:
                if attempt == max_retries - 1:
                    raise ApiTimeoutError("API request timed out.")
                time.sleep(2 ** attempt)
                continue
            except requests.exceptions.RequestException as e:
                msg = f"{e} ({type(e).__name__})"
                if "429" in msg or "resourceexhausted" in msg.lower():
                    if attempt == max_retries - 1:
                        raise ApiError("Rate limit exceeded.")
                    time.sleep((2 ** attempt) + 1)
                    continue
                raise ApiError(msg) from e
    finally:
        if not silent and spinner_thread:
            stop_event.set()
            spinner_thread.join()


def parse_args(argv):
    value_flags = {"--provider", "--model", "--api-key", "--base-url", "--timeout"}
    opts = {
        "silent": False,
        "type": False,
        "history": False,
        "help": False,
        "setup": False,
        "config": False,
        "_present": set(),
    }
    question_parts = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--help", "-h"):
            opts["help"] = True
        elif arg == "--silent":
            opts["silent"] = True
        elif arg == "--type":
            opts["type"] = True
        elif arg == "--history":
            opts["history"] = True
        elif arg == "--setup":
            opts["setup"] = True
        elif arg == "--config":
            opts["config"] = True
        elif arg in value_flags:
            key = arg.lstrip("-").replace("-", "_")
            opts["_present"].add(arg)
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                opts[key] = argv[i + 1]
                i += 1
            else:
                opts[key] = None
        else:
            question_parts.append(arg)
        i += 1
    opts["question"] = " ".join(question_parts).strip()
    return opts


def print_config(config: dict):
    if not config:
        print("No provider configured. Run `how --setup` to add one.")
        return
    key = config.get("api_key", "")
    masked = f"{key[:4]}...{key[-4:]}" if len(key) > 8 else "(set)"
    print(f"Provider: {config.get('provider', DEFAULT_PROVIDER)}")
    print(f"Base URL: {config.get('base_url')}")
    print(f"Model:    {config.get('model')}")
    print(f"API key:  {masked}")


def show_help():
    header()
    print("Usage: how <question> [options]\n")
    print("Options:")
    print("  --setup                    Connect/replace an API provider (onboarding)")
    print("  --provider [name]          Choose a provider (deepseek, openrouter)")
    print("  --model [name]             Pick or set the model (interactive if no name)")
    print("  --api-key <key>            Set/save the API key for the provider")
    print("  --base-url <url>           Override the OpenAI-compatible base URL")
    print("  --config                   Show the current provider configuration")
    print("  --silent                   Suppress spinner and typewriter effect")
    print("  --type                     Show output with typewriter effect")
    print("  --history                  Show command/question history")
    print("  --help                     Show this help message and exit")
    print(f"\nProviders: {', '.join(PROVIDERS)}")


def main():
    opts = parse_args(sys.argv[1:])

    if opts["help"]:
        show_help()
        sys.exit(0)
    if opts["history"]:
        show_history()
        sys.exit(0)
    if opts["config"]:
        print_config(load_config() or config_from_env())
        sys.exit(0)
    if opts["setup"]:
        try:
            onboard("Reconfiguring your API provider.")
        except AuthError as e:
            print(f"❌ Authentication Error: {e}")
            sys.exit(1)
        sys.exit(0)

    if not opts["question"]:
        show_help()
        sys.exit(1)

    try:
        config = build_config(opts)
    except AuthError as e:
        print(f"❌ Authentication Error: {e}")
        sys.exit(1)

    silent = opts["silent"]
    type_effect = opts["type"] and not silent

    try:
        timeout = int(opts["timeout"]) if opts.get("timeout") else DEFAULT_TIMEOUT
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT

    question = opts["question"]
    current_dir = os.getcwd()
    current_user = getpass.getuser()
    current_os = f"{platform.system()} {platform.release()}"
    try:
        files_list = os.listdir(current_dir)
        files = ", ".join(files_list[:20]) + ("..." if len(files_list) > 20 else "")
    except OSError:
        files = "Error listing files"
    git_repo = "Yes" if os.path.exists(os.path.join(current_dir, ".git")) else "No"
    tools = get_installed_tools()
    shell = get_current_terminal()

    prompt = f"""SYSTEM:
    You are an expert, concise shell assistant. Your goal is to provide accurate, executable shell commands.

    CONTEXT:
    -   **OS:** {current_os}
    -   **Shell:** {shell}
    -   **CWD:** {current_dir}
    -   **User:** {current_user}
    -   **Git Repo:** {git_repo}
    -   **Files (top 20):** {files}
    -   **Available Tools:** {tools}

    RULES:
    1.  **Primary Goal:** Generate *only* the exact, executable shell command(s) for the `{shell}` environment.
    2.  **Context is Key:** Use the CONTEXT (CWD, Files, OS) to write specific, correct commands.
    3.  **No Banter:** Do NOT include greetings, sign-offs, or conversational filler (e.g., "Here is the command:").
    4.  **Safety:** If a command is complex or destructive (e.g., `rm -rf`, `find -delete`), add a single-line comment (`# ...`) *after* the command explaining what it does.
    5.  **Questions:** If the user asks a question (e.g., "what is `ls`?"), provide a concise, one-line answer. Do not output a command.
    6.  **Ambiguity:** If the request is unclear, ask a single, direct clarifying question. Start the line with `#`.

    REQUEST:
    {question}

    RESPONSE:
    """

    try:
        text = generate_response(config, prompt, silent, timeout=timeout)
    except (AuthError, ContentError, ApiTimeoutError, ApiError) as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)

    raw_commands = clean_response(text)
    commands = [line.strip() for line in raw_commands.splitlines() if line.strip()]

    if not commands:
        print("⚠️ No valid commands generated.")
        sys.exit(1)
    full_command = "\n".join(commands)

    if type_effect:
        for c in full_command:
            sys.stdout.write(c)
            sys.stdout.flush()
            time.sleep(0.01)
        print()
    else:
        print(full_command)

    try:
        pyperclip.copy(full_command)
    except pyperclip.PyperclipException as e:
        logger.warning(f"Clipboard copy failed: {e}")

    log_history(question, commands)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 Interrupted.")
        sys.exit(130)
    except Exception as e:
        print(f"\n💥 Unexpected error: {type(e).__name__}: {e}")
        logger.exception("Unexpected error")
        sys.exit(1)
