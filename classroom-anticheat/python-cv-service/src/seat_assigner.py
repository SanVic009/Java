"""Legacy compatibility stub."""

from typing import Dict


class LegacyMapper:
    """No-op placeholder kept for repository compatibility."""

    def update(self, tracks) -> Dict[int, int]:
        _ = tracks
        return {}
