import os
import random
import sqlite3
import traceback

import discord
from discord import app_commands
from discord.ext import commands


# =========================================================
# 설정
# =========================================================

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN 환경변수가 설정되지 않았습니다."
    )


# =========================================================
# 기본 설정
# =========================================================

STATS = [
    "기혈",
    "내공",
    "이동",
    "근력",
    "기량",
    "지능",
    "신통력",
    "자질"
]

# -30이 적용되는 능력치
MINUS_STATS = [
    "기혈",
    "내공",
    "이동",
    "근력",
    "기량",
    "지능"
]

# Render에서는 /tmp가 아닌 영구 디스크를 사용하는 것이 좋음.
# 기본값은 현재 폴더의 wuxia_bot.db
DB_PATH = os.getenv("DB_PATH", "wuxia_bot.db")


# =========================================================
# Discord Bot
# =========================================================

intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =========================================================
# SQLite
# =========================================================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def load_user_data(user_id):
    import json

    conn = get_db()

    row = conn.execute(
        "SELECT data FROM users WHERE user_id = ?",
        (str(user_id),)
    ).fetchone()

    conn.close()

    if row is None:
        return {
            "presets": [],
            "selected_preset": None,
            "base_stats": None,
            "final_stats": None,
            "bonus_stat": None,
            "bonus_amount": None,
            "traits": [],
            "drawn_traits": []
        }

    return json.loads(row["data"])


def save_user_data(user_id, data):
    import json

    conn = get_db()

    conn.execute("""
        INSERT INTO users (user_id, data)
        VALUES (?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET data = excluded.data
    """, (
        str(user_id),
        json.dumps(data, ensure_ascii=False)
    ))

    conn.commit()
    conn.close()


def get_user_data(user_id):
    return load_user_data(user_id)


def reset_user_data(user_id):
    data = {
        "presets": [],
        "selected_preset": None,
        "base_stats": None,
        "final_stats": None,
        "bonus_stat": None,
        "bonus_amount": None,
        "traits": [],
        "drawn_traits": []
    }

    save_user_data(user_id, data)

    return data


# =========================================================
# 능력치
# =========================================================

def roll_stats():
    """
    8개의 능력치를 각각 D100으로 굴림.
    """

    return {
        stat: random.randint(1, 100)
        for stat in STATS
    }


def calculate_base_stats(stats):
    """
    최종 선택 후 기본 능력치 계산.

    기혈 / 내공 / 이동 / 근력 / 기량 / 지능
    → -30, 최소 1

    신통력 / 자질
    → 그대로

    이후
    내공 +10
    지능 +10
    """

    result = {}

    for stat in STATS:
        value = stats[stat]

        if stat in MINUS_STATS:
            value = max(1, value - 30)

        result[stat] = value

    # 기본 보너스
    result["내공"] += 10
    result["지능"] += 10

    return result


def is_bonus_available(stat, value):
    """
    91 이상이면 선택 불가.
    정확히 90까지 선택 가능.
    """

    if value > 90:
        return False

    return True


def get_bonus_amount(stat, value):
    """
    90이면 무조건 +1

    90 미만:
    신통력 / 자질 → +5
    나머지 → +10
    """

    if value == 90:
        return 1

    if stat in ["신통력", "자질"]:
        return 5

    return 10


def get_available_bonus_stats(stats):
    return [
        stat
        for stat in STATS
        if is_bonus_available(stat, stats[stat])
    ]


# =========================================================
# D100 색상
# =========================================================

def roll_color_icon(value):
    if 1 <= value <= 30:
        return "🔴"

    if 31 <= value <= 89:
        return "⚪"

    if 90 <= value <= 99:
        return "🔵"

    if value == 100:
        return "🟡"

    return ""


# =========================================================
# 출력용 텍스트
# =========================================================

def initial_stats_text(stats):
    lines = []

    for stat in STATS:
        value = stats[stat]
        icon = roll_color_icon(value)

        lines.append(
            f"**{stat}**　`{value}` {icon}"
        )

    return "\n".join(lines)


