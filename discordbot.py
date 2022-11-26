import asyncio
from typing import Dict, List, Optional, Union
import discord
from discord.ext import commands, tasks
import os
import traceback
import re
import emoji
import json
import jaconv
import cyrtranslit
import pinyin
import pycld2 as cld2
from ko_pron import romanise
from english_to_kana import EnglishToKana
import signal

DEBUG = False
pastauthor: Dict[int, discord.abc.User] = {}
bot_tasks: List[tasks.Loop] = []

if not DEBUG:
    pass
    prefix = os.getenv('DISCORD_BOT_PREFIX', default='🦑')
    token = os.environ['DISCORD_BOT_TOKEN']
    voicevox_key = os.environ['VOICEVOX_KEY']
    voicevox_speaker = os.getenv('VOICEVOX_SPEAKER', default='2')
else:
    prefix = "/"
    token = os.environ['GEKKA_DISCORD_BOT_TOKEN']
    voicevox_key = os.environ['GEKKA_VOICEVOX_KEY']
    voicevox_speaker = "2"

# intents = discord.Intents(all=True)
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=prefix, intents=intents)
with open('emoji_ja.json', encoding='utf-8') as file:
    emoji_dataset = json.load(file)
with open("data/ignore_users.json", "r", encoding="utf-8") as f:
    ignore_users = json.load(f)


ETK = EnglishToKana()


@bot.event
async def on_ready():
    if bot.user is None:
        raise Exception("seems failed to login")

    print('Logged in as ' + bot.user.name)
    presence = f'{prefix}ヘルプ | 0/{len(bot.guilds)}サーバー'
    await bot.change_presence(activity=discord.Game(name=presence))


@commands.is_owner()
@bot.command()
async def shutdown(ctx: Optional[commands.Context] = None):
    if ctx:
        await ctx.send("shutdown the bot...")
    print("shutdown bot...")
    await ready_for_disconnect()
    await bot.close()


async def ready_for_disconnect():
    for g in bot.guilds:
        if g.voice_client:
            print(
                f"disconnected voice channel from '{g.voice_client.channel}' at '{g.name}'")
            await mp3_player(
                "ここでお知らせです。プロジェクトに更新が入りましたので、Botは再起動を始めます。それでは、さようなら", g.voice_client, None)
            await g.voice_client.disconnect(force=False)
            await asyncio.sleep(5)
            if g.voice_client:
                await g.voice_client.disconnect(force=True)

    await bot.change_presence(status=discord.Status.dnd, activity=discord.Game("now restarting..."))


@bot.event
async def on_guild_join(guild: discord.Guild):
    presence = f'{prefix}ヘルプ | {len(bot.voice_clients)}/{len(bot.guilds)}サーバー'
    await bot.change_presence(activity=discord.Game(name=presence))


@bot.event
async def on_guild_remove(guild: discord.Guild):
    presence = f'{prefix}ヘルプ | {len(bot.voice_clients)}/{len(bot.guilds)}サーバー'
    await bot.change_presence(activity=discord.Game(name=presence))


@bot.command(alias=["connect", "con"])
async def 接続(ctx: commands.Context):
    if ctx.message.guild is not None and isinstance(ctx.author, discord.Member):
        if ctx.author.voice is None:
            await ctx.send('ボイスチャンネルに接続してから呼び出してください。')
        else:
            if ctx.message.guild.voice_client:
                if ctx.author.voice.channel == ctx.message.guild.voice_client.channel:
                    await ctx.send('接続済みです。')
                else:
                    if ctx.author.voice.channel is not None and ctx.voice_client:
                        await ctx.voice_client.disconnect(force=True)
                        await asyncio.sleep(0.5)
                        await ctx.author.voice.channel.connect()
            else:
                if ctx.author.voice.channel is not None:
                    await ctx.author.voice.channel.connect()


@bot.command(alias=["disconnect", "discon", "dis"])
async def 切断(ctx: commands.Context):
    if ctx.message.guild:
        if ctx.voice_client is None:
            await ctx.send('ボイスチャンネルに接続していません。')
        else:
            await ctx.voice_client.disconnect(force=False)


