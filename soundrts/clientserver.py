import sys
import threading
import time

from . import config
from . import msgparts as mp
from . import options, servermain
from .batteries import telnetlib
from .clientmedia import voice
from .clientservermenu import ServerMenu
from .clientversion import revision_checker
from .lib.log import exception, info
from .version import compatibility_version


class _Error(Exception):
    pass


class UnreachableServerError(_Error):
    pass


class WrongServerError(_Error):
    pass


class CompatibilityOrLoginError(_Error):
    pass


class ConnectionAbortedError(_Error):
    pass


def server_delay(host, port):
    t = time.time()
    try:
        with telnetlib.Telnet(host, port, 0.5) as tn:
            try:
                if tn.read_until(b":", 0.5) != b":":
                    return
                else:
                    return time.time() - t
            except EOFError:
                return
    except OSError:
        return


class ServerInAThread(threading.Thread):

    daemon = True

    def __init__(self, parameters):
        threading.Thread.__init__(self)
        self.parameters = parameters

    def run(self):
        servermain.start_server(self.parameters, is_standalone=False)


def start_server_and_connect(parameters):
    info("active threads: %s", threading.enumerate())
    ServerInAThread(parameters).start()
    servermain.server_ready.wait(10)
    revision_checker.start_if_needed()
    connect_and_play()
    info("active threads: %s", threading.enumerate())
    sys.exit()


def connect_and_play(host="127.0.0.1", port=options.port, auto=False):
    try:
        server = ConnectionToServer(host, port)
        ServerMenu(server, auto=auto).loop()
        server.close()  # without this, the server isn't closed after a game
    except UnreachableServerError:
        voice.alert(mp.SERVER_UNREACHABLE)
    except WrongServerError:
        voice.alert(mp.UNEXPECTED_REPLY)
    except CompatibilityOrLoginError:
        voice.alert(mp.CONNECTION_REJECTED + mp.OR_LOGIN_REJECTED)
    except ConnectionAbortedError:
        voice.alert(mp.CONNECTION_INTERRUPTED)
    except SystemExit:
        raise
    except:
        voice.alert(mp.ERROR_DURING_CONNECTION)
        exception("error during connection to server")


class ConnectionToServer:

    data = b""
    tn = None

    def __init__(self, host, port):
        self.host = host
        self.port = port
        if host is not None:
            self.open()

    def open(self):
        try:
            self.tn = telnetlib.Telnet(self.host, self.port, 1)
        except OSError:
            raise UnreachableServerError
        try:
            if self.tn.read_until(b":", 1) != b":":
                raise WrongServerError
            self.tn.write(
                ("login " + compatibility_version() + " %s\n" % config.login).encode()
            )
        except (EOFError, OSError):
            raise WrongServerError
        try:
            if not self.tn.read_until(b"ok!", 1).endswith(b"ok!"):
                raise EOFError
        except EOFError:
            raise CompatibilityOrLoginError

    def close(self):
        self.tn.close()

    def read_line(self):
        try:
            self.data += self.tn.read_very_eager()
        except:  # EOFError or (10054, 'Connection reset by peer')
            raise ConnectionAbortedError
        if b"\n" in self.data:
            line, self.data = self.data.split(b"\n", 1)
            return line.decode("ascii")

    def write_line(self, s):
        try:
            self.tn.write(s.encode("ascii") + b"\n")
        except OSError:  # connection aborted
            raise ConnectionAbortedError
