from telegram import Update
from telegram.ext import CallbackContext, filters

from core.plugin import Plugin, handler
from core.services.template.services import TemplateService
from utils.log import logger

__all__ = ("HelpPlugin",)


class HelpPlugin(Plugin):
    def __init__(self, template_service: TemplateService = None):
        if template_service is None:
            raise ModuleNotFoundError
        self.template_service = template_service

    @handler.command(command="help", block=False)
    @handler.command(command="start", filters=filters.Regex("inline_message$"), block=False)
    async def start(self, update: Update, _: CallbackContext):
        message = update.effective_message
        self.log_user(update, logger.info, "发出help命令")
        await message.reply_text("https://t.me/PaiGramTeam/148")
