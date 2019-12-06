import socket
import select
import time
import sys

class _Client(object):

    def __init__(self, socket, address, buffer, lastcheck):
        self.socket = socket
        self.address = address
        self.buffer = buffer
        self.lastcheck = lastcheck

class GameServer(object):
    # Different event outcomes
    _EVENT_NEW_CONNECTION = 1
    _EVENT_CONNECTION_CLOSED = 2
    _EVENT_COMMAND_ENTERED = 3

    # Different states we can be in while reading data from client
    # See _process_sent_data function
    _READ_STATE_NORMAL = 1
    _READ_STATE_COMMAND = 2
    _READ_STATE_SUBNEG = 3

    # Command codes used by telnet client protocol
    # See _process_sent_data function
    _TN_INTERPRET_AS_COMMAND = 255
    _TN_ARE_YOU_THERE = 246
    _TN_WILL = 251
    _TN_WONT = 252
    _TN_DO = 253
    _TN_DONT = 254
    _TN_SUBNEGOTIATION_START = 250
    _TN_SUBNEGOTIATION_END = 240

    # Socket to listen for client connections on
    # Dictionary of connected clients to map to _Client class
    _clients = {}
    # Player id counter
    _nextid = 0
    # List of occurences events waiting to be processed by
    # server
    _events = []
    # List of newly-added events
    _new_events = []
    def __init__(self):
        self._clients = {}
        self._nextid = 0
        self._events = []
        self._new_events = []

        self._listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        self._listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        self._listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listen_socket.setblocking(0)
        self._listen_socket.bind(('127.0.0.1', 1234))
        self._listen_socket.listen(1)

    def update(self):

        # Check for new stuff
        self._check_for_new_connections()
        self._check_for_disconnected()
        self._check_for_messages()

        # Move the new events into the main events list so that they can be
        # obtained with 'get_new_players', 'get_disconnected_players' and
        # 'get_commands'. The previous events are discarded
        self._events = list(self._new_events)
        self._new_events = []

    def _check_for_new_connections(self):

        # 'select' is used to check whether there is data waiting to be read
        # from the socket. We pass in 3 lists of sockets, the first being those
        # to check for readability. It returns 3 lists, the first being
        # the sockets that are readable. The last parameter is how long to wait
        # - we pass in 0 so that it returns immediately without waiting
        rlist, wlist, xlist = select.select([self._listen_socket], [], [], 0)
        if self._listen_socket not in rlist:
            return
        # If all goes well
        joined_socket, addr = self._listen_socket.accept()
        # Do we need this?
        joined_socket.setblocking(0)
        # Build new _Client object to hold info on new connection,
        # then pass the event, and update the id list
        self._clients[self._nextid] = _Client(joined_socket, addr[0],
                                                        "", time.time())
        self._new_events.append((self._EVENT_NEW_CONNECTION, self._nextid))
        self._nextid += 1
    def get_new_players(self):

        retval = []
        # Go through all the events in the main list
        for ev in self._events:
            if ev[0] == self._EVENT_NEW_CONNECTION:
                retval.append(ev[1])
        # Return the info list
        return retval

    # Returns a list of disconections since last update
    def get_disconnected_players(self):

        retval = []
        # Go through all the events in the main list
        for ev in self._events:
            # If the event is a player disconnect occurence, add the info to
            # the list
            if ev[0] == self._EVENT_CONNECTION_CLOSED:
                retval.append(ev[1])
        # Return the info list
        return retval

    # Returns a list of new commands since last update
    def get_commands(self):

        retval = []
        # Go through all the events in the main list
        for ev in self._events:
            # If the event is a command occurence, add the info to the list
            if ev[0] == self._EVENT_COMMAND_ENTERED:
                retval.append((ev[1], ev[2], ev[3]))
        # Return the info list
        return retval

    # Output from Server to Player
    def send_message(self, to, message):

        self._attempt_send(to, message+"\n\r")

    # Shutdown Game server
    def shutdown(self):

        # For each client
        for cl in self._clients.values():
            # Close the socket, disconnecting the client
            cl.socket.shutdown()
            cl.socket.close()
        # Stop listening for new clients
        self._listen_socket.close()

    # Handles output to Clients
    def _attempt_send(self, clid, data):

        # Python 2 / 3 fix
        if sys.version < '3' and type(data) != unicode:
            data = unicode(data, "latin1")
        try:
            # Make sure all data is sent in one shot
            self._clients[clid].socket.sendall(bytearray(data, "latin1"))

        # KeyError will be raised if there is no client with the given id in
        # the map
        except KeyError:
            pass
        # If there is a connection problem with the client
        # a socket error will be raised
        except socket.error:
            self._handle_disconnect(clid)

    # Next few sections handle connections, disconnections, and commands to server_side



    def _check_for_disconnected(self):

        # Check all Clients
        for id, cl in list(self._clients.items()):
            # Skip if check was in last 5 seconds
            if time.time() - cl.lastcheck < 5.0:
                continue
            # Send blank output to client to test connections,
            # and update the last check time
            self._attempt_send(id, "\x00")
            cl.lastcheck = time.time()

    def _check_for_messages(self):

        # Check all Clients
        for id, cl in list(self._clients.items()):
            rlist, wlist, xlist = select.select([cl.socket], [], [], 0)
            if cl.socket not in rlist:
                continue
            try:
                # Read data from socket, process the data,
                data = cl.socket.recv(4096).decode("latin1")
                message = self._process_sent_data(cl, data)
                if message:
                    # Strip tabs n spaces, seperates into command and parameters,
                    # and pass the event
                    message = message.strip()
                    command, params = (message.split(" ", 1) + ["", ""])[:2]
                    self._new_events.append((self._EVENT_COMMAND_ENTERED, id,
                                             command.lower(), params))
            # Handle socket errors as a disconnect
            except socket.error:
                self._handle_disconnect(id)

    def _handle_disconnect(self, clid):

        # remove the client from the clients map, and send event
        del(self._clients[clid])
        self._new_events.append((self._EVENT_CONNECTION_CLOSED, clid))

    def _process_sent_data(self, client, data):

        # the Telnet protocol allows special command codes to be inserted into
        # messages. For our very simple server we don't need to response to
        # any of these codes, but we must at least detect and skip over them
        # so that we don't interpret them as text data.
        # More info on the Telnet protocol can be found here:
        # http://pcmicro.com/netfoss/telnet.html

        # start with no message and in the normal state
        message = None
        state = self._READ_STATE_NORMAL

        # go through the data a character at a time
        for c in data:

            # handle the character differently depending on the state we're in:

            # normal state
            if state == self._READ_STATE_NORMAL:

                # if we received the special 'interpret as command' code,
                # switch to 'command' state so that we handle the next
                # character as a command code and not as regular text data
                if ord(c) == self._TN_INTERPRET_AS_COMMAND:
                    state = self._READ_STATE_COMMAND

                # if we get a newline character, this is the end of the
                # message. Set 'message' to the contents of the buffer and
                # clear the buffer
                elif c == "\n":
                    message = client.buffer
                    client.buffer = ""

                # some telnet clients send the characters as soon as the user
                # types them. So if we get a backspace character, this is where
                # the user has deleted a character and we should delete the
                # last character from the buffer.
                elif c == "\x08":
                    client.buffer = client.buffer[:-1]

                # otherwise it's just a regular character - add it to the
                # buffer where we're building up the received message
                else:
                    client.buffer += c

            # command state
            elif state == self._READ_STATE_COMMAND:

                # the special 'start of subnegotiation' command code indicates
                # that the following characters are a list of options until
                # we're told otherwise. We switch into 'subnegotiation' state
                # to handle this
                if ord(c) == self._TN_SUBNEGOTIATION_START:
                    state = self._READ_STATE_SUBNEG

                # if the command code is one of the 'will', 'wont', 'do' or
                # 'dont' commands, the following character will be an option
                # code so we must remain in the 'command' state
                elif ord(c) in (self._TN_WILL, self._TN_WONT, self._TN_DO,
                                self._TN_DONT):
                    state = self._READ_STATE_COMMAND

                # for all other command codes, there is no accompanying data so
                # we can return to 'normal' state.
                else:
                    state = self._READ_STATE_NORMAL

            # subnegotiation state
            elif state == self._READ_STATE_SUBNEG:

                # if we reach an 'end of subnegotiation' command, this ends the
                # list of options and we can return to 'normal' state.
                # Otherwise we must remain in this state
                if ord(c) == self._TN_SUBNEGOTIATION_END:
                    state = self._READ_STATE_NORMAL

        # return the contents of 'message' which is either a string or None
        return message
