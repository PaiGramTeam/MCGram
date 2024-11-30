import base64
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, List, Optional

from pydantic import field_validator, BaseModel
from kuronet.errors import BadRequest as SimnetBadRequest, InvalidCookies, TimedOut as SimnetTimedOut
from sqlalchemy.orm.exc import StaleDataError
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden

from core.plugin import Plugin
from core.services.task.models import Task as TaskUser, TaskStatusEnum
from core.services.task.services import TaskResinServices, TaskDailyServices
from gram_core.plugin.methods.migrate_data import IMigrateData, MigrateDataException
from plugins.tools.genshin import GenshinHelper, PlayerNotFoundError, CookiesNotFoundError
from utils.log import logger

if TYPE_CHECKING:
    from kuronet import MCClient
    from kuronet.models.mc.chronicle.notes import MCNoteWidget
    from telegram.ext import ContextTypes
    from gram_core.services.task.services import TaskServices


class TaskDataBase(BaseModel):
    noticed: Optional[bool] = False


class ResinData(TaskDataBase):
    notice_num: Optional[int] = 140

    @field_validator("notice_num")
    @classmethod
    def notice_num_validator(cls, v):
        if v < 100 or v > 240:
            raise ValueError("开拓力提醒数值必须在 100 ~ 240 之间")
        return v


class DailyData(TaskDataBase):
    notice_hour: Optional[int] = 22

    @field_validator("notice_hour")
    @classmethod
    def notice_hour_validator(cls, v):
        if v < 0 or v > 23:
            raise ValueError("每日任务提醒时间必须在 0 ~ 23 之间")
        return v


class WebAppData(BaseModel):
    user_id: int
    player_id: int

    resin: Optional[ResinData] = None
    daily: Optional[DailyData] = None


class DailyNoteTaskUser:
    def __init__(
        self,
        user_id: int,
        player_id: int,
        resin_db: Optional[TaskUser] = None,
        daily_db: Optional[TaskUser] = None,
    ):
        self.user_id = user_id
        self.player_id = player_id
        self.resin_db = resin_db
        self.daily_db = daily_db
        self.resin = ResinData(**self.resin_db.data) if self.resin_db else None
        self.daily = DailyData(**self.daily_db.data) if self.daily_db else None

    @property
    def status(self) -> TaskStatusEnum:
        return max(
            [
                self.resin_db.status if self.resin_db else TaskStatusEnum.STATUS_SUCCESS,
                self.daily_db.status if self.daily_db else TaskStatusEnum.STATUS_SUCCESS,
            ]
        )

    @status.setter
    def status(self, value: TaskStatusEnum):
        if self.resin_db:
            self.resin_db.status = value
        if self.daily:
            self.daily_db.status = value

    @staticmethod
    def js_bool(value: bool) -> str:
        return "true" if value else "false"

    @staticmethod
    def set_model_noticed(model: TaskDataBase):
        data = model.copy(deep=True)
        data.noticed = True
        return data

    @property
    def web_config(self) -> str:
        return base64.b64encode(
            (
                WebAppData(
                    user_id=self.user_id,
                    player_id=self.player_id,
                    resin=self.set_model_noticed(self.resin) if self.resin else None,
                    daily=self.set_model_noticed(self.daily) if self.daily else None,
                ).json()
            ).encode()
        ).decode()

    def save(self):
        if self.resin_db:
            self.resin_db.data = self.resin.dict()
        if self.daily_db:
            self.daily_db.data = self.daily.dict()


