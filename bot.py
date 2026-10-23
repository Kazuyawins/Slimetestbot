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

# ウェルカムメッセージの設定保持用変数
WELCOME_CHANNEL_ID = None
WELCOME_TITLE = "🎉 メンバーが参加しました！"
WELCOME_DESCRIPTION = "{member.mention} さん、**{guild.name}** へようこそ！\n\nルールを確認してサーバーをお楽しみください！"

# 退出通知用の変数
LEAVE_GUILD_ID = None
LEAVE_CHANNEL_ID = None

# カスタムキーワード応答の辞書
CUSTOM_RESPONSES = {}

# スパム対策用の記録用辞書と設定値
SPAM_TRACKER = defaultdict(deque)
SPAM_SETTINGS = {}

# グローバルチャット関連の変数
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


# --- 送信テスト（Testsend）コマンド ---
@bot.tree.command(
    name="testsend",
    description="【管理者用】各種通知機能やチャンネルへテストメッセージを送信します",
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    target="テスト送信する対象を選択してください",
)
@app_commands.choices(
    target=[
        app_commands.Choice(name="日付お知らせ通知 (setchannel)", value="date"),
        app_commands.Choice(name="ウェルカム通知 (setwelcome)", value="welcome"),
        app_commands.Choice(name="退出通知 (setleave)", value="leave"),
    ]
)
async def testsend(interaction: discord.Interaction, target: str):
  guild = interaction.guild

  if target == "date":
    if not NOTIFICATION_CHANNEL_ID:
      await interaction.response.send_message(
          "❌ 日付お知らせチャンネルが設定されていません（`/setchannel` で設定してください）。",
          ephemeral=True,
      )
      return
    channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
    if not channel:
      await interaction.response.send_message(
          "❌ 設定された日付お知らせチャンネルが見つかりませんでした。",
          ephemeral=True,
      )
      return
    await channel.send(
        "🧪 **【テスト送信】** 日付お知らせ機能のテストメッセージです。正しく送信されました！"
    )
    await interaction.response.send_message(
        f"✅ 日付お知らせチャンネル（{channel.mention}）へテストメッセージを送信しました！",
        ephemeral=True,
    )

  elif target == "welcome":
    if not WELCOME_CHANNEL_ID:
      await interaction.response.send_message(
          "❌ ウェルカム通知チャンネルが設定されていません（`/setwelcome` で設定してください）。",
          ephemeral=True,
      )
      return
    channel = bot.get_channel(WELCOME_CHANNEL_ID)
    if not channel:
      await interaction.response.send_message(
          "❌ 設定されたウェルカムチャンネルが見つかりませんでした。",
          ephemeral=True,
      )
      return

    formatted_description = (
        WELCOME_DESCRIPTION.replace("{member.mention}", interaction.user.mention)
        .replace("{member.name}", interaction.user.name)
        .replace("{guild.name}", guild.name)
    )
    embed = discord.Embed(
        title=f"[テスト] {WELCOME_TITLE}",
        description=formatted_description,
        color=discord.Color.green(),
    )
    if interaction.user.avatar:
      embed.set_thumbnail(url=interaction.user.avatar.url)

    await channel.send(embed=embed)
    await interaction.response.send_message(
        f"✅ ウェルカムチャンネル（{channel.mention}）へテスト埋め込みを送信しました！",
        ephemeral=True,
    )

  elif target == "leave":
    if not LEAVE_CHANNEL_ID or LEAVE_GUILD_ID != guild.id:
      await interaction.response.send_message(
          "❌ 退出通知チャンネルがこのサーバーに設定されていません（`/setleave` で設定してください）。",
          ephemeral=True,
      )
      return
    channel = bot.get_channel(LEAVE_CHANNEL_ID)
    if not channel:
      await interaction.response.send_message(
          "❌ 設定された退出通知チャンネルが見つかりませんでした。",
          ephemeral=True,
      )
      return

    embed = discord.Embed(
        title="🚪 【テスト】メンバーが退出しました",
        description=(
            f"**ユーザー:** {interaction.user} (`{interaction.user.id}`)\n"
            "**滞在時間:** 1日 2時間 30分 15秒 (テストデータ)"
        ),
        color=discord.Color.red(),
    )
    if interaction.user.avatar:
      embed.set_thumbnail(url=interaction.user.avatar.url)

    await channel.send(embed=embed)
    await interaction.response.send_message(
        f"✅ 退出通知チャンネル（{channel.mention}）へテスト埋め込みを送信しました！",
        ephemeral=True,
    )


