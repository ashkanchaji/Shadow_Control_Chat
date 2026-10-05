import socket
import threading
import struct
import os

# Server Configuration
HOST = '0.0.0.0'
PORT = 8888
BASE_DIR = 'server_files'
MAX_FILE_SIZE = 10 * 1024 * 1024 # 10 MB

# Data structures
users = {} # username -> password
online_users = {} # username -> socket
client_states = {} # socket -> username
offline_messages = {} # username -> list of str messages
chat_history = [] # list of all chats

def server_log(level, msg):
    print(f"[{level}] {msg}")

# Ensure base directory exists
if not os.path.exists(BASE_DIR):
    os.makedirs(BASE_DIR)

def send_msg(sock, msg):
    """ Prefix each message with a 4-byte length in network byte order """
    if isinstance(msg, str):
        msg = msg.encode('utf-8')
    msg = struct.pack('!I', len(msg)) + msg
    try:
        sock.sendall(msg)
    except:
        pass

def recvall(sock, n):
    """ Helper function to recv n bytes or return None if EOF is hit """
    data = bytearray()
    while len(data) < n:
        try:
            packet = sock.recv(n - len(data))
            if not packet:
                return None
            data.extend(packet)
        except:
            return None
    return bytes(data)

def recv_msg(sock):
    """ Read message length and unpack it into an integer """
    raw_msglen = recvall(sock, 4)
    if not raw_msglen:
        return None
    msglen = struct.unpack('!I', raw_msglen)[0]
    return recvall(sock, msglen)

def get_user_by_socket(sock):
    return client_states.get(sock, None)

