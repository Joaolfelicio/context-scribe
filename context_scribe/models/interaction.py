from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class Interaction:
    timestamp: datetime
    role: str  # "user" or "agent"
    content: str
    project_name: str = "global"
    metadata: Optional[dict] = None
