import subprocess
import sys
import importlib

# 필수 라이브러리 및 버전 설정
# discord.py는 요청하신 대로 2.6.3 버전으로 고정
required_libraries = {
    "discord": "discord.py[voice]==2.6.4",
    "genai": "google-genai",
    "dotenv": "python-dotenv",
    "requests": "requests",
    "bs4": "beautifulsoup4",
    "lxml": "lxml",
    "gtts": "gTTS",
    "PIL": "Pillow",
    "nacl": "PyNaCl"
}

def install_and_import():
    for module_name, package_name in required_libraries.items():
        try:
            # 모듈이 있는지 확인
            importlib.import_module(module_name)
        except ImportError:
            print(f"📦 {package_name} 설치 중...")
            try:
                # pip를 사용하여 설치
                subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
                print(f"✅ {package_name} 설치 완료!")
            except Exception as e:
                print(f"❌ {package_name} 설치 실패: {e}")

# 실행 시 모든 라이브러리 체크 및 설치
install_and_import()

# --- 여기서부터 기존 임포트 ---
import discord
from discord.ext import commands, tasks
from discord import FFmpegPCMAudio
import json
import os
import random
import datetime
from datetime import date, timedelta
import asyncio
import requests
from bs4 import BeautifulSoup
import urllib.parse
import io
from google import genai
from gtts import gTTS

# 이하 봇 코드...
# ====================================================================
# ----------------- 1. 보안 및 봇 설정 -----------------
# ====================================================================
# 🚨🚨🚨 실제 봇 실행 시에는 반드시 유효한 토큰으로 교체해 주세요! 🚨🚨🚨
BOT_TOKEN = "BOT_TOKEN"
BOT_PREFIX = "!"
DATA_FILE = "data.json"

# Gemini API 설정
client = genai.Client(api_key="Gemini_Key")

# 인텐트 설정 (필수)
intents = discord.Intents.default()
intents.message_content = True
intents.members = True # 밴/언밴 등 멤버 관련 기능을 위해 필요

bot = commands.Bot(command_prefix=BOT_PREFIX, intents=intents)

# ----------------- 봇 임시 데이터 저장소 (Bot 1) -----------------
# {길드ID: 최대숫자} 형태로 저장됩니다. (재시작 시 초기화됨)
server_range_settings = {}

# 경제 설정 (Bot 1)
RPS_REWARD = 1500
DAILY_COOLDOWN_HOURS = 24 # 일일 보상 쿨타임 (시간)
ATTENDANCE_COOLDOWN_HOURS = 24 # 출석 쿨타임 (시간)

# --- [데이터 저장소 (Bot 2)] ---
chat_sessions = {}
user_data_stocks = {}  # 유저 자금 및 보유 주식 데이터 (Bot 2 전용)
stocks = {
    "사성전자": {"price": 50000, "change": 0},
    "록데시네마": {"price": 120000, "change": 0},
    "엔지전자": {"price": 15000, "change": 0}
}

# ====================================================================
# ----------------- 2. 데이터 관리 함수 (Bot 1) -----------------
# ====================================================================

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            try:
                # 파일 크기가 0보다 클 때만 로드 시도
                if os.path.getsize(DATA_FILE) > 0:
                    return json.load(f)
                else:
                    return {}
            except json.JSONDecodeError:
                return {}
            except Exception as e:
                print(f"데이터 로드 중 알 수 없는 오류: {e}")
                return {}
    return {}

def save_data(data):
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except IOError as e:
        print(f"데이터 저장 오류: {e}")

def get_user_data(data, user_id):
    user_id_str = str(user_id)
    # 기본 데이터 구조 설정
    default_data = {
        "출석횟수": 0,
        "경험치": 0.0,
        "마지막 출석일": "",
        "마지막 출석시간": None,
        "money": 10000,
        "stocks": {},  # 이 줄이 핵심!
        "last_daily": None,
        "warnings": 0
    }
    
    if user_id_str not in data:
        data[user_id_str] = default_data
    else:
        # 기존 유저 데이터에 새로운 항목이 없으면 추가해줌
        for key, value in default_data.items():
            if key not in data[user_id_str]:
                data[user_id_str][key] = value
                
    return data[user_id_str]

# ----------------- 시간 계산 도우미 함수 -----------------

def calculate_time_left(last_time_str, cooldown_hours):
    """마지막 실행 시간과 쿨타임(시간)을 받아 남은 시간을 timedelta로 반환"""
    if last_time_str is None:
        return timedelta(seconds=0)
    
    try:
        last_time = datetime.datetime.fromisoformat(last_time_str)
    except ValueError:
        # ISO 형식이 아닐 경우 (구버전 데이터 등) 바로 사용 가능하도록 처리
        return timedelta(seconds=0)

    now = datetime.datetime.now()
    cooldown = timedelta(hours=cooldown_hours)
    
    time_passed = now - last_time

    if time_passed >= cooldown:
        return timedelta(seconds=0)
    else:
        return cooldown - time_passed

def format_timedelta(td: timedelta):
    """timedelta 객체를 'H시간 M분 S초' 문자열로 포맷팅"""
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    
    time_str = ""
    if hours > 0:
        time_str += f"{hours}시간 "
    if minutes > 0 or hours > 0:
        time_str += f"{minutes}분 "
    time_str += f"{seconds}초"
    
    return time_str.strip()

# ====================================================================
# ----------------- 2.5 데이터 관리 함수 (Bot 2) -----------------
# ====================================================================

# 유저 데이터 가져오기 함수 (Bot 2 주식 전용)
def get_user_info(user_id):
    if user_id not in user_data_stocks:
        user_data_stocks[user_id] = {"money": 1000000, "inventory": {}} # 초기자금 100만 원
    return user_data_stocks[user_id]

