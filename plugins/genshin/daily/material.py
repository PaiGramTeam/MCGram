import asyncio
import contextlib
import os
import re
from asyncio import Lock
from ctypes import c_double
from datetime import datetime
from functools import partial
from multiprocessing import Value
from pathlib import Path
from ssl import SSLZeroReturnError
from typing import Any, Dict, Iterable, Iterator, List, Literal, Optional, Tuple

import ujson as json
from aiofiles import open as async_open
from arkowrapper import ArkoWrapper
from bs4 import BeautifulSoup
from genshin import Client, InvalidCookies, GenshinException
from httpx import AsyncClient, HTTPError
from pydantic import BaseModel
from telegram import Message, Update, User
from telegram.constants import ChatAction, ParseMode
from telegram.error import RetryAfter, TimedOut
from telegram.ext import CallbackContext

from core.base.assets import AssetsCouldNotFound, AssetsService, AssetsServiceType
from core.baseplugin import BasePlugin
from core.cookies.error import CookiesNotFoundError
from core.plugin import Plugin, handler
from core.template import TemplateService
from core.template.models import FileType, RenderGroupResult
from core.user.error import UserNotFoundError
from metadata.genshin import AVATAR_DATA, HONEY_DATA
from utils.bot import get_all_args
from utils.decorators.admins import bot_admins_rights_check
from utils.decorators.error import error_callable
from utils.decorators.restricts import restricts
from utils.helpers import get_genshin_client
from utils.log import logger

INTERVAL = 1

DATA_TYPE = Dict[str, List[List[str]]]
DATA_FILE_PATH = Path(__file__).joinpath("../daily.json").resolve()
DOMAINS = ["忘却之峡", "太山府", "菫色之庭", "昏识塔", "塞西莉亚苗圃", "震雷连山密宫", "砂流之庭", "有顶塔"]
DOMAIN_AREA_MAP = dict(zip(DOMAINS, ["蒙德", "璃月", "稻妻", "须弥"] * 2))

WEEK_MAP = ["一", "二", "三", "四", "五", "六", "日"]


def sort_item(items: List["ItemData"]) -> Iterable["ItemData"]:
    """对武器和角色进行排序

    排序规则：持有（星级 > 等级 > 命座/精炼) > 未持有（星级 > 等级 > 命座/精炼）
    """
    return (
        ArkoWrapper(items)
        .sort(lambda x: x.level or -1, reverse=True)
        .groupby(lambda x: x.level is None)  # 根据持有与未持有进行分组并排序
        .map(
            lambda x: (
                ArkoWrapper(x[1])
                .sort(lambda y: y.rarity, reverse=True)
                .groupby(lambda y: y.rarity)  # 根据星级分组并排序
                .map(
                    lambda y: (
                        ArkoWrapper(y[1])
                        .sort(lambda z: z.refinement or z.constellation or -1, reverse=True)
                        .groupby(lambda z: z.refinement or z.constellation or -1)  # 根据命座/精炼进行分组并排序
                        .map(lambda i: ArkoWrapper(i[1]).sort(lambda j: j.id))
                    )
                )
            )
        )
        .flat(3)
    )


def get_material_serial_name(names: Iterable[str]) -> str:
    """获取材料的系列名"""

    def all_substrings(string: str) -> Iterator[str]:
        """获取字符串的所有连续字串"""
        length = len(string)
        for i in range(length):
            for j in range(i + 1, length + 1):
                yield string[i:j]

    result = []
    for name_a, name_b in ArkoWrapper(names).repeat(1).group(2).unique(list):
        for sub_string in all_substrings(name_a):
            if sub_string in ArkoWrapper(all_substrings(name_b)):
                result.append(sub_string)
    result = ArkoWrapper(result).sort(len, reverse=True)[0]
    chars = {"的": 0, "之": 0}
    for char, k in chars.items():
        result = result.split(char)[k]
    return result