# --- Doctor（診断）コマンド ---
@bot.tree.command(
    name="doctor",
    description="【管理者用】ボットの接続状態や各機能の設定状況を診断します",
)
@app_commands.default_permissions(administrator=True)
async def doctor(interaction: discord.Interaction):
  guild = interaction.guild
  channel = interaction.channel
  guild_id = guild.id

  latency = round(bot.latency * 1000)

  me = guild.me
  perms = channel.permissions_for(me)
  perm_status = []
  perm_status.append(
      "✅ メッセージ送信" if perms.send_messages else "❌ メッセージ送信不可"
  )
  perm_status.append(
      "✅ 埋め込みリンク" if perms.embed_links else "❌ 埋め込みリンク不可"
  )
  perm_status.append(
      "✅ メッセージ履歴" if perms.read_message_history else "❌ メッセージ履歴不可"
  )
  perm_status.append("✅ 外部絵文字" if perms.external_emojis else "❌ 外部絵文字不可")
  permissions_str = "\n".join(perm_status)

  date_ch_str = (
      f"<#{NOTIFICATION_CHANNEL_ID}>"
      if NOTIFICATION_CHANNEL_ID and bot.get_channel(NOTIFICATION_CHANNEL_ID)
      else "未設定または無効"
  )
  welcome_ch_str = (
      f"<#{WELCOME_CHANNEL_ID}>"
      if WELCOME_CHANNEL_ID and bot.get_channel(WELCOME_CHANNEL_ID)
      else "未設定"
  )
  leave_ch_str = (
      f"<#{LEAVE_CHANNEL_ID}>"
      if LEAVE_CHANNEL_ID and LEAVE_GUILD_ID == guild_id
      else "未設定"
  )

  global_status = (
      "🌐 接続中" if channel.id in GLOBAL_CHANNELS else "🔌 未接続"
  )

  spam_conf = SPAM_SETTINGS.get(guild_id)
  if spam_conf:
    spam_str = f"有効 ({spam_conf['seconds']}秒間に{spam_conf['limit']}件)"
  else:
    spam_str = "未設定"

  keyword_count = (
      len(CUSTOM_RESPONSES.get(guild_id, {}))
      if guild_id in CUSTOM_RESPONSES
      else 0
  )

  embed = discord.Embed(
      title="🩺 Bot 診断レポート (Doctor)",
      description=(
          "現在のサーバーにおけるボットの稼働状況と設定の健康状態です。"
      ),
      color=discord.Color.green(),
      timestamp=datetime.datetime.now(datetime.timezone.utc),
  )
  embed.add_field(
      name="🏓 応答速度", value=f"**{latency}ms**", inline=True
  )
  embed.add_field(
      name="🌐 グローバルチャット", value=global_status, inline=True
  )
  embed.add_field(
      name="🛡️ スパム対策", value=spam_str, inline=True
  )
  embed.add_field(
      name="🤖 自動応答キーワード数",
      value=f"**{keyword_count}** 件登録中",
      inline=True,
  )
  embed.add_field(
      name="📢 各種通知チャンネル設定",
      value=(
          f"• 日付お知らせ: {date_ch_str}\n"
          f"• ウェルカム通知: {welcome_ch_str}\n"
          f"• 退出通知: {leave_ch_str}"
      ),
      inline=False,
  )
  embed.add_field(
      name=f"🔑 このチャンネル ({channel.name}) での権限",
      value=permissions_str,
      inline=False,
  )

  await interaction.response.send_message(embed=embed, ephemeral=True)


# --- グローバルチャット接続コマンド（管理者のみ・実行者にのみ規約を非公開表示） ---
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
    super().__init__(timeout=None)  # 永続化

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


