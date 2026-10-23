import datetime
import io
import os
import random
import re
import string
from collections import defaultdict, deque
from aiohttp import web
import discord
from discord import app_commands
from discord.ext import commands, tasks
from PIL import Image, ImageDraw, ImageFont
from zoneinfo import ZoneInfo

# Intentsの設定
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

env_channel = os.getenv("CHANNEL_ID")
NOTIFICATION_CHANNEL_ID = (
    int(env_channel) if env_channel and env_channel.isdigit() else None
)

WELCOME_CHANNEL_ID = None
WELCOME_TITLE = "🎉 メンバーが参加しました！"
WELCOME_DESCRIPTION = "{member.mention} さん、**{guild.name}** へようこそ！\n\nルールを確認してサーバーをお楽しみください！"

LEAVE_GUILD_ID = None
LEAVE_CHANNEL_ID = None

CUSTOM_RESPONSES = {}
SPAM_TRACKER = defaultdict(deque)
SPAM_SETTINGS = {}

GLOBAL_CHANNELS = set()
GLOBAL_BANNED_USERS = set()

JST = ZoneInfo("Asia/Tokyo")

YOUTUBE_PATTERN = re.compile(
    r"https?://(?:www\.)?(?:youtube\.com/watch\?v=([\w-]+)|youtu\.be/([\w-]+))(\S*)"
)
X_PATTERN = re.compile(
    r"https?://(?:www\.)?(?:twitter\.com|x\.com)/([a-zA-Z0-9_]+/status/\d+)(\S*)"
)
INSTAGRAM_PATTERN = re.compile(
    r"https?://(?:www\.)?instagram\.com/(p|reel|tv|stories)/[\w-]+(\S*)"
)
TIKTOK_PATTERN = re.compile(r"https?://(?:www\.|vm\.|vt\.)?tiktok\.com/\S+")
FACEBOOK_PATTERN = re.compile(r"https?://(?:www\.)?(?:facebook\.com|fb\.watch)/\S+")
THREADS_PATTERN = re.compile(r"https?://(?:www\.)?threads\.net/\S+")


async def handle_ping(request):
  return web.Response(text="Bot is running!")


async def start_web_server():
  app = web.Application()
  app.add_routes([web.get("/", handle_ping)])
  runner = web.AppRunner(app)
  await runner.setup()
  port = int(os.getenv("PORT", 10000))
  site = web.TCPSite(runner, "0.0.0.0", port)
  await site.start()
  print(f"Webサーバーをポート {port} で起動しました（UptimeRobot用）")


daily_time = datetime.time(hour=0, minute=0, second=0, tzinfo=JST)


@tasks.loop(time=daily_time)
async def send_date_announcement():
  global NOTIFICATION_CHANNEL_ID
  if NOTIFICATION_CHANNEL_ID is None:
    return
  channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
  if channel is None:
    try:
      channel = await bot.fetch_channel(NOTIFICATION_CHANNEL_ID)
    except Exception as e:
      print(f"チャンネルの取得に失敗しました: {e}")
      return
  now = datetime.datetime.now(JST)
  weekdays = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"]
  weekday_str = weekdays[now.weekday()]
  message_text = f"📅 日付が変わりました！\n本日は **{now.month}月{now.day}日 ({weekday_str})** です。"
  await channel.send(message_text)


@send_date_announcement.before_loop
async def before_send_date_announcement():
  await bot.wait_until_ready()


@bot.tree.command(
    name="setchannel",
    description="日付お知らせを送信するチャンネルを現在のチャンネルに設定します",
)
@app_commands.default_permissions(manage_channels=True)
async def setchannel(interaction: discord.Interaction):
  global NOTIFICATION_CHANNEL_ID
  NOTIFICATION_CHANNEL_ID = interaction.channel.id
  await interaction.response.send_message(
      f"✅ このチャンネル（{interaction.channel.mention}）を日付お知らせの送信先として設定しました！",
      ephemeral=True,
  )


@bot.tree.command(
    name="setglobal",
    description="【管理者用】グローバルチャットの利用規約を表示し、同意パネルを設置します",
)
@app_commands.default_permissions(administrator=True)
async def setglobal(interaction: discord.Interaction):
  if not interaction.user.guild_permissions.administrator:
    await interaction.response.send_message(
        "❌ このコマンドを実行するにはサーバーの管理者権限が必要です。",
        ephemeral=True,
    )
    return

  embed = discord.Embed(
      title="🌐 グローバルチャット 利用規約・ルール",
      description=(
          "このチャンネルをグローバルチャットに接続します。\n\n"
          "**【利用規約・注意事項】**\n"
          "1. 荒らし行為、スパム、暴言、公序良俗に反する発言は禁止です。\n"
          "2. 他のサーバーのユーザーに対して迷惑をかける行為を行わないでください。\n"
          "3. ルールに違反した場合、グローバルチャットの利用が制限（BAN）されます。\n\n"
          "下の **「同意して参加する」** ボタンを押すことで、このチャンネルがグローバルチャットに参加します。"
      ),
      color=discord.Color.blue(),
  )
  view = GlobalAgreeView()
  await interaction.response.send_message(
      embed=embed, view=view, ephemeral=True
  )