def text_converter(text: str, message: Optional[discord.Message] = None, now_author: Optional[discord.Member] = None) -> str:
    """
    the converter of text for voicevox
    """
    print("got text:", text, end="")
    detected_lang: Optional[str] = None
    try:
        isReliable, textBytesFound, details = cld2.detect(text)
        detected_lang = details[0][1]
    except cld2.error as e:
        # print("ignore error:", e)
        pass

    # Replace new line
    text = text.replace('\n', '、')
    if isinstance(message, discord.Message):
        # Add author's name
        if now_author:
            text = message.author.display_name + '、' + text

        # Replace mention to user
        user_mentions: List[Union[discord.Member,
                                  discord.User]] = message.mentions
        for um in user_mentions:
            text = text.replace(
                f"<@{um.id}>", f"、{um.display_name}さんへのメンション")

        # Replace mention to role
        role_mentions: List[discord.Role] = message.role_mentions
        for rm in role_mentions:
            text = text.replace(
                rm.mention, f"、{rm.name}へのメンション")

    # Replace Unicode emoji
    text = re.sub(r'[\U0000FE00-\U0000FE0F]', '', text)
    text = re.sub(r'[\U0001F3FB-\U0001F3FF]', '', text)
    for char in text:
        # if char in emoji.UNICODE_EMOJI['en'] and char in emoji_dataset:
        if emoji.is_emoji(char) and char in emoji_dataset:
            text = text.replace(char, emoji_dataset[char]['short_name'])

    # Replace Discord emoji
    pattern = r'<:([a-zA-Z0-9_]+):\d+>'
    match = re.findall(pattern, text)
    for emoji_name in match:
        emoji_read_name = emoji_name.replace('_', ' ')
        text = re.sub(rf'<:{emoji_name}:\d+>',
                      f'、{emoji_read_name}、', text)

    # Replace URL
    pattern = r'https://tenor.com/view/[\w/:%#\$&\?\(\)~\.=\+\-]+'
    text = re.sub(pattern, '画像', text)
    pattern = r'https?://[\w/:%#\$&\?\(\)~\.=\+\-]+(\.jpg|\.jpeg|\.gif|\.png|\.bmp)'
    text = re.sub(pattern, '、画像', text)
    pattern = r'https?://[\w/:%#\$&\?\(\)~\.=\+\-]+'
    text = re.sub(pattern, '、ユーアールエル', text)

    # Replace spoiler
    pattern = r'\|{2}.+?\|{2}'
    text = re.sub(pattern, '伏せ字', text)

    # Replace laughing expression
    if text[-1:] == 'w' or text[-1:] == 'W' or text[-1:] == 'ｗ' or text[-1:] == 'W':
        while text[-2:-1] == 'w' or text[-2:-1] == 'W' or text[-2:-1] == 'ｗ' or text[-2:-1] == 'W':
            text = text[:-1]
        text = text[:-1] + '、ワラ'

    # Add attachment presence
    if isinstance(message, discord.Message):
        for attachment in message.attachments:
            if attachment.filename.endswith((".jpg", ".jpeg", ".gif", ".png", ".bmp")):
                text += '、画像'
            else:
                text += '、添付ファイル'

    # Text converting from every lang.
    if detected_lang == "zh":
        text = pinyin.get(text, format="strip", delimiter="")
    elif detected_lang == "ko":
        text = romanise(text, "rr")
    else:
        text = cyrtranslit.to_latin(text, 'ru')
        etk_text = ETK.convert(text)
        a2k_text = jaconv.alphabet2kana(text)
        text = jaconv.alphabet2kana(etk_text.lower())
        # text = romanise(text, "rr")

    text = jaconv.alphabet2kana(text)
    print(" -> ", text, f" (detected langcode: {detected_lang})")
    return text


async def mp3_player(text: str, voice_client: discord.VoiceClient, message: Optional[discord.Message] = None):
    """
    playing a mp3 exported voicevox
    """
    mp3url = f'https://api.su-shiki.com/v2/voicevox/audio/?text={text}&key={voicevox_key}&speaker={voicevox_speaker}&intonationScale=1'
    while voice_client.is_playing():
        await asyncio.sleep(0.5)
    try:
        voice_client.play(discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(mp3url), volume=0.75))
    except OSError as e:
        print("audio playing stopped cuz fatal error occurred:", e)
        if message:
            await message.reply(f"エラーが発生したので再生をストップしました、ごめんなさい！ ><\n```\n{e.strerror}\n```")


