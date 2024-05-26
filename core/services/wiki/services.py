from core.base_service import BaseService
from modules.wiki.character import Character
from modules.wiki.weapon import Weapon
from utils.log import logger

__all__ = ["WikiService"]


class WikiService(BaseService):
    def __init__(self):
        self.character = Character()
        self.weapon = Weapon()

    async def initialize(self) -> None:
        logger.info("正在加载 Wiki 数据")
        try:
            await self.character.read()
            await self.weapon.read()
        except Exception as e:
            logger.error("加载 Wiki 数据失败", exc_info=e)
        logger.info("加载 Wiki 数据完成")

    async def refresh_wiki(self) -> None:
        logger.info("正在重新获取Wiki")
        logger.info("正在重新获取角色信息")
        await self.character.refresh()
        logger.info("正在重新获取武器信息")
        await self.weapon.refresh()
        logger.info("刷新成功")
