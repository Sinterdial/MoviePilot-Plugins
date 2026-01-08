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
import datetime
import re
import traceback
from typing import Optional, Any, List, Dict, Tuple

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app import schemas
from app.chain.download import DownloadChain
from app.chain.subscribe import SubscribeChain
from app.core.config import settings
from app.core.context import MediaInfo, TorrentInfo, Context
from app.core.metainfo import MetaInfo
from app.helper.rss import RssHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import ExistMediaInfo
from app.schemas.types import SystemConfigKey, MediaType
from app.helper.sites import SitesHelper


def RecognizeMatchMetadata(result):
  """
    根据自定义规则刮削体育比赛信息
  """
  pass


class AutoSports(_PluginBase):
    # 插件名称
    plugin_name = "Sportscult 比赛自动下载及简单刮削"
    # 插件描述
    plugin_desc = "根据设置的球队名自动下载最新比赛，进行文件整理及简单的刮削"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/Sinterdial/MoviePilot-Plugins/main/icons/shortcut.png"
    # 插件版本
    plugin_version = "0.1.0"
    # 插件作者
    plugin_author = "Sinterdial"
    # 作者主页
    author_url = "https://github.com/Sinterdial"
    # 插件配置项ID前缀
    plugin_config_prefix = "AutoSports_"
    # 加载顺序
    plugin_order = 15
    # 可使用的用户级别
    auth_level = 1

    _enable: bool = False
    _teams_info: str = ""
    _cron: str = ""
    _notify: bool = False
    _onlyonce: bool = False
    _address: str = ""
    _include: str = ""
    _exclude: str = ""
    _proxy: bool = False
    _filter: bool = False
    _clear: bool = False
    _clearflag: bool = False
    _action: str = "download"
    _save_path: str = ""
    _size_range: str = ""

    downloadchain: DownloadChain = None
    subscribechain: SubscribeChain = None
    mediachain: MediaChain = None
    searchchain: SearchChain = None

    torrents_list = []

    @staticmethod
    def add_site() -> dict:
      """
          添加 Sportscult 站点索引
      """
      indexer: dict = {
        "id": "sportscult",
        "name": "Sportscult",
        "domain": "https://sportscult.org/index.php?page=torrents&search=barcelona&category=0&active=1&gold=0",
        "encoding": "UTF-8",
        "public": false,
        "search": {
          "paths": [
            {
              "path": "index.php",
              "method": "get"
            }
          ],
          "params": {
            "page": "torrent",
            "search": "{keyword}",
            "active": 1,
            "gold": 0
          },
          "batch": {
            "delimiter": " ",
            "space_replace": "_"
          }
        },
        "category": {
          "movie": [

          ],
          "tv": [
            {
                "id": 43,
                "cat": "La Liga",
                "desc": "西甲"
            },
            {
                "id": 60,
                "cat": "Champions League",
                "desc": "欧冠"
            }
          ]
        },
        "torrents": {
          "list": {
            "selector": "table.lista > tbody > tr:has(\"td.lista\")"
          },
          "fields": {
            "id": {
              "selector": "a[href*=\"torrent-details&id=\"]",
              "attribute": "href",
              "filters": [
                {
                  "name": "re_search",
                  "args": [
                    "\\d+",
                    0
                  ]
                }
              ]
            },
            "title_default": {
              "selector": "a[href*=\"torrent-details&id=\"]"
            },
            "title_optional": {
              "optional": true,
              "selector": "a[title][href*=\"torrent-details&id=\"]",
              "attribute": "title"
            },
            "title": {
              "text": "{% if fields['title_optional'] %}{{ fields['title_optional'] }}{% else %}{{ fields['title_default'] }}{% endif %}"
            },
            "details": {
              "selector": "a[href*=\"torrent-details&id=\"]",
              "attribute": "href"
            },
            "download": {
              "selector": "a[href*=\"download.php?id=\"]",
              "attribute": "href"
            },
            "imdbid": {
              "optional": true,
              "selector": "div.imdb_100 > a",
              "attribute": "href",
              "filters": [
                {
                  "name": "re_search",
                  "args": [
                    "tt\\d+",
                    0
                  ]
                }
              ]
            },
            "date_elapsed": {
              "selector": "td:nth-child(5)",
              "optional": true
            },
            "date_added": {
              "selector": "td:nth-child(5)",
              "attribute": "title",
              "optional": true
            },
            "size": {
              "selector": "td:nth-child(4)"
            },
            "seeders": {
              "selector": "td:nth-child(6) > a"
            },
            "leechers": {
              "selector": "td:nth-child(7) > a"
            },
            "grabs": {
              "selector": "td:nth-child(8) > a"
            },
            "downloadvolumefactor": {
              "case": {
                "img[alt=\"silver\"]": 0.5,
                "img[alt=\"gold\"]": 0,
                "*": 1
              }
            },
            "uploadvolumefactor": {
              "case": {
                "img[alt=\"silver\"]": 1,
                "img[alt=\"gold\"]": 1,
                "*": 1
              }
            },
            "description": {
              "optional": true,
              "selector": "a[href*=\"torrent-details&id=\"]",
              "contents": -1
            },
            "labels": {
              "optional": true,
              "selector": "a[href*=\"torrent-details&id=\"]"
            }
          }
        }
      }

      return indexer


    def init_plugin(self, config: dict = None):

      # 停止现有任务
      self.stop_service()

      sportscult_json = self.add_site()
      # 添加 SportsCult 站点
      SitesHelper().add_indexer(domain="sportscult.org", indexer=sportscult_json)


      # 配置
      if config:
        self.__validate_and_fix_config(config=config)
        self._teams_info = config.get("teams_info")
        self._enabled = config.get("enabled")
        self._cron = config.get("cron")
        self._notify = config.get("notify")
        self._onlyonce = config.get("onlyonce")
        self._address = config.get("address")
        self._include = config.get("include")
        self._exclude = config.get("exclude")
        self._proxy = config.get("proxy")
        self._filter = config.get("filter")
        self._clear = config.get("clear")
        self._action = config.get("action")
        self._save_path = config.get("save_path")
        self._size_range = config.get("size_range")

      if self._onlyonce:
        self._scheduler = BackgroundScheduler(timezone=settings.TZ)
        logger.info(f"自定义订阅服务启动，立即运行一次")
        self._scheduler.add_job(func=self.check, trigger='date',
                                run_date=datetime.datetime.now(
                                  tz=pytz.timezone(settings.TZ)) + datetime.timedelta(seconds=3)
                                )

        # 启动任务
        if self._scheduler.get_jobs():
          self._scheduler.print_jobs()
          self._scheduler.start()

      if self._onlyonce or self._clear:
        # 关闭一次性开关
        self._onlyonce = False
        # 记录清理缓存设置
        self._clearflag = self._clear
        # 关闭清理缓存开关
        self._clear = False
        # 保存设置
        self.__update_config()

    def get_state(self) -> bool:
      return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
      """
      定义远程控制命令
      :return: 命令关键字、事件、描述、附带数据
      """
      pass

    def get_api(self) -> List[Dict[str, Any]]:
      """
      获取插件API
      [{
          "path": "/xx",
          "endpoint": self.xxx,
          "methods": ["GET", "POST"],
          "summary": "API说明"
      }]
      """
      return [
        {
          "path": "/delete_history",
          "endpoint": self.delete_history,
          "methods": ["GET"],
          "summary": "删除自定义订阅历史记录"
        }
      ]

    def get_service(self) -> List[Dict[str, Any]]:
      """
      注册插件公共服务
      [{
          "id": "服务ID",
          "name": "服务名称",
          "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
          "func": self.xxx,
          "kwargs": {} # 定时器参数
      }]
      """
      if self._enabled and self._cron:
        return [{
          "id": "RssSubscribe",
          "name": "自定义订阅服务",
          "trigger": CronTrigger.from_crontab(self._cron),
          "func": self.check,
          "kwargs": {}
        }]
      elif self._enabled:
        return [{
          "id": "RssSubscribe",
          "name": "自定义订阅服务",
          "trigger": "interval",
          "func": self.check,
          "kwargs": {"minutes": 30}
        }]
      return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
      """
      拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
      """
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
                    'md': 4
                  },
                  'content': [
                    {
                      'component': 'VSwitch',
                      'props': {
                        'model': 'enabled',
                        'label': '启用插件',
                      }
                    }
                  ]
                },
                {
                  'component': 'VCol',
                  'props': {
                    'cols': 12,
                    'md': 4
                  },
                  'content': [
                    {
                      'component': 'VSwitch',
                      'props': {
                        'model': 'notify',
                        'label': '发送通知',
                      }
                    }
                  ]
                },
                {
                  'component': 'VCol',
                  'props': {
                    'cols': 12,
                    'md': 4
                  },
                  'content': [
                    {
                      'component': 'VSwitch',
                      'props': {
                        'model': 'onlyonce',
                        'label': '立即运行一次',
                      }
                    }
                  ]
                }
              ]
            },
            {
              'component': 'VRow',
              'content': [
                {
                  'component': 'VCol',
                  'props': {
                    'cols': 12,
                    'md': 6
                  },
                  'content': [
                    {
                      'component': 'VCronField',
                      'props': {
                        'model': 'cron',
                        'label': '执行周期',
                        'placeholder': '5位cron表达式，留空自动'
                      }
                    }
                  ]
                },
                {
                  'component': 'VCol',
                  'props': {
                    'cols': 12,
                    'md': 6
                  },
                  'content': [
                    {
                      'component': 'VSelect',
                      'props': {
                        'model': 'action',
                        'label': '动作',
                        'items': [
                          {'title': '订阅', 'value': 'subscribe'},
                          {'title': '下载', 'value': 'download'}
                        ]
                      }
                    }
                  ]
                }
              ]
            },
            {
              'component': 'VRow',
              'content': [
                {
                  'component': 'VCol',
                  'props': {
                    'cols': 12
                  },
                  'content': [
                    {
                      'component': 'VTextarea',
                      'props': {
                        'model': 'address',
                        'label': 'RSS地址',
                        'rows': 3,
                        'placeholder': '每行一个RSS地址'
                      }
                    }
                  ]
                }
              ]
            },
            {
              'component': 'VRow',
              'content': [
                {
                  'component': 'VCol',
                  'props': {
                    'cols': 12
                  },
                  'content': [
                    {
                      'component': 'VTextarea',
                      'props': {
                        'model': 'teams_info',
                        'label': '关注球队名',
                        'rows': 3,
                        'placeholder': '请输入关注球队的名称，一行一个（英文，关键字即可）'
                      }
                    }
                  ]
                }
              ]
            },
            {
              'component': 'VRow',
              'content': [
                {
                  'component': 'VCol',
                  'props': {
                    'cols': 12,
                    'md': 6
                  },
                  'content': [
                    {
                      'component': 'VTextField',
                      'props': {
                        'model': 'include',
                        'label': '包含',
                        'placeholder': '支持正则表达式'
                      }
                    }
                  ]
                },
                {
                  'component': 'VCol',
                  'props': {
                    'cols': 12,
                    'md': 6
                  },
                  'content': [
                    {
                      'component': 'VTextField',
                      'props': {
                        'model': 'exclude',
                        'label': '排除',
                        'placeholder': '支持正则表达式'
                      }
                    }
                  ]
                }
              ]
            },
            {
              'component': 'VRow',
              'content': [
                {
                  'component': 'VCol',
                  'props': {
                    'cols': 12,
                    'md': 6
                  },
                  'content': [
                    {
                      'component': 'VTextField',
                      'props': {
                        'model': 'size_range',
                        'label': '种子大小(GB)',
                        'placeholder': '如：3 或 3-5'
                      }
                    }
                  ]
                },
                {
                  'component': 'VCol',
                  'props': {
                    'cols': 12,
                    'md': 6
                  },
                  'content': [
                    {
                      'component': 'VTextField',
                      'props': {
                        'model': 'save_path',
                        'label': '保存目录',
                        'placeholder': '下载时有效，留空自动'
                      }
                    }
                  ]
                }
              ]
            },
            {
              'component': 'VRow',
              'content': [
                {
                  'component': 'VCol',
                  'props': {
                    'cols': 12,
                    'md': 4
                  },
                  'content': [
                    {
                      'component': 'VSwitch',
                      'props': {
                        'model': 'proxy',
                        'label': '使用代理服务器',
                      }
                    }
                  ]
                }, {
                  'component': 'VCol',
                  'props': {
                    'cols': 12,
                    'md': 4,
                  },
                  'content': [
                    {
                      'component': 'VSwitch',
                      'props': {
                        'model': 'filter',
                        'label': '使用订阅优先级规则',
                      }
                    }
                  ]
                },
                {
                  'component': 'VCol',
                  'props': {
                    'cols': 12,
                    'md': 4
                  },
                  'content': [
                    {
                      'component': 'VSwitch',
                      'props': {
                        'model': 'clear',
                        'label': '清理历史记录',
                      }
                    }
                  ]
                }
              ]
            }
          ]
        }
      ], {
        "enabled": False,
        "notify": True,
        "onlyonce": False,
        "cron": "*/30 * * * *",
        "address": "",
        "include": "",
        "exclude": "",
        "proxy": False,
        "clear": False,
        "filter": False,
        "action": "subscribe",
        "save_path": "",
        "size_range": ""
      }

    def get_page(self) -> List[dict]:
      """
      拼装插件详情页面，需要返回页面配置，同时附带数据
      """
      # 查询同步详情
      historys = self.get_data('history')
      if not historys:
        return [
          {
            'component': 'div',
            'text': '暂无数据',
            'props': {
              'class': 'text-center',
            }
          }
        ]
      # 数据按时间降序排序
      historys = sorted(historys, key=lambda x: x.get('time'), reverse=True)
      # 拼装页面
      contents = []
      for history in historys:
        title = history.get("title")
        poster = history.get("poster")
        mtype = history.get("type")
        time_str = history.get("time")
        contents.append(
          {
            'component': 'VCard',
            'content': [
              {
                "component": "VDialogCloseBtn",
                "props": {
                  'innerClass': 'absolute top-0 right-0',
                },
                'events': {
                  'click': {
                    'api': 'plugin/RssSubscribe/delete_history',
                    'method': 'get',
                    'params': {
                      'key': title,
                      'apikey': settings.API_TOKEN
                    }
                  }
                },
              },
              {
                'component': 'div',
                'props': {
                  'class': 'd-flex justify-space-start flex-nowrap flex-row',
                },
                'content': [
                  {
                    'component': 'div',
                    'content': [
                      {
                        'component': 'VImg',
                        'props': {
                          'src': poster,
                          'height': 120,
                          'width': 80,
                          'aspect-ratio': '2/3',
                          'class': 'object-cover shadow ring-gray-500',
                          'cover': True
                        }
                      }
                    ]
                  },
                  {
                    'component': 'div',
                    'content': [
                      {
                        'component': 'VCardTitle',
                        'props': {
                          'class': 'pa-1 pe-5 break-words whitespace-break-spaces'
                        },
                        'text': title
                      },
                      {
                        'component': 'VCardText',
                        'props': {
                          'class': 'pa-0 px-2'
                        },
                        'text': f'类型：{mtype}'
                      },
                      {
                        'component': 'VCardText',
                        'props': {
                          'class': 'pa-0 px-2'
                        },
                        'text': f'时间：{time_str}'
                      }
                    ]
                  }
                ]
              }
            ]
          }
        )

      return [
        {
          'component': 'div',
          'props': {
            'class': 'grid gap-3 grid-info-card',
          },
          'content': contents
        }
      ]

    def stop_service(self):
      """
      退出插件
      """
      try:
        if self._scheduler:
          self._scheduler.remove_all_jobs()
          if self._scheduler.running:
            self._scheduler.shutdown()
          self._scheduler = None
      except Exception as e:
        logger.error("退出插件失败：%s" % str(e))

    def delete_history(self, key: str, apikey: str):
      """
      删除同步历史记录
      """
      if apikey != settings.API_TOKEN:
        return schemas.Response(success=False, message="API密钥错误")
      # 历史记录
      historys = self.get_data('history')
      if not historys:
        return schemas.Response(success=False, message="未找到历史记录")
      # 删除指定记录
      historys = [h for h in historys if h.get("title") != key]
      self.save_data('history', historys)
      return schemas.Response(success=True, message="删除成功")

    def __update_config(self):
      """
      更新设置
      """
      self.update_config({
        "enabled": self._enabled,
        "notify": self._notify,
        "onlyonce": self._onlyonce,
        "cron": self._cron,
        "address": self._address,
        "include": self._include,
        "exclude": self._exclude,
        "proxy": self._proxy,
        "clear": self._clear,
        "filter": self._filter,
        "action": self._action,
        "save_path": self._save_path,
        "size_range": self._size_range
      })

    def check(self):
      """
      自动下载 SportsCult 球队最新内容
      """
      if not self._teams_info:
        logger.error(f"未输入球队名，不会进行任何操作，请输入球队名再试")
        return
      # 读取历史记录
      if self._clearflag:
        history = []
      else:
        history: List[dict] = self.get_data('history') or []

      searchchain = SearchChain()
      downloadchain = DownloadChain()
      subscribechain = SubscribeChain()

      sportscult_indexer: dict = {}

      for indexer in SitesHelper().get_indexers():
        # 检查站点索引开关
        if indexer.get("id") == "sportscult":
          sportscult_indexer = indexer

      for team_info in self._teams_info.split("\n"):
        # 在 SportsCult 搜索种子
        if not team_info:
          continue
        logger.info(f"开始在 Sportscult 搜索 {team_info} 的比赛...")

        results = searchchain.search_torrents(site=sportscult_indexer, keyword=team_info, mtype=MediaType.TV, page=1)

        if not results:
          logger.error(f"未获取到该球队相关比赛种子，请更换关键词再试试：{team_info}")
          return

        # 解析数据
        for result in results:
          try:
            title = result.get("title")
            description = result.get("description")
            enclosure = result.get("enclosure")
            link = result.get("link")
            size = result.get("size")
            pubdate: datetime.datetime = result.get("pubdate")
            # 检查是否处理过
            if not title or title in [h.get("key") for h in history]:
              continue
            # 检查规则
            if self._include and not re.search(r"%s" % self._include,
                                               f"{title} {description}", re.IGNORECASE):
              logger.info(f"{title} - {description} 不符合包含规则")
              continue
            if self._exclude and re.search(r"%s" % self._exclude,
                                           f"{title} {description}", re.IGNORECASE):
              logger.info(f"{title} - {description} 不符合排除规则")
              continue
            if self._size_range:
              sizes = [float(_size) * 1024 ** 3 for _size in self._size_range.split("-")]
              if len(sizes) == 1 and float(size) < sizes[0]:
                logger.info(f"{title} - 种子大小不符合条件")
                continue
              elif len(sizes) > 1 and not sizes[0] <= float(size) <= sizes[1]:
                logger.info(f"{title} - 种子大小不在指定范围")
                continue

            # 识别体育比赛信息
            mediainfo = RecognizeMatchMetadata(result)

            # 种子
            torrentinfo = TorrentInfo(
              title=title,
              description=description,
              enclosure=enclosure,
              page_url=link,
              size=size,
              pubdate=pubdate.strftime("%Y-%m-%d %H:%M:%S") if pubdate else None,
              site_proxy=self._proxy,
            )

            filter_groups = filter_groups = self.systemconfig.get(SystemConfigKey.SubscribeFilterRuleGroups)

            # 过滤种子
            if self._filter:
              result = self.chain.filter_torrents(
                rule_groups=filter_groups,
                torrent_list=[torrentinfo],
                mediainfo=mediainfo
              )
              if not result:
                logger.info(f"{title} {description} 不匹配过滤规则")
                continue
            # 媒体库已存在的剧集
            exist_info: Optional[ExistMediaInfo] = self.chain.media_exists(mediainfo=mediainfo)
            if mediainfo.type == MediaType.TV:
              if exist_info:
                exist_season = exist_info.seasons
                if exist_season:
                  exist_episodes = exist_season.get(meta.begin_season)
                  if exist_episodes and set(meta.episode_list).issubset(set(exist_episodes)):
                    logger.info(f'{mediainfo.title_year} {meta.season_episode} 己存在')
                    continue
            elif exist_info:
              # 电影已存在
              logger.info(f'{mediainfo.title_year} 己存在')
              continue
            # 下载或订阅
            if self._action == "download":
              # 添加下载
              result = downloadchain.download_single(
                context=Context(
                  meta_info=meta,
                  media_info=mediainfo,
                  torrent_info=torrentinfo,
                ),
                save_path=self._save_path,
                username="RSS订阅"
              )
              if not result:
                logger.error(f'{title} 下载失败')
                continue
            else:
              # 检查是否在订阅中
              subflag = subscribechain.exists(mediainfo=mediainfo, meta=meta)
              if subflag:
                logger.info(f'{mediainfo.title_year} {meta.season} 正在订阅中')
                continue
              # 添加订阅
              subscribechain.add(title=mediainfo.title,
                                 year=mediainfo.year,
                                 mtype=mediainfo.type,
                                 tmdbid=mediainfo.tmdb_id,
                                 season=meta.begin_season,
                                 exist_ok=True,
                                 username="RSS订阅")
            # 存储历史记录
            history.append({
              "title": f"{mediainfo.title} {meta.season}",
              "key": f"{title}",
              "type": mediainfo.type.value,
              "year": mediainfo.year,
              "poster": mediainfo.get_poster_image(),
              "overview": mediainfo.overview,
              "tmdbid": mediainfo.tmdb_id,
              "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
          except Exception as err:
            logger.error(f'刷新RSS数据出错：{str(err)} - {traceback.format_exc()}')
        logger.info(f"RSS {url} 刷新完成")
      # 保存历史记录
      self.save_data('history', history)
      # 缓存只清理一次
      self._clearflag = False

    def __log_and_notify_error(self, message):
      """
      记录错误日志并发送系统通知
      """
      logger.error(message)
      self.systemmessage.put(message, title="自定义订阅")

    def __validate_and_fix_config(self, config: dict = None) -> bool:
      """
      检查并修正配置值
      """
      size_range = config.get("size_range")
      if size_range and not self.__is_number_or_range(str(size_range)):
        self.__log_and_notify_error(f"自定义订阅出错，种子大小设置错误：{size_range}")
        config["size_range"] = None
        return False
      return True

    @staticmethod
    def __is_number_or_range(value):
      """
      检查字符串是否表示单个数字或数字范围（如'5', '5.5', '5-10' 或 '5.5-10.2'）
      """
      return bool(re.match(r"^\d+(\.\d+)?(-\d+(\.\d+)?)?$", value))

    @staticmethod
    def chinese_to_number(chinese_num: str) -> int:
        """
        将中文大写数字（如 第二十三季）转换为阿拉伯数字
        """
        char_to_digit = {
            '零': 0,
            '一': 1,
            '二': 2,
            '两': 2,
            '三': 3,
            '四': 4,
            '五': 5,
            '六': 6,
            '七': 7,
            '八': 8,
            '九': 9,
            '十': 10,
            '百': 100,
            '千': 1000,
            '万': 10000,
            '亿': 100000000
        }

        # 去除“第X季”的格式
        if chinese_num.startswith("第") and chinese_num.endswith("季"):
            chinese_num = chinese_num[1:-1]

        current_value = 0
        prev_value = 0

        i = 0
        while i < len(chinese_num):
            char = chinese_num[i]
            value = char_to_digit.get(char, None)

            if value is None:
                raise ValueError(f"不支持的字符：{char}")

            if value in [10, 100, 1000]:  # 处理“十百千”
                if prev_value == 0:
                    prev_value = 1  # 如“十五”中“十”前无数字，默认为1
                current_value += prev_value * value
                prev_value = 0
            else:
                prev_value = value
            i += 1

        current_value += prev_value  # 加上最后的个位数
        return current_value

    @staticmethod
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

