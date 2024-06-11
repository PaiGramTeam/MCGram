from typing import Optional, TYPE_CHECKING
from telegram.constants import ChatAction
from telegram.ext import filters

from core.plugin import Plugin, handler
from core.services.cookies.error import TooManyRequestPublicCookies
from core.services.template.models import RenderResult
from core.services.template.services import TemplateService
from plugins.tools.genshin import GenshinHelper
from utils.log import logger
from utils.uid import mask_number

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import ContextTypes
    from kuronet import MCClient

__all__ = ("PlayerStatsPlugins",)


class PlayerStatsPlugins(Plugin):
    """玩家统计查询"""

    def __init__(self, template: TemplateService, helper: GenshinHelper):
        self.template_service = template
        self.helper = helper

    @handler.command("stats", player=True, block=False)
    @handler.message(filters.Regex("^玩家统计查询(.*)"), player=True, block=False)
    async def command_start(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> Optional[int]:
        user_id = await self.get_real_user_id(update)
        message = update.effective_message
        self.log_user(update, logger.info, "查询游戏用户命令请求")
        uid: Optional[int] = None
        try:
            args = context.args
            if args is not None and len(args) == 9:
                uid = int(args[0])
            async with self.helper.genshin_or_public(user_id) as client:
                client: "MCClient"
                await client.refresh_data(client.player_id)
                render_result = await self.render(client, uid)
        except TooManyRequestPublicCookies:
            await message.reply_text("用户查询次数过多 请稍后重试")
            return
        except AttributeError as exc:
            logger.error("角色数据有误")
            logger.exception(exc)
            await message.reply_text("角色数据有误 估计是凌阳晕了")
            return
        except ValueError as exc:
            logger.warning("获取 uid 发生错误！ 错误信息为 %s", str(exc))
            await message.reply_text("输入错误")
            return
        await message.reply_chat_action(ChatAction.UPLOAD_PHOTO)
        await render_result.reply_photo(message, filename=f"{client.player_id}.png")

    async def render(self, client: "MCClient", uid: Optional[int] = None) -> RenderResult:
        if uid is None:
            uid = client.player_id

        user_info = await client.get_mc_notes(uid, auto_refresh=False)
        explor = await client.get_mc_explorer(uid, auto_refresh=False)

        data = {
            "uid": mask_number(uid),
            "stats": user_info,
            "stats_labels": [
                ("活跃天数", "activeDays"),
                ("联觉等级", "level"),
                ("索拉等级", "worldLevel"),
                ("成就达成数", "achievementCount"),
                ("获取角色数", "roleNum"),
                ("声匣收集数", "soundBox"),
                ("小型信标", "smallCount"),
                ("中型信标", "bigCount"),
            ],
            "area": explor.areaInfoList,
            "style": "huanglong",  # nosec
        }

        return await self.template_service.render(
            "mc/stats/stats.jinja2",
            data,
            {"width": 650, "height": 800},
            full_page=True,
        )
