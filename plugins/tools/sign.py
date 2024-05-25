import asyncio
import time
from enum import Enum
from typing import Optional, Tuple, List, TYPE_CHECKING

from httpx import TimeoutException
from kuronet.errors import BadRequest as SimnetBadRequest, AlreadyClaimed, InvalidCookies, TimedOut as SimnetTimedOut
from sqlalchemy.orm.exc import StaleDataError
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import Forbidden, BadRequest

from core.config import config
from core.dependence.redisdb import RedisDB
from core.plugin import Plugin
from core.services.cookies import CookiesService
from core.services.task.models import TaskStatusEnum
from core.services.task.services import SignServices
from core.services.users.services import UserService
from modules.apihelper.client.components.verify import Verify
from plugins.tools.genshin import PlayerNotFoundError, CookiesNotFoundError, GenshinHelper
from utils.log import logger

if TYPE_CHECKING:
    from kuronet import MCClient
    from telegram.ext import ContextTypes


class SignJobType(Enum):
    START = 1
    REDO = 2


class SignSystemException(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__()


class NeedChallenge(Exception):
    def __init__(self, uid: int, gt: str = "", challenge: str = ""):
        super().__init__()
        self.uid = uid
        self.gt = gt
        self.challenge = challenge


class SignSystem(Plugin):
    def __init__(
        self,
        redis: RedisDB,
        user_service: UserService,
        cookies_service: CookiesService,
        sign_service: SignServices,
        genshin_helper: GenshinHelper,
    ):
        self.cookies_service = cookies_service
        self.user_service = user_service
        self.sign_service = sign_service
        self.genshin_helper = genshin_helper
        self.cache = redis.client
        self.qname = "plugin:sign:"
        self.verify = Verify()

    async def get_challenge(self, uid: int) -> Tuple[Optional[str], Optional[str]]:
        data = await self.cache.get(f"{self.qname}{uid}")
        if not data:
            return None, None
        data = data.decode("utf-8").split("|")
        return data[0], data[1]

    async def set_challenge(self, uid: int, gt: str, challenge: str):
        await self.cache.set(f"{self.qname}{uid}", f"{gt}|{challenge}")
        await self.cache.expire(f"{self.qname}{uid}", 10 * 60)

    async def get_challenge_button(
        self,
        bot_username: str,
        uid: int,
        user_id: int,
        gt: Optional[str] = None,
        challenge: Optional[str] = None,
        callback: bool = True,
    ) -> Optional[InlineKeyboardMarkup]:
        if not config.pass_challenge_user_web:
            return None
        if challenge and gt:
            await self.set_challenge(uid, gt, challenge)
        if not challenge or not gt:
            gt, challenge = await self.get_challenge(uid)
        if not challenge or not gt:
            return None
        if callback:
            data = f"sign|{user_id}|{uid}"
            return InlineKeyboardMarkup([[InlineKeyboardButton("请尽快点我进行手动验证", callback_data=data)]])
        url = (
            f"{config.pass_challenge_user_web}?"
            f"gt={gt}&username={bot_username}&command=sign&challenge={challenge}&uid={uid}"
        )
        return InlineKeyboardMarkup([[InlineKeyboardButton("请尽快点我进行手动验证", url=url)]])

    async def start_sign(
        self,
        client: "MCClient",
        is_sleep: bool = False,
        is_raise: bool = False,
        title: Optional[str] = "签到结果",
    ) -> str:
        if is_sleep:
            await asyncio.sleep(1)  # nosec
        try:
            daily_reward_info = await client.get_reward_info(lang="zh-cn")
        except SimnetBadRequest as error:
            logger.warning("UID[%s] 获取签到信息失败，API返回信息为 %s", client.player_id, str(error))
            if is_raise:
                raise error
            return f"获取签到信息失败，API返回信息为 {str(error)}"
        if not daily_reward_info.signed_in:
            try:
                request_daily_reward = await client.claim_daily_reward(lang="zh-cn")
                logger.debug("request_daily_reward 返回 %s", request_daily_reward)
                if request_daily_reward:
                    logger.success("UID[%s] 签到成功", client.player_id)
            except TimeoutException as error:
                logger.warning("UID[%s] 签到请求超时", client.player_id)
                if is_raise:
                    raise error
                return "签到失败了呜呜呜 ~ 服务器连接超时 服务器熟啦 ~ "
            except AlreadyClaimed as error:
                logger.warning("UID[%s] 已经签到", client.player_id)
                if is_raise:
                    raise error
                result = "今天漂泊者已经签到过了~"
            except SimnetBadRequest as error:
                logger.warning("UID %s 签到失败，API返回信息为 %s", client.player_id, str(error))
                if is_raise:
                    raise error
                return f"获取签到状态失败，API返回信息为 {str(error)}"
            else:
                result = "OK"
        else:
            logger.info("UID[%s] 已经签到", client.player_id)
            result = "今天漂泊者已经签到过了~"
        logger.info("UID[%s] 签到结果 %s", client.player_id, result)
        reward = daily_reward_info.signInGoodsConfigs[
            daily_reward_info.claimed_rewards - (1 if daily_reward_info.signed_in else 0)
        ]
        today = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        missed_days = daily_reward_info.missed_rewards
        message = (
            f"#### {title} ####\n"
            f"时间：{today} (UTC+8)\n"
            f"UID: {client.player_id}\n"
            f"今日奖励: {reward.name} × {reward.amount}\n"
            f"本月漏签次数：{missed_days}\n"
            f"签到结果: {result}"
        )
        return message

    async def do_sign_job(self, context: "ContextTypes.DEFAULT_TYPE", job_type: SignJobType):
        include_status: List[TaskStatusEnum] = [
            TaskStatusEnum.STATUS_SUCCESS,
            TaskStatusEnum.TIMEOUT_ERROR,
            TaskStatusEnum.NEED_CHALLENGE,
        ]
        if job_type == SignJobType.START:
            title = "自动签到"
        elif job_type == SignJobType.REDO:
            title = "自动重新签到"
            include_status.remove(TaskStatusEnum.STATUS_SUCCESS)
        else:
            raise ValueError
        sign_list = await self.sign_service.get_all()
        for sign_db in sign_list:
            if sign_db.status not in include_status:
                continue
            user_id = sign_db.user_id
            try:
                async with self.genshin_helper.genshin(user_id) as client:
                    text = await self.start_sign(client, is_sleep=True, is_raise=True, title=title)
            except InvalidCookies:
                text = "自动签到执行失败，Cookie无效"
                sign_db.status = TaskStatusEnum.INVALID_COOKIES
            except AlreadyClaimed:
                text = "今天开拓者已经签到过了~"
                sign_db.status = TaskStatusEnum.ALREADY_CLAIMED
            except SimnetBadRequest as exc:
                text = f"自动签到执行失败，API返回信息为 {str(exc)}"
                sign_db.status = TaskStatusEnum.GENSHIN_EXCEPTION
            except SimnetTimedOut:
                text = "签到失败了呜呜呜 ~ 服务器连接超时 服务器熟啦 ~ "
                sign_db.status = TaskStatusEnum.TIMEOUT_ERROR
            except NeedChallenge:
                text = "签到失败，触发验证码风控"
                sign_db.status = TaskStatusEnum.NEED_CHALLENGE
            except PlayerNotFoundError:
                logger.info("用户 user_id[%s] 玩家不存在 关闭并移除自动签到", user_id)
                await self.sign_service.remove(sign_db)
                continue
            except CookiesNotFoundError:
                logger.info("用户 user_id[%s] cookie 不存在 关闭并移除自动签到", user_id)
                await self.sign_service.remove(sign_db)
                continue
            except Exception as exc:
                logger.error("执行自动签到时发生错误 user_id[%s]", user_id, exc_info=exc)
                text = "签到失败了呜呜呜 ~ 执行自动签到时发生错误"
            else:
                sign_db.status = TaskStatusEnum.STATUS_SUCCESS
            if sign_db.chat_id < 0:
                text = f'<a href="tg://user?id={sign_db.user_id}">NOTICE {sign_db.user_id}</a>\n\n{text}'
            try:
                await context.bot.send_message(sign_db.chat_id, text, parse_mode=ParseMode.HTML)
            except BadRequest as exc:
                logger.error("执行自动签到时发生错误 user_id[%s] Message[%s]", user_id, exc.message)
                sign_db.status = TaskStatusEnum.BAD_REQUEST
            except Forbidden as exc:
                logger.error("执行自动签到时发生错误 user_id[%s] message[%s]", user_id, exc.message)
                sign_db.status = TaskStatusEnum.FORBIDDEN
            except Exception as exc:
                logger.error("执行自动签到时发生错误 user_id[%s]", user_id, exc_info=exc)
                continue
            else:
                sign_db.status = TaskStatusEnum.STATUS_SUCCESS
            try:
                await self.sign_service.update(sign_db)
            except StaleDataError:
                logger.warning("用户 user_id[%s] 自动签到数据过期，跳过更新数据", user_id)
