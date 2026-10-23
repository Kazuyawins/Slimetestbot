import os
import random
import asyncio
import threading
import datetime
from zoneinfo import ZoneInfo
from http.server import HTTPServer, BaseHTTPRequestHandler
import re
import aiohttp
import discord
from discord.ext import commands
from discord import app_commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# 日本時間 (JST) の定義
JST = ZoneInfo("Asia/Tokyo")

# --- UptimeRobotのアクセスを受け取る簡易Webサーバー ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_health_check_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_health_check_server, daemon=True).start()
# ----------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True  # メッセージ内容の取得
intents.members = True          # メンバー情報取得

bot = commands.Bot(command_prefix="day!", intents=intents)

# チャンネルIDを保持する変数（プログラム内で動的に変更可能）
TARGET_CHANNEL_ID = 1521321579580096663  

# 各サービスのリンク検出用正規表現
YOUTUBE_PATTERN = re.compile(
    r'https?://(?:www\.)?(?:youtube\.com/watch\?v=([\w-]+)|youtu\.be/([\w-]+))(\S*)'
)
X_PATTERN = re.compile(
    r'https?://(?:www\.)?(?:twitter\.com|x\.com)/([a-zA-Z0-9_]+/status/\d+)(\S*)'
)
INSTAGRAM_PATTERN = re.compile(
    r'https?://(?:www\.)?instagram\.com/(p|reel|tv|stories)/[\w-]+(\S*)'
)
TIKTOK_PATTERN = re.compile(
    r'https?://(?:www\.|vm\.|vt\.)?tiktok\.com/\S+'
)
FACEBOOK_PATTERN = re.compile(
    r'https?://(?:www\.)?(?:facebook\.com|fb\.watch)/\S+'
)
THREADS_PATTERN = re.compile(
    r'https?://(?:www\.)?threads\.net/\S+'
)


# ==========================================
# 🔘 ロール付与ボタンのViewクラス定義
# ==========================================
class RoleButtonView(discord.ui.View):
    def __init__(self, role: discord.Role):
        super().__init__(timeout=None)
        self.role = role

        button = discord.ui.Button(
            label=f"{role.name} を取得 / 解除",
            style=discord.ButtonStyle.primary,
            custom_id=f"role_btn_{role.id}"
        )
        button.callback = self.button_callback
        self.add_item(button)

    async def button_callback(self, interaction: discord.Interaction):
        user = interaction.user
        role = self.role

        if role in user.roles:
            await user.remove_roles(role)
            await interaction.response.send_message(
                f"❌ **{role.name}** ロールを解除しました。", ephemeral=True
            )
        else:
            await user.add_roles(role)
            await interaction.response.send_message(
                f"✅ **{role.name}** ロールを付与しました！", ephemeral=True
            )


@bot.event
async def on_ready():
    print(f"ログインしました: {bot.user.name}")
    try:
        synced = await bot.tree.sync()
        print(f"スラッシュコマンドを同期しました: {len(synced)}個")
    except Exception as e:
        print(f"コマンド同期エラー: {e}")

    scheduler = AsyncIOScheduler(timezone=JST)
    scheduler.add_job(
        send_daily_message,
        CronTrigger(hour=0, minute=0, second=0, timezone=JST)
    )
    scheduler.start()

@bot.command(name="ping")
async def ping(ctx):
    latency_ms = round(bot.latency * 1000)
    await ctx.send(f"Pong! 🏓 応答速度: **{latency_ms}ms**")


# ==========================================
# 💬 メッセージ検知・WebHook送信処理（リプライ完全対応）
# ==========================================
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    content = message.content
    replaced = False

    # 1. YouTube -> koutube.com
    if YOUTUBE_PATTERN.search(content):
        content = content.replace("youtube.com", "koutube.com").replace("youtu.be", "koutube.com")
        replaced = True

    # 2. X / Twitter -> fxtwitter.com
    if X_PATTERN.search(content):
        content = content.replace("twitter.com", "fxtwitter.com").replace("x.com", "fxtwitter.com")
        replaced = True

    # 3. Instagram -> oginstagram.com
    if INSTAGRAM_PATTERN.search(content):
        content = content.replace("instagram.com", "oginstagram.com")
        replaced = True

    # 4. TikTok -> tnktok.com
    if TIKTOK_PATTERN.search(content):
        content = re.sub(r'https?://(?:www\.|vm\.|vt\.)?tiktok\.com', 'https://tnktok.com', content)
        replaced = True

    # 5. Facebook -> facebed.com
    if FACEBOOK_PATTERN.search(content):
        content = content.replace("facebook.com", "facebed.com")
        replaced = True

    # 6. Threads -> fixthreads.com
    if THREADS_PATTERN.search(content):
        content = content.replace("threads.net", "fixthreads.com")
        replaced = True

    # リンクが置換された場合、Webhookを使って送信者のアイコンと名前、返信を再現して送信
    if replaced:
        if message.channel.id == TARGET_CHANNEL_ID:
            try:
                webhooks = await message.channel.webhooks()
                webhook = discord.utils.get(webhooks, name="LinkFixerWebhook")
                if not webhook:
                    webhook = await message.channel.create_webhook(name="LinkFixerWebhook")

                display_name = message.author.display_name
                avatar_url = message.author.display_avatar.url

                # 返信（リプライ）情報を取得して引用形式で組み立てる
                prefix = ""
                if message.reference:
                    try:
                        ref_msg = message.reference.cached_message
                        if not ref_msg and message.channel:
                            ref_msg = await message.channel.fetch_message(message.reference.message_id)
                        if ref_msg:
                            ref_author = ref_msg.author.display_name
                            ref_content = ref_msg.content.replace('\n', ' ')
                            if len(ref_content) > 30:
                                ref_content = ref_content[:30] + "..."
                            prefix = f"> ↪️ **{ref_author}** への返信\n> {ref_content}\n\n"
                    except Exception:
                        pass

                final_content = prefix + content

                # Webhook経由でユーザーになりすまして送信
                await webhook.send(
                    content=final_content,
                    username=display_name,
                    avatar_url=avatar_url
                )

                # 元のメッセージを削除
                await message.delete()

            except discord.Forbidden:
                print("権限不足のため、Webhookの作成・送信またはメッセージの削除ができませんでした。")
            except Exception as e:
                print(f"Webhook送信エラー: {e}")


