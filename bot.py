import discord
from discord.ext import commands
from discord import ui
import aiohttp
from typing import Optional

# --- 기본 설정 ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

UNLIMITED_LIMIT_TEXT = "무제한"
session: Optional[aiohttp.ClientSession] = None

# 서버별 채널 설정
voice_creator_channel_id = {}  # {guild_id: channel_id}
summary_channel_id = {}        # {guild_id: channel_id}
temp_channel_count = 0


# -----------------------------------
# 🟢 봇 준비 완료
# -----------------------------------
@bot.event
async def on_ready():
    global session
    if session is None:
        session = aiohttp.ClientSession()

    await tree.sync()
    print(f"✅ 봇 로그인 완료: {bot.user}")
    print("✅ 슬래시 명령어 동기화 완료")


# -----------------------------------
# 🎙️ 음성 채널 자동 생성 / 삭제
# -----------------------------------
@bot.event
async def on_voice_state_update(member, before, after):
    guild = member.guild
    guild_id = guild.id

    # 1️⃣ 임시 채널 생성/삭제
    creator_id = voice_creator_channel_id.get(guild_id)
    if creator_id:
        global temp_channel_count
        # 임시 채널 생성
        if after.channel and after.channel.id == creator_id:
            temp_channel_count += 1
            new_channel = await guild.create_voice_channel(f"채널 {temp_channel_count}", category=after.channel.category)
            await member.move_to(new_channel)
        # 임시 채널 비면 삭제
        if before.channel and before.channel.name.startswith("채널 "):
            if len(before.channel.members) == 0:
                await before.channel.delete()

    # 2️⃣ 호스트 음성채널 이동 감지
    for channel in guild.text_channels:
        async for message in channel.history(limit=50):
            if not message.embeds:
                continue
            embed = message.embeds[0]
            if embed.description and str(member.id) in embed.description:
                new_desc = embed.description.splitlines()
                updated_lines = []
                voice_state = member.voice
                new_channel = voice_state.channel.mention if voice_state and voice_state.channel else "-"
                for line in new_desc:
                    if line.startswith("**음성 채널:**"):
                        updated_lines.append(f"**음성 채널:** {new_channel}")
                    else:
                        updated_lines.append(line)
                embed.description = "\n".join(updated_lines)
                await message.edit(embed=embed)

                # 모집한눈에보기 반영
                if hasattr(message, "summary_message_id"):
                    summary_channel = guild.get_channel(summary_channel_id[guild.id])
                    summary_msg = await summary_channel.fetch_message(message.summary_message_id)
                    await summary_msg.edit(embed=embed)
                break




# -----------------------------------
# 📢 모집한눈에보기 등록
# -----------------------------------
async def post_to_summary_channel(interaction: discord.Interaction, original_message: discord.Message):
    guild = interaction.guild
    if not guild:
        return None

    summary_id = summary_channel_id.get(guild.id)
    if not summary_id:
        await interaction.followup.send("❌ 모집한눈에보기 채널이 지정되지 않았습니다.", ephemeral=True)
        return None

    summary_channel = guild.get_channel(summary_id)
    if not summary_channel:
        return None

    jump_link = original_message.jump_url
    header_text = f"**{interaction.user.display_name}님이 모집 중**"
    original_embed = original_message.embeds[0] if original_message.embeds else None

    class LinkView(ui.View):
        def __init__(self, url: str):
            super().__init__(timeout=None)
            self.add_item(ui.Button(label="이동", style=discord.ButtonStyle.link, url=url))

    msg = await summary_channel.send(content=header_text, embed=original_embed, view=LinkView(jump_link))
    return msg


# -----------------------------------
# 🎨 모집 임베드 생성
# -----------------------------------
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


