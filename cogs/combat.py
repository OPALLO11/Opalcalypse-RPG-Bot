import asyncio
import os

from twitchio.ext import commands

from database import db
from game.boss_manager import boss_manager
from game.combat import process_action, get_party_data
from utils import emit_to_overlay


class CombatCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _process_rpg_action(self, ctx: commands.Context, action: str, skill_name: str = None, target: str = None):
        username = ctx.author.name
        player = db.get_player(username)
        if not player:
            asyncio.create_task(ctx.send(f"@{username} Please !register <character_name> before attacking."))
            return

        res = process_action(player, action, skill_name=skill_name, target=target)
        if res['success']:
            if action == 'def':
                asyncio.create_task(ctx.send(f"🛡️ @{username} ตั้งท่าหลบการโจมตีหมู่!"))
            elif action == 'skill' and player.get('class', 'warrior').lower() == 'priest':
                # Announcements for Priest skills are handled inside their returned messages
                asyncio.create_task(ctx.send(f"@{username} ✨ {res['message']}"))
            elif action == 'ultimate' and player.get('class', 'warrior').lower() == 'priest':
                asyncio.create_task(ctx.send(f"@{username} ✨ {res['message']}"))
            else:
                # Normal attack message
                asyncio.create_task(ctx.send(f"@{username} {res['message']}"))

            event_data = {
                'username': username,
                'action': res.get('action_name', action) if action != 'def' else f"Defend ({res.get('action_name')})",
                'damage': res['damage'],
                'is_crit': res['is_crit'],
                'boss_hp': res['boss_hp']
            }
            emit_to_overlay('combat_event', event_data)

            boss_state = res.get('boss_state', {})
            if boss_state.get('warning'):
                boss = boss_manager.get_current_boss()
                boss_name = boss['name'] if boss else 'บอส'
                next_atk = boss_state.get('next_attack', {})
                atk_name = next_atk.get('name', 'Mighty Strike')
                atk_type = next_atk.get('type', 'physical')

                type_th = "กายภาพ"
                if atk_type == "magic":
                    type_th = "เวทมนตร์"
                elif atk_type == "piercing":
                    type_th = "ทะลวง"

                asyncio.create_task(ctx.send(
                    f"⚠️ บอส {boss_name} กำลังจะใช้ท่า「{atk_name}」({type_th})! "
                    f"จะโจมตีหมู่ภายใน 20 วินาที! "
                    f"(พิมพ์ !def <สกิล> เพื่อหลบ หรือเสี่ยงตีต่อได้)"
                ))
                emit_to_overlay('combat_event', {
                    'username': '⚠️ WARNING',
                    'action': f"บอสจะใช้ {atk_name} ({type_th}) ในอีก 20 วินาที!",
                    'damage': 0, 'is_crit': False,
                    'boss_hp': res['boss_hp']
                })
                emit_to_overlay('boss_charging', {
                    'boss_name': boss_name,
                    'attack_name': atk_name,
                    'attack_type': atk_type,
                    'duration': 20
                })

            if not res.get('is_dead'):
                emit_to_overlay('boss_update', boss_manager.get_current_boss())

            if res.get('is_dead'):
                # Collect loot and gold details
                loot_data = res.get('loot', {})
                gold_rewards = res.get('gold_rewards', {})
                drops_text = []
                gold_text_list = []
                gold_rewards_detail = []

                # Parse gold rewards
                if gold_rewards:
                    for p_id, amount in gold_rewards.items():
                        p_info = db.players.get_player_basic(p_id, "username, character_name")
                        if p_info:
                            p_name = p_info['username']
                            p_char = p_info['character_name'] or p_name
                            gold_text_list.append(f"@{p_name} ได้ {amount:,}G")
                            gold_rewards_detail.append({
                                'player_id': p_id,
                                'username': p_name,
                                'character_name': p_char,
                                'amount': amount
                            })

                # Parse loot
                if loot_data:
                    for player_id, item_doc in loot_data.items():
                        p_info = db.players.get_player_basic(player_id, "username")
                        if p_info:
                            p_name = p_info['username']
                            item_name = item_doc.get('item_name', 'Unknown Item')
                            tier = item_doc.get('tier', '')
                            full_name = f"[{tier}] {item_name}" if tier else item_name

                            act = item_doc.get('action', 'new')
                            if act == 'new':
                                drops_text.append(f"@{p_name} ได้ของใหม่: {full_name}")
                            elif act == 'enhanced':
                                new_lvl = item_doc.get('new_level', 1)
                                drops_text.append(f"@{p_name} อัปเกรดสำเร็จ! {full_name} เป็น +{new_lvl}")
                            elif act == 'failed_protected':
                                drops_text.append(f"@{p_name} อัปเกรดล้มเหลว! แต่ใบกันแตกป้องกันไม่ให้ของพัง!")
                            elif act == 'broke':
                                drops_text.append(f"@{p_name} 💥บวกแตก! {full_name} หายไปในอากาศ!")
                            elif act == 'converted_exp':
                                amt = item_doc.get('amount', 500)
                                drops_text.append(f"@{p_name} ของล้น! {full_name} ย่อยเป็น {amt} EXP")
                            else:
                                drops_text.append(f"@{p_name} got {full_name}")

                emit_to_overlay('boss_defeated', {
                    'winner': username,
                    'drops': drops_text,
                    'gold_rewards': gold_rewards_detail
                })

                # Announce in chat
                chat_parts = ["🎉 Boss Defeated!"]
                if gold_text_list:
                    chat_parts.append("💰 ส่วนแบ่ง Gold: " + ", ".join(gold_text_list))
                if drops_text:
                    chat_parts.append("🎁 Loot drops: " + ", ".join(drops_text))
                else:
                    chat_parts.append("🎁 Loot drops: ไม่มีใครได้ของ")

                asyncio.create_task(ctx.send(" | ".join(chat_parts)))

                asyncio.create_task(self._coro_respawn())
        else:
            if action == 'skill' and (
                    "สกิลของคุณ" in res['message'] or "Your skills" in res['message'] or not skill_name):
                asyncio.create_task(ctx.send(f"@{username} 📖 {res['message']}"))
            else:
                asyncio.create_task(ctx.send(f"@{username} ❌ {res['message']}"))

    async def _coro_respawn(self):
        await asyncio.sleep(10)
        boss = boss_manager.spawn_boss(1)
        emit_to_overlay('boss_update', boss)
        emit_to_overlay('party_update', get_party_data(boss))

    @commands.command(name='attack', aliases=['atk'])
    async def cmd_attack(self, ctx: commands.Context):
        self._process_rpg_action(ctx, 'attack')

    @commands.command(name='skill', aliases=['sk'])
    async def cmd_skill(self, ctx: commands.Context, skill_name: str = "", target: str = ""):
        self._process_rpg_action(ctx, 'skill', skill_name=skill_name.strip(), target=target.strip())

    @commands.command(name='ultimate', aliases=['ult'])
    async def cmd_ultimate(self, ctx: commands.Context):
        self._process_rpg_action(ctx, 'ultimate')

    @commands.command(name='def')
    async def cmd_def(self, ctx: commands.Context, skill_name: str = ""):
        self._process_rpg_action(ctx, 'def', skill_name=skill_name.strip())

    @commands.command(name='spawn', aliases=['sp', 'spwn'])
    async def cmd_spawn(self, ctx: commands.Context, type_arg: str = 'normal'):
        if not ctx.author.is_mod and ctx.author.name.lower() != os.environ.get('TWITCH_CHANNEL', '').lower():
            await ctx.send(f"@{ctx.author.name} ❌ You are not allowed to use this command!")
            return

        boss = boss_manager.spawn_boss(1, boss_type=type_arg.lower())
        if boss:
            emit_to_overlay('boss_update', boss)
            emit_to_overlay('party_update', get_party_data(boss))
            await ctx.send(f"[{boss['type'].upper()}] The {boss['name']} has been summoned by an admin!")
        else:
            await ctx.send(f"Failed to spawn boss. Invalid type: {type_arg}")

    @commands.command(name='resetchallenge')
    async def cmd_resetchallenge(self, ctx: commands.Context):
        if not ctx.author.is_mod and ctx.author.name.lower() != os.environ.get('TWITCH_CHANNEL', '').lower():
            await ctx.send(f"@{ctx.author.name} ❌ You are not allowed to use this command!")
            return

        from game.challenge_manager import spawn_challenge
        new_challenge = spawn_challenge()
        if new_challenge:
            await ctx.send(f"⚠️ ผู้ดูแลระบบได้รีเซ็ตความท้าทายใหม่! เป้าหมายปัจจุบัน: {new_challenge['description']}")
        else:
            await ctx.send("Failed to spawn new challenge.")


def prepare(bot: commands.Bot):
    bot.add_cog(CombatCog(bot))
