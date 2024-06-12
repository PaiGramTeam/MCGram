import pytz

from typing import TYPE_CHECKING

from telegram.ext import filters

from core.dependence.redisdb import RedisDB
from core.plugin import Plugin, handler
from core.services.cookies import CookiesService
from core.services.users.services import UserService
from plugins.tools.genshin import GenshinHelper
from utils.log import logger

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import ContextTypes
    from kuronet import MCClient

try:
    import ujson as jsonlib

except ImportError:
    import json as jsonlib

shanghai_tz = pytz.timezone("Asia/Shanghai")


class RegTimePlugin(Plugin):
    """查询鸣潮注册时间"""

    def __init__(
        self,
        user_service: UserService = None,
        cookie_service: CookiesService = None,
        helper: GenshinHelper = None,
        redis: RedisDB = None,
    ):
        self.cache = redis.client
        self.cache_key = "plugin:reg_time:"
        self.user_service = user_service
        self.cookie_service = cookie_service
        self.helper = helper

    @staticmethod
    async def get_reg_time(client: "MCClient") -> str:
        """获取鸣潮注册时间"""
        note = await client.get_mc_notes(auto_refresh=False)
        return note.creatTime.astimezone(shanghai_tz).strftime("%Y-%m-%d %H:%M:%S")

    async def get_reg_time_from_cache(self, client: "MCClient") -> str:
        """从缓存中获取鸣潮注册时间"""
        if reg_time := await self.cache.get(f"{self.cache_key}{client.player_id}"):
            return reg_time.decode("utf-8")
        reg_time = await self.get_reg_time(client)
        await self.cache.set(f"{self.cache_key}{client.player_id}", reg_time)
        return reg_time

    @handler.command("reg_time", block=False)
    @handler.message(filters.Regex(r"^鸣潮账号注册时间$"), block=False)
    async def reg_time(self, update: "Update", _: "ContextTypes.DEFAULT_TYPE") -> None:
        user_id = await self.get_real_user_id(update)
        uid, offset = self.get_real_uid_or_offset(update)
        message = update.effective_message
        self.log_user(update, logger.info, "鸣潮注册时间命令请求")
        async with self.helper.genshin_or_public(user_id, player_id=uid, offset=offset) as client:
            reg_time = await self.get_reg_time_from_cache(client)
        await message.reply_text(f"你的鸣潮账号注册时间为：{reg_time}")