def handle_client(conn, addr):
    server_log("INFO", f"New connection from {addr}")
    
    # Per-connection state
    uploading_files = {} # filename -> file handle

    try:
        while True:
            msgBytes = recv_msg(conn)
            if not msgBytes:
                break
                
            # Try to decode the header to see what kind of message it is
            # Since chunks contain binary bytes, we split carefully.
            # We can split by | but limit to max splits for chunks.
            
            # The format is TYPE|COMMAND|ARGS...
            # For FILE_CHUNK, it's DATA|FILE_CHUNK|filename|chunk_index|chunk_size|bytes
            parts = msgBytes.split(b'|', 5) # Split up to 5 times for chunks
            
            if not parts:
                continue
                
            msg_type = parts[0].decode('utf-8', errors='ignore')
            cmd = parts[1].decode('utf-8', errors='ignore') if len(parts) > 1 else ""

            username = get_user_by_socket(conn)

            if msg_type == 'CTRL':
                args = [p.decode('utf-8', errors='ignore') for p in parts[2:]]
                
                if cmd == 'REGISTER':
                    if len(args) == 2:
                        u, p = args[0], args[1]
                        if u in users:
                            send_msg(conn, "CTRL|ERROR|username already exists")
                        else:
                            users[u] = p
                            user_dir = os.path.join(BASE_DIR, u)
                            if not os.path.exists(user_dir):
                                os.makedirs(user_dir)
                            send_msg(conn, "CTRL|OK")
                            server_log("INFO", f"user {u} registered")
                    else:
                        send_msg(conn, "CTRL|ERROR|invalid arguments")
                        
                elif cmd == 'LOGIN':
                    if len(args) == 2:
                        u, p = args[0], args[1]
                        if u not in users or users[u] != p:
                            send_msg(conn, "CTRL|AUTH_FAILED")
                        elif u in online_users:
                            send_msg(conn, "CTRL|ERROR|user already logged in")
                        else:
                            online_users[u] = conn
                            client_states[conn] = u
                            current_user = u
                            send_msg(conn, "CTRL|AUTH_SUCCESS")
                            server_log("INFO", f"user {u} logged in")
                            
                            # Send offline messages
                            if u in offline_messages and offline_messages[u]:
                                for sender, off_msg in offline_messages[u]:
                                    send_msg(conn, f"DATA|CHAT_FROM|{sender}|{off_msg}")
                                    server_log("INFO", f"Delivered offline message from {sender} to {u}")
                                offline_messages[u] = []
                    else:
                        send_msg(conn, "CTRL|ERROR|invalid arguments")
                        
                elif cmd == 'LOGOUT':
                    if username:
                        server_log("INFO", f"user {username} logged out")
                        del online_users[username]
                        del client_states[conn]
                        send_msg(conn, "CTRL|OK")
                    else:
                        send_msg(conn, "CTRL|ERROR|authentication required")
                        
                elif cmd == 'UPLOAD':
                    # UPLOAD <filename> <filesize>
                    if not username:
                        send_msg(conn, "CTRL|ERROR|authentication required")
                        continue
                    if len(args) >= 2:
                        filename = args[0]
                        filesize = int(args[1]) if args[1].isdigit() else 0
                        if filesize > MAX_FILE_SIZE:
                            send_msg(conn, f"CTRL|ERROR|file size exceeds limit of {MAX_FILE_SIZE/(1024*1024)}MB")
                            continue
                        try:
                            # Start upload session
                            f_path = os.path.join(BASE_DIR, username, filename)
                            file_handle = open(f_path, 'wb')
                            uploading_files[filename] = file_handle
                            send_msg(conn, f"CTRL|UPLOAD_ACK|{filename}")
                            server_log("INFO", f"user {username} started uploading file {filename} ({filesize} bytes)")
                        except Exception as e:
                            send_msg(conn, f"CTRL|ERROR|{str(e)}")
                    else:
                        send_msg(conn, "CTRL|ERROR|invalid filename or filesize")
                        
                elif cmd == 'LIST_FILES':
                    if not username:
                        send_msg(conn, "CTRL|ERROR|authentication required")
                        continue
                    user_dir = os.path.join(BASE_DIR, username)
                    if os.path.exists(user_dir):
                        files = os.listdir(user_dir)
                    else:
                        files = []
                    
                    if files:
                        send_msg(conn, f"CTRL|FILE_LIST|{','.join(files)}")
                    else:
                        send_msg(conn, "CTRL|FILE_LIST|empty")
                        
                elif cmd == 'LIST_USERS':
                    if not username:
                        send_msg(conn, "CTRL|ERROR|authentication required")
                        continue
                    users_list = [u for u in online_users.keys()]
                    send_msg(conn, f"CTRL|USER_LIST|{','.join(users_list)}")
                        
                elif cmd == 'SHARE':
                    # SHARE <filename> <target_user>
                    if not username:
                        send_msg(conn, "CTRL|ERROR|authentication required")
                        continue
                    if len(args) == 2:
                        filename, target = args[0], args[1]
                        # Check file exists
                        f_path = os.path.join(BASE_DIR, username, filename)
                        if not os.path.exists(f_path):
                            send_msg(conn, "CTRL|ERROR|file not found")
                        elif target not in users:
                            send_msg(conn, "CTRL|ERROR|target user not found")
                        elif target not in online_users:
                            send_msg(conn, "CTRL|ERROR|target user is offline")
                            server_log("ERROR", f"target user {target} is offline for share from {username}")
                        else:
                            # Send share request to target
                            target_sock = online_users[target]
                            send_msg(target_sock, f"CTRL|SHARE_REQUEST|{username}|{filename}")
                            send_msg(conn, "CTRL|OK")
                            server_log("INFO", f"user {username} sent a share request for {filename} to {target}")
                    else:
                        send_msg(conn, "CTRL|ERROR|invalid arguments")
                        
                elif cmd == 'ACCEPT_FILE':
                    # ACCEPT_FILE <filename> <sender>
                    if not username:
                        send_msg(conn, "CTRL|ERROR|authentication required")
                        continue
                    if len(args) == 2:
                        filename, sender = args[0], args[1]
                        # Start sending file to this user
                        threading.Thread(target=send_file_chunks, args=(conn, username, sender, filename)).start()
                        send_msg(conn, f"CTRL|SHARE_ACCEPTED|{filename}")
                        server_log("INFO", f"user {username} accepted file {filename} from {sender}")
                        if sender in online_users:
                            send_msg(online_users[sender], f"CTRL|INFO|User {username} accepted {filename}")
                    else:
                        send_msg(conn, "CTRL|ERROR|invalid arguments")

                elif cmd == 'REJECT_FILE':
                    # REJECT_FILE <filename> <sender>
                    if not username:
                        send_msg(conn, "CTRL|ERROR|authentication required")
                        continue
                    if len(args) == 2:
                        filename, sender = args[0], args[1]
                        send_msg(conn, f"CTRL|SHARE_REJECTED|{filename} rejected")
                        server_log("INFO", f"user {username} rejected file {filename} from {sender}")
                        if sender in online_users:
                            send_msg(online_users[sender], f"CTRL|INFO|User {username} rejected {filename}")
                    else:
                        send_msg(conn, "CTRL|ERROR|invalid arguments")

                elif cmd == 'EXIT':
                    if username:
                        server_log("INFO", f"user {username} disconnected")
                        del online_users[username]
                        del client_states[conn]
                    send_msg(conn, "CTRL|OK")
                    break

                else:
                    send_msg(conn, "CTRL|ERROR|unknown command")
            
            elif msg_type == 'DATA':
                if not username:
                    send_msg(conn, "CTRL|ERROR|authentication required")
                    continue
                    
                if cmd == 'CHAT':
                    # DATA|CHAT|target_user|message ... can contain arbitrary | because it's text
                    # Safer decoding for chat messages
                    target_msgText = msgBytes.split(b'|', 3)
                    if len(target_msgText) >= 4:
                        target = target_msgText[2].decode('utf-8', errors='ignore')
                        message = target_msgText[3].decode('utf-8', errors='ignore')
                        
                        if target not in users:
                            send_msg(conn, "CTRL|ERROR|target user not found")
                            server_log("ERROR", f"target user {target} not found for chat from {username}")
                        elif target not in online_users:
                            # Send offline
                            server_log("INFO", f"Saved offline message from {username} to {target}")
                            if target not in offline_messages:
                                offline_messages[target] = []
                            offline_messages[target].append((username, message))
                            send_msg(conn, "CTRL|OK|Message saved for when user comes online")
                        else:
                            target_sock = online_users[target]
                            send_msg(target_sock, f"DATA|CHAT_FROM|{username}|{message}")
                            
                        # Save chat history
                        chat_history.append(f"{username} -> {target}: {message}")
                        with open(os.path.join(BASE_DIR, "chat_history.txt"), "a", encoding="utf-8") as f:
                            f.write(f"{username} -> {target}: {message}\n")
                    else:
                        send_msg(conn, "CTRL|ERROR|invalid chat format")
                        
                elif cmd == 'FILE_CHUNK':
                    # DATA|FILE_CHUNK|filename|chunk_index|chunk_size|bytes
                    if len(parts) >= 6:
                        filename = parts[2].decode('utf-8', errors='ignore')
                        # index = int(parts[3])
                        # size = int(parts[4])
                        chunk_data = parts[5]
                        
                        if filename in uploading_files:
                            uploading_files[filename].write(chunk_data)
                    else:
                        pass # Corrupted chunk maybe
                        
                elif cmd == 'END_FILE':
                    # DATA|END_FILE|filename
                    filename = parts[2].decode('utf-8', errors='ignore')
                    if filename in uploading_files:
                        uploading_files[filename].close()
                        del uploading_files[filename]
                        send_msg(conn, f"CTRL|UPLOAD_SUCCESS|{filename}")
                        server_log("INFO", f"file {filename} uploaded by {username}")

    except Exception as e:
        server_log("ERROR", f"{addr} disconnected with error: {e}")
    finally:
        for fname, f_handle in uploading_files.items():
            try:
                f_handle.close()
                if current_user:
                    filepath = os.path.join(BASE_DIR, current_user, fname)
                    if os.path.exists(filepath):
                        os.remove(filepath)
                        server_log("INFO", f"Deleted incomplete file {fname} for {current_user}")
            except Exception as e:
                server_log("ERROR", f"Failed to delete incomplete file: {e}")
                
        if conn in client_states:
            uname = client_states[conn]
            if uname in online_users:
                del online_users[uname]
            del client_states[conn]
        conn.close()

def send_file_chunks(conn, recipient, sender, filename):
    f_path = os.path.join(BASE_DIR, sender, filename)
    if not os.path.exists(f_path):
        send_msg(conn, "CTRL|ERROR|file not found on server")
        return
        
    try:
        with open(f_path, 'rb') as f:
            chunk_index = 1
            while True:
                data = f.read(1024)
                if not data:
                    break
                # DATA|FILE_CHUNK|filename|chunk_index|chunk_size|bytes
                header = f"DATA|FILE_CHUNK|{filename}|{chunk_index}|{len(data)}|".encode('utf-8')
                msg = header + data
                # Send raw message
                msg = struct.pack('!I', len(msg)) + msg
                conn.sendall(msg)
                chunk_index += 1
                
        # Send END_FILE
        send_msg(conn, f"DATA|END_FILE|{filename}")
    except Exception as e:
        print(f"Error sending file to {recipient}: {e}")

def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen(10)
    print(f"[STARTING] Server is listening on {HOST}:{PORT}")
    
    while True:
        conn, addr = server.accept()
        thread = threading.Thread(target=handle_client, args=(conn, addr))
        thread.start()
        print(f"[ACTIVE CONNECTIONS] {threading.active_count() - 1}")

if __name__ == "__main__":
    main()
