import datetime
import io
import os
import random
import re
import string
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

# 退出通知用の変数（どのサーバーのどのチャンネルかを管理）
LEAVE_GUILD_ID = None
LEAVE_CHANNEL_ID = None

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


# --- テストコマンド（日付送信確認 ＆ 認証パネルの生存確認） ---
@bot.tree.command(
    name="test",
    description="【管理者用】日付お知らせのテスト送信と認証パネルの動作テストを行います",
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(role="認証テストで使用するロール（任意）")
async def test_command(interaction: discord.Interaction, role: discord.Role = None):
  now = datetime.datetime.now(JST)
  weekdays = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"]
  weekday_str = weekdays[now.weekday()]
  date_text = f"🧪 **【テスト】日付お知らせ確認**\n本日は **{now.month}月{now.day}日 ({weekday_str})** です。"

  test_role = role if role else interaction.guild.default_role

  embed = discord.Embed(
      title="🧪 【テスト】サーバー認証パネル",
      description=(
          "これは認証システムのテストパネルです。\n"
          f"対象ロール: {test_role.mention}\n\n"
          "下の **「認証を開始する」** ボタンを押して、画像認証が正常に動作するかテストしてください。"
      ),
      color=discord.Color.orange(),
  )
  view = CaptchaPanelView(test_role)

  await interaction.response.send_message(
      f"✅ テストメッセージを送信します。\n1️⃣ **日付お知らせのテスト:**\n{date_text}\n\n2️⃣ **認証パネルのテスト:**",
      embed=embed,
      view=view,
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


# --- 退出通知（即抜け時間記録）設定コマンド ---
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


# --- ユーザーのアバターを表示するコマンド ---
@bot.tree.command(
    name="avatar", description="指定したユーザー（または自分）のアバターを表示します"
)
@app_commands.describe(user="アバターを確認したいユーザー（省略時は自分）")
async def avatar(interaction: discord.Interaction, user: discord.User = None):
  target_user = user if user else interaction.user
  avatar_url = target_user.display_avatar.url

  embed = discord.Embed(
      title=f"🖼️ {target_user.display_name} のアバター",
      color=discord.Color.blue(),
  )
  embed.set_image(url=avatar_url)
  embed.set_footer(text=f"Requested by {interaction.user.display_name}")

  view = discord.ui.View()
  view.add_item(
      discord.ui.Button(
          label="ブラウザで開く", style=discord.ButtonStyle.link, url=avatar_url
      )
  )

  await interaction.response.send_message(embed=embed, view=view)


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
    super().__init__(timeout=None)
    self.role = role

  @discord.ui.button(
      label="認証を開始する",
      style=discord.ButtonStyle.success,
      custom_id="start_captcha",
  )
  async def start_auth(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    # 永続化によりロール情報が直接保持されていない場合の保険
    target_role = self.role
    if not target_role:
      await interaction.response.send_message(
          "❌ 認証ロールが設定されていません。", ephemeral=True
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

    view = CaptchaInputPromptView(target_role, code)
    await interaction.response.send_message(
        "下の画像に描かれている**5桁の英数字**を確認し、ボタンを押して入力してください：",
        file=file,
        view=view,
        ephemeral=True,
    )


class CaptchaInputPromptView(discord.ui.View):

  def __init__(self, role: discord.Role, correct_code: str):
    super().__init__(timeout=180)
    self.role = role
    self.correct_code = correct_code

  @discord.ui.button(
      label="コードを入力する", style=discord.ButtonStyle.primary, emoji="✍️"
  )
  async def open_modal(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    modal = CaptchaModal(self.role, self.correct_code)
    await interaction.response.send_modal(modal)


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


class DeleteLinkView(discord.ui.View):

  def __init__(self, author_id: int, user_message_id: int, channel):
    super().__init__(timeout=None)
    self.author_id = author_id
    self.user_message_id = user_message_id
    self.channel = channel

  @discord.ui.button(
      label="リンクを消す", style=discord.ButtonStyle.danger, emoji="🗑️"
  )
  async def delete_button(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    if interaction.user.id != self.author_id:
      await interaction.response.send_message(
          "❌ あなたが送信したリンクではないため削除できません。",
          ephemeral=True,
      )
      return

    try:
      user_msg = await self.channel.fetch_message(self.user_message_id)
      await user_msg.delete()
      await interaction.response.send_message(
          "✅ リンクを削除しました。", ephemeral=True
      )
    except discord.NotFound:
      await interaction.response.send_message(
          "ℹ️ すでに削除されているか、見つかりませんでした。", ephemeral=True
      )
    except Exception as e:
      await interaction.response.send_message(
          f"❌ 削除に失敗しました: {e}", ephemeral=True
      )


@bot.event
async def on_ready():
  print(f"ログインしました: {bot.user.name}")

  # ── 永続ビューの再登録（これにより再起動後もボタンが生き続けます） ──
  bot.add_view(CaptchaPanelView())

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


# --- メンバー退出時の滞在時間（即抜け時間）記録イベント ---
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

  content = message.content
  replaced = False

  if YOUTUBE_PATTERN.search(content):
    content = content.replace("youtube.com", "koutube.com").replace(
        "youtu.be", "koutube.com"
    )
    replaced = True
  if X_PATTERN.search(content):
    content = content.replace("twitter.com", "fxtwitter.com").replace(
        "x.com", "fxtwitter.com"
    )
    replaced = True
  if INSTAGRAM_PATTERN.search(content):
    content = content.replace("instagram.com", "oginstagram.com")
    replaced = True
  if TIKTOK_PATTERN.search(content):
    content = re.sub(
        r"https?://(?:www\.|vm\.|vt\.)?tiktok\.com",
        "https://tnktok.com",
        content,
    )
    replaced = True
  if FACEBOOK_PATTERN.search(content):
    content = content.replace("facebook.com", "facebed.com")
    replaced = True
  if THREADS_PATTERN.search(content):
    content = content.replace("threads.net", "fixthreads.com")
    replaced = True

  if replaced:
    response_text = content
    view = DeleteLinkView(message.author.id, message.id, message.channel)
    await message.channel.send(response_text, view=view)


async def main():
  token = os.getenv("DISCORD_TOKEN")
  if not token:
    print("エラー: DISCORD_TOKEN が環境変数に設定されていません。")
    return

  await start_web_server()

  async with bot:
    await bot.start(token)


if __name__ == "__main__":
  import asyncio

  asyncio.run(main())