import datetime
from typing import Dict, List

# from core.services.history_data.models import HistoryData, HistoryDataTypeEnum, HistoryDataAbyss
from gram_core.base_service import BaseService
from gram_core.services.history_data.services import HistoryDataBaseServices

try:
    import ujson as jsonlib
except ImportError:
    import json as jsonlib


__all__ = (
    "HistoryDataBaseServices",
    # "HistoryDataAbyssServices",
)


# class HistoryDataAbyssServices(BaseService, HistoryDataBaseServices):
#     DATA_TYPE = HistoryDataTypeEnum.ABYSS.value
#
#     @staticmethod
#     def exists_data(data: HistoryData, old_data: List[HistoryData]) -> bool:
#         return any(d.data == data.data for d in old_data)
#
#     @staticmethod
#     def create(user_id: int, abyss_data: "SpiralAbyss", character_data: Dict[int, int]):
#         data = HistoryDataAbyss(abyss_data=abyss_data, character_data=character_data)
#         json_data = data.model_dump_json(by_alias=True)
#         return HistoryData(
#             user_id=user_id,
#             data_id=abyss_data.season,
#             time_created=datetime.datetime.now(),
#             type=HistoryDataAbyssServices.DATA_TYPE,
#             data=jsonlib.loads(json_data),
#         )
