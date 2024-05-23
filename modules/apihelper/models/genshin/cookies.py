from typing import Optional, TypeVar

from pydantic import BaseModel

IntStr = TypeVar("IntStr", int, str)

__all__ = ("CookiesModel",)


class CookiesModel(BaseModel, frozen=False):
    """A model that represents the cookies used by the client."""

    account_id: Optional[IntStr] = None
    user_token: Optional[str] = None

    def to_dict(self):
        """Return the cookies as a dictionary."""
        return self.dict(exclude_defaults=True)

    def to_json(self):
        """Return the cookies as a JSON string."""
        return self.json(exclude_defaults=True)

    @property
    def user_id(self) -> Optional[int]:
        if self.account_id:
            return self.account_id
        return None

    def set_uid(self, user_id: int):
        """Set the user ID for the cookies."""
        if self.account_id is None and self.user_token:
            self.account_id = user_id