def final_stats_text(
    stats,
    bonus_stat=None,
    bonus_amount=None
):
    lines = []

    for stat in STATS:

        value = stats[stat]

        if bonus_stat == stat:
            lines.append(
                f"**{stat}**　{value}  `+{bonus_amount}`"
            )

        elif stat in MINUS_STATS:
            lines.append(
                f"**{stat}**　{value}  `-30 적용`"
            )

        else:
            lines.append(
                f"**{stat}**　{value}"
            )

    return "\n".join(lines)


# =========================================================
# 프리셋 Embed
# =========================================================

def add_presets_inline(
    embed,
    presets,
    selected_preset=None
):
    for i, stats in enumerate(presets):

        number = i + 1

        if selected_preset == number:
            title = f"⭐ 프리셋 {number} 《선택》"
        else:
            title = f"🎲 프리셋 {number}"

        embed.add_field(
            name=title,
            value=initial_stats_text(stats),
            inline=True
        )


def preset_embed(data):
    embed = discord.Embed(
        title="⚔️ 무협 캐릭터 능력치 생성",
        description=(
            "D100으로 능력치를 생성합니다.\n\n"
            "• 프리셋은 최대 3개까지 생성됩니다.\n"
            "• 원하는 프리셋 하나를 선택하세요.\n"
            "• 선택 후 능력치 보정 단계로 넘어갑니다."
        ),
        color=discord.Color.dark_red()
    )

    add_presets_inline(
        embed,
        data["presets"],
        data["selected_preset"]
    )

    return embed


def base_stats_embed(data):
    embed = discord.Embed(
        title="⚔️ 기본 능력치",
        description=(
            "선택한 프리셋을 기준으로 계산된 능력치입니다.\n\n"
            "기혈 / 내공 / 이동 / 근력 / 기량 / 지능\n"
            "→ -30 적용\n\n"
            "내공 → 기본 +10\n"
            "지능 → 기본 +10"
        ),
        color=discord.Color.orange()
    )

    add_presets_inline(
        embed,
        data["presets"],
        data["selected_preset"]
    )

    embed.add_field(
        name="📊 기본 능력치",
        value=final_stats_text(
            data["base_stats"]
        ),
        inline=False
    )

    return embed


def character_embed(data):
    embed = discord.Embed(
        title="⚔️ 무협 캐릭터",
        color=discord.Color.gold()
    )

    add_presets_inline(
        embed,
        data["presets"],
        data["selected_preset"]
    )

    embed.add_field(
        name="📊 최종 능력치",
        value=final_stats_text(
            data["final_stats"],
            data["bonus_stat"],
            data["bonus_amount"]
        ),
        inline=False
    )

    if data.get("drawn_traits"):

        trait_text = "\n".join(
            f"**{i + 1}.** {trait}"
            for i, trait in enumerate(data["drawn_traits"])
        )

        embed.add_field(
            name="🎴 추첨된 특성",
            value=trait_text,
            inline=False
        )

    return embed


# =========================================================
# 프리셋 View
# =========================================================

class PresetView(discord.ui.View):

    def __init__(self, user_id):
        super().__init__(timeout=900)

        self.user_id = user_id

        self.add_item(
            PresetButton(1)
        )

        self.add_item(
            PresetButton(2)
        )

        self.add_item(
            PresetButton(3)
        )

        self.add_item(
            RerollButton()
        )

    async def interaction_check(
        self,
        interaction: discord.Interaction
    ):
        if interaction.user.id != self.user_id:

            await interaction.response.send_message(
                "❌ 이 캐릭터 생성 메뉴를 사용한 사람만 조작할 수 있습니다.",
                ephemeral=True
            )

            return False

        return True


class PresetButton(
    discord.ui.Button
):

    def __init__(self, number):

        super().__init__(
            label=f"프리셋 {number}",
            style=discord.ButtonStyle.primary,
            custom_id=f"preset_{number}"
        )

        self.number = number

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        data = get_user_data(
            interaction.user.id
        )

        if len(data["presets"]) < self.number:

            await interaction.response.send_message(
                "❌ 아직 생성되지 않은 프리셋입니다.",
                ephemeral=True
            )

            return

        data["selected_preset"] = self.number

        selected_stats = data["presets"][
            self.number - 1
        ]

        data["base_stats"] = calculate_base_stats(
            selected_stats
        )

        data["final_stats"] = None
        data["bonus_stat"] = None
        data["bonus_amount"] = None

        save_user_data(
            interaction.user.id,
            data
        )

        await interaction.response.edit_message(
            embed=base_stats_embed(data),
            view=BonusView(
                interaction.user.id,
                data["base_stats"]
            )
        )


