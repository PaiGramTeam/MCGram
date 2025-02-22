import datetime
from enum import Enum
from typing import Any, Dict, List, Union

from pydantic import field_validator, BaseModel

from metadata.shortname import not_real_roles, roleToId, weaponToId
from modules.gacha_log.const import UIMF_VERSION


class ImportType(Enum):
    PaiGram = "PaiGram"
    PAIMONMOE = "PAIMONMOE"
    FXQ = "FXQ"
    UIGF = "UIGF"
    UNKNOWN = "UNKNOWN"


class FiveStarItem(BaseModel):
    name: str
    icon: str
    count: int
    type: str
    isUp: bool
    isBig: bool
    time: datetime.datetime


class FourStarItem(BaseModel):
    name: str
    icon: str
    count: int
    type: str
    time: datetime.datetime


class GachaItem(BaseModel):
    id: str
    name: str
    gacha_type: str
    item_type: str
    rank_type: str
    time: datetime.datetime

    @field_validator("name")
    @classmethod
    def name_validator(cls, v):
        if item_id := (roleToId(v) or weaponToId(v)):
            if item_id not in not_real_roles:
                return v
        raise ValueError(f"Invalid name {v}")

    @field_validator("gacha_type")
    @classmethod
    def check_gacha_type(cls, v):
        if v not in {"1", "2", "3", "4", "5", "6", "7"}:
            raise ValueError(f"gacha_type must be 1, 2, 3, 4, 5, 6, 7, invalid value: {v}")
        return v

    @field_validator("item_type")
    @classmethod
    def check_item_type(cls, item):
        if item not in {"角色", "武器"}:
            raise ValueError(f"error item type {item}")
        return item

    @field_validator("rank_type")
    @classmethod
    def check_rank_type(cls, rank):
        if rank not in {"5", "4", "3"}:
            raise ValueError(f"error rank type {rank}")
        return rank


class GachaLogInfo(BaseModel):
    user_id: str
    uid: str
    update_time: datetime.datetime
    import_type: str = ""
    item_list: Dict[str, List[GachaItem]] = {
        "角色祈愿": [],
        "武器祈愿": [],
        "常驻祈愿": [],
        "常驻武器祈愿": [],
        "新手祈愿": [],
    }

    @property
    def get_import_type(self) -> ImportType:
        try:
            return ImportType(self.import_type)
        except ValueError:
            return ImportType.UNKNOWN


class Pool:
    def __init__(self, five: List[str], four: List[str], name: str, to: str, **kwargs):
        self.five = five
        self.real_name = name
        self.name = "、".join(self.five)
        self.four = four
        self.from_ = kwargs.get("from")
        self.to = to
        self.from_time = datetime.datetime.strptime(self.from_, "%Y-%m-%d %H:%M:%S")
        self.to_time = datetime.datetime.strptime(self.to, "%Y-%m-%d %H:%M:%S")
        self.start = self.from_time
        self.start_init = False
        self.end = self.to_time
        self.dict = {}
        self.count = 0

    def parse(self, item: Union[FiveStarItem, FourStarItem]):
        if self.from_time <= item.time <= self.to_time:
            if self.dict.get(item.name):
                self.dict[item.name]["count"] += 1
            else:
                self.dict[item.name] = {
                    "name": item.name,
                    "icon": item.icon,
                    "count": 1,
                    "rank_type": 5 if isinstance(item, FiveStarItem) else 4,
                }

    def count_item(self, item: List[GachaItem]):
        for i in item:
            if self.from_time <= i.time <= self.to_time:
                self.count += 1
                if not self.start_init:
                    self.start = i.time
                    self.start_init = True
                self.end = i.time

    def to_list(self):
        return list(self.dict.values())


class ItemType(Enum):
    CHARACTER = "角色"
    WEAPON = "武器"


class UIGFGachaType(Enum):
    BEGINNER = "5"
    BEGINNER1 = "6"
    BEGINNER2 = "7"
    STANDARD_WEAPON = "4"
    STANDARD = "3"
    CHARACTER = "1"
    WEAPON = "2"


class UIGFItem(BaseModel):
    id: str
    name: str
    count: str = "1"
    gacha_type: UIGFGachaType
    item_id: str = ""
    item_type: ItemType
    rank_type: str
    time: str
    uigf_gacha_type: UIGFGachaType


class UIGFInfo(BaseModel):
    uid: str = "0"
    lang: str = "zh-cn"
    export_time: str = ""
    export_timestamp: int = 0
    export_app: str = ""
    export_app_version: str = ""
    uigf_version: str = UIMF_VERSION
    region_time_zone: int = 8

    def __init__(self, **data: Any):
        data["region_time_zone"] = data.get("region_time_zone", UIGFInfo.get_region_time_zone(data.get("uid", "0")))
        super().__init__(**data)
        if not self.export_time:
            self.export_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.export_timestamp = int(datetime.datetime.now().timestamp())

    @staticmethod
    def get_region_time_zone(uid: str) -> int:
        if uid.startswith("6"):
            return -5
        if uid.startswith("7"):
            return 1
        return 8


class UIGFModel(BaseModel):
    info: UIGFInfo
    list: List[UIGFItem]