# --- グローバルチャット解除コマンド ---
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


# --- グローバルチャット BAN / UNBAN コマンド ---
@bot.tree.command(
    name="glban",
    description="【管理者用】指定したユーザーのグローバルチャット利用を禁止または解除します",
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    user="対象のユーザー",
    action="ban（利用禁止）または unban（解除）を選択",
)
@app_commands.choices(
    action=[
        app_commands.Choice(name="BANする (利用禁止)", value="ban"),
        app_commands.Choice(name="解除する (UNBAN)", value="unban"),
    ]
)
async def glban(
    interaction: discord.Interaction, user: discord.User, action: str
):
  global GLOBAL_BANNED_USERS

  if action == "ban":
    GLOBAL_BANNED_USERS.add(user.id)
    await interaction.response.send_message(
        f"🔨 ユーザー **{user}** (`{user.id}`) をグローバルチャットからBANしました。",
        ephemeral=True,
    )
  elif action == "unban":
    if user.id in GLOBAL_BANNED_USERS:
      GLOBAL_BANNED_USERS.remove(user.id)
    await interaction.response.send_message(
        f"✅ ユーザー **{user}** (`{user.id}`) のグローバルチャットBANを解除しました。",
        ephemeral=True,
    )


# --- スパム対策の設定コマンド（秒数・件数） ---
@bot.tree.command(
    name="setspam",
    description="【管理者用】スパム検知の条件（秒数・件数）を設定します",
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    seconds="何秒間の間に（例: 5）",
    limit="何件送信されたら（例: 5）",
)
async def setspam(
    interaction: discord.Interaction,
    seconds: float,
    limit: int,
):
  guild_id = interaction.guild.id
  if guild_id not in SPAM_SETTINGS:
    SPAM_SETTINGS[guild_id] = {"seconds": seconds, "limit": limit, "role_id": None}
  else:
    SPAM_SETTINGS[guild_id]["seconds"] = seconds
    SPAM_SETTINGS[guild_id]["limit"] = limit

  await interaction.response.send_message(
      f"🛡️ スパム検知の条件を設定しました！\n"
      f"• **検知条件:** **{seconds}秒間**に **{limit}件** 以上の連続送信",
      ephemeral=True,
  )