# --- [주가 변동 로직] ---
@tasks.loop(seconds=5)
async def update_stock_prices():
    for name in stocks:
        # -7% ~ +7% 사이의 변동률
        fluctuation = random.randint(-7, 7) / 100
        change_amt = int(stocks[name]["price"] * fluctuation)
        stocks[name]["price"] += change_amt
        stocks[name]["change"] = change_amt

# ====================================================================
# ----------------- 3. ★ KBO 크롤링 함수 (최종) ★ -----------------
# ====================================================================
def fetch_kbo_rankings():
    """KBO 공식 홈페이지에서 실시간 순위를 가져옵니다. (깨짐 방지 로직 적용)"""
    url = 'https://www.koreabaseball.com/Record/TeamRank/TeamRankDaily.aspx'
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.koreabaseball.com/'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        # KBO 페이지는 utf-8 인코딩을 사용하므로 명시적으로 지정하여 데이터 깨짐을 방지
        response.encoding = 'utf-8' 
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 순위 테이블 찾기
        table = soup.find('table', class_='tData')
        if not table:
            table = soup.find('table', class_='tbl_type')

        if not table:
            print("🚨 오류: KBO 웹사이트에서 순위 표를 찾을 수 없습니다.")
            return None 

        rankings = []
        rows = table.find_all('tr')
        
        for row in rows:
            cols = row.find_all('td')
            if len(cols) >= 8:
                team_name = cols[1].text.strip()
                
                # 데이터 추출
                rankings.append({
                    'rank': cols[0].text.strip(), 
                    'team': team_name,
                    'games': cols[2].text.strip(),
                    'win': cols[3].text.strip(),
                    'lose': cols[4].text.strip(),
                    'draw': cols[5].text.strip(),
                    'pct': cols[6].text.strip(),
                    'gb': cols[7].text.strip(),       
                })
        return rankings
    except requests.exceptions.RequestException as e:
        print(f"🚨 KBO 크롤링 네트워크/HTTP 오류: {e}")
        return None
    except Exception as e:
        print(f"🚨 KBO 크롤링 치명적 오류: {e}")
        return None
# -------------------------------------------------------------


# ====================================================================
# ----------------- 4. 핵심 이벤트 핸들러 -----------------
# ====================================================================

@bot.event
async def on_ready():
    # Bot 2의 주식 루프 시작
    if not update_stock_prices.is_running():
        update_stock_prices.start()
        
    print('-----------------------------------------')
    print(f'✅ {bot.user.name} 봇이 준비되었습니다.')
    print(f'명령어 접두사: {BOT_PREFIX}')
    print("Copyright 2025-2026 엘도라도 All Rights Reserved.")
    print('-----------------------------------------')
    await bot.change_presence(activity=discord.Game(name=f"명령어 모음은 {BOT_PREFIX}엘도라도프로 입력해주세요!"))

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    await bot.process_commands(message)

# ====================================================================
# ----------------- 5. 명령어 에러 핸들링 -----------------
# ====================================================================

# 관리자 명령어 에러 핸들링 함수 (공용)
@bot.event
async def on_command_error(ctx, error):
    # 이미 해당 명령어에 대한 로컬 에러 핸들러가 있으면 건너뜁니다.
    if hasattr(ctx.command, 'on_error'):
        return

    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(title="🚫 권한 부족", description="이 명령어는 **관리자 권한**이 있는 분만 사용하실 수 있습니다.", color=discord.Color.dark_red())
        await ctx.send(embed=embed)
    elif isinstance(error, commands.MemberNotFound):
        embed = discord.Embed(title="🤔 사용자 찾기 실패", description="사용자를 찾을 수 없거나 올바르게 멘션되지 않았습니다.", color=discord.Color.light_grey())
        await ctx.send(embed=embed)
    elif isinstance(error, commands.MissingRequiredArgument):
        embed = discord.Embed(title="🧐 필수 인자 누락", description=f"명령어 사용법을 다시 한 번 확인해 주세요.\n**사용법 예시**: `{BOT_PREFIX}{ctx.command.name} [필수 인자]`", color=discord.Color.light_grey())
        await ctx.send(embed=embed)
    elif isinstance(error, commands.BadArgument):
        embed = discord.Embed(title="❌ 잘못된 입력 형식", description="입력 값이 올바른 형식이 아닙니다. 숫자가 필요한 곳에 문자를 입력했는지 확인해 주세요.", color=discord.Color.red())
        await ctx.send(embed=embed)
    elif isinstance(error, commands.CommandNotFound):
        # 명령어 찾지 못했을 때는 응답하지 않도록 처리 (선택적)
        pass
    else:
        # 기타 예상치 못한 오류
        print(f"🚨 명령어 실행 중 예상치 못한 오류 발생 ({ctx.command}): {error}")
        # embed = discord.Embed(title="⚠️ 명령어 오류", description=f"명령어 실행 중 알 수 없는 오류가 발생했습니다: `{error}`", color=discord.Color.orange())
        # await ctx.send(embed=embed)

# ----------------- 로컬 에러 핸들러 재정의 -----------------