# -----------------------------------
# 🎮 버튼 / 뷰 정의
# -----------------------------------
class RecruitButton(ui.Button):
    def __init__(self, game_name, max_limit, host_id):
        super().__init__(label="🖐️ 1명" if max_limit == UNLIMITED_LIMIT_TEXT else f"🖐️ 1/{max_limit}", style=discord.ButtonStyle.secondary)
        self.game_name = game_name
        self.max_limit = max_limit
        self.current_count = 1
        self.recruited_users = {host_id}
        self.host_id = host_id
        self.extra_text = ""

    def unlimited(self):
        return self.max_limit == UNLIMITED_LIMIT_TEXT

    async def callback(self, interaction):
        if self.disabled:
            await interaction.response.send_message("모집이 마감되었습니다.", ephemeral=True)
            return

        uid = interaction.user.id
        if uid in self.recruited_users:
            if uid == self.host_id:
                await interaction.response.send_message("모집자는 나갈 수 없습니다.", ephemeral=True)
                return
            self.recruited_users.remove(uid)
            self.current_count -= 1
        elif not self.unlimited() and self.current_count >= int(self.max_limit):
            await interaction.response.send_message("인원 제한에 도달했습니다.", ephemeral=True)
            return
        else:
            self.recruited_users.add(uid)
            self.current_count += 1

        # RecruitButton.callback 끝부분에 추가
        embed = create_recruit_embed(interaction, self.game_name, self.max_limit, self.current_count, self.recruited_users, self.host_id, self.extra_text)
        self.label = f"🖐️ {self.current_count}/{self.max_limit}" if not self.unlimited() else f"🖐️ {self.current_count}명"
        await interaction.response.edit_message(embed=embed, view=self.view)

        # --- 모집한눈에보기 채널 글도 업데이트 ---
        if hasattr(self.view, "summary_message_id"):
            summary_id = self.view.summary_message_id
            guild = interaction.guild
            if guild:
                summary_msg = await guild.get_channel(summary_channel_id[guild.id]).fetch_message(summary_id)
                await summary_msg.edit(embed=embed)


class CloseRecruitButton(ui.Button):
    def __init__(self, host_id):
        super().__init__(emoji="🔒", style=discord.ButtonStyle.secondary)
        self.host_id = host_id

    async def interaction_check(self, interaction):
        return interaction.user.id == self.host_id

    async def callback(self, interaction):
        btn = self.view.recruit_button
        btn.disabled = not btn.disabled
        self.emoji = "🔓" if btn.disabled else "🔒"
        await interaction.response.edit_message(view=self.view)


class CancelRecruitButton(ui.Button):
    def __init__(self, host_id):
        super().__init__(emoji="❌", style=discord.ButtonStyle.secondary)
        self.host_id = host_id

    async def interaction_check(self, interaction):
        if interaction.user.id != self.host_id:
            await interaction.response.send_message("모집 취소는 모집자만 가능합니다.", ephemeral=True)
            return False
        return True

    async def callback(self, interaction):
        game_name = self.view.recruit_button.game_name
        recruited_users = self.view.recruit_button.recruited_users
        participants_mentions = ' '.join(f'<@{uid}>' for uid in recruited_users)

        # 원본 모집글 삭제
        if interaction.message:
            await interaction.message.delete()

        # 취소 안내 메시지
        cancel_message = f"❌ **[{game_name}] 모집이 취소되었습니다.**\n{participants_mentions}"
        await interaction.channel.send(cancel_message)

        # 모집한눈에보기 임베드 수정
        if hasattr(self.view, "summary_message_id"):
            guild = interaction.guild
            summary_id = summary_channel_id.get(guild.id)
            if not summary_id:
                return
            summary_channel = guild.get_channel(summary_id)
            if summary_channel:
                try:
                    summary_msg = await summary_channel.fetch_message(self.view.summary_message_id)
                    new_embed = discord.Embed(
                        title=f"❌ [{game_name}] 모집이 취소되었습니다.",
                        description=f"이 모집은 취소되었습니다.\n(호스트: <@{self.host_id}>)",
                        color=discord.Color.red()
                    )
                    await summary_msg.edit(embed=new_embed)
                except discord.NotFound:
                    pass

        self.view.stop()


