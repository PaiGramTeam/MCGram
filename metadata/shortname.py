from __future__ import annotations

import functools
from typing import List

__all__ = [
    "roles",
    "traveler_roles",
    "weapons",
    "idToName",
    "roleToId",
    "roleToName",
    "weaponToName",
    "weaponToId",
    "elementToName",
    "elementsToColor",
    "not_real_roles",
    "roleToTag",
]

# noinspection SpellCheckingInspection
roles = {
    1102: ["散华", "sanhua"],
    1103: ["白芷", "baizhi"],
    1104: ["凌阳", "lingyang"],
    1105: ["折枝", "zhezi"],
    1106: ["釉瑚", "youhu"],
    1202: ["炽霞", "chixia"],
    1203: ["安可", "encore"],
    1204: ["莫特斐", "mortefi"],
    1205: ["长离", "changli"],
    1301: ["卡卡罗", "calcharo"],
    1302: ["吟霖", "yinlin"],
    1303: ["渊武", "yuanwu"],
    1304: ["今汐", "jinhsi"],
    1305: ["相里要", "xiangliyao"],
    1402: ["秧秧", "yangyang"],
    1403: ["秋水", "aalto"],
    1404: ["忌炎", "jiyan", "将军"],
    1405: ["鉴心", "jianxin"],
    1501: ["漂泊者·衍射", "roverspectro"],
    1502: ["漂泊者·衍射", "roverspectro"],
    1503: ["维里奈", "verina"],
    1504: ["灯灯", "lumi"],
    1505: ["守岸人", "shorekeeper"],
    1601: ["桃祈", "taoqi"],
    1602: ["丹瑾", "danjin"],
    1603: ["椿", "camellya"],
    1604: ["漂泊者·湮灭", "roverhavoc"],
    1605: ["漂泊者·湮灭", "roverhavoc"],
}
traveler_roles = [1501, 1502, 1604, 1605]
not_real_roles = []
weapons = {
    21010011: ["教学长刃"],
    21010012: ["原初长刃·朴石"],
    21010013: ["暗夜长刃·玄明"],
    21010015: ["浩境粼光"],
    21010016: ["苍鳞千嶂"],
    21010023: ["源能长刃·测壹"],
    21010024: ["异响空灵"],
    21010026: ["时和岁稔"],
    21010034: ["重破刃-41型"],
    21010043: ["远行者长刃·辟路"],
    21010044: ["永夜长明"],
    21010053: ["戍关长刃·定军"],
    21010064: ["东落"],
    21010074: ["纹秋"],
    21010084: ["凋亡频移"],
    21020011: ["教学迅刀"],
    21020012: ["原初迅刀·鸣雨"],
    21020013: ["暗夜迅刀·黑闪"],
    21020015: ["千古洑流"],
    21020016: ["赫奕流明"],
    21020017: ["心之锚"],
    21020023: ["源能迅刀·测贰"],
    21020024: ["行进序曲"],
    21020026: ["裁春"],
    21020034: ["瞬斩刀-18型"],
    21020043: ["远行者迅刀·旅迹"],
    21020044: ["不归孤军"],
    21020053: ["戍关迅刀·镇海"],
    21020064: ["西升"],
    21020074: ["飞景"],
    21020084: ["永续坍缩"],
    21030011: ["教学佩枪"],
    21030012: ["原初佩枪·穿林"],
    21030013: ["暗夜佩枪·暗星"],
    21030015: ["停驻之烟"],
    21030023: ["源能佩枪·测叁"],
    21030024: ["华彩乐段"],
    21030034: ["穿击枪-26型"],
    21030043: ["远行者佩枪·洞察"],
    21030044: ["无眠烈火"],
    21030053: ["戍关佩枪·平云"],
    21030064: ["飞逝"],
    21030074: ["奔雷"],
    21030084: ["悖论喷流"],
    21040011: ["教学臂铠"],
    21040012: ["原初臂铠·磐岩"],
    21040013: ["暗夜臂铠·夜芒"],
    21040015: ["擎渊怒涛"],
    21040016: ["诸方玄枢"],
    21040023: ["源能臂铠·测肆"],
    21040024: ["呼啸重音"],
    21040034: ["钢影拳-21丁型"],
    21040043: ["远行者臂铠·破障"],
    21040044: ["袍泽之固"],
    21040053: ["戍关臂铠·拔山"],
    21040064: ["骇行"],
    21040074: ["金掌"],
    21040084: ["尘云旋臂"],
    21050011: ["教学音感仪"],
    21050012: ["原初音感仪·听浪"],
    21050013: ["暗夜矩阵·暝光"],
    21050015: ["漪澜浮录"],
    21050016: ["掣傀之手"],
    21050023: ["源能音感仪·测五"],
    21050024: ["奇幻变奏"],
    21050026: ["琼枝冰绡"],
    21050034: ["鸣动仪-25型"],
    21050036: ["星序协响"],
    21050043: ["远行者矩阵·探幽"],
    21050044: ["今州守望"],
    21050053: ["戍关音感仪·留光"],
    21050064: ["异度"],
    21050074: ["清音"],
    21050084: ["核熔星盘"],
}
elements = {
    "pyro": ["火"],
    "hydro": ["水"],
    "anemo": ["风"],
    "cryo": ["冰"],
    "electro": ["雷"],
    "geo": ["岩"],
    "dendro": ["草"],
    "physical": ["物理"],
}
elementsToColor = {
    "anemo": "#65B89A",
    "geo": "#F6A824",
    "electro": "#9F79B5",
    "dendro": "#97C12B",
    "hydro": "#3FB6ED",
    "pyro": "#E76429",
    "cryo": "#8FCDDC",
    "physical": "#15161B",
}


@functools.lru_cache()
def elementToName(elem: str) -> str | None:
    """将元素昵称转为正式名"""
    elem = str.casefold(elem)  # 忽略大小写
    return elements[elem][0] if elem in elements else None


# noinspection PyPep8Naming
@functools.lru_cache()
def roleToName(shortname: str) -> str:
    """将角色昵称转为正式名"""
    shortname = str.casefold(shortname)  # 忽略大小写
    return next((value[0] for value in roles.values() for name in value if name == shortname), shortname)


# noinspection PyPep8Naming
@functools.lru_cache()
def roleToId(name: str) -> int | None:
    """获取角色ID"""
    name = str.casefold(name)
    return next((key for key, value in roles.items() for n in value if n == name), None)


# noinspection PyPep8Naming
@functools.lru_cache()
def idToName(cid: int) -> str | None:
    """从角色ID获取正式名"""
    return roles[cid][0] if cid in roles else None


# noinspection PyPep8Naming
@functools.lru_cache()
def weaponToName(shortname: str) -> str:
    """将武器昵称转为正式名"""
    shortname = str.casefold(shortname)  # 忽略大小写
    return next((value[0] for value in weapons.values() for name in value if name == shortname), shortname)


# noinspection PyPep8Naming
@functools.lru_cache()
def weaponToId(name: str) -> int | None:
    """获取武器ID"""
    name = str.casefold(name)
    return next((key for key, value in weapons.items() for n in value if n == name), None)


# noinspection PyPep8Naming
@functools.lru_cache()
def roleToTag(role_name: str) -> List[str]:
    """通过角色名获取TAG"""
    role_name = str.casefold(role_name)
    return next((value for value in roles.values() if value[0] == role_name), [role_name])