@bot.event
async def on_message(message: discord.Message):
    if message.guild:  # if message is sent in guild
        if message.guild.voice_client:  # if bot is in voice channel
            if isinstance(message.author, discord.Member) and not message.author.bot and message.author.id not in ignore_users["user_ids"]:
                if not message.content.startswith(prefix) and message.author.guild.voice_client:
                    author: Optional[discord.Member] = None
                    if message.guild.id not in pastauthor.keys() or pastauthor[message.guild.id] == message.author:
                        pastauthor[message.guild.id] = message.author
                        author = message.author

                    text = message.content
                    text = text_converter(text, message, author)
                    await mp3_player(text, message.guild.voice_client)
    await bot.process_commands(message)


@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if before.channel is None and bot.user:
        if member.id == bot.user.id:
            presence = f'{prefix}ヘルプ | {len(bot.voice_clients)}/{len(bot.guilds)}サーバー'
            await bot.change_presence(activity=discord.Game(name=presence))
        else:
            if member.guild.voice_client is None:
                await asyncio.sleep(0.5)
                if after.channel is not None:
                    await after.channel.connect()
            else:
                voice_channel = member.guild.voice_client.channel
                if isinstance(voice_channel, discord.VoiceChannel):
                    if voice_channel is after.channel:
                        text = member.display_name + 'さんが入室しました'
                        text = text_converter(text)
                        await mp3_player(text, member.guild.voice_client)
    elif after.channel is None:
        if member.id == bot.user.id:
            presence = f'{prefix}ヘルプ | {len(bot.voice_clients)}/{len(bot.guilds)}サーバー'
            await bot.change_presence(activity=discord.Game(name=presence))
        else:
            if member.guild.voice_client:
                voice_channel = member.guild.voice_client.channel
                if isinstance(voice_channel, discord.VoiceChannel):
                    if voice_channel is before.channel:
                        if len(voice_channel.members) == 1:
                            await asyncio.sleep(0.5)
                            await member.guild.voice_client.disconnect(force=False)
                        else:
                            text = member.display_name + 'さんが退室しました'
                            text = text_converter(text)
                            await mp3_player(text, member.guild.voice_client)
    elif before.channel != after.channel:
        if member.guild.voice_client:
            voice_channel = member.guild.voice_client.channel
            if isinstance(voice_channel, discord.VoiceChannel):
                if voice_channel is before.channel:
                    if len(voice_channel.members) == 1 or (member.voice and member.voice.self_mute):
                        await asyncio.sleep(0.5)
                        await member.guild.voice_client.disconnect(force=False)
                        await asyncio.sleep(0.5)
                        await after.channel.connect()


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    orig_error = getattr(error, 'original', error)
    error_msg = ''.join(
        traceback.TracebackException.from_exception(orig_error).format())
    await ctx.send(error_msg)


@bot.command(alias=["help", "h"])
async def ヘルプ(ctx: commands.Context):
    if bot.user:
        message = f"◆◇◆{bot.user.name}の使い方◆◇◆\n" \
            + f"{prefix}＋コマンドで命令できます。\n" \
            + f"{prefix}接続：ボイスチャンネルに接続します。\n"\
            + f"{prefix}切断：ボイスチャンネルから切断します。\n"
        await ctx.send(message)

if __name__ == "__main__":
    # bot.run(token)

    print("starting...")
    # dotenv.load_dotenv(".env")

    if token:
        loop = bot.loop

        async def exiting(signame):
            print(f"got {signame};")
            print(f"canceling all tasks...")
            for task in bot_tasks:
                try:
                    task.cancel()
                except asyncio.CancelledError:
                    print("cancelled error happend. ignoring it.")
                    pass
            # print(f"shutdown now...")
            await shutdown()  # type: ignore
        for signame in ('SIGINT', 'SIGTERM'):
            loop.add_signal_handler(getattr(signal, signame),
                                    lambda: asyncio.ensure_future(exiting(signame)))
        try:
            loop.run_until_complete(bot.start(token))
        finally:
            loop.close()
        print("stopping...")
    else:
        raise Exception("token is not set.")