@bot.command(name='주거라')
@commands.has_permissions(ban_members=True)
async def ban_user(ctx, member: discord.Member, *, reason=None):
    """멘션된 사용자를 서버에서 밴합니다."""
    reason_text = f"이유: {reason}" if reason else "이유: 없음"
    
    if member == bot.user:
        embed = discord.Embed(title="🚫 권한 오류", description="저는 저 자신을 밴할 수 없어요!", color=discord.Color.dark_red())
        await ctx.send(embed=embed)
        return
    
    # 봇의 역할보다 높은 역할을 가진 사용자 밴 방지
    if member.top_role >= ctx.guild.me.top_role and ctx.author.id != ctx.guild.owner_id:
        embed = discord.Embed(title="❌ 권한 부족", description=f"**{member.display_name}**님은 저보다 높은 권한을 가지고 있어서 밴할 수 없습니다. (서버 관리자는 제외)", color=discord.Color.dark_red())
        await ctx.send(embed=embed)
        return

    try:
        await member.ban(reason=reason)
        embed = discord.Embed(
            title="💀 사용자 밴 처리 완료", 
            description=f'**{member.display_name}**님이 서버에서 밴 처리되었습니다.', 
            color=discord.Color.red()
        )
        embed.add_field(name="처리 이유", value=reason_text, inline=False)
        await ctx.send(embed=embed)
    except discord.Forbidden:
        embed = discord.Embed(title="❌ 권한 오류 (Forbidden)", description="봇에게 해당 사용자를 밴할 수 있는 권한이 없습니다. 봇의 역할 순서를 확인해 주세요.", color=discord.Color.dark_red())
        await ctx.send(embed=embed)
    except Exception as e:
        embed = discord.Embed(title="⚠️ 밴 처리 오류", description=f"밴 처리 중 오류가 발생했습니다: `{e}`", color=discord.Color.orange())
        await ctx.send(embed=embed)

# 😇 "!살려라 <ID 또는 이름#태그>"
@bot.command(name='살려라')
@commands.has_permissions(ban_members=True)
async def unban_user(ctx, *, user_input):
    """ID나 이름#태그를 사용하여 밴된 사용자를 언밴합니다."""
    banned_users = [entry async for entry in ctx.guild.bans()]
    target_user = None

    try:
        user_id = int(user_input)
        for ban_entry in banned_users:
            if ban_entry.user.id == user_id:
                target_user = ban_entry.user
                break
    except ValueError:
        for ban_entry in banned_users:
            # 이름#태그 형식 또는 이름만으로 검색
            if f"{ban_entry.user.name}#{ban_entry.user.discriminator}" == user_input or ban_entry.user.name == user_input:
                target_user = ban_entry.user
                break
            
    if target_user:
        try:
            await ctx.guild.unban(target_user)
            embed = discord.Embed(title="😇 사용자 언밴 처리 완료", description=f'**{target_user.name}**님의 밴이 해제되었습니다.', color=discord.Color.green())
            await ctx.send(embed=embed)
        except Exception as e:
            embed = discord.Embed(title="⚠️ 언밴 처리 오류", description=f"언밴 처리 중 오류가 발생했습니다: `{e}`", color=discord.Color.orange())
            await ctx.send(embed=embed)
    else:
        embed = discord.Embed(title="❓ 사용자 찾기 실패", description=f"**{user_input}**님은 밴 목록에서 찾을 수 없거나 이미 언밴되었습니다.", color=discord.Color.light_grey())
        await ctx.send(embed=embed)


# ====================================================================
# ----------------- 6. 🎫 티켓 시스템 -----------------
# ====================================================================

@bot.command(name='티켓')
async def create_ticket(ctx):
    guild = ctx.guild
    author = ctx.author
    
    # 기존 티켓이 있는지 확인 (사용자 이름 기반 검색)
    for channel in guild.text_channels:
        if channel.name.startswith(f"티켓-{author.name.lower().replace(' ', '-').replace('_', '-')}"):
            embed = discord.Embed(
                title="🎫 티켓 생성 실패", 
                description=f"{author.mention}님, 이미 열려 있는 티켓 채널이 있습니다! 👉 {channel.mention}", 
                color=discord.Color.orange()
            )
            await ctx.send(embed=embed)
            return

    # 유효한 채널 이름 형식으로 변환 및 랜덤 숫자 추가
    # 이름에 특수문자나 띄어쓰기가 있을 경우를 대비하여 채널 이름 정리
    base_name = author.name.lower().replace(' ', '-').replace('_', '-').encode('ascii', 'ignore').decode('ascii')
    ticket_channel_name = f"티켓-{base_name}-{random.randint(100, 999)}"
    
    # 오버라이트 설정
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        author: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
    }

    # 서버 소유자에게도 메시지 읽기/쓰기 권한 부여
    if guild.owner:
        overwrites[guild.owner] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

    try:
        channel = await guild.create_text_channel(
            name=ticket_channel_name,
            overwrites=overwrites,
            reason=f"{author.name}님의 티켓 생성"
        )
        
        embed = discord.Embed(
            title="🎫 티켓 채널이 생성되었습니다!",
            description=f"안녕하세요 {author.mention}님!\n문의하실 내용을 여기에 적어주시면 관리자가 곧 확인하겠습니다.",
            color=discord.Color.green()
        )
        embed.set_footer(text=f"티켓을 닫으시려면 '{BOT_PREFIX}티켓종료'를 입력해 주세요.")
        
        await channel.send(f"{author.mention} (관리자)", embed=embed) # 관리자 멘션은 필요에 따라 추가
        
        confirm_embed = discord.Embed(
            title="✅ 티켓 채널 생성 완료", 
            description=f"{author.mention}님, 티켓 채널이 생성되었습니다: {channel.mention}", 
            color=discord.Color.green()
        )
        await ctx.send(embed=confirm_embed)

    except discord.Forbidden:
        forbidden_embed = discord.Embed(
            title="❌ 권한 오류 (Forbidden)", 
            description="봇에게 **'채널 관리'** 권한이 없어서 티켓을 만들 수 없었습니다. 봇의 권한 설정을 확인해 주세요.", 
            color=discord.Color.dark_red()
        )
        await ctx.send(embed=forbidden_embed)
    except Exception as e:
        error_embed = discord.Embed(
            title="⚠️ 티켓 생성 중 오류", 
            description=f"티켓 생성 중 오류가 발생했습니다: `{e}`", 
            color=discord.Color.orange()
        )
        await ctx.send(embed=error_embed)