class GlobalAgreeView(discord.ui.View):

  def __init__(self):
    super().__init__(timeout=None)

  @discord.ui.button(
      label="同意して参加する",
      style=discord.ButtonStyle.success,
      custom_id="global_agree_button",
  )
  async def agree_button(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    global GLOBAL_CHANNELS
    if not interaction.user.guild_permissions.administrator:
      await interaction.response.send_message(
          "❌ このボタンを押すには管理者権限が必要です。", ephemeral=True
      )
      return

    channel_id = interaction.channel.id
    if channel_id not in GLOBAL_CHANNELS:
      GLOBAL_CHANNELS.add(channel_id)

    await interaction.response.send_message(
        "🎉 グローバルチャットへの参加が完了しました！", ephemeral=True
    )

    join_embed = discord.Embed(
        title="🌐 グローバルチャット接続完了",
        description=(
            f"このチャンネル（{interaction.channel.mention}）がグローバルチャットに参加しました！\n"
            "他のサーバーのユーザーとメッセージの送受信が可能です。"
        ),
        color=discord.Color.green(),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    join_embed.set_footer(text=f"実行者: {interaction.user.display_name}")
    await interaction.channel.send(embed=join_embed)


@bot.tree.command(
    name="delglobal",
    description="【管理者用】現在のチャンネルをグローバルチャットから切断します",
)
@app_commands.default_permissions(manage_channels=True)
async def delglobal(interaction: discord.Interaction):
  global GLOBAL_CHANNELS
  channel_id = interaction.channel.id
  if channel_id in GLOBAL_CHANNELS:
    GLOBAL_CHANNELS.remove(channel_id)
  await interaction.response.send_message(
      "🔌 このチャンネルのグローバルチャット接続を解除しました。",
      ephemeral=True,
  )


@bot.tree.command(
    name="ping", description="Botの応答速度（レイテンシ）を確認します"
)
async def ping(interaction: discord.Interaction):
  latency = round(bot.latency * 1000)
  await interaction.response.send_message(
      f"🏓 ポン！ 応答速度: **{latency}ms**", ephemeral=True
  )


@bot.event
async def on_ready():
  print(f"ログインしました: {bot.user.name}")

  bot.add_view(CaptchaPanelView(None))
  bot.add_view(GlobalAgreeView())
  bot.add_view(RoleButtonView(None))

  try:
    synced = await bot.tree.sync()
    print(f"{len(synced)}個のスラッシュコマンドを同期しました。")
  except Exception as e:
    print(f"コマンドの同期に失敗しました: {e}")

  if not send_date_announcement.is_running():
    send_date_announcement.start()


@bot.event
async def on_message(message: discord.Message):
  if message.author.bot:
    return

  # --- グローバルチャットの転送処理 ---
  if message.channel.id in GLOBAL_CHANNELS:
    if message.author.id in GLOBAL_BANNED_USERS:
      return

    embed = discord.Embed(
        description=message.content,
        color=discord.Color.blue(),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    embed.set_author(
        name=f"{message.author.name} ({message.guild.name})",
        icon_url=(
            message.author.avatar.url
            if message.author.avatar
            else message.author.default_avatar.url
        ),
    )

    for ch_id in GLOBAL_CHANNELS:
      if ch_id == message.channel.id:
        continue
      target_channel = bot.get_channel(ch_id)
      if target_channel:
        try:
          await target_channel.send(embed=embed)
        except Exception:
          pass

  content = message.content

  # --- SNSリンク変換処理 ＆ Webhookなりすまし送信 ＆ リプライ再現 ---
  replaced = False

  if YOUTUBE_PATTERN.search(content):
    content = content.replace("youtube.com", "koutube.com").replace(
        "youtu.be", "koutube.com"
    )
    replaced = True
  elif X_PATTERN.search(content):
    content = content.replace("twitter.com", "fxtwitter.com").replace(
        "x.com", "fxtwitter.com"
    )
    replaced = True
  elif INSTAGRAM_PATTERN.search(content):
    content = content.replace("instagram.com", "oginstagram.com")
    replaced = True
  elif TIKTOK_PATTERN.search(content):
    content = re.sub(
        r"https?://(?:www\.|vm\.|vt\.)?tiktok\.com",
        "https://tnktok.com",
        content,
    )
    replaced = True
  elif FACEBOOK_PATTERN.search(content):
    content = content.replace("facebook.com", "facebed.com")
    replaced = True
  elif THREADS_PATTERN.search(content):
    content = content.replace("threads.net", "fixthreads.com")
    replaced = True

  if replaced:
    try:
      # ウェブフックを取得または作成
      webhooks = await message.channel.webhooks()
      webhook = discord.utils.get(webhooks, name="LinkFixerWebhook")
      if not webhook:
        webhook = await message.channel.create_webhook(name="LinkFixerWebhook")

      display_name = message.author.display_name
      avatar_url = message.author.display_avatar.url

      # 返信（リプライ）情報の取得・引用構築
      prefix = ""
      if message.reference:
        try:
          ref_msg = message.reference.cached_message
          if not ref_msg and message.channel:
            ref_msg = await message.channel.fetch_message(
                message.reference.message_id
            )
          if ref_msg:
            ref_author = ref_msg.author.display_name
            ref_content = ref_msg.content.replace("\n", " ")
            if len(ref_content) > 30:
              ref_content = ref_content[:30] + "..."
            prefix = f"> ↪️ **{ref_author}** への返信\n> {ref_content}\n\n"
        except Exception:
          pass

      final_content = prefix + content

      # Webhook経由で送信者の名前とアイコンで送信
      await webhook.send(
          content=final_content, username=display_name, avatar_url=avatar_url
      )

      # 元のメッセージを削除
      await message.delete()

    except discord.Forbidden:
      print(
          "【権限エラー】Webhookの作成・送信、またはメッセージの削除権限がありません。"
      )
    except Exception as e:
      print(f"Webhook送信エラー: {e}")


async def main():
  token = os.getenv("DISCORD_TOKEN")
  if not token:
    print("エラー: DISCORD_TOKEN が環境変数に設定されていません。")
    return

  import asyncio
  await asyncio.gather(start_web_server(), bot.start(token))


if __name__ == "__main__":
  import asyncio

  asyncio.run(main())