import datetime
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING

from kuronet.errors import DataNotPublic
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ChatAction
from telegram.ext import ConversationHandler, filters, CallbackContext
from telegram.helpers import create_deep_linked_url

from core.plugin import Plugin, handler
from core.services.template.models import RenderResult
from core.services.template.services import TemplateService
from plugins.tools.genshin import GenshinHelper
from utils.log import logger
from utils.uid import mask_number

if TYPE_CHECKING:
    from kuronet import MCClient


__all__ = ("DailyNotePlugin",)


class DailyNotePlugin(Plugin):
    """每日便签"""

    def __init__(
        self,
        template: TemplateService,
        helper: GenshinHelper,
    ):
        self.template_service = template
        self.helper = helper

    async def _get_daily_note(self, client: "MCClient") -> RenderResult:
        daily_info = await client.get_mc_notes_widget(client.player_id)

        day = datetime.now().strftime("%m-%d %H:%M") + " 星期" + "一二三四五六日"[datetime.now().weekday()]
        resin_need = daily_info.energyData.total - daily_info.energyData.cur
        resin_one_time = timedelta(minutes=6)
        resin_recovery_time = (
            (datetime.now() + (resin_one_time * resin_need)).strftime("%m-%d %H:%M") if resin_need else None
        )
        current_train_score = daily_info.livenessData.cur if daily_info.livenessData else 0
        max_train_score = daily_info.livenessData.total if daily_info.livenessData else 0

        render_data = {
            "uid": mask_number(client.player_id),
            "day": day,
            "resin_recovery_time": resin_recovery_time,
            "current_resin": daily_info.energyData.cur,
            "max_resin": daily_info.energyData.total,
            "liveness_unlock": daily_info.livenessData is not None,
            "current_train_score": current_train_score,
            "max_train_score": max_train_score,
            "battle_pass_data": daily_info.battlePassData,
        }
        render_result = await self.template_service.render(
            "mc/daily_note/daily_note.jinja2",
            render_data,
            {"width": 600, "height": 530},
            query_selector=".container",
            full_page=False,
            ttl=8 * 60,
        )
        return render_result

    @staticmethod
    def get_task_button(bot_username: str) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton(">> 设置状态提醒 <<", url=create_deep_linked_url(bot_username, "daily_note_tasks"))]]
        )

    @handler.command("dailynote", cookie=True, block=False)
    @handler.message(filters.Regex("^当前状态(.*)"), cookie=True, block=False)
    async def command_start(self, update: Update, context: CallbackContext) -> Optional[int]:
        user_id = await self.get_real_user_id(update)
        message = update.effective_message
        uid, offset = self.get_real_uid_or_offset(update)
        self.log_user(update, logger.info, "每日便签命令请求")

        try:
            async with self.helper.genshin(user_id, player_id=uid, offset=offset) as client:
                render_result = await self._get_daily_note(client)
        except DataNotPublic:
            reply_message = await message.reply_text(
                "查询失败惹，可能是便签功能被禁用了？请尝试通过库街区获取一次便签信息后重试。"
            )
            if filters.ChatType.GROUPS.filter(message):
                self.add_delete_message_job(reply_message, delay=30)
                self.add_delete_message_job(message, delay=30)
            return ConversationHandler.END

        await message.reply_chat_action(ChatAction.UPLOAD_PHOTO)
        await render_result.reply_photo(
            message,
            filename=f"{client.player_id}.png",
            reply_markup=self.get_task_button(context.bot.username),
        )
