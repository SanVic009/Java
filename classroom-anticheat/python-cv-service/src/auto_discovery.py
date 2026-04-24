"""Legacy compatibility stub."""

from typing import Dict


class LegacyDiscovery:
    """No-op placeholder kept for repository compatibility."""

    def update(self, tracks) -> bool:
        _ = tracks
        return True

    def get_mapping(self) -> Dict[int, int]:
        return {}
