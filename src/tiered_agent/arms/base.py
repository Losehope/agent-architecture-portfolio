from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class ArmResult:
    arm: str
    text: str
    sources: List[str] = field(default_factory=list)
    meta: Dict[str, object] = field(default_factory=dict)
