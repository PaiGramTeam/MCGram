def from_url_get_authkey(url: str) -> str:
    """从 UEL 解析 authkey
    :param url: URL
    :return: authkey
    """
    try:
        return url.split("record_id=")[1].split("&")[0]
    except IndexError:
        return url


def from_url_get_player_id(url: str) -> int:
    """从 URL 解析 player_id
    :param url: URL
    :return: player_id
    """
    try:
        return int(url.split("player_id=")[1].split("&")[0])
    except (IndexError, ValueError):
        return 0
