import os
import time
import asyncio
import json
import math

from datetime import datetime

from core.database.plugin import PluginBaseModel
from core.database.group import GroupBaseModel
from core.database.messages import *
from core.util import TimeRecorder
from core import send_to_console_channel, Message, Chain, AmiyaBotPluginInstance, bot as main_bot, OneBot11Instance

from amiyabot.database import *
from core.database.bot import Admin
from amiyabot.network.httpRequests import http_requests


@table
class TimerGroupSetting(GroupBaseModel):
    group_id: str = CharField(primary_key=True)
    bot_id: str = CharField(null=True)
    activity_remind: int = IntegerField(default=0, null=True)


@table
class ExtraTimers(PluginBaseModel):
    name: str = CharField(primary_key=True)
    time: int = IntegerField(default=0, null=False)
    info: str = CharField(default='{}', null=True)


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


class PraseDateException(Exception):
    ...


def parse_date(date_str):
    def try_prase(fstr) -> datetime:
        nonlocal date_str

        try:
            return datetime.strptime(date_str, fstr)
        except:
            return None

    def complete(dt: datetime, level: int, have_time) -> datetime:
        now = datetime.now()
        curyear = now.year
        curmonth = now.month
        curday = now.day

        dt = dt.replace(second=0)

        if not have_time:
            dt = dt.replace(hour=16, minute=0)

        if level >= 1:
            dt = dt.replace(year=curyear)
        if level >= 2:
            dt = dt.replace(month=curmonth)
        if level >= 3:
            dt = dt.replace(day=curday)

        if dt < now:
            if level >= 3:
                return dt.replace(day=curday+1)
            if level >= 2:
                return dt.replace(month=curmonth+1)
            if level >= 1:
                return dt.replace(year=curyear+1)
        else:
            return dt

    prase_level = [
        '%Y-%m-%d %H:%M',
        '%m-%d %H:%M',
        '%d %H:%M',
        '%H:%M',
    ]

    prase_level_without_time = [
        '%Y-%m-%d',
        '%m-%d',
        '%d'
    ]

    for matcher, have_time in [(prase_level, True), (prase_level_without_time, False)]:
        for level, fstr in enumerate(matcher):
            if result := try_prase(fstr):
                return complete(result, level, have_time).timestamp()

    raise PraseDateException('')


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

    asyncio.create_task(fresh())
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


@bot.on_message(group_id='remind', keywords=['添加提醒'], level=5)
async def _(data: Message):
    if not bool(Admin.get_or_none(account=data.user_id)):
        return Chain(data).text('抱歉，自定义活动提醒只能由兔兔管理员编辑~')

    try:
        _, name, time = data.text.split(' ', 2)
        time = parse_date(time)

        timer: ExtraTimers = ExtraTimers.get_or_none(
            name=name
        )
        if timer:
            ExtraTimers.update(time=time).where(
                ExtraTimers.name == name
            ).execute()
        else:
            ExtraTimers.create(
                name=name, time=time
            )
        asyncio.create_task(fresh())
        return Chain(data).text('成功添加了提醒~')
    except PraseDateException as e:
        return Chain(data).text('解析时间字符串失败，添加提醒失败')
    except Exception as e:
        return Chain(data).text('添加提醒失败')


@bot.on_message(group_id='remind', keywords=['删除提醒'], level=5)
async def _(data: Message):
    if not bool(Admin.get_or_none(account=data.user_id)):
        return Chain(data).text('抱歉，自定义活动提醒只能由兔兔管理员编辑~')

    try:
        _, name = data.text.split(' ', 2)
        ExtraTimers.delete().where(ExtraTimers.name == name).execute()
        asyncio.create_task(fresh())
        return Chain(data).text('成功删除了提醒~')
    except Exception as e:
        return Chain(data).text('删除提醒失败')


@bot.timed_task(each=3600, run_when_added=True)
async def _(_):
    await fresh()


async def fresh():
    activity_list = JsonData.get_json_data('activity_table')['basicInfo']
    act_timer_list: list[tuple] = []
    custom_timer_list: list[tuple] = []
    all_timer_list: list[tuple] = []

    for activity in activity_list.values():
        startTime = activity['startTime']
        endTime = activity['endTime']
        rewardEndTime = activity['rewardEndTime']
        name = activity['name']

        now = time.time()

        if startTime > now:
            act_timer_list.append((name, startTime))
        if endTime > now:
            act_timer_list.append((f'{name}结束', endTime))
        if rewardEndTime > now:
            act_timer_list.append((f'{name}商店关闭', endTime))

    for custom_timer in ExtraTimers.select().where(ExtraTimers.time >= now):
        custom_timer_list.append((custom_timer.name, custom_timer.time))

    act_timer_list = sorted(act_timer_list, key=lambda x: x[1])
    custom_timer_list = sorted(custom_timer_list, key=lambda x: x[1])
    all_timer_list += custom_timer_list
    if bot.get_config('activityAutoTimer'):
        all_timer_list += act_timer_list

    if all_timer_list:
        timer_name, timer_time = all_timer_list[0]
        timer_time = int((timer_time-time.time()) / 3600)
        day = int(timer_time/24)
        hour = timer_time - day*24
        new_nickname_str = '{} | 距{} {}d{}h'.format(bot.get_config('amiyaNickName'), timer_name, day, hour)
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
