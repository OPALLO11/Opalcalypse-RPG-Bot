from datetime import datetime

from .base import BaseRepository
from ..models import ArtGallery


class ArtRepository(BaseRepository):

    def add_art_gallery(self, username, bits_amount, prompt, image_url,
                        is_custom, discord_posted):
        with self._transact() as session:
            now = datetime.utcnow().isoformat()
            art = ArtGallery(
                username=username,
                bits_amount=bits_amount,
                prompt=prompt,
                image_url=image_url,
                is_custom=is_custom,
                discord_posted=discord_posted,
                created_at=now
            )
            session.add(art)
