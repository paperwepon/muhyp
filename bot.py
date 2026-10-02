import os
import json
import random
import sqlite3
import traceback

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv


# =========================================================
# 환경변수
# =========================================================

# 디스호스트의 .env를 우선적으로 확인하고,
# 현재 작업 폴더의 .env도 함께 확인합니다.
load_dotenv("/home/container/.env")
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN 환경변수가 설정되지 않았습니다.\n"
        "디스호스트의 환경변수 설정에서 DISCORD_TOKEN을 확인하세요."
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
            "drawn_traits": [],
            "enlightenment": 0
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
        "drawn_traits": [],
        "enlightenment": 0
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
# 경지 계산
# =========================================================

def calculate_realm(final_stats, enlightenment=0):
    """
    경지를 계산합니다.
    계산식: (기혈 + 내공 + 주스텟) / 3
    
    150 이상부터는 깨달음이 필요합니다 (깨달음 5 = 경지 1)
    """
    
    # 주스텟 계산 (신통력과 자질 중 높은 값)
    main_stat = max(final_stats.get("신통력", 0), final_stats.get("자질", 0))
    
    # 경지 계산: (기혈 + 내공 + 주스텟) / 3
    base_realm = (final_stats.get("기혈", 0) + final_stats.get("내공", 0) + main_stat) // 3
    
    # 깨달음에 따른 추가 경지 (깨달음 5 = 경지 1)
    additional_realm = enlightenment // 5
    
    total_realm = base_realm + additional_realm
    
    return total_realm


def get_realm_name(realm_value):
    """
    경지값에 따라 경지 이름을 반환합니다.
    """
    
    if 0 <= realm_value <= 10:
        return "삼류 하"
    elif 11 <= realm_value <= 20:
        return "삼류 중"
    elif 21 <= realm_value <= 30:
        return "삼류 상"
    elif 31 <= realm_value <= 39:
        return "이류 하"
    elif 40 <= realm_value <= 49:
        return "이류 중"
    elif realm_value == 50:
        return "이류 상"
    elif 51 <= realm_value <= 100:
        return "일류 하"
    elif 101 <= realm_value <= 125:
        return "일류 중"
    elif 126 <= realm_value <= 149:
        return "일류 상"
    elif realm_value == 150:
        return "일류 최상"
    elif 151 <= realm_value <= 200:
        return "절정 하"
    elif 201 <= realm_value <= 250:
        return "절정 중"
    elif 251 <= realm_value <= 299:
        return "절정 상"
    elif realm_value >= 300:
        return "절정 최상"
    else:
        return "미정"


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
        value=("\n".join(f"**{stat}**　{data['final_stats'][stat]}" for stat in STATS)
               if data.get("manual_stats") else final_stats_text(
                   data["final_stats"], data["bonus_stat"], data["bonus_amount"])),
        inline=False
    )

    # 경지 정보 추가
    if data.get("final_stats"):
        realm_value = calculate_realm(data["final_stats"], data.get("enlightenment", 0))
        realm_name = get_realm_name(realm_value)
        enlightenment = data.get("enlightenment", 0)
        
        realm_info = f"**경지값**: {realm_value}\n**경지**: {realm_name}"
        if enlightenment > 0:
            realm_info += f"\n**깨달음**: {enlightenment}"
        
        embed.add_field(
            name="🏔️ 경지",
            value=realm_info,
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

        if data["final_stats"] is not None:
            await interaction.response.send_message(
                "❌ 최종 스탯이 이미 저장되었습니다. `/스탯수정`을 사용하세요.", ephemeral=True)
            return

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

        if data["final_stats"] is not None:
            await interaction.response.send_message(
                "❌ 최종 스탯이 이미 저장되었습니다. `/스탯수정`을 사용하세요.", ephemeral=True)
            return

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

        if data["final_stats"] is not None:
            await interaction.response.send_message(
                "❌ 최종 스탯이 이미 저장되었습니다. `/스탯수정`을 사용하세요.", ephemeral=True)
            return

        if data["base_stats"] is None:
            await interaction.response.send_message(
                "❌ 사용할 수 없는 이전 메뉴입니다. `/캐릭터`로 다시 확인하세요.", ephemeral=True)
            return

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

        self.add_item(CharacterSaveButton())
        self.add_item(CharacterEditButton())
        self.add_item(CharacterDeleteButton())
        self.add_item(CharacterRefreshButton())
        self.add_item(CharacterCombatButton())

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


# 캐릭터 상태를 비교하여 오래된 입력창의 덮어쓰기를 방지합니다.
def character_snapshot(data):
    keys = ("presets", "selected_preset", "base_stats", "final_stats",
            "bonus_stat", "bonus_amount", "manual_stats", "enlightenment")
    return json.dumps({key: data.get(key) for key in keys}, ensure_ascii=False, sort_keys=True)


class OwnerView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=900)
        self.user_id = user_id

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ 본인의 메뉴만 사용할 수 있습니다.", ephemeral=True)
            return False
        return True


class CharacterSaveButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="💾 저장", style=discord.ButtonStyle.success)

    async def callback(self, interaction):
        data = get_user_data(interaction.user.id)
        if data["final_stats"] is None:
            await interaction.response.send_message("❌ 저장할 최종 스탯이 없습니다.", ephemeral=True)
            return
        # 화면에 남은 예전 값 대신 현재 DB의 최신 캐릭터를 저장합니다.
        save_user_data(interaction.user.id, data)
        await interaction.response.edit_message(
            content="✅ 현재 스탯을 저장했습니다. 수정 시에도 자동 저장됩니다.",
            embed=character_embed(data), view=CharacterView(interaction.user.id))


class CharacterEditButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="✏️ 수정", style=discord.ButtonStyle.primary)

    async def callback(self, interaction):
        data = get_user_data(interaction.user.id)
        if data["final_stats"] is None:
            await interaction.response.send_message("❌ 수정할 최종 스탯이 없습니다.", ephemeral=True)
            return
        await interaction.response.send_message(
            "수정할 항목을 선택하세요.",
            view=StatEditView(interaction.user.id), ephemeral=True)


class StatEditView(OwnerView):
    def __init__(self, user_id):
        super().__init__(user_id)
        
        # 능력치 수정
        stat_options = [discord.SelectOption(label=stat, value=f"stat_{stat}") for stat in STATS]
        # 깨달음 수정
        stat_options.append(discord.SelectOption(label="깨달음", value="enlightenment"))
        
        self.add_item(StatEditSelect(stat_options))


class StatEditSelect(discord.ui.Select):
    def __init__(self, options):
        super().__init__(placeholder="수정할 항목 선택", options=options)

    async def callback(self, interaction):
        data = get_user_data(interaction.user.id)
        if data["final_stats"] is None:
            await interaction.response.send_message("❌ 캐릭터가 삭제되었습니다.", ephemeral=True)
            return
        
        selected = self.values[0]
        
        if selected == "enlightenment":
            await interaction.response.send_modal(
                EnlightenmentEditModal(interaction.user.id, data))
        else:
            stat_name = selected.replace("stat_", "")
            await interaction.response.send_modal(
                StatEditModal(interaction.user.id, stat_name, data))


