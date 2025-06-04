from typing import List, Tuple, Dict, Any

from cachetools import cached, TTLCache

from app.api.endpoints.media import seasons
from app.chain.download import DownloadChain
from app.chain.media import MediaChain
from app.chain.search import SearchChain
from app.chain.subscribe import SubscribeChain
from app.core.config import settings
from app.core.metainfo import MetaInfo
from app.core.context import MediaInfo, Context, TorrentInfo
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import MediaType


class ShortCutModified(_PluginBase):
    # 插件名称
    plugin_name = "修改版快捷指令"
    # 插件描述
    plugin_desc = "IOS快捷指令，快速选片添加订阅"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/Sinterdial/MoviePilot-Plugins/main/icons/shortcut.png"
    # 插件版本
    plugin_version = "1.6.4"
    # 插件作者
    plugin_author = "Sinterdial"
    # 作者主页
    author_url = "https://github.com/Sinterdial"
    # 插件配置项ID前缀
    plugin_config_prefix = "ShortCutModified_"
    # 加载顺序
    plugin_order = 15
    # 可使用的用户级别
    auth_level = 1

    _enable: bool = False
    _plugin_key: str = ""
    _num: int = 3

    downloadchain: DownloadChain = None
    subscribechain: SubscribeChain = None
    mediachain: MediaChain = None
    searchchain: SearchChain = None

    torrents_list = []

    def init_plugin(self, config: dict = None):
        self._enable = config.get("enable") if config.get("enable") else False
        self._plugin_key = config.get("plugin_key") if config.get("plugin_key") else settings.API_TOKEN
        self._num = int(config.get("num")) if config.get("num") else 3

        self.downloadchain = DownloadChain()
        self.subscribechain = SubscribeChain()
        self.mediachain = MediaChain()
        self.searchchain = SearchChain()
        self.torrents_list = []

    def search(self, title: str, plugin_key: str) -> Any:
        """
        模糊搜索媒体信息列表
        """
        if self._plugin_key != plugin_key:
            logger.error(f"plugin_key错误：{plugin_key}")
            return []
        _, medias = self.mediachain.search(title=title)
        if medias:
            ret = []
            for media in medias[:self._num]:
                # 降低图片质量
                media.poster_path.replace("/original/", "/w200/")
                ret.append(media)
            return ret
        logger.info(f"{title} 没有找到结果")
        return []

    def get_seasons_list(self, title: str, tmdbid: str, type: str = "电视剧", plugin_key: str = "") -> Any:
        """
        查询季数
        """
        if self._plugin_key != plugin_key:
            msg = f"plugin_key错误：{plugin_key}"
            logger.error(msg)
            return msg
        # 元数据
        meta = MetaInfo(title=title)
        meta.tmdbid = tmdbid
        mediainfo: MediaInfo = self.chain.recognize_media(meta=meta, tmdbid=tmdbid,
                                                          mtype=MediaType(type))
        if not mediainfo:
            msg = f'未识别到媒体信息，标题：{title}，tmdb_id：{tmdbid}'
            logger.warn(msg)
            return msg

        # 查询缺失的媒体信息
        exist_flag, _ = self.downloadchain.get_no_exists_info(meta=meta, mediainfo=mediainfo)
        if exist_flag:
            msg = f'{mediainfo.title_year} 媒体库中已存在'
            logger.info(msg)
            return msg
        # 判断用户是否已经添加订阅
        if self.subscribechain.exists(mediainfo=mediainfo, meta=meta):
            msg = f'{mediainfo.title_year} 订阅已存在'
            logger.info(msg)
            return msg

        # 创建季列表
        seasons_list = list(range(1, mediainfo.number_of_seasons + 1))
        if seasons_list:
            return seasons_list
        else:
            return "未找到季数相关信息"

    def subscribe(self, title: str, tmdbid: str, type: str = "电视剧", season_to_subscribe: int = 1, plugin_key: str = "") -> Any:
        """
        添加订阅
        """
        def number_to_chinese(num: int) -> str:
            """
            将阿拉伯数字转换为中文大写数字表示

            支持将整数转换为对应的中文字符表达，包括零、一到九的基础数字，
            以及十、百、千、万、亿等单位组合。适用于需要将数字以中文形式展示的场景。

            参数:
                num (int): 需要转换的整数

            返回:
                str: 转换后的中文大写数字字符串

            示例:
                输入: 1234
                输出: "一千二百三十四"
            """
            if num == 0:
                return "零"

            # 定义基础数字和单位
            digits = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九"]
            units = ["", "十", "百", "千"]  # 十进制单位
            large_units = ["", "万", "亿", "万亿"]  # 大单位

            def chunk(number: int) -> str:
                """
                将小于10000的数字分解并转换为中文表示

                参数:
                    number (int): 小于10000的整数

                返回:
                    str: 中文表示的字符串片段
                """
                res = ""
                count = 0
                while number > 0:
                    digit = number % 10
                    if digit != 0:
                        res = digits[digit] + units[count] + res
                    else:
                        # 处理连续的零，避免出现多个“零”
                        if res and res[0] != '零':
                            res = '零' + res
                    number //= 10
                    count += 1
                return res

            result = ""
            chunk_index = 0
            while num > 0:
                part = num % 10000
                if part != 0:
                    # 对每个不超过10000的部分进行处理，并加上对应的大单位
                    result = chunk(part) + large_units[chunk_index] + result
                num //= 10000
                chunk_index += 1

            # 特殊情况处理，如"一十"应简化为"十"
            if result.startswith("一十"):
                result = result[1:]

            return result

        if self._plugin_key != plugin_key:
            msg = f"plugin_key错误：{plugin_key}"
            logger.error(msg)
            return msg
        # 元数据
        meta = MetaInfo(title=title)
        # 转化季数为大写
        season_info = "第" + number_to_chinese(season_to_subscribe) + "季"

        meta.tmdbid = tmdbid
        mediainfo: MediaInfo = self.chain.recognize_media(meta=meta, tmdbid=tmdbid,
                                                          mtype=MediaType(type))
        if not mediainfo:
            msg = f'未识别到媒体信息，标题：{title}，tmdb_id：{tmdbid}，季数: {season_info}'
            logger.warn(msg)
            return msg

        # 查询缺失的媒体信息
        exist_flag, _ = self.downloadchain.get_no_exists_info(meta=meta, mediainfo=mediainfo)
        if exist_flag:
            msg = f'{mediainfo.title_year} 媒体库中已存在'
            logger.info(msg)
            return msg
        # 判断用户是否已经添加订阅
        # 标记订阅季数
        meta.begin_season = season_to_subscribe

        if self.subscribechain.exists(mediainfo=mediainfo, meta=meta):
            msg = f'{mediainfo.title_year} 订阅已存在'
            logger.info(msg)
            return msg
        # 添加订阅
        sid, msg = self.subscribechain.add(title=mediainfo.title,
                                           year=mediainfo.year,
                                           mtype=mediainfo.type,
                                           tmdbid=mediainfo.tmdb_id,
                                           season=season_to_subscribe,
                                           exist_ok=True,
                                           username="快捷指令")

        if not msg:
            return f"{mediainfo.title_year} {season_info} 订阅成功"
        else:
            return msg

    @cached(TTLCache(maxsize=100, ttl=300))
    def torrents(self, tmdbid: int, type: str = None, area: str = "title",
                 season: str = None, plugin_key: str = None):
        """
        根据TMDBID精确搜索站点资源
        """
        if self._plugin_key != plugin_key:
            logger.error(f"plugin_key错误：{plugin_key}")
            return []
        if type:
            type = MediaType(type)
        if season:
            season = int(season)
        self.torrents_list = []

        if settings.RECOGNIZE_SOURCE == "douban":
            # 通过TMDBID识别豆瓣ID
            doubaninfo = self.mediachain.get_doubaninfo_by_tmdbid(tmdbid=tmdbid, mtype=type)
            if doubaninfo:
                torrents = self.searchchain.search_by_id(doubanid=doubaninfo.get("id"),
                                                         mtype=type, area=area, season=season)
            else:
                logger.error("未识别到豆瓣媒体信息")
                return []
        else:
            torrents = self.searchchain.search_by_id(tmdbid=tmdbid, mtype=type, area=area, season=season)

        if not torrents:
            logger.error("未搜索到任何资源")
            return []
        else:
            self.torrents_list = [torrent.to_dict() for torrent in torrents]

        return self.torrents_list[:50]

    def download(self, idx: int, plugin_key: str = None):
        if self._plugin_key != plugin_key:
            logger.error(f"plugin_key错误：{plugin_key}")
            return f"plugin_key错误：{plugin_key}"

        idx = idx - 1
        if idx > len(self.torrents_list):
            return "超出范围，添加失败"
        selected_info: dict = self.torrents_list[idx]
        # 媒体信息
        mediainfo = MediaInfo()
        mediainfo.from_dict(selected_info.get("media_info"))
        # 种子信息
        torrentinfo = TorrentInfo()
        torrentinfo.from_dict(selected_info.get("torrent_info"))
        # 元数据
        metainfo = MetaInfo(title=torrentinfo.title, subtitle=torrentinfo.description)

        # 上下文
        context = Context(
            meta_info=metainfo,
            media_info=mediainfo,
            torrent_info=torrentinfo
        )
        did = self.downloadchain.download_single(context=context, username="快捷指令")
        if not did:
            return f"添加下载失败"
        else:
            return f"{mediainfo.title_year} 添加下载成功"

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/search",
                "endpoint": self.search,
                "methods": ["GET"],
                "summary": "模糊搜索",
                "description": "模糊搜索",
            }, {
                "path": "/getSeasonsList",
                "endpoint": self.get_seasons_list,
                "methods": ["GET"],
                "summary": "查询剧集季信息",
                "description": "查询剧集季信息",
            },{
                "path": "/subscribe",
                "endpoint": self.subscribe,
                "methods": ["GET"],
                "summary": "添加订阅",
                "description": "添加订阅",
            }, {
                "path": "/torrents",
                "endpoint": self.torrents,
                "methods": ["GET"],
                "summary": "搜索种子",
                "description": "搜索种子",
            }, {
                "path": "/download",
                "endpoint": self.download,
                "methods": ["GET"],
                "summary": "下载任务",
                "description": "下载任务",
            }
        ]

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 2
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enable',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            }, {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'num',
                                            'label': '快捷指令列表展示数量',
                                            'placeholder': '数量过多会影响快捷指令速度',
                                        }
                                    }
                                ]
                            }, {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'plugin_key',
                                            'label': '插件plugin_key',
                                            'placeholder': '留空默认是mp的api_key',
                                        }
                                    }
                                ]
                            }
                        ]
                    }, {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '感谢Nest的想法和honue的原始代码。更新于 2025/6/4 安装完插件需要重启MoviePilot（1.8.3+） 只有订阅功能的快捷指令，暂无下载快捷指令。'
                                        }
                                    }
                                ]
                            }, {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '包含订阅和下载，快捷指令：https://www.icloud.com/shortcuts/467c61e122814fb3b910701c0ce276cc'
                                        }
                                    }
                                ]
                            }, {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '只有订阅功能，快捷指令：https://www.icloud.com/shortcuts/359d70d2fe554388a2efcdd9929a033b'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enable": self._enable,
            "num": self._num,
            "plugin_key": self._plugin_key,
        }

    def get_page(self) -> List[dict]:
        pass

    def get_state(self) -> bool:
        return self._enable

    def stop_service(self):
        pass
