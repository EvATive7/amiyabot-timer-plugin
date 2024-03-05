import os
import time
import asyncio
import json
import math

from core.database.group import GroupBaseModel
from core.database.messages import *
from core.util import TimeRecorder
from core import send_to_console_channel, Message, Chain, AmiyaBotPluginInstance, bot as main_bot, OneBot11Instance

from amiyabot.database import *
from amiyabot.network.httpRequests import http_requests


@table
class TimerGroupSetting(GroupBaseModel):
    group_id: str = CharField(primary_key=True)
    bot_id: str = CharField(null=True)
    activity_remind: int = IntegerField(default=0, null=True)


curr_dir = os.path.dirname(__file__)

gamedata_path = 'resource/gamedata'

last_nick_name = ''


class TimerPluginInstance(AmiyaBotPluginInstance):
    ...


bot = TimerPluginInstance(
    name='Timer',
    version='1.0',
    plugin_id='arknights-activity-remind',
    plugin_type='',
    description='通过修改群名片的方式进行事件的倒计时提醒，依赖于插件【明日方舟数据解析】。仅支持LLOnebot。',
    document=f'{curr_dir}/README.md',
    global_config_schema=f'{curr_dir}/config_schema.json',
    global_config_default=f'{curr_dir}/config_default.yaml'
)


class JsonData:
    cache = {}

    @classmethod
    def get_json_data(cls, name: str, folder: str = 'excel'):
        if name not in cls.cache:
            path = f'resource/gamedata/gamedata/{folder}/{name}.json'
            if os.path.exists(path):
                with open(path, mode='r', encoding='utf-8') as src:
                    cls.cache[name] = json.load(src)
            else:
                return {}

        return cls.cache[name]

    @classmethod
    def clear_cache(cls, name: str = None):
        if name:
            del cls.cache[name]
        else:
            cls.cache = {}


@bot.on_message(group_id='remind', keywords=['开启提醒'], level=5)
async def _(data: Message):
    if not data.is_admin:
        return Chain(data).text('抱歉，活动提醒只能由管理员设置')

    channel: TimerGroupSetting = TimerGroupSetting.get_or_none(
        group_id=data.channel_id, bot_id=data.instance.appid
    )
    if channel:
        TimerGroupSetting.update(activity_remind=1).where(
            TimerGroupSetting.group_id == data.channel_id,
            TimerGroupSetting.bot_id == data.instance.appid,
        ).execute()
    else:
        if TimerGroupSetting.get_or_none(group_id=data.channel_id):
            TimerGroupSetting.update(bot_id=data.instance.appid, activity_remind=1).where(
                TimerGroupSetting.group_id == data.channel_id
            ).execute()
        else:
            TimerGroupSetting.create(
                group_id=data.channel_id, bot_id=data.instance.appid, activity_remind=1
            )

    return Chain(data).text('已在本群开启活动提醒')


@bot.on_message(group_id='remind', keywords=['关闭提醒'], level=5)
async def _(data: Message):
    if not data.is_admin:
        return Chain(data).text('抱歉，活动提醒只能由管理员设置')

    TimerGroupSetting.update(activity_remind=0).where(TimerGroupSetting.group_id == data.channel_id,
                                                      TimerGroupSetting.bot_id == data.instance.appid).execute()

    return Chain(data).text('已在本群关闭活动提醒')


@bot.on_message(group_id='remind', keywords=['刷新提醒'], level=5)
async def _(data: Message):
    if not data.is_admin:
        return Chain(data).text('抱歉，活动提醒只能由管理员设置')

    asyncio.create_task(fresh())

    return Chain(data).text('已经启动刷新~')


@bot.timed_task(each=3600, run_when_added=True)
async def _(_):
    await fresh()


async def fresh():
    activity_list = JsonData.get_json_data('activity_table')['basicInfo']
    consider_list: list[tuple] = []

    for activity in activity_list.values():
        startTime = activity['startTime']
        endTime = activity['endTime']
        rewardEndTime = activity['rewardEndTime']
        name = activity['name']

        now = time.time()

        if startTime > now:
            consider_list.append((name, startTime))
        if endTime > now:
            consider_list.append((f'{name}结束', endTime))
        if rewardEndTime > now:
            consider_list.append((f'{name}商店关闭', endTime))

    if consider_list:
        consider_list = sorted(consider_list, key=lambda x: x[1])
        timer_name, timer_time = consider_list[0]
        new_nickname_str = '{} | 距{}{}h'.format(bot.get_config('amiyaNickName'), timer_name, int((timer_time-time.time()) / 3600))
    else:
        new_nickname_str = bot.get_config('amiyaNickName')

    if new_nickname_str == last_nick_name:
        return

    # Start Push
    target: List[TimerGroupSetting] = TimerGroupSetting.select().where(TimerGroupSetting.activity_remind == 1)

    if not target:
        return

    for target_item in target:
        channel_id = target_item.group_id
        bot_id = target_item.bot_id

        instance = main_bot[bot_id]
        if not instance:
            continue
        instance = instance.instance

        if type(instance) == OneBot11Instance:
            session = instance.session
            url = f'http://{instance.host}:{instance.http_port}/set_group_card'

            result = await http_requests.post(
                url,
                {
                    "group_id": channel_id,
                    "user_id": bot_id,
                    "card": new_nickname_str
                },
                {
                    'Authorization': f'Bearer {instance.token}'
                }
            )
            pass
