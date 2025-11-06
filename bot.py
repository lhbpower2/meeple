import discord
from discord.ext import commands
from discord import ui
import aiohttp
from aiohttp import web
import asyncio
import os
from typing import Optional

# -----------------------------
# 환경 변수
# -----------------------------
DISCORD_BOT_TOKEN = os.getenv("TOKEN")          # .env에 TOKEN 설정
KOYEP_URL = os.getenv("KOYEP_URL")             # Koyeb 앱 URL

UNLIMITED_LIMIT_TEXT = "무제한"
session: Optional[aiohttp.ClientSession] = None

# -----------------------------
# Discord Bot 설정
# -----------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# 서버별 채널 설정
voice_creator_channel_id = {}  # {guild_id: channel_id}
summary_channel_id = {}        # {guild_id: channel_id}
temp_channel_count = 0

# -----------------------------
# 🟢 봇 준비 완료
# -----------------------------
@bot.event
async def on_ready():
    global session
    if session is None:
        session = aiohttp.ClientSession()

    await tree.sync()
    print(f"✅ 봇 로그인 완료: {bot.user}")
    print("✅ 슬래시 명령어 동기화 완료")

# -----------------------------
# 🎙️ 음성 채널 자동 생성/삭제
# -----------------------------
@bot.event
async def on_voice_state_update(member, before, after):
    guild = member.guild
    guild_id = guild.id

    # 1️⃣ 임시 채널 생성/삭제
    creator_id = voice_creator_channel_id.get(guild_id)
    if creator_id:
        global temp_channel_count
        if after.channel and after.channel.id == creator_id:
            temp_channel_count += 1
            new_channel = await guild.create_voice_channel(f"채널 {temp_channel_count}", category=after.channel.category)
            await member.move_to(new_channel)
        if before.channel and before.channel.name.startswith("채널 "):
            if len(before.channel.members) == 0:
                await before.channel.delete()

# -----------------------------
# 🟢 모집/임베드 관련 함수 (기존 코드 유지)
# -----------------------------
def create_recruit_embed(interaction, game_name, max_limit, current_count, recruited_users, host_id, extra_text):
    host = interaction.guild.get_member(host_id)
    voice_status = "-"
    if host and host.voice and host.voice.channel:
        voice_status = host.voice.channel.mention

    status_text = f"{current_count}명" if max_limit == UNLIMITED_LIMIT_TEXT else f"{current_count}명 / {max_limit}명"
    participants = ' '.join(f'<@{uid}>' for uid in recruited_users)

    desc = [
        f"{game_name} 모집 중",
        "",
        f"**현재 인원:** {status_text}",
        f"**음성 채널:** {voice_status}"
    ]
    if participants:
        desc.append(f"**참가자:** {participants}")
    if extra_text:
        desc += ["", f"**설명:** {extra_text}"]

    return discord.Embed(description="\n".join(desc), color=discord.Color.blurple())

# -----------------------------
# 💬 Health Check 서버
# -----------------------------
async def health_check(request):
    return web.Response(text="OK", status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get('/health', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8000)
    await site.start()
    print("✅ Health check server running on port 8000")

# -----------------------------
# 🔄 Self Ping (Scale-to-Zero 방지)
# -----------------------------
async def ping_self():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            async with aiohttp.ClientSession() as s:
                await s.get(KOYEP_URL)
        except:
            pass
        await asyncio.sleep(180)  # 3분마다 Ping

# -----------------------------
# 🔹 슬래시 명령어 예시
# -----------------------------
@tree.command(name="음성채널지정", description="음성채널 생성용 채널을 지정합니다.")
@discord.app_commands.describe(channel="음성 채널을 선택하세요.")
async def set_voice_channel(interaction: discord.Interaction, channel: discord.VoiceChannel):
    voice_creator_channel_id[interaction.guild.id] = channel.id
    await interaction.response.send_message(f"✅ 음성채널 생성용 채널이 `{channel.name}` 으로 지정되었습니다.", ephemeral=True)

@tree.command(name="모집채널지정", description="모집한눈에보기 채널을 지정합니다.")
@discord.app_commands.describe(channel="텍스트 채널을 선택하세요.")
async def set_summary_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    summary_channel_id[interaction.guild.id] = channel.id
    await interaction.response.send_message(f"✅ 모집한눈에보기 채널이 `{channel.name}` 으로 지정되었습니다.", ephemeral=True)

# -----------------------------
# 🚀 메인 실행
# -----------------------------
async def main():
    # 1️⃣ Health Check 서버 시작
    bot.loop.create_task(start_web_server())
    # 2️⃣ Self-Ping 시작
    bot.loop.create_task(ping_self())
    # 3️⃣ Discord 봇 시작
    await bot.start(DISCORD_BOT_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