@bot.command(name='티켓종료', aliases=['티켓삭제', 'close'])
async def close_ticket(ctx):
    if "티켓-" in ctx.channel.name:
        closing_embed = discord.Embed(title="🔒 티켓 채널 삭제 예정", description="5초 뒤에 티켓 채널이 삭제될 예정입니다. 이용해 주셔서 감사합니다.", color=discord.Color.blue())
        await ctx.send(embed=closing_embed)
        
        await asyncio.sleep(5)
        try:
            await ctx.channel.delete(reason="티켓 종료")
        except discord.Forbidden:
            error_embed = discord.Embed(title="❌ 권한 오류 (Forbidden)", description="봇에게 **'채널 관리'** 권한이 없어서 채널을 삭제할 수 없습니다.", color=discord.Color.dark_red())
            await ctx.send(embed=error_embed)
    else:
        error_embed = discord.Embed(title="❌ 잘못된 채널", description="이곳은 티켓 채널이 아닙니다. 티켓 채널에서 사용해 주세요.", color=discord.Color.red())
        await ctx.send(embed=error_embed)

# ====================================================================
# ----------------- 7. ★ KBO 명령어 (수정 적용) ★ -----------------
# ====================================================================

@bot.command(name='KBO', aliases=['야구', '순위'])
async def kbo_rank(ctx):
    await_embed = discord.Embed(title="⚾ KBO 순위 정보 확인 중", description='잠시만 기다려주세요, KBO 홈페이지에서 최신 순위를 가져오고 있습니다...', color=discord.Color.light_grey())
    message_to_edit = await ctx.send(embed=await_embed) 
    
    loop = asyncio.get_event_loop()
    # 크롤링은 Blocking 작업이므로 Executor를 사용하여 비동기로 실행
    rankings = await loop.run_in_executor(None, fetch_kbo_rankings) 

    if rankings:
        rank_data = ''
        
        # 헤더는 공백을 사용하여 수동으로 간격을 맞춥니다.
        # 이 헤더 정렬과 아래 rank_data의 정렬을 최대한 맞추는 것이 중요합니다.
        header = '순위 | 팀명 | 경기 | 승 | 패 | 무 | 승률 | 게임차'
        
        # 💡 [핵심 수정]: ljust 사용을 피하고, 파이썬 문자열 포맷팅을 사용하여
        # 코드 블록 내에서 상대적인 간격을 유지하도록 수정합니다.
        for team in rankings:
            rank_data += (
                f"{team['rank']:<3}|"    # 순위 (< 왼쪽 정렬, 3칸 확보)
                f"{team['team']:<4}|"    # 팀명 (< 왼쪽 정렬, 4칸 확보)
                f"{team['games']:>4}|"   # 경기 (> 오른쪽 정렬, 4칸 확보)
                f"{team['win']:>3}|"     # 승 (> 오른쪽 정렬, 3칸 확보)
                f"{team['lose']:>3}|"    # 패
                f"{team['draw']:>3}|"    # 무
                f"{team['pct']:>6}|"     # 승률
                f"{team['gb']:>4}\n"     # 게임차
            )
        
        # 헤더 아래에 구분선 생성
        separator = '-' * (len(header) + 4) # 헤더 길이 기반으로 적절히 늘려서 사용
        
        embed = discord.Embed(
            title=f"⚾ {date.today().year} KBO 리그 실시간 순위",
            url='https://www.koreabaseball.com/',
            # 코드 블록을 사용하여 텍스트 정렬 유지
            description='```\n' + header + '\n' + separator + '\n' + rank_data + '```\nKBO 공식 홈페이지 기준 데이터입니다.',
            color=discord.Color.blue()
        )
        
        embed.set_footer(text=f'데이터 출처: KBO (koreabaseball.com) | 기준 시간: {discord.utils.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")}')

        await message_to_edit.edit(embed=embed)
    else:
        fail_embed = discord.Embed(
            title='❌ KBO 순위 정보 로딩 실패', 
            description='KBO 순위 정보를 가져오는 데 실패했습니다. 잠시 후 다시 시도해 주세요.\n(서버 콘솔의 에러 로그를 확인해 주십시오)',
            color=discord.Color.red()
        )
        await message_to_edit.edit(embed=fail_embed)

# ====================================================================
# ----------------- 8. 경제 및 레벨 시스템 -----------------
# ====================================================================

@bot.command(name='엘도라도프로', aliases=['정보'])
async def eldorado_pro_command(ctx):
    embed = discord.Embed(
        title="🌟 엘도라도 PRO 소개",
        description="엘도라도 PRO는 엘도라도가 만든 차세대 최첨단 봇입니다. 편리한 기능을 이용해 보세요!",
        color=discord.Color.from_rgb(18, 144, 255)
    )
    
    avatar_url = ctx.bot.user.avatar.url if ctx.bot.user.avatar else ctx.bot.user.default_avatar.url
    embed.set_thumbnail(url=avatar_url)
    
    # 여러 줄 문자열을 안전하게 구성
    commands_list = (
        f"⚾ **스포츠:** `{BOT_PREFIX}KBO` (실시간 야구 순위)\n"
        f"💰 **경제:** `{BOT_PREFIX}돈`, `{BOT_PREFIX}돈줘`, `{BOT_PREFIX}베팅`, `{BOT_PREFIX}가바보`, `!주식`, `!주식사기`, `!주식팔기`\n"
        f"📊 **레벨:** `{BOT_PREFIX}출석`, `{BOT_PREFIX}레벨`\n"
        f"🎫 **티켓:** `{BOT_PREFIX}티켓`, `{BOT_PREFIX}티켓종료`\n"
        f"🎲 **뽑기:** `{BOT_PREFIX}인원수설정 (최대 숫자)`, `{BOT_PREFIX}뽑기 (횟수)`\n"
        f"🚨 **경고:** `{BOT_PREFIX}경고`, `{BOT_PREFIX}경고추가`, `{BOT_PREFIX}경고제거`\n"
        f"💀 **처벌/해제:** `{BOT_PREFIX}주거라` (밴), `{BOT_PREFIX}살려라` (밴 해제)\n" # 주석은 문자열 밖으로!
        f"🤖 **AI:** `!엘도라도프로야`, `!그려줘`" # 마지막 줄은 \n이 없어도 돼
    )

    embed.add_field(
        name="기능 목록 안내",
        value=commands_list,
        inline=False
    )
    
    embed.set_footer(text=f"봇 개발: 엘도라도 | 접두사: {BOT_PREFIX}")
    await ctx.send(embed=embed)
    
