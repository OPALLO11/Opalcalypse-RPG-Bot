from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, JSON
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Player(Base):
    __tablename__ = 'players'

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, unique=True, nullable=False, index=True)
    twitch_id = Column(String)
    character_name = Column(String, index=True)
    class_name = Column('class', String, default='warrior')
    
    level = Column(Integer, default=1)
    exp = Column(Integer, default=0)
    hp = Column(Integer, default=1000)
    max_hp = Column(Integer, default=1000)
    mp = Column(Integer, default=50)
    max_mp = Column(Integer, default=50)
    atk = Column(Integer, default=100)
    def_stat = Column('def', Integer, default=30)
    
    equipped_weapon = Column(Integer, ForeignKey('items.id'))
    equipped_armor = Column(Integer, ForeignKey('items.id'))
    equipped_accessory = Column(Integer, ForeignKey('items.id'))
    
    total_damage = Column(Integer, default=0)
    bosses_defeated = Column(Integer, default=0)
    mvp_count = Column(Integer, default=0)
    session_renamed = Column(Boolean, default=False)
    session_class_changed = Column(Boolean, default=False)
    gold = Column(Integer, default=0)
    
    scroll_t1 = Column(Integer, default=0)
    scroll_t2 = Column(Integer, default=0)
    scroll_t3 = Column(Integer, default=0)
    created_at = Column(String, default=lambda: datetime.utcnow().isoformat())

    items = relationship('Item', back_populates='owner', foreign_keys='Item.owner_id')
    class_levels_data = relationship('PlayerClassLevel', back_populates='player', cascade='all, delete-orphan')


class PlayerClassLevel(Base):
    __tablename__ = 'player_class_levels'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    player_id = Column(Integer, ForeignKey('players.id'), nullable=False, index=True)
    class_name = Column(String, nullable=False)
    level = Column(Integer, default=1)
    exp = Column(Integer, default=0)

    player = relationship('Player', back_populates='class_levels_data')


class Item(Base):
    __tablename__ = 'items'

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, ForeignKey('players.id'), index=True)
    item_id = Column(String, nullable=False)
    obtained_from = Column(String)
    obtained_at = Column(String, default=lambda: datetime.utcnow().isoformat())
    enhancement_level = Column(Integer, default=0)

    owner = relationship('Player', back_populates='items', foreign_keys=[owner_id])


class Boss(Base):
    __tablename__ = 'bosses'
    
    instance_id = Column(Integer, primary_key=True, autoincrement=True)
    boss_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    type = Column(String)
    element = Column(String)
    base_hp = Column(Integer)
    base_def = Column(Integer, default=0)
    current_hp = Column(Integer)
    max_hp = Column(Integer)
    
    weakness = Column(JSON, default=list)
    resist = Column(JSON, default=list)
    
    image_url = Column(String)
    spawned_at = Column(String, default=lambda: datetime.utcnow().isoformat())
    status = Column(String, default='active')
    defeated_at = Column(String, nullable=True)

    participants = relationship('BossParticipant', back_populates='boss', cascade='all, delete-orphan')


class BossParticipant(Base):
    __tablename__ = 'boss_participants'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    boss_instance_id = Column(Integer, ForeignKey('bosses.instance_id'), nullable=False, index=True)
    player_id = Column(Integer, ForeignKey('players.id'), nullable=False, index=True)

    boss = relationship('Boss', back_populates='participants')
    player = relationship('Player')


class CombatLog(Base):
    __tablename__ = 'combat_log'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    boss_instance_id = Column(Integer, ForeignKey('bosses.instance_id'), index=True)
    player_id = Column(Integer, ForeignKey('players.id'), index=True)
    action = Column(String)
    damage = Column(Integer, default=0)
    is_crit = Column(Boolean, default=False)
    timestamp = Column(String, default=lambda: datetime.utcnow().isoformat())


class ArtGallery(Base):
    __tablename__ = 'art_gallery'

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String)
    bits_amount = Column(Integer)
    prompt = Column(String)
    image_url = Column(String)
    is_custom = Column(Boolean, default=False)
    discord_posted = Column(Boolean, default=False)
    created_at = Column(String, default=lambda: datetime.utcnow().isoformat())


class StreamChallenge(Base):
    __tablename__ = 'stream_challenges'

    id = Column(Integer, primary_key=True, autoincrement=True)
    challenge_type = Column(String)
    description = Column(String)
    target_value = Column(Integer)
    current_value = Column(Integer, default=0)
    reward_type = Column(String)
    reward_amount = Column(Integer)
    status = Column(String, default='active')
    created_at = Column(String, default=lambda: datetime.utcnow().isoformat())
