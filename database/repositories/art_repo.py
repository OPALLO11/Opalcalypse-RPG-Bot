"""
Art gallery repository — recording generated art entries.
"""

from datetime import datetime

from .base import BaseRepository


class ArtRepository(BaseRepository):

    def add_art_gallery(self, username, bits_amount, prompt, image_url,
                        is_custom, discord_posted):
        with self._transact() as (conn, c):
            now = datetime.now().isoformat()
            c.execute(
                '''INSERT INTO art_gallery
                   (username, bits_amount, prompt, image_url, is_custom,
                    discord_posted, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (username, bits_amount, prompt, image_url,
                 is_custom, discord_posted, now),
            )
