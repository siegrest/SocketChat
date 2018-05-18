from threading import Thread
from time import sleep
import sqlite3
import socket

"""
Headers:
    'disconnect' - a client disconnected
    'bye' - that client requested a disconnect
    'message' - a text message
    'welcome' - indicating a client it may join
    'connected' - a new client joined
    'couldn't connect' - server full or something, a client couldn't connect
    'full' - indicating a client the server is full
    'exit' - the clients MUST disconnect
"""


MAX_MSG_LENGTH = 2056


class Database:
    def __init__(self, name):
        self.name = name

        self.connection = None
        self.c = None

        self.__connect()

    def __connect(self):
        self.connection = sqlite3.connect(self.name, check_same_thread=False)
        self.c = self.connection.cursor()

        self.__verify_database()

    def close(self):
        self.connection.commit()
        self.connection.close()

    # ======================================================================================================
    # Initial database creation
    # ======================================================================================================

    def __verify_database(self):
        data = self.c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()

        if data is None:
            self.__create_table_users()
            self.__create_table_channels()
        else:
            if ("users",) not in data:
                self.__create_table_users()
            if ("channels",) not in data:
                self.__create_table_channels()
            if ("permissions",) not in data:
                self.__create_table_permissions()

        self.connection.commit()

    def __create_table_users(self):
        asd = "CREATE TABLE users (date TEXT, username TEXT, nick TEXT, password TEXT, rank INT, mute INT, ban INT)"
        self.c.execute(asd)

        data = [
            ("-", "root", "root", "123", 0, 0, 0),
            ("-", "1", "1", "1", 99, 0, 0),
            ("-", "2", "2", "2", 80, 0, 0),
            ("-", "3", "3", "3", 99, 1, 0),
            ("-", "4", "4", "4", 99, 1, 1),
            ("-", "5", "5", "5", 4, 0, 0)
        ]
        self.c.executemany("INSERT INTO users VALUES (?,?,?,?,?,?,?)", data)

    def __create_table_channels(self):
        self.c.execute("CREATE TABLE channels (name TEXT, max INT, rank INT)")

        # Add default channels
        data = [
            ("default", 512, 99),
            ("off-topic", 128, 90),
            ("music", 128, 20),
            ("code club", 64, 20),
            ("admin", 16, 10)
        ]

        self.c.executemany("INSERT INTO channels VALUES (?,?,?)", data)

    def __create_table_permissions(self):
        self.c.execute("CREATE TABLE permissions (rank INT, name TEXT, mute INT, kick INT, ban INT, join_full INT, change_nick INT)")

        # Add default channels
        data = [
            (0, "owner", 1, 1, 1, 1, 1),
            (5, "admin", 1, 1, 1, 1, 1),
            (10, "mod", 1, 1, 0, 1, 1),
            (80, "member", 0, 0, 0, 0, 1),
            (99, "default", 0, 0, 0, 0, 0)
        ]

        self.c.executemany("INSERT INTO permissions VALUES (?,?,?,?,?,?,?)", data)

    # ======================================================================================================
    # Entry checking
    # ======================================================================================================

    def check_username_exists(self, username):
        row = self.c.execute("SELECT * FROM users WHERE username=?", (username,))
        entry = row.fetchone()

        return entry is not None

    def check_channel_exists(self, channel):
        row = self.c.execute("SELECT * FROM channels WHERE name=?", (channel,))
        entry = row.fetchone()

        return entry is not None

    def check_login(self, username, password):
        row = self.c.execute("SELECT * FROM users WHERE username=? AND password=?", (username, password))
        return row.fetchone()

    # ======================================================================================================
    # Entry creation
    # ======================================================================================================

    def create_user(self, username, password):
        if self.check_username_exists(username):
            return False

        try:
            data = ("today", username, username, password, 99, 0, 0)
            self.c.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?)", data)
            self.connection.commit()
        except Exception as ex:
            print(ex)
            return False
        else:
            return True

    def create_channel(self, name, user_limit, rank):
        if self.check_channel_exists(name):
            return False

        try:
            data = (name, user_limit, rank)
            self.c.execute("INSERT INTO users VALUES (?,?,?)", data)
            self.connection.commit()
        except Exception as ex:
            print(ex)
            return False
        else:
            return True

    # ======================================================================================================
    # Entry removal
    # ======================================================================================================

    def remove_channel(self, channel):
        try:
            self.c.execute("DELETE FROM channels WHERE name=?", (channel,))
        except Exception as ex:
            print(ex)
            return False
        else:
            return True

    def remove_user(self, user):
        try:
            self.c.execute("DELETE FROM users WHERE username=?", (user,))
        except Exception as ex:
            print(ex)
            return False
        else:
            return True

    # ======================================================================================================
    # Entry updating
    # ======================================================================================================

    def mute_user(self, username, mute):
        if self.check_username_exists(username):
            return False

        # Whatever value is passed to 'mute', when it's True, it's 1
        mute = 1 if mute else 0

        try:
            self.c.execute("UPDATE users SET mute=? WHERE username =?", (mute, username))
            self.connection.commit()
        except Exception as ex:
            print(ex)
            return False
        else:
            return True

    # ======================================================================================================
    # Entry listing
    # ======================================================================================================

    def list_channels(self):
        rows = self.c.execute("SELECT * FROM channels")
        return rows.fetchall()

    def list_permissions(self):
        rows = self.c.execute("SELECT * FROM permissions")
        return rows.fetchall()


