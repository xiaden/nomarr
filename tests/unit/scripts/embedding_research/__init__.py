from pathlib import Path
from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)
__path__.append(str(Path(__file__).resolve().parents[4] / "scripts" / "embedding_research"))
