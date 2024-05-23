from datetime import datetime
from typing import Dict, Optional

from kuronet import MCClient, Region
from kuronet.errors import BadRequest as SimnetBadRequest
from kuronet.models.lab.role import Account
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, TelegramObject, Update
from telegram.ext import CallbackContext, ConversationHandler, filters
from telegram.helpers import escape_markdown

from core.basemodel import RegionEnum
from core.plugin import Plugin, conversation, handler
from core.services.cookies.models import CookiesDataBase as Cookies, CookiesStatusEnum
from core.services.cookies.services import CookiesService
from core.services.players.models import PlayersDataBase as Player, PlayerInfoSQLModel
from core.services.players.services import PlayersService, PlayerInfoService
from gram_core.services.devices import DevicesService
from modules.apihelper.models.genshin.cookies import CookiesModel
from utils.log import logger

__all__ = ("AccountCookiesPlugin",)


class AccountIdNotFound(Exception):
    pass


class AccountCookiesPluginDeviceData(TelegramObject):
    device_id: str = ""
    device_fp: str = ""
    device_name: Optional[str] = None


class AccountCookiesPluginData(TelegramObject):
    region: RegionEnum = RegionEnum.NULL
    cookies: dict = {}
    account_id: int = 0
    # player_id: int = 0
    genshin_account: Optional[Account] = None
    device: Optional[AccountCookiesPluginDeviceData] = None

    def reset(self):
        self.region = RegionEnum.NULL
        self.cookies = {}
        self.account_id = 0
        self.genshin_account = None
        self.device = None


CHECK_SERVER, INPUT_COOKIES, COMMAND_RESULT = range(10100, 10103)


