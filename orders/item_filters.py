import os


EXCLUDE_NON_WEAPON_ITEMS = os.getenv("EXCLUDE_NON_WEAPON_ITEMS", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}


def is_excluded_item_name(name: str) -> bool:
    normalized = name.strip()

    return (
        normalized.startswith("Sticker |")
        or normalized.startswith("Souvenir ")
        or normalized.startswith("Sealed Graffiti |")
        or normalized.startswith("Graffiti |")
        or normalized.startswith("*")
        or normalized.startswith("★")
        or normalized.endswith(" Case")
        or normalized.endswith(" Capsule")
    )


def should_parse_item(name: str) -> bool:
    if not EXCLUDE_NON_WEAPON_ITEMS:
        return True

    return not is_excluded_item_name(name)
