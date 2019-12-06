import datetime
import time
import json
import sys
import inspect
##used random for item numbers
import random
# import the MUD server class

from server import GameServer

server = GameServer()

while True:
    time.sleep(0.2)
    server.update()
    for id in server.get_new_players():
        server.send_message(id, "Congrats it connected")