class RerollButton(
    discord.ui.Button
):

    def __init__(self):

        super().__init__(
            label="🎲 다시 굴리기",
            style=discord.ButtonStyle.secondary,
            custom_id="reroll"
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        data = get_user_data(
            interaction.user.id
        )

        if len(data["presets"]) >= 3:

            await interaction.response.send_message(
                "❌ 프리셋은 최대 3개까지 생성할 수 있습니다.",
                ephemeral=True
            )

            return

        new_stats = roll_stats()

        data["presets"].append(
            new_stats
        )

        save_user_data(
            interaction.user.id,
            data
        )

        await interaction.response.edit_message(
            embed=preset_embed(data),
            view=PresetView(
                interaction.user.id
            )
        )


# =========================================================
# 능력치 보너스 선택
# =========================================================

class BonusSelect(
    discord.ui.Select
):

    def __init__(
        self,
        stats
    ):

        options = []

        for stat in STATS:

            value = stats[stat]

            # 91 이상은 아예 선택지에서 제거
            if value > 90:
                continue

            bonus = get_bonus_amount(
                stat,
                value
            )

            final_value = value + bonus

            if value == 90:

                label = (
                    f"{stat}　{value} → {final_value} (+1)"
                )

                description = (
                    f"{stat}은 90이므로 +1"
                )

            elif stat in ["신통력", "자질"]:

                label = (
                    f"{stat}　{value} → {final_value} (+5)"
                )

                description = (
                    f"{stat}은 +5 적용"
                )

            else:

                label = (
                    f"{stat}　{value} → {final_value} (+10)"
                )

                description = (
                    f"{stat}은 +10 적용"
                )

            options.append(
                discord.SelectOption(
                    label=label,
                    value=stat,
                    description=description
                )
            )

        if not options:

            options.append(
                discord.SelectOption(
                    label="선택 가능한 능력치 없음",
                    value="NONE",
                    description="모든 능력치가 90을 초과했습니다."
                )
            )

        super().__init__(
            placeholder="보너스를 받을 능력치를 선택하세요.",
            options=options,
            custom_id="bonus_select"
        )

        self.stats = stats

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        selected = self.values[0]

        if selected == "NONE":

            await interaction.response.send_message(
                "❌ 선택 가능한 능력치가 없습니다.",
                ephemeral=True
            )

            return

        data = get_user_data(
            interaction.user.id
        )

        base_value = data["base_stats"][selected]

        if base_value > 90:

            await interaction.response.send_message(
                "❌ 90을 초과한 능력치는 선택할 수 없습니다.",
                ephemeral=True
            )

            return

        bonus = get_bonus_amount(
            selected,
            base_value
        )

        data["bonus_stat"] = selected
        data["bonus_amount"] = bonus

        data["final_stats"] = (
            data["base_stats"].copy()
        )

        data["final_stats"][selected] += bonus

        save_user_data(
            interaction.user.id,
            data
        )

        await interaction.response.edit_message(
            embed=character_embed(data),
            view=CharacterView(
                interaction.user.id
            )
        )


class BonusView(
    discord.ui.View
):

    def __init__(
        self,
        user_id,
        stats
    ):

        super().__init__(timeout=900)

        self.user_id = user_id

        self.add_item(
            BonusSelect(stats)
        )

    async def interaction_check(
        self,
        interaction: discord.Interaction
    ):

        if interaction.user.id != self.user_id:

            await interaction.response.send_message(
                "❌ 이 캐릭터 생성 메뉴를 사용한 사람만 조작할 수 있습니다.",
                ephemeral=True
            )

            return False

        return True


# =========================================================
# 캐릭터 View
# =========================================================

class CharacterView(
    discord.ui.View
):

    def __init__(
        self,
        user_id
    ):

        super().__init__(timeout=900)

        self.user_id = user_id

        self.add_item(
            CharacterRefreshButton()
        )

    async def interaction_check(
        self,
        interaction: discord.Interaction
    ):

        if interaction.user.id != self.user_id:

            await interaction.response.send_message(
                "❌ 이 캐릭터 생성 메뉴를 사용한 사람만 조작할 수 있습니다.",
                ephemeral=True
            )

            return False

        return True


class CharacterRefreshButton(
    discord.ui.Button
):

    def __init__(self):

        super().__init__(
            label="🔄 캐릭터 다시 확인",
            style=discord.ButtonStyle.secondary,
            custom_id="character_refresh"
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        data = get_user_data(
            interaction.user.id
        )

        if data["final_stats"] is None:

            await interaction.response.send_message(
                "❌ 아직 최종 능력치가 결정되지 않았습니다.",
                ephemeral=True
            )

            return

        await interaction.response.edit_message(
            embed=character_embed(data),
            view=CharacterView(
                interaction.user.id
            )
        )


# =========================================================
# 특성
# =========================================================

def save_traits(
    user_id,
    traits
):

    data = get_user_data(
        user_id
    )

    data["traits"] = traits
    data["drawn_traits"] = []

    save_user_data(
        user_id,
        data
    )


def draw_traits(
    traits
):

    remaining = traits.copy()

    results = []

    # D10
    if len(remaining) >= 10:

        index = random.randrange(
            len(remaining)
        )

        results.append(
            remaining.pop(index)
        )

    # D9
    if len(remaining) >= 9:

        index = random.randrange(
            len(remaining)
        )

        results.append(
            remaining.pop(index)
        )

    # D8
    if len(remaining) >= 8:

        index = random.randrange(
            len(remaining)
        )

        results.append(
            remaining.pop(index)
        )

    return results


# =========================================================
# /무협생성
# =========================================================

@bot.tree.command(
    name="무협생성",
    description="무협 캐릭터 능력치를 생성합니다."
)
async def wuxia_generate(
    interaction: discord.Interaction
):

    data = get_user_data(
        interaction.user.id
    )

    # 능력치 생성 관련 데이터만 초기화
    data["presets"] = [
        roll_stats()
    ]

    data["selected_preset"] = None
    data["base_stats"] = None
    data["final_stats"] = None
    data["bonus_stat"] = None
    data["bonus_amount"] = None

    save_user_data(
        interaction.user.id,
        data
    )

    await interaction.response.send_message(
        embed=preset_embed(data),
        view=PresetView(
            interaction.user.id
        )
    )


# =========================================================
# /특성설정
# =========================================================

@bot.tree.command(
    name="특성설정",
    description="특성 10개를 한 번에 설정합니다."
)
@app_commands.describe(
    특성1="특성 1",
    특성2="특성 2",
    특성3="특성 3",
    특성4="특성 4",
    특성5="특성 5",
    특성6="특성 6",
    특성7="특성 7",
    특성8="특성 8",
    특성9="특성 9",
    특성10="특성 10"
)
async def trait_setting(
    interaction: discord.Interaction,
    특성1: str,
    특성2: str,
    특성3: str,
    특성4: str,
    특성5: str,
    특성6: str,
    특성7: str,
    특성8: str,
    특성9: str,
    특성10: str
):

    traits = [
        특성1.strip(),
        특성2.strip(),
        특성3.strip(),
        특성4.strip(),
        특성5.strip(),
        특성6.strip(),
        특성7.strip(),
        특성8.strip(),
        특성9.strip(),
        특성10.strip()
    ]

    # 빈칸 검사
    if any(
        not trait
        for trait in traits
    ):

        await interaction.response.send_message(
            "❌ 특성은 10개 모두 입력해야 합니다.",
            ephemeral=True
        )

        return

    # 중복 검사
    if len(set(traits)) != 10:

        await interaction.response.send_message(
            "❌ 중복된 특성이 있습니다.\n"
            "10개의 특성은 모두 서로 달라야 합니다.",
            ephemeral=True
        )

        return

    save_traits(
        interaction.user.id,
        traits
    )

    trait_text = "\n".join(
        f"**{i + 1}.** {trait}"
        for i, trait in enumerate(traits)
    )

    embed = discord.Embed(
        title="🎴 특성 설정 완료",
        description=(
            "10개의 특성이 모두 저장되었습니다.\n"
            "이제 `/특성뽑기`를 사용하면\n"
            "D10 → D9 → D8 방식으로\n"
            "3개의 특성을 추첨합니다."
        ),
        color=discord.Color.purple()
    )

    embed.add_field(
        name="📜 설정된 특성",
        value=trait_text,
        inline=False
    )

    await interaction.response.send_message(
        embed=embed
    )


# =========================================================
# /특성뽑기
# =========================================================

@bot.tree.command(
    name="특성뽑기",
    description="설정한 10개의 특성에서 D10 → D9 → D8로 3개를 뽑습니다."
)
async def trait_draw(
    interaction: discord.Interaction
):

    data = get_user_data(
        interaction.user.id
    )

    traits = data["traits"]

    if len(traits) != 10:

        await interaction.response.send_message(
            "❌ 먼저 `/특성설정`으로 특성을 정확히 10개 설정해주세요.",
            ephemeral=True
        )

        return

    results = draw_traits(
        traits
    )

    data["drawn_traits"] = results

    save_user_data(
        interaction.user.id,
        data
    )

    embed = discord.Embed(
        title="🎴 특성 추첨 결과",
        description="D10 → D9 → D8 순서로 추첨했습니다.",
        color=discord.Color.purple()
    )

    if len(results) >= 1:

        embed.add_field(
            name="🎲 D10",
            value=f"**{results[0]}**",
            inline=False
        )

    if len(results) >= 2:

        embed.add_field(
            name="🎲 D9",
            value=f"**{results[1]}**",
            inline=False
        )

    if len(results) >= 3:

        embed.add_field(
            name="🎲 D8",
            value=f"**{results[2]}**",
            inline=False
        )

    await interaction.response.send_message(
        embed=embed
    )


# =========================================================
# /캐릭터
# =========================================================

@bot.tree.command(
    name="캐릭터",
    description="현재 저장된 무협 캐릭터를 확인합니다."
)
async def character(
    interaction: discord.Interaction
):

    data = get_user_data(
        interaction.user.id
    )

    if not data["presets"]:

        await interaction.response.send_message(
            "❌ 아직 캐릭터 능력치를 생성하지 않았습니다.\n"
            "`/무협생성`을 먼저 사용해주세요.",
            ephemeral=True
        )

        return

    if data["final_stats"] is not None:

        await interaction.response.send_message(
            embed=character_embed(data),
            view=CharacterView(
                interaction.user.id
            )
        )

        return

    if data["base_stats"] is not None:

        await interaction.response.send_message(
            embed=base_stats_embed(data),
            view=BonusView(
                interaction.user.id,
                data["base_stats"]
            )
        )

        return

    await interaction.response.send_message(
        embed=preset_embed(data),
        view=PresetView(
            interaction.user.id
        )
    )


# =========================================================
# /초기화
# =========================================================

@bot.tree.command(
    name="초기화",
    description="내 무협 캐릭터와 특성을 모두 초기화합니다."
)
async def reset(
    interaction: discord.Interaction
):

    reset_user_data(
        interaction.user.id
    )

    await interaction.response.send_message(
        "♻️ 캐릭터와 특성이 모두 초기화되었습니다.",
        ephemeral=True
    )


# =========================================================
# 에러 처리
# =========================================================

@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error
):

    print("=" * 60)
    print("Discord Command Error")

    traceback.print_exception(
        type(error),
        error,
        error.__traceback__
    )

    print("=" * 60)

    try:

        if interaction.response.is_done():

            await interaction.followup.send(
                "❌ 명령어 실행 중 오류가 발생했습니다.\n"
                "봇 콘솔의 오류 내용을 확인해주세요.",
                ephemeral=True
            )

        else:

            await interaction.response.send_message(
                "❌ 명령어 실행 중 오류가 발생했습니다.\n"
                "봇 콘솔의 오류 내용을 확인해주세요.",
                ephemeral=True
            )

    except Exception:
        pass


# =========================================================
# 봇 시작
# =========================================================

@bot.event
async def on_ready():

    try:

        init_db()

        synced = await bot.tree.sync()

        print("=" * 60)
        print(f"로그인 완료: {bot.user}")
        print(f"슬래시 명령어 {len(synced)}개 동기화 완료")
        print(f"데이터베이스: {DB_PATH}")
        print("=" * 60)

    except Exception:

        print("슬래시 명령어 동기화 또는 DB 초기화 실패:")

        traceback.print_exc()


# =========================================================
# 실행
# =========================================================

bot.run(TOKEN)