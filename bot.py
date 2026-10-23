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


# --- スパム対策の設定コマンド ---
@bot.tree.command(
    name="setspam",
    description="【管理者用】スパム検知の条件とペナルティ（タイムアウト/キック/BAN/削除）を設定します",
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    seconds="何秒間の間に（例: 5）",
    limit="何件メッセージが送信されたら（例: 5）",
    action="ペナルティの種類を選択",
    timeout_minutes="タイムアウトする場合の分数（デフォルト: 5）",
)
@app_commands.choices(
    action=[
        app_commands.Choice(name="タイムアウト (Timeout)", value="timeout"),
        app_commands.Choice(name="キック (Kick)", value="kick"),
        app_commands.Choice(name="BAN (Ban)", value="ban"),
        app_commands.Choice(name="メッセージ削除のみ (Delete)", value="delete"),
    ]
)
async def setspam(
    interaction: discord.Interaction,
    seconds: float,
    limit: int,
    action: str,
    timeout_minutes: int = 5,
):
  guild_id = interaction.guild.id
  SPAM_SETTINGS[guild_id] = {
      "seconds": seconds,
      "limit": limit,
      "action": action,
      "timeout_minutes": timeout_minutes,
      "role_id": None,
  }

  action_names = {
      "timeout": f"タイムアウト ({timeout_minutes}分)",
      "kick": "キック",
      "ban": "BAN",
      "delete": "メッセージ削除のみ",
  }

  await interaction.response.send_message(
      f"🛡️ スパム検知の条件を設定しました！\n"
      f"• **検知条件:** **{seconds}秒間**に **{limit}件** 以上の連続送信\n"
      f"• **ペナルティ:** **{action_names.get(action, action)}**",
      ephemeral=True,
  )


