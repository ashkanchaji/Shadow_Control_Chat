from fileinput import filename
import socket
import threading
import struct
import os
import sys

HOST = '127.0.0.1'
PORT = 8888
CLIENT_DIR = 'client_files'

if not os.path.exists(CLIENT_DIR):
    os.makedirs(CLIENT_DIR)

downloading_files = {} # filename -> dict of {handle, size, received}
pending_uploads = set()
active_uploads = set()
pending_shares = {} # filename -> sender

def print_msg(msg):
    sys.stdout.write('\r\033[K' + msg + '\n>> ')
    sys.stdout.flush()

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

def encrypt_msg(msg):
    return ''.join(chr(ord(c) + 3) for c in msg)

def decrypt_msg(msg):
    return ''.join(chr(ord(c) - 3) for c in msg)

def receive_thread(sock):
    while True:
        msgBytes = recv_msg(sock)
        if not msgBytes:
            if active_uploads or downloading_files:
                print_msg("[ERROR connection lost during transfer]")
            else:
                print_msg("[DISCONNECTED] Server connection closed.")
            os._exit(0)
            
        parts = msgBytes.split(b'|', 5)
        if not parts:
            continue
            
        msg_type = parts[0].decode('utf-8', errors='ignore')
        cmd = parts[1].decode('utf-8', errors='ignore') if len(parts) > 1 else ""
        
        if msg_type == 'CTRL':
            args = [p.decode('utf-8', errors='ignore') for p in parts[2:]]
            
            if cmd == 'SHARE_REQUEST':
                sender, filename = args[0], args[1]
                pending_shares[filename] = sender
                print_msg(f"[SHARE REQUEST] {sender} wants to share '{filename}' with you.\nType 'ACCEPT {filename}' or 'REJECT {filename}'")
                
            elif cmd == 'SHARE_ACCEPTED':
                print_msg(f"[SERVER SHARE_ACCEPTED] {args[0]}")
                if len(args) == 1:
                    filename = args[0]
                    f_path = os.path.join(CLIENT_DIR, filename)
                    downloading_files[filename] = {'handle': open(f_path, 'wb'), 'size': 0, 'received': 0}
                    
            elif cmd == 'SHARE_REJECTED':
                print_msg(f"[SERVER SHARE_REJECTED] {' '.join(args)}")
                
            elif cmd == 'INFO':
                print_msg(f"[SERVER INFO] {' '.join(args)}")
                
            elif cmd == 'UPLOAD_ACK':
                filename = args[0]
                if filename in pending_uploads:
                    pending_uploads.remove(filename)
                    active_uploads.add(filename)
                    threading.Thread(target=upload_file_chunks, args=(sock, filename), daemon=True).start()
                
            elif cmd == 'UPLOAD_SUCCESS':
                print_msg(f"[INFO] Upload of {args[0]} completed successfully.")
                
            elif cmd in ['OK', 'ERROR', 'FILE_LIST', 'USER_LIST', 'AUTH_SUCCESS', 'AUTH_FAILED']:
                print_msg(f"[SERVER {cmd}] {' '.join(args)}")
                
        elif msg_type == 'DATA':
            if cmd == 'CHAT_FROM':
                rest = msgBytes.split(b'|', 3)
                if len(rest) >= 4:
                    sender = rest[2].decode('utf-8', errors='ignore')
                    msg = rest[3].decode('utf-8', errors='ignore')
                    decrypted_msg = decrypt_msg(msg)
                    print_msg(f"[CHAT from {sender}]: {decrypted_msg}")
                    
            elif cmd == 'FILE_CHUNK':
                if len(parts) >= 6:
                    filename = parts[2].decode('utf-8', errors='ignore')
                    chunk_index = parts[3].decode('utf-8', errors='ignore')
                    chunk_data = parts[5]
                    
                    if filename in downloading_files:
                        downloading_files[filename]['handle'].write(chunk_data)
                        downloading_files[filename]['received'] += len(chunk_data)
                        received_kb = downloading_files[filename]['received'] / 1024
                        
                        sys.stdout.write(f"\r\033[K[INFO] Downloading {filename}: {received_kb:.1f} KB received")
                        sys.stdout.flush()
            elif cmd == 'END_FILE':
                filename = parts[2].decode('utf-8', errors='ignore')
                if filename in downloading_files:
                    downloading_files[filename]['handle'].close()
                    del downloading_files[filename]
                    
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    print_msg(f"[DOWNLOAD SUCCESS] {filename} saved in {CLIENT_DIR}/.")

