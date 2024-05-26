import asyncio
from pathlib import Path
from ssl import SSLZeroReturnError
from typing import Optional, List, Dict

from aiofiles import open as async_open
from httpx import AsyncClient, HTTPError

from core.base_service import BaseService
from modules.wiki.base import WikiModel
from modules.wiki.models.character import EncoreAvatar
from modules.wiki.models.weapon import EncoreWeapon
from utils.const import PROJECT_ROOT
from utils.log import logger
from utils.typedefs import StrOrURL, StrOrInt

ASSETS_PATH = PROJECT_ROOT.joinpath("resources/assets")
ASSETS_PATH.mkdir(exist_ok=True, parents=True)
DATA_MAP = {
    "character": WikiModel.BASE_URL + "character.json",
    "weapon": WikiModel.BASE_URL + "weapon.json",
}


class AssetsServiceError(Exception):
    pass


class AssetsCouldNotFound(AssetsServiceError):
    def __init__(self, message: str, target: str):
        self.message = message
        self.target = target
        super().__init__(f"{message}: target={target}")


class _AssetsService:
    client: Optional[AsyncClient] = None

    def __init__(self, client: Optional[AsyncClient] = None) -> None:
        self.client = client

    async def _download(self, url: StrOrURL, path: Path, retry: int = 5) -> Optional[Path]:
        """从 url 下载图标至 path"""
        if not url:
            return None
        if not url.startswith("http"):
            return None
        logger.debug("正在从 %s 下载图标至 %s", url, path)
        headers = None
        for time in range(retry):
            try:
                response = await self.client.get(url, follow_redirects=False, headers=headers)
            except Exception as error:  # pylint: disable=W0703
                if not isinstance(error, (HTTPError, SSLZeroReturnError)):
                    logger.error(error)  # 打印未知错误
                if time != retry - 1:  # 未达到重试次数
                    await asyncio.sleep(1)
                else:
                    raise error
                continue
            if response.status_code != 200:  # 判定页面是否正常
                return None
            async with async_open(path, "wb") as file:
                await file.write(response.content)  # 保存图标
            return path.resolve()


class _AvatarAssets(_AssetsService):
    path: Path
    data: List[EncoreAvatar]
    name_map: Dict[str, EncoreAvatar]
    id_map: Dict[int, EncoreAvatar]

    def __init__(self, client: Optional[AsyncClient] = None) -> None:
        super().__init__(client)
        self.path = ASSETS_PATH.joinpath("character")
        self.path.mkdir(exist_ok=True, parents=True)

    async def initialize(self):
        logger.info("正在初始化角色素材图标")
        html = await self.client.get(DATA_MAP["character"])
        self.data = [EncoreAvatar(**data) for data in html.json()]
        self.name_map = {icon.name: icon for icon in self.data}
        self.id_map = {icon.id: icon for icon in self.data}
        tasks = []
        for icon in self.data:
            base_path = self.path / f"{icon.id}"
            base_path.mkdir(exist_ok=True, parents=True)
            gacha_path = base_path / "gacha.png"
            big_gacha_path = base_path / "big_gacha.png"
            normal_path = base_path / "normal.png"
            square_path = base_path / "square.png"

            if not gacha_path.exists():
                tasks.append(self._download(icon.gacha, gacha_path))
            if not big_gacha_path.exists():
                tasks.append(self._download(icon.big_gacha, big_gacha_path))
            if not normal_path.exists():
                tasks.append(self._download(icon.normal, normal_path))
            if not square_path.exists() and icon.square:
                tasks.append(self._download(icon.square, square_path))

            if len(tasks) >= 100:
                await asyncio.gather(*tasks)
                tasks = []
        if tasks:
            await asyncio.gather(*tasks)
        logger.info("角色素材图标初始化完成")

    def get_path(self, icon: EncoreAvatar, name: str, ext: str = "png") -> Path:
        path = self.path / f"{icon.id}"
        path.mkdir(exist_ok=True, parents=True)
        return path / f"{name}.{ext}"

    def get_by_id(self, id_: int) -> Optional[EncoreAvatar]:
        return self.id_map.get(id_, None)

    def get_by_name(self, name: str) -> Optional[EncoreAvatar]:
        return self.name_map.get(name, None)

    def get_target(self, target: StrOrInt, second_target: StrOrInt = None) -> EncoreAvatar:
        data = None
        if isinstance(target, int):
            data = self.get_by_id(target)
        elif isinstance(target, str):
            data = self.get_by_name(target)
        if data is None:
            if second_target:
                return self.get_target(second_target)
            raise AssetsCouldNotFound("角色素材图标不存在", target)
        return data

    def gacha(self, target: StrOrInt, second_target: StrOrInt = None) -> Path:
        icon = self.get_target(target, second_target)
        return self.get_path(icon, "gacha")

    def big_gacha(self, target: StrOrInt, second_target: StrOrInt = None) -> Path:
        icon = self.get_target(target, second_target)
        return self.get_path(icon, "big_gacha")

    def normal(self, target: StrOrInt, second_target: StrOrInt = None) -> Path:
        icon = self.get_target(target, second_target)
        return self.get_path(icon, "normal")

    def square(self, target: StrOrInt, second_target: StrOrInt = None, allow_icon: bool = True) -> Path:
        icon = self.get_target(target, second_target)
        path = self.get_path(icon, "square")
        if not path.exists():
            if allow_icon:
                return self.get_path(icon, "normal")
            raise AssetsCouldNotFound("角色素材图标不存在", target)
        return path


