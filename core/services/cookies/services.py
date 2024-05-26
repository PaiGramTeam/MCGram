from typing import List

from gram_core.base_service import BaseService
from gram_core.basemodel import RegionEnum
from gram_core.services.cookies.error import CookieServiceError
from gram_core.services.cookies.models import CookiesStatusEnum, CookiesDataBase as Cookies
from gram_core.services.cookies.services import (
    CookiesService,
    PublicCookiesService as BasePublicCookiesService,
    NeedContinue,
)

from kuronet import MCClient, Region
from kuronet.errors import InvalidCookies, TooManyRequests, BadRequest as SimnetBadRequest

from utils.log import logger

__all__ = ("CookiesService", "PublicCookiesService")


class PublicCookiesService(BaseService, BasePublicCookiesService):
    async def initialize(self) -> None:
        logger.info("正在初始化公共Cookies池")
        await self.refresh()
        logger.success("刷新公共Cookies池成功")

    async def check_public_cookie(self, region: RegionEnum, cookies: Cookies, public_id: int):  # skipcq: PY-R1000 #
        if region == RegionEnum.HYPERION:
            client = MCClient(cookies=cookies.data, region=Region.CHINESE, lang="zh-Hans")
        elif region == RegionEnum.HOYOLAB:
            client = MCClient(cookies=cookies.data, region=Region.OVERSEAS, lang="zh-Hans")
        else:
            raise CookieServiceError
        try:
            if client.account_id is None:
                raise RuntimeError("account_id not found")
            await client.verify_token_v2()
        except InvalidCookies as exc:
            logger.warning("Cookies无效 ")
            logger.exception(exc)
            cookies.status = CookiesStatusEnum.INVALID_COOKIES
            await self._repository.update(cookies)
            await self._cache.delete_public_cookies(cookies.user_id, region)
            raise NeedContinue
        except TooManyRequests:
            logger.warning("用户 [%s] 查询次数太多或操作频繁", public_id)
            cookies.status = CookiesStatusEnum.TOO_MANY_REQUESTS
            await self._repository.update(cookies)
            await self._cache.delete_public_cookies(cookies.user_id, region)
            raise NeedContinue
        except SimnetBadRequest as exc:
            if "invalid content type" in exc.message:
                raise exc
            logger.warning("用户 [%s] 获取账号信息发生错误，错误信息为", public_id)
            logger.exception(exc)
            await self._cache.delete_public_cookies(cookies.user_id, region)
            raise NeedContinue
        except RuntimeError as exc:
            if "account_id not found" in str(exc):
                cookies.status = CookiesStatusEnum.INVALID_COOKIES
                await self._repository.update(cookies)
                await self._cache.delete_public_cookies(cookies.user_id, region)
                raise NeedContinue
            raise exc
        except Exception as exc:
            await self._cache.delete_public_cookies(cookies.user_id, region)
            raise exc
        finally:
            await client.shutdown()

    async def refresh(self):
        """刷新公共Cookies 定时任务
        :return:
        """
        user_list: List[int] = []
        cookies_list = await self._repository.get_all(
            region=RegionEnum.HYPERION, status=CookiesStatusEnum.STATUS_SUCCESS
        )
        for cookies in cookies_list:
            user_list.append(cookies.user_id)
        if len(user_list) > 0:
            add, count = await self._cache.add_public_cookies(user_list, RegionEnum.HYPERION)
            logger.info("国服公共Cookies池已经添加[%s]个 当前成员数为[%s]", add, count)
        user_list.clear()
        cookies_list = await self._repository.get_all(
            region=RegionEnum.HOYOLAB, status=CookiesStatusEnum.STATUS_SUCCESS
        )
        for cookies in cookies_list:
            user_list.append(cookies.user_id)
        if len(user_list) > 0:
            add, count = await self._cache.add_public_cookies(user_list, RegionEnum.HOYOLAB)
            logger.info("国际服公共Cookies池已经添加[%s]个 当前成员数为[%s]", add, count)