class AccountCookiesPlugin(Plugin.Conversation):
    """Cookie绑定"""

    def __init__(
        self,
        players_service: PlayersService = None,
        cookies_service: CookiesService = None,
        player_info_service: PlayerInfoService = None,
        devices_service: DevicesService = None,
    ):
        self.cookies_service = cookies_service
        self.players_service = players_service
        self.player_info_service = player_info_service
        self.devices_service = devices_service

    async def _parse_args(self, update: Update, context: CallbackContext) -> Optional[int]:
        args = self.get_args(context)
        account_cookies_plugin_data: AccountCookiesPluginData = context.chat_data.get("account_cookies_plugin_data")
        if len(args) < 2:
            return None
        regions = {"米游社": RegionEnum.HYPERION, "HoYoLab": RegionEnum.HOYOLAB}
        if args[0] not in regions:
            return None
        cookies = " ".join(args[1:])
        account_cookies_plugin_data.region = regions[args[0]]
        if ret := await self.parse_cookies(update, context, cookies):
            return ret
        return await self.check_cookies(update, context)

    @conversation.entry_point
    @handler.command(command="setcookie", filters=filters.ChatType.PRIVATE, block=False)
    @handler.command(command="setcookies", filters=filters.ChatType.PRIVATE, block=False)
    @handler.command(command="start", filters=filters.Regex("set_cookie$"), block=False)
    async def command_start(self, update: Update, context: CallbackContext) -> int:
        user = update.effective_user
        message = update.effective_message
        logger.info("用户 %s[%s] 绑定账号命令请求", user.full_name, user.id)
        account_cookies_plugin_data: AccountCookiesPluginData = context.chat_data.get("account_cookies_plugin_data")
        if account_cookies_plugin_data is None:
            account_cookies_plugin_data = AccountCookiesPluginData()
            context.chat_data["account_cookies_plugin_data"] = account_cookies_plugin_data
        else:
            account_cookies_plugin_data.reset()

        if ret := await self._parse_args(update, context):
            return ret

        text = f'你好 {user.mention_markdown_v2()} {escape_markdown("！请选择要绑定的服务器！或回复退出取消操作")}'
        reply_keyboard = [["库街区"], ["退出"]]
        await message.reply_markdown_v2(text, reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True))
        return CHECK_SERVER

    @conversation.state(state=CHECK_SERVER)
    @handler.message(filters=filters.TEXT & ~filters.COMMAND, block=False)
    async def check_server(self, update: Update, context: CallbackContext) -> int:
        message = update.effective_message
        account_cookies_plugin_data: AccountCookiesPluginData = context.chat_data.get("account_cookies_plugin_data")
        if message.text == "退出":
            await message.reply_text("退出任务", reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
        if message.text == "库街区":
            region = RegionEnum.HYPERION
            bbs_name = "库街区"
        else:
            await message.reply_text("选择错误，请重新选择")
            return CHECK_SERVER
        account_cookies_plugin_data.region = region
        await message.reply_text(f"请输入{bbs_name}的 user_token ！或回复退出取消操作", reply_markup=ReplyKeyboardRemove())
        await message.reply_html("<b>关于如何获取 user_token </b>\n\nhttps://telegra.ph/paigramteam-bot-usertoken-05-23")
        return INPUT_COOKIES

    @conversation.state(state=INPUT_COOKIES)
    @handler.message(filters=filters.TEXT & ~filters.COMMAND, block=False)
    async def input_cookies(self, update: Update, context: CallbackContext) -> int:
        message = update.effective_message
        if message.text == "退出":
            await message.reply_text("退出任务", reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
        if ret := await self.parse_cookies(update, context, message.text):
            return ret
        return await self.check_cookies(update, context)

    @staticmethod
    async def parse_cookies(update: Update, context: CallbackContext, text: str) -> Optional[int]:
        user = update.effective_user
        message = update.effective_message
        account_cookies_plugin_data: AccountCookiesPluginData = context.chat_data.get("account_cookies_plugin_data")
        if not text.startswith("ey"):
            logger.info("用户 %s[%s] user_token 格式有误", user.full_name, user.id)
            await message.reply_text("user_token 格式有误，请检查后重新尝试绑定", reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
        cookies = {
            "user_token": text,
        }
        account_cookies_plugin_data.cookies = cookies

    async def check_cookies(self, update: Update, context: CallbackContext) -> int:
        user = update.effective_user
        message = update.effective_message
        account_cookies_plugin_data: AccountCookiesPluginData = context.chat_data.get("account_cookies_plugin_data")
        cookies = CookiesModel(**account_cookies_plugin_data.cookies)
        if account_cookies_plugin_data.region == RegionEnum.HYPERION:
            region = Region.CHINESE
        elif account_cookies_plugin_data.region == RegionEnum.HOYOLAB:
            region = Region.OVERSEAS
        else:
            logger.error("用户 %s[%s] region 异常", user.full_name, user.id)
            await message.reply_text("数据错误", reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
        async with MCClient(cookies=cookies.to_dict(), region=region) as client:
            if not cookies.user_token:
                await message.reply_text(
                    "user_token 异常，请尝试重新绑定。", reply_markup=ReplyKeyboardRemove()
                )
                return ConversationHandler.END
            try:
                if region == Region.CHINESE:
                    account = await client.verify_token()
                    cookies.set_uid(account.userId)
                    account_cookies_plugin_data.account_id = account.userId
                    logger.success("用户 %s[%s] 绑定时获取 account_id 成功", user.full_name, user.id)
                    genshin_accounts = await client.get_mc_accounts()
            except SimnetBadRequest as exc:
                logger.warning(
                    "用户 %s[%s] 获取账号信息发生错误 [%s]%s", user.full_name, user.id, exc.ret_code, exc.original
                )
                await message.reply_text("user_token 无效，请重新绑定。", reply_markup=ReplyKeyboardRemove())
                return ConversationHandler.END
            except UnicodeEncodeError:
                await message.reply_text("user_token 非法，请重新绑定。", reply_markup=ReplyKeyboardRemove())
                return ConversationHandler.END
        if account_cookies_plugin_data.account_id is None:
            await message.reply_text("无法获取账号ID，请检查 user_token 是否正确或请稍后重试")
            return ConversationHandler.END
        genshin_account: Optional[Account] = None
        level: int = 0
        # todo : 多账号绑定
        for temp in genshin_accounts:
            if temp.level >= level:  # 获取账号等级最高的
                level = temp.level
                genshin_account = temp
        if genshin_account is None:
            await message.reply_text("未找到鸣潮账号，请确认账号信息无误。")
            return ConversationHandler.END
        account_cookies_plugin_data.genshin_account = genshin_account
        player_info = await self.players_service.get(
            user.id, player_id=genshin_account.uid, region=account_cookies_plugin_data.region
        )
        if player_info:
            cookies_database = await self.cookies_service.get(
                user.id, player_info.account_id, account_cookies_plugin_data.region
            )
            if cookies_database:
                await message.reply_text("警告，你已经绑定 user_token ，如果继续操作会覆盖当前 user_token 。")
        reply_keyboard = [["确认", "退出"]]
        await message.reply_text("获取角色基础信息成功，请检查是否正确！")
        logger.info(
            "用户 %s[%s] 获取账号 %s[%s] 信息成功",
            user.full_name,
            user.id,
            genshin_account.nickname,
            genshin_account.uid,
        )
        text = (
            f"*角色信息*\n"
            f"角色名称：{escape_markdown(genshin_account.nickname, version=2)}\n"
            f"角色等级：{genshin_account.level}\n"
            f"UID：`{genshin_account.uid}`\n"
            f"服务器名称：`{genshin_account.server_name}`\n"
        )
        await message.reply_markdown_v2(text, reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True))
        account_cookies_plugin_data.cookies = cookies.to_dict()
        return COMMAND_RESULT

    async def update_player(self, uid: int, genshin_account: Account, region: RegionEnum, account_id: int):
        player = await self.players_service.get(uid, player_id=genshin_account.uid, region=region)
        if player:
            if player.account_id != account_id:
                player.account_id = account_id
                await self.players_service.update(player)
        else:
            player_model = Player(
                user_id=uid,
                account_id=account_id,
                player_id=genshin_account.uid,
                region=region,
                is_chosen=True,  # todo 多账号
            )
            await self.update_player_info(player_model, genshin_account.nickname)
            await self.players_service.add(player_model)

    async def update_player_info(self, player: Player, nickname: str):
        player_info = await self.player_info_service.get(player)
        if player_info is None:
            player_info = PlayerInfoSQLModel(
                user_id=player.user_id,
                player_id=player.player_id,
                nickname=nickname,
                create_time=datetime.now(),
                is_update=True,
            )  # 不添加更新时间
            await self.player_info_service.add(player_info)

    async def update_cookies(self, uid: int, account_id: int, region: RegionEnum, cookies: Dict):
        cookies_data_base = await self.cookies_service.get(uid, account_id, region)
        if cookies_data_base:
            cookies_data_base.data = cookies
            cookies_data_base.status = CookiesStatusEnum.STATUS_SUCCESS
            await self.cookies_service.update(cookies_data_base)
        else:
            cookies = Cookies(
                user_id=uid,
                account_id=account_id,
                data=cookies,
                region=region,
                status=CookiesStatusEnum.STATUS_SUCCESS,
                is_share=True,  # todo 用户可以自行选择是否将Cookies加入公共池
            )
            await self.cookies_service.add(cookies)

    @conversation.state(state=COMMAND_RESULT)
    @handler.message(filters=filters.TEXT & ~filters.COMMAND, block=False)
    async def command_result(self, update: Update, context: CallbackContext) -> int:
        user = update.effective_user
        message = update.effective_message
        account_cookies_plugin_data: AccountCookiesPluginData = context.chat_data.get("account_cookies_plugin_data")
        if message.text == "退出":
            await message.reply_text("退出任务", reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
        if message.text == "确认":
            genshin_account = account_cookies_plugin_data.genshin_account
            await self.update_player(
                user.id, genshin_account, account_cookies_plugin_data.region, account_cookies_plugin_data.account_id
            )
            await self.update_cookies(
                user.id,
                account_cookies_plugin_data.account_id,
                account_cookies_plugin_data.region,
                account_cookies_plugin_data.cookies,
            )
            logger.info("用户 %s[%s] 绑定账号成功", user.full_name, user.id)
            await message.reply_text("保存成功", reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
        await message.reply_text("回复错误，请重新输入")
        return COMMAND_RESULT