def upload_file_chunks(sock, filename):
    f_path = os.path.join(CLIENT_DIR, filename)
    filesize = os.path.getsize(f_path)
    try:
        with open(f_path, 'rb') as f:
            chunk_index = 1
            sent_bytes = 0
            while True:
                data = f.read(1024)
                if not data:
                    break
                header = f"DATA|FILE_CHUNK|{filename}|{chunk_index}|{len(data)}|".encode('utf-8')
                msg = header + data
                msg = struct.pack('!I', len(msg)) + msg
                sock.sendall(msg)
                
                sent_bytes += len(data)
                pct = int((sent_bytes / filesize) * 100)

                sys.stdout.write(f"\r\033[K[INFO] Uploading {filename}: {pct}%")
                sys.stdout.flush()
                
                chunk_index += 1
                
        sys.stdout.write("\n>> ")
        sys.stdout.flush()
        
        send_msg(sock, f"DATA|END_FILE|{filename}")
        print_msg(f"END_FILE {filename}")
    except Exception as e:
        print_msg(f"[ERROR] Failed to upload: {e}")
    finally:
        if filename in active_uploads:
            active_uploads.remove(filename)

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((HOST, PORT))
    except Exception as e:
        print(f"Could not connect to server: {e}")
        sys.exit(1)
        
    print("Connected to server.")
    
    t = threading.Thread(target=receive_thread, args=(sock,), daemon=True)
    t.start()
    
    while True:
        try:
            user_input = input(">> ").strip()
            if not user_input:
                continue
                
            parts = user_input.split(" ")
            cmd = parts[0].upper()
            
            if cmd == 'REGISTER':
                if len(parts) == 3:
                    send_msg(sock, f"CTRL|REGISTER|{parts[1]}|{parts[2]}")
                else:
                    print_msg("Usage: REGISTER <username> <password>")
                    
            elif cmd == 'LOGIN':
                if len(parts) == 3:
                    send_msg(sock, f"CTRL|LOGIN|{parts[1]}|{parts[2]}")
                else:
                    print_msg("Usage: LOGIN <username> <password>")
                    
            elif cmd == 'LOGOUT':
                send_msg(sock, "CTRL|LOGOUT")
                
            elif cmd == 'UPLOAD':
                if len(parts) == 2:
                    filename = parts[1]
                    f_path = os.path.join(CLIENT_DIR, filename)
                    if not os.path.exists(f_path):
                        print_msg(f"[ERROR] File {filename} not found in {CLIENT_DIR}/.")
                    else:
                        filesize = os.path.getsize(f_path)
                        pending_uploads.add(filename)
                        send_msg(sock, f"CTRL|UPLOAD|{filename}|{filesize}")
                else:
                    print_msg("Usage: UPLOAD <filename>")
                    
            elif cmd == 'LIST_FILES':
                send_msg(sock, "CTRL|LIST_FILES")
                
            elif cmd == 'LIST_USERS':
                send_msg(sock, "CTRL|LIST_USERS")
                
            elif cmd == 'SHARE':
                if len(parts) == 3:
                    send_msg(sock, f"CTRL|SHARE|{parts[1]}|{parts[2]}")
                else:
                    print_msg("Usage: SHARE <filename> <target_user>")
                    
            elif cmd == 'ACCEPT':
                if len(parts) == 2:
                    filename = parts[1]
                    if filename in pending_shares:
                        sender = pending_shares[filename]
                        send_msg(sock, f"CTRL|ACCEPT_FILE|{filename}|{sender}")
                    else:
                        print_msg("No pending share request for this file.")
                else:
                    print_msg("Usage: ACCEPT <filename>")
                    
            elif cmd == 'REJECT':
                if len(parts) == 2:
                    filename = parts[1]
                    if filename in pending_shares:
                        sender = pending_shares.pop(filename)
                        send_msg(sock, f"CTRL|REJECT_FILE|{filename}|{sender}")
                    else:
                        print_msg("No pending share request for this file.")
                else:
                    print_msg("Usage: REJECT <filename>")
                    
            elif cmd == 'CHAT':
                if len(parts) >= 3:
                    target = parts[1]
                    message = " ".join(parts[2:])
                    encrypted_msg = encrypt_msg(message)
                    send_msg(sock, f"DATA|CHAT|{target}|{encrypted_msg}")
                else:
                    print_msg("Usage: CHAT <target_user> <message>")
                    
            elif cmd == 'EXIT':
                send_msg(sock, "CTRL|EXIT")
                break
            else:
                print_msg("Unknown command. Available commands:\nREGISTER <user> <pass> | LOGIN <user> <pass> | LOGOUT | UPLOAD <file> | LIST_FILES | LIST_USERS | SHARE <file> <user> | ACCEPT <file> | REJECT <file> | CHAT <user> <msg> | EXIT")
                
        except KeyboardInterrupt:
            if active_uploads or downloading_files:
                sys.stdout.write("\n\033[K[ERROR connection lost during transfer]\n")
                sys.stdout.flush()
            send_msg(sock, "CTRL|EXIT")
            sock.close()
            os._exit(0)
            
    sock.close()

if __name__ == "__main__":
    main()
