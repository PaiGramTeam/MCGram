from typing import List, Dict, Optional

from modules.wiki.base import WikiModel
from modules.wiki.models.character import EncoreAvatar


class Character(WikiModel):
    avatar_url = WikiModel.BASE_URL + "character.json"
    avatar_path = WikiModel.BASE_PATH / "character.json"

    def __init__(self):
        super().__init__()
        self.all_avatars: List[EncoreAvatar] = []
        self.all_avatars_map: Dict[int, EncoreAvatar] = {}
        self.all_avatars_name: Dict[str, EncoreAvatar] = {}

    def clear_class_data(self) -> None:
        self.all_avatars.clear()
        self.all_avatars_map.clear()
        self.all_avatars_name.clear()

    async def refresh(self):
        datas = await self.remote_get(self.avatar_url)
        await self.dump(datas.json(), self.avatar_path)
        await self.read()

    async def read(self):
        if not self.avatar_path.exists():
            await self.refresh()
            return
        datas = await WikiModel.read(self.avatar_path)
        self.clear_class_data()
        for data in datas:
            m = EncoreAvatar(**data)
            self.all_avatars.append(m)
            self.all_avatars_map[m.id] = m
            self.all_avatars_name[m.name] = m

    def get_by_id(self, cid: int) -> Optional[EncoreAvatar]:
        return self.all_avatars_map.get(cid)

    def get_by_name(self, name: str) -> Optional[EncoreAvatar]:
        return self.all_avatars_name.get(name)

    def get_name_list(self) -> List[str]:
        return list(self.all_avatars_name.keys())
