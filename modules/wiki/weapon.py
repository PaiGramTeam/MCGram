from typing import List, Dict, Optional

from modules.wiki.base import WikiModel
from modules.wiki.models.weapon import EncoreWeapon


class Weapon(WikiModel):
    weapon_url = WikiModel.BASE_URL + "weapon.json"
    weapon_path = WikiModel.BASE_PATH / "weapon.json"

    def __init__(self):
        super().__init__()
        self.all_weapons: List[EncoreWeapon] = []
        self.all_weapons_map: Dict[int, EncoreWeapon] = {}
        self.all_weapons_name: Dict[str, EncoreWeapon] = {}

    def clear_class_data(self) -> None:
        self.all_weapons.clear()
        self.all_weapons_map.clear()
        self.all_weapons_name.clear()

    async def refresh(self):
        datas = await self.remote_get(self.weapon_url)
        await self.dump(datas.json(), self.weapon_path)
        await self.read()

    async def read(self):
        if not self.weapon_path.exists():
            await self.refresh()
            return
        datas = await WikiModel.read(self.weapon_path)
        self.clear_class_data()
        for data in datas:
            m = EncoreWeapon(**data)
            self.all_weapons.append(m)
            self.all_weapons_map[m.id] = m
            self.all_weapons_name[m.name] = m

    def get_by_id(self, cid: int) -> Optional[EncoreWeapon]:
        return self.all_weapons_map.get(cid)

    def get_by_name(self, name: str) -> Optional[EncoreWeapon]:
        return self.all_weapons_name.get(name)

    def get_name_list(self) -> List[str]:
        return list(self.all_weapons_name.keys())