@bot.tree.command(
    name="spam_role",
    description="【管理者用】スパム判定から除外するロールを設定します",
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(role="除外したいロール")
async def spam_role(interaction: discord.Interaction, role: discord.Role):
  guild_id = interaction.guild.id
  if guild_id not in SPAM_SETTINGS:
    SPAM_SETTINGS[guild_id] = {
        "seconds": 5.0,
        "limit": 5,
        "action": "timeout",
        "timeout_minutes": 5,
        "role_id": role.id,
    }
  else:
    SPAM_SETTINGS[guild_id]["role_id"] = role.id

  await interaction.response.send_message(
      f"🛡️ スパム除外ロールに **{role.name}** を設定しました！",
      ephemeral=True,
  )


@bot.tree.command(
    name="spam_role_remove",
    description="【管理者用】スパム除外ロールの設定を解除します",
)
@app_commands.default_permissions(administrator=True)
async def spam_role_remove(interaction: discord.Interaction):
  guild_id = interaction.guild.id
  if guild_id in SPAM_SETTINGS:
    SPAM_SETTINGS[guild_id]["role_id"] = None

  await interaction.response.send_message(
      "🗑️ スパム除外ロールの設定を解除しました。", ephemeral=True
  )


# --- ロール付与パネルコマンド ---
@bot.tree.command(
    name="role_panel",
    description="【管理者用】ロール付与ボタン付きの埋め込みメッセージを送信します",
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    role="付与・解除を切り替えるロール",
    title="埋め込みのタイトル",
    description="本文（説明文）",
    button_label="ボタンに表示するテキスト",
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
        "❌ 指定されたロールがボットのロールよりも上にあるため、付与できません。",
        ephemeral=True,
    )
    return

  embed = discord.Embed(
      title=title, description=description, color=discord.Color.blue()
  )
  view = RoleButtonView(role.id, button_label)

  await interaction.channel.send(embed=embed, view=view)
  await interaction.response.send_message(
      "✅ ロール付与パネルを送信しました！", ephemeral=True
  )


class RoleButtonView(discord.ui.View):

  def __init__(self, role_id: int = None, button_label: str = "ロールを受け取る"):
    super().__init__(timeout=None)
    self.role_id = role_id
    custom_id = f"role_button_{role_id}" if role_id else "role_button_default"

    self.add_item(
        discord.ui.Button(
            label=button_label,
            style=discord.ButtonStyle.primary,
            custom_id=custom_id,
        )
    )

  async def interaction_check(self, interaction: discord.Interaction) -> bool:
    role_id = self.role_id
    if not role_id and interaction.data.get("custom_id"):
      parts = interaction.data["custom_id"].split("_")
      if parts[-1].isdigit():
        role_id = int(parts[-1])

    role = interaction.guild.get_role(role_id) if role_id else None
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
  view = CaptchaPanelView(role.id)
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


class CaptchaInputPromptView(discord.ui.View):

  def __init__(self, role: discord.Role, correct_code: str):
    super().__init__(timeout=180)
    self.role = role
    self.correct_code = correct_code

  @discord.ui.button(
      label="コードを入力する",
      style=discord.ButtonStyle.primary,
      custom_id="open_captcha_modal_btn",
  )
  async def open_modal(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await interaction.response.send_modal(
        CaptchaModal(self.role, self.correct_code)
    )


class CaptchaPanelView(discord.ui.View):

  def __init__(self, role_id: int = None):
    super().__init__(timeout=None)
    self.role_id = role_id
    custom_id = f"start_captcha_{role_id}" if role_id else "start_captcha_default"

    self.button = discord.ui.Button(
        label="認証を開始する",
        style=discord.ButtonStyle.success,
        custom_id=custom_id,
    )
    self.button.callback = self.start_auth
    self.add_item(self.button)

  async def start_auth(self, interaction: discord.Interaction):
    role_id = self.role_id
    if not role_id and interaction.data.get("custom_id"):
      parts = interaction.data["custom_id"].split("_")
      if parts[-1].isdigit():
        role_id = int(parts[-1])

    target_role = interaction.guild.get_role(role_id) if role_id else None
    if not target_role:
      await interaction.response.send_message(
          "❌ 認証ロールが見つからないか、設定されていません。", ephemeral=True
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


@bot.event
async def on_ready():
  print(f"ログインしました: {bot.user.name}")

  bot.add_view(CaptchaPanelView())
  bot.add_view(GlobalAgreeView())
  bot.add_view(RoleButtonView())

  try:
    synced = await bot.tree.sync()
    print(f"{len(synced)}個のスラッシュコマンドを同期しました。")
  except Exception as e:
    print(f"コマンドの同期に失敗しました: {e}")

  idols_task = send_date_announcement
  if not idols_task.is_running():
    idols_task.start()


@bot.event
async def on_message(message: discord.Message):
  if message.author.bot:
    return

  # --- グローバルチャットの転送処理 ---
  if message.channel.id in GLOBAL_CHANNELS:
    if message.author.id in GLOBAL_BANNED_USERS:
      return

    content = message.content

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

    display_name = f"{message.author.display_name} ({message.guild.name})"
    avatar_url = (
        message.author.avatar.url
        if message.author.avatar
        else message.author.default_avatar.url
    )
    final_content = prefix + content

    for ch_id in GLOBAL_CHANNELS:
      if ch_id == message.channel.id:
        continue
      target_channel = bot.get_channel(ch_id)
      if target_channel:
        try:
          webhooks = await target_channel.webhooks()
          webhook = discord.utils.get(webhooks, name="GlobalChatWebhook")
          if not webhook:
            webhook = await target_channel.create_webhook(name="GlobalChatWebhook")

          await webhook.send(
              content=final_content,
              username=display_name,
              avatar_url=avatar_url,
          )
        except Exception as e:
          print(f"グローバルチャット Webhook送信エラー: {e}")

  # --- スパム対策の判定と実行処理 ---
  if message.guild:
    guild_id = message.guild.id
    if not message.author.guild_permissions.administrator and guild_id in SPAM_SETTINGS:
      settings = SPAM_SETTINGS[guild_id]
      role_id = settings.get("role_id")

      # 除外ロール持ちはスキップ
      if not (role_id and any(r.id == role_id for r in message.author.roles)):
        now_ts = datetime.datetime.now().timestamp()
        user_history = SPAM_TRACKER[message.author.id]

        time_window = settings["seconds"]
        message_limit = settings["limit"]

        while user_history and now_ts - user_history[0] > time_window:
          user_history.popleft()

        user_history.append(now_ts)

        if len(user_history) >= message_limit:
          action = settings.get("action", "timeout")
          try:
            if action == "timeout":
              minutes = settings.get("timeout_minutes", 5)
              await message.author.timeout(
                  datetime.timedelta(minutes=minutes),
                  reason="スパム検知による自動タイムアウト",
              )
              await message.channel.send(
                  f"⚠️ {message.author.mention} さん、短期間の連続送信（スパム）が検知されたため、{minutes}分間のタイムアウト処分を受けました。",
                  delete_after=10,
              )
            elif action == "kick":
              await message.author.kick(reason="スパム検知による自動キック")
              await message.channel.send(
                  f"⚠️ {message.author.mention} さんがスパム検知によりキックされました。",
                  delete_after=10,
              )
            elif action == "ban":
              await message.author.ban(reason="スパム検知による自動BAN")
              await message.channel.send(
                  f"⚠️ {message.author.mention} さんがスパム検知によりBANされました。",
                  delete_after=10,
              )
            elif action == "delete":
              pass  # メッセージ削除のみ

            user_history.clear()
          except discord.Forbidden:
            print("権限不足のためスパム処置を実行できませんでした。")
          except Exception as e:
            print(f"スパム処置エラー: {e}")

          try:
            await message.delete()
            return  # スパム判定時は以降の処理を中断
          except Exception:
            pass

  content = message.content

  # --- SNSリンク変換処理（通常テキスト送信） ---
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
      await message.channel.send(f"{message.author.mention} が送信したリンク:\n{content}")
      await message.delete()
    except discord.Forbidden:
      print("【権限エラー】メッセージの削除または送信権限がありません。")
    except Exception as e:
      print(f"リンク送信エラー: {e}")


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