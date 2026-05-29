from twitchio.ext import commands

from database import db
from game.boss_manager import boss_manager
from game.helpers import find_item_data, get_level_requirement
from utils import send_streamerbot_message


class InfoCog(commands.Component):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name='test')
    async def cmd_test(self, ctx: commands.Context):
        await ctx.send("prefix command is working")

    @commands.command(name='boss')
    async def cmd_boss(self, ctx: commands.Context):
        boss = boss_manager.get_current_boss()
        if boss:
            weaknesses = ', '.join(boss.get('weakness', []))
            await ctx.send(f"Boss: {boss['name']} ({boss['current_hp']}/{boss['max_hp']}) Weak to: {weaknesses}")
        else:
            await ctx.send("No boss is currently active.")

    @commands.command(name='register', aliases=['reg', 'regis'])
    async def cmd_register(self, ctx: commands.Context, *args):
        args_list = list(args)
        from game.logic import CLASSES

        if len(args_list) < 2 or args_list[-1].lower() not in CLASSES:
            available_classes = ", ".join(CLASSES.keys())
            await ctx.send(
                f"❌ @{ctx.chatter.name} ลงทะเบียนไม่สำเร็จ! "
                f"กรุณากรอกข้อมูลให้ครบถ้วน: !register <ชื่อ> <อาชีพ> "
                f"(ตัวอย่าง: !register GM warrior หรือ !register Healer priest) "
                f"อาชีพที่มี: {available_classes}"
            )
            return

        class_name = args_list.pop().lower()
        character_name = " ".join(args_list)

        success = db.create_player(ctx.chatter.name, ctx.chatter.id, character_name, class_name)
        if success:
            await ctx.send(
                f"@{ctx.chatter.name} Successfully registered as '{character_name}' (Class: {class_name.capitalize()})!")
        else:
            await ctx.send(f"@{ctx.chatter.name} You are already registered.")

    @commands.command(name='changeclass', aliases=['cc', 'ccl'])
    async def cmd_changeclass(self, ctx: commands.Context, new_class: str = ""):
        if not new_class:
            await ctx.send(f"@{ctx.chatter.name} Usage: !changeclass <class>")
            return

        player = db.get_player(ctx.chatter.name)
        if not player:
            await ctx.send(f"@{ctx.chatter.name} You need to !register first.")
            return

        if player.get('session_class_changed'):
            await ctx.send(f"@{ctx.chatter.name} You have already changed your class in this stream/session.")
            return

        from game.logic import CLASSES
        new_class = new_class.lower()
        if new_class not in CLASSES:
            await ctx.send(f"@{ctx.chatter.name} Invalid class. Available classes: {', '.join(CLASSES.keys())}")
            return

        if player.get('class') == new_class:
            await ctx.send(f"@{ctx.chatter.name} You are already a {new_class.capitalize()}.")
            return

        # Recalculate stats for the new class
        temp_player = player.copy()
        temp_player['class'] = new_class
        # Ensure we use level for the new class if they have levels in it
        cls_data = temp_player.get('class_levels', {}).get(new_class, {'level': 1})
        temp_player['level'] = cls_data.get('level', 1)

        from game.logic import calculate_player_stats
        s = calculate_player_stats(temp_player)

        success = db.update_player(player['id'], {
            'class': new_class,
            'session_class_changed': 1,
            'hp': s['max_hp'],
            'mp': s['max_mp']
        })

        if success:
            await ctx.send(f"@{ctx.chatter.name} Successfully changed class to {new_class.capitalize()}!")
        else:
            await ctx.send(f"@{ctx.chatter.name} Failed to change class.")

    @commands.command(name='rename')
    async def cmd_rename(self, ctx: commands.Context, *, new_name: str = ""):
        if not new_name:
            await ctx.send(f"@{ctx.chatter.name} Please provide a new name: !rename <name>")
            return

        player = db.get_player(ctx.chatter.name)
        if not player:
            await ctx.send(f"@{ctx.chatter.name} You need to !register first.")
            return

        if player.get('session_renamed'):
            await ctx.send(f"@{ctx.chatter.name} You have already renamed your character in this stream/session.")
            return

        success = db.update_player(player['id'], {
            'character_name': new_name,
            'session_renamed': 1
        })

        if success:
            await ctx.send(f"@{ctx.chatter.name} Successfully renamed to '{new_name}'!")
        else:
            await ctx.send(f"@{ctx.chatter.name} Failed to rename your character.")

    @commands.command(name='inventory', aliases=['inv'])
    async def cmd_inventory(self, ctx: commands.Context):
        player = db.get_player(ctx.chatter.name)
        if not player:
            await ctx.send(f"@{ctx.chatter.name} Please !register first.")
            return

        # Get items via repository
        items = db.items.get_items_by_owner(player['id'])

        if not items:
            await ctx.send(f"@{ctx.chatter.name} Your inventory is empty.")
            return

        item_list_str = []
        for db_item in items:
            item_data, tier = find_item_data(db_item['item_id'])
            name = item_data['name'] if item_data else db_item['item_id']
            tier = tier or ""

            enh_lvl = db_item.get('enhancement_level') or 0
            enh_str = f"+{enh_lvl}" if enh_lvl > 0 else ""

            # Highlight equipped items
            equipped = ""
            if db_item['id'] in [player.get('equipped_weapon'), player.get('equipped_armor'),
                                 player.get('equipped_accessory')]:
                equipped = " (Equipped)"

            full_name = f"[{tier}] {name}" if tier else name
            if enh_str:
                full_name += f" {enh_str}"

            item_list_str.append(f"{full_name}{equipped}")

        msg = f"@{ctx.chatter.name} Inventory: " + ", ".join(item_list_str)
        if not send_streamerbot_message(msg):
            await ctx.send(msg)

    @commands.command(name='equip', aliases=['eq'])
    async def cmd_equip(self, ctx: commands.Context, *, item_name: str = ""):
        if not item_name:
            await ctx.send(f"@{ctx.chatter.name} Usage: !equip <item name>")
            return

        player = db.get_player(ctx.chatter.name)
        if not player: return

        # Get items via repository
        db_items = db.items.get_items_by_owner(player['id'])

        if not db_items:
            await ctx.send(f"@{ctx.chatter.name} Your inventory is empty.")
            return

        from game.logic import ITEMS

        target_db_id = None
        target_item_id = None
        target_item_name = None

        # Try to match the provided name to an item in their inventory
        search_name = item_name.lower().strip()
        for db_item in db_items:
            i_id = db_item['item_id']
            item_data, _ = find_item_data(i_id)
            i_name = item_data['name'] if item_data else i_id

            # Allow matching by full name or ID (fallback)
            if search_name == i_name.lower() or search_name == str(db_item['id']):
                target_db_id = db_item['id']
                target_item_id = i_id
                target_item_name = i_name
                break

        if not target_db_id:
            await ctx.send(f"@{ctx.chatter.name} You do not own an item named '{item_name}'.")
            return

        slot = None
        for tier_items in ITEMS.get('weapons', {}).values():
            if any(i['id'] == target_item_id for i in tier_items): slot = 'equipped_weapon'
        for tier_items in ITEMS.get('armors', {}).values():
            if any(i['id'] == target_item_id for i in tier_items): slot = 'equipped_armor'
        for tier_items in ITEMS.get('accessories', {}).values():
            if any(i['id'] == target_item_id for i in tier_items): slot = 'equipped_accessory'

        if slot:
            # Check level requirement before equipping
            enh_lvl = 0
            item_row = db.items.get_item_by_db_id(target_db_id)
            if item_row:
                enh_lvl = item_row.get('enhancement_level') or 0

            item_data, item_tier = find_item_data(target_item_id)
            if not item_tier:
                item_tier = 'R'

            req_lvl = get_level_requirement(item_tier, enh_lvl)

            current_lvl = player.get('level', 1)
            if current_lvl < req_lvl:
                await ctx.send(
                    f"@{ctx.chatter.name} ❌ เลเวลไม่ถึง! ไอเทมนี้ต้องการเลเวล {req_lvl} (เลเวลปัจจุบันของคุณคือ {current_lvl})")
                return

            db.update_player(player['id'], {slot: target_db_id})
            await ctx.send(f"@{ctx.chatter.name} Equipped {target_item_name}!")
        else:
            await ctx.send(f"@{ctx.chatter.name} Invalid item type.")

    @commands.command(name='unequip', aliases=['uneq', 'uq'])
    async def cmd_unequip(self, ctx: commands.Context, slot_name: str = ""):
        player = db.get_player(ctx.chatter.name)
        if not player: return

        slot_map = {'weapon': 'equipped_weapon', 'armor': 'equipped_armor', 'accessory': 'equipped_accessory'}
        slot_db = slot_map.get(slot_name.lower())

        if not slot_db:
            await ctx.send(f"@{ctx.chatter.name} Usage: !unequip weapon/armor/accessory")
            return

        if player.get(slot_db) is None:
            await ctx.send(f"@{ctx.chatter.name} You don't have a {slot_name.lower()} equipped.")
            return

        db.update_player(player['id'], {slot_db: None})
        await ctx.send(f"@{ctx.chatter.name} Unequipped {slot_name.lower()}!")

    @commands.command(name='sell')
    async def cmd_sell(self, ctx: commands.Context, *, target: str = ""):
        player = db.get_player(ctx.chatter.name)
        if not player:
            await ctx.send(f"@{ctx.chatter.name} Please !register first.")
            return

        target = target.strip()
        if not target:
            await ctx.send(
                f"@{ctx.chatter.name} วิธีใช้: !sell <ชื่อไอเทม/ID> เพื่อขายทีละชิ้น หรือ !sell R / !sell SR เพื่อขายเหมา")
            return

        target_tier = None
        target_item_name = None

        if target.upper() in ['R', 'SR']:
            target_tier = target.upper()
        else:
            target_item_name = target

        from game.shop import sell_items
        success, msg = sell_items(player['id'], target_item_name=target_item_name, target_tier=target_tier)
        await ctx.send(f"@{ctx.chatter.name} {msg}")

    @commands.command(name='stats', aliases=['stat'])
    async def cmd_stats(self, ctx: commands.Context):
        player = db.get_player(ctx.chatter.name)
        if not player:
            await ctx.send(f"@{ctx.chatter.name} Please !register first.")
            return

        from game.logic import calculate_player_stats, get_required_exp
        import json

        s = calculate_player_stats(player)
        name = player.get('character_name') or player['username']
        cls_name = player.get('class', 'warrior').lower()

        class_levels = player.get('class_levels', {})
        if isinstance(class_levels, str):
            try:
                class_levels = json.loads(class_levels)
            except Exception:
                class_levels = {}

        cls_data = class_levels.get(cls_name, {})
        level = cls_data.get('level', player.get('level', 1))
        exp = cls_data.get('exp', 0)
        req_exp = get_required_exp(level)

        from game.combat import check_cooldown
        alive, cd = check_cooldown(player['id'], 'respawn')

        current_hp = 0 if not alive else player.get('hp', s['max_hp'])
        current_mp = player.get('mp', 0)

        # Check if any equipped item level requirement is not met
        has_inactive_item = False
        eq = db.get_player_equipment(player['id'])
        for s_name, item in eq.items():
            if item:
                item_tier = item.get('tier', 'R')
                enh_lvl = item.get('enhancement_level') or 0
                req_lvl = get_level_requirement(item_tier, enh_lvl)

                if level < req_lvl:
                    has_inactive_item = True
                    break

        msg = f"Stats for {name} ({cls_name.capitalize()} Lv.{level}): {current_hp}/{s['max_hp']} HP | {current_mp}/{s['max_mp']} MP | {exp}/{req_exp} EXP | {s['atk']} ATK | {s['def']} DEF | {int(s['crit_chance'] * 100)}% CRIT"
        if has_inactive_item:
            msg += " ⚠️ (มีไอเทมที่ไม่มีผลเนื่องจากเลเวลไม่ถึง)"
        if not send_streamerbot_message(msg):
            await ctx.send(msg)

    @commands.command(name='info')
    async def cmd_info(self, ctx: commands.Context):
        msg1 = "📜 [เริ่มเล่น] สมัคร !register (!reg) <ชื่อ> | เปลี่ยนอาชีพ !changeclass (!cc) | สถานะ !stats (!st) | ดูของคนอื่น !inspect (!ins)"
        msg2 = "⚔️ [ต่อสู้] โจมตี !attack (!atk) | สกิล !skill (!sk) <สกิล> | ไม้ตาย !ultimate (!ult) | ดูบอส !boss (!bs)"
        msg3 = "🎒 [ไอเทม] กระเป๋า !inventory (!inv) | ใส่ของ !equip (!eq) <ชื่อ> | ถอดของ !unequip (!uq) <slot>"
        msg4 = "💰 [ร้านค้า] เช็คเงิน !gold | ดูร้าน !shop (!shp) | ซื้อ !buy (!b) <ของ> | ขายขยะ !sell (!sel) <ของ/R/SR>"

        for msg in [msg1, msg2, msg3, msg4]:
            if not send_streamerbot_message(msg):
                await ctx.send(msg)

    @commands.command(name='inspect', aliases=['equipment', 'equipments', 'ins'])
    async def cmd_inspect(self, ctx: commands.Context, target_name: str = ""):
        search_name = target_name.strip().replace('@', '') if target_name else ctx.chatter.name

        player = db.get_player(search_name)
        if not player:
            await ctx.send(f"@{ctx.chatter.name} Player '{search_name}' is not registered.")
            return

        eq = db.get_player_equipment(player['id'])

        icon_map = {'warrior': '⚔️', 'mage': '🔮', 'rogue': '🗡️', 'priest': '💖'}
        cls = player.get('class', 'warrior').lower()
        icon = icon_map.get(cls, '⚔️')

        payload = {
            "username": player['username'],
            "character_name": player.get('character_name') or player['username'],
            "class": cls,
            "icon": icon,
            "level": player['level'],
            "equipped_weapon": eq.get('equipped_weapon'),
            "equipped_armor": eq.get('equipped_armor'),
            "equipped_accessory": eq.get('equipped_accessory')
        }

        from utils import emit_to_overlay
        emit_to_overlay('inspect_player', payload)

        def format_item(item):
            if not item: return "None"
            enh = f"+{item['enhancement_level']} " if item['enhancement_level'] > 0 else ""
            return f"{enh}{item['name']}"

        msg = f"🔍 Inspecting {payload['character_name']} ({cls.capitalize()} Lv.{payload['level']}) | Weapon: {format_item(payload['equipped_weapon'])} | Armor: {format_item(payload['equipped_armor'])} | Accessory: {format_item(payload['equipped_accessory'])}"
        if not send_streamerbot_message(msg):
            await ctx.send(msg)

    @commands.command(name='gold', aliases=['money'])
    async def cmd_gold(self, ctx: commands.Context):
        player = db.get_player(ctx.chatter.name)
        if not player:
            await ctx.send(f"@{ctx.chatter.name} Please !register first.")
            return

        t1 = player.get('scroll_t1', 0)
        t2 = player.get('scroll_t2', 0)
        t3 = player.get('scroll_t3', 0)

        msg = f"@{ctx.chatter.name} คุณมี {player.get('gold', 0)} Gold"
        if t1 > 0 or t2 > 0 or t3 > 0:
            msg += f" | ใบกันแตก: [Basic={t1}] [Blessed={t2}] [Divine={t3}]"

        await ctx.send(msg)

    @commands.command(name='shop')
    async def cmd_shop(self, ctx: commands.Context):
        player = db.get_player(ctx.chatter.name)
        lvl = player.get('level', 1) if player else 1

        msg = f"🛒 ร้านค้าสตรีม (Shop) | พิมพ์ !buy <ไอเทม> เพื่อซื้อ:\n" \
              f"1. Potion (500 Gold) - ฟื้นฟู HP/MP ทั้งหมดทันที\n"

        if lvl >= 11:
            msg += f"2. Basic Scroll [พิมพ์ !buy scroll_t1] (10,000 Gold) - กันแตก 75% (ใช้กับของ R, SR เท่านั้น)\n" \
                   f"3. Blessed Scroll [พิมพ์ !buy scroll_t2] (50,000 Gold) - กันแตก 100% / โอกาสติด +10% (ใช้กับของ SSR เท่านั้น)\n" \
                   f"4. Divine Scroll [พิมพ์ !buy scroll_t3] (100,000 Gold) - กันแตก 100% / โอกาสติด +25% (ใช้กับของ UR เท่านั้น)"
        else:
            msg += f"\n*(ไอเทมอื่นๆ จะปลดล็อคเมื่อเลเวล 11 ขึ้นไป)*"

        await ctx.send(msg)

    @commands.command(name='buy')
    async def cmd_buy(self, ctx: commands.Context, item_name: str = ""):
        if not item_name:
            await ctx.send(f"@{ctx.chatter.name} Usage: !buy potion/scroll")
            return

        player = db.get_player(ctx.chatter.name)
        if not player:
            await ctx.send(f"@{ctx.chatter.name} Please !register first.")
            return

        from game.shop import buy_shop_item
        success, msg = buy_shop_item(ctx.chatter.name, item_name)
        if success:
            await ctx.send(f"@{ctx.chatter.name} {msg}")
            if item_name.lower().strip() == 'potion':
                from utils import emit_to_overlay
                from game.combat import get_party_data
                boss = db.get_active_boss()
                if boss and player['id'] in boss.get('participants', []):
                    emit_to_overlay('party_update', get_party_data(boss))
        else:
            await ctx.send(f"@{ctx.chatter.name} ❌ {msg}")

    @commands.command(name='classes', aliases=['class', 'cls'])
    async def cmd_classes(self, ctx: commands.Context):
        msg = "📜 [ข้อมูลอาชีพ] มี 4 อาชีพให้เลือกเล่น:\n" \
              "⚔️ Warrior: เลือดเยอะ ถึกทน มีสกิลยั่วยุ (Taunt) รับดึงดูดบอสให้เพื่อน\n" \
              "🔮 Mage: พลังเวทย์ทำลายล้างแบบหมู่ แรงมาก แต่เปราะบางแพ้ทางกายภาพ\n" \
              "🗡️ Rogue: โจมตีคริติคอลแรง 2 เท่า และแรงขึ้น 3 เท่าถ้าบอสเลือดต่ำกว่า 30%\n" \
              "💖 Priest: สายซัพพอร์ต มีสกิลฟื้นฟูเลือดและชุบชีวิตเพื่อนร่วมทีม"
        if not send_streamerbot_message(msg):
            await ctx.send(msg)

    @commands.command(name='reload')
    async def cmd_reload(self, ctx: commands.Context):
        import os
        author_name = ctx.chatter.name
        is_mod = getattr(ctx.chatter, 'moderator', False) or getattr(ctx.chatter, 'is_mod', False)
        channel_owner = os.environ.get('TWITCH_CHANNEL', '').lower()
        if not is_mod and author_name.lower() != channel_owner:
            await ctx.send(f"@{author_name} ❌ You are not allowed to use this command!")
            return

        try:
            import sys
            import importlib

            # List of modules to reload in dependency order
            modules_to_reload = [
                'utils.utils',
                'utils',
                'game.items',
                'game.helpers',
                'game.logic',
                'game.enhancement',
                'game.boss_manager',
                'game.challenge_manager',
                'game.combat',
                'cogs.combat',
                'cogs.info'
            ]

            # Reload modules in order if they are already imported
            for mod_name in modules_to_reload:
                if mod_name in sys.modules:
                    importlib.reload(sys.modules[mod_name])

            # Import cogs again from fresh reloaded modules
            import cogs.combat
            import cogs.info

            # 1. Native TwitchIO Bot mode reload handling
            if self.bot:
                await self.bot.remove_component("CombatCog")
                await self.bot.remove_component("InfoCog")

                await self.bot.add_component(cogs.combat.CombatCog(self.bot))
                await self.bot.add_component(cogs.info.InfoCog(self.bot))

                # Update globals in bot module
                bot_mod = sys.modules.get('bot')
                if bot_mod:
                    bot_mod.combat_cog = self.bot.get_component("CombatCog")
                    bot_mod.info_cog = self.bot.get_component("InfoCog")
            else:
                # 2. Local WS Server mode reload handling
                bot_mod = sys.modules.get('bot')
                if bot_mod:
                    bot_mod.combat_cog = cogs.combat.CombatCog(None)
                    bot_mod.info_cog = cogs.info.InfoCog(None)

            await ctx.send("🔄 Cogs and game rules successfully reloaded!")
            print("[Bot] Cogs and game rules successfully reloaded!")
        except Exception as e:
            await ctx.send(f"❌ Failed to reload cogs: {e}")
            import traceback
            traceback.print_exc()


async def prepare(bot: commands.Bot):
    await bot.add_component(InfoCog(bot))
