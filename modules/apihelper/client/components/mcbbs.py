import asyncio
import os
import re
from typing import List

from ..base.hyperionrequest import HyperionRequest
from ...models.genshin.aliplayer_decrypt import authkey_to_encrypt_data, get_query_str
from ...models.genshin.hyperion import PostRecommend, PostInfo, ArtworkImage

__all__ = ("MCBBS",)


class MCBBS:
    """库街区相关API请求"""

    POST_FULL_URL = "https://api.kurobbs.com/forum/getPostDetail"
    GET_OFFICIAL_RECOMMENDED_POSTS_URL = "https://api.kurobbs.com/forum/companyEvent/findEventList"

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/90.0.4430.72 Safari/537.36"
    )

    def __init__(self, *args, **kwargs):
        self.client = HyperionRequest(headers=self.get_headers(), *args, **kwargs)

    @staticmethod
    def extract_post_id(text: str) -> int:
        """
        :param text:
            # https://www.kurobbs.com/postDetail.html?postId=1242810036910063616
            # https://www.kurobbs.com/mc/post/1242810036910063616
        :return: post_id
        """
        rgx = re.compile(r"(?:www\.)?kurobbs\.(.*)/(postDetail\.html\?postId=|[^.]+/post/)(?P<article_id>\d+)")
        matches = rgx.search(text)
        if matches is None:
            return -1
        entries = matches.groupdict()
        if entries is None:
            return -1
        try:
            art_id = int(entries.get("article_id"))
        except (IndexError, ValueError, TypeError):
            return -1
        return art_id

    @staticmethod
    def get_headers():
        return {
            "source": "android",
            "version": "2.2.0",
            "versionCode": "2200",
            "osVersion": "Android",
            "countryCode": "CN",
            "lang": "zh-Hans",
            "channelId": "4",
            "User-Agent": "okhttp/3.11.0",
            "devcode": "",
            "token": "",
        }

    @staticmethod
    def get_list_url_params(forum_id: int, is_good: bool = False, is_hot: bool = False, page_size: int = 20) -> dict:
        return {
            "forum_id": forum_id,
            "gids": 2,
            "is_good": is_good,
            "is_hot": is_hot,
            "page_size": page_size,
            "sort_type": 1,
        }

    @staticmethod
    def get_images_params(
        resize: int = 600, quality: int = 80, auto_orient: int = 0, interlace: int = 1, images_format: str = "jpg"
    ):
        """
        image/resize,s_600/quality,q_80/auto-orient,0/interlace,1/format,jpg
        :param resize: 图片大小
        :param quality: 图片质量
        :param auto_orient: 自适应
        :param interlace: 图片渐进显示
        :param images_format: 图片格式
        :return:
        """
        params = (
            f"image/resize,s_{resize}/quality,q_{quality}/auto-orient,"
            f"{auto_orient}/interlace,{interlace}/format,{images_format}"
        )
        return {"x-oss-process": params}

    async def get_official_recommended_posts(self, game_id: int, page_size: int = 10) -> list["PostRecommend"]:
        data = {"forumId": "9", "gameId": str(game_id), "pageSize": str(page_size), "pageNo": "1", "eventType": ""}
        response = await self.client.post(url=self.GET_OFFICIAL_RECOMMENDED_POSTS_URL, data=data)
        if "data" not in response:
            return []
        return [PostRecommend.parse(data_list) for data_list in response["data"]["list"]]

    async def get_post_info(self, post_id: int) -> PostInfo:
        data = {
            "isOnlyPublisher": "0",
            "postId": str(post_id),
            "showOrderType": "2",
        }
        response = await self.client.post(self.POST_FULL_URL, data=data)
        return PostInfo.paste_data(response)

    async def get_images_by_post_id(self, post_info: PostInfo) -> List[ArtworkImage]:
        art_list = []
        task_list = [
            self.download_image(post_info.post_id, post_info.image_urls[page], page)
            for page in range(len(post_info.image_urls))
        ]
        result_lists = await asyncio.gather(*task_list)
        for result_list in result_lists:
            for result in result_list:
                if isinstance(result, ArtworkImage):
                    art_list.append(result)

        def take_page(elem: ArtworkImage):
            return elem.page

        art_list.sort(key=take_page)
        return art_list

    async def download_image(self, art_id: int, url: str, page: int = 0) -> List[ArtworkImage]:
        filename = os.path.basename(url)
        _, _file_extension = os.path.splitext(filename)
        file_extension = _file_extension.lower()
        is_image = file_extension in ".jpg" or file_extension in ".jpeg" or file_extension in ".png"
        response = await self.client.get(
            url, params=self.get_images_params(resize=2000) if is_image else None, de_json=False
        )
        return ArtworkImage.gen(
            art_id=art_id, page=page, file_name=filename, file_extension=url.split(".")[-1], data=response.content
        )

    async def refresh_play_code(self, video_id: str) -> dict:
        data = {"videoId": str(video_id)}
        response = await self.client.post("https://api.kurobbs.com/forum/video/refreshPlayCode", data=data)
        play_auth = response.get("data", {}).get("playAuth", "")
        if not play_auth:
            raise ValueError("Failed to refresh play code.")
        return authkey_to_encrypt_data(play_auth)

    async def get_video_url(self, video_id: str) -> str:
        play_auth = await self.refresh_play_code(video_id)
        params = get_query_str(play_auth)
        url = f"https://vod.cn-shanghai.aliyuncs.com/?{params}"
        response = await self.client.get(url)
        info = response.get("PlayInfoList", {}).get("PlayInfo", [])
        if not info:
            raise ValueError("Failed to get video URL.")
        video_url = info[-1].get("PlayURL", "")
        if not video_url:
            raise ValueError("Video URL is empty.")
        return video_url

    async def close(self):
        await self.client.shutdown()
