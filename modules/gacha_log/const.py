from kuronet.models.mc.wish import MCBannerType

PAIMONMOE_VERSION = 3
UIMF_VERSION = "v1.0"


GACHA_TYPE_LIST = {
    MCBannerType.WEAPON: "武器祈愿",
    MCBannerType.CHARACTER: "角色祈愿",
    MCBannerType.STANDARD: "常驻祈愿",
    MCBannerType.STANDARD_WEAPON: "常驻武器祈愿",
    MCBannerType.TEMPORARY_SELF: "新手祈愿",
    MCBannerType.TEMPORARY_GIFT: "新手祈愿",
    MCBannerType.TEMPORARY: "新手祈愿",
}
GACHA_TYPE_LIST_REVERSE = {v: k for k, v in GACHA_TYPE_LIST.items()}