# ==========================================
# 🎁 スラッシュコマンド群
# ==========================================

@bot.tree.command(name="setup_role", description="ボタンでロールが付与できるメッセージパネルを作成します")
@app_commands.describe(role="付与対象のロールを選択してください", title="埋め込みのタイトル", description="説明文")
async def setup_role(interaction: discord.Interaction, role: discord.Role, title: str = "ロールパネル", description: str = "下のボタンを押すとロールの取得・解除ができます。"):
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("❌ このコマンドを使用するには「ロールの管理」権限が必要です。", ephemeral=True)
        return

    embed = discord.Embed(
        title=title,
        description=f"{description}\n\n対象ロール: {role.mention}",
        color=discord.Color.green()
    )
    
    view = RoleButtonView(role)
    await interaction.channel.send(embed=embed, view=view)
    await interaction.response.send_message("✅ ロールパネルを作成しました！", ephemeral=True)

@bot.tree.command(name="help", description="Botの機能一覧や使い方を案内します（自分だけに見えます）")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 Bot コマンドガイド & 機能一覧",
        description="Discordで `/` を入力するとすべてのコマンドが補完表示されます。",
        color=discord.Color.blue()
    )
    embed.add_field(name="🩺 システム・管理", value="`/doctor` : 稼働状態チェック\n`/setchannel` : 送信チャンネル設定\n`/setup_role` : ロールパネル作成\n`/day` : 本日の曜日を確認", inline=False)
    embed.set_footer(text="毎日 0:00 に曜日メッセージが自動投稿されます！")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="setchannel", description="0時の曜日メッセージを送信するチャンネルを設定・確認します")
@app_commands.describe(channel="送信先にしたいチャンネルを指定してください")
async def setchannel(interaction: discord.Interaction, channel: discord.TextChannel = None):
    global TARGET_CHANNEL_ID

    if channel is None:
        current_ch = bot.get_channel(TARGET_CHANNEL_ID)
        ch_name = f"#{current_ch.name}" if current_ch else "不明（ID不一致）"
        await interaction.response.send_message(f"📢 現在の自動送信チャンネル設定:\n- チャンネル名: {ch_name}\n- チャンネルID: `{TARGET_CHANNEL_ID}`", ephemeral=True)
    else:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ このコマンドを実行するにはサーバーの管理者権限が必要です。", ephemeral=True)
            return

        TARGET_CHANNEL_ID = channel.id
        await interaction.response.send_message(f"✅ 自動送信チャンネルを **{channel.mention}** (ID: `{channel.id}`) に変更しました！", ephemeral=True)

@bot.tree.command(name="doctor", description="Botの健康状態チェック（自分だけ）")
async def doctor(interaction: discord.Interaction):
    latency_ms = round(bot.latency * 1000)
    channel = bot.get_channel(TARGET_CHANNEL_ID)
    status = f"✅ (`#{channel.name}`)" if channel else "❌ 取得失敗"
    await interaction.response.send_message(f"🩺 **ドクターチェック**: 正常稼働中 🟢 / Ping: {latency_ms}ms / チャンネル: {status}", ephemeral=True)

@bot.tree.command(name="day", description="本日の曜日と日付を送信します")
async def day_command(interaction: discord.Interaction):
    now = datetime.datetime.now(JST)
    weekdays = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"]
    weekday_str = weekdays[now.weekday()]
    await interaction.response.send_message(f"📅 本日は **{now.month}月{now.day}日 ({weekday_str})** です！")

@bot.tree.command(name="hello", description="Hello link")
async def robot_status(interaction: discord.Interaction):
    await interaction.response.send_message("https://gachi.gay/raXplb")


# ==========================================
# ⏰ 0時の曜日別メッセージ処理
# ==========================================
async def send_daily_message():
    channel = bot.get_channel(TARGET_CHANNEL_ID)
    if channel:
        now = datetime.datetime.now(JST)
        weekday = now.weekday()
        messages = {
            0: "# 月曜日",
            1: "# 火曜日",
            2: "# 水曜日",
            3: "# 木曜日",
            4: "# 金曜日",
            5: "# 土曜日",
            6: "# 日曜日"
        }
        text = messages.get(weekday)
        if text:
            await channel.send(text)
    else:
        print(f"エラー: チャンネルID {TARGET_CHANNEL_ID} が見つかりません。")

TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("DISCORD_BOT_TOKEN")
if not TOKEN:
    print("エラー: DISCORD_TOKEN または DISCORD_BOT_TOKEN が環境変数に設定されていません。")
else:
    bot.run(TOKEN)