class Channel:
    def __init__(self, data):
        self.name = data[0]
        self.max = int(data[1])
        self.rank = int(data[2])

        self.clients = []

    def to_csv(self):
        return "{0}:{1}:{2}:{3}".format(
            self.name,
            len(self.clients),
            self.max,
            self.rank
        )


class Permission:
    def __init__(self, data):
        self.rank = int(data[0])
        self.name = data[1]

        self.mute = True if data[2] == "1" else False
        self.kick = True if data[3] == "1" else False
        self.ban = True if data[4] == "1" else False
        self.join = True if data[5] == "1" else False
        self.nick = True if data[6] == "1" else False

        self.clients = []


class Client:
    def __init__(self, server, connection, address):
        self.server = server
        self.connection = connection
        self.address = address
        self.client_id = None
        self.thread = None

        self.logged_in = False

        self.channel = None
        self.permission = None

        self.username = None
        self.nick = None
        self.mute = None

    # ======================================================================================================
    # Receive and process messages
    # ======================================================================================================

    def __loop_receive(self):
        self.send_data("!login", "please send login info")

        try:
            while True:
                sleep(0.1)
                data = self.connection.recv(MAX_MSG_LENGTH).decode("utf-8")
                print("[RAW - RECEIVE]", data)
                self.__parse_data(data)
        except ConnectionResetError:
            pass
        finally:
            self.stop()

    def __parse_data(self, data):
        split_data = data.split(" ", 1)
        cmd = split_data[0]
        content = split_data[1] if len(split_data) > 1 else ""

        if not self.logged_in:
            if cmd == "!login":
                self.__login(content)
            elif cmd == "!register":
                self.__register(content)
            return

        if cmd == "!msg":
            self.__form_message(content)
        elif cmd == "!channels":
            self.__cmd_channels()
        elif cmd == "!mute":
            self.__cmd_mute(content)

    def __form_message(self, msg):
        if self.mute:
            self.send_data("!mute", "you are muted")
            return

        print("[MSG][{}] {} ({}:{}): '{}'".format(
            self.permission.name,
            self.username,
            self.address[0],
            self.address[1],
            msg
        ))

        formatted_msg = "[{}][{}] {}: {}".format(self.channel.name, self.permission.name, self.username, msg)

        self.server.send_msg_from_client_to_all_in_channel(self, formatted_msg)

    def __login(self, content):
        try:
            username = content.split(" ")[0]
            password = content.split(" ")[1]
        except IndexError:
            self.send_data("!error", "invalid info provided")
            self.logged_in = False
            return

        user_data = self.server.database.check_login(username, password)

        if user_data is None:
            self.send_data("!error", "invalid username or password")
            self.logged_in = False
            return
        elif user_data[6] is 1:
            self.send_data("!error", "you are banned")
            self.logged_in = False
            return

        self.send_data("!success", "logged in successfully")
        self.logged_in = True

        self.username = user_data[1]
        self.nick = user_data[2]
        self.rank = user_data[4]
        self.mute = user_data[5]

        self.__join_default_channel()
        self.__load_permissions()

        print("[LOGIN] '{0}' just logged in as client {1} from '{2}:{3}'".format(
            self.username,
            self.client_id,
            self.address[0],
            self.address[1]
        ))

    def __register(self, content):
        try:
            username = content.split(" ")[0]
            password = content.split(" ")[1]
        except IndexError:
            self.send_data("!error", "invalid info provided")
            return

        if not self.server.database.create_user(username, password):
            self.send_data("!error", "username already in use")
            return

        self.send_data("!success", "account created and logged in")
        self.logged_in = True

        self.__join_default_channel()
        self.__load_permissions()

        self.username = username
        self.nick = username
        self.rank = 99
        self.mute = 0

    def __join_default_channel(self):
        self.channel = self.server.channels["default"]
        self.channel.clients.append(self)

    def __load_permissions(self):
        for rank, permission in self.server.permissions.items():
            if self.rank <= int(rank):
                self.permission = permission
                break

        self.permission.clients.append(self)

    # ======================================================================================================
    # Commands
    # ======================================================================================================

    def __cmd_channels(self):
        reply = ""

        for name, channel in self.server.channels.items():
            if channel.rank >= self.rank:
                reply += channel.to_csv() + ","

        if reply.endswith(","):
            reply = reply[:len(reply) - 1]

        self.send_data("!channels", reply)

    def __cmd_mute(self, content):
        if not self.permission.mute:
            return False

        for client in self.server.clients:
            if content != client.username:
                return False
            elif client.rank >= self.rank:
                return False

            client.mute = not client.mute
            self.server.database.mute_user(content, client.mute)

            print("[MUTE] {} {} {}".format(
                self.username,
                "muted" if client.mute else "unmuted",
                client.username
            ))

            return True

    # ======================================================================================================
    # Send data
    # ======================================================================================================

    def send_data(self, cmd, content):
        payload = cmd + " " + content

        print("[RAW - SEND]", payload)

        try:
            self.connection.send(payload.encode("utf-8"))
        except ConnectionResetError:
            pass

    # ======================================================================================================
    # Control functions
    # ======================================================================================================

    def run(self, client_id):
        self.client_id = client_id

        self.thread = Thread(
            target=self.__loop_receive,
            name="client-" + str(self.client_id),
            daemon=True
        )

        self.thread.start()

    def stop(self):
        print("[DISCONNECT] '{}' disconnected from '{}:{}'".format(
            self.username,
            self.address[0],
            self.address[1]
        ))

        if self.connection:
            self.connection.close()

        self.server.clients.remove(self)
        self.channel.clients.remove(self)
        self.permission.clients.remove(self)


