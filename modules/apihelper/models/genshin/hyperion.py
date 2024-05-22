from io import BytesIO
from typing import Any, List, Optional

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, PrivateAttr

__all__ = ("ArtworkImage", "PostInfo")


class ArtworkImage(BaseModel):
    art_id: int
    page: int = 0
    data: bytes = b""
    file_name: Optional[str] = None
    file_extension: Optional[str] = None
    is_error: bool = False

    @property
    def format(self) -> Optional[str]:
        if not self.is_error:
            try:
                with BytesIO(self.data) as stream, Image.open(stream) as im:
                    return im.format
            except UnidentifiedImageError:
                pass
        return None

    @staticmethod
    def gen(*args, **kwargs) -> List["ArtworkImage"]:
        data = [ArtworkImage(*args, **kwargs)]
        if data[0].file_extension and data[0].file_extension in ["gif", "mp4"]:
            return data
        try:
            with BytesIO(data[0].data) as stream, Image.open(stream) as image:
                width, height = image.size
                crop_height = height
                crop_num = 1
                max_height = 10000 - width
                while crop_height > max_height:
                    crop_num += 1
                    crop_height = height / crop_num
                new_data = []
                for i in range(crop_num):
                    slice_image = image.crop((0, crop_height * i, width, crop_height * (i + 1)))
                    bio = BytesIO()
                    slice_image.save(bio, "png")
                    kwargs["data"] = bio.getvalue()
                    kwargs["file_extension"] = "png"
                    new_data.append(ArtworkImage(*args, **kwargs))
                return new_data
        except UnidentifiedImageError:
            return data


class PostInfo(BaseModel):
    _data: dict = PrivateAttr()
    post_id: int
    subject: str
    image_urls: List[str]
    created_at: str

    def __init__(self, _data: dict, **data: Any):
        super().__init__(**data)
        self._data = _data

    @classmethod
    def paste_data(cls, data: dict) -> "PostInfo":
        _data_post = data["data"]
        post = _data_post["postDetail"]
        post_id = post["id"]
        subject = post.get("postTitle", "")
        cover_images = post.get("coverImages", [])
        image_urls1 = [image["url"] for image in cover_images]
        post_content = post.get("postContent", [])
        image_urls2 = []
        skip_focus = False
        for image in post_content:
            content_type = image.get("contentType")
            if content_type == 1:
                if image.get("content") == "关注库街区《鸣潮》官方账号，获取更多《鸣潮》资讯。":
                    skip_focus = True
            elif content_type == 2:
                if skip_focus:
                    skip_focus = False
                    continue
                image_url = image.get("url")
                if image_url:
                    image_urls2.append(image_url)
        image_urls = image_urls2 if image_urls2 else image_urls1
        created_at = post.get("postTime", "")
        return PostInfo(
            _data=data,
            post_id=post_id,
            subject=subject,
            image_urls=image_urls,
            created_at=created_at,
        )

    def __getitem__(self, item):
        return self._data[item]
