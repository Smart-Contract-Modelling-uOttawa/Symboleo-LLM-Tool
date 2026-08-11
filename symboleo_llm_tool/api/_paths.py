from pathlib import Path

# Under configs/app/ rather than beside the run configs: everything else in
# configs/ is a pipeline config a user hands to --config, and this is the one
# file the *deployment* owns. Kept inside configs/ so the Docker read-only
# mount covers it unchanged.
UI_CONFIG_PATH = Path("configs/app/ui_config.yaml")
FRONTEND_DIST = Path("frontend/dist")
