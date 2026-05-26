import asyncio
from twitchio.ext import commands
import inspect

print(inspect.signature(commands.Bot.__init__))