class RecruitView(ui.View):
    def __init__(self, game_name, max_limit, host_id):
        super().__init__(timeout=None)
        self.recruit_button = RecruitButton(game_name, max_limit, host_id)
        self.add_item(self.recruit_button)
        self.add_item(CloseRecruitButton(host_id))
        self.add_item(CancelRecruitButton(host_id))


class RecruitModal(ui.Modal, title="모집 추가 설명"):
    def __init__(self, game_name, max_limit, host_id):
        super().__init__(title="모집 추가 설명")
        self.game_name = game_name
        self.max_limit = max_limit
        self.host_id = host_id
        self.desc = ui.TextInput(label="추가 설명 (최대 200자)", style=discord.TextStyle.paragraph, required=False, max_length=200)
        self.add_item(self.desc)

    async def on_submit(self, interaction: discord.Interaction):
        extra_text = self.desc.value.strip()
        view = RecruitView(self.game_name, self.max_limit, self.host_id)
        view.recruit_button.extra_text = extra_text

        embed = create_recruit_embed(interaction, self.game_name, self.max_limit, 1, {self.host_id}, self.host_id, extra_text)

        # ✅ 텍스트 제거 + 임베드 교체
        await interaction.response.edit_message(content=None, embed=embed, view=view)

        # 📢 모집한눈에보기 등록
        msg = await interaction.channel.fetch_message(interaction.message.id)
        summary_msg = await post_to_summary_channel(interaction, msg)
        if summary_msg:
            view.summary_message_id = summary_msg.id


class LimitSelectView(ui.View):
    def __init__(self, game_name, host_id):
        super().__init__(timeout=180)
        self.game_name = game_name
        self.host_id = host_id

    @ui.select(
        placeholder="모집 인원 제한 선택",
        options=[discord.SelectOption(label=f"{i}명", value=str(i)) for i in range(1, 9)] +
                [discord.SelectOption(label="무제한", value=UNLIMITED_LIMIT_TEXT)]
    )
    async def select_callback(self, interaction, select):
        if interaction.user.id != self.host_id:
            await interaction.response.send_message("모집자만 선택할 수 있습니다.", ephemeral=True)
            return
        modal = RecruitModal(self.game_name, select.values[0], self.host_id)
        await interaction.response.send_modal(modal)


# -----------------------------------
#

# -----------------------------------
# 💬 추가 설명 입력 모달
# -----------------------------------
class ExtraDescriptionModal(ui.Modal, title="모집 설명 추가"):
    def __init__(self, game_name, max_limit, host_id):
        super().__init__()
        self.game_name = game_name
        self.max_limit = max_limit
        self.host_id = host_id

        self.desc = ui.TextInput(
            label="추가 설명 (선택 사항)",
            style=discord.TextStyle.paragraph,
            placeholder="예: 8시부터 시작 / 초보자 환영 등",
            required=False,
            max_length=200,
        )
        self.add_item(self.desc)

    async def on_submit(self, interaction: discord.Interaction):
        view = RecruitView(self.game_name, self.max_limit, self.host_id)
        embed = create_recruit_embed(
            interaction,
            self.game_name,
            self.max_limit,
            1,
            {self.host_id},
            self.host_id,
            self.desc.value.strip(),
        )
        await interaction.response.edit_message(content=None, embed=embed, view=view)
        msg = await interaction.channel.fetch_message(interaction.message.id)
        await post_to_summary_channel(interaction, msg)
# -----------------------------------
# 🧾 슬래시 명령어
# -----------------------------------
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


@tree.command(name="모집", description="보드게임 모집을 시작합니다.")
@discord.app_commands.describe(게임="모집할 게임 이름을 입력하세요.")
async def recruit_command(interaction: discord.Interaction, 게임: str):
    view = LimitSelectView(게임, interaction.user.id)
    await interaction.response.send_message(f"✅ '{게임}' 모집을 시작합니다. 인원 제한을 선택하세요.", view=view)


# -----------------------------------
# 🚀 실행
# -----------------------------------
if __name__ == "__main__":
