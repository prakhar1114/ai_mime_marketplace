from pathlib import Path
from scripts.add_to_marketplace import parse_frontmatter
fields, _ = parse_frontmatter(Path("skills/order-grocery-on-blinkit/SKILL.md"))
print(fields)