@bot.command(name="출석", aliases=['출첵', 'ㅊㅊ'])
async def check_attendance(ctx):
    data = load_data()
    user_id_str = str(ctx.author.id)
    user_data = get_user_data(data, user_id_str)
    now = datetime.datetime.now()
    
    # 쿨타임 체크 로직
    time_left = calculate_time_left(user_data.get("마지막 출석시간"), ATTENDANCE_COOLDOWN_HOURS)
    
    if time_left.total_seconds() > 0:
        time_str = format_timedelta(time_left)
        embed = discord.Embed(title="📅 출석 실패", description=f"출석은 **{ATTENDANCE_COOLDOWN_HOURS}시간**마다 가능합니다.", color=discord.Color.red())
        embed.set_footer(text=f"다음 출석까지 남은 시간: {time_str}")
        await ctx.send(embed=embed) 
        return

    # 보상 지급 로직
    earned_money = random.randint(100, 200) 
    user_data["money"] += earned_money
    user_data["출석횟수"] += 1
    earned_exp = random.uniform(1.0, 1.5)
    user_data["경험치"] += earned_exp
    user_data["마지막 출석일"] = date.today().isoformat()
    user_data["마지막 출석시간"] = now.isoformat()
    
    save_data(data)
    
    embed = discord.Embed(title="✨ 출석 완료!", description=f"성공적으로 출석하여 보상이 지급되었습니다.", color=discord.Color.green())
    embed.add_field(name="💰 획득 금액", value=f"**{earned_money:,}원**", inline=True)
    embed.add_field(name="📊 획득 경험치", value=f"**{earned_exp:.2f} EXP**", inline=True)
    embed.set_footer(text=f"현재 잔고: {user_data['money']:,}원 | 다음 출석까지 {ATTENDANCE_COOLDOWN_HOURS}시간")
    
    await ctx.send(embed=embed)

@bot.command(name="레벨")
async def show_level(ctx):
    data = load_data()
    user_data = get_user_data(data, ctx.author.id)
    total_exp = user_data["경험치"]
    
    level = 0
    base_required = 10 # 레벨 0 -> 1에 필요한 기본 경험치
    exp_copy = total_exp
    req_next = base_required
    
    # 레벨 계산 로직: 10, 20, 30, 40...
    while exp_copy >= req_next:
        exp_copy -= req_next
        level += 1
        req_next = base_required + level * 10 # 다음 레벨 요구 경험치 (레벨 1 -> 2는 20, 레벨 2 -> 3은 30)

    exp_curr = exp_copy 
    req_curr = base_required + level * 10 
    percent = (exp_curr / req_curr) * 100 if req_curr > 0 else 0
    
    embed = discord.Embed(title=f"📊 {ctx.author.display_name}님의 레벨 정보", color=discord.Color.blue())
    embed.set_thumbnail(url=ctx.author.avatar.url if ctx.author.avatar else ctx.author.default_avatar.url)
    embed.add_field(name="현재 레벨", value=f"**{level}**", inline=True)
    embed.add_field(name="총 경험치", value=f"{total_exp:.2f} EXP", inline=True)
    embed.add_field(name="출석 횟수", value=f"{user_data['출석횟수']}회", inline=True)
    embed.add_field(name="다음 레벨까지", value=f"**{req_curr - exp_curr:.2f} EXP** 필요 (총 {req_curr:.2f} EXP)", inline=False)
    embed.add_field(name="진행도", value=f"레벨 {level}의 {percent:.1f}%", inline=True)
    await ctx.send(embed=embed)

@bot.command(name="돈", aliases=["잔고", "지갑"])
async def money(ctx):
    data = load_data()
    user_data = get_user_data(data, ctx.author.id)
    embed = discord.Embed(
        title="💰 현재 잔고", 
        description=f"**{ctx.author.display_name}**님의 현재 잔고는 **{user_data['money']:,}원** 입니다.", 
        color=discord.Color.gold()
    )
    await ctx.send(embed=embed)

@bot.command(name="돈줘", aliases=["일일보상"])
async def daily_reward(ctx):
    data = load_data()
    user_id_str = str(ctx.author.id)
    user_data = get_user_data(data, user_id_str)
    now = datetime.datetime.now()
    
    # 쿨타임 체크 로직
    time_left = calculate_time_left(user_data.get("last_daily"), DAILY_COOLDOWN_HOURS)
    
    if time_left.total_seconds() > 0:
        time_str = format_timedelta(time_left)
        embed = discord.Embed(title="😅 잠깐만요!", description=f"일일 보상은 **{DAILY_COOLDOWN_HOURS}시간**마다 받으실 수 있습니다.", color=discord.Color.orange())
        embed.set_footer(text=f"다음 보상까지 남은 시간: {time_str}")
        await ctx.send(embed=embed)
        return
            
    reward = 10000
    user_data["money"] += reward
    user_data["last_daily"] = now.isoformat() 
    save_data(data)
    
    embed = discord.Embed(title="🎁 일일 보상 지급 완료!", description=f"**{reward:,}원**이 성공적으로 지급되었습니다.", color=discord.Color.yellow())
    embed.set_footer(text=f"현재 잔고: {user_data['money']:,}원")
    await ctx.send(embed=embed)

