import asyncio
from typing import List, Optional, Sequence, TYPE_CHECKING, Union, Tuple, Any, Dict

from arkowrapper import ArkoWrapper
from kuronet import MCClient
from kuronet.models.mc.character import MCRole
from kuronet.models.mc.chronicle.role import MCRoleSkill, MCRoleDetail, MCRoleWeaponData
from pydantic import BaseModel
from kuronet.errors import BadRequest as SimnetBadRequest
from telegram.constants import ChatAction
from telegram.ext import filters

from core.dependence.assets import AssetsService
from core.plugin import Plugin, handler
from core.services.cookies import CookiesService
from core.services.players import PlayersService
from core.services.players.services import PlayerInfoService
from core.services.template.models import FileType
from core.services.template.services import TemplateService
from gram_core.services.template.models import RenderGroupResult
from metadata.shortname import traveler_roles
from plugins.tools.genshin import CharacterDetails, GenshinHelper
from plugins.tools.player_info import PlayerInfoSystem
from utils.log import logger
from utils.uid import mask_number

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import ContextTypes
    from gram_core.services.template.models import RenderResult

MAX_AVATAR_COUNT = 40


class SkillData(BaseModel):
    """天赋数据"""

    skill: MCRoleSkill
    buffed: bool = False
    """是否得到了命座加成"""


class AvatarData(BaseModel):
    avatar: MCRole
    detail: MCRoleDetail
    icon: str
    weapon: MCRoleWeaponData
    weapon_icon: Optional[str]
    skills: List[SkillData]
    constellation: int

    def sum_of_skills(self) -> int:
        total_level = 0
        for skill_data in self.skills:
            total_level += skill_data.skill.level
        return total_level


class AvatarListPlugin(Plugin):
    """练度统计"""

    def __init__(
        self,
        player_service: PlayersService = None,
        cookies_service: CookiesService = None,
        assets_service: AssetsService = None,
        template_service: TemplateService = None,
        helper: GenshinHelper = None,
        character_details: CharacterDetails = None,
        player_info_service: PlayerInfoService = None,
        player_info_system: PlayerInfoSystem = None,
    ) -> None:
        self.cookies_service = cookies_service
        self.assets_service = assets_service
        self.template_service = template_service
        self.helper = helper
        self.character_details = character_details
        self.player_service = player_service
        self.player_info_service = player_info_service
        self.player_info_system = player_info_system

    async def get_avatar_data(self, character: MCRole, client: "MCClient") -> Optional["AvatarData"]:
        detail = await self.character_details.get_character_details(client, character)
        if detail is None:
            return None
        talents = [t for t in detail.skillList if t.skill.type in ["常态攻击", "共鸣技能", "共鸣解放"]]
        return AvatarData(
            avatar=character,
            detail=detail,
            icon=(self.assets_service.avatar.square(character.roleId)).as_uri(),
            weapon=detail.weaponData,
            weapon_icon=(self.assets_service.weapon.icon(detail.weaponData.weapon.weaponId)).as_uri(),
            skills=[
                SkillData(skill=s, buffed=False)
                for s in sorted(talents, key=lambda x: ["常态攻击", "共鸣技能", "共鸣解放"].index(x.skill.type))
            ],
            constellation=len([i for i in detail.chainList if i.unlocked]),
        )

    async def get_avatars_data(
        self, characters: Sequence[MCRole], client: "MCClient", max_length: int = None
    ) -> List["AvatarData"]:
        async def _task(c):
            return await self.get_avatar_data(c, client)

        task_results = await asyncio.gather(*[_task(character) for character in characters])

        return sorted(
            list(filter(lambda x: x, task_results)),
            key=lambda x: (
                x.avatar.level,
                x.avatar.starLevel,
                x.sum_of_skills(),
            ),
            reverse=True,
        )[:max_length]

    async def avatar_list_render(
        self,
        base_render_data: Dict,
        avatar_datas: List[AvatarData],
        only_one_page: bool,
    ) -> Union[Tuple[Any], List["RenderResult"], None]:
        def render_task(start_id: int, c: List[AvatarData]):
            _render_data = {
                "avatar_datas": c,  # 角色数据
                "start_id": start_id,  # 开始序号
            }
            _render_data.update(base_render_data)
            return self.template_service.render(
                "mc/avatar_list/main.jinja2",
                _render_data,
                viewport={"width": 1040, "height": 500},
                full_page=True,
                query_selector=".container",
                file_type=FileType.PHOTO,
                ttl=30 * 24 * 60 * 60,
            )

        if only_one_page:
            return [await render_task(0, avatar_datas)]
        avatar_datas_group = [
            avatar_datas[i : i + MAX_AVATAR_COUNT] for i in range(0, len(avatar_datas), MAX_AVATAR_COUNT)
        ]
        tasks = [render_task(i * MAX_AVATAR_COUNT, c) for i, c in enumerate(avatar_datas_group)]
        return await asyncio.gather(*tasks)

    def get_default_avatar(self, characters: Sequence[MCRole]) -> Optional[str]:
        avatar = None
        for ch in characters:
            if ch.roleId in traveler_roles:
                return self.assets_service.avatar.normal(ch.roleId).as_uri()
        return avatar

    @handler.command("avatars", cookie=True, block=False)
    @handler.message(filters.Regex(r"^(全部)?练度统计$"), cookie=True, block=False)
    async def avatar_list(self, update: "Update", _: "ContextTypes.DEFAULT_TYPE"):
        user_id = await self.get_real_user_id(update)
        user_name = self.get_real_user_name(update)
        message = update.effective_message
        all_avatars = "全部" in message.text or "all" in message.text  # 是否发送全部角色

        self.log_user(update, logger.info, "[bold]练度统计[/bold]: all=%s", all_avatars, extra={"markup": True})
        notice = None
        try:
            async with self.helper.genshin_or_public(user_id) as client:
                client: "MCClient"
                notice = await message.reply_text("凌阳需要收集整理数据，还请耐心等待哦~")
                await message.reply_chat_action(ChatAction.TYPING)
                characters = await client.get_mc_roles(client.player_id)
                avatar_datas: List[AvatarData] = await self.get_avatars_data(
                    characters.roleList, client, None if all_avatars else MAX_AVATAR_COUNT
                )
        except SimnetBadRequest as e:
            if notice:
                await notice.delete()
            raise e

        name_card, avatar, nickname, rarity = await self.player_info_system.get_player_info(
            client.player_id, user_id, user_name
        )
        if not avatar:
            avatar = self.get_default_avatar(characters.roleList)

        await message.reply_chat_action(ChatAction.UPLOAD_PHOTO)
        base_render_data = {
            "uid": mask_number(client.player_id),  # 玩家uid
            "nickname": nickname,  # 玩家昵称
            "avatar": avatar,  # 玩家头像
            "rarity": rarity,  # 玩家头像对应的角色星级
            "namecard": name_card,  # 玩家名片
            "has_more": len(characters.roleList) != len(avatar_datas),  # 是否显示了全部角色
        }

        images = await self.avatar_list_render(base_render_data, avatar_datas, not all_avatars)
        self.add_delete_message_job(notice, delay=5)

        for group in ArkoWrapper(images).group(10):  # 每 10 张图片分一个组
            await RenderGroupResult(results=group).reply_media_group(
                message, allow_sending_without_reply=True, write_timeout=60
            )

        self.log_user(
            update,
            logger.info,
            "[bold]练度统计[/bold]发送图片成功",
            extra={"markup": True},
        )
