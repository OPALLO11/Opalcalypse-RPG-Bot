from datetime import datetime

from .base import BaseRepository
from ..models import StreamChallenge


def row_to_dict(obj):
    if obj is None:
        return None
    d = {**obj.__dict__}
    d.pop('_sa_instance_state', None)
    if 'class_name' in d:
        d['class'] = d.pop('class_name')
    if 'def_stat' in d:
        d['def'] = d.pop('def_stat')
    return d


class ChallengeRepository(BaseRepository):

    def get_active_challenge(self):
        with self._read_only() as session:
            chal = session.query(StreamChallenge).filter_by(status='active').order_by(StreamChallenge.id.desc()).first()
            return row_to_dict(chal)

    def create_challenge(self, challenge_type, description, target_val,
                         reward_type, reward_amt):
        with self._transact() as session:
            session.query(StreamChallenge).filter_by(status='active').update({'status': 'expired'})
            now = datetime.utcnow().isoformat()
            new_chal = StreamChallenge(
                challenge_type=challenge_type,
                description=description,
                target_value=target_val,
                current_value=0,
                reward_type=reward_type,
                reward_amount=reward_amt,
                status='active',
                created_at=now
            )
            session.add(new_chal)
            session.flush()
            return new_chal.id

    def update_challenge_progress(self, challenge_id, amount):
        with self._transact() as session:
            chal = session.query(StreamChallenge).filter_by(id=challenge_id).first()
            if not chal or chal.status != 'active':
                return None

            new_value = chal.current_value + amount
            status = 'active'
            if new_value >= chal.target_value:
                new_value = chal.target_value
                status = 'completed'

            chal.current_value = new_value
            chal.status = status
            session.flush()

            return row_to_dict(chal)