@bot.command(name="베팅")
async def bet(ctx, amount: int = None):
    if amount is None or amount <= 0:
        embed = discord.Embed(title="❌ 베팅 오류", description="베팅하실 **올바른 금액(1원 이상)**을 숫자로 입력해 주세요.\n사용법: `!베팅 [금액]`", color=discord.Color.red())
        await ctx.send(embed=embed)
        return
        
    data = load_data()
    user_data = get_user_data(data, str(ctx.author.id))
    
    if amount > user_data['money']:
        embed = discord.Embed(title="❌ 잔고 부족", description=f"현재 잔고 **{user_data['money']:,}원**보다 많은 금액을 베팅하실 수 없습니다!", color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    # 50% 확률로 승리
    if random.random() < 0.5:
        user_data['money'] += amount
        embed = discord.Embed(title="🎉 베팅 성공!", description=f"**{amount:,}원**을 획득하셨습니다! (총 2배)", color=discord.Color.green())
        embed.set_footer(text=f"현재 잔고: {user_data['money']:,}원")
    else:
        user_data['money'] -= amount
        embed = discord.Embed(title="💸 베팅 실패...", description=f"**{amount:,}원**을 잃으셨습니다.", color=discord.Color.red())
        embed.set_footer(text=f"현재 잔고: {user_data['money']:,}원")
    
    save_data(data)
    await ctx.send(embed=embed)

@bot.command(name="가바보")
async def rps(ctx, user_choice: str = None):
    valid = ["가위", "바위", "보"]
    if user_choice is None or user_choice.lower() not in [v.lower() for v in valid]:
        embed = discord.Embed(title="⚠️ 입력 오류", description="**가위, 바위, 보** 중 하나를 정확히 입력해 주세요.\n사용법: `!가바보 [가위/바위/보]`", color=discord.Color.orange())
        await ctx.send(embed=embed)
        return

    # 대소문자 무시를 위해 입력된 선택을 정규화
    user_choice_normalized = user_choice.capitalize()
    if user_choice_normalized not in valid:
          # "바위"의 오타로 들어왔을 경우 등을 위해 다시 한번 체크
        user_choice_normalized = user_choice 

    data = load_data()
    user_data = get_user_data(data, str(ctx.author.id))
    
    bot_choice = random.choice(valid)
    
    # 승리 조건 체크
    if (user_choice_normalized == "가위" and bot_choice == "보") or \
       (user_choice_normalized == "바위" and bot_choice == "가위") or \
       (user_choice_normalized == "보" and bot_choice == "바위"):
        result = "승리"
        user_data["money"] += RPS_REWARD
        color = discord.Color.green()
    elif user_choice_normalized == bot_choice:
        result = "무승부"
        # 무승부 시 상금의 절반 지급
        user_data["money"] += int(RPS_REWARD / 2)
        color = discord.Color.light_grey()
    else:
        result = "패배"
        color = discord.Color.red()

    save_data(data)
    
    embed = discord.Embed(title=f"✌️ 가위바위보 결과: {result}", description=f"👤 **{ctx.author.display_name}**님의 선택: {user_choice_normalized}\n🤖 **봇**의 선택: {bot_choice}", color=color)
    
    if result == "승리":
        embed.set_footer(text=f"보상: +{RPS_REWARD:,}원 | 현재 잔고: {user_data['money']:,}원")
    elif result == "무승부":
        embed.set_footer(text=f"보상: +{int(RPS_REWARD / 2):,}원 (소정의 무승부 보상) | 현재 잔고: {user_data['money']:,}원")
    else:
        embed.set_footer(text=f"현재 잔고: {user_data['money']:,}원")
    
    await ctx.send(embed=embed)

# ====================================================================
# ----------------- 9. 경고 시스템 -----------------
# ====================================================================

@bot.command(name='경고추가')
@commands.has_permissions(kick_members=True)
async def add_warn(ctx, member: discord.Member, count: int = 1):
    data = load_data()
    user_data = get_user_data(data, str(member.id))
    user_data["warnings"] += count
    save_data(data)
    
    embed = discord.Embed(
        title="🚨 경고 추가 완료", 
        description=f"**{member.display_name}**님께 경고 **+{count}회**가 추가되었습니다.", 
        color=discord.Color.orange()
    )
    embed.set_footer(text=f"현재 총 경고 횟수: {user_data['warnings']}회 (처리 관리자: {ctx.author.display_name})")
    await ctx.send(embed=embed)

@bot.command(name='경고제거')
@commands.has_permissions(kick_members=True)
async def remove_warn(ctx, member: discord.Member, count: int = 1):
    data = load_data()
    user_data = get_user_data(data, str(member.id))
    user_data["warnings"] = max(0, user_data["warnings"] - count)
    save_data(data)
    
    embed = discord.Embed(
        title="➖ 경고 제거 완료", 
        description=f"**{member.display_name}**님의 경고 **-{count}회**가 차감되었습니다.", 
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"현재 총 경고 횟수: {user_data['warnings']}회 (처리 관리자: {ctx.author.display_name})")
    await ctx.send(embed=embed)

@bot.command(name='경고')
async def check_warn(ctx, member: discord.Member = None):
    target = member or ctx.author
    data = load_data()
    cnt = get_user_data(data, str(target.id))["warnings"]
    
    embed = discord.Embed(
        title="⚠️ 경고 횟수 확인", 
        description=f"**{target.display_name}**님의 현재 경고 횟수는 **{cnt}회**입니다.", 
        color=discord.Color.gold()
    )
    await ctx.send(embed=embed)

# ====================================================================
# ----------------- 10. 숫자 뽑기 기능 -----------------
# ====================================================================

# ⚙️ "!인원수설정 (최대 숫자)" 명령어
@bot.command(name='인원수설정')
@commands.has_permissions(manage_guild=True)
async def set_number_range(ctx, count: int = None):
    """서버의 무작위 숫자 뽑기 최대 범위를 설정합니다. (1부터 N까지)"""
    
    if ctx.guild is None:
        embed = discord.Embed(title="❌ 서버 전용 명령어", description="이 명령어는 **DM이 아닌 서버 채널**에서만 사용할 수 있습니다.", color=discord.Color.dark_red())
        await ctx.send(embed=embed)
        return

    if count is None:
        current_count = server_range_settings.get(ctx.guild.id, 0)
        embed = discord.Embed(title="💡 현재 뽑기 범위", description=f"현재 뽑기 범위는 **1부터 {current_count}**까지로 설정되어 있습니다.", color=discord.Color.dark_teal())
        await ctx.send(embed=embed)
        return

    if count <= 0:
        embed = discord.Embed(title="❌ 범위 설정 오류", description="범위의 최대 숫자는 1 이상으로 설정해야 합니다.", color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    server_range_settings[ctx.guild.id] = count
    
    embed = discord.Embed(
        title="✅ 뽑기 범위 설정 완료", 
        description=f"뽑기 범위가 **1부터 {count}**까지로 설정되었습니다!", 
        color=discord.Color.green()
    )
    embed.set_footer(text=f"이제 {BOT_PREFIX}뽑기 [횟수] 명령어로 해당 범위 내의 숫자를 무작위로 뽑을 수 있습니다.")
    await ctx.send(embed=embed)

# 🔢 "!뽑기 [횟수]" 명령어 (여러 개 뽑기 가능)
@bot.command(name='뽑기', aliases=['랜덤숫자'])
async def pick_random_number(ctx, count: int = 1): 
    """설정된 범위(1부터 N) 내에서 무작위 숫자를 1개 또는 지정된 횟수만큼 뽑습니다."""
    
    if ctx.guild is None:
        embed = discord.Embed(
            title="❌ DM 지원 불가", 
            description=f"뽑기 기능은 **서버 채널**에서만 사용할 수 있습니다. (서버별로 `{BOT_PREFIX}인원수설정`이 필요합니다.)", 
            color=discord.Color.dark_red()
        )
        await ctx.send(embed=embed)
        return

    # 1. 설정된 인원수(최대 범위) 확인
    max_range = server_range_settings.get(ctx.guild.id)
    
    if max_range is None or max_range == 0:
        embed = discord.Embed(
            title="❌ 뽑기 범위 미설정", 
            description=f"먼저 `{BOT_PREFIX}인원수설정 (숫자)` 명령어로 뽑을 최대 범위(숫자)를 **1 이상**으로 설정해야 합니다.", 
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    # 2. 횟수 및 유효성 검사
    if count <= 0:
        embed = discord.Embed(title="❌ 횟수 오류", description="뽑을 횟수는 1 이상으로 지정해 주세요.", color=discord.Color.red())
        await ctx.send(embed=embed)
        return
        
    if count > max_range:
        embed = discord.Embed(
            title="❌ 횟수 초과", 
            description=f"설정된 최대 범위는 **{max_range}**입니다. 뽑을 횟수를 이보다 적게 지정해 주세요.", 
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    # 3. 무작위 숫자 뽑기 (중복 없이)
    try:
        # random.sample(범위, 횟수)를 사용하여 중복 없이 뽑기
        picked_numbers = random.sample(range(1, max_range + 1), count)
        picked_numbers.sort()
        
        # 결과 메시지 포맷팅
        if count == 1:
            result_title = f"🎲 무작위 숫자 뽑기 결과!"
            result_value = f"## **{picked_numbers[0]}**"
        else:
            result_title = f"🎲 총 {count}개의 숫자 뽑기 결과!"
            result_value = ', '.join([f'**{n}**' for n in picked_numbers]) 

    except ValueError:
        embed = discord.Embed(title="⚠️ 뽑기 오류", description="뽑을 수 있는 유효한 범위나 횟수가 아닙니다. 설정을 다시 확인해 주세요.", color=discord.Color.orange())
        await ctx.send(embed=embed)
        return

    # 4. 결과 출력
    embed = discord.Embed(
        title=result_title,
        description=f"**1**부터 **{max_range}** 범위 내에서 무작위로 뽑은 숫자입니다.",
        color=discord.Color.purple()
    )
    
    embed.add_field(name="🎉 당첨된 숫자", value=result_value, inline=False)
    
    await ctx.send(embed=embed)

# ====================================================================
# ----------------- 11. 주식 관련 명령어 (통합 버전) -----------------
# ====================================================================

@bot.command(name="주식")
async def show_stocks(ctx):
    embed = discord.Embed(
        title="📈 엘도라도 증권", 
        description="5초마다 시세가 자동으로 변동됩니다.", 
        color=0x00ff00
    )
    for name, info in stocks.items():
        diff = info['change']
        mark = "🔺" if diff > 0 else "▼" if diff < 0 else "➖"
        embed.add_field(
            name=name, 
            value=f"현재가: **{info['price']:,}원**\n변동: {mark} {abs(diff):,}원", 
            inline=False
        )
    embed.set_footer(text=f"요청자: {ctx.author.display_name}")
    await ctx.send(embed=embed)

@bot.command(name="주식사기")
async def buy_stock(ctx, name: str, amount: int):
    if name not in stocks:
        return await ctx.send("❌ 해당 회사는 존재하지 않습니다.")
    if amount <= 0:
        return await ctx.send("❌ 1주 이상부터 구입 가능합니다.")

    # [수정] data.json에서 통합 유저 데이터 로드
    data = load_data()
    user = get_user_data(data, ctx.author.id)
    
    total_cost = stocks[name]["price"] * amount
    
    if user["money"] < total_cost:
        return await ctx.send(f"❌ 잔액이 부족합니다. (현재 잔액: {user['money']:,}원 / 필요: {total_cost:,}원)")
    
    # 돈 차감 및 인벤토리 업데이트
    user["money"] -= total_cost
    user["stocks"][name] = user.get("stocks", {}).get(name, 0) + amount
    
    # [수정] 변경 사항 저장
    save_data(data)
    await ctx.send(f"✅ {name} 주식 {amount}주 매수가 완료되었습니다. (남은 돈: {user['money']:,}원)")

@bot.command(name="주식팔기")
async def sell_stock(ctx, name: str):
    # [수정] data.json에서 통합 유저 데이터 로드
    data = load_data()
    user = get_user_data(data, ctx.author.id)
    
    # 유저가 보유한 주식 수량 확인 (기본값 0)
    inventory = user.get("stocks", {})
    amount = inventory.get(name, 0)
    
    if name not in stocks or amount <= 0:
        return await ctx.send(f"❌ 보유 중인 {name} 주식이 없습니다.")
    
    total_price = stocks[name]["price"] * amount
    
    # 돈 추가 및 주식 삭제
    user["money"] += total_price
    del user["stocks"][name]
    
    # [수정] 변경 사항 저장
    save_data(data)
    await ctx.send(f"💰 {name} 주식 {amount}주 전량 매도! {total_price:,}원이 입급되었습니다. (잔액: {user['money']:,}원)")

# --- [기존 기능: 대화 및 그림 (Bot 2)] ---

@bot.command(name="엘도라도프로야", aliases=["대화", "질문", "AI야"])
async def chat_with_gemini(ctx, *, content: str):
    async with ctx.typing():
        try:
            if ctx.channel.id not in chat_sessions:
                chat_sessions[ctx.channel.id] = []
            
            personality = (
                "너의 이름은 '엘도라도 PRO'야."
                "사용자에게 친근하게 반말을 사용해줘."
                "이모지는 꼭 필요할 때 한두 개만 쓰고 너무 많이 쓰지 마."
                "이전 대화 내용을 참고해서 맥락에 맞는 대답을 해줘."
                "답변은 반드시 한글로 해줘."
                "너의 공식 사이트는 https://kas_roka.enn.kr 이고 매 질문마다 링크를 넣지 말고 사이트 링크를 알려달라고 할 때만 알려 줘."
            )

            response = client.models.generate_content(
                model="models/gemini-3-flash-preview", # 최신 모델로 수정 권장
                contents=chat_sessions[ctx.channel.id] + [content],
                config={"system_instruction": personality}
            )
            response_text = response.text
            
            chat_sessions[ctx.channel.id].append(content)
            chat_sessions[ctx.channel.id].append(response_text)
            if len(chat_sessions[ctx.channel.id]) > 20:
                chat_sessions[ctx.channel.id] = chat_sessions[ctx.channel.id][-20:]

            if len(response_text) > 2000:
                with open("answer.txt", "w", encoding="utf-8-sig") as f:
                    f.write(response_text)
                await ctx.send("📄 너무 길어서 파일로 보낼게!", file=discord.File("answer.txt"))
                os.remove("answer.txt")
            else:
                await ctx.send(response_text)
                
        except Exception as e:
            await ctx.send(f"🚨 오류 발생: {e}")

@bot.command(name="그려줘", aliases=["그림", "그리기", "AI그림"])
async def draw_image(ctx, *, prompt: str):
    async with ctx.typing():
        try:
            encoded_prompt = urllib.parse.quote(prompt)
            seed = random.randint(1, 999999)
            image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?seed={seed}&width=1024&height=1024&nologo=true"
            
            embed = discord.Embed(title="🎨 엘도라도 PRO의 화방", description=f"**요청:** {prompt}", color=0x3498db)
            embed.set_image(url=image_url)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"🚨 그림 오류: {e}")

# ====================================================================
# ----------------- 12. 봇 실행 -----------------
# ====================================================================

if __name__ == "__main__":
    print("Copyright 2025-2026 엘도라도 All Rights Reserved.")
    print("이 봇에대한 저작권은 2025-2026년에 만들어졌으며, 모든 권한은 엘도라도에게 있습니다.")
    
    # 🚨 주의: 실제로 봇을 실행할 때는 유효한 토큰으로 교체하세요.
    if not BOT_TOKEN or BOT_TOKEN.startswith("MTQ0NzQ0ODAwNjMyODIzODE0Mw"):
          print("🚨 디스코드 토큰 오류: 'MTQ0NzQ0ODAwNjMyODIzODE0Mw...' 토큰은 테스트용이거나 유효하지 않습니다. BOT_TOKEN 변수에 유효한 토큰을 넣어주세요.")
    else:
        try:
            bot.run(BOT_TOKEN)
        except discord.LoginFailure:
            print("🚨 디스코드 토큰 오류: 토큰을 다시 확인해 주십시오.")
        except Exception as e:
            print(f"🚨 봇 실행 중 알 수 없는 오류 발생: {e}")