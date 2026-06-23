"""Symboleo LLM Tool package.

Pin LiteLLM's model-metadata source to the bundled (package-versioned) copy.
By default LiteLLM fetches ``model_prices_and_context_window.json`` from GitHub
``main`` over HTTP at import time, which makes model/param compatibility data
non-deterministic (it depends on network availability and whatever upstream
``main`` holds at startup). Our drop/warn behavior depends on that data, so we
pin it for reproducibility and offline safety; refreshing the model list is then
an explicit ``litellm`` version bump.

This must run here: the package root is the earliest guaranteed execution point
ahead of any ``import litellm`` (LiteLLM reads this env var once, at import). A
``.env`` line would load too late for the CLI, which imports litellm before
``load_dotenv()`` runs. ``setdefault`` preserves an explicit override — set
``LITELLM_LOCAL_MODEL_COST_MAP=False`` (a real OS env var) to opt back into the
live remote fetch.
"""

import os

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