# --- スパム検知の除外ロール追加コマンド ---
@bot.tree.command(
    name="spam_role",
    description="【管理者用】スパム判定から除外するロールを追加・設定します",
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(role="除外したいロール")
async def spam_role(interaction: discord.Interaction, role: discord.Role):
  guild_id = interaction.guild.id
  if guild_id not in SPAM_SETTINGS:
    SPAM_SETTINGS[guild_id] = {"seconds": 5.0, "limit": 5, "role_id": role.id}
  else:
    SPAM_SETTINGS[guild_id]["role_id"] = role.id

  await interaction.response.send_message(
      f"🛡️ スパム除外ロールに **{role.name}** を設定しました！",
      ephemeral=True,
  )


# --- スパム検知の除外ロール削除コマンド ---
@bot.tree.command(
    name="spam_role_remove",
    description="【管理者用】設定されているスパム除外ロールを解除します",
)
@app_commands.default_permissions(administrator=True)
async def spam_role_remove(interaction: discord.Interaction):
  guild_id = interaction.guild.id
  if guild_id in SPAM_SETTINGS:
    SPAM_SETTINGS[guild_id]["role_id"] = None

  await interaction.response.send_message(
      "🗑️ スパム除外ロールの設定を解除しました（除外なし）。",
      ephemeral=True,
  )


# --- ウェルカムメッセージ設定コマンド ---
@bot.tree.command(
    name="setwelcome",
    description=(
        "【管理者用】ウェルカムメッセージの送信先と表示内容を設定します"
    ),
)
@app_commands.default_permissions(manage_channels=True)
@app_commands.describe(
    title="埋め込みのタイトル",
    description=(
        "本文（{member.mention} で参加者をメンションできます）"
    ),
)
async def setwelcome(
    interaction: discord.Interaction, title: str, description: str
):
  global WELCOME_CHANNEL_ID, WELCOME_TITLE, WELCOME_DESCRIPTION
  WELCOME_CHANNEL_ID = interaction.channel.id
  WELCOME_TITLE = title
  WELCOME_DESCRIPTION = description

  await interaction.response.send_message(
      f"✅ このチャンネル（{interaction.channel.mention}）をウェルカムメッセージの送信先に設定し、内容を保存しました！",
      ephemeral=True,
  )


# --- 退出通知設定コマンド ---
@bot.tree.command(
    name="setleave",
    description=(
        "【管理者用】メンバー退出時の滞在時間記録を送信するチャンネルを設定します"
    ),
)
@app_commands.default_permissions(manage_channels=True)
async def setleave(interaction: discord.Interaction):
  global LEAVE_CHANNEL_ID, LEAVE_GUILD_ID
  LEAVE_GUILD_ID = interaction.guild.id
  LEAVE_CHANNEL_ID = interaction.channel.id
  await interaction.response.send_message(
      f"✅ このチャンネル（{interaction.channel.mention}）を退出時間記録の送信先に設定しました！",
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


# --- 管理者専用：埋め込みメッセージ送信コマンド ---
@bot.tree.command(
    name="sendembed",
    description="【管理者用】指定した内容の埋め込み（Embed）メッセージを送信します",
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    title="埋め込みのタイトル",
    description="本文（説明文）",
    url="リンクを持たせるURL（任意）",
    color="カラー (blue, green, red, gold など)",
)
async def sendembed(
    interaction: discord.Interaction,
    title: str,
    description: str,
    url: str = None,
    color: str = "blue",
):
  color_map = {
      "blue": discord.Color.blue(),
      "green": discord.Color.green(),
      "red": discord.Color.red(),
      "gold": discord.Color.gold(),
      "purple": discord.Color.purple(),
  }
  embed_color = color_map.get(color.lower(), discord.Color.blue())

  embed = discord.Embed(
      title=title, description=description, color=embed_color, url=url
  )

  await interaction.channel.send(embed=embed)
  await interaction.response.send_message(
      "✅ 埋め込みメッセージを送信しました！", ephemeral=True
  )


# --- 管理者専用：ロール付与パネル送信コマンド ---
@bot.tree.command(
    name="role_panel",
    description=(
        "【管理者用】ロール付与ボタン付きの埋め込みメッセージを送信します"
    ),
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    role="付与・解除を切り替えるロール",
    title="埋め込みのタイトル",
    description="本文（説明文）",
    button_label="ボタンに表示するテキスト（例: ロールを受け取る）",
)
async def role_panel(
    interaction: discord.Interaction,
    role: discord.Role,
    title: str,
    description: str,
    button_label: str = "ロールを受け取る",
):
  if interaction.guild.me.top_role <= role:
    await interaction.response.send_message(
        "❌ 指定されたロールがボットのロールよりも上にあるため、付与できません。ボットのロール位置を上に移動させてください。",
        ephemeral=True,
    )
    return

  embed = discord.Embed(
      title=title, description=description, color=discord.Color.blue()
  )
  view = RoleButtonView(role, button_label)

  await interaction.channel.send(embed=embed, view=view)
  await interaction.response.send_message(
      "✅ ロール付与パネルを送信しました！", ephemeral=True
  )


class RoleButtonView(discord.ui.View):

  def __init__(self, role: discord.Role = None, button_label: str = "ロールを受け取る"):
    super().__init__(timeout=None)  # 永続化
    self.role = role
    if role:
      self.add_item(
          discord.ui.Button(
              label=button_label,
              style=discord.ButtonStyle.primary,
              custom_id=f"role_button_{role.id}",
          )
      )

  async def interaction_check(self, interaction: discord.Interaction) -> bool:
    role_id = int(interaction.custom_id.split("_")[-1])
    role = interaction.guild.get_role(role_id)

    if not role:
      await interaction.response.send_message(
          "❌ ロールが見つかりませんでした。", ephemeral=True
      )
      return False

    try:
      if role in interaction.user.roles:
        await interaction.user.remove_roles(role)
        await interaction.response.send_message(
            f"❌ ロール「{role.name}」を解除しました。", ephemeral=True
        )
      else:
        await interaction.user.add_roles(role)
        await interaction.response.send_message(
            f"🎉 ロール「{role.name}」を付与しました！", ephemeral=True
        )
    except discord.Forbidden:
      await interaction.response.send_message(
          "❌ ボットにロールを管理する権限がありません。", ephemeral=True
      )
    except Exception as e:
      await interaction.response.send_message(
          f"❌ エラーが発生しました: {e}", ephemeral=True
      )
    return True


# --- カスタム自動応答の追加・削除・確認コマンド ---
@bot.tree.command(
    name="addkeyword",
    description=(
        "【管理者用】特定の言葉を検知したときにボットが返す返答を追加します"
    ),
)
@app_commands.default_permissions(manage_channels=True)
@app_commands.describe(
    keyword="検知する言葉（メッセージに含まれていると反応）",
    response_message="ボットが送信する返答メッセージ",
)
async def addkeyword(
    interaction: discord.Interaction, keyword: str, response_message: str
):
  guild_id = interaction.guild.id
  if guild_id not in CUSTOM_RESPONSES:
    CUSTOM_RESPONSES[guild_id] = {}

  CUSTOM_RESPONSES[guild_id][keyword] = response_message
  await interaction.response.send_message(
      f"✅ キーワード **「{keyword}」** に対する自動応答を設定しました！\n返答: {response_message}",
      ephemeral=True,
  )


@bot.tree.command(
    name="delkeyword",
    description="【管理者用】登録されている自動応答キーワードを削除します",
)
@app_commands.default_permissions(manage_channels=True)
@app_commands.describe(keyword="削除したいキーワード")
async def delkeyword(interaction: discord.Interaction, keyword: str):
  guild_id = interaction.guild.id
  if guild_id in CUSTOM_RESPONSES and keyword in CUSTOM_RESPONSES[guild_id]:
    del CUSTOM_RESPONSES[guild_id][keyword]
    await interaction.response.send_message(
        f"🗑️ キーワード **「{keyword}」** の自動応答を削除しました。",
        ephemeral=True,
    )
  else:
    await interaction.response.send_message(
        f"❌ 指定されたキーワード「{keyword}」は登録されていません。",
        ephemeral=True,
    )


@bot.tree.command(
    name="listkeywords", description="現在登録されている自動応答の一覧を表示します"
)
async def listkeywords(interaction: discord.Interaction):
  guild_id = interaction.guild.id
  if (
      guild_id not in CUSTOM_RESPONSES
      or not CUSTOM_RESPONSES[guild_id]
  ):
    await interaction.response.send_message(
        "ℹ️ 現在登録されている自動応答はありません。", ephemeral=True
    )
    return

  desc = ""
  for kw, resp in CUSTOM_RESPONSES[guild_id].items():
    desc += f"• **{kw}** ➔ {resp}\n"

  embed = discord.Embed(
      title="🤖 自動応答キーワード一覧",
      description=desc,
      color=discord.Color.blue(),
  )
  await interaction.response.send_message(embed=embed, ephemeral=True)


# --- CAPTCHA認証パネル設置コマンド ---
@bot.tree.command(
    name="captcha_setup", description="認証パネル（ボタン）を設置します"
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(role="認証完了時に付与するロール")
async def captcha_setup(interaction: discord.Interaction, role: discord.Role):
  embed = discord.Embed(
      title="🔒 サーバー認証",
      description=(
          "サーバーへようこそ！\n下の **「認証を開始する」** ボタンを押して、"
          "表示される画像認証をクリアしてください。"
      ),
      color=discord.Color.blue(),
  )
  view = CaptchaPanelView(role)
  await interaction.channel.send(embed=embed, view=view)
  await interaction.response.send_message(
      "✅ 認証パネルを設置しました！", ephemeral=True
  )


def generate_captcha_code():
  return "".join(
      random.choices(string.ascii_uppercase + string.digits, k=5)
  )


def create_captcha_image(code):
  width, height = 200, 80
  image = Image.new("RGB", (width, height), color=(240, 240, 240))
  draw = ImageDraw.Draw(image)

  for _ in range(5):
    xy = (
        random.randint(0, width),
        random.randint(0, height),
        random.randint(0, width),
        random.randint(0, height),
    )
    draw.line(xy, fill=(random.randint(100, 200),) * 3, width=2)

  for _ in range(100):
    xy = (random.randint(0, width), random.randint(0, height))
    draw.point(xy, fill=(random.randint(50, 150),) * 3)

  try:
    font = ImageFont.load_default()
  except Exception:
    font = None

  x = 30
  for char in code:
    y = random.randint(10, 30)
    draw.text(
        (x, y),
        char,
        fill=(random.randint(0, 100),) * 3,
        font=font,
        font_size=36,
    )
    x += 28

  buffer = io.BytesIO()
  image.save(buffer, format="PNG")
  buffer.seek(0)
  return buffer


class CaptchaPanelView(discord.ui.View):

  def __init__(self, role: discord.Role = None):
    super().__init__(timeout=None)  # 永続化
    self.role = role

  @discord.ui.button(
      label="認証を開始する",
      style=discord.ButtonStyle.success,
      custom_id="start_captcha",
  )
  async def start_auth(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    target_role = self.role
    if not target_role:
      await interaction.response.send_message(
          "❌ 認証ロールが正しく設定されていません。管理者により再度 `/captcha_setup` を実行してください。",
          ephemeral=True,
      )
      return

    if target_role in interaction.user.roles:
      await interaction.response.send_message(
          "ℹ️ すでに認証済みです！", ephemeral=True
      )
      return

    code = generate_captcha_code()
    image_bytes = create_captcha_image(code)
    file = discord.File(image_bytes, filename="captcha.png")

    await interaction.response.send_message(
        "下の画像に描かれている**5桁の英数字**を確認し、ボタンを押して入力してください：",
        file=file,
        view=CaptchaInputPromptView(target_role, code),
        ephemeral=True,
    )


class CaptchaInputPromptView(discord.ui.View):

  def __init__(self, role: discord.Role, correct_code: str):
    super().__init__(timeout=180)
    self.role = role
    self.correct_code = correct_code

  @discord.ui.button(
      label="コードを入力する",
      style=discord.ButtonStyle.primary,
      custom_id="open_captcha_modal",
  )
  async def open_modal(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await interaction.response.send_modal(
        CaptchaModal(self.role, self.correct_code)
    )


class CaptchaModal(discord.ui.Modal, title="CAPTCHA画像認証"):

  def __init__(self, role: discord.Role, correct_code: str):
    super().__init__()
    self.role = role
    self.correct_code = correct_code

    self.user_input = discord.ui.TextInput(
        label="画像の英数字を入力してください（大文字小文字区別）",
        placeholder="例: A3B9X",
        min_length=5,
        max_length=5,
        required=True,
    )
    self.add_item(self.user_input)

  async def on_submit(self, interaction: discord.Interaction):
    entered_text = self.user_input.value.strip()

    if entered_text == self.correct_code:
      try:
        await interaction.user.add_roles(self.role)
        await interaction.response.send_message(
            "🎉 認証に成功しました！ロールが付与されました。",
            ephemeral=True,
        )
      except discord.Forbidden:
        await interaction.response.send_message(
            "❌ ボットにロールを付与する権限がありません。", ephemeral=True
        )
    else:
      await interaction.response.send_message(
          "❌ 認証コードが違います。もう一度パネルのボタンからやり直してください。",
          ephemeral=True,
      )


# ---------------------------------------------------------
# 🤖 起動時処理（ボタンをずっと生かすための永続ビュー登録）
# ---------------------------------------------------------
@bot.event
async def on_ready():
  print(f"ログインしました: {bot.user.name}")

  # 再起動後もボタンが機能し続けるようにビューを常時登録
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


# --- ウェルカムメッセージ送信イベント ---
@bot.event
async def on_member_join(member: discord.Member):
  global WELCOME_CHANNEL_ID, WELCOME_TITLE, WELCOME_DESCRIPTION
  if WELCOME_CHANNEL_ID is None:
    return

  channel = bot.get_channel(WELCOME_CHANNEL_ID)
  if channel is None:
    try:
      channel = await bot.fetch_channel(WELCOME_CHANNEL_ID)
    except Exception:
      return

  formatted_description = (
      WELCOME_DESCRIPTION.replace("{member.mention}", member.mention)
      .replace("{member.name}", member.name)
      .replace("{guild.name}", member.guild.name)
  )

  embed = discord.Embed(
      title=WELCOME_TITLE,
      description=formatted_description,
      color=discord.Color.green(),
  )
  if member.avatar:
    embed.set_thumbnail(url=member.avatar.url)

  await channel.send(embed=embed)


# --- メンバー退出時の滞在時間記録イベント ---
@bot.event
async def on_member_remove(member: discord.Member):
  global LEAVE_CHANNEL_ID, LEAVE_GUILD_ID

  if LEAVE_CHANNEL_ID is None or LEAVE_GUILD_ID is None:
    return
  if member.guild.id != LEAVE_GUILD_ID:
    return
  if member.id == bot.user.id:
    return

  channel = bot.get_channel(LEAVE_CHANNEL_ID)
  if channel is None:
    try:
      channel = await bot.fetch_channel(LEAVE_CHANNEL_ID)
    except Exception:
      return

  if member.joined_at:
    now = datetime.datetime.now(datetime.timezone.utc)
    duration = now - member.joined_at

    total_seconds = int(duration.total_seconds())
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    time_str = ""
    if days > 0:
      time_str += f"{days}日 "
    if hours > 0:
      time_str += f"{hours}時間 "
    if minutes > 0:
      time_str += f"{minutes}分 "
    time_str += f"{seconds}秒"
  else:
    time_str = "不明"

  embed = discord.Embed(
      title="🚪 メンバーが退出しました",
      description=(
          f"**ユーザー:** {member} (`{member.id}`)\n"
          f"**滞在時間:** {time_str}"
      ),
      color=discord.Color.red(),
  )
  if member.avatar:
    embed.set_thumbnail(url=member.avatar.url)

  await channel.send(embed=embed)


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

  # --- スパム対策 ---
  if message.guild:
    guild_id = message.guild.id
    if not message.author.guild_permissions.administrator and guild_id in SPAM_SETTINGS:
      settings = SPAM_SETTINGS[guild_id]
      role_id = settings.get("role_id")

      if role_id and any(r.id == role_id for r in message.author.roles):
        pass
      else:
        now_ts = datetime.datetime.now().timestamp()
        user_history = SPAM_TRACKER[message.author.id]

        time_window = settings["seconds"]
        message_limit = settings["limit"]

        while user_history and now_ts - user_history[0] > time_window:
          user_history.popleft()

        user_history.append(now_ts)

        if len(user_history) >= message_limit:
          try:
            timeout_duration = datetime.timedelta(minutes=5)
            await message.author.timeout(
                timeout_duration, reason="連続メッセージ（スパム）の検知"
            )
            await message.channel.send(
                f"⚠️ {message.author.mention} さん、短期間に多数のメッセージが送信されたため、スパムとして検知され5分間のタイムアウト処置を行いました。",
                delete_after=10,
            )
            user_history.clear()
          except discord.Forbidden:
            pass
          except Exception:
            pass

  content = message.content

  # --- キーワード検知による自動応答処理 ---
  guild_id = message.guild.id if message.guild else None
  if guild_id and guild_id in CUSTOM_RESPONSES:
    for keyword, response in CUSTOM_RESPONSES[guild_id].items():
      if keyword in content:
        await message.channel.send(response)
        break

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
      webhooks = await message.channel.webhooks()
      webhook = discord.utils.get(webhooks, name="LinkFixerWebhook")
      if not webhook:
        webhook = await message.channel.create_webhook(name="LinkFixerWebhook")

      display_name = message.author.display_name
      avatar_url = message.author.display_avatar.url

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

      await webhook.send(
          content=final_content, username=display_name, avatar_url=avatar_url
      )

      await message.delete()

    except discord.Forbidden:
      print(
          "権限不足のため、Webhookの作成・送信またはメッセージの削除ができませんでした。"
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