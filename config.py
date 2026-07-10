from pathlib import Path
import yaml

def load_db_config(config_path: str | Path) -> dict:
    """Loads the database configuration from a YAML file."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found at: {path}")
        
    with open(path, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)