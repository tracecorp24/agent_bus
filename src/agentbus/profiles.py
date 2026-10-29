"""Repo profilleri (G5).

Test komutları, paylaşılan klasörler (junction: node_modules, venv),
kopyalanacak ortam dosyaları ve serialize_files tanımlarını yönetir.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any
import yaml


@dataclass
class RepoProfile:
    name: str
    setup_commands: List[str] = field(default_factory=list)
    junction_dirs: List[str] = field(default_factory=list)  # node_modules, .venv vb.
    copy_files: List[str] = field(default_factory=list)     # .env.example -> .env vb.
    test_command: Optional[str] = None
    serialize_files: List[str] = field(default_factory=list) # VERSION, package.json vb.


# KOVAN için hazır profil (G5)
KOVAN_PROFILE = RepoProfile(
    name="kovan",
    setup_commands=[],
    junction_dirs=["frontend/node_modules", "backend/.venv"],
    copy_files=[],
    test_command="python -m pytest backend/tests",
    serialize_files=["backend/app/VERSION", "frontend/package.json"]
)

DEFAULT_PROFILE = RepoProfile(
    name="default",
    setup_commands=[],
    junction_dirs=[],
    copy_files=[],
    test_command=None,
    serialize_files=[]
)


def load_profile(profile_path: Optional[Path] = None, profile_name: str = "default") -> RepoProfile:
    """YAML dosyasından veya hazır tanımlardan repo profilini yükler."""
    if profile_path and profile_path.exists():
        try:
            data = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
            return RepoProfile(
                name=data.get("name", profile_name),
                setup_commands=data.get("setup_commands", []),
                junction_dirs=data.get("junction_dirs", []),
                copy_files=data.get("copy_files", []),
                test_command=data.get("test_command"),
                serialize_files=data.get("serialize_files", []),
            )
        except Exception:
            pass

    if profile_name == "kovan":
        return KOVAN_PROFILE
    return DEFAULT_PROFILE