class DailyMaterial(Plugin, BasePlugin):
    """每日素材表"""

    data: DATA_TYPE
    locks: Tuple[Lock] = (Lock(), Lock())

    def __init__(self, assets: AssetsService, template_service: TemplateService):
        self.assets_service = assets
        self.template_service = template_service
        self.client = AsyncClient()

    async def __async_init__(self):
        """插件在初始化时，会检查一下本地是否缓存了每日素材的数据"""
        data = None

        async def task_daily():
            async with self.locks[0]:
                logger.info("正在开始获取每日素材缓存")
                self.data = await self._refresh_data()

        if (not DATA_FILE_PATH.exists()) or (  # 若缓存不存在
            (datetime.today() - datetime.fromtimestamp(os.stat(DATA_FILE_PATH).st_mtime)).days > 3  # 若缓存过期，超过了3天
        ):
            self.refresh_task = asyncio.create_task(task_daily())  # 创建后台任务
        if not data and DATA_FILE_PATH.exists():  # 若存在，则读取至内存中
            async with async_open(DATA_FILE_PATH) as file:
                data = json.loads(await file.read())
        self.data = data

    @staticmethod
    async def _get_skills_data(client: Client, character_id: int) -> Optional[List[int]]:
        """获取角色技能的数据"""
        for _ in range(5):
            try:
                detail = await client.get_character_details(character_id)
            except Exception as e:  # pylint: disable=W0703
                if isinstance(e, GenshinException):
                    # 如果是 Too Many Requests 异常，则等待一段时间后重试
                    if "Too Many Requests" in e.msg:
                        await asyncio.sleep(0.2)
                        continue
                # 如果是其他异常，则直接抛出
                raise e
            else:
                break
        else:
            # 如果重试了5次都失败了，则直接返回 None
            logger.warning(
                f"daily_material 解析角色 id 为 [bold]{character_id}[/]的数据时遇到了 Too Many Requests 错误", extra={"markup": True}
            )
            return None
        # 不用针对旅行者、草主进行特殊处理，因为输入数据不会有旅行者。
        # 不用计算命座加成，因为这个是展示天赋升级情况，10 级为最高。计算命座会引起混淆。
        talents = [t for t in detail.talents if t.type in ["attack", "skill", "burst"]]
        return [t.level for t in talents]

    async def _get_data_from_user(self, user: User) -> Tuple[Optional[Client], Dict[str, List[Any]]]:
        """获取已经绑定的账号的角色、武器信息"""
        user_data = {"avatar": [], "weapon": []}
        try:
            logger.debug("尝试获取已绑定的原神账号")
            client = await get_genshin_client(user.id)
            logger.debug(f"获取账号数据成功: UID={client.uid}")
            characters = await client.get_genshin_characters(client.uid)
            for character in characters:
                if character.name == "旅行者":  # 跳过主角
                    continue
                cid = AVATAR_DATA[str(character.id)]["id"]
                weapon = character.weapon
                user_data["avatar"].append(
                    ItemData(
                        id=cid,
                        name=character.name,
                        rarity=character.rarity,
                        level=character.level,
                        constellation=character.constellation,
                        gid=character.id,
                        icon=(await self.assets_service.avatar(cid).icon()).as_uri(),
                    )
                )
                user_data["weapon"].append(
                    ItemData(
                        id=str(weapon.id),
                        name=weapon.name,
                        level=weapon.level,
                        rarity=weapon.rarity,
                        refinement=weapon.refinement,
                        icon=(
                            await getattr(  # 判定武器的突破次数是否大于 2 ;若是, 则将图标替换为 awakened (觉醒) 的图标
                                self.assets_service.weapon(weapon.id), "icon" if weapon.ascension < 2 else "awaken"
                            )()
                        ).as_uri(),
                        c_path=(await self.assets_service.avatar(cid).side()).as_uri(),
                    )
                )
        except (UserNotFoundError, CookiesNotFoundError):
            logger.info(f"未查询到用户({user.full_name} {user.id}) 所绑定的账号信息")
        except InvalidCookies:
            logger.info(f"用户({user.full_name} {user.id}) 所绑定的账号信息已失效")
        else:
            # 没有异常返回数据
            return client, user_data
        # 有上述异常的， client 会返回 None
        return None, user_data

    @handler.command("daily_material", block=False)
    @restricts(restricts_time_of_groups=20, without_overlapping=True)
    @error_callable
    async def daily_material(self, update: Update, context: CallbackContext):
        user = update.effective_user
        message = update.effective_message
        args = get_all_args(context)
        now = datetime.now()

        try:
            weekday = (_ := int(args[0])) - (_ > 0)
            weekday = (weekday % 7 + 7) % 7
            time = title = f"星期{WEEK_MAP[weekday]}"
        except (ValueError, IndexError):
            title = "今日"
            weekday = now.weekday() - (1 if now.hour < 4 else 0)
            weekday = 6 if weekday < 0 else weekday
            time = f"星期{WEEK_MAP[weekday]}"
        full = bool(args and args[-1] == "full")  # 判定最后一个参数是不是 full

        logger.info(f'用户 {user.full_name}[{user.id}] 每日素材命令请求 || 参数 weekday="{WEEK_MAP[weekday]}" full={full}')

        if weekday == 6:
            await message.reply_text(
                ("今天" if title == "今日" else "这天") + "是星期天, <b>全部素材都可以</b>刷哦~", parse_mode=ParseMode.HTML
            )
            return

        if self.locks[0].locked():  # 若检测到了第一个锁：正在下载每日素材表的数据
            notice = await message.reply_text("派蒙正在摘抄每日素材表，以后再来探索吧~")
            self._add_delete_message_job(context, notice.chat_id, notice.message_id, 5)
            return

        if self.locks[1].locked():  # 若检测到了第二个锁：正在下载角色、武器、材料的图标
            await message.reply_text("派蒙正在搬运每日素材的图标，以后再来探索吧~")
            return

        notice = await message.reply_text("派蒙可能需要找找图标素材，还请耐心等待哦~")
        await message.reply_chat_action(ChatAction.TYPING)

        # 获取已经缓存的秘境素材信息
        local_data = {"avatar": [], "weapon": []}
        if not self.data:  # 若没有缓存每日素材表的数据
            logger.info("正在获取每日素材缓存")
            self.data = await self._refresh_data()
        for domain, sche in self.data.items():
            area = DOMAIN_AREA_MAP[domain]  # 获取秘境所在的区域
            type_ = "avatar" if DOMAINS.index(domain) < 4 else "weapon"  # 获取秘境的培养素材的类型：是天赋书还是武器突破材料
            # 将读取到的数据存入 local_data 中
            local_data[type_].append({"name": area, "materials": sche[weekday][0], "items": sche[weekday][1]})

        # 尝试获取用户已绑定的原神账号信息
        client, user_data = await self._get_data_from_user(user)

        await message.reply_chat_action(ChatAction.TYPING)
        render_data = RenderData(title=title, time=time, uid=client.uid if client else client)

        # 如果 client 为 None 就没必要进技能处理 因为已经触发 InvalidCookies 等异常
        if client:
            for type_ in ["avatar", "weapon"]:
                areas = []
                for area_data in local_data[type_]:  # 遍历每个区域的信息：蒙德、璃月、稻妻、须弥
                    items = []
                    for id_ in area_data["items"]:  # 遍历所有该区域下，当天（weekday）可以培养的角色、武器
                        added = False
                        for i in user_data[type_]:  # 从已经获取的角色数据中查找对应角色、武器
                            if id_ == str(i.id):
                                if i.rarity > 3:  # 跳过 3 星及以下的武器
                                    if type_ == "avatar":  # 给角色添加天赋信息
                                        skills = await self._get_skills_data(client, i.gid)
                                        i.skills = skills
                                    items.append(i)
                                added = True
                        if added:
                            continue
                        try:
                            item = HONEY_DATA[type_][id_]
                        except KeyError:  # 跳过不存在或者已忽略的角色、武器
                            logger.warning(f"未在 honey 数据中找到 {type_} {id_} 的信息")
                            continue
                        if item[2] < 4:  # 跳过 3 星及以下的武器
                            continue
                        items.append(
                            ItemData(  # 添加角色数据中未找到的
                                id=id_,
                                name=item[1],
                                rarity=item[2],
                                icon=(await getattr(self.assets_service, type_)(id_).icon()).as_uri(),
                            )
                        )
                    materials = []
                    for mid in area_data["materials"]:  # 添加这个区域当天（weekday）的培养素材
                        try:
                            path = (await self.assets_service.material(mid).icon()).as_uri()
                            material = HONEY_DATA["material"][mid]
                            materials.append(ItemData(id=mid, icon=path, name=material[1], rarity=material[2]))
                        except AssetsCouldNotFound as exc:
                            logger.error(f"出错了呜呜呜 ~ {repr(exc)}")
                            await notice.edit_text("出错了呜呜呜 ~ 派蒙找不到一些素材")
                            return
                    areas.append(
                        AreaData(
                            name=area_data["name"],
                            materials=materials,
                            # template previewer pickle cannot serialize generator
                            items=list(sort_item(items)),
                            material_name=get_material_serial_name(map(lambda x: x.name, materials)),
                        )
                    )
                setattr(render_data, {"avatar": "character"}.get(type_, type_), areas)

        await message.reply_chat_action(ChatAction.TYPING)

        # 是否发送原图
        file_type = FileType.DOCUMENT if full else FileType.PHOTO

        character_img_data, weapon_img_data = await asyncio.gather(
            self.template_service.render(  # 渲染角色素材页
                "genshin/daily_material/character.html",
                {"data": render_data},
                {"width": 1164, "height": 500},
                file_type=file_type,
                ttl=30 * 24 * 60 * 60,
            ),
            self.template_service.render(  # 渲染武器素材页
                "genshin/daily_material/weapon.html",
                {"data": render_data},
                {"width": 1164, "height": 500},
                file_type=file_type,
                ttl=30 * 24 * 60 * 60,
            ),
        )

        self._add_delete_message_job(context, notice.chat_id, notice.message_id, 5)
        await message.reply_chat_action(ChatAction.UPLOAD_PHOTO)

        character_img_data.filename = f"{title}可培养角色.png"
        weapon_img_data.filename = f"{title}可培养武器.png"

        await RenderGroupResult([character_img_data, weapon_img_data]).reply_media_group(message)

        logger.debug("角色、武器培养素材图发送成功")

    @handler.command("refresh_daily_material", block=False)
    @bot_admins_rights_check
    async def refresh(self, update: Update, context: CallbackContext):
        user = update.effective_user
        message = update.effective_message

        logger.info(f"用户 {user.full_name}[{user.id}] 刷新[bold]每日素材[/]缓存命令", extra={"markup": True})
        if self.locks[0].locked():
            notice = await message.reply_text("派蒙还在抄每日素材表呢，我有在好好工作哦~")
            self._add_delete_message_job(context, notice.chat_id, notice.message_id, 10)
            return
        if self.locks[1].locked():
            notice = await message.reply_text("派蒙正在搬运每日素材图标，在努力工作呢！")
            self._add_delete_message_job(context, notice.chat_id, notice.message_id, 10)
            return
        async with self.locks[1]:  # 锁住第二把锁
            notice = await message.reply_text("派蒙正在重新摘抄每日素材表，请稍等~", parse_mode=ParseMode.HTML)
            async with self.locks[0]:  # 锁住第一把锁
                data = await self._refresh_data()
            notice = await notice.edit_text(
                "每日素材表" + ("摘抄<b>完成！</b>" if data else "坏掉了！等会它再长好了之后我再抄。。。") + "\n正搬运每日素材的图标中。。。",
                parse_mode=ParseMode.HTML,
            )
            self.data = data or self.data
        time = await self._download_icon(notice)

        async def job(_, n):
            await n.edit_text(n.text_html.split("\n")[0] + "\n每日素材图标搬运<b>完成！</b>", parse_mode=ParseMode.HTML)
            await asyncio.sleep(INTERVAL)
            await notice.delete()

        context.application.job_queue.run_once(
            partial(job, n=notice), when=time + INTERVAL, name="notice_msg_final_job"
        )

    async def _refresh_data(self, retry: int = 5) -> DATA_TYPE:
        """刷新来自 honey impact 的每日素材表"""
        from bs4 import Tag

        result = {}
        for i in range(retry):  # 重复尝试 retry 次
            try:
                response = await self.client.get("https://genshin.honeyhunterworld.com/?lang=CHS")
                soup = BeautifulSoup(response.text, "lxml")
                calendar = soup.select(".calendar_day_wrap")[0]
                key: str = ""
                for tag in calendar:
                    tag: Tag
                    if tag.name == "span":  # 如果是秘境
                        key = tag.find("a").text
                        result[key] = [[[], []] for _ in range(7)]
                        for day, div in enumerate(tag.find_all("div")):
                            result[key][day][0] = []
                            for a in div.find_all("a"):
                                honey_id = re.findall(r"/(.*)?/", a["href"])[0]
                                mid: str = [i[0] for i in HONEY_DATA["material"].items() if i[1][0] == honey_id][0]
                                result[key][day][0].append(mid)
                    else:  # 如果是角色或武器
                        id_ = re.findall(r"/(.*)?/", tag["href"])[0]
                        if tag.text.strip() == "旅行者":  # 忽略主角
                            continue
                        id_ = ("" if id_.startswith("i_n") else "10000") + re.findall(r"\d+", id_)[0]
                        for day in map(int, tag.find("div")["data-days"]):  # 获取该角色/武器的可培养天
                            result[key][day][1].append(id_)
                for stage, schedules in result.items():
                    for day, _ in enumerate(schedules):
                        # noinspection PyUnresolvedReferences
                        result[stage][day][1] = list(set(result[stage][day][1]))  # 去重
                async with async_open(DATA_FILE_PATH, "w", encoding="utf-8") as file:
                    await file.write(json.dumps(result))  # skipcq: PY-W0079
                logger.info("每日素材刷新成功")
                break
            except (HTTPError, SSLZeroReturnError):
                from asyncio import sleep

                await sleep(1)
                if i <= retry - 1:
                    logger.warning("每日素材刷新失败, 正在重试")
                else:
                    logger.error("每日素材刷新失败, 请稍后重试")
                continue
        # noinspection PyTypeChecker
        return result

    async def _download_icon(self, message: Optional[Message] = None) -> float:
        """下载素材图标"""
        asset_list = []

        from time import time as time_

        lock = asyncio.Lock()

        the_time = Value(c_double, time_() - INTERVAL)

        async def edit_message(text):
            """修改提示消息"""
            async with lock:
                if message is not None and time_() >= (the_time.value + INTERVAL):
                    with contextlib.suppress(TimedOut, RetryAfter):
                        await message.edit_text(
                            "\n".join(message.text_html.split("\n")[:2] + [text]), parse_mode=ParseMode.HTML
                        )
                        the_time.value = time_()

        async def task(item_id, name, item_type):
            logger.debug(f'正在开始下载 "{name}" 的图标素材')
            await edit_message(f"正在搬运 <b>{name}</b> 的图标素材。。。")
            asset: AssetsServiceType = getattr(self.assets_service, item_type)(item_id)  # 获取素材对象
            asset_list.append(asset.honey_id)
            # 找到该素材对象的所有图标类型
            # 并根据图标类型找到下载对应图标的函数
            for icon_type in asset.icon_types:
                await getattr(asset, icon_type)(True)  # 执行下载函数
            logger.debug(f'"{name}" 的图标素材下载成功')
            await edit_message(f"正在搬运 <b>{name}</b> 的图标素材。。。<b>成功！</b>")

        for TYPE, ITEMS in HONEY_DATA.items():  # 遍历每个对象
            task_list = []
            new_items = []
            for ID, DATA in ITEMS.items():
                if (ITEM := [ID, DATA[1], TYPE]) not in new_items:
                    new_items.append(ITEM)
                    task_list.append(task(*ITEM))
            await asyncio.gather(*task_list)  # 等待所有任务执行完成

        logger.info("图标素材下载完成")
        return the_time.value


class ItemData(BaseModel):
    id: str  # ID
    name: str  # 名称
    rarity: int  # 星级
    icon: str  # 图标
    level: Optional[int] = None  # 等级
    constellation: Optional[int] = None  # 命座
    skills: Optional[List[int]] = None  # 天赋等级
    gid: Optional[int] = None  # 角色在 genshin.py 里的 ID
    refinement: Optional[int] = None  # 精炼度
    c_path: Optional[str] = None  # 武器使用者图标


class AreaData(BaseModel):
    name: Literal["蒙德", "璃月", "稻妻", "须弥"]  # 区域名
    material_name: str  # 区域的材料系列名
    materials: List[ItemData] = []  # 区域材料
    items: Iterable[ItemData] = []  # 可培养的角色或武器


class RenderData(BaseModel):
    title: str  # 页面标题，主要用于显示星期几
    time: str  # 页面时间
    uid: Optional[int] = None  # 用户UID
    character: List[AreaData] = []  # 角色数据
    weapon: List[AreaData] = []  # 武器数据

    def __getitem__(self, item):
        return self.__getattribute__(item)