class Server:
    def __init__(self, database, ip, port, max_clients):
        self.ip = ip
        self.port = port
        self.max_clients = max_clients
        self.clients = []
        self.channels = {}
        self.permissions = {}

        self.database = database
        self.connection = None

    # ======================================================================================================
    # Receive and process clients
    # ======================================================================================================

    def __loop_receive(self):
        while True:
            sleep(0.1)
            connection, address = self.connection.accept()
            client = Client(self, connection, address)

            self.clients.append(client)
            client_id = self.clients.index(client)
            client.run(client_id)

    # ======================================================================================================
    # Send data
    # ======================================================================================================

    def send_data_to_all(self, sender, cmd, content):
        for client in self.clients:
            if client != sender and client.channel == sender.channel:
                client.send_data(cmd, content)

    def send_msg_from_client_to_all_in_channel(self, sender, content):
        for client in self.channels[sender.channel.name].clients:
            if client != sender:
                client.send_data("!msg", content)

    # ======================================================================================================
    # Load data from database on program start
    # ======================================================================================================

    def __load_channels(self):
        print("Loaded channels:")
        print("|   {:>12} | {:>5} | {:>4} |".format(
            "name", "slots", "rank"
        ))

        for data in self.database.list_channels():
            print("|   {:>12} | {:>5} | {:>4} |".format(
                data[0], data[1], data[2]
            ))
            self.channels[data[0]] = Channel(data)

        print()

    def __load_permissions(self):
        print("Loaded permissions:")
        print("|   {:>4} | {:>12} | {:>4} | {:>4} | {:>3} | {:>9} | {:>11} |".format(
            "rank", "name", "mute", "kick", "ban", "join full", "change nick"
        ))

        for data in self.database.list_permissions():
            print("|   {:>4} | {:>12} | {:>4} | {:>4} | {:>3} | {:>9} | {:>11} |".format(
                data[0], data[1], data[2], data[3], data[4], data[5], data[6]
            ))

            self.permissions[data[0]] = Permission(data)

        print()

    # ======================================================================================================
    # Control functions
    # ======================================================================================================

    def run(self):
        self.__load_channels()
        self.__load_permissions()

        print("Starting server on '{0}:{1}'".format(self.ip, self.port))

        self.connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connection.bind((self.ip, self.port))

        # Specifying max connections here doesn't really seem to work for some reason
        self.connection.listen(self.max_clients)

        print("Awaiting connections ({} max)...".format(self.max_clients))

        self.__loop_receive()

    def stop(self):
        for client in self.clients:
            client.stop()
        self.connection.close()


def init():
    database = Database("test.db")
    server = Server(database, "localhost", 8888, 5)

    try:
        server.run()
    finally:
        server.stop()
        database.close()


if __name__ == "__main__":
    init()
