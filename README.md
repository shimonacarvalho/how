<p align="center">
  <img src="./screenshot.png" alt="How-CLI" />
</p>
 <h1 align="center">How-CLI</h1>
    <p align="center">A Terminal-Based Assistant for Generating Shell Commands</p>

**How-CLI** is a terminal-based assistant that generates precise shell commands for any task you ask. It works with **DeepSeek** or **OpenRouter** (any model they offer), providing context-aware, executable shell commands tailored to your current environment.

---

## Features

- Generate **exact shell commands** based on your current working directory, OS, and available tools.
- **Interactive TUI onboarding**: a friendly terminal UI walks you through picking a provider and API key.
- **Live model picker**: fetches the provider's model list and lets you filter/select one from a list.
- Context-aware: considers **files, git repositories, shell type**, and installed tools.
- **Command history** logging for easy reference.
- Clipboard support: copies generated commands automatically.
- Typewriter effect for visually appealing output (optional).
- Handles API errors, content blocks, and timeouts gracefully.

---

### ⚠️ Disclaimer:

```
Yeah, I know... It’s an API wrapper.
I know it's not the next Warp AI terminal or some fancy LLM-based shell integration with auto-completion and context persistence...
I know it's “yet another CLI tool”
and yes, I'm painfully aware that wrapping an API and printing stuff in the terminal isn't groundbreaking computer science...
But here's the thing: I made How-CLI because it was fun and quick to build...
It's not meant to change the world. It’s meant to make typing "how to do X in bash" a little more amusing..
Think of it as a weekend hack.
```

## Installation

```bash
pip install how-cli-assist
```

## Quick Start

The first time you run `how`, it **onboards you** with a TUI: pick a provider, paste your API key, then choose a model from the live list. Configuration is saved to `~/.config/how-cli/config.json`.

```bash
# Onboard / switch provider at any time
how --setup

# Examples:
how to create a Python virtual environment
> python -m venv env

how to list all files modified in the last 7 days
> find . -type f -mtime -7

# Show your previous questions and commands
how --history
```

### Supported providers

| Provider | Default model |
| --- | --- |
| DeepSeek | `deepseek-chat` |
| OpenRouter | `deepseek/deepseek-chat` |

Models are fetched from each provider's `/models` endpoint, so any model they expose can be selected.

## Options

`--setup` : Connect or replace an API provider (interactive TUI onboarding).

`--provider [name]` : Choose a provider (`deepseek`, `openrouter`). Without a name, opens a picker.

`--model [name]` : Set the model. Without a name, opens the interactive model picker.

`--api-key <key>` : Set and save the API key for the active provider.

`--base-url <url>` : Override the OpenAI-compatible base URL.

`--config` : Show the current provider configuration (API key masked).

`--silent` : Suppress spinner and typewriter effect.

`--type` : Show output with typewriter effect.

`--history` : Display previous questions and generated commands.

`--help` : Show help message and exit.

## Environment variables

Useful for scripting and non-interactive sessions:

- `HOW_PROVIDER` — provider name (defaults to `deepseek`)
- `HOW_BASE_URL` — OpenAI-compatible base URL
- `HOW_MODEL` — model name
- `HOW_API_KEY` — API key (also read from each provider's standard env var, e.g. `DEEPSEEK_API_KEY`, `OPENROUTER_API_KEY`)
- `XDG_CONFIG_HOME` — config location (defaults to `~/.config`)

```bash
HOW_MODEL=deepseek-chat DEEPSEEK_API_KEY=sk-... how "untar a .tar.gz"
```

## Configuration file

Stored at `~/.config/how-cli/config.json` (created with `600` permissions):

```json
{
  "provider": "deepseek",
  "base_url": "https://api.deepseek.com/v1",
  "model": "deepseek-chat",
  "api_key": "sk-..."
}
```

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