class DailyNoteSystem(Plugin):
    def __init__(
        self,
        genshin_helper: GenshinHelper,
        resin_service: TaskResinServices,
        daily_service: TaskDailyServices,
    ):
        self.genshin_helper = genshin_helper
        self.resin_service = resin_service
        self.daily_service = daily_service

    async def get_single_task_user(self, user_id: int, player_id: int) -> DailyNoteTaskUser:
        resin_db = await self.resin_service.get_by_user_id(user_id, player_id)
        daily_db = await self.daily_service.get_by_user_id(user_id, player_id)
        return DailyNoteTaskUser(
            user_id=user_id,
            player_id=player_id,
            resin_db=resin_db,
            daily_db=daily_db,
        )

    @staticmethod
    def get_resin_notice(user: DailyNoteTaskUser, notes: "MCNoteWidget") -> str:
        notice = None
        if user.resin_db and notes.max_stamina > 0:
            if notes.current_stamina >= user.resin.notice_num:
                if not user.resin.noticed:
                    resin_need = notes.max_stamina - notes.current_stamina
                    resin_one_time = timedelta(minutes=6)
                    rec_time = (
                        (datetime.now() + (resin_one_time * resin_need)).strftime("%m-%d %H:%M") if resin_need else None
                    )
                    notice = (
                        f"### 结晶波片提示 ####\n\n当前结晶波片为 {notes.current_stamina} / {notes.max_stamina} ，记得使用哦~\n"
                        f"预计全部恢复完成：{rec_time}"
                    )
                    user.resin.noticed = True
            else:
                user.resin.noticed = False
        return notice

    @staticmethod
    def get_daily_notice(user: DailyNoteTaskUser, notes: "MCNoteWidget") -> str:
        notice = None
        now_hour = datetime.now().hour
        if user.daily_db:
            if now_hour == user.daily.notice_hour:
                if notes.current_liveness != notes.max_liveness and (not user.daily.noticed):
                    notice = (
                        f"### 每日任务提示 ####\n\n"
                        f"当前进度为 {notes.current_liveness} / {notes.max_liveness} ，记得完成哦~"
                    )
                    user.daily.noticed = True
            else:
                user.daily.noticed = False
        return notice

    @staticmethod
    async def start_get_notes(
        client: "MCClient",
        user: DailyNoteTaskUser = None,
    ) -> List[str]:
        notes = await client.get_mc_notes_widget()
        if not user:
            return []
        notices = [
            DailyNoteSystem.get_resin_notice(user, notes),
            DailyNoteSystem.get_daily_notice(user, notes),
        ]
        user.save()
        return notices

    async def get_all_task_users(self) -> List[DailyNoteTaskUser]:
        resin_list = await self.resin_service.get_all()
        daily_list = await self.daily_service.get_all()
        user_list = set()
        for i in resin_list + daily_list:
            user_list.add((i.user_id, i.player_id))
        return [
            DailyNoteTaskUser(
                user_id=i,
                player_id=p,
                resin_db=next((x for x in resin_list if x.user_id == i and x.player_id == p), None),
                daily_db=next((x for x in daily_list if x.user_id == i and x.player_id == p), None),
            )
            for i, p in user_list
        ]

    async def remove_task_user(self, user: DailyNoteTaskUser):
        if user.resin_db:
            await self.resin_service.remove(user.resin_db)
        if user.daily_db:
            await self.daily_service.remove(user.daily_db)

    async def update_task_user(self, user: DailyNoteTaskUser):
        if user.resin_db:
            try:
                await self.resin_service.update(user.resin_db)
            except StaleDataError:
                logger.warning("用户 user_id[%s] 自动便签提醒 - 结晶波片数据过期，跳过更新数据", user.user_id)
        if user.daily_db:
            try:
                await self.daily_service.update(user.daily_db)
            except StaleDataError:
                logger.warning("用户 user_id[%s] 自动便签提醒 - 每日任务数据过期，跳过更新数据", user.user_id)

    @staticmethod
    async def check_need_note(web_config: WebAppData) -> bool:
        need_verify = False
        if web_config.resin and web_config.resin.noticed:
            need_verify = True
        if web_config.daily and web_config.daily.noticed:
            need_verify = True
        return need_verify

    async def import_web_config_resin(self, user: DailyNoteTaskUser, web_config: WebAppData):
        user_id, player_id = user.user_id, user.player_id
        if web_config.resin.noticed:
            if not user.resin_db:
                resin = self.resin_service.create(
                    user_id,
                    player_id,
                    user_id,
                    status=TaskStatusEnum.STATUS_SUCCESS,
                    data=ResinData(notice_num=web_config.resin.notice_num).dict(),
                )
                await self.resin_service.add(resin)
            else:
                user.resin.notice_num = web_config.resin.notice_num
                user.resin.noticed = False
                user.resin_db.status = TaskStatusEnum.STATUS_SUCCESS
        else:
            if user.resin_db:
                await self.resin_service.remove(user.resin_db)
                user.resin_db = None
                user.resin = None

    async def import_web_config_daily(self, user: DailyNoteTaskUser, web_config: WebAppData):
        user_id, player_id = user.user_id, user.player_id
        if web_config.daily.noticed:
            if not user.daily_db:
                daily = self.daily_service.create(
                    user_id,
                    player_id,
                    user_id,
                    status=TaskStatusEnum.STATUS_SUCCESS,
                    data=DailyData(notice_hour=web_config.daily.notice_hour).dict(),
                )
                await self.daily_service.add(daily)
            else:
                user.daily.noticed = False
                user.daily_db.status = TaskStatusEnum.STATUS_SUCCESS
        else:
            if user.daily_db:
                await self.daily_service.remove(user.daily_db)
                user.daily_db = None
                user.daily = None

    async def import_web_config(self, web_config: WebAppData):
        user_id, player_id = web_config.user_id, web_config.player_id
        user = await self.get_single_task_user(user_id, player_id)
        if web_config.resin:
            await self.import_web_config_resin(user, web_config)
        if web_config.daily:
            await self.import_web_config_daily(user, web_config)
        user.save()
        await self.update_task_user(user)

    async def do_get_notes_job(self, context: "ContextTypes.DEFAULT_TYPE"):
        include_status: List[TaskStatusEnum] = [
            TaskStatusEnum.STATUS_SUCCESS,
            TaskStatusEnum.TIMEOUT_ERROR,
        ]
        task_list = await self.get_all_task_users()
        for task_db in task_list:
            if task_db.status not in include_status:
                continue
            user_id = task_db.user_id
            player_id = task_db.player_id
            logger.debug("自动便签提醒 - 请求便签信息 user_id[%s] player_id[%s]", user_id, player_id)
            try:
                async with self.genshin_helper.genshin(user_id, player_id=player_id) as client:
                    text = await self.start_get_notes(client, task_db)
            except InvalidCookies:
                text = "自动便签提醒执行失败，Cookie无效"
                task_db.status = TaskStatusEnum.INVALID_COOKIES
            except SimnetBadRequest as exc:
                text = f"自动便签提醒执行失败，API返回信息为 {str(exc)}"
                task_db.status = TaskStatusEnum.GENSHIN_EXCEPTION
            except SimnetTimedOut:
                logger.info("用户 user_id[%s] 请求便签超时", user_id)
                continue
            except PlayerNotFoundError:
                logger.info("用户 user_id[%s] 玩家不存在 关闭并移除自动便签提醒", user_id)
                await self.remove_task_user(task_db)
                continue
            except CookiesNotFoundError:
                logger.info("用户 user_id[%s] cookie 不存在 关闭并移除自动便签提醒", user_id)
                await self.remove_task_user(task_db)
                continue
            except Exception as exc:
                logger.error("执行自动便签提醒时发生错误 user_id[%s]", user_id, exc_info=exc)
                text = "获取便签失败了呜呜呜 ~ 执行自动便签提醒时发生错误"
            else:
                task_db.status = TaskStatusEnum.STATUS_SUCCESS
            for idx, task_user_db in enumerate([task_db.resin_db, task_db.daily_db]):
                if task_user_db is None:
                    continue
                notice_text = text[idx] if isinstance(text, list) else text
                if not notice_text:
                    continue
                if task_user_db.chat_id < 0:
                    notice_text = (
                        f'<a href="tg://user?id={task_user_db.user_id}">'
                        f"NOTICE {task_user_db.user_id}</a>\n\n{notice_text}"
                    )
                try:
                    await context.bot.send_message(task_user_db.chat_id, notice_text, parse_mode=ParseMode.HTML)
                except BadRequest as exc:
                    logger.error("执行自动便签提醒时发生错误 user_id[%s] Message[%s]", user_id, exc.message)
                    task_user_db.status = TaskStatusEnum.BAD_REQUEST
                except Forbidden as exc:
                    logger.error("执行自动便签提醒时发生错误 user_id[%s] message[%s]", user_id, exc.message)
                    task_user_db.status = TaskStatusEnum.FORBIDDEN
                except Exception as exc:
                    logger.error("执行自动便签提醒时发生错误 user_id[%s]", user_id, exc_info=exc)
                    continue
            await self.update_task_user(task_db)

    async def get_migrate_data(self, old_user_id: int, new_user_id: int, _) -> Optional["TaskMigrate"]:
        return await TaskMigrate.create(
            old_user_id,
            new_user_id,
            self.resin_service,
        )