class StatEditModal(discord.ui.Modal):
    def __init__(self, user_id, stat, data):
        super().__init__(title=f"{stat} 수정", timeout=900)
        self.user_id = user_id
        self.stat = stat
        self.snapshot = character_snapshot(data)
        self.value_input = discord.ui.TextInput(
            label=f"{stat}의 변경 후 최종값", default=str(data["final_stats"][stat]),
            placeholder="1 이상의 정수", max_length=10)
        self.add_item(self.value_input)

    async def on_submit(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ 본인의 스탯만 수정할 수 있습니다.", ephemeral=True)
            return
        try:
            value = int(str(self.value_input).strip())
        except ValueError:
            value = 0
        if not 1 <= value <= 2147483647:
            await interaction.response.send_message("❌ 1~2147483647 사이의 정수를 입력하세요. 수정 버튼으로 다시 입력할 수 있습니다.", ephemeral=True)
            return
        data = get_user_data(self.user_id)
        if data["final_stats"] is None or character_snapshot(data) != self.snapshot:
            await interaction.response.send_message(
                "❌ 입력 중 캐릭터가 변경되었습니다. `/캐릭터`에서 다시 수정하세요.", ephemeral=True)
            return
        previous = data["final_stats"][self.stat]
        data["final_stats"][self.stat] = value
        data["manual_stats"] = True
        save_user_data(self.user_id, data)
        await interaction.response.edit_message(
            content=f"✅ {self.stat}: {previous} → {value} · 저장 완료",
            embed=character_embed(data), view=CharacterView(self.user_id))


class EnlightenmentEditModal(discord.ui.Modal):
    def __init__(self, user_id, data):
        super().__init__(title="깨달음 수정", timeout=900)
        self.user_id = user_id
        self.snapshot = character_snapshot(data)
        self.value_input = discord.ui.TextInput(
            label="깨달음 (경지 150 이상에서 사용)", 
            default=str(data.get("enlightenment", 0)),
            placeholder="0 이상의 정수 (깨달음 5 = 경지 1)", max_length=10)
        self.add_item(self.value_input)

    async def on_submit(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ 본인의 깨달음만 수정할 수 있습니다.", ephemeral=True)
            return
        try:
            value = int(str(self.value_input).strip())
        except ValueError:
            value = 0
        if not 0 <= value <= 2147483647:
            await interaction.response.send_message("❌ 0~2147483647 사이의 정수를 입력하세요. 수정 버튼으로 다시 입력할 수 있습니다.", ephemeral=True)
            return
        data = get_user_data(self.user_id)
        if data["final_stats"] is None or character_snapshot(data) != self.snapshot:
            await interaction.response.send_message(
                "❌ 입력 중 캐릭터가 변경되었습니다. `/캐릭터`에서 다시 수정하세요.", ephemeral=True)
            return
        previous = data.get("enlightenment", 0)
        data["enlightenment"] = value
        data["manual_stats"] = True
        save_user_data(self.user_id, data)
        await interaction.response.edit_message(
            content=f"✅ 깨달음: {previous} → {value} · 저장 완료",
            embed=character_embed(data), view=CharacterView(self.user_id))


class CharacterDeleteButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="🗑️ 삭제", style=discord.ButtonStyle.danger)

    async def callback(self, interaction):
        data = get_user_data(interaction.user.id)
        if data["final_stats"] is None:
            await interaction.response.send_message("❌ 삭제할 최종 스탯이 없습니다.", ephemeral=True)
            return
        await interaction.response.send_message(
            "스탯과 프리셋을 삭제할까요? 특성은 유지됩니다.",
            view=StatDeleteView(interaction.user.id, data), ephemeral=True)


class StatDeleteView(OwnerView):
    def __init__(self, user_id, data):
        super().__init__(user_id)
        self.snapshot = character_snapshot(data)

    @discord.ui.button(label="삭제", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction, button):
        data = get_user_data(self.user_id)
        if data["final_stats"] is None or character_snapshot(data) != self.snapshot:
            await interaction.response.edit_message(
                content="❌ 캐릭터가 변경되었습니다. `/캐릭터`에서 다시 확인하세요.", embed=None, view=None)
            self.stop()
            return
        clear_character_stats(data)
        save_user_data(self.user_id, data)
        await interaction.response.edit_message(
            content="✅ 스탯과 프리셋을 삭제했습니다. 특성은 유지됩니다.", embed=None, view=None)
        self.stop()

    @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        await interaction.response.edit_message(content="삭제를 취소했습니다.", embed=None, view=None)
        self.stop()


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

    if data["final_stats"] is not None:
        await interaction.response.send_message(
            "❌ 저장된 스탯이 있습니다. 다시 생성하려면 `/스탯삭제 확인: True`를 먼저 사용하세요.",
            ephemeral=True)
        return
    data.pop("manual_stats", None)
    data.pop("combat", None)

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

    if not data["presets"] and data["final_stats"] is None:

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
# 스탯 직접 저장 / 수정 / 삭제 (본인 캐릭터만 관리)
# =========================================================

def clear_character_stats(data):
    # 특성 목록과 추첨 결과는 보존하고 생성 이력만 제거합니다.
    data.update(presets=[], selected_preset=None, base_stats=None,
                final_stats=None, bonus_stat=None, bonus_amount=None)
    data.pop("manual_stats", None)
    data.pop("combat", None)


@bot.tree.command(name="스탯저장", description="8개 최종 스탯을 직접 입력하여 저장합니다.")
@app_commands.describe(
    덮어쓰기="기존 스탯을 교체하려면 True를 선택하세요.",
    깨달음="경지 150 이상에서 사용 가능합니다 (기본값: 0)"
)
async def stats_save(
    interaction: discord.Interaction,
    기혈: app_commands.Range[int, 1, 2147483647],
    내공: app_commands.Range[int, 1, 2147483647],
    이동: app_commands.Range[int, 1, 2147483647],
    근력: app_commands.Range[int, 1, 2147483647],
    기량: app_commands.Range[int, 1, 2147483647],
    지능: app_commands.Range[int, 1, 2147483647],
    신통력: app_commands.Range[int, 1, 2147483647],
    자질: app_commands.Range[int, 1, 2147483647],
    덮어쓰기: bool = False,
    깨달음: app_commands.Range[int, 0, 2147483647] = 0
):
    data = get_user_data(interaction.user.id)
    if (data["presets"] or data["final_stats"] is not None) and not 덮어쓰기:
        await interaction.response.send_message(
            "❌ 기존 스탯이 있습니다. 교체하려면 `덮어쓰기: True`로 실행하세요.",
            ephemeral=True)
        return
    clear_character_stats(data)
    # 직접 입력값은 최종값이므로 생성 보정이나 보너스를 다시 적용하지 않습니다.
    data["final_stats"] = dict(zip(STATS, [기혈, 내공, 이동, 근력, 기량, 지능, 신통력, 자질]))
    data["enlightenment"] = 깨달음
    data["manual_stats"] = True
    save_user_data(interaction.user.id, data)
    await interaction.response.send_message(
        content="✅ 스탯을 저장했습니다.", embed=character_embed(data), ephemeral=True)


@bot.tree.command(name="스탯수정", description="내 캐릭터의 최종 스탯 한 항목을 수정합니다.")
@app_commands.choices(능력치=[app_commands.Choice(name=stat, value=stat) for stat in STATS])
@app_commands.describe(값="변경 후 최종값을 입력하세요. (1 이상)")
async def stats_edit(
    interaction: discord.Interaction,
    능력치: app_commands.Choice[str],
    값: app_commands.Range[int, 1, 2147483647]
):
    data = get_user_data(interaction.user.id)
    if data["final_stats"] is None:
        await interaction.response.send_message(
            "❌ 먼저 캐릭터 생성을 완료하거나 `/스탯저장`을 사용하세요.", ephemeral=True)
        return
    previous = data["final_stats"][능력치.value]
    data["final_stats"][능력치.value] = 값
    data["manual_stats"] = True
    save_user_data(interaction.user.id, data)
    await interaction.response.send_message(
        content=f"✅ {능력치.value}: {previous} → {값}",
        embed=character_embed(data), ephemeral=True)


@bot.tree.command(name="스탯삭제", description="내 스탯과 프리셋을 삭제합니다. 특성은 유지됩니다.")
@app_commands.describe(확인="삭제하려면 True를 선택하세요.")
async def stats_delete(interaction: discord.Interaction, 확인: bool = False):
    if not 확인:
        await interaction.response.send_message(
            "스탯과 프리셋을 삭제하려면 `/스탯삭제 확인: True`로 실행하세요. 특성은 유지됩니다.",
            ephemeral=True)
        return
    data = get_user_data(interaction.user.id)
    clear_character_stats(data)
    save_user_data(interaction.user.id, data)
    await interaction.response.send_message("✅ 스탯과 프리셋을 삭제했습니다. 특성은 유지됩니다.", ephemeral=True)


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

# =========================================================
# 무공 계산: 선택한 심법과 수련도는 사용자별로 DB에 보관합니다.
# =========================================================
import ast
from fractions import Fraction

HEART_METHODS = {
    "웅패신공": ("녹림", "1.2", "30% 달성마다 기혈 +5, 근력 +5"),
    "육합공": ("화산파", "1.4", "처음 익히면 기혈 +10, 내공 +10"),
    "소청기공": ("도가", "1.3", "처음 배우면 신통력 +10"),
    "태청기공": ("도가", "1.8", "정순하고 부드러운 정종 내공"),
    "도반삼양귀원공": ("사천당가", "1.8", "독·암기 기 운용 보조"),
    "태백일심법": ("점창파", "1.5", "4절기 내공 수련 시 고정값 +5"),
    "혼원공": ("개방", "1.4", "매턴 내공 5% 회복, 최소 1"),
    "북명신공": ("미지정", "3.5", "한계 내공량 무한")
}

# 문파, 이름, 極 기준, 일반식, 極 식(없으면 일반식), 소모, 참고효과
ATTACK_ROWS = [
("무당파","무당장권",300,"(수련도/30+이동/20)*배율","(수련도/30+이동/10)*배율","1","입문 권법"),
("아미파","소청신권",400,"(수련도/20+기량/20)*배율",None,"3","입문 권법"),
("점창파","궁전권",400,"(수련도/20+기량/2)*배율",None,"3","極 충자 준비 후 돌진 시 명중·피해 배율 +2 (조건부, 미적용)"),
("소림사","백보신권",500,"(수련도/25+근력/30)*2",None,"3","원거리 정권"),
("점창파","섬광분운검법",600,"(성취도+기량/2)*배율","(성취도+기량/2+내공/6)*배율","5","연타 d6, 급소 +2"),
("화산파","육합검법(기본)",600,"(수련도/25+기량/30)*배율","(수련도/25+기량/30+내공/20)*배율","3","極 6초식 사용 가능"),
("화산파","육합귀일",600,None,"(수련도*3/50+기량/30+내공/20)*배율","15","16.666…는 50/3으로 처리. 極 전용, 사거리 기량/5"),
("무당파","신문십삼검",600,"(수련도/40+기량/20+지능/10)*배율","(수련도/50+기량/20+지능/10)*배율","1","지성은 저장된 지능 사용. 신문혈·무장해제"),
("녹림","녹림권법",600,"(수련도/20+근력/30)*배율","(수련도/20+근력/30+녹림보정)*배율","2","極 기혈 +5, 근력 +5 (스탯에 자동 가산하지 않음)"),
("점창파","관일창법",600,"(수련도/30+기량/2)*배율","(수련도/30+기량/2+내공/6)*배율","5","사거리 기량/2, 급소 +2"),
("개방","연화장",600,"(수련도/20+근력/30)*배율",None,"3","내공 없이 사용 시 배율 미적용. 極 처음 보는 상대 확정 명중 (조건부, 미적용)"),
("개방","복호권",600,"(수련도/25+근력/15)*배율",None,"2","내공 없이 사용 가능. 極 낮은 경지 상대 최종 명중·피해 +5 (조건부, 미적용)"),
("개방","타소봉법",600,"(수련도/25+근력/30)*배율","(수련도/25+근력/30+5)*배율","1","표의 * 주석 미제공. 뇌진탕 등 조건부 효과 미적용"),
("점창파","창응칠식",700,"(성취도+기량/3)*배율","(성취도+기량/3+10)*배율","10","極 기습 원거리 시 기량 항 3배 (조건부, 미적용)"),
("소림사","나한권",700,"(수련도/50+근력/5)*2",None,"미기재","권법"),
("무당파","면장",900,"(수련도/40+기량/20)*배율","(수련도/40+기량/20)*(배율+1)","15","근접·단일"),
("무당파","요지유검",950,"(수련도/30+기량/20)*배율","(수련도/30+기량/20+지능/10)*배율","5","지성=지능. 極 유수련 명중 1/3 (조건부, 미적용)"),
("사천당가","구환살",1200,"(수련도/20+기량/15)*배율","미확정","25","極 +내공/15의 적용 위치 확인 필요. 낮은 경지 상대 확정 명중 (조건부)"),
("사천당가","배심정",1200,"(수련도/20+기량/10)*배율","미확정","15","極 +내공/15의 적용 위치 확인 필요"),
("무당파","십단금",1200,"(수련도/25+기량/15)*배율","(수련도/25+기량/15+10)*배율","25","極 피해 절반 호신강기 무시"),
("소림사","대력금강지",1200,"(수련도/20+근력/10)*배율","(수련도/25+근력/10)*배율","15","極 방어 피해감소 무시"),
("곤륜파","태허도룡검법",1500,"(수련도/15+기량/10)*배율","미확정","15","곤륜파 내공은 선택 심법배율로 처리. 極 +근력/20 위치 확인 필요. 이형 명중 +1 (조건부)"),
("명교","화조풍월",3000,"(수련도/60+기량/3)*3","(수련도/20+기량/2)*3","30","고정 배율 3"),
("명교","경화수월",3000,"(수련도/50+기량/2)*3","(수련도/10+기량)*3","50","첫 출수 절대명중 +4, 이후 명중식 절반 (조건부, 미적용)"),
("명교","비화낙엽",3000,"(수련도/40+기량/2)*3","(수련도/20+기량)*3","50","첫 공격 절대명중 +2 (조건부, 미적용)"),
("명교","유록화홍",3000,"(수련도/100+내공/4)*3","(수련도/50+기량/3+내공/10)*3","내공 1할","내력 대결"),
("명교","백화요란",3000,"(수련도/200+기량/5)*3","(수련도/100+기량/5)*3","50","반원 범위 기량/10, 대상 기량/50"),
("명교","낙화낭자",3000,"(수련도/20+기량)*3","(수련도/10+기량)*3","30","같은 상대 1회, 다음 회피·명중 절대보정 -2"),
("명교","금상첨화",3000,"(수련도/60+기량/3)*3","(수련도/30+기량/2)*3","50","절대명중 +2 (미적용). 같은 상대 1회"),
("동사","탄지신통",3000,"(근력/2+기량/2)*배율","(수련도/6+근력/2+기량/2)*배율","20","표의 0.5는 참고값; 식의 배율은 선택 심법 사용. 極 자동반격"),
("사천당가","만천화우",5000,"(수련도/10+기량/10)*배율","미확정","전체 내공 5할, 최소 100","極 +내공/15 위치 확인 필요"),
("혈구음진경","진 구음백골조",5000,"(수련도+마기/3)*배율",None,"예비기혈","특수 즉사 판정은 자동 처리하지 않음"),
("화산파","이십사수매화검법",5000,"(수련도/10+기량/10+내공/10)*배율",None,"25","궁극 절학"),
("무당파","태극검",25000,"(수련도/50+기량)*2",None,"미기재","고정 배율 2")
]
MOVE_ROWS = [
("화산파","초상비",400,"(수련도/40+이동/10)*배율","(수련도/20+이동/10+5)*배율","3","기초 경공"),
("개방","초상비(草上飛)",400,"(수련도/40+이동/10)*배율","(수련도/40+이동/10+5)*배율","3","極 식 +5"),
("녹림","산악신법",400,"(수련도/30+이동/15)*배율",None,"3","산악 지형, 極 나려타곤 가능"),
("무당파","건곤구공",600,"(수련도/40+이동/10)*배율",None,"3","極 출수·회피 +1 (절대보정은 별도 표시, 수식에 미합산)"),
("곤륜파","운해비영",800,"(수련도/30+이동/20)*배율","(수련도/30+이동/20+신통력/10)*배율","3","極 회피 실패 피해 1할 경감"),
("아미파","영활선변",800,"(수련도/25+이동/10)*배율",None,"3","사각 파고들기"),
("사천당가","귀영보",800,"(수련도/20+이동/10)*배율","(수련도/25+이동/10)*배율","3","기습 출수 +1, 상태이상 급소 +1"),
("점창파","비운축영",900,"(수련도/20+이동/15)*배율",None,"3","추격 거리 ×1.5, 極 출수 +1·최소타수 +1"),
("소림사","일위도강",900,"(수련도/30+이동/20)*2",None,"미기재","고정 배율 2"),
("무당파","제운종",1200,"(수련도/20+이동/10)*2",None,"0","기본 출수·회피 +1, 極 내공10 소모 추가 +1 (별도 보정)"),
("혈구음진경","혈해유령보",4000,"수련도+마기/3",None,"예비기혈","極 절대회피 +3, 실패 피해무효는 조건부"),
("새외","성화령신공",0,"(마기/2)*3",None,"0","고정 배율 3")
]
ATTACKS = {str(i): row for i, row in enumerate(ATTACK_ROWS)}
MOVES = {str(i): row for i, row in enumerate(MOVE_ROWS)}


def formula_value(formula, values):
    """등록된 식만 AST로 계산합니다. 나눗셈과 최종값은 버림, 배율은 정확한 유리수."""
    def walk(node):
        if isinstance(node, ast.Name):
            if node.id not in values or values[node.id] is None:
                raise ValueError(f"{node.id} 입력이 필요합니다.")
            return Fraction(str(values[node.id]))
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return Fraction(str(node.value))
        if isinstance(node, ast.BinOp):
            left, right = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Add): return left + right
            if isinstance(node.op, ast.Mult): return left * right
            if isinstance(node.op, ast.Div): return Fraction(left // right)
        raise ValueError("지원하지 않는 계산식입니다.")
    result = walk(ast.parse(formula, mode="eval").body)
    return result.numerator // result.denominator


def combat_settings(data):
    c = data.get("combat", {})
    return {"heart": c.get("heart"), "attack": c.get("attack"), "move": c.get("move"),
            "attack_training": dict(c.get("attack_training", {})),
            "move_training": dict(c.get("move_training", {})),
            "achievement": c.get("achievement"), "magic": c.get("magic")}


def combat_embed(data):
    c = combat_settings(data)
    heart = HEART_METHODS.get(c["heart"])
    embed = discord.Embed(title="⚔️ 무공 명중·회피 계산", color=discord.Color.blue())
    embed.description = (f"심법: **{c['heart']} ×{heart[1]}**\n{heart[2]}" if heart else "심법을 선택하세요.")
    for kind, label, catalog in (("attack", "명중치", ATTACKS), ("move", "회피치", MOVES)):
        key = c[kind]
        if key not in catalog:
            embed.add_field(name=label, value="무공을 선택하세요.", inline=False)
            continue
        sect, name, limit, normal, extreme, cost, note = catalog[key]
        training = c[kind + "_training"].get(key)
        text = f"{sect} · **{name}** · 소모 {cost}\n"
        if training is None:
            text += "수련도 입력이 필요합니다."
        else:
            mastered = training >= limit
            formula = (extreme or normal) if mastered else normal
            text += f"수련도 {training} / 極 기준 {limit} · {'極' if mastered else '일반'}\n"
            if formula is None or formula == "미확정":
                text += "**계산 보류: 해당 단계의 식이 미공개 또는 적용 위치 미확정입니다.**"
                if normal: text += f"\n일반식 참고: `{normal}`"
            elif "배율" in formula and heart is None:
                text += "심법을 선택하세요."
            else:
                values = dict(data["final_stats"])
                values.update(수련도=training, 배율=heart[1] if heart else None,
                              성취도=c["achievement"], 마기=c["magic"], 녹림보정=Fraction(1, 6))
                try:
                    value = formula_value(formula, values)
                    text += f"`{formula}`\n**{label}: {value}**"
                    used = sorted({n.id for n in ast.walk(ast.parse(formula, mode="eval")) if isinstance(n, ast.Name)})
                    text += "\n사용값: " + ", ".join(f"{n}={values[n]}" for n in used)
                except ValueError as error:
                    text += str(error)
        text += f"\n참고: {note}"
        embed.add_field(name=label, value=text, inline=False)
    embed.set_footer(text="각 나눗셈·최종값 버림 | 수련도 ≥ 기준이면 極 | 조건부·절대보정, 피해, 자원 차감 미적용")
    return embed


class CombatSelect(discord.ui.Select):
    def __init__(self, kind, options, row):
        super().__init__(placeholder={"heart":"심법 선택", "attack":"공격 무공 선택", "move":"경공 선택"}[kind], options=options, row=row)
        self.kind = kind

    async def callback(self, interaction):
        data = get_user_data(interaction.user.id)
        if data["final_stats"] is None:
            await interaction.response.send_message("❌ 캐릭터 스탯을 먼저 저장하세요.", ephemeral=True)
            return
        c = combat_settings(data)
        c[self.kind] = self.values[0]
        data["combat"] = c
        save_user_data(interaction.user.id, data)
        await interaction.response.edit_message(embed=combat_embed(data), view=CombatView(interaction.user.id, data))


class CombatView(OwnerView):
    def __init__(self, user_id, data):
        super().__init__(user_id)
        c = combat_settings(data)
        self.add_item(CombatSelect("heart", [discord.SelectOption(label=f"{v[0]} · {k} ×{v[1]}", value=k, default=c["heart"]==k) for k,v in HEART_METHODS.items()], 0))
        # Discord의 선택 메뉴당 25개 제한에 맞춰 공격 목록을 나눕니다.
        entries = list(ATTACKS.items())
        for page in range(2):
            self.add_item(CombatSelect("attack", [discord.SelectOption(label=f"{v[0]} · {v[1]}", value=k, default=c["attack"]==k) for k,v in entries[page*25:(page+1)*25]], page+1))
        self.add_item(CombatSelect("move", [discord.SelectOption(label=f"{v[0]} · {v[1]}", value=k, default=c["move"]==k) for k,v in MOVES.items()], 3))

    @discord.ui.button(label="📝 수련도·추가값 입력", style=discord.ButtonStyle.primary, row=4)
    async def training(self, interaction, button):
        data = get_user_data(self.user_id)
        if data["final_stats"] is None:
            await interaction.response.send_message("❌ 캐릭터가 삭제되었습니다.", ephemeral=True)
            return
        c = combat_settings(data)
        if c["attack"] not in ATTACKS and c["move"] not in MOVES:
            await interaction.response.send_message("먼저 공격 무공이나 경공을 선택하세요.", ephemeral=True)
            return
        await interaction.response.send_modal(CombatTrainingModal(self.user_id, data))

    @discord.ui.button(label="🔄 최신 스탯으로 계산", style=discord.ButtonStyle.secondary, row=4)
    async def refresh(self, interaction, button):
        data = get_user_data(self.user_id)
        if data["final_stats"] is None:
            await interaction.response.edit_message(content="캐릭터가 삭제되었습니다.", embed=None, view=None)
            return
        await interaction.response.edit_message(embed=combat_embed(data), view=CombatView(self.user_id, data))


class CombatTrainingModal(discord.ui.Modal):
    def __init__(self, user_id, data):
        super().__init__(title="수련도·추가값 입력", timeout=900)
        self.user_id = user_id
        self.previous = combat_settings(data)
        self.snapshot = character_snapshot(data)
        self.inputs = {}
        c = self.previous
        for kind, catalog in (("attack",ATTACKS),("move",MOVES)):
            if c[kind] in catalog:
                default = c[kind+"_training"].get(c[kind])
                item = discord.ui.TextInput(label=f"{catalog[c[kind]][1]} 수련도", default=str(default) if default is not None else None, placeholder="0 이상의 정수", max_length=10)
                self.inputs[kind] = item
                self.add_item(item)
        for key, label in (("achievement", "성취도 (해당 식에 필요할 때 입력)"),("magic","마기 (해당 식에 필요할 때 입력)")):
            item = discord.ui.TextInput(label=label, required=False, default=str(c[key]) if c[key] is not None else None, placeholder="미정이면 비워 두세요 · 0 이상 정수", max_length=10)
            self.inputs[key] = item
            self.add_item(item)

    async def on_submit(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ 본인만 입력할 수 있습니다.", ephemeral=True)
            return
        parsed = {}
        for key, item in self.inputs.items():
            raw = str(item).strip()
            if not raw and key in ("achievement", "magic"):
                parsed[key] = None
                continue
            if not raw.isascii() or not raw.isdecimal() or int(raw) > 2147483647:
                await interaction.response.send_message("❌ 0~2147483647 사이의 정수를 입력하세요. 입력 버튼으로 다시 시도할 수 있습니다.", ephemeral=True)
                return
            parsed[key] = int(raw)
        data = get_user_data(self.user_id)
        c = combat_settings(data)
        if data["final_stats"] is None or character_snapshot(data) != self.snapshot or c != self.previous:
            await interaction.response.send_message("❌ 입력 중 설정 또는 스탯이 변경되었습니다. `/무공`에서 다시 입력하세요.", ephemeral=True)
            return
        for key, value in parsed.items():
            if key in ("attack", "move"):
                c[key+"_training"][c[key]] = value
            else:
                c[key] = value
        data["combat"] = c
        save_user_data(self.user_id, data)
        await interaction.response.edit_message(content="✅ 설정 저장 완료", embed=combat_embed(data), view=CombatView(self.user_id, data))


async def open_combat(interaction):
    data = get_user_data(interaction.user.id)
    if data["final_stats"] is None:
        await interaction.response.send_message("❌ 먼저 `/무협생성`을 완료하거나 `/스탯저장`을 사용하세요.", ephemeral=True)
        return
    await interaction.response.send_message(embed=combat_embed(data), view=CombatView(interaction.user.id, data), ephemeral=True)


class CharacterCombatButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="⚔️ 무공 계산", style=discord.ButtonStyle.primary, row=1)

    async def callback(self, interaction):
        await open_combat(interaction)


@bot.tree.command(name="무공", description="심법·무공·경공과 수련도를 설정하여 명중치·회피치를 계산합니다.")
async def martial_calculator(interaction: discord.Interaction):
    await open_combat(interaction)



bot.run(TOKEN)