class _WeaponAssets(_AssetsService):
    path: Path
    data: List[EncoreWeapon]
    name_map: Dict[str, EncoreWeapon]
    id_map: Dict[int, EncoreWeapon]

    def __init__(self, client: Optional[AsyncClient] = None) -> None:
        super().__init__(client)
        self.path = ASSETS_PATH.joinpath("weapon")
        self.path.mkdir(exist_ok=True, parents=True)

    async def initialize(self):
        logger.info("正在初始化武器素材图标")
        html = await self.client.get(DATA_MAP["weapon"])
        self.data = [EncoreWeapon(**data) for data in html.json()]
        self.name_map = {icon.name: icon for icon in self.data}
        self.id_map = {icon.id: icon for icon in self.data}
        tasks = []
        for icon in self.data:
            base_path = self.path / f"{icon.id}"
            base_path.mkdir(exist_ok=True, parents=True)
            big_pic_path = base_path / "big_pic.png"
            icon_path = base_path / "icon.png"
            if not big_pic_path.exists():
                tasks.append(self._download(icon.big_pic, big_pic_path))
            if not icon_path.exists():
                tasks.append(self._download(icon.icon, icon_path))
            if len(tasks) >= 100:
                await asyncio.gather(*tasks)
                tasks = []
        if tasks:
            await asyncio.gather(*tasks)
        logger.info("武器素材图标初始化完成")

    def get_path(self, icon: EncoreWeapon, name: str) -> Path:
        path = self.path / f"{icon.id}"
        path.mkdir(exist_ok=True, parents=True)
        return path / f"{name}.png"

    def get_by_id(self, id_: int) -> Optional[EncoreWeapon]:
        return self.id_map.get(id_, None)

    def get_by_name(self, name: str) -> Optional[EncoreWeapon]:
        return self.name_map.get(name, None)

    def get_target(self, target: StrOrInt, second_target: StrOrInt = None) -> Optional[EncoreWeapon]:
        if isinstance(target, int):
            return self.get_by_id(target)
        elif isinstance(target, str):
            return self.get_by_name(target)
        if second_target:
            return self.get_target(second_target)
        raise AssetsCouldNotFound("武器素材图标不存在", target)

    def big_pic(self, target: StrOrInt, second_target: StrOrInt = None) -> Path:
        icon = self.get_target(target, second_target)
        return self.get_path(icon, "big_pic")

    def icon(self, target: StrOrInt, second_target: StrOrInt = None) -> Path:
        icon = self.get_target(target, second_target)
        return self.get_path(icon, "icon")


class AssetsService(BaseService.Dependence):
    """asset服务

    用于储存和管理 asset :
        当对应的 asset (如某角色图标)不存在时，该服务会先查找本地。
        若本地不存在，则从网络上下载；若存在，则返回其路径
    """

    client: Optional[AsyncClient] = None

    avatar: _AvatarAssets
    """角色"""
    weapon: _WeaponAssets
    """武器"""

    def __init__(self):
        self.client = AsyncClient(timeout=60.0)
        self.avatar = _AvatarAssets(self.client)
        self.weapon = _WeaponAssets(self.client)

    async def initialize(self):  # pylint: disable=W0221
        await self.avatar.initialize()
        await self.weapon.initialize()