class TaskMigrate(IMigrateData):
    old_user_id: int
    new_user_id: int
    task_services: "TaskServices"
    need_migrate_tasks: List[TaskUser]

    async def migrate_data_msg(self) -> str:
        return f"定时任务数据 {len(self.need_migrate_tasks)} 条"

    async def migrate_data(self) -> bool:
        id_list = []
        for task in self.need_migrate_tasks:
            try:
                await self.task_services.update(task)
            except StaleDataError:
                id_list.append(str(task.id))
        if id_list:
            raise MigrateDataException(f"任务数据迁移失败：id {','.join(id_list)}")
        return True

    @staticmethod
    async def create_tasks(
        old_user_id: int,
        new_user_id: int,
        task_services: "TaskServices",
    ) -> List[TaskUser]:
        need_migrate, _ = await TaskMigrate.filter_sql_data(
            TaskUser,
            task_services.get_all_by_user_id,
            old_user_id,
            new_user_id,
            (TaskUser.user_id, TaskUser.type),
        )
        for i in need_migrate:
            i.user_id = new_user_id
        return need_migrate

    @classmethod
    async def create(
        cls,
        old_user_id: int,
        new_user_id: int,
        task_services: "TaskServices",
    ) -> Optional["TaskMigrate"]:
        need_migrate_tasks = await cls.create_tasks(old_user_id, new_user_id, task_services)
        if not need_migrate_tasks:
            return None
        self = cls()
        self.old_user_id = old_user_id
        self.new_user_id = new_user_id
        self.task_services = task_services
        self.need_migrate_tasks = need_migrate_tasks
        return self
